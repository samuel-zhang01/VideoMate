# Architecture — implemented source 0.8

Standard-library Python orchestrates separately launched FFmpeg/FFprobe workers. Tk provides the desktop interface; CLI and GUI call the same inspection, recovery and job services. There is no web server or runtime network client.

| Area | Responsibility |
| --- | --- |
| CLI and GUI | User flow, sensitive treatment, safe messages, cancellation |
| Dependencies and local setup | Locate/hash tools, check executable health/encoders, prepare workspace |
| Inspection and backend parsers | Bounded technical facts, per-stream decoding, conservative classification |
| Recovery, profiles and verification | Plan attempts, encode candidates, compare properties/timing, publish exclusively |
| Jobs, private state and checkpoint | Memory-only or persistent SQLite journals, locks, keyed path-free resume and session reports |
| Encoding and output layout | Rate budgets, non-sensitive naming/folder choices and collision handling |
| Migration | Whole-tree preflight, verified copies, existing repair engine, pre-run unresolved-file policy and adjacent completion/omission status |
| Profiles | Validated processing-only presets; no locators, secrets or privacy permissions |
| Cleanup and discovery | Bounded selection, excluded review folders, separately confirmed manual actions |
| Runner and policy | Process limits/lifecycle, protocol restrictions, local path rules |
| Export and schema | Closed diagnostic objects with keyed opaque IDs |
| Bootstrap and installers | Explicit public-software setup, separate from media runtime |

## Data flow

Selected local input → probe/decode → typed private findings → recovery plan → separate candidate → independent decode/property/timing verification → exclusive publication. Recovery never rewrites originals. Locators/results/output hashes stay in private memory or explicitly retained job storage. A separate projection builds sanitized JSON; raw backend logs are never forwarded. Decode/encode stderr is classified incrementally into bounded counts, with only the last progress counters retained. Probe JSON and tool listings retain raw-capture limits.

Workers use argument arrays, bounded captures, timeout/size budgets, Windows Job Objects or POSIX process groups. Those controls manage lifecycle/resources, not filesystem/network security isolation. Windows assignment occurs after launch. Explicitly selected local files can be processed with Sensitive: Yes/No; neither setting is an OS sandbox.

Windows shutdown explicitly terminates the assigned job and polls its active-process count for up to five seconds before closing the handle; a failed query or timeout raises a fixed error. The implementation follows Microsoft's [job termination](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject) and [job accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information) APIs. On POSIX, a process-group permission denial is tolerated only if the worker has already exited. These checks prevent successful completion from being reported after unconfirmed shutdown; they do not add an OS sandbox.

## Storage and restart

Runtime workspaces live outside software/cloud sync. New Sensitive jobs use SQLite in memory and exclusively owned session scratch/candidate directories, removed at normal shutdown/cancellation. Optional Sensitive history or non-sensitive jobs use persistent journals. The publication adapter uses same-filesystem exclusive rename on Windows and hard links on POSIX, refusing collisions. Migration preflights publication with owned markers before source-byte inspection. Failed encodes remove their exact candidate after worker exit. Ordinary resume checks fingerprints/output hashes; private resume authenticates keyed whole-file identifiers after operator reselection, checks policy/version and output hashes, and reuses only complete work. A crash can leave an orphan; filesystem/database atomicity and secure erasure are not claimed.

Migration uses bounded file workers with separate scratch directories, one shared CPU budget and configurable combined GPU admission. Generated qualification checks combined decoder/encoder routes, retaining GPU encoding with software decoding when the pair fails. Optional synthetic calibration measures one/two concurrent verified encodes per route and stores a bundle-bound, expiring ranking in local preferences. Migration re-qualifies routes and uses that ranking to assign initial lanes and bounded per-route gates; a verified real output can still change a lane's first choice. Authoritative integrity inspection and candidate verification use software decoding because hardware error concealment can hide packet damage. NVIDIA NVENC indices are explicitly qualified; AMD, Intel and Apple APIs currently use their default adapter. One copy semaphore prevents competing verified copies, while independent video processing overlaps. Journals, counters, event callbacks and UI updates remain on the coordinator. Cancellation drains completed results and joins workers before session cleanup. Status writes are throttled. Output hashes used solely for restartable Repair are omitted for session-only migration; copy hashing and independent full repair verification remain enforced.

Exports use fresh in-memory HMAC keys. Direct mappings are only available by non-sensitive opt-in. A separate salted passphrase-derived key authenticates private checkpoints and content IDs; it is never saved. Checkpoints are not encrypted or shared exports. Minimal-retention jobs retain up to eight sanitized reports in process memory for explicit export. Persistent platform vaults and encrypted-at-rest storage are unimplemented. GUI aliases hide queued Sensitive filenames. Path rules cannot identify every unknown sync agent or hostile host policy. [Privacy requirements](privacy-and-diagnostics.md).

## Configuration

Preferences are validated local JSON with no selected-input history. The GUI loads its chosen settings file; the CLI accepts --config and explicit overrides. Workspace, recovered output, diagnostics, event logs and tools are configurable. Jobs persist their storage/privacy choices; candidates stay on the output filesystem for exclusive publication. Event logs contain only fixed codes and input counters. [Settings contract](settings-and-privacy.md).

## Distribution

Python 3.11+ code is portable. Native tool and optional Python/Tk catalogs cover Windows x64, Apple Silicon, Linux x64 and Linux ARM64. Launchers prepare missing pinned public dependencies automatically unless --offline is set. No-Python bootstrap uses platform shell tools to download and hash-check the exact runtime archive before execution; Python then performs controlled installation. Runtime media services contain no network provisioning logic. Complete desktop/runtime kits remain fully offline.

Windows/Mac desktop builds use native PyInstaller, bundle software/licenses and test both the frozen app and extracted ZIP. Python kits can be assembled for foreign platforms without executing their binaries; this proves packaging only. Linux x64 uses a runtime-inclusive Python kit. Signing, authenticated distribution and full license/source delivery remain release work.

Responsive Tk surfaces wrap text and action rows, switch sidebar navigation to a compact top bar, and scroll all pages. Focused controls are revealed automatically. Initial window bounds respect the screen. Windows declares system DPI awareness before creating the root; mixed-DPI monitor transitions are not qualified.
