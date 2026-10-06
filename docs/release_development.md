# Release development and native-host handoff

This is the working handoff for building VideoMate without hosted GitHub Actions. The application stays Python; PyInstaller bundles the interpreter and Tk, while FFmpeg performs video work. Builds and tests use generated fixtures only. **Never** use operator media, settings, workspaces, checkpoints, diagnostics, or real filenames to qualify a release. Read `AGENTS.md` before touching the project.

## Target matrix

| Target | Native release build | Current local qualification |
| --- | --- | --- |
| Windows x64 (`windows-x86_64`) | Desktop ZIP containing `VideoMate.exe` | New local build passed frozen and extracted generated-media self-tests; clean-machine review pending |
| Windows ARM64 (`windows-arm64`) | Desktop ZIP containing native ARM64 `VideoMate.exe` | Build path and pinned Python/FFmpeg prepared; **no ARM64 host qualification** |
| Linux x64 (`linux-x86_64`) | Desktop ZIP containing ELF executable, plus AppImage | New WSL Ubuntu build passed frozen/extracted and AppImage generated-media checks, including a direct FUSE launch; native Linux distribution/clean-host review pending |
| Linux ARM64 (`linux-arm64`) | Desktop ZIP containing ELF executable, plus AppImage | Build path prepared; **no ARM64 host qualification** |
| macOS Apple Silicon (`macos-arm64`) | `.app` in desktop ZIP; optional signed/notarized DMG path | Native development build and generated-media GUI checks passed on macOS 27.0; **distribution qualification remains open** |

`x86_64` means 64-bit Intel/AMD, not 32-bit x86. There is no 32-bit product target. Intel Mac and Windows 32-bit are out of scope unless the owner requests them. Windows-on-ARM running an emulated x64 Python must use the x64 tool bundle; the native ARM64 build requires an ARM64 Python and must produce an ARM64 PE bootloader. No cross-compiled artifact is labeled qualified.

## One-command local build

On **each matching native OS/architecture**, from the source repository:

```text
python tools/build_release.py
```

For source-level GUI tests on the current WSL Ubuntu host, use the pinned Linux Python/Tk runtime provisioned by `tools/install_python.py` or the release builder. The host's default Python 3.12 lacks Tk and `os.process_cpu_count`; it cannot run the full GUI suite. A scheduler test now supports that older API surface. On 2026-09-28 the pinned-runtime run passed 298 generated-fixture tests with one optional skip; the default Python 3.12 passed 298 tests with 11 GUI/platform skips. The WSL Linux x64 desktop ZIP and AppImage passed packaged self-tests, and the AppImage passed a separate direct FUSE launch. These checks do not qualify other Linux distributions.

On Linux, `python3 tools/build_release.py` is equivalent. The command detects the host, uses a native Python with Tk or installs the pinned local Python/Tk, provisions pinned FFmpeg/FFprobe if missing, creates/reuses a private build venv in the user cache, installs pinned PyInstaller requirements, freezes the desktop, tests it before and after ZIP extraction with generated media, and on Linux builds/tests an AppImage using pinned AppImage tooling and a pinned type-2 runtime. Existing release filenames are never overwritten. No operator paths or media are inputs. The build may download **public software**; processing in the finished app is offline.

For a disconnected builder, pre-cache the catalog-pinned Python, FFmpeg, build-wheel and AppImage-tool archives, then run:

```text
python tools/build_release.py --offline --wheelhouse /approved/local/wheelhouse
```

The wheelhouse must match that host's Python and architecture. An already provisioned builder venv does not need the wheelhouse again. `--output-root` selects a new artifact directory. `--no-appimage` limits a Linux build to the desktop ZIP. The `dist/` and `dependencies/` binary/cache outputs are Git-ignored and must never be committed. The builder creates no tag, upload, signing request, GitHub Actions run, or operating-system service.

Architecture-specific source pins are in `dependencies/python-sources.json`, `dependencies/sources.json`, and `dependencies/appimage-sources.json`. Windows ARM64 FFmpeg uses an immutable BtbN GPL static archive; verify encoder/filter capabilities **on the native host** before release. The pinned archive SHA and binary PE header are checked during provisioning. The three build catalogs are software provenance, not evidence that a foreign CPU can run the package. When updating any pin, record its immutable URL, publisher, digest, license, and native runtime result. An existing mismatched installed bundle is not silently replaced.

## Native release gates

1. Build from a reviewed source commit on a native 64-bit host with working GUI display. Use a release output directory outside cloud sync when possible. Do not mount or select operator media.
2. Run the one-command builder and verify the new ZIP/AppImage plus SHA-256 sidecars. The frozen desktop and extracted ZIP must pass their generated-media self-tests. The AppImage must pass `--check` and its own generated-media self-test. Review the fixed synthetic report only.
3. Run `python tools/check_repository.py` against the staged source index and the focused package tests. Confirm the frozen executable architecture (`dumpbin`/`sigcheck` on Windows, `file` on Linux, `file`/`lipo -info` on macOS), packaged FFmpeg/FFprobe architecture and the exact third-party notices/licenses. Check on a clean native machine or clean VM of the same architecture, including an offline launch with no Python installed.
4. On Linux, exercise normal FUSE launch and the documented extract-and-run fallback; check desktop integration and at least one older intended distribution because PyInstaller's glibc and GUI library compatibility is host-dependent. WSL success qualifies WSL only. Keep the desktop ZIP as the Linux fallback.
5. Record each host OS/version, CPU architecture, display/Tk version, FFmpeg hash/version, generated test results, package hashes, visual GUI checks, failure categories and compatibility limits in release notes. A checksum alone is not a signature or a runtime test.
6. Review GPL/corresponding-source obligations for the **exact** FFmpeg archive and other bundled licenses. Publisher signing, notarization and organization security approval are separate release gates. Do not claim those are complete from an ad-hoc signature.
7. Publish only artifacts that passed their own native gate. Leave unqualified targets out of the release or label them experimental. Never overwrite an uploaded asset or move a published tag. GitHub Actions remains disabled; no workflow dispatch is authorized. Self-hosted runners can later call the same command after the owner authorizes runner setup.

## Apple Silicon qualification checklist

Use a physical or virtual **Apple Silicon** Mac with a native arm64 Python 3.13+ and Tk, macOS 15 for the first qualification, the project source at the reviewed commit, Xcode command-line tools, and a network path for downloading pinned **public software** or a preloaded offline cache. Confirm `uname -m` is `arm64`; confirm Python's architecture is arm64 rather than Rosetta. Do not attach operator storage or copy private reports. The repo contains a generated dimensional raster mark, a hand-authored SVG rendition, and the derived `assets/videomate.icns`; `tools/build_desktop.py` uses that icon for the native `.app`.

1. Read `AGENTS.md`, then inspect the source, catalogs, and this handoff. Check `git status` and the intended version/tag without opening any excluded files. Use a new release directory outside synced folders, for example a fresh local build directory under the Mac user cache.
2. Run `python3 tools/build_release.py --output-root <new-local-output-directory>`. If the installed Python lacks Tk, the builder uses the pinned Apple Silicon runtime. If building offline, provision the catalog archives and wheelhouse first and add `--offline --wheelhouse <directory>`.
3. Confirm the app executable and both FFmpeg tools report arm64 Mach-O architecture. Launch the **extracted** `.app` with Finder and with `start.command`; run `--check` and the generated self-test. Review UI at 800×600, 1024×768 and 1440×900 with normal and enlarged text, menu/button contrast, accessibility focus, a disconnected/offline state, and operation under a non-admin user. Validate private workspace creation and Sensitive defaults using synthetic paths only. Test copy/remux and verified re-encode routes with generated fixtures; do not substitute real media.
4. For a broadly distributable Mac build, use the optional [Developer ID signing path](macos-signing.md) with an approved Developer ID Application identity, bundle ID and hardened runtime. PyInstaller signs collected code; the builder refreshes FFmpeg hashes after signing, seals the app, verifies matching team identifiers and re-runs generated self-tests. Keep credentials in the Mac keychain or approved signing service, never in the repository or diagnostics. This signed path still requires its first certificate-backed native run; the default build remains ad-hoc signed.
5. The optional DMG path stages the signed `.app` with an Applications shortcut, signs and notarizes the image with the approved Apple account through `notarytool`, staples the ticket and verifies it with `codesign`, `spctl` and `stapler validate`. Test opening the downloaded DMG and launching its app on a separate clean Apple Silicon Mac under Gatekeeper. Packaging in a DMG alone does not provide signing/notarization.
6. Record minimum tested macOS version, signing/notarization evidence, archive and DMG digests, license materials, and any GPU fallback behavior. Only then add a Mac DMG release asset. A signed/notarized runtime can still operate fully offline; Apple's notarization connection is a **release-machine** step, never an operator-media step.

Use the [Mac signing command](macos-signing.md) once the membership and Developer ID certificate are active. Run `spctl -a -vv --type execute` against the mounted, final app on a separate clean Mac. Keep the staging directory new and project-owned, and never clear a path containing unrelated files just to rerun a release.

See `docs/releases.md` for source versioning and upload policy. Public references: [PyInstaller platform builds](https://pyinstaller.org/en/stable/usage.html), [AppDir format](https://docs.appimage.org/reference/appdir.html), [AppImage tooling and offline runtime](https://github.com/AppImage/appimagetool), [Apple software distribution](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution), [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
