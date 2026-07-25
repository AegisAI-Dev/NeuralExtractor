# Existing Neural Extractor V3 release compliance review

Status: **HOLD — evidence collection and qualified legal review required**  
Review date: **2026-07-22**

This is a local engineering review, not legal advice. It does not declare that
any historical distribution complied or failed to comply with a license. It
does not authorize changing or deleting a release.

## Scope and evidence limits

This review used only the current local working copy, directly readable local
Git reflog/tag-ref files, release notes, manifests, checksum files, and binaries
under `dist/`. No Git command, remote API, browser query, GitHub CLI operation,
download, upload, or remote mutation was performed.

Consequently, **the set of actually published V3 releases is not established by
this review**. A local tag, commit message, README statement, or release note is
evidence of local release intent/history, not proof that a remote release was
published, which assets it contained, what notices/source accompanied it, when
it was accessible, or whether it was later changed. Those matters are marked
`UNKNOWN — remote release evidence required`.

## Local version-history evidence

| Version | Local evidence | Local tag target | Publication status |
|---|---|---|---|
| 3.0.0 | Initial reflog message `Release Neural Extractor V3.0.0`; local tag ref | `1eff9308d8e0ce17a1fc4a914ae4f8c338bdc485` | UNKNOWN |
| 3.0.1 | No local tag ref, version-specific note, manifest, checksum, or binary found | None found | UNKNOWN, including whether this version existed publicly |
| 3.0.2 | Local release commit messages, local tag ref, and later documentation discussing installed 3.0.2 updaters | `53de3ae0ddab5323470f09dee7685e63513f98ac` | UNKNOWN |
| 3.0.3 | Local release commit message/tag and `docs/V3.0.3-RELIABILITY.md` | `2d00be72ece2017170636c0b528f25f83ee4a885` | UNKNOWN |
| 3.0.4 | Local release commit/tag, release note, updater-hotfix document, binary, checksum, and manifest | `f689d8a403ebe0002a91119c7eea26be2e78155b` | UNKNOWN; local distribution-shaped artifact exists |
| 3.0.5 | Local release commit/tag and release note/documentation | `40d62decd202f28700957a54dde4251454c89914` | UNKNOWN |
| 3.0.6 | Local release commit/tag and release note | `8e365d060196e899d39f121d9e1a088688b8654b` | UNKNOWN |
| 3.0.7 | Local release commit/tag and release note | `96a64afc609e469c54319a6c92adb61b97bdc60d` | UNKNOWN |
| 3.0.8 | HOLD release note, old bundled-provider binary set, and provider-free audit candidates; no local tag ref | None found | Not approved; whether any 3.0.8 asset was externally exposed is UNKNOWN |

The README and historical documents refer users to an “official” GitHub Release
and discuss 3.0.2 through 3.0.7 as installed/release versions. That is a reason
to prioritize remote evidence preservation and legal review, but it is not a
substitute for a release-page snapshot or asset ledger.

## Exact local artifact inventory

All hashes below were recalculated locally with SHA-256. File modification times
are deliberately not treated as publication times.

| Local path under `dist/` | Bytes | SHA-256 | Evidentiary classification |
|---|---:|---|---|
| `NeuralExtractorV3-3.0.3-backup.exe` | 193,141,493 | `02fbde8845bcb7b8946a44f320aa1f88a63a70ceac9765f800276ce11bfa6ed7` | Misleading filename evidence only: byte-identical to the local 3.0.4 EXE; not accepted as proof of an actual 3.0.3 release binary. |
| `NeuralExtractorV3-3.0.4-windows-x64.exe` | 193,141,493 | `02fbde8845bcb7b8946a44f320aa1f88a63a70ceac9765f800276ce11bfa6ed7` | Historical distribution-shaped binary; HOLD for review. |
| `NeuralExtractorV3-3.0.4-windows-x64.exe.sha256` | 107 | `d289fa9e4bbd44a5b8e9487e574ff341a84374d3c9fa52b058dd84e3437fbcd3` | Sidecar naming the same EXE hash. |
| `NeuralExtractorV3-3.0.4-manifest.json` | 388 | `efd6133f33c910bc09094e91b722c05ff387c2adab2a0aff28a33ec7b9dea456` | Declares release version 3.0.4, stable channel, x64, exact asset name/size/hash. |
| `NeuralExtractorV3.exe` | 234,709,652 | `0d4d4bdf1eabf5af88c1094732ae28cf55f12a0dc36377d90088eb54537b82ac` | Duplicate of the prohibited legacy 3.0.8 binary. |
| `NeuralExtractorV3-3.0.8-windows-x64.exe` | 234,709,652 | `0d4d4bdf1eabf5af88c1094732ae28cf55f12a0dc36377d90088eb54537b82ac` | Prohibited legacy bundled-provider artifact; do not publish, rename, or reuse. |
| `NeuralExtractorV3-3.0.8-windows-x64.exe.sha256` | 107 | `b0cba6ae97a62251ce4a4102d0405616a9a9a2d7c4803694235b5eb1a369acf4` | Sidecar naming the prohibited EXE hash. |
| `NeuralExtractorV3-3.0.8-manifest.json` | 388 | `6a04df22e764fc5c6a73c79f0c34f4b6299679abc48645d6d91c65986dfaad4d` | Declares release version 3.0.8, stable channel, x64, exact prohibited asset name/size/hash. |
| `pyside-provider-free-audit-20260722-1/NeuralExtractorV3.exe` | 203,003,860 | `e6e909971a59a9eaba7bd2eeee9e10b8e016f33b294c3799c000758a490418aa` | Superseded local audit candidate; non-public. |
| `pyside-provider-free-audit-20260722-2/NeuralExtractorV3.exe` | 189,351,131 | `528a7c693825ef8efd1adfe4f7b65afb4a1642ece39fd530c8c69abf436bafee` | Superseded local audit candidate; non-public. |
| `pyside-provider-free-seed-audit-20260722/NeuralExtractorV3.exe` | 189,260,920 | `4dbd2b8d92212fe31b1f6b20cfa768f5c443186563ef9fd7b509b06e598cc3af` | Intermediate local audit candidate; non-public. |
| `pyside-provider-free-phase1-audit-20260722/NeuralExtractorV3.exe` | 189,260,936 | `e4a9146f4e9da5574f7736be70dc2c06bfb7daa2e71ec4c3889f7eb541016d88` | Intermediate local audit candidate; non-public. |
| `pyside-provider-free-final-audit-20260722/NeuralExtractorV3.exe` | 189,262,055 | `124891f5915a7293194e79cbe44be71683d3d99b2d5a930fc5ea753f8a2c5cd3` | Superseded local final-audit candidate; non-public. |
| `pyside-provider-free-final-audit-20260722-2/NeuralExtractorV3.exe` | 189,262,303 | `45b42363487c44cd2566d76e2d59d41a5edeaeeb647bd09824465b3caa6c3e38` | Current provider-free one-file audit evidence; still HOLD and non-public. |
| `pyside-provider-free-final-audit-20260722-2/THIRD_PARTY_LICENSES-artifact-companion.txt` | 70,930 | `235848a8bb0e1605afd47d65fba8941f681e2152f254e25595442a2dc38d58e2` | Current artifact-specific compliance inventory; records unresolved blockers and HOLD. |

The identical hashes of the `3.0.3-backup` and 3.0.4 files mean that the former
must not be used to make claims about a 3.0.3 release payload. Obtain the actual
3.0.3 release asset, if any, and hash it independently.

## Local binary scan findings

The local PyInstaller archive reader was used recursively. Counts are
case-insensitive path/name matches and are evidence indicators, not a substitute
for the full component inventory.

| Artifact | CArchive / PYZ entries | GUI/runtime evidence | Provider evidence | Compliance material observable in archive |
|---|---:|---|---|---|
| 3.0.4 EXE (`02fbde…`) | 225 / 1,525 | 130 PyQt6 matches; PyQt6 QtCore/Gui/Widgets plus Network/Pdf/Svg DLLs/plugins/translations; `python312.dll`, `python3.dll`, `ffmpeg.exe`, `ffprobe.exe`, `node.exe`, and a root `libffi-8.dll` are present. Exact historical component versions/source builds remain unproven by the local release set. | No `bgutil`, `getpot`, `yt_dlp_plugins`, or canvas path matches. | No root `LICENSE`, `THIRD_PARTY_LICENSES.txt`, `THIRD_PARTY_NOTICES.md`, source manifest, or source bundle was found in the EXE; only manifest/checksum sidecars are present locally. |
| Legacy 3.0.8 EXE (`0d4d4b…`) | 6,022 / 1,536 | 130 PyQt6 matches; `python312.dll`, `ffmpeg.exe`, `ffprobe.exe`, `node.exe`, and native canvas dependencies are present. The prior audit also records the wrong root libffi selection. | 5,755 `bgutil` matches, including in-process `getpot_bgutil` Python/PYZ modules plus provider JavaScript, npm, canvas, and native files. | An embedded `THIRD_PARTY_NOTICES.md` and numerous dependency license files are present, but no embedded root `LICENSE`, `THIRD_PARTY_LICENSES.txt`, complete Corresponding Source, or release source bundle was found. |
| Current provider-free audit EXE (`45b423…`) | 336 / 1,535 | No PyQt6; 40 PySide6 matches; CPython, Node, FFmpeg/ffprobe, Qt/PySide/Shiboken and the corrected single root libffi are present. | No `bgutil`, `getpot`, `yt_dlp_plugins`, provider JavaScript/TypeScript, npm tree, or canvas path matches. | Embeds root `LICENSE`, `THIRD_PARTY_LICENSES.txt`, `THIRD_PARTY_NOTICES.md`, `SOURCE-HASHES.sha256`, `requirements.lock`, and license texts. It is still incomplete as a public compliance package and remains HOLD. |

For the legacy 3.0.8 artifact, the provider Python was imported into the same
Python/yt-dlp worker process; only its JavaScript layer ran through Node. The
current provider-free candidate has no provider code in the main artifact and
uses a separately installed optional helper, but that helper has its own
independent HOLD.

## Version-by-version recommended action matrix

`Confirmed` below means confirmed from a local binary scan. `Documented` means a
local release note states the behavior but the historical release asset was not
available for verification. `Unknown` must not be converted into a compliance
claim without the actual asset and contemporaneous materials.

| Version/candidate | PyQt6 | Bundled PO provider | FFmpeg/Qt/Python runtime | License/source material known to accompany the release | Recommended action without changing remote state |
|---|---|---|---|---|---|
| 3.0.0 | Unknown; no local release binary | Unknown | Unknown | Unknown | Preserve tag/reflog evidence. Obtain the exact release record/assets and contemporaneous source/notices. Qualified review decides whether notice/source remediation or withdrawal is appropriate. |
| 3.0.1 | Unknown | Unknown | Unknown | Unknown; no local version evidence found | Ask the owner whether 3.0.1 existed or was distributed. If yes, obtain and audit it; if no, record that answer with evidence. |
| 3.0.2 | Unknown; local history alone is insufficient | Unknown | Documentation describes a PyInstaller one-file updater, but exact payload is unknown | Unknown | Treat as a priority review because local docs describe a defective installed updater and a manual upgrade path. Preserve actual release assets before counsel recommends any action. |
| 3.0.3 | Unknown; the local file named `3.0.3-backup` is actually byte-identical to 3.0.4 | Documentation says no PO token was collected/generated/fetched, but the actual binary is absent | Documentation mentions child FFmpeg and Node processes; exact packaged bytes are unknown | Unknown | Do not rely on the mislabeled backup. Obtain the actual asset/source snapshot and audit it independently. |
| 3.0.4 | **Confirmed present** | **Confirmed absent** in the local binary | **Confirmed:** PyQt6/Qt payload, CPython 3.12-family DLLs, Node, FFmpeg/ffprobe and root libffi | Locally found only the EXE, SHA sidecar, and manifest; no root license/notices/source bundle in the archive | High-priority qualified review. Determine PyQt6 license basis and whether required project/third-party source and notices were actually delivered. Consider withdrawal or remedial source/notice delivery only on counsel’s instruction. |
| 3.0.5 | Artifact-level status unknown; later 3.0.8 migration notes make continued PyQt6 use plausible, not proven | **Documented absent** by the 3.0.5 release note | Documentation identifies the desktop/updater/yt-dlp environment but exact bundled runtime is unknown | Unknown | Obtain exact binary, manifest, release page, notices, and source material. Audit PyQt/Qt, Python, FFmpeg, Node and updater contents. |
| 3.0.6 | Artifact-level status unknown; continued PyQt6 use is plausible, not proven | **Documented absent**; release note states no PO provider was bundled | Exact packaged runtime unknown | Unknown | Same evidence collection and qualified review as 3.0.5, including native runtime mapping. |
| 3.0.7 | The 3.0.8 note says PyQt6 was replaced directly, supporting a PyQt6 inference for the preceding source; no local 3.0.7 binary verifies it | No provider bundle is documented; exact binary unknown | Release notes mention retained yt-dlp/worker/Node/FFmpeg behavior, but packaged bytes are unknown | Unknown | Obtain the exact asset and contemporaneous material. Treat PyQt6 status as an inference until scanned. Review any public artifact before leaving it available. |
| Legacy bundled-provider 3.0.8 (`0d4d4b…`) | **Confirmed present** | **Confirmed present** in-process plus JavaScript/npm/canvas payload | **Confirmed:** PyQt6/Qt, CPython, Node, FFmpeg/ffprobe, canvas/native payload; prior audit found wrong root libffi | Some embedded notices/licenses, but no complete release compliance/source package | **Do not publish, rename, or reuse.** If it was exposed anywhere, preserve evidence and refer withdrawal/remediation to qualified counsel immediately. |
| Provider-free one-file 3.0.8 (`45b423…`) | **Confirmed absent**; PySide6/Qt present | **Confirmed absent** from main EXE; optional helper separate | Fully inventoried in the artifact companion | Improved embedded notices/manifests, but ownership, LGPL replacement, FFmpeg/Python source closure, Microsoft rights, Qt/native closure and legal approval remain unresolved | Keep non-public on HOLD. Use only as audit evidence while building the preferred compliance-friendly one-folder/source package. |
| Optional PO helper 1.3.1 | Not applicable | Separate GPL-3.0-only provider package | Node plus npm/canvas/MSYS2/librsvg/Rust closure | Independent helper package exists locally; native/source/relink closure remains incomplete | Keep separate and non-public on HOLD. Do not place it in any Neural Extractor release or updater asset. |

## Material that must be obtained for every possibly published release

Before a qualified reviewer can decide whether a release should remain
available, receive supplemental material, or be withdrawn, preserve and supply:

1. an immutable release-page/API snapshot with release ID, tag, timestamps,
   description, asset names, sizes, uploader identity, and asset download URLs;
2. every binary and sidecar exactly as served, with newly calculated SHA-256;
3. the source tree/commit actually used to build each binary;
4. the build environment, dependency locks, PyInstaller spec, scripts, patches,
   toolchain and logs;
5. a recursive archive/native inventory of the actual asset;
6. the `LICENSE`, third-party notices, license texts, source bundles, written
   offers, and installation/relink information available to recipients at the
   time;
7. evidence for the PyQt commercial or GPL licensing route used, if PyQt was
   included;
8. complete FFmpeg Corresponding Source/build information for any conveyed GPL
   FFmpeg build;
9. complete source/provenance for CPython/PBS and other native components;
10. proof of Microsoft redistribution rights and all Qt/third-party notices;
11. download/access history and dates needed to assess exposure; and
12. the resolved Neural Extractor copyright ownership and MIT authority record.

Upstream links alone do not prove that a distributor accompanied an old binary
with required source or made a valid offer. Conversely, absence of material
from the current working directory does not prove that recipients were never
given it; contemporaneous release evidence is required.

## Questions for qualified legal review

For each release that was actually conveyed, counsel should determine at least:

- whether the person/entity distributing it had authority to license the
  project-owned material;
- which PyQt/Qt license route applied and whether its conditions were met;
- whether the provider/main-program relationship and method of conveyance
  triggered GPL obligations for any broader work;
- whether FFmpeg and every other copyleft component received the required
  source, notices, build/install information, or valid offer;
- whether missing Microsoft/native redistribution evidence affects continued
  availability;
- whether a curative notice/source delivery is legally sufficient and practical;
- whether any asset should be withdrawn, disabled from the updater, replaced,
  or accompanied by a public correction; and
- what records must be retained and for how long.

## Engineering recommendation

1. Keep all local historical files immutable as evidence; do not rename or
   overwrite them.
2. Keep publication fail-closed and explicitly block the prohibited legacy
   3.0.8 hash
   `0d4d4bdf1eabf5af88c1094732ae28cf55f12a0dc36377d90088eb54537b82ac`.
3. Under separate owner authorization, collect remote release evidence
   read-only and hash every historical asset. This review did not do so.
4. Complete a release-by-release binary-to-source and notice comparison.
5. Present that evidence, the ownership answers, and the current seven release
   blockers to qualified counsel.
6. Make no remote alteration until counsel and the authorized owner approve a
   precise action for each release.

No Git or remote mutation was performed during this review.
