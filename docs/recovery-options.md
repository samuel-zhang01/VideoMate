# Recovery options and private resume

These features are included in the **0.8.4 local release candidate**. Finish any running job before restarting the source launcher with `--offline`.

Migration and saved processing profiles were added in source 0.8. See the [workflow guide](migration-and-profiles.md). Migration has an explicit Sensitive local-output naming exception; ordinary Repair retains neutral names.

Current source offers **Try one last verified partial recovery for damaged videos** (on by default in new GUI settings and built-in Repair/Migration profiles; CLI `--partial-salvage` / `--no-partial-salvage`). After ordinary attempts fail, it tries a software re-encode that can retain a playable portion shorter than the reported source duration. The source must have known duration and evidence of damage/truncation; the result must have a fresh, complete software decode and pass stream/property/timing checks under the disclosed shortening policy. A nonzero FFmpeg exit can be accepted only on this final salvage attempt and only when the resulting candidate independently passes those checks. The result is tagged `partial_salvage`; migration places it in the main package and marks the package `needs_review`. It does not synthesize missing bytes, reconstruct absent MP4 initialization, guarantee every usable interval, or overwrite the original. A strict size target can still withhold a playable candidate; choose best effort if retaining verified content matters more than approximate size.

## Names and folders

Recovery always writes separate copies beneath the selected recovered-files directory and a neutral job ID. Ordinary Sensitive Repair jobs force neutral filenames under `input-N`, regardless of a saved layout preference.

With **Sensitive: No**, choose **Keep source filename** or **Keep filename and folder structure** in Options. Folder structure is relative to the folders explicitly selected; multiple roots use `selection-N` namespaces. Selecting an individual file does not reproduce its absolute parent path. Output extensions reflect the selected container. A collision adds `.recovered-N`; existing files and originals are never overwritten. Paths and names stay out of diagnostics in both modes.

CLI: `--output-layout neutral|filename|folders`. Folder discovery still requires `--recursive` when appropriate.

## MP4, quality and size

**Convert all eligible files to MP4** selects automatic MP4 recovery even for clean inputs. It first tries lossless container conversion (stream copy) for supported codecs, then verifies the candidate with full software decoding and stream/timing checks. A rejected copy falls back to eligible H.264/AAC encoding, with hardware preferred. Explicit audio processing, quality or bitrate changes require encoding from the start. Source/target-size policies can accept a copy within the size ceiling; an oversized copy falls through to encoding.

**Selective HEVC migration** is a separate built-in profile. Healthy `.mp4` files whose video streams are H.264 or HEVC are copied unchanged. Other recognized video files, including MOV files, and damaged video inputs go through verified HEVC/AAC MP4 encoding with playback loudness normalization. This profile does not normalize the healthy files it copies. It uses the source dimensions, passthrough frame timing, known audio sample rate/channels and an estimated video bitrate; for non-HEVC source video, Auto aims at 80% of the source video bitrate. The result may be larger or smaller and visual quality is not certified. Software libx265 and generated-frame-qualified HEVC hardware encoders are eligible. If one qualified hardware route fails on a file, other qualified GPU encoders are tried before libx265. A verified hardware route becomes that worker's first choice on later inputs. No attempt bypasses verification or silently changes codec. HDR, interlaced, unsupported pixel/audio layouts, missing initialization and severe timing loss can remain unresolved.

Stream copy preserves the encoded video/audio, including eligible HEVC 10-bit and multichannel tracks. Metadata/chapters may still be omitted, and auxiliary-track omission requires permission. MP4 does not guarantee universal player support: copied DTS, HEVC or AV1 remain those codecs. HDR-to-SDR tone mapping is not implemented; clean HDR can be copied, but unsupported HDR/interlaced/pixel-format transformations cannot be encoded. AAC encoding preserves known supported speaker layouts up to eight channels; unknown layouts and 5.1(side) remain blocked because this AAC encoder changes the layout. No silent downmix or speaker remapping is allowed.

| Rate policy | Behaviour |
| --- | --- |
| Auto | Use source video bitrate when known, bounded by source size/duration with room for audio/overhead; otherwise estimate from source size/duration or image geometry/frame rate. |
| Quality | Software libx264/libx265 use the selected CRF, default 18. Hardware encoders use the Auto bitrate estimate; CRF is not a portable hardware quality control. |
| Match source size | Estimate a video budget from source bytes and duration, reserving AAC audio and container overhead. |
| Target size | Estimate a video budget for the selected MiB per file. |
| Video bitrate | Use the selected kbit/s per video stream. |

The built-in MP4 profiles now select **Approximate source file size**. **Use source-size MP4 defaults** on Options applies that choice and turns off temporary size caps, including caps retained in older settings. It leaves privacy and storage permissions unchanged. Healthy migration copies remain byte-for-byte unchanged; enable Convert every eligible file to apply encoding options to healthy videos too. Lossless FFV1 cannot promise similar output sizes. MP4 stream copy remains subject to an enabled finished-size ceiling.

Size policies use average-bitrate encoding, not exact byte-size guarantees. Source/target size modes check the finished candidate: if it exceeds the target by more than **25%** (configurable 5–100%), one additional encoding attempt reduces the video bitrate using the observed size. Hardware remains preferred for that attempt. If the result still exceeds tolerance, it is not published as a verified repair; migration's selected unresolved policy applies. Smaller verified outputs are kept without padding and reported as below target when outside tolerance. A retry adds processing time. This is a bounded correction, not a conventional two-pass encoder analysis. Auto/Quality/custom bitrate modes do not enforce a finished-size target.

Missing duration/size evidence or an infeasible video budget blocks the plan. Adaptive AAC uses each track's known source bitrate, bounded below at 32 kbit/s and above at the larger of 192 kbit/s or 64 kbit/s per channel (up to eight); without a known bitrate it defaults to 64 kbit/s per channel; an explicit AAC bitrate overrides this budget. Multiple video tracks share the estimated video budget. Auto can use video bitrates down to 50 kbit/s for small low-bitrate sources.

Temporary candidate caps are optional and **off by default**: `--max-output-mib 0` and `--max-source-percent 0`. When explicitly enabled, the smaller enabled limit applies, with a 1 MiB floor for the source ratio. Existing saved settings are retained; apply the new MP4 defaults to clear previous caps. These limits are separate from finished-size targeting. Low-disk protection (64 MiB reserve), timeouts, cancellation and verification remain enabled. FFmpeg's `-fs` truncation is not used. `.candidates` holds full proposed outputs until verification/publication or rejection; rejected attempts are removed after the worker exits. Temporary growth is allowed, not a promise of unlimited disk space. A crash can leave private remnants.

CLI flags: `--convert-all-mp4`, `--convert-noncompliant-hevc`, `--video-codec h264|hevc`, `--rate-control auto|quality|source_size|target_size|bitrate`, `--size-tolerance-percent 25`, `--video-bitrate-kbps 8000`, `--target-size-mib 500`, `--quality-crf 18`, `--max-output-mib 0`, `--max-source-percent 0`. The selective preset fixes Auto rate control and playback normalization; use the ordinary MP4 mode for custom rate/size policies.

## Audio and playback conveniences

Options → advanced recovery includes a small set of MP4 controls. All are saved in custom processing profiles and available in the CLI:

| Choice | Behaviour |
| --- | --- |
| Loudness: Off / Playback / Broadcast | Off by default. Playback targets -16 LUFS; Broadcast targets -23 LUFS. Both use a -1.5 dBTP target and LRA 11 with single-pass dynamic `loudnorm`, independently per audio track. |
| AAC bitrate | Adaptive by default (`0`), or 64/96/128/160/192/256/320 kbit/s per track. The selected audio budget is reserved before calculating video bitrate. |
| Software encoding speed | Fast / Medium / Slow; default Medium. Applies to libx264/libx265, including software fallback; hardware remains preferred. The selective HEVC profile uses Fast. Faster encoding trades compression efficiency for speed. |
| MP4 fast-start | On by default. Places the playback index at the front of the completed file. Can be disabled to avoid that extra file rearrangement. |

Loudness processing changes audio samples and may compress dynamic range; it does not restore missing audio or certify a broadcast delivery. FFmpeg's dynamic normalization internally upsamples, so VideoMate explicitly retains the selected source sample rate and channel count and verifies them afterward. Silent, very short or heavily damaged audio may not reach the requested target. No measured levels, raw filter output or source metadata enter diagnostics; exports disclose `audio_normalized` and the fixed requested preset. See [FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm) and [MP4 fast-start](https://ffmpeg.org/ffmpeg-formats.html#mov_002c-mp4_002c-ismv).

Audio options require Compatible SDR re-encoding; preservation/remux combinations are rejected with a fixed explanation rather than silently ignoring the audio change. Automatic strategy selects re-encoding when audio options are active. Healthy migration copies still stay unchanged unless all-file conversion is selected. No resizing, frame-rate conversion, denoising, subtitle burn-in or HDR tone mapping is added by these controls.

CLI: `--audio-normalization off|playback|broadcast`, `--audio-bitrate-kbps 0`, `--software-preset fast|medium|slow`, `--mp4-faststart` / `--no-mp4-faststart`.

## Losses and repair details

Shorter output still requires **Allow shorter**. The new maximum shortening is 10% by default and is checked against known file and decoded-stream durations, outside the existing 250 ms timing tolerance. Set `--allow-shorter --max-shorter-percent N` to choose a limit from 0 to 100. Manual interval salvage compares against the requested interval. This is a duration guard, not proof that every interior frame survived.

Activity and sanitized exports include per-attempt decoder/encoder, required verification checks, fixed failure reasons and output duration changes. `verified_with_losses` can mean metadata removal alone; review the specific disclosures. Repeated FFmpeg errors are counted as typed categories while streaming, so a noisy decode no longer exhausts the raw log capture budget. Worker timeouts, cancellation, candidate-size limits and full candidate verification remain enforced. Null verification preserves the demuxer time base to avoid avoidable timestamp rounding; this does not waive genuine timestamp errors. See [FFmpeg's time-base and frame-rate options](https://ffmpeg.org/ffmpeg.html).

## Minimal retention and private resume

New Sensitive jobs keep their source paths and job journal in memory. No export-to-filename mapping is written. Normal completion or cancellation removes this session's private scratch/candidate directories; published recovered files remain. Up to eight sanitized session reports remain in memory for explicit export until the app closes. In the CLI, use `--export-on-completion` if you need a report after the command exits.

For restartable Sensitive work, enable **Private resume** in Settings before starting. Enter a strong passphrase of at least 12 characters. Keep the neutral job ID locally. To continue after interruption:

1. Reselect the same complete set of files, possibly renamed or in a different order.
2. Restore the same recovery policy, source version, backend version and output location.
3. Enter the job ID in Activity and choose **Resume private scan** or **Resume private repair**.
4. Enter the same passphrase. The program reads and hashes the selected files locally to match them. No assistant performs this step on real files.

Completed work is reused at file boundaries. Partial or unsuccessful repairs restart. Completed recovered outputs must still exist with matching hashes; missing or changed outputs are reprocessed. Changed source content or a changed policy rejects the checkpoint; start a new job instead. There is no frame-level continuation. Hashing the entire selection adds disk I/O before processing.

CLI: add `--private-resume` to a scan or an executed recovery. On a later invocation, reselect the inputs with the same flags and add `--checkpoint <job-id>`. The passphrase is requested from an interactive terminal; there is no command-line or environment-variable secret option. Guided previews do not create checkpoints.

The checkpoint uses a random salt and PBKDF2-HMAC-SHA256 (600,000 iterations) to derive a key. It stores keyed content identifiers and authenticates the whole document. It contains no source names/paths, raw source hashes or saved passphrase. It **is not encrypted**: counts, codec/timing results and neutral recovered-output references remain readable and linkable within the checkpoint. Weak passphrases can be guessed offline. Never share a checkpoint. It is deleted after the batch finishes, including batches ending with review/failed results. This is ordinary file deletion, not secure erasure.

Private resume takes precedence over the optional **Keep Sensitive job history** setting. That separate history option restores ordinary SQLite resume with plaintext source paths. Sensitive: No jobs retain ordinary history; filename mappings require a separate opt-in. Existing jobs, mappings and logs are not retroactively erased. A hard crash can leave temporary/candidate files, and host paging/crash dumps are outside the app's retention controls.

## Separate manual cleanup

An unreadable result is not proof that a file is irrecoverable. Cleanup is never automatic. Select individual entries on Start, then use the separate cleanup action under advanced Options to move them to a review folder or delete them. Folders are not accepted. The local dialog requires the exact phrase `QUARANTINE N` or `DELETE N` for the selected count.

Quarantine moves each selected original into a hidden `.videomate-review` folder beside it, with a neutral name. That folder is excluded from recursive discovery. No original-name mapping is retained; restoration is manual. The content is still sensitive. Deletion is permanent from VideoMate's perspective and does not promise secure erasure. Stopping midway does not undo earlier completed actions. CLI equivalents are `cleanup --input <file> --action quarantine|delete --confirm "ACTION N"`.

## Migration restart

Migration has a separate indexed checkpoint and reconnect scheduler, without the Inspect/Repair checkpoint's 1,000-file limit. Enable Private resume before the first migration; resume through Activity → Resume from private checkpoint… or `migrate --checkpoint <id>` with the original policy, selected roots and passphrase. It verifies already published outputs, retries temporary failures and leaves unresolved originals unchanged. [Full contract and limitations](interruption-recovery.md).

## Explicit finished-size policy (current source)

`--size-policy strict` retains existing withholding behavior. `--size-policy best_effort` permits a fully verified oversized output with a fixed warning after one bounded bitrate adjustment, and falls back to Auto when a size estimate is unavailable. New MP4 presets choose best effort; saved settings remain strict until changed. This never disables media verification or low-disk limits. [Result review and retry workflow](completed-jobs-and-retries.md).
