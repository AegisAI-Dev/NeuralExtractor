"""Run controlled Windows smokes against two packaged Neural Extractor EXEs.

The script works only inside a unique caller-provided workspace. It never uses
or replaces an installed Neural Extractor executable.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from neural_extractor_v3.config import APP_NAME, VERSION
from neural_extractor_v3.core.process_control import process_creation_identity
from neural_extractor_v3.core.update_installer import (
    RESULT_FILENAME,
    STARTUP_MARKER_FILENAME,
    TRANSACTION_FILENAME,
    UpdateTransaction,
    prepare_and_launch_update,
)
from neural_extractor_v3.core.update_manifest import (
    UpdateManifest,
    expected_exe_filename,
    sha256_file,
)
from neural_extractor_v3.core.update_ownership import (
    OWNERSHIP_SCHEMA_VERSION,
    OwnershipRecord,
    OwnershipRole,
    TransactionState,
    UpdateOwnershipManager,
    new_transaction_id,
    normalized_target_identity,
)
from neural_extractor_v3.core.updater import UpdateInfo

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class SmokeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Scenario:
    root: Path
    local_app_data: Path
    updates_root: Path
    helper_root: Path
    target: Path
    staged: Path
    transaction_id: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeError(message)


def _environment(
    scenario: Scenario,
    *,
    startup_timeout_seconds: int | None = None,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(scenario.local_app_data)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment.pop("NEURAL_EXTRACTOR_UPDATER_STARTUP_TIMEOUT_SECONDS", None)
    if startup_timeout_seconds is not None:
        environment["NEURAL_EXTRACTOR_UPDATER_STARTUP_TIMEOUT_SECONDS"] = str(
            startup_timeout_seconds
        )
    return environment


def _scenario(base: Path, name: str, target_package: Path, staged_package: Path) -> Scenario:
    root = (base / name).resolve()
    local_app_data = root / "local-app-data"
    updates_root = local_app_data / "NeuralExtractorV3" / "updates"
    helper_root = local_app_data / "NeuralExtractorV3" / "updater-helper"
    target = root / "install" / "NeuralExtractorV3.exe"
    transaction_id = new_transaction_id()
    staged = (
        updates_root
        / VERSION
        / transaction_id
        / "package"
        / expected_exe_filename(VERSION)
    )
    target.parent.mkdir(parents=True)
    staged.parent.mkdir(parents=True)
    shutil.copy2(target_package, target)
    shutil.copy2(staged_package, staged)
    return Scenario(
        root,
        local_app_data,
        updates_root,
        helper_root,
        target,
        staged,
        transaction_id,
    )


def _update_info(staged: Path) -> UpdateInfo:
    size = staged.stat().st_size
    digest = sha256_file(staged)
    manifest = UpdateManifest(
        schema_version=1,
        application_name=APP_NAME,
        release_version=VERSION,
        asset_filename=expected_exe_filename(VERSION),
        asset_sha256=digest,
        asset_size=size,
        platform="windows",
        architecture="x64",
        channel="stable",
        minimum_updater_version=VERSION,
    )
    base_url = f"https://github.com/AegisAI-Dev/NeuralExtractor/releases/download/v{VERSION}"
    return UpdateInfo(
        version=VERSION,
        tag_name=f"v{VERSION}",
        name=f"Neural Extractor V3 v{VERSION}",
        html_url=f"https://github.com/AegisAI-Dev/NeuralExtractor/releases/tag/v{VERSION}",
        download_url=f"{base_url}/{manifest.asset_filename}",
        manifest_url=f"{base_url}/NeuralExtractorV3-{VERSION}-manifest.json",
        checksum_url="",
        published_at="",
        body="packaged updater smoke",
        download_size=size,
        sha256=digest,
        manifest=manifest,
    )


def _start_parent(environment: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - fixed interpreter and controlled script
        [sys.executable, "-c", "import time; time.sleep(300)"],
        shell=False,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
        env=environment,
    )


def _stop_parent(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _wait_for_state(transaction_path: Path, states: set[str], timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError, json.JSONDecodeError):
            latest = _read_json(transaction_path)
            if latest.get("state") in states:
                return latest
        time.sleep(0.2)
    raise SmokeError(
        f"Transaction did not reach {sorted(states)}; last state={latest.get('state')!r}"
    )


def _wait_for_text(path: Path, text: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError, UnicodeError):
            if text in path.read_text(encoding="utf-8"):
                return
        time.sleep(0.2)
    raise SmokeError(f"Timed out waiting for {text!r} in {path}")


def _wait_for_path(path: Path, *, exists: bool, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() is exists:
            return
        time.sleep(0.1)
    expectation = "appear" if exists else "be removed"
    raise SmokeError(f"Timed out waiting for {label} to {expectation}: {path}")


def _wait_for_terminal_cleanup(
    scenario: Scenario,
    transaction_path: Path,
    helper_path: Path,
    *,
    state: TransactionState,
    timeout: float,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError, json.JSONDecodeError):
            latest = _read_json(transaction_path)
            backup = Path(str(latest.get("backup_executable") or ""))
            marker = Path(str(latest.get("startup_marker") or ""))
            ownership = UpdateOwnershipManager(scenario.updates_root).read(scenario.target)
            if (
                latest.get("state") == state.value
                and not backup.exists()
                and not marker.exists()
                and ownership is None
                and not helper_path.exists()
                and (
                    state != TransactionState.CONFIRMED or not scenario.staged.exists()
                )
            ):
                return latest
        time.sleep(0.2)
    raise SmokeError(
        f"Terminal {state.value} cleanup did not finish; "
        f"last state={latest.get('state')!r}"
    )


def _normalize(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _processes_for_executable(executable: Path) -> list[tuple[int, str]]:
    if os.name != "nt":
        return []
    from ctypes import wintypes

    class ProcessEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    create_snapshot.restype = wintypes.HANDLE
    process_first = kernel32.Process32FirstW
    process_first.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32)]
    process_first.restype = wintypes.BOOL
    process_next = kernel32.Process32NextW
    process_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32)]
    process_next.restype = wintypes.BOOL
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    query_image = kernel32.QueryFullProcessImageNameW
    query_image.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    query_image.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    snapshot = create_snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        raise SmokeError(f"Windows process enumeration failed with error {error}")
    expected = _normalize(executable)
    matches: list[tuple[int, str]] = []
    try:
        entry = ProcessEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = process_first(snapshot, ctypes.byref(entry))
        while has_entry:
            pid = int(entry.th32ProcessID)
            handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                try:
                    length = wintypes.DWORD(32_768)
                    buffer = ctypes.create_unicode_buffer(length.value)
                    if query_image(handle, 0, buffer, ctypes.byref(length)) and _normalize(
                        buffer.value
                    ) == expected:
                        identity = process_creation_identity(pid)
                        if identity is not None:
                            matches.append((pid, identity))
                finally:
                    close_handle(handle)
            has_entry = process_next(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error not in {0, 18}:  # ERROR_NO_MORE_FILES is the successful end of enumeration.
            raise SmokeError(f"Windows process enumeration ended with error {error}")
    finally:
        close_handle(snapshot)
    return matches


def _terminate_exact_executable(executable: Path) -> None:
    taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
    for pid, expected_identity in _processes_for_executable(executable):
        try:
            current_identity = process_creation_identity(pid)
        except (OSError, PermissionError) as exc:
            raise SmokeError(f"Could not revalidate controlled process {pid}") from exc
        if current_identity != expected_identity:
            continue
        subprocess.run(  # noqa: S603 - exact enumerated PID and fixed system executable
            [str(taskkill), "/PID", str(pid), "/T", "/F"],
            shell=False,
            check=False,
            capture_output=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )


def _wait_for_no_process(executable: Path, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _processes_for_executable(executable):
            return
        time.sleep(0.2)
    raise SmokeError(f"Processes remain for controlled executable {executable}")


def _write_stale_ownership(scenario: Scenario) -> None:
    manager = UpdateOwnershipManager(scenario.updates_root)
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds")
    record = OwnershipRecord(
        schema_version=OWNERSHIP_SCHEMA_VERSION,
        transaction_id=new_transaction_id(),
        target_identity=normalized_target_identity(scenario.target),
        target_name=scenario.target.name,
        owner_pid=2_147_000_000,
        owner_process_created="a" * 64,
        role=OwnershipRole.INSTALLATION.value,
        state=TransactionState.WAITING_FOR_PARENT_EXIT.value,
        created_at=timestamp,
        heartbeat_at=timestamp,
    )
    path = manager.path_for_target(scenario.target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict()), encoding="utf-8")
    (scenario.updates_root / "install.lock").write_text(
        json.dumps(
            {
                "token": new_transaction_id(),
                "owner_pid": 2_147_000_001,
                "transaction": "legacy-stale-transaction",
            }
        ),
        encoding="utf-8",
    )


def _run_prepared_update(
    scenario: Scenario,
    *,
    create_stale_state: bool = False,
    startup_timeout_seconds: int | None = None,
) -> tuple[Path, Path]:
    environment = _environment(
        scenario,
        startup_timeout_seconds=startup_timeout_seconds,
    )
    old_environment = os.environ.copy()
    parent: subprocess.Popen[bytes] | None = None
    original_hash = sha256_file(scenario.target)
    try:
        os.environ.clear()
        os.environ.update(environment)
        parent = _start_parent(environment)
        parent_created = process_creation_identity(parent.pid)
        _require(parent_created is not None, "Fake GUI process identity was unavailable")
        if create_stale_state:
            _write_stale_ownership(scenario)
        prepared = prepare_and_launch_update(
            _update_info(scenario.staged),
            scenario.staged,
            parent_pid=parent.pid,
            transaction_id=scenario.transaction_id,
            target_executable=scenario.target,
            frozen=True,
            updates_root=scenario.updates_root,
            temporary_root=Path(tempfile.gettempdir()),
            helper_root=scenario.helper_root,
            handoff_timeout=45,
        )
        transaction_path = prepared.transaction_path
        helper_path = (
            scenario.helper_root
            / normalized_target_identity(scenario.target)
            / prepared.transaction_id
            / "NeuralExtractorV3-Updater.exe"
        )
        ownership = UpdateOwnershipManager(scenario.updates_root).read(scenario.target)
        _require(ownership is not None, "Packaged helper did not claim ownership")
        _require(ownership.owner_pid == prepared.helper_pid, "GUI did not report inner helper PID")
        _require(
            ownership.role == OwnershipRole.INSTALLATION.value,
            "Packaged helper claim did not become installation ownership",
        )
        transaction = _read_json(transaction_path)
        backup = Path(str(transaction["backup_executable"]))
        time.sleep(1.0)
        _require(parent.poll() is None, "Controlled GUI parent exited unexpectedly")
        _require(
            sha256_file(scenario.target) == original_hash,
            "Packaged helper replaced the target before its parent exited",
        )
        _require(not backup.exists(), "Packaged helper backed up before its parent exited")
        return transaction_path, helper_path
    finally:
        if parent is not None:
            _stop_parent(parent)
        os.environ.clear()
        os.environ.update(old_environment)


def _success_smoke(base: Path, old_package: Path, new_package: Path) -> dict[str, object]:
    scenario = _scenario(base, "success", old_package, new_package)
    old_hash = sha256_file(scenario.target)
    new_hash = sha256_file(scenario.staged)
    _require(old_hash != new_hash, "Two distinct packaged builds are required for replacement smoke")
    transaction_path, helper_path = _run_prepared_update(scenario, create_stale_state=True)
    prepared_transaction = _read_json(transaction_path)
    backup = Path(str(prepared_transaction["backup_executable"]))
    _wait_for_path(backup, exists=True, timeout=30, label="last known-good backup")
    _wait_for_state(
        transaction_path,
        {TransactionState.CONFIRMED.value},
        timeout=120,
    )
    transaction = _wait_for_terminal_cleanup(
        scenario,
        transaction_path,
        helper_path,
        state=TransactionState.CONFIRMED,
        timeout=45,
    )
    _require(sha256_file(scenario.target) == new_hash, "Confirmed update did not replace target")
    _require(not backup.exists(), "Confirmed update retained its backup")
    _require(
        UpdateOwnershipManager(scenario.updates_root).read(scenario.target) is None,
        "Confirmed update retained ownership",
    )
    _require(not helper_path.exists(), "Confirmed update retained the detached helper copy")
    _terminate_exact_executable(scenario.target)
    _wait_for_no_process(scenario.target)
    _wait_for_no_process(helper_path)
    log = scenario.updates_root / "updater.log"
    _require(log.exists(), "Packaged updater diagnostic log was not created")
    text = log.read_text(encoding="utf-8")
    _require("confirmed successfully" in text, "Packaged success was not logged")
    _require("Recovered stale" in text, "Stale updater state recovery was not logged")
    return {
        "state": transaction["state"],
        "target_sha256": new_hash,
        "stale_recovery": "pass",
        "ownership_cleanup": "pass",
        "helper_cleanup": "pass",
    }


def _build_nonconfirming_stage(scenario: Scenario) -> None:
    source = scenario.root / "nonconfirming-update-target.py"
    dist = scenario.root / "nonconfirming-dist"
    work = scenario.root / "nonconfirming-build"
    specs = scenario.root / "nonconfirming-spec"
    specs.mkdir(parents=True)
    source.write_text(
        "import time\n\ntime.sleep(300)\n",
        encoding="utf-8",
    )
    process = subprocess.run(  # noqa: S603 - fixed interpreter and controlled PyInstaller args
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--windowed",
            "--clean",
            "--noconfirm",
            "--name",
            "NeuralExtractorV3-NonConfirming",
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
            "--specpath",
            str(specs),
            str(source),
        ],
        shell=False,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
        creationflags=CREATE_NO_WINDOW,
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "")[-1000:]
        raise SmokeError(f"Controlled nonconfirming package build failed: {detail}")
    built = dist / "NeuralExtractorV3-NonConfirming.exe"
    _require(built.is_file(), "Controlled nonconfirming package was not produced")
    shutil.copy2(built, scenario.staged)


def _timeout_rollback_smoke(base: Path, old_package: Path) -> dict[str, object]:
    scenario = _scenario(base, "timeout-rollback", old_package, old_package)
    _build_nonconfirming_stage(scenario)
    old_hash = sha256_file(scenario.target)
    staged_hash = sha256_file(scenario.staged)
    _require(old_hash != staged_hash, "Timeout stage unexpectedly matches target")
    transaction_path, helper_path = _run_prepared_update(
        scenario,
        startup_timeout_seconds=3,
    )
    prepared_transaction = _read_json(transaction_path)
    backup = Path(str(prepared_transaction["backup_executable"]))
    _wait_for_path(backup, exists=True, timeout=30, label="rollback backup")
    _wait_for_state(
        transaction_path,
        {TransactionState.ROLLED_BACK.value},
        timeout=120,
    )
    transaction = _wait_for_terminal_cleanup(
        scenario,
        transaction_path,
        helper_path,
        state=TransactionState.ROLLED_BACK,
        timeout=45,
    )
    _require(sha256_file(scenario.target) == old_hash, "Rollback did not restore original target")
    result = _read_json(transaction_path.parent / RESULT_FILENAME)
    _require(result.get("status") == "rollback_succeeded", "Rollback result was not successful")
    _require(
        "startup_confirmation_timeout" in str(result.get("message") or ""),
        "Rollback was not caused by the intended startup-confirmation timeout",
    )
    _require(
        UpdateOwnershipManager(scenario.updates_root).read(scenario.target) is None,
        "Rollback retained ownership",
    )
    _terminate_exact_executable(scenario.target)
    _wait_for_no_process(scenario.target)
    _wait_for_no_process(helper_path)
    return {
        "state": transaction["state"],
        "result": result["status"],
        "failure_code": "startup_confirmation_timeout",
        "restored_sha256": old_hash,
        "ownership_cleanup": "pass",
    }


def _manual_transaction(
    scenario: Scenario,
    transaction_id: str,
    parent_pid: int,
    parent_created: str,
) -> Path:
    transaction_dir = scenario.updates_root / VERSION / transaction_id
    transaction_dir.mkdir(parents=True, exist_ok=True)
    transaction_path = transaction_dir / TRANSACTION_FILENAME
    _require(not transaction_path.exists(), "Manual smoke transaction already exists")
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds")
    transaction = UpdateTransaction(
        schema_version=2,
        transaction_id=transaction_id,
        confirmation_token=new_transaction_id(),
        state=TransactionState.HANDED_OFF.value,
        expected_version=VERSION,
        expected_sha256=sha256_file(scenario.staged),
        expected_size=scenario.staged.stat().st_size,
        original_sha256=sha256_file(scenario.target),
        parent_pid=parent_pid,
        parent_process_created=parent_created,
        target_identity=normalized_target_identity(scenario.target),
        target_executable=str(scenario.target),
        staged_executable=str(scenario.staged),
        backup_executable=str(
            scenario.target.parent / f".{scenario.target.name}.{transaction_id}.backup"
        ),
        startup_marker=str(transaction_dir / STARTUP_MARKER_FILENAME),
        created_at=timestamp,
        updated_at=timestamp,
        launched_pid=None,
        launched_process_created=None,
    )
    transaction_path.write_text(
        json.dumps(transaction.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return transaction_path


def _concurrency_smoke(
    base: Path,
    old_package: Path,
    new_package: Path,
) -> dict[str, object]:
    scenario = _scenario(base, "concurrency", old_package, new_package)
    environment = _environment(scenario)
    competitor = _start_parent(environment)
    other_parent = _start_parent(environment)
    helper = scenario.root / "helper" / "NeuralExtractorV3-Updater.exe"
    helper.parent.mkdir(parents=True)
    shutil.copy2(new_package, helper)
    process: subprocess.Popen[bytes] | None = None
    process_created: str | None = None
    original_hash = sha256_file(scenario.target)
    try:
        competitor_created = process_creation_identity(competitor.pid)
        other_created = process_creation_identity(other_parent.pid)
        _require(competitor_created is not None, "Competitor identity was unavailable")
        _require(other_created is not None, "Second parent identity was unavailable")
        manager = UpdateOwnershipManager(scenario.updates_root)
        competitor_transaction = new_transaction_id()
        live_record = manager.reserve_handoff(
            competitor_transaction,
            scenario.target,
            parent_pid=competitor.pid,
            parent_process_created=competitor_created,
        )
        second_transaction = scenario.transaction_id
        transaction_path = _manual_transaction(
            scenario,
            second_transaction,
            other_parent.pid,
            other_created,
        )
        process = subprocess.Popen(  # noqa: S603 - controlled packaged helper and transaction
            [str(helper), "--apply-update", str(transaction_path)],
            shell=False,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            env=environment,
        )
        process_created = process_creation_identity(process.pid)
        _require(process_created is not None, "Concurrent helper identity was unavailable")
        log = scenario.updates_root / "updater.log"
        _wait_for_text(log, "Updater helper rejected transaction: concurrent_update", timeout=45)
        preserved = manager.read(scenario.target)
        _require(preserved == live_record, "Packaged rejection modified the live competitor")
        _require(
            sha256_file(scenario.target) == original_hash,
            "Rejected concurrent helper modified the target",
        )
        return {
            "rejection": "concurrent_update",
            "competitor_preserved": True,
            "target_unchanged": True,
        }
    finally:
        if process is not None and process.poll() is None:
            taskkill = (
                Path(os.environ.get("SystemRoot", r"C:\Windows"))
                / "System32"
                / "taskkill.exe"
            )
            current_created = process_creation_identity(process.pid)
            if current_created is not None and current_created == process_created:
                subprocess.run(  # noqa: S603 - exact revalidated PID and fixed system executable
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    shell=False,
                    check=False,
                    capture_output=True,
                    timeout=15,
                    creationflags=CREATE_NO_WINDOW,
                )
        _stop_parent(competitor)
        _stop_parent(other_parent)
        UpdateOwnershipManager(scenario.updates_root).recover_stale()
        _wait_for_no_process(helper)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-package", type=Path, required=True)
    parser.add_argument("--new-package", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=("all", "success", "timeout", "concurrency"),
        default="all",
    )
    return parser.parse_args()


def main() -> int:
    if os.name != "nt":
        raise SmokeError("Packaged updater smoke requires Windows")
    args = _parse_args()
    old_package = args.old_package.resolve()
    new_package = args.new_package.resolve()
    workspace = args.workspace.resolve() / f"run-{uuid.uuid4().hex}"
    _require(old_package.is_file(), f"Old package is missing: {old_package}")
    _require(new_package.is_file(), f"New package is missing: {new_package}")
    _require(
        workspace.parent == args.workspace.resolve() and workspace.name.startswith("run-"),
        "Smoke workspace is invalid",
    )
    workspace.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    completed = False
    try:
        results: dict[str, object] = {}
        if args.scenario in {"all", "success"}:
            results["same_transaction_handoff"] = _success_smoke(
                workspace,
                old_package,
                new_package,
            )
        if args.scenario in {"all", "timeout"}:
            results["startup_timeout_rollback"] = _timeout_rollback_smoke(
                workspace,
                old_package,
            )
        if args.scenario in {"all", "concurrency"}:
            results["genuine_concurrency"] = _concurrency_smoke(
                workspace,
                old_package,
                new_package,
            )
        results["elapsed_seconds"] = round(time.monotonic() - started, 2)
        results["status"] = "PASS"
        print(json.dumps(results, indent=2, sort_keys=True))
        completed = True
        return 0
    finally:
        controlled_executables = list(workspace.rglob("*.exe"))
        for executable in controlled_executables:
            _terminate_exact_executable(executable)
        for executable in controlled_executables:
            _wait_for_no_process(executable)
        if completed and workspace.exists():
            shutil.rmtree(workspace)
        elif workspace.exists():
            print(f"FAILED_WORKSPACE={workspace}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
