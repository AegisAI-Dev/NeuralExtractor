# FFmpeg source and build record

Release-gate-status: **HOLD**

Corresponding-source-status: **INCOMPLETE**

Qualified-review-status: **REQUIRED**

This is an engineering provenance and distribution record, not legal advice or
a claim of compliance. It applies to the exact `ffmpeg.exe` and `ffprobe.exe`
bytes inventoried below. Do not use it for a later binary without regenerating
and reviewing every machine-readable inventory.

## Exact conveyed binaries

The audited binaries came unchanged from BtbN release
`autobuild-2026-06-30-13-34`, asset
`ffmpeg-N-125365-g9a01c1cb6a-win64-gpl.zip`.

| Path | Version | Size | SHA-256 |
|---|---|---:|---|
| `bin/ffmpeg.exe` | `N-125365-g9a01c1cb6a-20260630` | 143,314,944 | `6ed7e5c931d3cbc72931ee7e97efc4b7d8a1287f03c60585fab81a6a293b2e0e` |
| `bin/ffprobe.exe` | `N-125365-g9a01c1cb6a-20260630` | 143,109,120 | `55a3d20229c2373dade4362215c9bd5a04b59d4e734d0bbb882afd9cea4fb046` |

The compiler reported by the binary is GCC 15.2.0 from crosstool-NG
`1.28.0.23_185f348`. `BINARY-INVENTORY.json` preserves both complete
`-version` outputs and the parsed configure arguments.

## Retained source and build inputs

| Input | Purpose | SHA-256 |
|---|---|---|
| `third_party_sources/ffmpeg/archives/ffmpeg-9a01c1cb6a4cf87529fe9898b66ec55c5b032639.tar.gz` | Exact FFmpeg source commit | `b752d9b889d87ff96522438450268b1cfad449f4a8e66ff5058432636f491129` |
| `third_party_sources/ffmpeg/archives/btbn-ffmpeg-builds-7a83528ea3431e9eca982a712bc3a7cd0789d5d0.tar.gz` | Exact BtbN recipe commit | `0f0f15e02b4fd1b1bc37d2e3a6f57cd7a2078c31a51c8546110d3ccb40029d30` |
| `third_party_sources/ffmpeg/archives/ffmpeg-N-125365-g9a01c1cb6a-win64-gpl.zip` | Exact upstream binary asset | `52c0383c460f0ec1039088f1591921fb82e3b870b32aab8faf2ff1e5ae14bf9d` |
| `third_party_sources/ffmpeg/build-scripts/` | Extracted BtbN build scripts, patches, and container recipes | Bound file-by-file by `SOURCE-MANIFEST.json` |

`SOURCE-MANIFEST.json` contains 268 retained source/build/archive records with
size and SHA-256. `BUILD-DEPENDENCIES.json` extracts 118 repository references
from the BtbN build graph: 114 use a full Git commit or numeric SVN revision and
four use a tag or other literal. This graph is a superset; the configure command
below determines which libraries were enabled in the conveyed binary.

## Exact observed configure command

```text
--prefix=/ffbuild/prefix --pkg-config-flags=--static --pkg-config=pkg-config --cross-prefix=x86_64-w64-mingw32- --arch=x86_64 --target-os=mingw32 --enable-gpl --enable-version3 --disable-debug --disable-w32threads --enable-pthreads --enable-iconv --enable-zlib --enable-libxml2 --enable-libvmaf --enable-fontconfig --enable-libharfbuzz --enable-libfreetype --enable-libfribidi --enable-vulkan --enable-libshaderc --enable-libvorbis --disable-libxcb --disable-xlib --disable-libpulse --enable-gmp --enable-lzma --enable-liblcevc-dec --enable-opencl --enable-amf --enable-libaom --enable-libaribb24 --enable-avisynth --enable-chromaprint --enable-libdav1d --enable-libdavs2 --enable-libdvdread --enable-libdvdnav --disable-libfdk-aac --enable-ffnvcodec --enable-cuda-llvm --enable-frei0r --enable-libgme --enable-libkvazaar --enable-libaribcaption --enable-libass --enable-libbluray --enable-libjxl --enable-libmp3lame --enable-libopus --enable-libplacebo --enable-librist --enable-libssh --enable-libtheora --enable-libvpx --enable-libwebp --enable-libzmq --enable-lv2 --enable-libvpl --enable-openal --enable-liboapv --enable-libopencore-amrnb --enable-libopencore-amrwb --enable-libopenh264 --enable-libopenjpeg --enable-libopenmpt --enable-librav1e --enable-librubberband --enable-schannel --enable-sdl2 --enable-libsnappy --enable-libsoxr --enable-libsrt --enable-libsvtav1 --enable-libtwolame --enable-libuavs3d --disable-libdrm --enable-vaapi --enable-libvidstab --enable-libvvenc --disable-whisper --enable-libx264 --enable-libx265 --enable-libxavs2 --enable-libxvid --enable-libzimg --enable-libzvbi --extra-cflags=-DLIBTWOLAME_STATIC --extra-cxxflags= --extra-libs=-lgomp --extra-ldflags=-pthread --extra-ldexeflags= --cc=x86_64-w64-mingw32-gcc --cxx=x86_64-w64-mingw32-g++ --ar=x86_64-w64-mingw32-gcc-ar --ranlib=x86_64-w64-mingw32-gcc-ranlib --nm=x86_64-w64-mingw32-gcc-nm --extra-version=20260630
```

`--enable-gpl` and `--enable-version3` are present and `--enable-nonfree` is
absent. The current engineering classification is therefore a
GPL-3.0-or-later distribution route. The exact combined-work conclusion and
each external library's selected terms still require qualified review.

## Preserved license material

The project preserves, without rewriting third-party terms:

- `licenses/ffmpeg/FFmpeg-LICENSE.md`;
- `licenses/ffmpeg/FFmpeg-COPYING.GPLv2`;
- `licenses/ffmpeg/FFmpeg-COPYING.GPLv3`;
- `licenses/ffmpeg/FFmpeg-COPYING.LGPLv2.1`;
- `licenses/ffmpeg/FFmpeg-COPYING.LGPLv3`;
- `licenses/ffmpeg/BtbN-FFmpeg-Builds-LICENSE`;
- `licenses/ffmpeg/BtbN-binary-LICENSE.txt`.

The BtbN recipe license is MIT. That license does not replace the licenses of
FFmpeg or any linked library.

## Why the source set is not yet sufficient

The exact FFmpeg source and exact BtbN recipes are retained, but the source
archives or complete source trees for the enabled linked libraries are not.
Every `source_archive_retained` field in `BUILD-DEPENDENCIES.json` is therefore
false. The exact container image digest, crosstool input closure, original build
log, and a clean reconstruction have also not been retained.

For a GPL-covered binary, an upstream URL alone is not treated here as the
distributor's complete Corresponding Source delivery. Before public
distribution, the release owner must choose and document a GPLv3 section 6
conveyance method, provide the complete applicable source and scripts on that
basis, and obtain qualified review. If a written offer is considered, counsel
must approve its form, duration, recipients, cost terms, and operational source
fulfilment. No offer is made by this document.

Required engineering closure before PASS:

1. Identify the exact enabled linked-library build records from the final
   configure and link outputs.
2. Retain each applicable source tree, nested submodule, patch, generator input,
   and build/install script with hashes.
3. Retain the exact build environment identifiers and a complete build log.
4. Perform and record a clean rebuild sufficient to show that the retained
   material can generate functional replacement binaries.
5. Ship the exact GPL text, FFmpeg/BtbN notices, linked-library notices, source
   manifest, and the qualified-review-approved source delivery instructions.

## Local verification

Run only against the audited workspace:

```powershell
.\.venv\Scripts\python.exe scripts\runtime_closure\generate_runtime_evidence.py --check
.\.venv\Scripts\python.exe scripts\runtime_closure\generate_runtime_evidence.py --check --release-gate
```

The first command must report no stale evidence. The second command is expected
to fail while this record is HOLD. Do not suppress that failure for a release.
