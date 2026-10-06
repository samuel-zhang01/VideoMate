# Workflows, profiles and migration

VideoMate 0.8.4 includes these three workflows. Finish a running job before switching builds.

| Workflow | What it creates |
| --- | --- |
| Inspect | Video integrity findings; no media copies |
| Repair | Independently verified recovered video copies |
| Migrate | A new collection containing healthy copies, verified repairs and other files, with unresolved-file handling chosen before starting |

On **Start**, select **Migrate a folder**, choose one source folder, and choose an **empty destination**. Blank uses **Workspace/recovered**, if it is empty. The destination entry uses the same setting shown in Settings. Select the unresolved-file policy, then click **Start new migration** at the bottom of the window. That button stays visible on every page. For a stopped memory-only job, choose **Continue stopped migration** in the same app session; a private-checkpoint job uses **Activity → Resume from private checkpoint…** with its Job ID and original passphrase after reselecting the same roots and options. Both reuse the existing package after verification. If Sensitive local-name permission is missing, a dialog asks before processing; declining starts nothing. No preview or profile is required. **Options** contains optional presets and advanced recovery settings; **Preview workflow** is optional. **Settings** controls storage, privacy and diagnostic logging.

## Profiles

Current source filters recipes by task, shows effective settings and marks modified profiles. Built-ins preserve machine CPU/runner/GPU/timeout limits, including the optional CPU encoding lane. MP4 recipes use explicit best-effort size matching; older saved settings keep strict limits. Update saved profile changes an existing custom recipe without saving unrelated global settings. Old CLI preset names remain aliases. See [completed results and unresolved retries](completed-jobs-and-retries.md).

Built-ins cover Inspect, preservation repair, Compatible MP4 repair, and four migration choices. **Keep healthy · lossless recovery** copies healthy files and uses preservation repair. **Keep healthy · MP4 recovery** copies healthy files unchanged and tries verified MP4 stream copy for the others, then eligible H.264/AAC repair if needed, preferring qualified hardware. **Convert eligible videos to MP4** converts every eligible video, including healthy ones, using the same lossless-first policy. **Migrate · selective HEVC MP4** copies healthy `.mp4` H.264/HEVC video unchanged and encodes other recognized or damaged videos as HEVC/AAC MP4 with playback loudness normalization, subject to the normal verification and unresolved-file policy. Copied compliant videos keep their original loudness. Selecting a profile applies it immediately; no extra Apply step is needed. A profile collects the existing processing options. Individual settings remain editable afterward, and profiles are optional.

**Save current as profile** stores a named processing preset in the selected local settings file. Up to 12 custom profiles are supported, with names up to 40 characters. Built-ins cannot be removed. Deleting a custom profile does not change the current processing settings. Reset defaults resets current options without deleting saved profiles.

Profiles never store input selections, output/storage locations, passphrases, the Sensitive flag, history/mapping permissions, diagnostic logging consent or permission to preserve Sensitive local output names. Applying one cannot silently change those choices. Profile names are local preferences and never enter diagnostic exports.

CLI `--preset "Migrate — keep healthy formats"` applies a built-in or a custom preset loaded through `--config`. Explicit flags override processing values. The preset must match the command's workflow. `--profile` remains the existing encoding-format option (`preserve_decoded_samples` or `compatible_sdr`); `--preset` selects the collection of settings.

## One folder, one new package

Migration accepts exactly one explicitly selected local source folder, recursively including ordinary files and empty subfolders. Video extensions recognized by VideoMate receive full integrity inspection. Other extensions are copied and hash-verified without being opened by FFmpeg or executed. An unknown video extension is treated as an ordinary file, not certified healthy. Archives are copied as files, never expanded.

For new GUI/CLI jobs, the selected destination **is** the collection root; neutral sidecars and temporary staging sit beside it:

```text
chosen-empty-destination/             source-relative files and folders directly
chosen-empty-destination.status.json  completion state and aggregate counts
chosen-empty-destination.owner        package ownership marker
chosen-empty-destination.review/      only when separate review copies are requested
candidates-<random-id>/               temporary staging during this job
```

Names and relative folders are mirrored directly into the destination, without an extra `content` or `migration-ID` wrapper. The destination must be empty for a new job; VideoMate rejects an occupied destination rather than merging unknown files. Older migration packages retain their original `migration-ID` layout on retry/resume. The status JSON is beside the destination to avoid colliding with source filenames. With **Sensitive: Yes**, explicitly enable **Permit original names in this local output (Sensitive)** or approve the prompt when starting. Diagnostics still exclude names/paths. That consent does not anonymize the package: its filenames, metadata and contents remain private. Ordinary Repair continues to require neutral names in Sensitive mode.

With **Sensitive: No**, migration always preserves original names and relative folders automatically; its naming-permission checkbox is disabled. The separate Repair output-layout preference does not alter migration structure.

Start now states this directory behavior directly. The Repair output-layout control is disabled during migration so a saved “Neutral names” Repair preference cannot be mistaken for the migration policy. Sensitive migration still requires the separate local-name permission before processing.

Healthy videos are copied byte for byte, including their embedded metadata. The MP4 migration preset instead converts all eligible videos. Damaged inputs use the selected repair policy and must pass fresh software decode/property/timing verification before entering the package as a repair. Repaired copies can change extension and omit metadata or other explicitly permitted material. When an extension would conflict with another selected file, a `.repaired-N` suffix protects the existing name. This may require updating references in accompanying documents/playlists; VideoMate does not rewrite their contents.

Choose **If a video cannot be repaired** before starting. The batch then proceeds without repeated prompts:

| Choice | Result |
| --- | --- |
| Exclude from output; keep sources (default) | Leave the unresolved video at its source and count the omission; no review copy or review folder |
| Copy unchanged into output | Include the original at its matching relative path, explicitly marked unresolved in the report |
| Copy to a separate review folder | Put an unchanged copy at its relative path in the adjacent `.review` folder; omit it from the main package |

These choices also apply to unsupported videos and unsuccessful requested conversions. An unresolved result does not establish irrecoverability. Sources remain untouched in every case. Manual deletion/quarantine stays a separate action under advanced recovery options, requires individual file selection and typed confirmation, and can be performed after local review. [Cleanup and recovery options](recovery-options.md).

Each copied file is streamed into an exclusive candidate, SHA-256 checked, checked against source filesystem identity/size/mtime, then published without overwriting an existing file. Source selection and fingerprints are checked again before declaring the package complete. This is not an atomic filesystem snapshot; keep the source folder unchanged during migration.

Optional file timestamp preservation is best effort and reported. This is a content migration, not a filesystem clone: creation times, directory timestamps, ownership/ACLs, NTFS alternate streams, macOS resource forks, hard-link relationships and extended attributes are not preserved. Do not use it as the only archival copy when those properties matter.

## Status and limits

The adjacent `.status.json` contains fixed states and aggregate counts, including output files, partial recoveries, omissions and each unresolved-file disposition, plus local totals for processed source bytes, package bytes and review bytes. Exact byte sizes stay private and do not enter diagnostic exports. `complete` means all selected files were successfully copied or repaired without partial salvage. `needs_review` means a verified partial is published or some videos remain unresolved, whether excluded, copied unchanged or kept separately. `incomplete` means a copy failed or the source tree changed. `building` and `interrupted` must not be treated as completion. Omission counts also include failures and unprocessed files. Individual repair losses and timestamp outcomes appear in explicit sanitized diagnostics. No source name is recorded in this status file or in exported diagnostics.

Migration has no configured file-count or visited-entry ceiling. Inventory and the session journal use memory proportional to the collection, so available RAM, disk capacity and filesystem limits still matter. Status counters update incrementally. Existing per-worker timeout and per-candidate size limits remain configurable in Settings. Inspect/Repair discovery and private checkpoints retain their existing separate limits.

The GUI shows files found during discovery, then a determinate bar with processed/total files, elapsed time and an approximate remaining time based on completed-file throughput. After the first minute it uses only recent completions, so a long fast-copy phase does not dominate the estimate for a slow video tail. When the recent rate is too sparse or stale it shows “estimating” instead of promising an unrealistic finish time. Repairs and mixed file sizes can still change the estimate substantially. Final source checks and diagnostic preparation have their own phase labels. File progress reaching the total is not a declaration that the package is healthy; read the final status. Stop remains available, and an interrupted job keeps its actual progress.

Symlinks/reparse points, nested mounts, unsafe locations, inaccessible entries and case/Unicode name conflicts fail preflight rather than silently disappearing from a purportedly complete package. Errors give fixed, path-free reason codes: `MIG-WORKSPACE`, `MIG-OUTPUT`, `MIG-STORAGE`, `MIG-FOLDER`, `MIG-EMPTY`, `MIG-LINK`, `MIG-ACCESS`, `MIG-NAMES`, etc. Source folders cannot contain or overlap the workspace, output, selected logs/diagnostics or software checkout; the GUI also rejects a settings file inside the source before preparing storage. The default Workspace in Settings is valid when Source is a separate approved folder. Existing software/source-root and cloud-sync restrictions apply.

Before inspecting source bytes, migration exercises publication and collision refusal using tiny, newly created marker files in its staging/output directories, then removes those markers. Windows uses exclusive same-filesystem rename, which does not require hard links. macOS/Linux retain exclusive hard-link publication and require filesystem support. Neither path overwrites destinations. See [Python's platform-specific rename semantics](https://docs.python.org/3/library/os.html#os.rename). A successful preflight cannot guarantee later space/access availability. Closed copy/publication failure reasons distinguish source reads, output writes, verification, denied access, locks, long paths, unsupported publication and space exhaustion. A healthy video's copy failure does not reclassify it as damaged.

Migration starts with up to four file lanes and can grow to the qualified GPU route count, bounded by the CPU budget and any explicit Parallel files cap. CPU codec-thread requests are shared across lanes; one copy/hash lane avoids competing large verification reads. Journal publication intents use serialized durable transactions. See [interruption recovery and scheduling](interruption-recovery.md).

Settings → Encoding hardware can prefer a qualified NVIDIA, AMD, Intel or Apple route. **Optimize selected codec** uses only an internally generated clip to benchmark that codec, verifies every synthetic output with software decoding, compares one versus two concurrent jobs and saves a bounded route ranking in local settings. With Automatic selected, migration apportions spare video lanes by measured aggregate throughput while giving each qualified route an initial lane. Calibration can add at most two automatic file lanes, up to six total unless the qualified-route baseline is already higher, when simultaneous synthetic encodes improve throughput and the CPU budget permits. An explicit Parallel files limit still wins. A manually preferred vendor takes the first route position and a larger share of spare lanes. The saved recommendation may lower the per-route admission cap but never raises it above Concurrent GPU jobs. Unavailable routes are discarded when a new job qualifies its actual hardware. A successful real repair can still move its verified route to the front of that worker's later attempts; calibration is an initial schedule, not a guarantee that every file will use the same GPU. Benchmarks do not inspect operator media and cannot predict every source codec or filter workload.

Settings → Processing limits now enables an **automatic CPU encoding lane** by default. It runs only when at least 16 process-visible and budgeted codec threads, enough videos, qualified GPU routes and at least two requested codec threads per video lane are available. The lane uses software decoding and H.264/H.265 encoding from its first encode attempt. It receives at most eight codec threads and roughly one quarter of the available video codec-thread budget; GPU lanes share the rest, and a mixed tree still reserves one copy lane. On a 32-thread computer at the default CPU setting, a two-GPU mixed batch requests 11 + 11 GPU worker threads, 7 CPU worker threads and one copy thread. The **Force CPU encoding lane** checkbox and CLI `--migration-cpu-encoding` bypass only the 16-thread automatic threshold; route, video and minimum-thread checks still apply. Turn both checkboxes off, or use CLI `--no-migration-cpu-encoding`, to disable it. No GPU route or insufficient lane capacity keeps the original schedule. CPU thread counts are FFmpeg requests, not OS core affinity. This is conservative static admission, not live CPU-utilization adjustment. Full software verification, audio filters, file I/O and GPU feeding already use CPU; an extra lane may reduce throughput on disk-bound or CPU-bound machines. Compare equal operator-run batches before adopting a custom limit.

Full integrity checks and candidate verification use software decoding. Eligible recovery prefers qualified hardware. NVIDIA devices 0–15 are individually tested with generated frames and explicitly selected for CUDA/NVENC; other codec APIs retain their qualified default adapter. The Concurrent GPU jobs setting now applies per qualified device, default 2 (1–16). Worker/CPU limits still apply. Same-vendor multi-adapter AMD/Intel routing and physical multi-GPU qualification are not claimed. [Details and limits](interruption-recovery.md).

If one encoded candidate fails a stream or timing invariant, later encoder candidates receive a quick metadata preflight. A candidate with the same decisive mismatch is rejected before an unnecessary full software decode; one whose metadata passes still receives the complete independent decode and preservation checks. Encoding attempts are not skipped, so an alternate encoder can still recover the file.

The progress bar also shows the active file count. ETA is based on completed files, not frame progress or predicted encoding cost. Use a lower parallel-file limit on slow disks or limited-memory machines.

## Candidate files and size control

During direct migration, a sibling `candidates-<random-id>` directory holds full proposed outputs, including copied files, until verification finishes. Older versioned packages keep their `.candidates` staging location. Staging is not an additional permanent media library. Successful outputs are published into the package; rejected encoding attempts are removed immediately after their worker exits, including retained Repair jobs. Owned session staging is removed on normal completion/cancellation. A crash can leave remnants; the app does not discover or delete old operator state.

Temporary caps now default to off (`--max-output-mib 0 --max-source-percent 0`). Large intermediate candidates are allowed while encoding. Low-disk monitoring still stops encodes below a 64 MiB reserve, with timeouts/cancellation retained. Optional temporary caps can still be explicitly configured; existing saved settings retain their values. **Use source-size MP4 defaults** on Options applies the MP4 repair preset and clears old caps without changing privacy or output location. Activity shows private source/cap/output sizes; those values are excluded from exports.

MP4 profiles now target the original file size using source size/duration and reserved AAC/container budgets. Finished output exceeding the selected tolerance (default +25%) gets one bitrate-adjustment retry. If still oversized, it is withheld and the unresolved policy applies. Smaller verified files are retained without padding. This is approximate size targeting, not exact matching; lossless FFV1 cannot promise it. Normalization, AAC bitrate, software encoding speed and fast-start are optional [conversion controls](recovery-options.md). Healthy copies keep their original size and bytes unless all-file conversion is enabled. A smaller file is not evidence of successful recovery; verification still decides publication.

Migration history defaults to memory-only in both privacy modes. Automatic reconnect/retries stay within that session. Optional Private resume stores a passphrase-keyed path-free restart journal, without mappings or raw content hashes. Reselect the same roots/policy and use Activity Resume from private checkpoint with the Job ID/passphrase to reuse its package. Completed checkpoints are removed; interrupted or needs-review checkpoints remain private. Only current-session owned candidates with confirmed worker shutdown are cleaned; unknown older remnants remain untouched. [Restart workflow](interruption-recovery.md).

Large migration diagnostics are internally split into independently scoped JSON pages of at most 1,000 records and 16 MiB each, splitting further for dense findings. Normal export consolidates those validated pages into one text log: healthy copies are counted and repeated failure/recovery patterns are grouped. Optional CLI `export-diagnostics --technical-json` writes every page for per-record analysis. No filename mapping is created for migration. Explicit session export refreshes each page's identifiers. Activity logs use four rotating 4 MiB text segments with cumulative totals; old detail may be replaced, but late failures are still recorded. Exported per-input diagnostics are independent of activity-log rotation.

## CLI examples

Initialize the workspace first, then substitute local paths yourself:

```sh
sh start.sh --offline --cli migrate --workspace /local/workspace \
  --input /local/collection --sensitive yes --local-output-names --preview

sh start.sh --offline --cli migrate --workspace /local/workspace \
  --input /local/collection --sensitive yes --local-output-names \
  --preset "Migrate — keep healthy formats" --unresolved exclude --export-on-completion
```

On Windows use `start.bat --offline --cli ...` with Windows paths. `--unresolved copy` includes unchanged unresolved videos; `--unresolved review` requests the separate review folder. `--no-preserve-file-times` disables timestamp copying. Use `--private-resume` to enable a migration restart checkpoint; later add `--checkpoint <job-id>` with the same selections/policy. Migration does not accept interval salvage; use Repair for deliberate editing.

Assistant development uses only generated media, documents and folders. Never expose the operator package, real input names, private settings, review contents or checkpoints to the assistant. Share only deliberately reviewed sanitized diagnostics.

## Diagnosing interrupted jobs (source 0.8.4)

Starting input IDs are not progress counts: video and ordinary-copy lanes can process out of order. The progress bar and final migration totals show actual completed work. A disconnected source/output device can interrupt processing and prevent the adjacent status file from being updated; a stale building state is not completion. Published outputs remain. Reconnect recovery continues in the current session; restart reuses the package only when Private resume was enabled before the original run.

Activity → Job summary displays whole-job totals. **Export diagnostic log** writes a plain-text log in the configured Diagnostics directory. It includes pipeline outcomes, stop reason/stage, independent reporting/cleanup issues, worker exit codes and timing, hardware choices, recovery attempts and verification failures. Repeated patterns appear once with counts; routine successful copies are summarized. No browser is needed. Export before closing a minimal-retention session. Use optional technical JSON for per-record analysis; the text log does not preserve an individual reference for every repeated record.
