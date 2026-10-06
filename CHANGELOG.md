# Changelog

## Unreleased — public source preparation

- Add the MIT license with copyright attribution to samuel-zhang01. Third-party components retain their own licenses.
- Expand installation, GUI, CLI, result, privacy, and troubleshooting guidance; add a documentation index.
- Consolidate synthetic-only development evidence, remove obsolete/private development narrative, and separate design audit documentation.
- Add redacted source/history publication checks and a source-only clean snapshot builder.
- Include the application license and linked documentation in desktop/runtime packaging. No new binary or native platform qualification is claimed.

## 0.8.4 — 2026-09-30 local release candidate

- Add Settings → Encoding hardware → Optimize selected codec. It benchmarks only a generated 720p clip, verifies H.264/HEVC hardware outputs with software decoding, and keeps a bounded local ranking. Migration requalifies routes before using the ranking.
- Add native-host desktop build paths for Windows ARM64 and Linux x64/ARM64, plus pinned Linux AppImage packaging. These paths still require qualification on their respective native hosts before publication.
- Fix a GUI race so changing the FFmpeg folder during a tools check cannot accept the old result or start calibration with unchecked tools.
- Reject malformed scan, migration and recovery options with fixed errors before processing. Confirm shutdown after a failed Windows Job assignment before allowing worker cleanup.
- Tighten release gates: check the selected Developer ID identity before a signed build, require matching Apple team IDs and internal app links for a notarized DMG, verify DMG checksums in the asset gate, and require a hashed passing synthetic report plus internal links for AppImage input.
- Fix macOS generated-fixture tests to resolve the system temporary-directory alias before passing local paths through symlink-rejecting application rules.

## 0.8.3 — 2026-09-28 development prerelease

- Automatically consider one CPU encoding lane during migration when the process-visible CPU budget is at least 16 threads, enough video inputs and qualified GPU routes exist, and every video lane retains at least two requested codec threads. On a 32-thread host using the default budget, this gives FFmpeg 30 shared codec threads and requests seven for the CPU lane. GPU routes remain preferred, and the separate copy lane remains serialized.
- Make automatic CPU encoding the default for both new and existing settings; the new automatic checkbox can disable it. Retain the earlier force option for deliberately using a CPU lane below the automatic threshold. CLI `--no-migration-cpu-encoding` disables both; `--migration-cpu-encoding` forces the eligible lane.
- Report the automatic/forced decision and CPU budgets in path-free job activity. No live CPU-load sampling or universal speedup is claimed.

## 0.8.2 — 2026-09-28 development prerelease

- Continue a stopped migration in the same app session using a keyed, path-free snapshot. Verify completed outputs and require the original recovery policy; Private resume jobs restart through their disk checkpoint instead. Surface the correct continuation action on Start and Activity.
- Gate the optional CPU encoding lane on available codec threads, reserving at least two per video worker and capping the software lane at eight threads. No live CPU-utilization sampling or automatic throughput claim.
- Remove superseded design drafts, an obsolete audit and its one-time archive helper from the active repository.

- Add an opt-in migration CPU encoding lane alongside qualified GPU routes. The scheduler preserves one lane per qualified GPU route and the copy lane, divides the video codec-thread budget between GPU and software workers, and reports when the hybrid lane cannot run. GUI and CLI expose the choice; defaults remain GPU-first.

- Place new GUI/CLI migrations directly in an empty chosen destination, with neutral status/ownership and temporary staging beside it. Keep older versioned packages compatible with verified retry/resume; reject fresh reuse of occupied destinations.
- Add a final software partial-salvage attempt for damaged videos. Publish only independently verified playable results, mark them partial, and require package review. Keep originals and established unresolved-file policies unchanged.
- Label all otherwise unexplained nonzero FFmpeg exits with a fixed failure code and aggregate stage/exit/message counts in the sanitized text log. No raw worker output is retained.

- Add selective HEVC/MP4 migration profile: copy healthy compliant MP4 videos unchanged; encode other recognized or damaged videos with playback loudness, source-derived bitrate, hardware qualification and libx265 fallback. Verify output codec, geometry, audio and timing before publication; keep failures unresolved.

- Keep completed-job outcomes/progress across review, export and preview; show video coverage, grouped exclusion reasons and repair-loss disclosures. Make review/export primary completed-job actions and hide optional restart controls until requested.
- Revalidate completed outputs during live reconnect. Classify backend startup failures as operational and retry eligible failures up to three times after draining workers.
- Add path-free, keyed in-memory unresolved retry snapshots for new jobs. Preview policy changes, verify reselected storage/completed outputs, and reuse the existing package without overwriting verified work.
- Add specific plan-refusal codes, actual hardware route/concurrency summaries, and explicit strict/best-effort size policy with full verification in both modes. MP4 presets select best effort; existing settings retain strict behavior.
- Simplify and filter migration recipes, show effective settings/modified profiles, preserve machine limits when applying built-ins, and allow updating custom profiles without saving unrelated settings.

- Add migration reconnect recovery with storage identity checks, selected-tree rediscovery, three bounded retries, worker draining and owned-staging sweeps. Preserve unknown remnants and stop on unconfirmed workers, changed storage or conflicting outputs.
- Add optional passphrase-keyed, path-free SQLite restart journals without the migration input-count limit. Persist verified publication intents before final moves and verify source/output hashes on reuse. Remove fully completed checkpoints; retain interrupted/needs-review checkpoints.
- Add GUI private-checkpoint resume and reconnect controls, CLI checkpoint support, workspace/process coordinator locks, shared copy/hash admission and per-device GPU gates. Explicitly qualify NVIDIA indices 0–15; other GPU APIs retain their qualified default adapter.

- Preserve the original migration failure when status writes, event-log shutdown or session cleanup also fail. Snapshot cleanup warnings before closing memory-only journals, and allow opted-in diagnostic export after interruption.
- Include closed whole-job migration counts, stop stage/reason and secondary pipeline issues in every diagnostic batch, including a summary-only batch when no file finished. Reject inconsistent counts and unknown fields.
- Export one detailed plain-text log by default, grouping repeated failure/recovery patterns and summarizing ordinary successes. Include pipeline exit codes, worker timing ranges, decoder/encoder and thread allocation, limits, recovery attempts, verification issues and safe technical media facts. Keep JSON batches optional through `export-diagnostics --technical-json`; remove HTML generation.
- Replace JSONL activity logs and the 5,000-record cutoff with compact text, progress summaries every 1,000 completed files, repeated-worker-message counts, and bounded rotation (four segments, 4 MiB each). Late failures continue to be logged; cumulative totals survive rotation.
- Rename Activity actions to Job summary / Export diagnostic log. Starting-file messages distinguish an input ID from completed-file progress. Source GUI self-test now includes text-log generation.

## 0.8.1 — development preview

- Use software decoding for authoritative inspection: approved corrupted clips exposed silent GPU error concealment and false clean results. Hardware remains preferred for eligible recovery.
- Convert-to-MP4 and automatic MP4 migration try lossless stream copy first, verify it, then fall back to eligible H.264/AAC encoding. Honor requested audio/quality/bitrate transformations and finished-size ceilings. Preserve compatible HEVC 10-bit and multichannel streams without unsupported conversion.
- Qualify combined hardware decode/encode routes once per job, retain GPU encoding when the decoder pairing fails, and explicitly repack eligible downloaded NV12 frames to planar YUV420.
- Support known AAC speaker layouts up to eight channels, scale adaptive audio budgets by channel count, and preserve DTS through MP4 copying. Block unknown layouts and unsupported 5.1(side) AAC conversion instead of silently remapping speakers.
- Show each migration repair attempt and verification reason. Expand packaged GUI qualification to 33 checks, including lossless MP4 conversion and encoding fallback. Make Linux GUI visibility checks wait for native map events.

## 0.8.0 — development preview

- Stop all job runners and retain owned staging if worker shutdown cannot be confirmed; prevent retries and misleading per-file continuation. Drain completed migration results after dispatch failure and preserve fatal errors over cancellation.
- Put Activity findings ahead of resume controls; isolate GUI QA setup before any workspace preparation. Add mixed-folder migration to packaged self-tests and include migration/recovery documentation in packages.
- Remove automatic release-tag Actions triggers; prepare releases using local qualification. Archive historical validation notes separately from current status.

- Separate finished-size targets from optional temporary caps, which now default off. MP4 presets target source size, check final overshoot and permit one bitrate-adjustment retry before withholding still-oversized results. Keep smaller verified outputs without padding; retain low-disk, timeout and verification controls.
- Add optional Playback/Broadcast loudness normalization, explicit AAC bitrate, software H.264 speed and MP4 fast-start controls across GUI/CLI/profiles. Keep normalization off by default, preserve sample rate/channels, reject incompatible preservation/remux settings, and disclose transformations through closed diagnostic notes.
- Add a one-click source-size MP4 default preset on Options, clarify automatic migration folder structure on Start and disable the unrelated Repair naming control during migration.
- Parallelize migration with a shared CPU budget, reusable file workers, one verified-copy lane and configurable combined GPU admission. Qualify supported codec APIs and distribute workers across matching decoder/encoder routes; retain software fallback and full software verification. Physical same-vendor multi-GPU routing remains unimplemented.
- Add optional source-relative candidate caps (1 MiB ratio floor when enabled), adaptive AAC budgets and more conservative Auto video bitrate for small inputs. Reject explicitly size-limited candidates rather than accepting FFmpeg-truncated output. Clean rejected attempts immediately and monitor free output space.
- Add Windows exclusive-rename output publication without hard-link dependency, generated-marker migration preflight, fixed read/write/verification/publication failure categories and support-summary reason counts. POSIX publication still requires hard links. Preserve clean integrity classifications when only copying fails.
- Simplify output selection to an optional override of Workspace/recovered, clarify automatic non-sensitive migration naming, show active files and local size totals, throttle status writes and avoid migration's unused resume-output hash pass. Add the Migrate — repair to MP4 profile for hardware-eligible repair while copying healthy files unchanged.
- Remove migration file/entry count ceilings, update status counts incrementally and split large sanitized reports into bounded, independently scoped documents. Add a determinate migration progress bar, file counts, elapsed time and approximate remaining time.
- Replace the generic migration preflight failure with specific path-free reason codes; check folder-role overlaps before GUI setup writes. Prepare workspace now saves current settings and verifies the saved file, recreates a missing file, and uses the default when the settings-file field is blank.
- Add one-folder migration packages with hash-verified healthy/non-video copies, verified repairs, direct relative structure, collision handling and adjacent completion/omission reports. Unresolved files are excluded by default; choose unchanged package copies or a separate review folder before starting. Sources are never automatically deleted.
- Add explicit permission for preserved names in Sensitive local migration outputs; keep names/paths out of diagnostics. Migration history is session-only; Inspect/Repair retain existing resume options.
- Reorganize the GUI around Start, Options, Activity and Settings. Keep task/source/output choices together and the Start button visible on every page. Ask for missing Sensitive migration naming permission before starting. Add built-in processing profiles, custom local profile save/remove and collapsible advanced options. Profiles exclude privacy permissions and storage paths.
- Prepare missing settings, workspace subfolders and configured storage directories at GUI startup and from Prepare workspace, preserving existing files. Source launchers prefer the checkout over an older adjacent binary. Replace classic navigation buttons with themed controls for consistent colors on macOS.
- Add fixed migration outcomes to sanitized exports/support summaries. Keep packaging/release publication separate from this source iteration.
- Handle a POSIX process-group permission race only after confirming worker exit; retain resource limits and reject termination denial for a live worker.
- Wait for assigned Windows workers to exit before returning from job shutdown; report a fixed failure when termination cannot be confirmed within five seconds.

## 0.7.0 — unreleased

- Default new Sensitive jobs to memory-only journals and no export mappings; retain sanitized session reports for explicit export. Add optional passphrase-authenticated, path-free checkpoints for resuming reselected inputs. No checkpoint encryption or historical-state purge is claimed.
- Add filename/folder layouts for non-sensitive recovered copies, eligible all-file MP4 conversion, automatic/quality/bitrate/approximate-size policies and a configurable duration-loss limit.
- Add per-attempt verification reasons, decoder choices and processing budgets to closed diagnostics. Stream/count repeated worker errors without retaining raw logs; preserve demuxer time bases during null verification.
- Add separate, explicitly confirmed manual quarantine/deletion for individually selected originals. No automatic deletion based on integrity classifications.
- Keep published binaries at 0.6.2; broad suites and native rebuilds remain deferred.

## 0.6.4 — unreleased

- Prefer qualified hardware decoding for full inspection and eligible re-encoding; retain hardware encoding when falling back to software decoding. Verify recovery outputs with software.
- Inspect batch inputs concurrently using one shared CPU budget, defaulting to available logical CPUs minus two, with configurable runner limits and bounded GPU admission. Keep database writes on the job thread and repairs serial.
- Add Additional diagnostics beside Sensitive: Yes/No, plus CLI/settings controls. Opt-in safe disk logs and explicit exports contain fixed worker diagnostics, error categories and resource-limit reasons without raw text or locators.
- Broad test suites, native builds and release publication remain deferred.

## 0.6.3 — unreleased

- Operator-only testing guide and identifier-free, schema-validated support summaries.
- Optional generated-frame-qualified H.264 hardware encoding with software fallback; integrity verification stays on software decoding.
- Fixed encoder categories in sanitized recovery attempts; no driver text or hardware identifiers.
- Rapid iteration: batch edits, validate once at the end, retain 0.6.2 as the published rollback release.

## 0.6.2 — 2026-09-27

- Fix recursive folder discovery on Windows with Python 3.11 while retaining mount and reparse-point exclusions.
- Collect the Python license from Unix/framework standard-library layouts as well as Windows installation roots.
- Validate native Apple Silicon and Linux ARM64 source/runtime workflows in GitHub Actions.
- Publish complete desktop/runtime packages with SHA-256 checksums; retain 0.6.1 as an unpublished build attempt.

## 0.6.1 — 2026-09-27

- Explain and confirm missing Python/Tk downloads; decline by default, with --yes for unattended setup and --offline for disconnected use.
- Honor selected Python and active venv/Conda environments without installing or modifying them.
- Build versioned GitHub desktop/runtime releases with per-platform tests, SHA-256 sidecars and draft prereleases.
- Add release guidance and third-party notices. Complete desktop/runtime packages need no preinstalled Python.

## 0.6.0 — 2026-09-27

- Source-only Git repository setup, stronger ignore rules, commit guard, contributor guidance and private bug-reporting rules.
- Automatic setup of missing pinned FFmpeg, FFprobe and Python/Tk on Windows x64, Apple Silicon and glibc Linux x64/ARM64. Explicit --offline and supplied archives remain supported.
- No-Python bootstrap, Unicode-safe Windows archive extraction and checksums without optional PowerShell modules.
- Responsive navigation, wrapping controls, scrollable pages, focus visibility, screen-aware initial size and system DPI awareness on Windows.
- Source launchers use current code; older dist builds are no longer opened implicitly.
- More installation, Git-index and GUI scaling tests; obsolete local builds archived by exact allowlist.

At the time of 0.6.0, Apple Silicon and Linux ARM64 had not yet been executed natively. Later validation is recorded in the implementation-status document.

## 0.5.0

Universal copy, Sensitive Yes/No treatment, configurable storage and processing settings, private event logs and saved preferences. Operator-selected local processing replaced the old blanket test-only gate. Sensitive treatment is not encryption or an OS sandbox.
