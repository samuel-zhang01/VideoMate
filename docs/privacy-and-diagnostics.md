# Privacy and diagnostic export design

Status: binding privacy requirements, implemented test-edition controls and explicitly marked production design. Documents alone do not establish deployment protection.

Source 0.7 implements offline processing, explicit local selection, sanitized exports and Sensitive: Yes/No treatment. Yes hides queue filenames, defaults to memory-only journals, and disables automatic exports/basic disk logs. Explicit sanitized export remains available. Additional diagnostics independently opts in to safe technical disk logging. No keeps the same export restrictions. Optional retained state and settings are local plaintext; encryption and OS isolation are not implemented. See [settings](settings-and-privacy.md) and [implementation status](implementation-status.md).

New Sensitive jobs store paths, private timing evidence and recovered-output hashes in an in-memory SQLite journal; normal completion/cancellation removes owned scratch and candidate directories. Published outputs remain. Up to eight sanitized session reports stay in memory until the app closes. Ordinary persistent SQLite history is retained for non-sensitive jobs or by explicit Sensitive history opt-in. No Sensitive export mappings are written. Existing state is not discovered or purged. None of the private locators, absolute timing values or hashes enter exports. GUI selections stay in memory; there is no media preview or browser server. Removing container tags/chapters does not anonymize media or strip every embedded bitstream payload.

Optional private resume stores passphrase-keyed content IDs, authenticated typed results and neutral recovered-output references, with no source paths, raw source hashes or saved passphrase. The checkpoint is not encrypted and is never shareable diagnostic data. The operator must reselect the same files and enter the same passphrase; the program hashes those files locally. It checks policy/version and recovered-output hashes before reusing completed work, then deletes the checkpoint when the batch finishes. A generic lock marker can remain in `state`; it contains no source/job identifier. Crash remnants, paging, backups and host dumps are outside normal retention cleanup. See the exact [checkpoint contract](recovery-options.md).

The current source also provides `support-summary` for an already-sanitized export. It validates before printing and retains only versions, OS/architecture and aggregate fixed-category counts; it omits scoped IDs, times, source geometry and locators. Optional encoder names in recovery attempts are a closed enum, never driver output. [Operator-only iteration](operator-testing.md).

Migration now adds fixed filesystem failure reasons and aggregate reason counts to support summaries; worker limits distinguish candidate-size exhaustion from low output-disk space. Every nonzero FFmpeg worker exit without a more specific operational reason is labeled `ffmpeg_process_failed`, even when the backend emits no classifiable message. The default text log aggregates exit codes and classified message categories by stage, while retaining bounded grouped detail for affected files. It never records raw FFmpeg stderr or command lines. No exception text, paths, driver identifiers or errno messages are exported. Source/candidate/output byte sizes shown in local Activity and aggregate package status stay private and are excluded from both diagnostic exports and support summaries. Failed encoding candidates are removed after their worker exits in either retention mode; this is ordinary deletion, not secure erasure or cleanup of older state.

Encoding conveniences add only fixed disclosures: audio normalization applied/requested preset, size adjustment attempted, and finished size within/below/above target. No loudness measurements or exact byte sizes are exported. The number of repair attempts varies with qualified hardware routes, decoder fallback, partial salvage and at most one size-adjustment retry; the closed export schema bounds the recorded list at 80. Older schema readers may reject these additions; use the matching source reader. Optional normalization is off by default and changes the local audio, not the diagnostics boundary. Temporary size caps now default off, while disk/time/cancellation and full verification controls remain enabled.

Current source can retain up to eight path-free in-memory migration retry snapshots until the app closes. They contain a random matching key, keyed manifest/content tokens, authenticated sanitized reports and neutral output kinds, never source locators. They are private application state and are not shareable diagnostics or persisted restart history. Hardware summary exports add only closed route enums, job-scoped slot numbers and bounded concurrency counts. Updated readers are required for these new optional fields. See [completed jobs and retries](completed-jobs-and-retries.md).

## Owner's boundary

Source 0.8 adds migration packages. The owner explicitly permits preserved local filenames/folders for Sensitive migration only through a separate local-output option. Healthy videos and other files are copied byte for byte, including their existing embedded data. Unresolved videos default to exclusion from output with reported omissions; the operator may request unchanged copies in the package or a separate review folder. Sources remain untouched. These packages are private media, never diagnostic exports. Migration defaults to memory-only journals in both modes and no mappings. Optional Private resume adds a passphrase-keyed, path-free SQLite checkpoint with authenticated publication intents; technical data is not encrypted. See [interruption recovery](interruption-recovery.md). Its exported outcome is a closed object of input kind, action, copy check, timestamp outcome and fixed reason. Profiles contain processing settings only and never enter exports. [Workflow contract](migration-and-profiles.md).

Real media is highly sensitive. Development assistants must never read or inspect it, and must not obtain it indirectly through tools, logs, screenshots, previews, private databases or reference clips. The operator runs the finished program inside an approved local environment.

Installation and runtime must be fully offline. No telemetry, crash-upload SDK, analytics, automatic update check, online codec lookup, network listener, remote model, cloud repair, or automatic sharing is permitted.

The owner authorized automatic provisioning of missing public software at startup. The launcher can download checksum-pinned FFmpeg/FFprobe and Python/Tk; --offline prohibits downloads and accepts supplied or cached archives. Provisioning is separate from media runtime and never reads media. There are no automatic updates or uploads.

The approved debugging channel is an operator-generated sanitized diagnostic file. Exact playback-relative timestamps and technical codec details are allowed. This permission does not allow recording dates, location, filenames, raw text, or arbitrary embedded metadata.

"Proxy" here means a diagnostic stand-in for a file, not a network proxy. There is no media relay service.

## Data classes and destinations

| Data | Private operator environment | Shared export | Code repository / CI |
| --- | --- | --- | --- |
| Source, recovered output, reference clip, frames, audio | Required for operator processing | Never | Never |
| Paths, filenames, machine/user names, filesystem labels | Only where needed locally | Never | Never from real inputs |
| Embedded text, location, recording dates, chapters, attachments | Private; minimize collection | Never | Never from real inputs |
| Raw FFmpeg/FFprobe output | Bounded local memory only in v1 | Never | Synthetic parser fixtures only |
| Private state, ID mappings, input hashes, exact byte sizes | Private | Never | Never from real inputs |
| Passphrases/keys and future credential-store contents | Private memory today; protected provider planned | Never | Invented test keys only |
| Fixed error categories, coverage and recovery outcomes | Yes | Allowed | Invented examples only |
| Relative playback times and allowlisted codec properties | Yes | Allowed in detailed profile | Invented examples only |
| Keyed export-scoped identifiers | Yes | Allowed | Synthetic examples only |

A sanitized export is still potentially sensitive technical information. Pseudonymization does not guarantee anonymity: timestamps, media structure and codec properties can be distinctive. Export does not authorize publication or sharing by the application or assistant. The operator decides whether and where to share it.

## Keyed identifiers

Use the standard HMAC-SHA-256 construction, not an unkeyed filename hash and not a custom cryptographic primitive. The [Python HMAC documentation](https://docs.python.org/3/library/hmac.html) describes the standard library interface.

Current exports use the construction below with a fresh in-memory random secret for each export. Direct private mappings are off by default and can only be enabled for Sensitive: No. They do not retain a workspace secret or implement a credential vault. Export identifiers are unrelated to optional private-resume content IDs; content hashes never enter a shared export.

Proposed production construction:

1. Generate a random 256-bit installation/workspace secret `K` using the OS cryptographic random source inside the operator environment.
2. Assign each local input a random UUID stored only in the private database alongside its locator. This UUID represents an input record, not a content fingerprint.
3. For each export, generate a fresh 128-bit random nonce `N`.
4. Derive `K_export = HMAC-SHA256(K, ASCII("videomate/export/v1") || 0x00 || N)`.
5. Emit `file_ref = "f_" || hex(HMAC-SHA256(K_export, ASCII("file") || 0x00 || UUID_bytes))`.
6. Use the same derivation with domain `job` and a private job UUID for `job_ref`, prefixed `j_`.

Encoding is fixed: ASCII domains, one zero byte as separator, 16-byte binary UUIDs and nonce, lowercase full 64-character hexadecimal MAC. Export `N` as a 32-character hex `export_scope`. It does not itself resolve any reference; only an explicitly retained private mapping can link an export reference to a filename in the current implementation.

Properties:

- Repeated observations for the same input in one export share a reference.
- Fresh exports intentionally use different references, including for the same input.
- Neither filenames nor source bytes enter identifier generation. This avoids filename dictionary guessing and avoids requiring an additional read of a sensitive file merely to assign an ID.
- Same-content files at different locations are separate records. Renames are resolved locally by an explicit mapping operation or become new records; content deduplication is not inferred from IDs.
- IDs are pseudonyms, not encryption, file checksums, or signatures authenticating the export.
- Cross-export correlation is disabled in v1. If troubleshooting needs continuity, export the relevant related attempts together. Stable shared IDs would require a separate explicit feature decision.

## Optional persistent secret storage (future work)

Implement a credential-provider interface using platform-managed protection: Windows credential protection, macOS Keychain, and an approved Linux provider. Headless Linux may require an organization-provisioned provider. Do not silently fall back to a plaintext key file, hardcoded secret, environment variable, or command-line argument.

If the provider is unavailable, secret-dependent export is blocked with a fixed local error. Unavailable protection must not produce an unkeyed hash fallback. Development tests use clearly labelled synthetic keys that never represent a production secret.

The key must not be passed to FFmpeg, child processes, logs, reports, support bundles, public repositories or the assistant. Limit key lifetime in memory and avoid unnecessary copies; Python cannot promise perfect memory zeroization. Host memory, paging, crash dump and credential policy belong to the approved deployment controls.

Key rotation produces a new key generation; keep the old key only if the operator's retention policy requires resolving old exports. Lost keys/mappings make those references unresolvable; do not promise recovery. No key recovery or backup leaves the approved environment automatically.

## Structured diagnostics, not redacted logs

Do not export a log file after applying filename replacement. Logs can contain filenames in multiple encodings, metadata values, URLs, device strings, encoder configuration, or arbitrary strings supplied by damaged inputs.

Instead, construct a new object from a small set of typed facts and fixed enums. Validate the object against [the closed schema](../schemas/diagnostic-export-v1.schema.json). Use `additionalProperties: false` on every object; cap arrays, integers and string formats. Do not include a generic `message`, `details`, `context`, `exception`, `command`, `tags`, or `raw` field.

Apply an overall 16 MiB UTF-8 export limit in addition to the schema's per-field limits. Enforce budgets while constructing and reading the export, not only after allocating or serializing it. Reject duplicate JSON keys, excessive nesting and trailing material. Bundle the schema and validator offline; the `$schema` URI is an identifier, not permission to fetch it over the network.

Unknown codec/profile identifiers become `other` or `unknown`; unknown backend errors become `unclassified_error`. Never pass through an unrecognized string from the input. Software versions are normalized numeric release identifiers, not arbitrary build banners or build paths.

The detailed schema permits:

- Schema version, declared data origin, export scope and export-scoped job/file references.
- Normalized application/backend versions and enumerated OS/architecture.
- Scan depth, state, integrity, completeness, coverage and recovery outcome.
- Allowlisted container/codec/profile/pixel-format families and numeric technical properties.
- Stream ordinals, error categories/counts and optional exact relative media intervals.
- Fixed recovery strategy/profile, rate policy, per-attempt decoder/encoder, verification states and closed verification-failure reasons.
- Bounded CPU budget, runner count and hardware-decoding preference, with no device identifiers.
- Input/output playback duration and input/output intervals that were cut or filled, where known.

Times are signed integer microseconds relative to the media timeline, not calendar or recording time. Establish one local presentation origin shared by all streams of an input and subtract it before export; use a separate common origin for the output. Never normalize each stream independently, which would erase synchronization offsets. Keep these origins private. Raw timestamps may embed an absolute clock, so never copy them verbatim merely because FFprobe calls them PTS/DTS. If a safe relative origin cannot be established, export an unknown interval. Negative relative values can represent valid preroll. Do not export embedded SMPTE timecode, creation timestamps, filesystem times, GPS time or wall-clock run times. Duration can be unknown; represent it as `null`, not zero.

## Export sequence

1. A Sensitive: No job projects available results at completion/cancellation, or the operator explicitly requests a fresh diagnostic export. Sensitive: Yes jobs never export automatically.
2. Load only the typed private facts needed by the projection.
3. Resolve approved enum/numeric fields; derive fresh scoped references.
4. Validate the new object structurally and semantically. Reject unexpected fields, invalid interval ordering, incompatible states, excessive records or missing required facts.
5. Include only the allowed categories. There is no hidden attachment, thumbnail, raw log or private mapping. The current GUI does not provide a dedicated JSON preview; operator review is performed locally on the saved export.
6. Render the validated facts into one plain-text log in the configured diagnostics directory using a generated neutral filename. JSON batches are optional for technical tools; no raw logs are redacted into this export.
7. The operator chooses whether to transfer it. The application has no upload path.

For large jobs, explicitly select a bounded subset or split exports into bounded independently scoped files. Do not silently truncate diagnostic findings; record omission counts and mark coverage appropriately.

Session-only migration implements automatic splitting: each document contains up to 1,000 input records under the 16 MiB construction/encoding limits. Dense batches split further, with all input records accounted for across the resulting documents. Each page has its own export scope and no mapping or cross-page identifier manifest. These per-document limits do not cap the migration's file count. The session retains sanitized pages in memory until exit or report eviction; a large collection requires proportionally more memory.

No export can prove it contains no secrets merely by matching a schema. Construction from trusted typed values, strict normalization, adversarial privacy tests, and operator review are all required. Fixed-format fields could still be abused by a faulty or malicious producer.

Semantic validation must additionally check unique file references and stream ordinals, interval start/end ordering, matching frame-rate numerator/denominator, codec/stream compatibility, findings referring to existing or explicitly omitted streams, and recovery/verification consistency. A `no_errors_detected` file result requires a completed full inspection of intended audio/video streams. A quick or focused pass cannot produce that file-wide conclusion. `verified` and `verified_with_losses` require successful required output checks; an inconclusive required check yields `verification_inconclusive`. Omitted export records do not retroactively change actual scan coverage, but must be disclosed.

An assistant may read only an already-sanitized export deliberately supplied by the operator. It must never read private input in order to perform sanitization in the conversation.

## Local observability

Optional basic disk logs use only fixed event codes, bounded sequence/input counters and random neutral filenames. Basic logging is disabled for Sensitive: Yes. The separate Additional diagnostics opt-in enables detailed safe disk logging in either mode. Its records contain closed worker stages, approved decoder/encoder names, bounded exit codes, relative elapsed milliseconds, thread allocation, limit reasons and fixed error categories/counts. No raw backend/application text, locators, metadata, command lines or device names are written. Each detail is validated before writing. Activity logs use plain text, aggregate routine successes, record the first three occurrences of a worker pattern per bounded window, and count later repeats. Progress is emitted every 1,000 completions and on close. Four rotating segments of 4 MiB retain recent detail and cumulative counts; older detail may be replaced, explicitly marked in segment headers. They no longer stop at 5,000 records. Diagnostic exports carry at most 1,024 worker records per input and an explicit omission count, under the existing total size limit. These optional fields extend schema version 1; older readers may reject a newer export and should be upgraded, never bypass validation. The private job store may retain essential private locators and technical facts, but not a raw stderr archive.

Local operator reports can resolve identifiers and display detailed findings. They are confidential and distinct from the export. Never open such a report in a connected assistant browser or upload it as an attachment.

Disable application crash uploads. Exceptions must be rendered through a safe handler that does not include private variable values or command lines. OS crash dumps, shell history, terminal scrollback, process listings and enterprise monitoring may expose local paths or memory; application redaction cannot control a privileged host observer. Deployment policy must address these surfaces.

## Threat model and required controls

| Failure or threat | Design response | Remaining limit |
| --- | --- | --- |
| A raw backend line leaks metadata | Memory-only capture, typed classification, no raw forwarding/export | Parser correctness requires adversarial tests |
| Predictable filenames are guessed from hashes | HMAC over opaque private UUIDs with a secret and fresh export scope | Exported technical facts can still correlate |
| Media triggers external network/local references | Constrained input set, protocol restriction, worker filesystem and network containment | Backend bugs require OS controls and maintained builds |
| A corrupted stream exhausts resources | Budgets, bounded parsers, cancellable workers, attempt limits | Filesystem/OS enforcement varies by platform |
| A candidate overwrites the original | Unique destinations, alias checks, transactional job ownership and no-overwrite publication | Requires concurrent/race-condition testing |
| Runtime data enters cloud sync or Git | Explicit approved runtime roots outside code/sync, private permissions, Git ignores as a secondary guard | Unknown sync agents require organization policy |
| A crash exposes memory or arguments | Safe app handlers, no uploads, protected host dump/paging policy | Privileged or compromised hosts are outside app guarantees |
| An update introduces unexpected code | Locked offline bundles, checksum manifests today; authenticated manifests and controlled updates required for production | Trusted build and verification-key provisioning are necessary |

No compliance certification, accreditation, or guarantee against a compromised host is asserted. The design is intended to make the stated confidentiality requirements concrete and testable.

## Fixed privacy invariants

1. The development assistant sees synthetic inputs and intentionally supplied sanitized diagnostics only.
2. Originals are never modified by inspection or recovery.
3. Runtime needs no network, and export never transmits data.
4. No arbitrary input-derived text enters a shared export.
5. Keys and filename mappings remain exclusively within the approved operator environment.
6. A failed check cannot enable a less-private fallback.
7. New data fields require a documented privacy decision and schema revision before use.

## Fixed error catalog alignment

The 0.8.0 local checkpoint adds the existing fixed migration preflight, settings-location and worker-shutdown reason codes to the diagnostic schema error enum. These carry no names, locators or arbitrary text. Every approved application error is exercised through closed export validation; unknown text remains rejected.

## Readable reports and migration context (source 0.8.3)

Explicit diagnostic export now writes one plain-text `.log` from closed-schema validated technical facts. It includes the original stop stage/reason, secondary failures, worker stages/exit codes, decoder/encoder/thread choices, elapsed timing ranges, findings, repair attempts, verification failures and permitted relative playback intervals. Successful copies are summarized; identical detailed patterns are grouped across at most 128 distinct patterns per window, then flushed without dropping later patterns. Sanitized temporary text is held in an automatically closed temporary file while assembling the log; this never contains source locators or raw worker output. No HTML or browser is involved.

The default export writes no JSON batches. CLI `export-diagnostics --technical-json` additionally writes bounded, independently scoped JSON for schema validation/support-summary or individual record analysis. Explicit non-sensitive mapping opt-in also retains its matching JSON document; mappings themselves remain private and outside the export directory. The text log uses neutral record ordinals, not file references or mappings. It summarizes repeated records rather than providing a reversible per-input index. Sensitive jobs still require an explicit export request or prior export-on-completion opt-in. Additional diagnostics independently authorizes safe activity logging, not automatic diagnostic export.

Every migration batch can include a closed migration_summary object: package state, planned/processed/published/excluded/failed/unprocessed file counts, stop stage/reason and at most 32 typed secondary pipeline issues. No byte sizes, device identities or absolute times are added. A zero-file batch is allowed only with a whole-job summary, so preparation failures remain diagnosable. Counts have semantic consistency checks. Use the updated reader/schema for these additions; older readers may reject them. A batch is never silently described as the complete job.

If a storage loss prevents status writes or cleanup, the original processing failure retains priority (except unconfirmed live-worker shutdown), secondary errors are reported separately, and memory-only reports are retained for explicit export while the application stays open. No automatic source deletion or OS device reconnection is performed. Application-level reconnect recovery and optional interrupted-package resume now follow the [interruption contract](interruption-recovery.md).
