# VideoMate

An independent offline video inspection and recovery project by **samuel-zhang01**. This project is unaffiliated with other products or projects using the VideoMate name.

<img src="assets/videomate-mark.png" alt="VideoMate logo" width="120">

**Offline video inspection, verified recovery, and folder migration.** VideoMate runs FFmpeg and FFprobe locally through a native desktop interface or command line. Inspection, repair, and migration preserve your original files. Recovery can retain readable material; it cannot recreate missing bytes.

**Current source: 0.8.4 development preview.** Build paths exist for Windows, macOS, and Linux, but the latest source has not passed all native release gates. Apple Silicon development builds are ad hoc signed; signing, notarization, clean-machine checks, and native ARM64 qualification remain open. See [implementation status](docs/implementation-status.md). Source availability does not qualify downloadable binaries.

## What you can do

| Task | Use it for | Result |
| --- | --- | --- |
| **Inspect** | Check selected videos without creating replacements | Container findings and, by default, full software decoding of audio/video streams |
| **Repair** | Recover readable material from selected videos | New outputs published only after independent decode, stream-property, and timing verification |
| **Migrate** | Build a new collection from one mixed folder | Byte-verified healthy/non-video copies, verified repairs, and explicit counts of unresolved files |

Controls include remuxing, FFV1/PCM preservation, eligible H.264/HEVC MP4 conversion, profiles, approximate size targeting, optional audio normalization, qualified hardware encoding, cancellation, and private restart checkpoints. There is no playback, thumbnail service, upload, telemetry, or processing-time network access.

## Install and start

### From source

Download/extract the source or clone it to a software folder. Keep inputs, outputs, settings, and job workspaces outside the checkout and cloud-sync folders.

| Platform | Open the desktop interface | Check setup without selecting media |
| --- | --- | --- |
| Windows x64 / ARM64 | Double-click `start.bat`, or run `.\start.bat` in PowerShell | `.\start.bat --check` |
| macOS Apple Silicon | Open `start.command`, or run `sh start.sh` in Terminal | `sh start.sh --check` |
| Linux x64 / ARM64 | Run `sh start.sh` in a graphical session | `sh start.sh --check` |

Python 3.11+ is required; the GUI also needs Tk and a display. The application has no runtime pip dependencies. Linux requires compatible glibc and display libraries; Alpine/musl is not qualified. Intel Mac and 32-bit builds are not current targets. Platform support remains subject to the qualification limits above.

The launchers reuse suitable existing Python, activated venv/Conda environments, or a bundled runtime. If Python/Tk must be downloaded, setup explains the local installation and asks first, defaulting to No. Missing checksum-pinned FFmpeg/FFprobe is provisioned automatically unless `--offline` is set. `--yes` or `--setup-online` permits unattended setup. Installed tools are reused without update checks. Setup does not change OS security settings or install system packages.

### Fully offline installation

Use a complete, qualified desktop/runtime package, or transfer the source plus the exact archives listed in the [dependency catalogs](dependencies/README.md). To prohibit downloads from the first launch:

```powershell
.\start.bat --offline --check
.\start.bat --offline
```

```sh
sh start.sh --offline --check
sh start.sh --offline
```

If software is missing, supply pinned archives or prepopulate the software cache; offline mode fails rather than downloading. For example, on macOS/Linux:

```sh
sh start.sh --offline --archive-directory /approved/software/archives \
  --runtime-archive /approved/software/pinned-python.tar.gz --check
```

Replace these illustrative software paths with your own. Catalog checksums must match; suspect installed bundles are refused. The [setup guide](docs/launchers.md) covers Windows archive flags, custom interpreters, caches, and troubleshooting.

### Packaged desktop builds

When a qualified package is published, choose the matching OS/architecture and extract the **entire** archive. Python/Tk and processing tools are included. Use `start.bat` on Windows, `start.command` on Apple Silicon, or `./start.sh` on Linux. Keep notices and license files with the package; copying just the executable is insufficient.

Native desktop launchers support GUI startup, `--check`, and `--self-test NEW-REPORT.json`. Use source/Python-kit launchers for the CLI and provisioning flags. See [desktop packaging](docs/desktop.md) and [release gates](docs/releases.md). This source preparation does not publish or qualify new binaries.

## Use the desktop interface

### First run

1. Open VideoMate. It creates missing default settings and workspace directories without replacing unrelated contents. If preparation is blocked, choose valid local locations in **Settings → Storage**, then use **Prepare workspace**.
2. Leave **Sensitive: Yes** enabled for private material. Queue names are hidden and automatic exports/basic logs are off. **Additional diagnostics** separately opts in to sanitized technical disk logs.
3. On **Start**, choose **Inspect**, **Repair**, or **Migrate**, select your source, and choose an output location when needed.
4. Use **Options** for a processing profile and optional tuning. Start the task using the button at the bottom of the window.
5. Watch **Activity** for progress, findings, cancellation, completion state, and diagnostic export controls. Review the final result before relying on outputs.

### Inspect videos

Select files, or explicitly select a folder and recursive discovery. **Full** inspection is the default: it probes the container and independently decodes each audio/video stream in software. **Quick** inspection only probes metadata and cannot establish file-wide health. Inspect does not repair or replace files.

Inspect/Repair folder discovery is bounded to 1,000 files and 100,000 visited entries. Links, reparse points, unsafe locations, and unsupported selections are refused or excluded according to discovery policy. Migration has a separate inventory policy.

### Repair selected videos

Choose a separate output folder and recovery profile. Guided mode previews the plan; automatic mode tries the selected bounded policy. Healthy inputs normally receive no replacement unless conversion is explicitly requested.

| Choice | What it does | Tradeoff |
| --- | --- | --- |
| Remux | Copies eligible encoded streams to a new container | Does not reconstruct corrupt encoded frames |
| Preserve decoded samples | Uses FFV1 video / PCM audio in Matroska for supported formats | Can create very large files; damaged decoded material is not restored original content |
| Compatible SDR / MP4 | Tries eligible stream copy, then H.264/AAC encoding when needed; HEVC is optional | Encoding is lossy and limited to supported source properties |

Every published repair needs fresh full software decoding, stream-property checks, and timing evidence. Successful FFmpeg exit alone is insufficient. Metadata removal and explicitly permitted shortening/track loss are disclosed. **Verified with losses** requires review; it does not promise original fidelity or perceptual lip-sync.

For similar MP4 sizes, **Use source-size MP4 defaults** selects size targeting and clears temporary size caps. Targets are approximate; finished outputs above the tolerance can receive one adjustment attempt. Optional normalization changes encoded audio. Read [recovery options](docs/recovery-options.md) before enabling shortening, track loss, partial salvage, or all-file conversion.

### Migrate a folder

1. Choose exactly one local source folder. Recognized videos receive full inspection; other ordinary files are copied and byte-verified. Archives are copied without expansion.
2. Choose an **empty destination** separate from the source and workspace. VideoMate mirrors files/subfolders directly into it. Status/ownership sidecars and temporary staging sit beside it.
3. Choose a profile: keep healthy formats, keep healthy files with MP4 recovery, convert all eligible videos to MP4, or selectively convert noncompliant videos to HEVC MP4.
4. Choose the unresolved-file policy **before** starting: exclude and report omissions (default), copy unchanged into output, or copy unchanged to a separate review folder. Originals remain at their source in every case.
5. With Sensitive: Yes, explicitly permit original names/folders in this local output. The package remains private media. With Sensitive: No, migration preserves names automatically.
6. Choose session-only continuation or enable a private restart checkpoint before starting. Keep the source tree unchanged throughout the job.
7. Review Activity and the adjacent status file. `complete` means selected files were successfully copied/repaired without partial salvage. `needs_review` means partial recovery or unresolved videos. `incomplete`, `building`, and `interrupted` must not be treated as completion.

Migration is a content migration, not a complete filesystem backup. ACLs, extended attributes, resource forks, alternate streams, and hard-link relationships are not preserved. Unknown video extensions are treated as ordinary files rather than certified healthy videos. Keep an independent backup. See [migration and profiles](docs/migration-and-profiles.md).

### Stop, continue, or resume

- **While the app stays open:** stop a migration, reselect the same source/destination/options, then use **Continue stopped migration**. Completed outputs are verified before reuse.
- **After closing the app:** restart is available only if **Private resume** was enabled before the job. Reselect the original roots and policy; use **Activity → Resume from private checkpoint…** with the original Job ID and passphrase.
- **Start new migration:** requires a new empty destination. A diagnostic export cannot restore a lost checkpoint.

Private checkpoints authenticate path-free technical state using passphrase-keyed content IDs. They are **not encrypted**, and the passphrase is not saved. Changed sources, outputs, policy, storage identity, or ownership can prevent reuse. Session-only state is lost when the app closes. [Interruption recovery](docs/interruption-recovery.md).

## Use the command line

Run from the source root. Launcher flags come **before** `--cli`; command options come afterward. Paths below are invented examples to replace locally. They do not authorize assistant access to existing media.

```sh
sh start.sh --offline --cli --help
sh start.sh --offline --cli recover --help
sh start.sh --offline --cli init --workspace /local/videomate-workspace

# Full inspection; explicitly export before the process exits.
sh start.sh --offline --cli scan --workspace /local/videomate-workspace \
  --input /local/selected-video.mp4 --sensitive yes --export-on-completion

# Guided preview; add --execute to carry out the plan.
sh start.sh --offline --cli recover --workspace /local/videomate-workspace \
  --input /local/selected-video.mp4 --sensitive yes --mode guided

# Automatic recovery into separate outputs.
sh start.sh --offline --cli recover --workspace /local/videomate-workspace \
  --input /local/selected-video.mp4 --sensitive yes --mode auto \
  --export-on-completion

# Inventory a mixed collection before migration.
sh start.sh --offline --cli migrate --workspace /local/videomate-workspace \
  --input /local/collection --recovered-dir /local/new-empty-destination \
  --sensitive yes --local-output-names --preview

# Build the package; unresolved files stay at their original source.
sh start.sh --offline --cli migrate --workspace /local/videomate-workspace \
  --input /local/collection --recovered-dir /local/new-empty-destination \
  --sensitive yes --local-output-names --unresolved exclude \
  --export-on-completion
```

On Windows, use `.\start.bat` and Windows paths:

```powershell
.\start.bat --offline --cli init --workspace "$env:LOCALAPPDATA\VideoMateWorkspace"
.\start.bat --offline --cli scan --workspace "$env:LOCALAPPDATA\VideoMateWorkspace" `
  --input "D:\SelectedVideos\example.mp4" --sensitive yes --export-on-completion
```

`init` creates a new workspace; its parent must already exist. Repeat `--input` for Inspect/Repair batches, and add `--recursive` for subfolders. `--config` loads local preferences; explicit command options override them. `--private-resume` prompts for a passphrase in an interactive terminal. Do not put passphrases in command arguments.

| Exit | Meaning |
| --- | --- |
| `0` | No attention required |
| `1` | Findings, review needed, or disclosed recovery losses; a verified output can still exist |
| `2` | Blocked or failed work |
| `130` | Cancellation |

For retained jobs, `report`, `resume`, and `export-diagnostics` accept `--job` and `--workspace`. They cannot retrieve another process's memory-only session. Use `--export-on-completion` for minimal-retention CLI runs. [Complete CLI operation guide](docs/local-testing.md).

## Privacy and diagnostics

Sensitive: Yes is the default. It hides queue names, uses memory-only job history by default, disables automatic exports/basic disk logs, and uses neutral Repair output names. **Additional diagnostics** independently enables bounded sanitized technical disk logging. Sensitive: No permits local names and ordinary retained history while keeping offline operation and the closed diagnostic schema.

Explicit exports contain opaque HMAC identifiers, fixed categories, and allowlisted technical fields such as playback-relative timestamps. They exclude filenames, paths, recording dates, embedded free-form text, media bytes, raw FFmpeg logs, command lines, and keys. Technical exports can still be distinctive; review locally before sharing.

Use **Activity → Export diagnostic log** before closing a memory-only session. It writes a grouped text log. CLI `export-diagnostics --technical-json` adds validated JSON pages for retained jobs. `support-summary` validates an already-sanitized JSON export and prints an identifier-free summary; it does not accept raw logs or the text export.

These controls are application policy, **not encryption or an OS sandbox**. Settings, opted-in persistent history, outputs, and checkpoints require private storage. Crash remnants, paging, backups, and host dumps are outside normal cleanup. Removing metadata does not anonymize video/audio content. [Settings and privacy](docs/settings-and-privacy.md), [diagnostic contract](docs/privacy-and-diagnostics.md), [security reports](SECURITY.md).

## Limitations and troubleshooting

- **Missing software:** run the setup check; supply catalog-pinned archives for offline use. CLI can operate without Tk. Tk import alone does not prove a display exists.
- **Rejected paths:** use local ordinary paths outside repositories, cloud-sync storage, and the source tree. Links/network paths are refused. New migration destinations must be empty.
- **Unsupported repair:** HDR/interlaced re-encoding, arbitrary gap filling, missing-header reconstruction, and specialist codec/layout recovery are outside the implemented policy. Failed repair does not establish irrecoverability.
- **Slow processing:** integrity checks and final verification use software decoding. Hardware encoding has generated-frame qualification and software fallback. More parallel lanes can be slower on limited storage/CPU; reduce parallel files in Settings. **Optimize selected codec** benchmarks synthetic media only.
- **macOS distribution:** development builds are ad hoc signed and have failed Gatekeeper assessment. Signing/notarization and clean-machine qualification remain open; do not disable OS protections to qualify a release.
- **Original cleanup:** a separate manual feature requires individually selected files and exact confirmation. It never runs as a scan/repair/migration side effect.

## Documentation and development

Start with the [documentation index](docs/README.md).

```text
src/videomate/      Application and platform adapters
tools/             Setup, packaging, source/publication checks
tests/             Generated-fixture and source checks
docs/              User guides, privacy contracts, release gates
docs/development/  Curated development evidence and design audit
dependencies/      Public software catalogs and license notices
schemas/           Closed diagnostic export schema
examples/          Wholly synthetic diagnostic example
assets/            Project branding
```

Contributions/tests use generated fixtures only. Never commit operator media, exports, settings, state, builds, or downloaded dependencies. See [contributing](CONTRIBUTING.md) for focused checks and the source-only hook. GitHub Actions remains disabled; retained workflows are manual definitions for future authorized use.

VideoMate's source is licensed under [MIT](LICENSE). Copyright **samuel-zhang01**; retain the copyright and permission notice when redistributing copies or substantial portions. Bundled dependencies retain their own licenses. See [third-party notices](THIRD_PARTY_NOTICES.md); binary distribution needs review of exact bundled notices and corresponding-source materials.
