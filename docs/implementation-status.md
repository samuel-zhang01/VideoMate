# Implementation status

VideoMate **0.8.4 is development-preview source**. Public source preparation does not qualify a production release or update earlier binary packages. GitHub Actions remains disabled. Historical generated-fixture evidence is curated in [development validation](development/validation.md).

## Implemented

- Native Tk GUI and CLI for Inspect, Repair, and Migrate; explicit local selection, conservative filesystem restrictions, and separate FFmpeg/FFprobe workers.
- Full software integrity decoding, guided/automatic recovery, remux, FFV1/PCM preservation, eligible H.264/HEVC MP4 conversion, explicit shortening/track-loss policies, and independently verified publication with collision refusal. Missing source bytes cannot be recreated.
- Folder migration with byte-verified healthy/non-video copies, verified repairs, unresolved-file policies, aggregate status, and explicit Sensitive local-name consent. Originals remain untouched.
- Sensitive: Yes/No treatment, default Yes; memory-only Sensitive journals, no Sensitive export mappings, separate opt-in to bounded sanitized disk diagnostics, and closed HMAC-scoped exports.
- Optional path-free authenticated restart checkpoints, verified same-session migration continuation, bounded reconnect retries, and completed-job unresolved retry. Checkpoints are not encrypted.
- Per-job generated-frame hardware qualification, synthetic H.264/HEVC calibration, per-route concurrency recommendations, shared codec-thread budgets, and optional/automatic eligible CPU encoding lanes. No universal speedup or live CPU-utilization scheduling is claimed.
- Checksum-pinned public dependency provisioning, existing-tool reuse, Python/Tk download consent, and fully offline setup with supplied archives. Processing does not use the network.
- Native-host desktop builders for Windows x64/ARM64, Linux x64/ARM64, and Apple Silicon; Linux AppImage tooling and optional Mac Developer ID/DMG/notarization paths. Build-path implementation is not native distribution qualification.
- Separate manual original-file cleanup, requiring individually selected files and exact operator confirmation; never a scan/repair/migration side effect.

## Current UI/source changes

The October source audit added Storage, Privacy, Performance, Application, and Display settings sections; unsaved-edit indicators, undo, reduced motion, bounded validation/correction, responsive layouts, optimizer Stop/progress, and stale-result guards. Source startup honors selected tools and keeps help/version commands independent of FFmpeg. Settings and saved jobs enforce bounded persistence. Linux uses absolute XDG roots; storage rules reject other repositories. Unconfirmed worker shutdown retains priority and blocks further work.

Fourteen focused native GUI checks passed with no skips using a pinned Python/Tk runtime and isolated generated fixtures. Portable controller/persistence/startup/shutdown checks also passed; overlapping groups are detailed in the [design audit](development/app-improvement-audit.md). The audit did not run the broad suite or rebuild binaries. Existing binaries do not contain these changes. Screen-reader/high-contrast/mixed-DPI behavior and long-job responsiveness remain follow-up work.

## Platform qualification

| Target | Recorded development evidence | Still open |
| --- | --- | --- |
| Windows x64 | Earlier 0.8.3 source and desktop generated-media checks | Current-source rebuild, clean-machine distribution |
| Windows ARM64 | Build path and pinned software catalogs | Native runtime/package qualification |
| Linux x64 | Earlier WSL source, runtime/desktop, and FUSE AppImage checks | Current-source rebuild, intended native distributions and clean hosts |
| Linux ARM64 | Build path and pinned catalogs | Current native runtime/package qualification |
| macOS Apple Silicon | 0.8.4 development suite and frozen/extracted synthetic self-tests; subsequent focused GUI audit | Final-source rebuild, Developer ID/notarization, clean-machine Gatekeeper, macOS 15 |

The September Mac development suite recorded 308 tests with one optional skip and 36-check frozen/extracted self-tests. Its ad hoc signature passed verification; Gatekeeper rejected the app. Certificate-backed signing/notarization has not been exercised. Earlier results are historical evidence, not fresh qualification of the public snapshot.

## Public source preparation

The source now has an attribution-preserving MIT license, detailed usage README, documentation index, source/publication guards, and a clean source-only snapshot builder. Operator-derived narrative and obsolete local-host notes are omitted from the public tree. Development evidence is synthetic-only. See [public preparation and audit scope](public-release.md).

Publication preparation passed 21 focused checks with one optional schema-validator skip, plus staged-source parsing, documentation links, and CLI-example parsing. A separate single-commit snapshot is tree-verified against the reviewed index; the original private history is retained locally and is not the publication artifact. No new product binaries were built.

No OS-enforced sandbox, encrypted workspace, credential vault, telemetry, runtime network service, or signed general-distribution package is claimed. Private settings/retained history and optional checkpoints are local technical state. Pseudonymous diagnostics may still be distinctive; the operator reviews and authorizes sharing. No operator media/state is accessed by publication preparation.
