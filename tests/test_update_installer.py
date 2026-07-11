import hashlib
import json
import os
from pathlib import Path

import pytest
from neural_extractor_v3.core import update_installer as installer_module
from neural_extractor_v3.core.update_installer import (
    INSTALL_LOCK_FILENAME,
    RESULT_FILENAME,
    STARTUP_MARKER_FILENAME,
    TRANSACTION_FILENAME,
    InstallationCapability,
    UpdateApplier,
    UpdateTransaction,
    assess_installation_capability,
    load_update_transaction,
    prepare_and_launch_update,
    write_startup_confirmation,
)
from neural_extractor_v3.core.update_manifest import MIN_UPDATE_SIZE_BYTES, UpdateManifest
from neural_extractor_v3.core.updater import UpdateError, UpdateInfo

OLD_BYTES = b"O" * MIN_UPDATE_SIZE_BYTES
NEW_BYTES = b"N" * MIN_UPDATE_SIZE_BYTES
VERSION = "3.0.3"
TOKEN = "A" * 48


class FakeProcess:
    def __init__(self, pid=9001, poll_result=None):
        self.pid = pid
        self.poll_result = poll_result
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.poll_result

    def terminate(self):
        self.terminated = True
        self.poll_result = 0

    def kill(self):
        self.killed = True
        self.poll_result = -9

    def wait(self, timeout=None):
        return self.poll_result or 0


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        self.value += 0.1
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_manifest(version=VERSION, content=NEW_BYTES):
    return UpdateManifest(
        schema_version=1,
        application_name="Neural Extractor V3",
        release_version=version,
        asset_filename=f"NeuralExtractorV3-{version}-windows-x64.exe",
        asset_sha256=sha256(content),
        asset_size=len(content),
        platform="windows",
        architecture="x64",
        channel="stable",
        minimum_updater_version="3.0.2",
    )


def make_info(manifest):
    return UpdateInfo(
        version=manifest.release_version,
        tag_name=f"v{manifest.release_version}",
        name=f"Neural Extractor V3 v{manifest.release_version}",
        html_url="https://github.com/AegisAI-Dev/NeuralExtractor/releases/tag/v3.0.3",
        download_url=(
            "https://github.com/AegisAI-Dev/NeuralExtractor/releases/download/v3.0.3/"
            + manifest.asset_filename
        ),
        manifest_url=(
            "https://github.com/AegisAI-Dev/NeuralExtractor/releases/download/v3.0.3/"
            "NeuralExtractorV3-3.0.3-manifest.json"
        ),
        checksum_url="",
        published_at="",
        body="",
        download_size=manifest.asset_size,
        sha256=manifest.asset_sha256,
        manifest=manifest,
    )


def write_transaction(tmp_path: Path, *, staged_bytes=NEW_BYTES):
    root = (tmp_path / "updates").resolve()
    target = (tmp_path / "install" / "NeuralExtractorV3.exe").resolve()
    target.parent.mkdir(parents=True)
    target.write_bytes(OLD_BYTES)
    staged = (root / VERSION / "package" / f"NeuralExtractorV3-{VERSION}-windows-x64.exe")
    staged.parent.mkdir(parents=True)
    staged.write_bytes(staged_bytes)
    transaction_dir = root / VERSION / TOKEN
    transaction_dir.mkdir(parents=True)
    transaction_path = transaction_dir / TRANSACTION_FILENAME
    marker = transaction_dir / STARTUP_MARKER_FILENAME
    backup = target.parent / f".{target.name}.{TOKEN}.backup"
    transaction = UpdateTransaction(
        schema_version=1,
        token=TOKEN,
        expected_version=VERSION,
        expected_sha256=sha256(NEW_BYTES),
        expected_size=len(NEW_BYTES),
        original_sha256=sha256(OLD_BYTES),
        parent_pid=4242,
        target_executable=str(target),
        staged_executable=str(staged),
        backup_executable=str(backup),
        startup_marker=str(marker),
        created_at="2026-07-12T12:00:00+00:00",
    )
    installer_module._atomic_write_json(transaction_path, transaction.to_dict())
    installer_module._atomic_write_json(
        root / INSTALL_LOCK_FILENAME,
        {
            "token": TOKEN,
            "owner_pid": transaction.parent_pid,
            "transaction": str(transaction_path),
        },
    )
    return root, transaction_path, transaction, target, staged, backup, marker


def make_applier(tmp_path, transaction_path, root, launcher, **overrides):
    clock = overrides.pop("clock", FakeClock())
    return UpdateApplier(
        transaction_path,
        updates_root=root,
        temporary_root=tmp_path / "not-the-system-temp",
        process_exists=overrides.pop("process_exists", lambda _pid: False),
        process_launcher=launcher,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        startup_timeout=overrides.pop("startup_timeout", 2),
        parent_exit_timeout=overrides.pop("parent_exit_timeout", 2),
        **overrides,
    )


def test_source_mode_and_temporary_locations_fall_back_to_manual_install(tmp_path):
    manifest = make_manifest()
    target = tmp_path / "NeuralExtractorV3.exe"
    target.write_bytes(OLD_BYTES)

    source = assess_installation_capability(manifest, target_executable=target, frozen=False)
    temporary = assess_installation_capability(
        manifest,
        target_executable=target,
        frozen=True,
        temporary_root=tmp_path,
        updates_root=tmp_path / "updates",
    )

    assert isinstance(source, InstallationCapability)
    assert not source.available
    assert "packaged" in source.reason
    assert not temporary.available
    assert "temporary" in temporary.reason


def test_capability_reports_insufficient_disk_space(tmp_path, monkeypatch):
    manifest = make_manifest()
    target = tmp_path / "install" / "NeuralExtractorV3.exe"
    target.parent.mkdir()
    target.write_bytes(OLD_BYTES)
    monkeypatch.setattr(
        installer_module.shutil,
        "disk_usage",
        lambda _path: type("DiskUsage", (), {"free": 0})(),
    )

    capability = assess_installation_capability(
        manifest,
        target_executable=target,
        frozen=True,
        updates_root=tmp_path / "updates",
        temporary_root=tmp_path / "not-the-system-temp",
    )

    assert not capability.available
    assert capability.code == "insufficient_disk_space"


def test_capability_combines_same_volume_staging_backup_and_helper_space(
    tmp_path,
    monkeypatch,
):
    manifest = make_manifest()
    target = tmp_path / "install" / "NeuralExtractorV3.exe"
    target.parent.mkdir()
    target.write_bytes(OLD_BYTES)
    free_bytes = installer_module.DISK_SPACE_MARGIN_BYTES + 3 * MIN_UPDATE_SIZE_BYTES
    monkeypatch.setattr(
        installer_module.shutil,
        "disk_usage",
        lambda _path: type("DiskUsage", (), {"free": free_bytes})(),
    )

    capability = assess_installation_capability(
        manifest,
        target_executable=target,
        frozen=True,
        updates_root=tmp_path / "updates",
        temporary_root=tmp_path / "not-the-system-temp",
    )

    assert not capability.available
    assert capability.code == "insufficient_disk_space"


def test_prepare_copies_verified_helper_and_launches_only_private_mode(tmp_path):
    manifest = make_manifest()
    info = make_info(manifest)
    root = tmp_path / "updates"
    target = tmp_path / "install" / "NeuralExtractorV3.exe"
    target.parent.mkdir()
    target.write_bytes(OLD_BYTES)
    staged = root / VERSION / "package" / manifest.asset_filename
    staged.parent.mkdir(parents=True)
    staged.write_bytes(NEW_BYTES)
    launches = []

    def launch(arguments):
        launches.append(arguments)
        return FakeProcess(pid=7777)

    prepared = prepare_and_launch_update(
        info,
        staged,
        parent_pid=4242,
        target_executable=target,
        frozen=True,
        updates_root=root,
        temporary_root=tmp_path / "not-the-system-temp",
        helper_root=tmp_path / "helper",
        detached_launcher=launch,
    )

    assert prepared.helper_pid == 7777
    assert launches == [
        [
            str((tmp_path / "helper" / "NeuralExtractorV3-Updater.exe").resolve()),
            "--apply-update",
            str(prepared.transaction_path),
        ]
    ]
    assert (tmp_path / "helper" / "NeuralExtractorV3-Updater.exe").read_bytes() == OLD_BYTES
    assert prepared.transaction_path.exists()
    lock = json.loads((root / INSTALL_LOCK_FILENAME).read_text(encoding="utf-8"))
    assert lock["owner_pid"] == 7777


def test_successful_apply_waits_backs_up_replaces_restarts_and_confirms(tmp_path):
    root, tx_path, transaction, target, staged, backup, marker = write_transaction(tmp_path)
    launches = []
    process_checks = iter([True, True, False])

    def launcher(arguments):
        launches.append(arguments)
        if "--post-update-token" in arguments:
            write_startup_confirmation(
                TOKEN,
                marker,
                version=VERSION,
                updates_root=root,
            )
        return FakeProcess()

    applier = make_applier(
        tmp_path,
        tx_path,
        root,
        launcher,
        process_exists=lambda _pid: next(process_checks),
    )

    result = applier.apply()

    assert result == 0
    assert target.read_bytes() == NEW_BYTES
    assert not backup.exists()
    assert not staged.exists()
    assert not marker.exists()
    assert launches[0][0] == str(target)
    assert "--post-update-token" in launches[0]
    payload = json.loads((tx_path.parent / RESULT_FILENAME).read_text())
    assert payload["status"] == "success"


def test_success_record_failure_keeps_verified_backup(tmp_path, monkeypatch):
    root, tx_path, _transaction, target, _staged, backup, marker = write_transaction(tmp_path)

    def launcher(_arguments):
        write_startup_confirmation(TOKEN, marker, version=VERSION, updates_root=root)
        return FakeProcess()

    def fail_result(_status, _message):
        raise OSError("result blocked")

    applier = make_applier(tmp_path, tx_path, root, launcher)
    monkeypatch.setattr(applier, "_write_result", fail_result)

    assert applier.apply() == 0
    assert target.read_bytes() == NEW_BYTES
    assert backup.exists()


def test_backup_exists_before_replacement_and_transient_lock_is_retried(tmp_path):
    root, tx_path, _transaction, target, _staged, backup, marker = write_transaction(tmp_path)
    replace_calls = []

    def replace_with_locks(source, destination):
        replace_calls.append((Path(source), Path(destination)))
        assert backup.exists()
        if len(replace_calls) < 3:
            raise PermissionError("transient antivirus lock")
        os.replace(source, destination)

    def launcher(arguments):
        write_startup_confirmation(TOKEN, marker, version=VERSION, updates_root=root)
        return FakeProcess()

    applier = make_applier(
        tmp_path,
        tx_path,
        root,
        launcher,
        replace_file=replace_with_locks,
    )

    assert applier.apply() == 0
    assert len(replace_calls) == 3
    assert target.read_bytes() == NEW_BYTES


@pytest.mark.parametrize("failure_mode", ["timeout", "early_exit", "launch_failure"])
def test_startup_failures_restore_and_relaunch_previous_version(tmp_path, failure_mode):
    root, tx_path, _transaction, target, _staged, backup, _marker = write_transaction(tmp_path)
    launches = []

    def launcher(arguments):
        launches.append(arguments)
        if len(launches) == 1:
            if failure_mode == "launch_failure":
                raise OSError("launch blocked")
            return FakeProcess(poll_result=1 if failure_mode == "early_exit" else None)
        return FakeProcess(pid=9002)

    applier = make_applier(
        tmp_path,
        tx_path,
        root,
        launcher,
        startup_timeout=0.5,
    )

    result = applier.apply()

    assert result == 3
    assert target.read_bytes() == OLD_BYTES
    assert backup.exists()
    assert "--update-rollback-status" in launches[-1]
    payload = json.loads((tx_path.parent / RESULT_FILENAME).read_text())
    assert payload["status"] == "rollback_succeeded"


def test_checksum_mismatch_never_replaces_target(tmp_path):
    root, tx_path, _transaction, target, _staged, _backup, _marker = write_transaction(
        tmp_path,
        staged_bytes=b"X" * len(NEW_BYTES),
    )
    launches = []

    applier = make_applier(
        tmp_path,
        tx_path,
        root,
        lambda arguments: launches.append(arguments) or FakeProcess(),
    )

    assert applier.apply() == 2
    assert target.read_bytes() == OLD_BYTES
    assert launches and "--update-rollback-status" in launches[-1]


def test_pre_install_failure_waits_for_closing_parent_then_relaunches_original(tmp_path):
    root, tx_path, _transaction, target, _staged, _backup, _marker = write_transaction(
        tmp_path,
        staged_bytes=b"X" * len(NEW_BYTES),
    )
    process_checks = iter([True, True, False])
    launches = []
    applier = make_applier(
        tmp_path,
        tx_path,
        root,
        lambda arguments: launches.append(arguments) or FakeProcess(),
        process_exists=lambda _pid: next(process_checks),
    )

    assert applier.apply() == 2
    assert target.read_bytes() == OLD_BYTES
    assert launches and "--update-rollback-status" in launches[-1]


def test_backup_failure_preserves_and_relaunches_original(tmp_path, monkeypatch):
    root, tx_path, _transaction, target, _staged, _backup, _marker = write_transaction(tmp_path)
    original_copy = installer_module._copy_file_sync
    launches = []

    def fail_backup(source, destination):
        if str(destination).endswith(".backup"):
            raise PermissionError("backup blocked")
        return original_copy(source, destination)

    monkeypatch.setattr(installer_module, "_copy_file_sync", fail_backup)
    applier = make_applier(
        tmp_path,
        tx_path,
        root,
        lambda arguments: launches.append(arguments) or FakeProcess(),
    )

    assert applier.apply() == 2
    assert target.read_bytes() == OLD_BYTES
    assert launches and "--update-rollback-status" in launches[-1]


def test_parent_exit_timeout_does_not_launch_a_duplicate_original(tmp_path):
    root, tx_path, _transaction, target, _staged, _backup, _marker = write_transaction(tmp_path)
    launches = []
    applier = make_applier(
        tmp_path,
        tx_path,
        root,
        lambda arguments: launches.append(arguments) or FakeProcess(),
        process_exists=lambda _pid: True,
        parent_exit_timeout=0.5,
    )

    assert applier.apply() == 2
    assert target.read_bytes() == OLD_BYTES
    assert launches == []


def test_rollback_failure_keeps_backup_and_reports_recovery_path(tmp_path):
    root, tx_path, _transaction, target, _staged, backup, _marker = write_transaction(tmp_path)
    messages = []

    def replace_then_block_rollback(source, destination):
        if str(source).endswith(".rollback"):
            raise PermissionError("rollback locked")
        os.replace(source, destination)

    applier = make_applier(
        tmp_path,
        tx_path,
        root,
        lambda _arguments: FakeProcess(poll_result=1),
        replace_file=replace_then_block_rollback,
        message_callback=lambda title, message: messages.append((title, message)),
    )

    assert applier.apply() == 4
    assert backup.exists()
    assert target.read_bytes() == NEW_BYTES
    assert messages and str(backup) in messages[0][1]
    payload = json.loads((tx_path.parent / RESULT_FILENAME).read_text())
    assert payload["status"] == "rollback_failed"


def test_concurrent_updater_lock_is_rejected(tmp_path):
    root, tx_path, _transaction, _target, _staged, _backup, _marker = write_transaction(tmp_path)
    installer_module._atomic_write_json(
        root / INSTALL_LOCK_FILENAME,
        {"token": "B" * 48, "owner_pid": 9999, "transaction": str(tx_path)},
    )
    applier = make_applier(tmp_path, tx_path, root, lambda _arguments: FakeProcess())

    with pytest.raises(UpdateError) as exc_info:
        applier.apply()

    assert exc_info.value.code == "concurrent_update"


def test_concurrent_updater_with_same_token_but_wrong_owner_is_rejected(tmp_path):
    root, tx_path, _transaction, _target, _staged, _backup, _marker = write_transaction(tmp_path)
    installer_module._atomic_write_json(
        root / INSTALL_LOCK_FILENAME,
        {"token": TOKEN, "owner_pid": 9999, "transaction": str(tx_path)},
    )
    applier = make_applier(tmp_path, tx_path, root, lambda _arguments: FakeProcess())

    with pytest.raises(UpdateError) as exc_info:
        applier.apply()

    assert exc_info.value.code == "concurrent_update"


def test_transaction_paths_and_startup_tokens_cannot_escape_update_root(tmp_path):
    root, tx_path, transaction, _target, _staged, _backup, marker = write_transaction(tmp_path)
    payload = transaction.to_dict()
    payload["target_executable"] = str(root / "NeuralExtractorV3.exe")
    installer_module._atomic_write_json(tx_path, payload)

    with pytest.raises(UpdateError):
        load_update_transaction(
            tx_path,
            updates_root=root,
            temporary_root=tmp_path / "not-the-system-temp",
        )
    with pytest.raises(UpdateError):
        write_startup_confirmation(
            "B" * 48,
            marker,
            version=VERSION,
            updates_root=root,
        )


def test_transaction_requires_exact_package_path_and_marker_version(tmp_path):
    root, tx_path, transaction, _target, staged, _backup, _marker = write_transaction(tmp_path)
    alternate = root / VERSION / "alternate" / staged.name
    alternate.parent.mkdir(parents=True)
    alternate.write_bytes(NEW_BYTES)
    payload = transaction.to_dict()
    payload["staged_executable"] = str(alternate)
    installer_module._atomic_write_json(tx_path, payload)

    with pytest.raises(UpdateError):
        load_update_transaction(
            tx_path,
            updates_root=root,
            temporary_root=tmp_path / "not-the-system-temp",
        )

    wrong_version_marker = root / "8.8.8" / TOKEN / STARTUP_MARKER_FILENAME
    with pytest.raises(UpdateError):
        write_startup_confirmation(
            TOKEN,
            wrong_version_marker,
            version=VERSION,
            updates_root=root,
        )


def test_installer_source_has_no_shell_true_uac_or_external_shells():
    source = Path(installer_module.__file__).read_text(encoding="utf-8")
    lowered = source.lower()

    assert "shell=true" not in lowered
    assert '"runas"' not in lowered
    assert "powershell" not in lowered
    assert "cmd.exe" not in lowered
