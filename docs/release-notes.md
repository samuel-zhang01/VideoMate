# VideoMate 0.8.4 — local release candidate

Version 0.8.4 adds generated-video hardware calibration in Settings. The chosen H.264 or HEVC route is measured locally, checked by independent software decoding, saved for up to 30 days, and requalified before each migration. The GUI now waits for a processing-tool check when the configured FFmpeg path changes, so an earlier check cannot enable processing or calibration for the new path.

The source also adds native-host Windows ARM64 and Linux x64/ARM64 desktop build paths and pinned Linux AppImage packaging. Release inputs now require a passing hashed synthetic report and internal software links. Mac signing checks require an available exact Developer ID identity, a matching team on the signed app and DMG, and app links contained within the bundle. Malformed scan, migration and recovery options receive fixed errors before processing; failed Windows Job assignment confirms worker shutdown before cleanup.

## Local qualification

On macOS 27.0.1 arm64, the full generated-fixture source suite passed **308 tests with one optional skip**. Focused native GUI, calibration, recovery, runner, signing and release-asset tests also passed. The local Apple Silicon development ZIP passed frozen and extracted 36-check generated-media self-tests, checksum and arm64 architecture checks, and an offline launcher check. Only generated fixtures and public build software were used. This does not qualify the other platforms or a public release.

Certificate-backed signing, notarization, DMG distribution, Gatekeeper acceptance, macOS 15 and clean-machine tests remain open. Windows ARM64 and Linux ARM64 require native qualification; Windows x64 and Linux x64 evidence from 0.8.3 does not automatically qualify 0.8.4. GitHub Actions remains disabled. See [Apple Silicon validation](development/validation.md) and the [release handoff](release_development.md).

# VideoMate 0.8.3 — automatic CPU encoding admission

Migration now automatically considers one software-encoding lane beside qualified GPU routes. It is admitted only with at least 16 process-visible and budgeted codec threads, enough video inputs and file lanes, and at least two requested codec threads per video lane. On a 32-thread computer using the default setting, VideoMate budgets about 30 codec threads. In a mixed batch with two qualified GPU routes, it requests 11 threads for each GPU worker, 7 for the CPU worker and one for verified copies. GPU routes remain preferred. The CPU request is capped at eight threads and about one quarter of the video budget.

**Settings → Processing limits** offers Automatic CPU encoding (on by default), a separate Force option for smaller machines, and the existing CPU-thread/parallel-file limits. An older saved settings file acquires automatic mode without losing an earlier Force choice. CLI `--no-migration-cpu-encoding` disables both automatic and forced lanes; `--migration-cpu-encoding` forces the eligible lane. The job activity states which mode was requested, whether it was admitted, and the process-visible/requested budgets. These are FFmpeg thread requests, not OS CPU affinity or a measured throughput gain. VideoMate does not sample live CPU utilization or change lane counts mid-job.

This release retains the 0.8.2 migration continuation and private restart workflows. A stopped memory-only job can continue in the same app session after verifying its source and completed outputs. Restart after closing the app still requires Private resume enabled before the first run. Starting a new migration still requires an empty destination. Independent candidate verification, unresolved-file exclusions, source preservation and Sensitive-mode diagnostic boundaries are unchanged.

## Qualification

The full generated-data source suite passed on native Windows x64 and Linux x64 under WSL: **275 tests on each platform, with one optional external schema-validator check skipped on each**. The Windows x64 desktop and Linux x64 runtime kits contain Python/Tk and FFmpeg/FFprobe for offline operation. Frozen/extracted package self-tests, offline launch and package checksum checks qualify these two build targets. Apple Silicon and Linux ARM64 packages need fresh native qualification; WSL testing does not guarantee every Linux distribution or a clean machine. GitHub Actions stayed disabled.

## Limits

VideoMate is an unsigned development prerelease, not encryption or an OS filesystem/network sandbox. The private restart checkpoint authenticates keyed technical state but does not encrypt it. Changed source/output/storage identity or package ownership stops reuse for review. Missing bytes cannot be reconstructed, and a successful software decode does not prove visual completeness. Physical multi-GPU throughput, live CPU-load scheduling, native Apple Silicon behavior, signing/notarization and specialist missing-header/HDR recovery remain unqualified. See [interruption recovery](interruption-recovery.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).
