# Local dependencies

VideoMate resolves FFmpeg/FFprobe from `dependencies/ffmpeg/<platform>/bin`, verifies the accompanying `manifest.json` hashes, executes software health checks and checks recovery encoders. Startup provisions missing public software automatically unless --offline is set; media processing remains offline. The optional Python/Tk runtime lives separately under `dependencies/python/<platform>` or the documented WSL native cache.

## Prepared platforms

| Platform | Native tools | Execution evidence |
| --- | --- | --- |
| Windows x64 | FFmpeg/FFprobe 9.0.2, Gyan essentials | Source GUI/CLI and packaged desktop |
| Windows ARM64 | FFmpeg/FFprobe 9.0.2, BtbN GPL static build | Pinned archive and ARM64 PE headers; native execution pending |
| Apple Silicon | FFmpeg/FFprobe 9.0.2, Martin Riedl | Checksums and ARM64 Mach-O headers only |
| Linux x64 | FFmpeg/FFprobe 9.0.2, Martin Riedl | WSL Ubuntu, source GUI/CLI and recovery |
| Linux ARM64 | FFmpeg/FFprobe 9.0.2, Martin Riedl | Checksums and ARM64 ELF headers only |

`sources.json` pins exact public archives and publisher SHA-256 values. Windows uses one archive per architecture; Mac/Linux use separate tool ZIPs. `python-sources.json` pins Astral python-build-standalone CPython 3.13.15 release 20260924 for the five 64-bit targets, including Windows ARM64. `appimage-sources.json` pins the Linux x64/ARM64 AppImage builder and runtime. Windows x64 and Linux x64 portable Python/Tk have been executed here; Windows ARM64 still requires a native host test. Existing Anaconda Python also works; no Conda packages are modified.

Primary provenance: [FFmpeg downloads](https://ffmpeg.org/download.html), [Gyan builds](https://www.gyan.dev/ffmpeg/builds/), [Martin Riedl builds](https://ffmpeg.martin-riedl.de/), [python-build-standalone release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260924), [standalone runtime documentation](https://gregoryszorc.com/docs/python-build-standalone/main/running.html).

## Setup

Use [start.bat/start.sh](../docs/launchers.md) for normal configuration. The explicit provisioning tools are also available:

```text
python tools/install_ffmpeg.py --platform windows-x86_64
python tools/install_ffmpeg.py --platform windows-arm64
python tools/install_ffmpeg.py --platform macos-arm64
python tools/install_ffmpeg.py --platform linux-x86_64
python tools/install_ffmpeg.py --platform linux-arm64
python tools/install_python.py --platform linux-x86_64 --online
```

Direct FFmpeg provisioning is an explicitly requested download unless `--offline` is supplied. Python provisioning defaults offline and needs `--online` for downloads. The launcher permits missing-software downloads unless --offline is selected. The no-Python shell helper uses runtime-bootstrap.tsv, which must match the canonical JSON pins. Provisioning reads only software, never media.

For offline installation, use the exact pinned Windows ZIP with `--archive`, or a Mac/Linux directory containing the catalog's two filenames with `--archive-directory`, plus `--offline`. Supply a Python runtime tarball with install_python.py `--archive` or the launcher's `--runtime-archive`. Cached archives are under dependencies/cache. Existing platform directories are never overwritten. Setup locks protect concurrent installs; failed owned partial downloads are cleaned up without removing another process's files.

Checksums detect changes relative to trusted catalog/manifest files. They are not authenticated signatures and do not protect against an attacker replacing both software and manifest. Binary-header checks do not prove OS compatibility. Mac FFmpeg declares a macOS 12 minimum, but the complete GUI's minimum supported version remains unqualified; the native build workflow targets macOS 15.

## Alternative approved tools

Import compatible self-contained native tools with expected digests and license:

```sh
python3 tools/install_ffmpeg.py --platform linux-x86_64 \
  --import-directory /approved/ffmpeg/bin --version 9.0.2 \
  --ffmpeg-sha256 '<expected-64-hex-digest>' \
  --ffprobe-sha256 '<expected-64-hex-digest>' \
  --license-file /approved/ffmpeg/LICENSE
```

Select the actual platform/version. Imports never download. Software health and encoder checks still need to run on the target. Other adapter tags may accept explicit imports; only the four catalog targets have prepared pins.

For a pyz in dist, dependencies sit beside dist. For a standalone pyz elsewhere, dependencies sit next to it. CLI `--dependencies` options and the GUI's offline-bundle selector can choose a different tool root. Neither is a media directory.

## Build transferable kits

```text
python tools/build_zipapp.py
python tools/build_offline_bundle.py --platform windows-x86_64 --output dist/videomate-0.6.0-windows-x86_64-test-kit.zip
python tools/build_offline_bundle.py --platform macos-arm64 --output dist/videomate-0.6.0-macos-arm64-test-kit.zip
python tools/build_offline_bundle.py --platform linux-x86_64 --include-runtime --output dist/videomate-0.6.0-linux-x86_64-runtime-kit.zip
```

Include-runtime packages an already provisioned runtime for the selected platform. On WSL, build the Linux kit with Linux Python so it finds the native cache and preserves Unix modes/case. Builders refuse existing destinations. Kits contain launchers, bootstrap tools, catalogs, docs, schema, manifests and licenses. Package hashes include executable permission handling; they are not publisher signatures. A foreign-platform kit is not execution evidence.

For native self-contained Windows, Linux and Mac desktops see [desktop builds](../docs/desktop.md) and [release development](../docs/release_development.md). Offline builds need platform-matching PyInstaller wheels and a Python/Tk build runtime. Normal application use needs no pip dependencies.

Downloaded runtimes, executables, cache and wheelhouses are ignored by Git. Preserve licenses. A public distribution must satisfy the exact FFmpeg build's corresponding-source and dependency-license obligations; these local development artifacts are not a complete public release or SBOM.
