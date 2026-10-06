# Product design — current 0.8 behaviour

VideoMate helps an operator distinguish readable, damaged, unreadable and inconclusive videos, select a recovery policy and verify the result. It cannot manufacture missing original content.

## Workflow

1. Start the offline GUI or CLI and check software without opening media.
2. Choose Sensitive: Yes/No, select local inputs and configure storage in Settings.
3. Inspect the container and, by default, decode every intended audio/video stream.
4. Preview a guided policy or run automatic recovery.
5. Independently verify candidates; publish only outputs passing required checks.
6. Review grouped outcomes and export session diagnostics before closing. Resume interrupted work only when retained history or a private checkpoint was enabled.

The GUI has Start, Options, Activity and Settings pages. Sensitive: Yes replaces visible queue paths with neutral item numbers and disables automatic diagnostic exports and basic disk logs. Additional diagnostics beside Sensitive opts in to enhanced safe disk logs in either mode. Explicit sanitized export remains available. Sensitive: No displays local paths; no mode generates media previews. GUI and CLI share services. Software hashes/executable health/encoders are checked automatically, and startup creates missing settings and storage directories without overwriting existing files.

## Recovery choices

Workflow selection comes before advanced controls: **Inspect** reports health, **Repair** writes verified recovered copies, and **Migrate** builds a new mixed-file collection. Seven built-in processing profiles and up to twelve custom presets collect the underlying options. Start keeps task, source, output and migration policy together; the primary action stays visible at the bottom of every page. Preview and profiles are optional. Privacy/storage remain independent; migration needs separate consent to preserve Sensitive local output names. [Migration package and profile design](migration-and-profiles.md).

| Choice | Behaviour |
| --- | --- |
| Guided | Preview the policy before explicit execution |
| Automatic | Bounded eligible remux/re-encode sequence; qualified GPU routes precede software encoding and every candidate is verified |
| Remux | Copy selected encoded audio/video streams into Matroska |
| Preserve decoded samples | Eligible FFV1/PCM re-encoding into Matroska |
| Compatible SDR | Eligible lossy H.264/AAC conversion to MP4 |
| Convert all eligible files | Verified MP4 stream copy first, then eligible encoding; also applies to clean inputs |
| Rate/size policy | Source estimate, software CRF, explicit bitrate or approximate source/target size |
| Output layout | Neutral names, or non-sensitive basename/selected folder structure |
| Section salvage | CLI-only explicit common interval with recorded cuts |

Healthy inputs need no recovered copy unless conversion is forced. Shorter output and auxiliary-track omission need explicit options; allowed shortening defaults to a 10% ceiling beyond timing tolerance. Unsupported HDR/interlaced re-encoding stops for review. Metadata/chapters are omitted and disclosed. [Exact recovery and private resume options](recovery-options.md).

New Sensitive jobs have memory-only journals and no export mappings. Optional private resume stores authenticated keyed content IDs and technical results, without source paths; reselecting files and entering the same passphrase matches completed work locally. It is not encryption. Non-sensitive jobs or explicit Sensitive history opt-in use ordinary private SQLite journals. Existing state is not erased. Separate original-file cleanup requires individual selection and typed confirmation; there is no automatic deletion based on a result.

## Result meanings

Completion, integrity, source completeness and recovery are separate facts. A clean full decode does not establish completeness; quick inspection cannot label the whole file healthy. Unreadable files may need another copy or specialist reconstruction and are never silently deleted or moved.

`verified_with_losses` means required checks passed and disclosures need review, including metadata loss. Sorting groups findings without moving originals. Resume works at file/attempt boundaries, not arbitrary frames.

Automatic reliable damage localization, multiple-interval editing, reference-assisted missing-header recovery, broader profiles, OS isolation/encrypted storage and signed distributions remain future work. There is no cloud repair or remote preview feature. [Release gates](validation-and-roadmap.md).
