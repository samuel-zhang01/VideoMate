# Local operation and testing

VideoMate 0.8.4 supports inspection, repair, migration and a native GUI. Choose Sensitive: Yes/No for new jobs. Assistant testing uses generated media; production media remains operator-only. [Migration and profiles](migration-and-profiles.md), [sensitive treatment](settings-and-privacy.md), [recovery and private resume](recovery-options.md).

GitHub Actions is currently disabled for this repository at the owner's request. Use local synthetic tests and local release builds; do not dispatch hosted jobs. Workflow definitions are retained for a future explicitly configured self-hosted runner setup. No self-hosted runners are installed by this change.

## Start

The self-contained Windows desktop package includes Python, Tk, FFmpeg and FFprobe. Extract the whole ZIP and open `start.bat` (or `VideoMate/VideoMate.exe`). No separate dependencies are needed; startup verifies the tools automatically. Apple Silicon development builds still need distribution qualification. See [desktop installation/builds](desktop.md).

Source launchers start with Python 3.11+ and can provision pinned tools and optional Python/Tk from offline archives or explicit online setup. Runtime-inclusive kits already contain Python/Tk. See [launch scripts and installation](launchers.md). Neither scanning nor repair uses the network.

From the checkout:

```powershell
.\start.bat --offline --cli doctor
.\start.bat --offline --cli gui
```

The GUI creates missing first-run settings, workspace folders and configured output/diagnostic/log directories at startup. Existing settings and contents are preserved; invalid files and unsafe locations are rejected. **Prepare workspace** recreates partially missing app folders, saves current preferences and verifies the selected settings file. A blank settings-file field uses the default. Empty log directories do not enable logging. On **Start**, choose a task, select the source, set the output if needed, then click the persistent Start button at the bottom. **Options** contains optional profiles/tuning. Activity supports cancellation, resume and grouped findings. Sensitive: Yes hides queue names and suppresses automatic exports/basic logs; Additional diagnostics separately enables safe technical logs. Both modes preserve originals and stay offline. No playback, thumbnails, browser server or automatic sharing is provided.

Extracted Python kits contain videomate.pyz at the root, launch scripts, setup tools and pinned FFmpeg/FFprobe. Kits built with --include-runtime also include Python/Tk; other kits need an existing interpreter initially. Their bundle manifest declares python_included. None is a signed production distribution.

To rebuild from source, use `py -3.13 tools/build_zipapp.py`. The [dependency guide](../dependencies/README.md) covers pinned offline provisioning on Windows, Apple Silicon and Linux.

## Workspace and inputs

The GUI creates its default workspace automatically under `%LOCALAPPDATA%/VideoMate/Workspace` on Windows or `~/Library/Application Support/VideoMate/Workspace` on macOS, or ~/.local/state/VideoMate/Workspace on Linux. For the CLI, create a new workspace once:

```powershell
.\start.bat --offline --cli init --workspace "$env:LOCALAPPDATA\VideoMateWorkspace"
```

Inputs and workspace must be local, outside the software/repository directory and known cloud-sync folders. Links/reparse points and network paths are rejected. These checks are conservative path rules, not proof of organization-approved storage or an OS sandbox.

```powershell
.\start.bat --offline --cli scan --workspace "$env:LOCALAPPDATA\VideoMateWorkspace" --input "D:\Videos\clip.mp4"
```

Replace the example path. Repeat `--input` for a batch. To scan a folder, select it explicitly and add `--recursive`; links, nested mounts, known sync/repository folders and the workspace are skipped. Discovery selects common video extensions, deduplicates filesystem identities and limits the job to 1,000 files and 100,000 visited entries. Explicit files do not need a recognized extension.

Full scanning probes the container and independently decodes each audio/video stream. `--depth quick` only probes and never establishes full decode health. Terminal summaries use input numbers instead of paths.

## Repair

Preview a guided plan:

```powershell
.\start.bat --offline --cli recover --workspace "$env:LOCALAPPDATA\VideoMateWorkspace" --input "D:\Videos\clip.mp4" --mode guided
```

Add `--execute` to carry out the guided policy, or use automatic mode:

```powershell
.\start.bat --offline --cli recover --workspace "$env:LOCALAPPDATA\VideoMateWorkspace" --input "D:\Videos\clip.mp4" --mode auto
```

| Option | Behaviour |
| --- | --- |
| `--strategy auto` | Compatible MP4 tries verified stream copy then eligible encoding; requested audio/quality/bitrate changes encode directly. Preservation re-encodes packet damage and otherwise tries container repair first. At most four codec/fallback attempts plus one finished-size adjustment attempt. |
| `--strategy remux` | Copy selected encoded audio/video streams into a new Matroska container. Corrupt encoded frames still require recovery or review. |
| `--strategy reencode` | Decode usable content and write a new candidate using the chosen profile. |
| `--profile preserve_decoded_samples` | Default: FFV1 video and PCM audio in Matroska, using eligible source pixel/sample formats. Can produce large files. |
| `--profile compatible_sdr` | MP4 stream copy when eligible; encoding fallback uses H.264 and adaptive AAC, limited to eligible progressive 8-bit YUV420 video and known supported speaker layouts up to eight channels. See recovery options for layout limits. |
| `--force` | Explicit conversion even when full inspection finds no errors; otherwise healthy files produce no replacement. |
| `--allow-shorter` | Permit a shorter verified candidate within `--max-shorter-percent` (default 10), beyond the existing timing tolerance. Longer-than-expected output remains a verification failure. |
| `--convert-all-mp4` | Try verified MP4 stream copy for clean and damaged files, then eligible SDR encoding. Explicit audio/quality/bitrate changes encode directly. Does not perform HDR tone mapping. |
| `--rate-control` | `auto`, `quality`, `source_size`, `target_size` or `bitrate`; see the recovery guide for budgets and limitations. |
| `--output-layout` | `neutral` by default; `filename` or `folders` applies only with Sensitive: No. |
| `--allow-track-loss` | Permit omitting subtitles, attachments, data streams and attached pictures. Without this, those inputs are blocked for repair. |
| `--keep-start 10 --keep-end 30` | Keep one common playback-relative interval, in seconds, by re-encoding. Record the removed leading/trailing intervals. |
| `--timeout 3600` | Maximum seconds per worker, up to 86400. |
| `--max-output-mib 0` | Optional absolute temporary candidate cap in MiB; off by default. Low-disk protection remains active. |
| `--max-source-percent 0` | Optional temporary source-relative cap; off by default, independent of the finished-size target. |
| `--size-tolerance-percent 25` | Allowed final overshoot for source/target size policies. Oversized candidates receive one bitrate adjustment; still-oversized results are withheld. |
| `--audio-normalization playback` | Optional single-pass loudness target (-16 LUFS); `broadcast` targets -23 LUFS; default `off`. MP4 re-encoding only. |

The interval option is explicit section salvage, not automatic localization of corruption. No arbitrary gap filling, silence/black-frame insertion or multiple-interval cutting is implemented. Timing comparison has finite tolerances and cannot establish perceptual lip-sync.

The preserve profile supports a bounded set of planar YUV/gray formats and PCM sample representations. HDR re-encoding, interlaced re-encoding and unverified transformations are blocked. Unknown/unsupported profiles may need specialist tools. A successful small synthetic test does not establish support for every codec, channel layout or legacy container.

Container/stream tags and chapters are excluded and disclosed as metadata loss. This is not anonymization: the pictures/audio and embedded codec payloads remain private. Decoder concealment can turn damaged input into a cleanly decodable output without restoring the lost original content.

## Verification and output

A candidate needs a successful recovery process **and** a fresh full decode with no detected errors, matching required stream count/properties, and timing comparisons. Checks compare known dimensions, pixel formats, sample rates, channels, aspect/colour/layout properties, relative stream starts and duration evidence. Timing tolerances are 100 ms for known relative starts and 250 ms for durations/endpoints. Missing essential duration evidence prevents verification.

Candidates passing these checks are published exclusively on the same filesystem: Windows uses rename with collision refusal; macOS/Linux use a hard link followed by removal from staging. Existing files are never replaced; unsupported publication fails with a fixed reason. Migration checks the operation with generated markers before inspecting source bytes. Rejected encoding attempts are removed after the worker exits. Scanning/recovery never overwrite, move or delete originals. Manual cleanup is a separate selected-file action requiring typed confirmation. The source's filesystem identity/size/mtime are checked around work; this detects many changes but is not a trusted source-content checksum. Optional private resume additionally hashes reselected content locally.

`verified_with_losses` means the candidate passed those checks and its disclosures need review. Metadata exclusion alone produces this status. A verified output does not prove completeness, visual fidelity or perfect synchronization.

| Location | Contents |
| --- | --- |
| `recovered/<job-id>/input-N` | Neutral verified outputs; non-sensitive layout choices may use other subfolders beneath the job root |
| `jobs/session-<random>` | Minimal-retention scratch/candidates; removed on normal completion/cancellation, with no SQLite file |
| `jobs/<job-id>/job.sqlite3` | Optional retained private journal with input paths, results, settings and output locators/hashes |
| Sibling `candidates-<random-id>` for direct migration; `.candidates` for Repair/older packages | Private staging on the publication filesystem; only owned current-job candidates are removed after workers stop |
| `state` | Optional private checkpoints, non-sensitive opt-in mappings and a generic lock marker; never share |
| `export-review` | Sanitized text log on explicit export; optional validated technical JSON batches |

## Resume, sort and export

Every run prints a random local job ID. Keep it locally. New Sensitive jobs have no saved history by default: GUI reports remain in memory for the most recent eight jobs and must be exported before closing. CLI users can request `--export-on-completion` during the run. Enable `--retain-history` only if plaintext source paths in saved SQLite are acceptable. For retained jobs, `recover --job <id>` reuses the prior input list for a fresh inspection and new policy.

Private resume is the path-free alternative: use `--private-resume`, then reselect the same complete input set and use `scan` or executed `recover --checkpoint <id>` with the same policy and passphrase. It matches keyed content hashes locally. Changed source content or policy/version rejects reuse; missing/altered recovered outputs are reprocessed. Checkpoints are authenticated technical data, not encryption, and are deleted on batch completion. See [private resume](recovery-options.md). The commands below apply to ordinary retained history:

```powershell
.\start.bat --offline --cli resume --workspace "$env:LOCALAPPDATA\VideoMateWorkspace" --job <job-id>
.\start.bat --offline --cli report --workspace "$env:LOCALAPPDATA\VideoMateWorkspace" --job <job-id>
.\start.bat --offline --cli export-diagnostics --workspace "$env:LOCALAPPDATA\VideoMateWorkspace" --job <job-id>
```

Reports group input numbers by integrity and recovery outcome. Sorting never moves originals. Resume restarts interrupted files/attempts rather than claiming arbitrary frame-level continuation. Unchanged completed inputs are skipped; verified output hashes are checked before reuse. A changed source/output/backend causes reprocessing. Simultaneous writers to one job are blocked with an OS file lock.

Cancellation stops workers. With minimal retention, available sanitized reports stay in the current GUI session only; private checkpoints retain eligible completed work if enabled. Sensitive: No writes diagnostics for available results after ordinary cancellation. Sensitive jobs require an explicit export request. Abrupt termination/disk failure can prevent export or leave an orphan candidate/output. Only opted-in persistent history or private checkpoints can survive process exit. Ordinary `resume` keeps the saved policy; it does not turn a guided preview into an executable plan.

Exit codes: `0` no attention required; `1` findings/review/disclosed recovery losses; `2` blocked or failed work; `130` cancellation. Never infer a repair failure just from exit `1`: verified outputs with disclosed losses use it intentionally.

## Privacy and deployment limits

Share only diagnostic JSON you have reviewed in the configured diagnostics folder (workspace/export-review by default). Never share source/recovered media, raw FFmpeg logs, SQLite files, private mappings or keys. Detailed exports retain allowlisted technical properties and relative durations, which may themselves be sensitive. No upload occurs automatically.

Each export uses a fresh HMAC key in memory. Mappings are disabled for Sensitive jobs and require opt-in otherwise. There is no production credential vault. Retained SQLite files and private checkpoints are not encrypted. Decode/encode output is classified incrementally; raw lines are bounded in memory and never persisted/displayed.

The previous test-only gate has been replaced by explicit local selection and Sensitive: Yes/No. OS-enforced isolation, workspace encryption and signed distributions remain separate work. Native macOS/Linux evidence covers the published preview, not the new source paths. The assistant never accesses existing operator media.
