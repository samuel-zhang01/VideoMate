# Settings and sensitive treatment

VideoMate uses a simple **Sensitive: Yes / No** flag for new jobs. Yes is the default. The flag controls application behaviour; it is not a claim of encryption, OS isolation or certification.

| Behaviour | Yes | No |
| --- | --- | --- |
| Queue filenames | Neutral item numbers | Local paths shown |
| Job journal | Memory only by default; optional keyed checkpoint or plaintext history | Plaintext saved history |
| Export-to-filename mappings | Never written | Separate opt-in, off by default |
| Output names/folders | Neutral Repair; explicit local-name permission for Migration | Neutral, original basename or selected folder structure |
| Automatic diagnostic export | Off | Sanitized export after completion/cancellation |
| Basic event logs | Off | Optional; fixed event codes and counters |
| Additional diagnostics checkbox | Optional safe technical disk log, off by default | Same |
| Explicit diagnostic export | Sanitized, local, operator-requested | Same |
| Processing / original files | Offline / preserved | Same |
| Raw FFmpeg logs, uploads, telemetry | Never saved or transmitted | Same |

Saved jobs keep their privacy/storage choices when resumed. The current toggle applies to new jobs and does not silently downgrade a saved job. Reusing a sensitive job's input list with `recover --job` cannot reduce its sensitivity. Older 0.4 test jobs retain their original automatic-export behaviour. The hidden legacy `--test-files` alias maps new jobs to Sensitive: No; new commands should use `--sensitive yes` or `--sensitive no`.

Filename masking applies to the queue. Native file pickers and editable settings locations necessarily show local paths. New Sensitive jobs keep paths and journals in memory unless **Keep Sensitive job history** is explicitly enabled. **Private resume** instead stores a passphrase-authenticated checkpoint without source paths, and requires reselecting the same files. It takes precedence over retained history. Recovered media, checkpoints, settings and any retained history/mappings are **not encrypted by VideoMate**. Turning on Sensitive does not erase older state. [Private resume and retention details](recovery-options.md).

## Configurable locations

**Start** offers Inspect, Repair and Migrate; **Options** holds built-in/custom processing profiles. Profiles exclude privacy permissions and all storage paths. Migration uses session-only history in both privacy modes and copies ordinary files as well as healthy videos. Its pre-run unresolved-file policy defaults to exclusion with reported omissions; unchanged package copies or a separate review folder are optional. Originals stay untouched. Its local naming consent is independent of profiles. [Migration and profiles](migration-and-profiles.md).

Settings now has **Storage**, **Privacy**, **Performance**, **Application** and **Display** sections. Storage holds the output and diagnostic locations; Application holds the settings file, tools and workspace preparation; Privacy holds retention/logging choices; Performance holds hardware and worker limits. Display offers **Reduce motion**, which stops continuous progress animation while keeping counts and status updates. This display preference stays outside processing profiles.

**Save settings** keeps current preferences for future sessions. **Undo unsaved edits** returns to this session's last saved/initial values, including hardware rankings. **Reset session to defaults** changes the current preferences until saved; it does not delete saved profiles or selected inputs. The page shows whether edits are unsaved. Command-S on macOS or Ctrl-S elsewhere saves while idle. Invalid numeric/path settings identify the field without repeating the entered value and reveal its page/section.

Open **Settings** to choose:

- **Workspace:** active session scratch, optional saved jobs/checkpoints/mappings and default temporary candidates.
- **Output folder:** defaults to `workspace/recovered`. For Migrate, Start shows the destination directly and requires it to be empty for a new job; the files land at its root. Repair uses the same setting as an optional override. Direct migration candidates sit in an owned sibling folder on the publication filesystem; rejected encoding attempts are removed after worker exit. Crash remnants can remain private.
- **Diagnostics:** defaults to `workspace/export-review`; explicit export writes one sanitized text log, with technical JSON only when requested through the CLI.
- **Event logs:** defaults to `workspace/logs`. Basic logs require Sensitive: No. **Additional diagnostics**, beside the Sensitive selector, independently opts in to enhanced safe logs in either mode. The same option appears in Settings; both controls stay synchronized.
- **Settings file:** the JSON file written by Save settings or Prepare workspace; blank uses the default location. It stores preferences, never input selections or keys.
- **Processing tools:** an optional verified FFmpeg/FFprobe bundle; blank uses bundled tools.

Locations must be absolute local paths, outside known cloud-sync/software roots, without links/reparse points. Files are never overwritten during recovery/export. Changing folders affects new jobs; it does not move old data. Defaults remain inside the workspace when an optional location is blank.

**Prepare workspace** recreates missing app/storage folders, saves current preferences (including to a missing settings file), and reads the file back before reporting success. Automatic startup creates missing settings while retaining an existing valid configuration. Invalid or unrelated files are left intact; choose a different settings filename or fix them locally. Settings shows a preparation result separately from tool readiness. Migration source/output/workspace/settings overlaps are rejected before preparation can create anything inside a selected source.

Processing settings include recovery hardware decoding and Compatible SDR hardware encoding (both preferred by default; authoritative inspection uses software decoding), a shared CPU thread budget (0 = available logical CPUs minus two, minimum one), parallel files for Inspect/Migrate (0 = automatic), migration GPU jobs (default 2, range 1–16), worker timeout (1–86,400 seconds), recursion, recovery strategy/profile and explicit loss permissions. Temporary candidate caps default to off: absolute MiB accepts 0–1,048,576; source-relative percent accepts 0–10,000 with a 1 MiB floor when enabled. These are separate from final-size targeting. Options includes finished-size tolerance (default 25%, range 5–100%), loudness normalization (Off/Playback/Broadcast), AAC bitrate, software H.264 speed, MP4 fast-start, all-eligible-file MP4 conversion, output layout and maximum shortening (10% by default when shorter output is permitted). Save settings persists these choices; Reset defaults changes the session until saved. Existing saved values are preserved; Use source-size MP4 defaults applies the new size policy and clears old temporary caps. Passphrases and input selections are never preferences. Invalid settings produce a fixed message without exposing their contents. Existing unrelated files are not overwritten by Save settings.

Settings → Performance → Encoding hardware offers Automatic or a preferred NVIDIA, AMD, Intel or Apple encoder API for **Migration**. A preference orders qualified routes; unavailable hardware is not assumed present, and a verified working fallback remains. **Optimize selected codec** calibrates the codec currently selected in Options → Advanced recovery options, using only an internally generated 720p/30 fps, 480-frame clip. It compares a verified single encode with two simultaneous verified encodes per qualified route. Stop remains available; cancelling before the result is accepted keeps the previous ranking. Neutral route IDs, measured aggregate frames per second, recommended one/two-job limit, FFmpeg bundle signature and 30-day expiry are saved in the local settings file. No media selections, names or paths enter this record or sanitized diagnostics. A job re-qualifies hardware before using the saved ranking; changed bundles or expired records fall back to qualified default order. Repeat Optimize for the other codec if needed. Do not optimize while a processing job is active. This is a short synthetic comparison, not a guarantee for every source format, size or filter chain. GPU preference/calibration currently affect Migration; standalone Repair remains serial.

Migration automatically considers one CPU encoding lane by default when the process-visible and budgeted CPU thread count is at least 16 and video/GPU lane limits permit it. The default thread budget is available logical CPUs minus two (about 30 on a 32-thread computer). The lane takes at most eight advisory FFmpeg threads, roughly one quarter of the video budget. Disable the automatic checkbox to retain GPU-only scheduling; the separate Force checkbox or CLI `--migration-cpu-encoding` bypasses the 16-thread threshold while still protecting GPU lanes. CLI `--no-migration-cpu-encoding` disables both; `--no-migration-cpu-auto` disables only automatic admission. Older settings files gain automatic mode through the new default, while retaining any earlier Force choice. This is static scheduling, not live CPU-load monitoring or core affinity, and changes no privacy policy.

## Choose a settings file

Default GUI preferences:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%/VideoMate/settings.json` |
| macOS | `~/Library/Application Support/VideoMate/settings.json` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/VideoMate/settings.json` |

On Linux, empty or relative XDG values use the home defaults. An absolute `XDG_STATE_HOME` selects the default workspace parent; an absolute `XDG_CONFIG_HOME` selects the settings parent. Existing saved paths are retained.

Use `start.bat --config C:\Local\settings.json` or `sh start.sh --config /local/settings.json`, or set `VIDEOMATE_CONFIG`. Saving to another file does not alter OS environment variables: use that path on the next launch. Missing files start with defaults; invalid files are not automatically replaced.

The GUI loads its selected preferences automatically. CLI processing reads a preferences file only when `--config` is passed after the command, and explicit CLI flags take precedence:

```sh
sh start.sh --cli scan --config /local/settings.json --sensitive yes --input /local/video.mp4
sh start.sh --cli recover --workspace /local/workspace --sensitive no --write-logs \
  --logs-dir /local/events --recovered-dir /local/recovered --diagnostics-dir /local/diagnostics \
  --timeout 1800 --max-output-mib 8192 --input /local/video.mp4 --mode auto
```

Initialize a CLI workspace first with `init --workspace <path>`; the GUI prepares it automatically. Ordinary resume/report/export locate retained jobs through the workspace and use their saved policy. Minimal-retention GUI reports remain in memory for the most recent eight jobs; export before closing. A separate CLI invocation cannot access those session reports: request `--export-on-completion` during the run. Private resume uses `scan`/`recover --checkpoint <id>` with reselected inputs and the same policy, rather than the ordinary `resume` command.

CLI equivalents are `--hardware-decoding` / `--no-hardware-decoding`, `--hardware-encoding` / `--no-hardware-encoding` (recovery), `--cpu-threads 0`, `--max-runners 0`, migration's `--migration-gpu-jobs 2` and `--hardware-preference auto|nvidia|amd|intel|apple`, recovery's `--max-source-percent 0 --max-output-mib 0`, and `--diagnostic-logs` / `--no-diagnostic-logs`. CLI migration reads any saved calibration from its selected settings file; calibration itself is currently a GUI action. Audio/playback flags are documented in [recovery options](recovery-options.md). CPU and runner overrides accept 0–1024. Standalone Repair is serial. Inspect shares its CPU budget across software decoding runners; GPU concealment is not accepted as evidence of health. Migration defaults to up to four files, with one copy at a time and configurable combined GPU decode/encode admission. Its codec APIs are qualified locally, not individual same-vendor cards. New choices apply to new jobs; resume retains the saved choices.

The detailed log records fixed worker stages, decoder/encoder names, exit codes, limit reasons, elapsed milliseconds, thread allocations and categorized message counts. These same typed details are retained for explicit diagnostic export whether or not disk logging is enabled. Unknown errors become a fixed category.

Disk activity logs use neutral `.log` filenames, compact completion summaries and detailed failure/fallback lines. Four rotating 4 MiB segments retain recent detail; cumulative counts continue through long jobs. Earlier detail may be replaced after rotation. No free-form backend messages, paths, command lines or recording metadata are included. These are local operational records; use **Export diagnostic log** for a reviewed, consolidated export. The application has no upload function.

## Why the older version blocked sensitive files

The earlier development gate tied all operator processing to unfinished OS isolation and persistent key storage. The existing offline and sanitized-diagnostic controls did not require that blanket restriction. Version 0.5 separates practical sensitive treatment from those stronger future controls, keeping the limits explicit. Assistant development still uses only generated media and never reads existing operator files or private state.

Source 0.8.3 writes one detailed text log to the configurable Diagnostics location. Repeated patterns are grouped, and JSON batches are optional via CLI `export-diagnostics --technical-json` (also retained when a non-sensitive user explicitly enabled mappings). Sensitive migration exports still require explicit opt-in; enabling Additional diagnostics alone does not authorize an export. No HTML is produced, and media filenames and paths remain excluded.

## Migration interruption recovery

Start → If migration is interrupted exposes the same switches as Settings. Migration interruption recovery defaults on: verify returned storage, rediscover the selected tree and retry temporary failures up to three times. A stopped memory-only migration can continue within the same app session with its original policy. Private resume independently enables passphrase-keyed restart state for migration in either Sensitive mode; its passphrase is entered twice before the new job. Use Activity → Resume from private checkpoint… with the same roots, policy, Job ID and passphrase. No names, paths or passphrase are stored in that checkpoint, but technical details remain private and unencrypted. [Workflow, retention, CPU/GPU limits](interruption-recovery.md).
