"""Fail closed when a Windows EXE crosses the audited distribution boundary."""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Protocol

from PyInstaller.archive.readers import CArchiveReader

CPYTHON_LIBFFI_SHA256 = (
    "d1682615247e165ba8aa0cff59e090a0b1b6b90793e48733f441dff8d8e6328e"
)
CPYTHON_CTYPES_SHA256 = (
    "6968228b18fc86b0b02f3dbf2c879c2c6f689a66130a72f35a3f0b2755d99e41"
)
ROOT_LIBFFI_PATH = "libffi-8.dll"
ROOT_CTYPES_PATH = "_ctypes.pyd"
LICENSE_MANIFEST_PATH = "licenses/RELEASE-LICENSE-MANIFEST.sha256"

ALLOWED_PYSIDE_ROOT_NATIVE = frozenset(
    {
        "pyside6/msvcp140.dll",
        "pyside6/msvcp140_1.dll",
        "pyside6/msvcp140_2.dll",
        "pyside6/opengl32sw.dll",
        "pyside6/pyside6.abi3.dll",
        "pyside6/qt6core.dll",
        "pyside6/qt6gui.dll",
        "pyside6/qt6widgets.dll",
        "pyside6/qtcore.pyd",
        "pyside6/qtgui.pyd",
        "pyside6/qtwidgets.pyd",
        "pyside6/vcruntime140.dll",
        "pyside6/vcruntime140_1.dll",
    }
)
ALLOWED_QT_PLUGINS = frozenset(
    {
        "pyside6/plugins/imageformats/qico.dll",
        "pyside6/plugins/platforms/qoffscreen.dll",
        "pyside6/plugins/platforms/qwindows.dll",
        "pyside6/plugins/styles/qmodernwindowsstyle.dll",
    }
)
REQUIRED_PYSIDE_PATHS = ALLOWED_PYSIDE_ROOT_NATIVE | ALLOWED_QT_PLUGINS | {
    "shiboken6/shiboken.pyd",
    "shiboken6/shiboken6.abi3.dll",
}

REQUIRED_COMPLIANCE_PATHS: tuple[str, ...] = (
    "LICENSE",
    "THIRD_PARTY_LICENSES.txt",
    "THIRD_PARTY_NOTICES.md",
    "docs/DEPENDENCY-SOURCE.md",
    "docs/BUILD-REPRODUCIBILITY.md",
    "docs/LGPL-COMPLIANCE.md",
    "docs/QT-REPLACEMENT-GUIDE.md",
    "docs/QT-BUILD-PROVENANCE.md",
    "docs/OPTIONAL-PO-PROVIDER.md",
    "requirements.lock",
    "SOURCE-HASHES.sha256",
    LICENSE_MANIFEST_PATH,
)

_MANIFEST_LINE = re.compile(r"^([0-9a-fA-F]{64})[ \t]+\*?(.+?)\s*$")
_SOURCE_HASH_LINE = re.compile(r"^([0-9a-f]{64})  ([^\\]+)$")
_INVENTORY_FINGERPRINT = re.compile(
    r"(?m)^Audited non-compliance payload fingerprint SHA-256: ([0-9a-f]{64})\s*$"
)
_PYQT_TOKEN = re.compile(r"(?:^|[./_\\-])pyqt(?:5|6)?(?:$|[./_\\-])", re.I)
_PROVIDER_TOKEN = re.compile(
    r"(?:^|[./_\\-])(?:bgutil|getpot)(?:$|[./_\\-])"
    r"|(?:^|[./\\])(?:yt_dlp_plugins|yt-dlp-plugins)(?:$|[./\\])",
    re.I,
)
_RAW_JAVASCRIPT_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".js.map")
_CODE_OR_BINARY_SUFFIXES = (
    ".dll",
    ".dylib",
    ".exe",
    ".pyd",
    ".py",
    ".pyc",
    ".so",
)


class _EmbeddedArchive(Protocol):
    toc: dict[str, object]

    def extract(self, name: str, raw: bool = False) -> bytes | None: ...


class _CArchive(Protocol):
    toc: dict[str, tuple[object, ...]]

    def extract(self, name: str) -> bytes: ...

    def open_embedded_archive(self, name: str) -> _EmbeddedArchive: ...


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fingerprint_payload_identity(path: str, payload: bytes) -> tuple[bytes, int, bytes]:
    if path.casefold() != "base_library.zip":
        return b"RAW", len(payload), hashlib.sha256(payload).digest()

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zip_archive:
            members = zip_archive.infolist()
            names = [member.filename.replace("\\", "/") for member in members]
            folded = [name.casefold() for name in names]
            if len(folded) != len(set(folded)):
                raise ValueError("base_library.zip contains duplicate member paths")
            records = []
            for member, name in zip(members, names, strict=True):
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts:
                    raise ValueError(
                        f"base_library.zip contains unsafe member path: {name}"
                    )
                records.append((name, zip_archive.read(member)))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"cannot inspect base_library.zip: {exc}") from exc

    digest = hashlib.sha256()
    total_size = 0
    for name, data in sorted(records, key=lambda item: (item[0].casefold(), item[0])):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
        total_size += len(data)
    return b"CANONICAL-ZIP-CONTENT-V1", total_size, digest.digest()


def _normalize_archive_path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./")


def _safe_manifest_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/").removeprefix("./")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe manifest path: {value!r}")
    return path


def _parse_manifest(payload: str) -> dict[PurePosixPath, str]:
    records: dict[PurePosixPath, str] = {}
    for line_number, raw_line in enumerate(payload.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _MANIFEST_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"invalid manifest line {line_number}: {raw_line!r}")
        path = _safe_manifest_path(match.group(2))
        if path in records:
            raise ValueError(f"duplicate manifest path: {path.as_posix()}")
        records[path] = match.group(1).lower()
    if not records:
        raise ValueError("manifest has no file records")
    return records


def _entry_type(entry: tuple[object, ...]) -> str:
    return str(entry[-1]) if entry else ""


def _is_code_or_binary(path: str, typecode: str) -> bool:
    lowered = path.casefold()
    return typecode in {"m", "s"} or lowered.endswith(_CODE_OR_BINARY_SUFFIXES)


def _is_documentation_path(path: str) -> bool:
    lowered = path.casefold()
    return lowered.startswith(("docs/", "licenses/")) or lowered in {
        "license",
        "third_party_licenses.txt",
        "third_party_notices.md",
    }


def _scan_carchive_names(
    archive: _CArchive,
    normalized: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    for archive_name in archive.toc:
        path = _normalize_archive_path(archive_name)
        lowered = path.casefold()
        if lowered.endswith(_RAW_JAVASCRIPT_SUFFIXES):
            errors.append(f"raw JavaScript/TypeScript payload is forbidden: {path}")
        if "node_modules/canvas/" in lowered or lowered.endswith("/canvas.node") or lowered == "canvas.node":
            errors.append(f"canvas native/provider payload is forbidden: {path}")
        if _PYQT_TOKEN.search(lowered) and not _is_documentation_path(path):
            errors.append(f"PyQt code or binary is forbidden: {path}")
        if _PROVIDER_TOKEN.search(lowered) and not _is_documentation_path(path):
            errors.append(f"in-process provider code is forbidden: {path}")

    folded: dict[str, list[str]] = {}
    for original, path in normalized.items():
        folded.setdefault(path.casefold(), []).append(original)
    collisions = [values for values in folded.values() if len(values) > 1]
    for values in collisions:
        errors.append("case-insensitive archive path collision: " + ", ".join(sorted(values)))
    return errors


def _verify_pyz(archive: _CArchive) -> list[str]:
    errors: list[str] = []
    pyz_names = [name for name, entry in archive.toc.items() if _entry_type(entry) == "z"]
    if len(pyz_names) != 1:
        return [f"expected exactly one embedded PYZ archive, found {len(pyz_names)}"]
    try:
        pyz = archive.open_embedded_archive(pyz_names[0])
    except Exception as exc:  # PyInstaller exposes several archive-specific exceptions.
        return [f"cannot inspect embedded PYZ archive: {exc}"]

    module_names = [str(name) for name in pyz.toc]
    for module_name in module_names:
        lowered = module_name.casefold()
        if _PYQT_TOKEN.search(lowered):
            errors.append(f"PyQt module is forbidden in embedded PYZ: {module_name}")
        if _PROVIDER_TOKEN.search(lowered):
            errors.append(f"provider module is forbidden in embedded PYZ: {module_name}")

    if not any(name.casefold() == "pyside6" for name in module_names):
        errors.append("embedded PYZ does not contain the required PySide6 package")
    return errors


def _verify_pyside_payload(archive: _CArchive, normalized: dict[str, str]) -> list[str]:
    errors: list[str] = []
    folded = {path.casefold() for path in normalized.values()}
    if not any(path.startswith("pyside6/") for path in folded):
        errors.append("archive does not contain a PySide6 binary payload")

    missing = sorted(REQUIRED_PYSIDE_PATHS - folded)
    if missing:
        errors.append("archive is missing audited PySide6/Qt paths: " + ", ".join(missing))

    audited_paths = {
        path
        for path in folded
        if path.startswith(("pyside6/plugins/", "pyside6/translations/"))
        or (
            len(PurePosixPath(path).parts) == 2
            and path.startswith("pyside6/")
            and path.endswith((".dll", ".pyd"))
        )
    }
    unexpected = sorted(audited_paths - ALLOWED_PYSIDE_ROOT_NATIVE - ALLOWED_QT_PLUGINS)
    if unexpected:
        errors.append("archive contains unaudited PySide6/Qt paths: " + ", ".join(unexpected))
    return errors


def _verify_libffi(archive: _CArchive, normalized: dict[str, str]) -> list[str]:
    errors: list[str] = []
    libffi_names = [
        name
        for name, path in normalized.items()
        if PurePosixPath(path.casefold()).name.startswith("libffi")
        and PurePosixPath(path.casefold()).suffix == ".dll"
    ]
    root_names = [
        name for name in libffi_names if normalized[name].casefold() == ROOT_LIBFFI_PATH
    ]
    if len(libffi_names) != 1:
        rendered = [normalized[name] for name in libffi_names]
        errors.append(
            "archive must contain exactly one libffi DLL at root "
            f"({ROOT_LIBFFI_PATH}); found {rendered}"
        )
    if len(root_names) != 1:
        errors.append(
            f"archive must contain exactly one root {ROOT_LIBFFI_PATH}; "
            f"found {[normalized[name] for name in root_names]}"
        )
        return errors
    archive_name = root_names[0]
    actual_hash = _sha256(archive.extract(archive_name))
    if actual_hash != CPYTHON_LIBFFI_SHA256:
        errors.append(
            f"archive hash mismatch for {ROOT_LIBFFI_PATH}: "
            f"expected {CPYTHON_LIBFFI_SHA256}, got {actual_hash}"
        )

    ctypes_names = [
        name for name, path in normalized.items() if path.casefold() == ROOT_CTYPES_PATH
    ]
    if len(ctypes_names) != 1:
        errors.append(
            f"archive must contain exactly one root {ROOT_CTYPES_PATH}; "
            f"found {[normalized[name] for name in ctypes_names]}"
        )
    else:
        ctypes_hash = _sha256(archive.extract(ctypes_names[0]))
        if ctypes_hash != CPYTHON_CTYPES_SHA256:
            errors.append(
                f"archive hash mismatch for {ROOT_CTYPES_PATH}: "
                f"expected {CPYTHON_CTYPES_SHA256}, got {ctypes_hash}"
            )
    return errors


def _verify_license_manifest(archive: _CArchive, normalized: dict[str, str]) -> list[str]:
    errors: list[str] = []
    by_folded_path = {path.casefold(): name for name, path in normalized.items()}
    manifest_name = by_folded_path.get(LICENSE_MANIFEST_PATH.casefold())
    if manifest_name is None:
        return [f"missing required compliance path: {LICENSE_MANIFEST_PATH}"]
    try:
        manifest = _parse_manifest(archive.extract(manifest_name).decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        return [f"invalid packaged license manifest: {exc}"]

    actual_license_paths = {
        PurePosixPath(path[len("licenses/") :])
        for path in normalized.values()
        if path.casefold().startswith("licenses/")
        and path.casefold() != LICENSE_MANIFEST_PATH.casefold()
    }
    if set(manifest) != actual_license_paths:
        unlisted = sorted(actual_license_paths - set(manifest), key=str)
        absent = sorted(set(manifest) - actual_license_paths, key=str)
        errors.append(
            "packaged license manifest coverage mismatch: "
            f"unlisted={[path.as_posix() for path in unlisted]}, "
            f"absent={[path.as_posix() for path in absent]}"
        )

    for relative_path, expected_hash in manifest.items():
        packaged_path = f"licenses/{relative_path.as_posix()}"
        archive_name = by_folded_path.get(packaged_path.casefold())
        if archive_name is None:
            continue
        payload = archive.extract(archive_name)
        if not payload:
            errors.append(f"packaged license file is empty: {packaged_path}")
        elif _sha256(payload) != expected_hash:
            errors.append(f"packaged license hash mismatch: {packaged_path}")
    return errors


def _verify_source_hash_manifest(archive: _CArchive, normalized: dict[str, str]) -> list[str]:
    by_folded_path = {path.casefold(): name for name, path in normalized.items()}
    manifest_name = by_folded_path.get("source-hashes.sha256")
    if manifest_name is None:
        return []  # The common compliance-path check reports this once.
    try:
        lines = archive.extract(manifest_name).decode("utf-8-sig").splitlines()
    except UnicodeError as exc:
        return [f"invalid packaged SOURCE-HASHES.sha256: {exc}"]

    errors: list[str] = []
    records: dict[str, str] = {}
    for line_number, line in enumerate(lines, 1):
        match = _SOURCE_HASH_LINE.fullmatch(line)
        if match is None:
            errors.append(
                "invalid packaged SOURCE-HASHES.sha256 line "
                f"{line_number}; expected lowercase '<sha256>  <relative/posix-path>'"
            )
            continue
        try:
            path = _safe_manifest_path(match.group(2)).as_posix()
        except ValueError as exc:
            errors.append(f"invalid packaged source-hash path: {exc}")
            continue
        if path != match.group(2):
            errors.append(f"non-canonical source-hash path: {match.group(2)}")
        elif path in records:
            errors.append(f"duplicate packaged source-hash path: {path}")
        else:
            records[path] = match.group(1)
    if not records:
        errors.append("packaged SOURCE-HASHES.sha256 has no valid file records")

    # Build/source manifests may cover files intentionally supplied only in the
    # corresponding-source companion. If a listed file is also in the EXE,
    # however, its packaged bytes must match the declared source hash.
    for path, expected_hash in records.items():
        archive_name = by_folded_path.get(path.casefold())
        if archive_name is not None and _sha256(archive.extract(archive_name)) != expected_hash:
            errors.append(f"packaged source-hash mismatch: {path}")
    return errors


def _calculate_payload_fingerprint(
    archive: _CArchive, normalized: dict[str, str]
) -> str:
    compliance_folded = {path.casefold() for path in REQUIRED_COMPLIANCE_PATHS}
    digest = hashlib.sha256()
    for archive_name, path in sorted(
        normalized.items(), key=lambda item: (item[1].casefold(), item[1])
    ):
        if (
            _entry_type(archive.toc[archive_name]) == "z"
            or path.casefold() in compliance_folded
            or _is_documentation_path(path)
        ):
            continue
        payload = archive.extract(archive_name)
        identity_kind, identity_size, identity_digest = _fingerprint_payload_identity(
            path, payload
        )
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_entry_type(archive.toc[archive_name]).encode("ascii", "replace"))
        digest.update(b"\0")
        digest.update(identity_kind)
        digest.update(b"\0")
        digest.update(str(identity_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(identity_digest)

    pyz_names = [name for name, entry in archive.toc.items() if _entry_type(entry) == "z"]
    if len(pyz_names) != 1:
        raise ValueError(f"expected exactly one embedded PYZ archive, found {len(pyz_names)}")
    pyz = archive.open_embedded_archive(pyz_names[0])
    for module_name in sorted(
        (str(name) for name in pyz.toc),
        key=lambda item: (item.casefold(), item),
    ):
        raw_module = pyz.extract(module_name, raw=True)
        if raw_module is None:
            raw_module = b""
        if not isinstance(raw_module, bytes):
            raise ValueError(
                f"embedded PYZ extraction did not return bytes: {module_name}"
            )
        entry = pyz.toc[module_name]
        entry_type = entry[0] if isinstance(entry, (tuple, list)) and entry else "UNKNOWN"
        digest.update(b"PYZ\0")
        digest.update(module_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry_type).encode("ascii", "replace"))
        digest.update(b"\0")
        digest.update(str(len(raw_module)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(raw_module).digest())
    return digest.hexdigest()


def _verify_distribution_inventory(
    archive: _CArchive, normalized: dict[str, str]
) -> list[str]:
    errors: list[str] = []
    inventory_name = next(
        (
            name
            for name, path in normalized.items()
            if path.casefold() == "third_party_licenses.txt"
        ),
        None,
    )
    if inventory_name is None:
        return []  # The common compliance-path check reports this once.
    try:
        text = archive.extract(inventory_name).decode("utf-8-sig")
    except UnicodeError as exc:
        return [f"invalid packaged THIRD_PARTY_LICENSES.txt: {exc}"]

    status_patterns = {
        "public verdict": r"(?m)^Public-distribution verdict: (HOLD|PASS)\s*$",
        "release gate": r"(?m)^Release-gate-status: (HOLD|PASS)\s*$",
        "qualified review": r"(?m)^Qualified-review-status: (HOLD|PASS)\s*$",
    }
    statuses: dict[str, str] = {}
    for label, pattern in status_patterns.items():
        matches = re.findall(pattern, text)
        if len(matches) != 1:
            errors.append(f"packaged inventory has no unique {label} status")
        else:
            statuses[label] = matches[0]
    blocker_matches = re.findall(r"(?m)^Audit-blocker-count: ([0-9]+)\s*$", text)
    blocker_count: int | None = None
    if len(blocker_matches) != 1:
        errors.append("packaged inventory has no unique audit blocker count")
    else:
        blocker_count = int(blocker_matches[0])

    status_values = set(statuses.values())
    if len(statuses) == len(status_patterns) and len(status_values) != 1:
        errors.append("packaged inventory has inconsistent audit status fields")
    elif status_values == {"HOLD"} and blocker_count == 0:
        errors.append("packaged HOLD inventory must declare at least one audit blocker")
    elif status_values == {"PASS"} and blocker_count != 0:
        errors.append("packaged PASS inventory must declare zero audit blockers")

    match = _INVENTORY_FINGERPRINT.search(text)
    if match is None:
        errors.append("packaged inventory has no audited payload fingerprint")
    else:
        try:
            actual = _calculate_payload_fingerprint(archive, normalized)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"cannot calculate packaged payload fingerprint: {exc}")
        else:
            if match.group(1) != actual:
                errors.append(
                    "packaged inventory payload fingerprint mismatch: "
                    f"expected {match.group(1)}, got {actual}"
                )

    for zero_row in (
        "| PyQt code/binary/module | 0 | 0 | 0 |",
        "| bgutil/getpot/yt_dlp_plugins provider code/module | 0 | 0 | 0 |",
        "| Raw JavaScript/TypeScript payload | 0 | 0 | 0 |",
        "| canvas native/module payload | 0 | 0 | 0 |",
    ):
        if zero_row not in text:
            errors.append(f"packaged inventory lacks verified zero-count row: {zero_row}")

    inventoried_paths = {
        path
        for path in normalized.values()
        if path.casefold().endswith((".dll", ".pyd", ".exe"))
        or path.casefold().startswith(
            ("pyside6/plugins/", "pyside6/translations/")
        )
    }
    missing_paths = sorted(path for path in inventoried_paths if f"| {path} |" not in text)
    if missing_paths:
        errors.append(
            "packaged inventory omits native/Qt paths: " + ", ".join(missing_paths)
        )
    return errors


def verify_archive(archive: _CArchive) -> list[str]:
    """Return release-blocking errors for an already-open CArchive."""
    normalized = {name: _normalize_archive_path(name) for name in archive.toc}
    folded_paths = {path.casefold() for path in normalized.values()}
    errors = _scan_carchive_names(archive, normalized)

    missing = [
        path for path in REQUIRED_COMPLIANCE_PATHS if path.casefold() not in folded_paths
    ]
    if missing:
        errors.append("missing required compliance paths: " + ", ".join(missing))

    errors.extend(_verify_pyz(archive))
    errors.extend(_verify_pyside_payload(archive, normalized))
    errors.extend(_verify_libffi(archive, normalized))
    errors.extend(_verify_source_hash_manifest(archive, normalized))
    errors.extend(_verify_distribution_inventory(archive, normalized))
    if LICENSE_MANIFEST_PATH.casefold() in folded_paths:
        errors.extend(_verify_license_manifest(archive, normalized))
    return errors


def verify(executable: Path) -> list[str]:
    """Return release-blocking archive errors for *executable*."""
    try:
        archive = CArchiveReader(str(executable))
    except Exception as exc:  # Keep malformed/not-PyInstaller artifacts fail closed.
        return [f"cannot read PyInstaller CArchive: {exc}"]
    return verify_archive(archive)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve()
    if not executable.is_file():
        parser.error(f"executable does not exist: {executable}")

    errors = verify(executable)
    if errors:
        for error in errors:
            print(f"HOLD: {error}")
        return 1
    print("PASS: packaged PySide6 boundary, notices, manifests, and CPython libffi verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
