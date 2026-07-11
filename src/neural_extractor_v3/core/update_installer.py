"""Detached Windows update installation, startup confirmation, and rollback."""

from __future__ import annotations

import contextlib
import ctypes
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from neural_extractor_v3.config import VERSION, app_data_dir
from neural_extractor_v3.core.update_manifest import (
    MAX_UPDATE_SIZE_BYTES,
    MIN_UPDATE_SIZE_BYTES,
    SHA256_PATTERN,
    UpdateManifest,
    expected_exe_filename,
    parse_numeric_version,
    sha256_file,
)
from neural_extractor_v3.core.updater import ProgressCallback, UpdateError, UpdateInfo

TRANSACTION_SCHEMA_VERSION = 1
UPDATE_HELPER_FILENAME = "NeuralExtractorV3-Updater.exe"
TRANSACTION_FILENAME = "transaction.json"
RESULT_FILENAME = "result.json"
STARTUP_MARKER_FILENAME = "startup-confirmation.json"
INSTALL_LOCK_FILENAME = "install.lock"

PARENT_EXIT_TIMEOUT_SECONDS = 90
STARTUP_CONFIRMATION_TIMEOUT_SECONDS = 60
PROCESS_POLL_INTERVAL_SECONDS = 0.25
REPLACEMENT_RETRY_COUNT = 20
REPLACEMENT_RETRY_DELAY_SECONDS = 0.5
ORIGINAL_RECOVERY_GRACE_SECONDS = 5
DISK_SPACE_MARGIN_BYTES = 64 * 1024 * 1024

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
OFFICIAL_EXECUTABLE_PATTERN = re.compile(
    r"^NeuralExtractorV3(?:-\d+\.\d+\.\d+-windows-x64)?\.exe$",
    re.IGNORECASE,
)

ProcessExists = Callable[[int], bool]
Sleep = Callable[[float], None]
Monotonic = Callable[[], float]
ReplaceFile = Callable[[str | Path, str | Path], None]
MessageCallback = Callable[[str, str], None]


class ChildProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


ProcessLauncher = Callable[[list[str]], ChildProcess]


@dataclass(frozen=True, slots=True)
class InstallationCapability:
    available: bool
    reason: str
    target_executable: Path | None = None
    code: str = ""


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    helper_pid: int
    transaction_path: Path


@dataclass(frozen=True, slots=True)
class UpdateTransaction:
    schema_version: int
    token: str
    expected_version: str
    expected_sha256: str
    expected_size: int
    original_sha256: str
    parent_pid: int
    target_executable: str
    staged_executable: str
    backup_executable: str
    startup_marker: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TRANSACTION_FIELDS = {
    "schema_version",
    "token",
    "expected_version",
    "expected_sha256",
    "expected_size",
    "original_sha256",
    "parent_pid",
    "target_executable",
    "staged_executable",
    "backup_executable",
    "startup_marker",
    "created_at",
}


def update_root() -> Path:
    root = (app_data_dir() / "updates").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_within(path: Path, root: Path) -> bool:
    path = path.resolve()
    root = root.resolve()
    return path == root or root in path.parents


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise UpdateError(
                "invalid_transaction",
                f"Duplicate update transaction field: {key}",
            )
        result[key] = value
    return result


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def _copy_file_sync(source: Path, destination: Path) -> None:
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        while chunk := input_handle.read(1024 * 1024):
            output_handle.write(chunk)
        output_handle.flush()
        os.fsync(output_handle.fileno())
    shutil.copystat(source, destination, follow_symlinks=True)


def _directory_writable(directory: Path) -> bool:
    probe = Path(directory) / f".neural-extractor-write-{secrets.token_hex(8)}.tmp"
    try:
        with probe.open("xb") as handle:
            handle.write(b"ok")
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()


def _official_target_name(name: str) -> bool:
    return bool(OFFICIAL_EXECUTABLE_PATTERN.fullmatch(name))


def assess_installation_capability(
    manifest: UpdateManifest,
    *,
    target_executable: Path | None = None,
    frozen: bool | None = None,
    updates_root: Path | None = None,
    temporary_root: Path | None = None,
) -> InstallationCapability:
    """Check whether this process can safely self-replace without elevation."""
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not is_frozen:
        return InstallationCapability(
            False,
            "Automatic installation is available only in the packaged Windows application.",
            code="manual_install_required",
        )
    if sys.platform != "win32":
        return InstallationCapability(
            False,
            "Automatic installation is supported only on Windows.",
            code="wrong_platform",
        )

    target = Path(target_executable or sys.executable).resolve()
    if not target.exists() or not target.is_file():
        return InstallationCapability(
            False,
            "The running application executable could not be found.",
            code="invalid_install_location",
        )
    if not _official_target_name(target.name):
        return InstallationCapability(
            False,
            "The running executable does not have an official Neural Extractor filename.",
            code="invalid_install_location",
        )

    root = Path(updates_root or update_root()).resolve()
    temp_root = Path(temporary_root or tempfile.gettempdir()).resolve()
    meipass = Path(str(getattr(sys, "_MEIPASS", ""))).resolve() if getattr(sys, "_MEIPASS", None) else None
    if _is_within(target, root) or _is_within(target, temp_root) or (
        meipass is not None and _is_within(target, meipass)
    ):
        return InstallationCapability(
            False,
            "The application is running from a temporary or update-staging location.",
            code="invalid_install_location",
        )

    if not _directory_writable(target.parent):
        return InstallationCapability(
            False,
            "The application folder is not writable without elevated permissions.",
            code="insufficient_permissions",
        )

    try:
        current_size = target.stat().st_size
        staged_candidate = root / manifest.release_version / "package" / manifest.asset_filename
        staged_size = (
            manifest.asset_size
            if staged_candidate.exists()
            and staged_candidate.is_file()
            and staged_candidate.stat().st_size == manifest.asset_size
            else 0
        )
        missing_staging_space = manifest.asset_size - staged_size
        required_target_space = current_size + manifest.asset_size + DISK_SPACE_MARGIN_BYTES
        required_staging_space = missing_staging_space + current_size + DISK_SPACE_MARGIN_BYTES

        root.mkdir(parents=True, exist_ok=True)
        target_usage = shutil.disk_usage(target.parent)
        root_usage = shutil.disk_usage(root)
        same_volume = target.parent.stat().st_dev == root.stat().st_dev
        if same_volume:
            combined_required = (
                missing_staging_space
                + current_size * 2
                + manifest.asset_size
                + DISK_SPACE_MARGIN_BYTES
            )
            if target_usage.free < combined_required:
                return InstallationCapability(
                    False,
                    "There is insufficient disk space for staging, backup, and replacement.",
                    code="insufficient_disk_space",
                )
        elif target_usage.free < required_target_space:
            return InstallationCapability(
                False,
                "There is insufficient disk space in the application folder.",
                code="insufficient_disk_space",
            )
        if not same_volume and root_usage.free < required_staging_space:
            return InstallationCapability(
                False,
                "There is insufficient disk space for update staging.",
                code="insufficient_disk_space",
            )
    except OSError:
        return InstallationCapability(
            False,
            "Available disk space could not be verified.",
            code="insufficient_disk_space",
        )

    return InstallationCapability(
        True,
        "Automatic installation is available.",
        target,
        code="available",
    )


def _default_detached_launcher(arguments: list[str]) -> ChildProcess:
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    return subprocess.Popen(  # noqa: S603 - arguments are internally constructed and validated
        arguments,
        shell=False,
        close_fds=True,
        creationflags=creation_flags,
    )


def _default_process_launcher(arguments: list[str]) -> ChildProcess:
    return subprocess.Popen(  # noqa: S603 - arguments are internally constructed and validated
        arguments,
        shell=False,
        close_fds=True,
    )


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(  # type: ignore[attr-defined]
                handle,
                ctypes.byref(exit_code),
            ):
                return False
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _show_native_message(title: str, message: str) -> None:
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                None,
                message,
                title,
                0x00000010,
            )


def _append_update_log(message: str) -> None:
    log_path = app_data_dir() / "updates" / "updater.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    with contextlib.suppress(OSError):
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")


def _lock_path(root: Path) -> Path:
    return Path(root) / INSTALL_LOCK_FILENAME


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_strict_json_object,
        )
    except UpdateError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError("invalid_transaction", "The update transaction file is invalid.") from exc
    if not isinstance(payload, dict):
        raise UpdateError("invalid_transaction", "The update transaction file is invalid.")
    return payload


def _read_lock(root: Path) -> dict[str, Any] | None:
    path = _lock_path(root)
    if not path.exists():
        return None
    try:
        payload = _read_json(path)
    except UpdateError:
        return {"invalid": True}
    return payload


def _create_install_lock(root: Path, token: str, owner_pid: int, transaction: Path) -> None:
    path = _lock_path(root)
    existing = _read_lock(root)
    if existing:
        existing_pid = existing.get("owner_pid")
        if isinstance(existing_pid, int) and _process_exists(existing_pid):
            raise UpdateError(
                "concurrent_update",
                "Another Neural Extractor update is already running.",
            )
        with contextlib.suppress(OSError):
            path.unlink()

    payload = {
        "token": token,
        "owner_pid": owner_pid,
        "transaction": str(Path(transaction).resolve()),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise UpdateError(
            "concurrent_update",
            "Another Neural Extractor update is already running.",
        ) from exc


def _claim_install_lock(root: Path, transaction: UpdateTransaction, transaction_path: Path) -> None:
    payload = _read_lock(root)
    if not payload or payload.get("token") != transaction.token:
        raise UpdateError("concurrent_update", "The update installation lock is missing or invalid.")
    if Path(str(payload.get("transaction") or "")).resolve() != transaction_path.resolve():
        raise UpdateError("concurrent_update", "The update installation lock is inconsistent.")
    if payload.get("owner_pid") not in {transaction.parent_pid, os.getpid()}:
        raise UpdateError("concurrent_update", "Another updater process owns this installation.")
    _atomic_write_json(
        _lock_path(root),
        {
            "token": transaction.token,
            "owner_pid": os.getpid(),
            "transaction": str(transaction_path.resolve()),
        },
    )


def _release_install_lock(root: Path, token: str) -> None:
    payload = _read_lock(root)
    if payload and payload.get("token") == token:
        with contextlib.suppress(OSError):
            _lock_path(root).unlink()


def prepare_and_launch_update(
    info: UpdateInfo,
    staged_executable: Path,
    *,
    parent_pid: int,
    progress_callback: ProgressCallback | None = None,
    target_executable: Path | None = None,
    frozen: bool | None = None,
    updates_root: Path | None = None,
    temporary_root: Path | None = None,
    helper_root: Path | None = None,
    detached_launcher: ProcessLauncher = _default_detached_launcher,
) -> PreparedUpdate:
    root = Path(updates_root or update_root()).resolve()
    capability = assess_installation_capability(
        info.manifest,
        target_executable=target_executable,
        frozen=frozen,
        updates_root=root,
        temporary_root=temporary_root,
    )
    if not capability.available or capability.target_executable is None:
        raise UpdateError(capability.code or "installation_failure", capability.reason)

    target = capability.target_executable
    staged = Path(staged_executable).resolve()
    if not _is_within(staged, root) or staged.name != expected_exe_filename(info.version):
        raise UpdateError("unsafe_path", "The staged update path is invalid.")
    if not staged.exists() or staged.stat().st_size != info.manifest.asset_size:
        raise UpdateError("file_size_mismatch", "The staged update package size is invalid.")
    if not hmac.compare_digest(sha256_file(staged), info.manifest.asset_sha256):
        raise UpdateError("checksum_mismatch", "The staged update checksum is invalid.")

    token = secrets.token_urlsafe(36)
    transaction_dir = (root / info.version / token).resolve()
    if not _is_within(transaction_dir, root):
        raise UpdateError("unsafe_path", "The update transaction path is invalid.")
    transaction_dir.mkdir(parents=True, exist_ok=False)

    helper_dir = Path(helper_root or (app_data_dir() / "updater-helper")).resolve()
    helper_dir.mkdir(parents=True, exist_ok=True)
    helper = helper_dir / UPDATE_HELPER_FILENAME
    helper_temp = helper_dir / f".{UPDATE_HELPER_FILENAME}.{secrets.token_hex(8)}.tmp"
    transaction_path = transaction_dir / TRANSACTION_FILENAME
    marker_path = transaction_dir / STARTUP_MARKER_FILENAME
    backup_path = target.parent / f".{target.name}.{token}.backup"

    if progress_callback:
        progress_callback(92, "Preparing detached updater")

    try:
        _copy_file_sync(target, helper_temp)
        if not hmac.compare_digest(sha256_file(helper_temp), sha256_file(target)):
            raise UpdateError("staging_failure", "The detached updater copy could not be verified.")
        os.replace(helper_temp, helper)

        transaction = UpdateTransaction(
            schema_version=TRANSACTION_SCHEMA_VERSION,
            token=token,
            expected_version=info.version,
            expected_sha256=info.manifest.asset_sha256,
            expected_size=info.manifest.asset_size,
            original_sha256=sha256_file(target),
            parent_pid=parent_pid,
            target_executable=str(target),
            staged_executable=str(staged),
            backup_executable=str(backup_path),
            startup_marker=str(marker_path),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        _atomic_write_json(transaction_path, transaction.to_dict())
        _create_install_lock(root, token, parent_pid, transaction_path)

        process = detached_launcher(
            [str(helper), "--apply-update", str(transaction_path)]
        )
        _atomic_write_json(
            _lock_path(root),
            {
                "token": token,
                "owner_pid": process.pid,
                "transaction": str(transaction_path.resolve()),
            },
        )
        if progress_callback:
            progress_callback(100, "Updater ready; Neural Extractor will restart")
        return PreparedUpdate(process.pid, transaction_path)
    except Exception:
        _release_install_lock(root, token)
        with contextlib.suppress(OSError):
            helper_temp.unlink()
        raise


def load_update_transaction(
    transaction_path: Path,
    *,
    updates_root: Path | None = None,
    temporary_root: Path | None = None,
) -> UpdateTransaction:
    root = Path(updates_root or update_root()).resolve()
    path = Path(transaction_path).resolve()
    if not _is_within(path, root) or path.name != TRANSACTION_FILENAME:
        raise UpdateError("invalid_transaction", "The update transaction path is unsafe.")
    payload = _read_json(path)
    if set(payload) != TRANSACTION_FIELDS:
        raise UpdateError("invalid_transaction", "The update transaction fields are invalid.")
    if payload.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
        raise UpdateError("invalid_transaction", "The update transaction schema is unsupported.")

    token = str(payload.get("token") or "")
    if not TOKEN_PATTERN.fullmatch(token):
        raise UpdateError("invalid_transaction", "The update transaction token is invalid.")
    version = str(payload.get("expected_version") or "")
    try:
        parse_numeric_version(version)
    except ValueError as exc:
        raise UpdateError("invalid_transaction", "The update transaction version is invalid.") from exc

    expected_hash = str(payload.get("expected_sha256") or "")
    original_hash = str(payload.get("original_sha256") or "")
    if not SHA256_PATTERN.fullmatch(expected_hash) or not SHA256_PATTERN.fullmatch(original_hash):
        raise UpdateError("invalid_transaction", "The update transaction checksum is invalid.")
    size = payload.get("expected_size")
    parent_pid = payload.get("parent_pid")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not MIN_UPDATE_SIZE_BYTES <= size <= MAX_UPDATE_SIZE_BYTES
    ):
        raise UpdateError("invalid_transaction", "The update transaction size is invalid.")
    if isinstance(parent_pid, bool) or not isinstance(parent_pid, int) or parent_pid <= 0:
        raise UpdateError("invalid_transaction", "The update parent process ID is invalid.")

    transaction_dir = path.parent.resolve()
    expected_transaction_dir = (root / version / token).resolve()
    if transaction_dir != expected_transaction_dir:
        raise UpdateError("invalid_transaction", "The update transaction directory is invalid.")

    target = Path(str(payload.get("target_executable") or "")).resolve()
    staged = Path(str(payload.get("staged_executable") or "")).resolve()
    backup = Path(str(payload.get("backup_executable") or "")).resolve()
    marker = Path(str(payload.get("startup_marker") or "")).resolve()

    temp_root = Path(temporary_root or tempfile.gettempdir()).resolve()
    if (
        not target.exists()
        or not target.is_file()
        or not _official_target_name(target.name)
        or _is_within(target, root)
        or _is_within(target, temp_root)
    ):
        raise UpdateError("invalid_transaction", "The update target executable is invalid.")
    if not _directory_writable(target.parent):
        raise UpdateError("invalid_transaction", "The update target directory is not writable.")
    try:
        required_space = target.stat().st_size + size + DISK_SPACE_MARGIN_BYTES
        if shutil.disk_usage(target.parent).free < required_space:
            raise UpdateError(
                "insufficient_disk_space",
                "There is insufficient disk space to apply the staged update safely.",
            )
    except OSError as exc:
        raise UpdateError(
            "insufficient_disk_space",
            "Available disk space could not be verified before installation.",
        ) from exc
    expected_staged = (root / version / "package" / expected_exe_filename(version)).resolve()
    if staged != expected_staged:
        raise UpdateError("invalid_transaction", "The staged update executable is invalid.")
    if backup != target.parent / f".{target.name}.{token}.backup":
        raise UpdateError("invalid_transaction", "The update backup path is invalid.")
    if marker != transaction_dir / STARTUP_MARKER_FILENAME:
        raise UpdateError("invalid_transaction", "The startup marker path is invalid.")

    return UpdateTransaction(
        schema_version=TRANSACTION_SCHEMA_VERSION,
        token=token,
        expected_version=version,
        expected_sha256=expected_hash.lower(),
        expected_size=size,
        original_sha256=original_hash.lower(),
        parent_pid=parent_pid,
        target_executable=str(target),
        staged_executable=str(staged),
        backup_executable=str(backup),
        startup_marker=str(marker),
        created_at=str(payload.get("created_at") or ""),
    )


class UpdateApplier:
    """Apply one validated update transaction from the detached helper process."""

    def __init__(
        self,
        transaction_path: Path,
        *,
        updates_root: Path | None = None,
        process_exists: ProcessExists = _process_exists,
        process_launcher: ProcessLauncher = _default_process_launcher,
        sleep: Sleep = time.sleep,
        monotonic: Monotonic = time.monotonic,
        replace_file: ReplaceFile = os.replace,
        message_callback: MessageCallback = _show_native_message,
        parent_exit_timeout: float = PARENT_EXIT_TIMEOUT_SECONDS,
        startup_timeout: float = STARTUP_CONFIRMATION_TIMEOUT_SECONDS,
        temporary_root: Path | None = None,
    ) -> None:
        self.root = Path(updates_root or update_root()).resolve()
        self.transaction_path = Path(transaction_path).resolve()
        self.transaction = load_update_transaction(
            self.transaction_path,
            updates_root=self.root,
            temporary_root=temporary_root,
        )
        self.process_exists = process_exists
        self.process_launcher = process_launcher
        self.sleep = sleep
        self.monotonic = monotonic
        self.replace_file = replace_file
        self.message_callback = message_callback
        self.parent_exit_timeout = parent_exit_timeout
        self.startup_timeout = startup_timeout

    def apply(self) -> int:
        transaction = self.transaction
        target = Path(transaction.target_executable)
        staged = Path(transaction.staged_executable)
        backup = Path(transaction.backup_executable)
        marker = Path(transaction.startup_marker)
        replacement_temp = target.parent / f".{target.name}.{transaction.token}.new"
        target_replaced = False
        new_process: ChildProcess | None = None

        _claim_install_lock(self.root, transaction, self.transaction_path)
        _append_update_log(
            f"Applying update {transaction.expected_version}; target={target.name}"
        )

        try:
            self._verify_staged(staged)
            self._wait_for_parent_exit()
            with contextlib.suppress(OSError):
                marker.unlink()

            if backup.exists():
                if not hmac.compare_digest(sha256_file(backup), transaction.original_sha256):
                    raise UpdateError(
                        "installation_failure",
                        "An existing update backup is invalid. Installation stopped.",
                    )
            else:
                _copy_file_sync(target, backup)
            if not hmac.compare_digest(sha256_file(backup), transaction.original_sha256):
                raise UpdateError("installation_failure", "The application backup could not be verified.")

            with contextlib.suppress(OSError):
                replacement_temp.unlink()
            _copy_file_sync(staged, replacement_temp)
            if replacement_temp.stat().st_size != transaction.expected_size or not hmac.compare_digest(
                sha256_file(replacement_temp), transaction.expected_sha256
            ):
                raise UpdateError("checksum_mismatch", "The replacement copy failed verification.")

            self._replace_with_retry(replacement_temp, target)
            target_replaced = True
            if not hmac.compare_digest(sha256_file(target), transaction.expected_sha256):
                raise UpdateError("checksum_mismatch", "The installed update failed verification.")

            new_process = self.process_launcher(
                [
                    str(target),
                    "--post-update-token",
                    transaction.token,
                    "--post-update-marker",
                    str(marker),
                ]
            )
            self._wait_for_startup_confirmation(new_process, marker)

            result_recorded = True
            try:
                self._write_result("success", "Update installed and startup confirmed.")
            except OSError:
                result_recorded = False
                _append_update_log("Startup succeeded, but the success record could not be written")
            if result_recorded:
                with contextlib.suppress(OSError):
                    backup.unlink()
            with contextlib.suppress(OSError):
                staged.unlink()
            with contextlib.suppress(OSError):
                marker.unlink()
            _release_install_lock(self.root, transaction.token)
            _append_update_log(f"Update {transaction.expected_version} confirmed successfully")
            return 0
        except Exception as exc:
            update_error = (
                exc
                if isinstance(exc, UpdateError)
                else UpdateError("installation_failure", "The update installation failed.", str(exc))
            )
            _append_update_log(
                f"Update {transaction.expected_version} failed: {update_error.code}"
            )
            with contextlib.suppress(OSError):
                replacement_temp.unlink()
            if target_replaced:
                return self._rollback(update_error, new_process)
            return self._recover_original_without_replacement(update_error)

    def _verify_staged(self, staged: Path) -> None:
        transaction = self.transaction
        if not staged.exists() or staged.stat().st_size != transaction.expected_size:
            raise UpdateError("file_size_mismatch", "The staged update package is missing or incomplete.")
        if not hmac.compare_digest(sha256_file(staged), transaction.expected_sha256):
            raise UpdateError("checksum_mismatch", "The staged update checksum is invalid.")

    def _wait_for_parent_exit(self) -> None:
        deadline = self.monotonic() + self.parent_exit_timeout
        while self.process_exists(self.transaction.parent_pid):
            if self.monotonic() >= deadline:
                raise UpdateError(
                    "installation_failure",
                    "Neural Extractor did not close in time. The update was not installed.",
                )
            self.sleep(PROCESS_POLL_INTERVAL_SECONDS)

    def _replace_with_retry(self, source: Path, target: Path) -> None:
        last_error: OSError | None = None
        for attempt in range(REPLACEMENT_RETRY_COUNT):
            try:
                self.replace_file(source, target)
                return
            except OSError as exc:
                last_error = exc
                if attempt + 1 < REPLACEMENT_RETRY_COUNT:
                    self.sleep(REPLACEMENT_RETRY_DELAY_SECONDS)
        raise UpdateError(
            "installation_failure",
            "Windows could not replace the application file. Antivirus or a file lock may be blocking it.",
            technical=str(last_error or "replace failed"),
        )

    def _wait_for_startup_confirmation(self, process: ChildProcess, marker: Path) -> None:
        deadline = self.monotonic() + self.startup_timeout
        while self.monotonic() < deadline:
            if marker.exists() and self._valid_startup_marker(marker):
                return
            if process.poll() is not None:
                raise UpdateError(
                    "installation_failure",
                    "The updated application exited before startup completed.",
                )
            self.sleep(PROCESS_POLL_INTERVAL_SECONDS)
        raise UpdateError(
            "installation_failure",
            "The updated application did not confirm startup in time.",
        )

    def _valid_startup_marker(self, marker: Path) -> bool:
        try:
            payload = _read_json(marker)
        except UpdateError:
            return False
        return (
            set(payload) == {"token", "version", "status", "pid"}
            and payload.get("token") == self.transaction.token
            and payload.get("version") == self.transaction.expected_version
            and payload.get("status") == "initialized"
            and isinstance(payload.get("pid"), int)
            and not isinstance(payload.get("pid"), bool)
        )

    def _rollback(self, original_error: UpdateError, process: ChildProcess | None) -> int:
        transaction = self.transaction
        target = Path(transaction.target_executable)
        backup = Path(transaction.backup_executable)
        rollback_temp = target.parent / f".{target.name}.{transaction.token}.rollback"
        try:
            self._stop_process(process)
            if not backup.exists() or not hmac.compare_digest(
                sha256_file(backup), transaction.original_sha256
            ):
                raise UpdateError("rollback_failure", "The last known-good backup is missing or invalid.")
            with contextlib.suppress(OSError):
                rollback_temp.unlink()
            _copy_file_sync(backup, rollback_temp)
            self._replace_with_retry(rollback_temp, target)
            if not hmac.compare_digest(sha256_file(target), transaction.original_sha256):
                raise UpdateError("rollback_failure", "The restored application failed verification.")
            with contextlib.suppress(OSError):
                self._write_result(
                    "rollback_succeeded",
                    f"Update failed ({original_error.code}); the previous version was restored.",
                )
            self.process_launcher(
                [str(target), "--update-rollback-status", str(self.transaction_path)]
            )
            _release_install_lock(self.root, transaction.token)
            _append_update_log("Rollback succeeded and the previous version was restarted")
            return 3
        except Exception as rollback_error:
            with contextlib.suppress(OSError):
                rollback_temp.unlink()
            with contextlib.suppress(OSError):
                self._write_result(
                    "rollback_failed",
                    f"Update failed ({original_error.code}) and rollback failed.",
                )
            _release_install_lock(self.root, transaction.token)
            self.message_callback(
                "Neural Extractor Update Recovery",
                "The update and automatic rollback both failed.\n\n"
                f"Backup retained at:\n{backup}\n\n"
                f"Target application:\n{target}\n\n"
                "Close Neural Extractor, copy the backup over the target file, and retry later.",
            )
            _append_update_log(f"Rollback failed: {type(rollback_error).__name__}")
            return 4

    def _recover_original_without_replacement(self, error: UpdateError) -> int:
        target = Path(self.transaction.target_executable)
        backup = Path(self.transaction.backup_executable)
        if backup.exists():
            with contextlib.suppress(OSError):
                if not hmac.compare_digest(
                    sha256_file(backup), self.transaction.original_sha256
                ):
                    backup.unlink()
        with contextlib.suppress(OSError):
            self._write_result(
                "original_preserved",
                f"Update failed ({error.code}); the original executable was not replaced.",
            )
        parent_running = self.process_exists(self.transaction.parent_pid)
        deadline = self.monotonic() + ORIGINAL_RECOVERY_GRACE_SECONDS
        while parent_running and self.monotonic() < deadline:
            self.sleep(PROCESS_POLL_INTERVAL_SECONDS)
            parent_running = self.process_exists(self.transaction.parent_pid)
        if not parent_running:
            with contextlib.suppress(Exception):
                self.process_launcher(
                    [str(target), "--update-rollback-status", str(self.transaction_path)]
                )
        _release_install_lock(self.root, self.transaction.token)
        return 2

    @staticmethod
    def _stop_process(process: ChildProcess | None) -> None:
        if process is None or process.poll() is not None:
            return
        with contextlib.suppress(Exception):
            process.terminate()
            process.wait(timeout=10)
        if process.poll() is None:
            with contextlib.suppress(Exception):
                process.kill()
                process.wait(timeout=5)

    def _write_result(self, status: str, message: str) -> None:
        _atomic_write_json(
            self.transaction_path.parent / RESULT_FILENAME,
            {
                "status": status,
                "message": message,
                "version": self.transaction.expected_version,
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )


def run_update_helper(transaction_path: Path) -> int:
    """Entry point used by the copied packaged EXE in detached helper mode."""
    try:
        return UpdateApplier(transaction_path).apply()
    except UpdateError as exc:
        _append_update_log(f"Updater helper rejected transaction: {exc.code}")
        _show_native_message(
            "Neural Extractor Update",
            f"The update could not be applied safely.\n\n{exc.user_message}",
        )
        return 5
    except Exception as exc:
        _append_update_log(f"Updater helper failed: {type(exc).__name__}")
        _show_native_message(
            "Neural Extractor Update",
            "The update helper encountered an unexpected error. The current application was not intentionally removed.",
        )
        return 6


def write_startup_confirmation(
    token: str,
    marker_path: Path,
    *,
    version: str = VERSION,
    updates_root: Path | None = None,
) -> None:
    root = Path(updates_root or update_root()).resolve()
    marker = Path(marker_path).resolve()
    if not TOKEN_PATTERN.fullmatch(str(token or "")):
        raise UpdateError("invalid_transaction", "The startup confirmation token is invalid.")
    if not _is_within(marker, root) or marker.name != STARTUP_MARKER_FILENAME:
        raise UpdateError("unsafe_path", "The startup confirmation path is invalid.")
    if marker.parent.name != token:
        raise UpdateError("invalid_transaction", "The startup confirmation token does not match its path.")
    parse_numeric_version(version)
    if marker.parent.parent.name != version:
        raise UpdateError(
            "invalid_transaction",
            "The startup confirmation version does not match its path.",
        )
    _atomic_write_json(
        marker,
        {
            "token": token,
            "version": version,
            "status": "initialized",
            "pid": os.getpid(),
        },
    )


def read_update_recovery_message(
    transaction_path: Path,
    *,
    updates_root: Path | None = None,
) -> str:
    root = Path(updates_root or update_root()).resolve()
    path = Path(transaction_path).resolve()
    if not _is_within(path, root) or path.name != TRANSACTION_FILENAME:
        return "The previous update failed, but its recovery details could not be validated."
    result_path = path.parent / RESULT_FILENAME
    try:
        payload = _read_json(result_path)
    except UpdateError:
        return "The previous update failed. The original application remains available."
    status = payload.get("status")
    if status == "rollback_succeeded":
        return "The update failed to start correctly. Neural Extractor restored and restarted the previous version."
    if status == "original_preserved":
        return "The update could not be installed. The original Neural Extractor executable was preserved."
    if status == "rollback_failed":
        return "The update and automatic rollback failed. Use the retained backup described in the updater log."
    return "The previous update did not complete. The current executable was preserved where possible."


def cleanup_stale_update_state(
    *,
    updates_root: Path | None = None,
    successful_retention_days: int = 7,
) -> None:
    """Remove only old, confirmed-success transaction metadata and stale partial files."""
    root = Path(updates_root or update_root()).resolve()
    if not root.exists():
        return
    cutoff = time.time() - successful_retention_days * 24 * 60 * 60
    for partial in root.rglob("*.part"):
        with contextlib.suppress(OSError):
            if partial.stat().st_mtime < cutoff:
                partial.unlink()
    for result_path in root.rglob(RESULT_FILENAME):
        try:
            if result_path.stat().st_mtime >= cutoff:
                continue
            payload = _read_json(result_path)
            if payload.get("status") != "success":
                continue
            transaction_dir = result_path.parent.resolve()
            if _is_within(transaction_dir, root):
                shutil.rmtree(transaction_dir)
        except (OSError, UpdateError):
            continue
