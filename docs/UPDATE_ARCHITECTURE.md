# Neural Extractor V3 Update Architecture

## Release 3.0.2

Version 3.0.2 is the bootstrap release for the Windows self-updater. Version
3.0.1 can discover a release but cannot replace itself, so users of 3.0.1 must
install 3.0.2 manually once. A packaged 3.0.2 installation can perform the
complete confirmed update flow for 3.0.3 and later releases.

The existing YouTube HTTP 403 retry hardening is included in 3.0.2. Update work
does not alter download naming, Mix/RDMM normalization, queueing, cancellation,
subtitles, thumbnails, cookies, browser-cookie fallback, Node, EJS, or ffmpeg
behavior.

## Previous Limitation

The earlier updater checked the latest GitHub Release and opened a browser. It
did not download, verify, install, restart, confirm startup, or roll back an
update. Asset selection could also accept an ambiguous EXE name.

## Trust Model

The automatic source is pinned in code to the official repository:

```text
AegisAI-Dev/NeuralExtractor
```

Only the latest non-draft, non-prerelease GitHub Release is considered. The
updater accepts only HTTPS URLs matching exact release-asset URLs in that
repository. It never uses a repository or local target supplied by release
metadata, command-line users, or environment variables.

The strict manifest and the package are obtained through TLS with certificate
verification, explicit timeouts, and bounded streaming. SHA-256 protects the
package against corruption and a package/manifest mismatch. It does not protect
against compromise of the official GitHub repository, release credentials, or
the build pipeline because the manifest is not independently signed.

There is currently no Authenticode signing certificate or signature-validation
step. Do not describe the EXE as publisher-signed.

## Release Assets

For release `X.Y.Z`, automatic installation requires exactly:

```text
NeuralExtractorV3-X.Y.Z-windows-x64.exe
NeuralExtractorV3-X.Y.Z-manifest.json
```

The workflow also publishes this human-verification sidecar:

```text
NeuralExtractorV3-X.Y.Z-windows-x64.exe.sha256
```

`NeuralExtractorV3.exe` may remain as a convenience download, but the automatic
updater never selects it.

## Manifest Format

Schema version 1 contains exactly these required fields plus one optional field:

```json
{
  "application_name": "Neural Extractor V3",
  "architecture": "x64",
  "asset_filename": "NeuralExtractorV3-3.0.2-windows-x64.exe",
  "asset_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "asset_size": 123456789,
  "channel": "stable",
  "minimum_updater_version": "3.0.2",
  "platform": "windows",
  "release_version": "3.0.2",
  "schema_version": 1
}
```

Parsing rejects duplicate keys, unknown fields, missing fields, invalid numeric
versions, release/manifest mismatches, same versions, downgrades, wrong platform
or architecture, non-stable channels, path separators, unexpected filenames,
invalid hashes, and implausible sizes.

## Download And Verification

1. The app selects the exact versioned EXE and manifest from GitHub metadata.
2. GitHub's reported EXE size must equal the manifest size.
3. The EXE streams into a random `.part` file below
   `%LOCALAPPDATA%\NeuralExtractorV3\updates\<version>\package`.
4. Content-Length, actual byte count, manifest size, and the global maximum size
   are enforced.
5. The file is flushed and closed, then SHA-256 is recalculated locally.
6. Only a size- and hash-matched file is atomically promoted to the staged EXE.
7. A cached staged EXE is reused only after a fresh size and SHA-256 check.

A checksum mismatch removes the partial file and cannot reach installation.

## Installation Sequence

1. The GUI shows current/new versions, release details, size, and a user-confirmed
   `Download and Install` action.
2. The app checks packaged Windows mode, official target name, writable install
   directory, safe non-temporary location, and free space.
3. The running EXE copies itself to
   `%LOCALAPPDATA%\NeuralExtractorV3\updater-helper\NeuralExtractorV3-Updater.exe`.
4. It creates a strict transaction with a random token and a single installation
   lock, then starts the helper with `--apply-update <transaction.json>`.
5. The GUI exits only after the detached helper is ready.
6. The helper validates paths, token, lock owner, version, size, disk space, and
   hashes again, then waits up to a bounded timeout for the GUI process to exit.
7. It creates and verifies a backup before copying and replacing the target EXE.
8. Windows file-lock failures are retried for a bounded number of attempts.
9. The new EXE starts directly with a token-bound private startup mode. No shell,
   PowerShell, cmd.exe, batch file, system Python, UAC request, or silent
   elevation is used.

## Startup Confirmation And Rollback

Process creation alone is not success. After the Qt application and main window
initialize, the new process writes a token- and version-bound marker inside its
controlled transaction directory. The helper accepts only that exact marker and
waits for it with a bounded timeout.

After confirmation, the helper records success and removes the backup. If the
success record itself cannot be written, it keeps the verified backup
conservatively. Confirmed-success transaction metadata is cleaned only after the
retention period.

If replacement, launch, early startup, or confirmation fails, the helper stops
the failed new process, verifies and restores the backup, verifies the restored
EXE, and restarts the previous version. The restored app reports rollback status.
If rollback fails, recoverable files remain in place and a native recovery
message gives the exact backup and target paths. Sanitized helper events are in:

```text
%LOCALAPPDATA%\NeuralExtractorV3\updates\updater.log
```

## Permissions And Manual Fallback

Automatic installation is unavailable when the app runs from source, from a
PyInstaller temporary extraction/update staging path, under a non-official EXE
name, outside Windows, in a non-writable directory, or without sufficient free
space. The app does not request elevation. In these cases the update dialog
explains the reason and keeps the `Open Download Page` manual fallback.

## Publishing 3.0.2

The workflow supports tag pushes matching `v*.*.*` and explicit
`workflow_dispatch`. It validates that the requested release version, runtime
`VERSION`, and `pyproject.toml` version are identical numeric `X.Y.Z` values
before dependencies, tests, build, manifest generation, or publishing.

Recommended owner procedure without Git CLI:

1. In GitHub Desktop, review the local file list and diff.
2. Commit the complete 3.0.2 source and documentation changes locally.
3. Push the branch with GitHub Desktop.
4. Merge that branch into the repository's default branch using the GitHub web
   interface, then confirm the default branch contains version 3.0.2 and the
   updated workflow.
5. Confirm that tag `v3.0.2` does not already exist. In GitHub Actions, open
   `Build and Release Neural Extractor V3`, choose `Run workflow`, select the
   default branch, enter exactly `3.0.2`, and run it.
6. Wait for validation, tests, PyInstaller, checksum, manifest, artifact upload,
   and GitHub Release publication to complete.
7. On the `v3.0.2` release page, verify that the versioned EXE, manifest, checksum,
   and optional unversioned convenience EXE are present.
8. Download the manifest and versioned EXE on a clean Windows profile, compare
   size and SHA-256, launch it, and test the manual update check before announcing
   the release.

`workflow_dispatch` is shown in the Actions UI only after this workflow exists on
the default branch. The manual run requires a new tag, then creates tag `v3.0.2`
and the GitHub Release automatically. An existing tag makes the manual workflow
fail rather than reusing an ambiguous release target.

## Upgrade Expectations

- `3.0.1 -> 3.0.2`: detect the release, open its page, close Neural Extractor,
  manually place/run the 3.0.2 EXE once.
- `3.0.2 -> 3.0.3+`: check, confirm, download, verify, install, restart, confirm
  startup, and clean up automatically; roll back automatically on failure.
- Updates are optional. There are no forced or silent replacements.
