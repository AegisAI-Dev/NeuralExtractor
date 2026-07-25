# Python runtime reproducibility record

Release-gate-status: **HOLD**

Immediate-binary-provenance: **26 OF 26 MATCH**

Independent-clean-rebuild: **NOT COMPLETED**

This document separates two facts that must not be conflated:

1. The selected runtime bytes in the audited artifact match an exact retained
   python-build-standalone 20250317 archive.
2. This workspace does not yet contain enough recorded environment evidence to
   reproduce that upstream release independently and attribute any resulting
   byte differences.

It is an engineering record, not legal advice. Reproducibility is used as a
fail-closed release criterion here; it is not presented as a universal legal
test.

## Evidence already established

`third_party_sources/python-runtime/RUNTIME-ASSET-COMPARISON.json` opens the
retained compressed runtime asset directly and hashes each relevant member.
For every selected CPython/PBS DLL or PYD, it records the final path/hash, source
member path/hash, and equality result. All 26 records match.

The retained PBS commit includes:

- top-level `build-windows.py` orchestration;
- `cpython-windows/build.py` implementation;
- `pythonbuild/downloads.py` versions, URLs, and expected hashes;
- Windows patches and support code;
- dependency license files and `python-licenses.rst`;
- upstream building and testing documentation.

The actual source/input hashes are machine-checked by
`third_party_sources/python-runtime/SOURCE-MANIFEST.json`.

## Rebuild preparation, not a completed recipe

The upstream documentation starts Windows builds from a Visual Studio native
tools environment and uses a command shaped like:

```powershell
py.exe build-windows.py --python cpython-3.12 --sh C:\cygwin64\bin\sh.exe --options <release-options>
```

Do not treat that command as the exact 20250317 production invocation. The
following values have not been recovered from an original release log:

- exact Visual Studio 2022 edition and point build;
- exact MSVC toolset selection;
- exact Windows SDK version selected during compilation;
- exact Cygwin package versions;
- the release's complete option/profile selection, including optimization and
  profile-guided build details;
- environment variables and runner image identity;
- locale, timezone, filesystem-path, clock, and signing/timestamp inputs;
- the original command line and complete stdout/stderr build log.

The PBS recipe also obtains libffi from a source-control checkout. The exact
source snapshot used by the recipe is retained as commit
`16fad4855b3d8c03b5910e405ff3a04395b39a98`, but source-control metadata and the
original checkout transcript are not.

## Required clean-rebuild protocol

Before changing this gate to PASS:

1. Provision an isolated Windows x64 build host and record its image digest or
   equivalent immutable identity.
2. Record Visual Studio, MSVC, Windows SDK, Cygwin, Python driver, Perl, NASM,
   jom, and every other tool version before the build.
3. Disable unrecorded downloads. Populate the recipe only from the retained,
   hash-verified inputs or add every missing input to the manifest first.
4. Record the exact command line, environment allowlist, source paths, complete
   stdout/stderr, exit codes, and produced archive hashes.
5. Run the upstream distribution tests retained with the recipe.
6. Compare every selected DLL/PYD with
   `RUNTIME-ASSET-COMPARISON.json`. If bytes differ, preserve the new binary,
   map the differences to documented toolchain/build inputs, and perform
   functional/API compatibility tests; do not silently relabel it as the
   audited upstream asset.
7. Rebuild the PyInstaller application from locked inputs and rerun the final
   native inventory and application smoke tests.
8. Obtain qualified review of the resulting source/notices package and the
   separate Microsoft redistribution record.

## Local evidence checks

```powershell
.\.venv\Scripts\python.exe scripts\runtime_closure\generate_runtime_evidence.py --check
.\.venv\Scripts\python.exe scripts\runtime_closure\generate_runtime_evidence.py --check --release-gate
```

`--check` must succeed and report no stale files. `--release-gate` must continue
to return nonzero while any generated record is HOLD. The generator performs no
network request, Git operation, publication, or remote mutation.

## Current blockers

- No original PBS 20250317 Windows release build log is retained.
- The exact buildhost/toolchain point versions are unresolved.
- No independent clean rebuild has been completed.
- No complete explanation of reproducibility differences exists.
- Microsoft runtime redistribution entitlement remains unresolved.

Result: exact immediate byte provenance is established; independent source
reproducibility is not. Public distribution remains **HOLD**.
