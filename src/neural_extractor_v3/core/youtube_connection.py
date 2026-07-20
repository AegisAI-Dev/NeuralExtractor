"""Managed Firefox profile and YouTube connection lifecycle.

The profile managed here is deliberately outside Firefox's normal profile
directories.  This module never reads or writes ``profiles.ini`` and never
selects the user's default Firefox profile.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from neural_extractor_v3.config import YOUTUBE_HOSTS, app_data_dir
from neural_extractor_v3.core.process_control import process_creation_identity

SETTINGS_PREFIX = "youtube_connection"
FIREFOX_PROFILE_DIRECTORY = "firefox-profile"
FIREFOX_COOKIE_DATABASE = "cookies.sqlite"
FIREFOX_LOCK_FILES = ("parent.lock", ".parentlock", "lock")
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
DEFAULT_CONNECTION_URL = "https://www.youtube.com/"

_SENSITIVE_QUERY_NAMES = {
    "access_token",
    "auth",
    "authorization",
    "cookie",
    "credential",
    "key",
    "password",
    "po_token",
    "token",
}
_AUTH_COOKIE_NAMES = {
    "APISID",
    "HSID",
    "LOGIN_INFO",
    "SAPISID",
    "SID",
    "SSID",
    "__SECURE-1PAPISID",
    "__SECURE-1PSID",
    "__SECURE-3PAPISID",
    "__SECURE-3PSID",
}


class ConnectionState(str, Enum):
    NOT_CONFIGURED = "not_configured"
    FIREFOX_MISSING = "firefox_missing"
    PROFILE_READY = "profile_ready"
    WAITING_FOR_LOGIN = "waiting_for_login"
    BROWSER_OPEN = "browser_open"
    VERIFYING = "verifying"
    CONNECTED = "connected"
    EXPIRED = "expired"
    LOCKED = "locked"
    INVALID = "invalid"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class FirefoxDiscoveryResult:
    executable: Path | None
    source: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class FirefoxProcessIdentity:
    pid: int
    creation_identity: str
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConnectionSnapshot:
    state: ConnectionState
    profile_path: Path
    firefox_path: Path | None
    last_verified: str
    failure_reason: str

    @property
    def connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED


@dataclass(frozen=True, slots=True)
class VerificationResult:
    success: bool
    code: str
    message: str
    warning: str = ""


@dataclass(frozen=True, slots=True)
class DisconnectResult:
    success: bool
    code: str
    message: str
    manual_cleanup_path: Path | None = None


class SettingsStore(Protocol):
    def value(self, key: str, default: Any = None) -> Any: ...

    def setValue(self, key: str, value: Any) -> None: ...  # noqa: N802

    def remove(self, key: str) -> None: ...

    def sync(self) -> None: ...


RegistryReader = Callable[[], Iterable[Path | str]]
BinaryValidator = Callable[[Path], bool]
PopenFactory = Callable[..., subprocess.Popen[Any]]
IdentityProvider = Callable[[int], str | None]
Verifier = Callable[[Path, str], VerificationResult]


def youtube_data_root(application_data: Path | None = None) -> Path:
    return Path(application_data or app_data_dir()) / "youtube"


def dedicated_firefox_profile_path(application_data: Path | None = None) -> Path:
    return youtube_data_root(application_data) / FIREFOX_PROFILE_DIRECTORY


def _normalized_path(path: Path | str, *, strict: bool = False) -> Path:
    candidate = Path(path).expanduser()
    return candidate.resolve(strict=strict)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _is_reparse_point(path: Path) -> bool:
    try:
        details = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(details.st_mode):
        return True
    attributes = int(getattr(details, "st_file_attributes", 0))
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def validate_dedicated_profile_path(
    profile_path: Path | str,
    *,
    application_data: Path | None = None,
    require_exists: bool = True,
) -> Path:
    """Return the exact managed profile or reject traversal/reparse escapes."""
    application_root = Path(application_data or app_data_dir()).expanduser()
    root = youtube_data_root(application_root)
    expected = dedicated_firefox_profile_path(application_root)
    try:
        normalized_root = _normalized_path(root)
        normalized_expected = _normalized_path(expected)
        normalized_profile = _normalized_path(profile_path)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Dedicated Firefox profile path is invalid.") from exc

    if not _same_path(normalized_profile, normalized_expected):
        raise ValueError("Dedicated Firefox profile path is outside the managed location.")
    if normalized_profile == normalized_root or normalized_profile.parent != normalized_root:
        raise ValueError("Dedicated Firefox profile path is not a safe child directory.")
    if require_exists and (not normalized_profile.exists() or not normalized_profile.is_dir()):
        raise ValueError("Dedicated Firefox profile does not exist.")

    # A junction on the application-owned ancestor could otherwise make the
    # fixed logical profile path resolve outside Neural Extractor's tree.
    for candidate in (application_root, root, expected):
        if candidate.exists() and _is_reparse_point(candidate):
            raise ValueError("Dedicated Firefox profile uses an unsafe reparse point.")
    if require_exists and _is_reparse_point(normalized_profile):
        raise ValueError("Dedicated Firefox profile uses an unsafe reparse point.")
    return normalized_profile


def _strip_registry_value(value: Path | str) -> Path:
    raw = os.path.expandvars(str(value)).strip().strip('"')
    return Path(raw)


def _read_firefox_app_paths_registry() -> list[Path]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    candidates: list[Path] = []
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe"
    views = (0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0))
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in dict.fromkeys(views):
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                    value, _ = winreg.QueryValueEx(key, None)
            except OSError:
                continue
            if isinstance(value, str) and value.strip():
                candidates.append(_strip_registry_value(value))
    return candidates


def _windows_binary_is_firefox(path: Path) -> bool:
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    version = ctypes.WinDLL("version", use_last_error=True)
    get_size = version.GetFileVersionInfoSizeW
    get_size.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    get_size.restype = wintypes.DWORD
    get_info = version.GetFileVersionInfoW
    get_info.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
    get_info.restype = wintypes.BOOL
    query_value = version.VerQueryValueW
    query_value.argtypes = [
        wintypes.LPCVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.UINT),
    ]
    query_value.restype = wintypes.BOOL

    ignored = wintypes.DWORD()
    size = int(get_size(str(path), ctypes.byref(ignored)))
    if size <= 0:
        return False
    buffer = ctypes.create_string_buffer(size)
    if not get_info(str(path), 0, size, buffer):
        return False

    translations_pointer = wintypes.LPVOID()
    translations_length = wintypes.UINT()
    translations: list[tuple[int, int]] = []
    if query_value(
        buffer,
        r"\VarFileInfo\Translation",
        ctypes.byref(translations_pointer),
        ctypes.byref(translations_length),
    ):
        count = int(translations_length.value) // (2 * ctypes.sizeof(wintypes.WORD))
        words = ctypes.cast(translations_pointer, ctypes.POINTER(wintypes.WORD))
        translations.extend((int(words[index * 2]), int(words[index * 2 + 1])) for index in range(count))
    if not translations:
        translations.append((0x0409, 0x04B0))

    def version_string(name: str) -> str:
        for language, codepage in translations:
            pointer = wintypes.LPVOID()
            length = wintypes.UINT()
            key = rf"\StringFileInfo\{language:04x}{codepage:04x}\{name}"
            if query_value(buffer, key, ctypes.byref(pointer), ctypes.byref(length)) and length.value:
                return ctypes.wstring_at(pointer, length.value).rstrip("\x00")
        return ""

    product = version_string("ProductName").casefold()
    description = version_string("FileDescription").casefold()
    company = version_string("CompanyName").casefold()
    original = version_string("OriginalFilename").casefold()
    return (
        "firefox" in f"{product} {description}"
        and "mozilla" in company
        and original == "firefox.exe"
    )


class FirefoxDiscovery:
    """Find and validate a Firefox executable without executing candidates."""

    def __init__(
        self,
        *,
        registry_reader: RegistryReader = _read_firefox_app_paths_registry,
        environ: Mapping[str, str] | None = None,
        binary_validator: BinaryValidator = _windows_binary_is_firefox,
    ) -> None:
        self.registry_reader = registry_reader
        self.environ = dict(os.environ if environ is None else environ)
        self.binary_validator = binary_validator

    def validate_executable(self, path: Path | str | None) -> Path | None:
        if not path or "\x00" in str(path):
            return None
        try:
            candidate = _normalized_path(_strip_registry_value(path), strict=True)
            if not candidate.is_file() or candidate.name.casefold() != "firefox.exe":
                return None
            with candidate.open("rb") as handle:
                if handle.read(2) != b"MZ":
                    return None
            if not self.binary_validator(candidate):
                return None
        except (OSError, RuntimeError, ValueError):
            return None
        return candidate

    def standard_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            root = self.environ.get(variable)
            if root:
                candidates.append(Path(root) / "Mozilla Firefox" / "firefox.exe")
        return candidates

    def discover(self, stored_path: Path | str | None = None) -> FirefoxDiscoveryResult:
        if stored_path:
            validated = self.validate_executable(stored_path)
            if validated:
                return FirefoxDiscoveryResult(validated, "stored")

        with contextlib.suppress(Exception):
            for candidate in self.registry_reader():
                validated = self.validate_executable(candidate)
                if validated:
                    return FirefoxDiscoveryResult(validated, "registry")

        for candidate in self.standard_candidates():
            validated = self.validate_executable(candidate)
            if validated:
                return FirefoxDiscoveryResult(validated, "standard_install")
        return FirefoxDiscoveryResult(
            None,
            "missing",
            "Firefox is not installed or no valid firefox.exe could be found.",
        )


def _safe_youtube_url(url: str | None) -> str:
    if not url:
        return DEFAULT_CONNECTION_URL
    try:
        parsed = urlsplit(str(url).strip())
    except ValueError:
        return DEFAULT_CONNECTION_URL
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in YOUTUBE_HOSTS or parsed.username or parsed.password:
        return DEFAULT_CONNECTION_URL
    safe_query = []
    for name, value in parse_qsl(parsed.query, keep_blank_values=True):
        if name.casefold() in _SENSITIVE_QUERY_NAMES:
            continue
        safe_query.append((name, value))
    sanitized = urlunsplit(("https", parsed.netloc, parsed.path or "/", urlencode(safe_query), ""))
    return sanitized if len(sanitized) <= 2048 else DEFAULT_CONNECTION_URL


def _sanitize_failure_reason(reason: str) -> str:
    cleaned = " ".join(str(reason or "").split())
    cleaned = re.sub(
        r"(?i)\b(cookie|authorization|password|token)\s*[:=]\s*\S+",
        r"\1=<redacted>",
        cleaned,
    )
    home = str(Path.home())
    if home:
        cleaned = cleaned.replace(home, "<user-profile>")
    return cleaned[:500]


def _firefox_cookie_database(profile: Path) -> Path:
    return profile / FIREFOX_COOKIE_DATABASE


def profile_lock_reason(profile: Path) -> str:
    for name in FIREFOX_LOCK_FILES:
        if (profile / name).exists():
            return "Dedicated Firefox is still open. Close it before continuing."
    database = _firefox_cookie_database(profile)
    if database.exists() and _windows_file_is_locked(database):
        return "The dedicated Firefox profile is still locked."
    return ""


def _windows_file_is_locked(path: Path) -> bool:
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    create_file = ctypes.windll.kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = ctypes.windll.kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    generic_read = 0x80000000
    open_existing = 3
    file_attribute_normal = 0x80
    invalid_handle = wintypes.HANDLE(-1).value
    handle = create_file(
        str(path),
        generic_read,
        0,
        None,
        open_existing,
        file_attribute_normal,
        None,
    )
    if handle == invalid_handle:
        return ctypes.get_last_error() in {5, 32, 33}
    close_handle(handle)
    return False


def inspect_youtube_session_cookies(profile: Path) -> tuple[bool, str]:
    """Inspect cookie names/domains only; cookie values are never selected."""
    database = _firefox_cookie_database(profile)
    if not database.exists() or not database.is_file():
        return False, "The dedicated profile has no Firefox cookie database yet."
    if profile_lock_reason(profile):
        return False, "The dedicated Firefox profile is still locked."

    uri = f"file:{database.as_posix()}?mode=ro"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        rows = connection.execute(
            "SELECT host, name FROM moz_cookies "
            "WHERE host LIKE '%youtube.com' OR host LIKE '%google.com'"
        )
        for host, name in rows:
            normalized_host = str(host or "").casefold()
            normalized_name = str(name or "").upper()
            if normalized_host.endswith(("youtube.com", "google.com")) and (
                normalized_name in _AUTH_COOKIE_NAMES
            ):
                return True, "YouTube account session markers were found."
    except (OSError, sqlite3.Error):
        return False, "The Firefox cookie database could not be inspected safely."
    finally:
        if connection is not None:
            connection.close()
    return False, "YouTube sign-in was not completed in the dedicated profile."


class YouTubeConnectionManager:
    """Persist sanitized connection state and own one isolated Firefox launch."""

    def __init__(
        self,
        settings: SettingsStore,
        *,
        application_data: Path | None = None,
        discovery: FirefoxDiscovery | None = None,
        popen_factory: PopenFactory = subprocess.Popen,
        identity_provider: IdentityProvider = process_creation_identity,
    ) -> None:
        self.settings = settings
        self.application_data = Path(application_data or app_data_dir())
        self.profile_path = dedicated_firefox_profile_path(self.application_data)
        self.discovery = discovery or FirefoxDiscovery()
        self.popen_factory = popen_factory
        self.identity_provider = identity_provider
        self._process: subprocess.Popen[Any] | None = None
        self._process_identity: FirefoxProcessIdentity | None = None

        self.state = self._load_state()
        self.firefox_path = self._load_path("firefox_path")
        self.last_verified = str(self._value("last_verified", "") or "")
        self.failure_reason = _sanitize_failure_reason(str(self._value("failure_reason", "") or ""))
        self._reconcile_stored_profile()
        self.refresh_browser_state()

    def _key(self, name: str) -> str:
        return f"{SETTINGS_PREFIX}/{name}"

    def _value(self, name: str, default: Any = None) -> Any:
        return self.settings.value(self._key(name), default)

    def _load_state(self) -> ConnectionState:
        raw = str(self._value("state", ConnectionState.NOT_CONFIGURED.value) or "")
        with contextlib.suppress(ValueError):
            return ConnectionState(raw)
        return ConnectionState.ERROR

    def _load_path(self, name: str) -> Path | None:
        raw = str(self._value(name, "") or "").strip()
        return Path(raw) if raw else None

    def _reconcile_stored_profile(self) -> None:
        stored = self._load_path("profile_path")
        if stored:
            try:
                matches = _same_path(_normalized_path(stored), _normalized_path(self.profile_path))
            except (OSError, RuntimeError, ValueError):
                matches = False
            if not matches:
                self._set_state(ConnectionState.INVALID, "Stored dedicated profile path was rejected.")
                self.settings.remove(self._key("profile_path"))
                self.settings.sync()
                return
        if self.state == ConnectionState.CONNECTED:
            try:
                validate_dedicated_profile_path(
                    self.profile_path,
                    application_data=self.application_data,
                )
            except ValueError:
                self._set_state(ConnectionState.INVALID, "Dedicated Firefox profile is unavailable.")

    def snapshot(self) -> ConnectionSnapshot:
        return ConnectionSnapshot(
            self.state,
            self.profile_path,
            self.firefox_path,
            self.last_verified,
            self.failure_reason,
        )

    def _set_state(self, state: ConnectionState, reason: str = "") -> None:
        self.state = state
        self.failure_reason = _sanitize_failure_reason(reason)
        self.settings.setValue(self._key("state"), state.value)
        if self.profile_path.exists():
            self.settings.setValue(self._key("profile_path"), str(self.profile_path))
        if self.failure_reason:
            self.settings.setValue(self._key("failure_reason"), self.failure_reason)
        else:
            self.settings.remove(self._key("failure_reason"))
        self.settings.sync()

    def discover_firefox(self) -> FirefoxDiscoveryResult:
        result = self.discovery.discover(self.firefox_path)
        if result.executable:
            self.firefox_path = result.executable
            self.settings.setValue(self._key("firefox_path"), str(result.executable))
            self.settings.sync()
        else:
            self._set_state(ConnectionState.FIREFOX_MISSING, result.reason)
        return result

    def set_firefox_path(self, path: Path | str) -> bool:
        validated = self.discovery.validate_executable(path)
        if not validated:
            self._set_state(ConnectionState.FIREFOX_MISSING, "Firefox executable is invalid.")
            return False
        self.firefox_path = validated
        self.settings.setValue(self._key("firefox_path"), str(validated))
        self.settings.sync()
        if self.state == ConnectionState.FIREFOX_MISSING:
            self._set_state(ConnectionState.NOT_CONFIGURED)
        return True

    def create_profile(self) -> Path:
        root = youtube_data_root(self.application_data)
        if (
            self.application_data.exists()
            and _is_reparse_point(self.application_data)
        ) or (
            root.exists()
            and _is_reparse_point(root)
        ):
            self._set_state(ConnectionState.INVALID, "Managed YouTube directory is unsafe.")
            raise ValueError("Managed YouTube directory is unsafe.")
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.profile_path.mkdir(parents=False, exist_ok=True, mode=0o700)
            with contextlib.suppress(OSError):
                root.chmod(0o700)
                self.profile_path.chmod(0o700)
            validated = validate_dedicated_profile_path(
                self.profile_path,
                application_data=self.application_data,
            )
        except (OSError, ValueError) as exc:
            self._set_state(ConnectionState.ERROR, "Dedicated profile could not be created.")
            raise RuntimeError("Dedicated profile could not be created.") from exc
        self._set_state(ConnectionState.PROFILE_READY)
        return validated

    def build_launch_command(self, target_url: str | None = None) -> list[str]:
        discovery = self.discovery.discover(self.firefox_path)
        if not discovery.executable:
            self._set_state(ConnectionState.FIREFOX_MISSING, discovery.reason)
            raise RuntimeError("Firefox is not installed.")
        self.firefox_path = discovery.executable
        profile = self.create_profile()
        return [
            str(discovery.executable),
            "-no-remote",
            "-profile",
            str(profile),
            "-url",
            _safe_youtube_url(target_url),
        ]

    def launch(self, target_url: str | None = None) -> FirefoxProcessIdentity:
        self.refresh_browser_state()
        if self.browser_is_open():
            self._set_state(ConnectionState.BROWSER_OPEN, "Dedicated Firefox is already running.")
            raise RuntimeError("Dedicated Firefox is already running.")
        command = self.build_launch_command(target_url)
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "shell": False,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            process = self.popen_factory(command, **kwargs)
        except (OSError, subprocess.SubprocessError) as exc:
            self._set_state(ConnectionState.ERROR, "Dedicated Firefox could not be started.")
            raise RuntimeError("Dedicated Firefox could not be started.") from exc
        identity = self.identity_provider(process.pid) or ""
        self._process = process
        self._process_identity = FirefoxProcessIdentity(process.pid, identity, tuple(command))
        self._set_state(ConnectionState.BROWSER_OPEN)
        return self._process_identity

    def browser_is_open(self) -> bool:
        if self._process is not None and self._process.poll() is None:
            tracked = self._process_identity
            if not tracked or not tracked.creation_identity:
                return True
            current = self.identity_provider(tracked.pid)
            if current == tracked.creation_identity:
                return True
        if self.profile_path.exists() and profile_lock_reason(self.profile_path):
            return True
        return False

    def refresh_browser_state(self) -> ConnectionState:
        if self.browser_is_open():
            if self.state in {
                ConnectionState.BROWSER_OPEN,
                ConnectionState.WAITING_FOR_LOGIN,
                ConnectionState.PROFILE_READY,
            }:
                self._set_state(ConnectionState.BROWSER_OPEN)
            return self.state
        if self._process is not None:
            self._process = None
            self._process_identity = None
        if self.state == ConnectionState.BROWSER_OPEN:
            self._set_state(ConnectionState.WAITING_FOR_LOGIN)
        return self.state

    def verify(self, verifier: Verifier, target_url: str) -> VerificationResult:
        self.refresh_browser_state()
        if self.browser_is_open():
            result = VerificationResult(False, "locked", "Profile is still locked.")
            self._set_state(ConnectionState.LOCKED, result.message)
            return result
        try:
            profile = validate_dedicated_profile_path(
                self.profile_path,
                application_data=self.application_data,
            )
        except ValueError:
            result = VerificationResult(False, "invalid", "Dedicated Firefox profile is invalid.")
            self._set_state(ConnectionState.INVALID, result.message)
            return result
        cookies_present, cookie_reason = inspect_youtube_session_cookies(profile)
        if not cookies_present:
            result = VerificationResult(False, "sign_in_incomplete", cookie_reason)
            self._set_state(ConnectionState.INVALID, result.message)
            return result

        self._set_state(ConnectionState.VERIFYING)
        try:
            result = verifier(profile, _safe_youtube_url(target_url))
        except Exception:
            result = VerificationResult(False, "error", "YouTube session verification failed.")
        if result.success:
            self.last_verified = datetime.now(UTC).isoformat(timespec="seconds")
            self.settings.setValue(self._key("last_verified"), self.last_verified)
            self._set_state(ConnectionState.CONNECTED)
        elif result.code in {"expired", "session_rejected", "authentication_required"}:
            self._set_state(ConnectionState.EXPIRED, result.message)
        elif result.code == "locked":
            self._set_state(ConnectionState.LOCKED, result.message)
        elif result.code == "invalid":
            self._set_state(ConnectionState.INVALID, result.message)
        else:
            self._set_state(ConnectionState.ERROR, result.message)
        return result

    def mark_expired(self, reason: str = "YouTube session expired.") -> None:
        self._set_state(ConnectionState.EXPIRED, reason)

    def connected_profile(self) -> Path | None:
        if self.state != ConnectionState.CONNECTED:
            return None
        try:
            return validate_dedicated_profile_path(
                self.profile_path,
                application_data=self.application_data,
            )
        except ValueError:
            self._set_state(ConnectionState.INVALID, "Dedicated Firefox profile is unavailable.")
            return None

    def disconnect(self) -> DisconnectResult:
        self.refresh_browser_state()
        if self.browser_is_open():
            result = DisconnectResult(
                False,
                "locked",
                "Close the dedicated Firefox window before disconnecting.",
            )
            self._set_state(ConnectionState.LOCKED, result.message)
            return result
        if not self.profile_path.exists():
            self._clear_connection_settings()
            self.state = ConnectionState.DISCONNECTED
            return DisconnectResult(True, "disconnected", "YouTube is disconnected.")
        try:
            profile = validate_dedicated_profile_path(
                self.profile_path,
                application_data=self.application_data,
            )
            if profile_lock_reason(profile):
                raise PermissionError("profile is locked")
            self._reject_reparse_tree(profile)
            shutil.rmtree(profile)
        except (OSError, ValueError) as exc:
            result = DisconnectResult(
                False,
                "remove_failed",
                "Dedicated profile could not be removed.",
                self.profile_path,
            )
            detail = "Dedicated profile could not be removed safely."
            if isinstance(exc, PermissionError):
                detail = "Dedicated Firefox profile is still locked."
            self._set_state(ConnectionState.ERROR, detail)
            return result
        self._clear_connection_settings()
        self.state = ConnectionState.DISCONNECTED
        return DisconnectResult(True, "disconnected", "YouTube is disconnected.")

    @staticmethod
    def _reject_reparse_tree(profile: Path) -> None:
        if _is_reparse_point(profile):
            raise ValueError("managed profile is a reparse point")
        for root, directories, files in os.walk(profile, topdown=True, followlinks=False):
            for name in [*directories, *files]:
                candidate = Path(root) / name
                if _is_reparse_point(candidate):
                    raise ValueError("managed profile contains a reparse point")

    def _clear_connection_settings(self) -> None:
        for name in ("state", "profile_path", "last_verified", "failure_reason"):
            self.settings.remove(self._key(name))
        self.settings.sync()
        self.last_verified = ""
        self.failure_reason = ""


__all__ = [
    "ConnectionSnapshot",
    "ConnectionState",
    "DEFAULT_CONNECTION_URL",
    "DisconnectResult",
    "FirefoxDiscovery",
    "FirefoxDiscoveryResult",
    "FirefoxProcessIdentity",
    "VerificationResult",
    "YouTubeConnectionManager",
    "dedicated_firefox_profile_path",
    "inspect_youtube_session_cookies",
    "profile_lock_reason",
    "validate_dedicated_profile_path",
    "youtube_data_root",
]
