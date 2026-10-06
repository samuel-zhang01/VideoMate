# Synthetic development evidence

This is a curated record of generated-fixture/source checks. It contains no operator diagnostics, corpus details, private host locations, or local signing-account state. Historical results do not qualify subsequent changes or every platform.

## 0.8.4 source and Apple Silicon development package

The 30 September 2026 macOS 27.0.1 arm64 checkpoint recorded 308 source tests with one optional skip. The local desktop ZIP passed frozen and extracted 36-check generated-media self-tests, checksum/architecture checks, and an offline launcher check. The executable, FFmpeg, and FFprobe were arm64. This was a local development build, not a published package.

Ad hoc signature verification passed; Gatekeeper assessment rejected the app. Developer ID signing, notarization, DMG distribution, macOS 15, and clean-machine acceptance remain open. The implemented signing guards have focused synthetic coverage, not certificate-backed distribution evidence.

The 4 October source audit subsequently checked fourteen native GUI cases with no skips, twelve portable controller/correction cases, and focused persistence, launch, storage, and shutdown groups. Overlapping groups must not be summed into a suite count. A dedicated generated-only window supported visual review. No broad source suite or package rebuild was performed for that audit. See the [design audit](app-improvement-audit.md).

## Earlier 0.8.3 development checkpoints

Windows x64 and Linux x64 under WSL each recorded 275 generated-fixture tests with one optional external schema-validator skip for the 0.8.3 iteration. Later checkpoints recorded 296 Windows tests with one optional skip plus two spawned-process restart/review cases, and 298 WSL tests with one optional skip using the pinned Python/Tk runtime. The host Python 3.12 run recorded 298 tests with eleven GUI/platform skips.

Windows desktop, Linux desktop/runtime, and AppImage development artifacts passed their documented frozen/extracted generated-media checks and checksum/architecture checks. The WSL AppImage also passed a direct FUSE launch. WSL evidence does not qualify other Linux distributions or clean hosts. These earlier artifacts do not contain every later 0.8.4 change.

## Remaining qualification

- Rebuild and test the final reviewed source on each native target before releasing its binaries.
- Windows ARM64 and Linux ARM64 need native-host qualification of the current build paths.
- Review Linux glibc/display/FUSE compatibility on intended distributions and clean hosts.
- Complete Apple Silicon signing/notarization and clean-machine Gatekeeper acceptance.
- Review accessibility with assistive technology, high contrast, and physical mixed-DPI displays.
- Preserve exact third-party notices and complete the corresponding-source gate for bundled GPL-enabled tools.

Only generated fixtures may be used by development assistants. See [release gates](../releases.md), [implementation status](../implementation-status.md), and [validation recipes](../validation-and-roadmap.md).
