# VideoMate app improvement audit and execution plan

Audit date: 4 October 2026. Scope: the 0.8.4 source application, its offline launchers and its documented deployment boundaries. This is a development audit, not release qualification. No operator media, settings, workspaces, checkpoints or sessions are evidence for this review.

The ten scoped rounds below are implemented and have passed their focused checks. They improve first-use guidance, settings organization, correction messages, compact layouts and motion preferences, and fix concrete cancellation, persistence, offline-startup and shutdown defects. The app remains a development release candidate. Its main remaining weaknesses are accessibility qualification, long-job measurement and distribution readiness.

The priority is a clear, controllable first experience: choose a task, understand privacy, select inputs, configure output and run a verified operation. The service layer has substantial preservation and diagnostic safeguards. The audit found avoidable interface friction and storage/setup failures that appearance changes alone would not address. These rounds combine usability work with repairs to those failures before considering a larger interface rewrite.

## Review method

Three independent adversarial reviewers examine usability, safety and platform behavior. Scores are judgments on a ten-point rubric: 1–3 means a core task is blocked or dangerous; 4–5 means substantial friction or an unresolved defect; 6–7 means a usable implementation with material gaps; 8 means focused verification and clear limitations; 9 requires wider native/accessibility validation; 10 requires sustained representative evidence. Ten rounds do not imply a score of ten.

Evidence levels remain separate: source review, generated-fixture checks, dedicated native GUI checks, and release qualification. A skipped GUI check does not establish visual quality. Existing historical platform checks do not qualify this changed source or a newly distributed binary.

## Adversarial grades

These are engineering judgments from the independent usability, safety and platform reviewers. They are not measurements of user satisfaction, penetration-test results or certifications. The after scores credit source fixes and executed focused checks. Native evidence from this pass is limited to macOS and generated application state; wider accessibility, backend performance and distribution claims remain open.

| Aspect | Before | After | Evidence and reason for the remaining gap |
| --- | --- | --- | --- |
| Functionality and recovery | 7 | 7 | Inspect, Repair, Migrate, profiles and continuation exist. Generated/stub journey checks preserve task routing; actual backend recovery was not requalified in this pass. |
| Fresh-user guidance | 5.5 | 6.5 | Task explanations, empty-state instructions and default-format consequences are clearer. Independent first-time user comprehension has not been measured. |
| Information hierarchy | 5.5 | 6.5 | Five Settings sections replace one long form. Advanced recovery and results still contain substantial technical detail. |
| Visual consistency | 6 | 6.5 | Shared colors, spacing, selected sections and focus were reviewed in a dedicated generated window. The idle bar no longer implies running work. The existing Tk visual language remains; this is not a full visual redesign. |
| Motion and feedback | 4 | 7 | Optimizer Stop, honest terminal states, reduced motion and protection against stale Stop messages are verified. Additional animation is intentionally deferred until it explains a real state change. |
| Settings and configuration | 5.5 | 7.5 | Fixed field guidance, correct page/focus, save state and undo are verified. Profile portability and clearer active-versus-resumed-job explanations remain follow-up work. |
| Settings persistence robustness | 6 | 8 | Larger valid preferences round-trip; oversized writes preserve prior state; malformed calibration values fail safely. Filesystem races and durability across power loss are not newly qualified. |
| Language and terminology | 5 | 6.5 | Conditional codec explanations and task consequences are clearer. Advanced controls still expose technical enums and acronyms; localization is not implemented. |
| Responsiveness and small displays | 6 | 7 | Threaded work, cancellation and the focused viewport matrix pass. Settings preparation still performs synchronous filesystem work; long-job latency and memory require measurement. |
| Keyboard and accessibility readiness | 4 | 6 | Native Tab/Shift-Tab, focus reveal, compact controls and keyboard saving were checked. Tk did not expose individual controls in the Mac accessibility tree; screen-reader and high-contrast behavior remain unqualified. |
| Privacy communication | 7 | 7.5 | Compact layouts retain export/logging disclosures, with Sensitive enabled by default. Local paths and media are not encrypted, and filename masking is not OS isolation. |
| Privacy and export architecture | 8 | 8 | The closed diagnostics boundary remains intact. No export vocabulary or network-processing behavior was widened by this pass. Production containment still requires separate qualification. |
| Offline launch | 6 | 8 | Custom bundles, stale-tool correction and metadata/help dispatch are verified without fallback installation. Clean-machine packaged installation remains a release gate. |
| Cross-platform compatibility | 6 | 6 | Adapters and platform build paths exist; Linux XDG defaults are corrected. Windows/Linux native execution of this changed source was not performed. |
| Settings portability | 5 | 5 | Full settings retain host-specific paths; processing profiles remain local. A path-free processing-profile transfer format is proposed below. |
| Deployability | 4 | 4 | Signing, clean-machine qualification, native Windows/Linux ARM64 execution and complete public-distribution materials remain substantive gates. |
| Production containment | 5 | 5 | Path heuristics, bounded workers and closed exports do not establish OS filesystem/network isolation or encrypted storage. |

There is no overall average: a stronger visual or settings score cannot compensate for an unresolved release or accessibility gate.

## Execution rounds

| Round | Problem and work | Acceptance evidence | Status |
| --- | --- | --- | --- |
| 1 | Enable optimizer Stop/progress, wait for worker exit, and make cancellation win over an already-queued success. | Native stub-worker cancellation and every terminal state pass; the exact late-Stop race has portable and native coverage. | Complete |
| 2 | Lock preset-forced radio and combobox values, then reapply locks after jobs, previews and optimization. | Selective HEVC codec, rate and loudness stay locked; deselection restores editability. | Complete |
| 3 | Add shared bounded field guidance and reveal the actual control, including hidden advanced Options during Inspect. | Numeric endpoints, malformed values, path guidance and HEVC conflict pass; entered values never appear in the correction. Native page/focus checks pass. | Complete |
| 4 | Use a 256 KiB read/write preference bound checked before replacement; reject extreme calibration numbers safely. | A valid configuration above the former 32 KiB limit round-trips. Unicode-expanded oversized saves preserve prior bytes; legacy settings still load. | Complete |
| 5 | Resolve custom tools before provisioning; keep metadata/help/doctor independent of FFmpeg; keep stale custom tools editable; honor Linux XDG defaults. | Twenty-one focused launcher checks and four environment-only default-path checks pass. No fallback download is allowed for a selected custom bundle. | Complete |
| 6 | Group Storage, Privacy, Performance, Application and Display; show unsaved edits and provide save, undo and session reset. | Save/reset/undo preserves selections and saved profiles. Calibration participates in dirty state. Native section, Tab/Shift-Tab and focus-reveal checks pass. | Complete |
| 7 | Explain Inspect, Repair and Migrate before selection; use task-specific empty states and disclose lossless default output size. | Native generated/stub journeys exercise task routing, output selection and migration preview without creating output or granting filename permission. | Complete |
| 8 | Keep compact privacy disclosures, wrap footer actions and retain visible keyboard focus. | 800×600, 1024×768 and 1440×900 at 100%, 150% and 200% Tk text scales pass. Every Settings section is separately checked at 800×600/200%. | Complete |
| 9 | Add persistent reduced motion, conditional conversion help and consistent section/action treatment; remove the misleading busy segment while idle. | Motion preference round-trips and preserves progress meaning. Start, Storage and Display were observed in the generated-only window; keyboard edit/save and the corrected empty idle bar are visible. | Complete |
| 10 | Support bounded saved layout maps, reject repository roots as storage, and preserve unconfirmed-worker failure despite secondary logging errors. Recheck the resulting integrations. | A 1,000-entry layout representation persists/reloads/updates; oversized writes preserve state. Generated root-storage and shutdown-failure regressions pass. Final independent review found no new blocking defect in these changes. | Complete |

Each round follows finding → narrow implementation → focused verification → adversarial review. Privacy and recovery checks take precedence over decoration. Broad suites, full platform builds, Actions, release publication and system configuration remain outside this pass.

The rounds are ten scoped audit-and-improvement cycles, not ten independent complete visual redesigns. They were implemented in parallel where files were independent, then reviewed together. Follow-up adversarial findings produced additional corrections: cancelled optimizer results cannot be saved, completed jobs cannot unlock forced preset fields, reset cannot silently lose a calibration ranking, stale worker messages cannot erase Stop acknowledgement, logging errors cannot hide an unconfirmed worker shutdown, and Ready no longer displays a busy progress segment.

## Evidence and verification limits

| Executed check group | Result | What it establishes |
| --- | --- | --- |
| [Native GUI audit checks](../../tests/test_gui_audit.py), [fresh-user journeys](../../tests/test_gui_journeys.py), and three selected [layout checks](../../tests/test_gui_layout.py) | 14 passed, no skips, in the final combined run | Native Tk behavior, task/service routing with stubs, settings/validation, motion, keyboard navigation and the declared viewport matrix. |
| [Portable controller checks](../../tests/test_gui_controller.py) and [fixed correction guidance](../../tests/test_gui_validation.py) | 12 passed | Controller transitions, exact queued-success cancellation, stale Stop messages, preset locks, undo and closed correction messages. These do not establish painting or accessibility semantics. |
| Preferences/sensitivity, calibration and three selected saved-job persistence checks | 21 passed | Read/write bounds, malformed-value rejection and ordinary settings compatibility. |
| Selected storage/workspace checks | 6 passed | Generated repository markers, cloud-path heuristics and valid workspace preparation. This group overlaps the preference group. |
| Selected shutdown/scheduler checks | 15 passed | Logging-failure injection preserves the critical worker-stop failure and blocks the next coordinator; scheduling checks remain intact. |
| Launcher checks and platform-default checks | 21 and 4 passed | Offline dispatch/selection behavior and XDG default handling, with generated settings, mocks and guarded environment-only checks. |
| Source import, syntax and whitespace checks | Passed | Changed Python sources parse/import and the diff has no whitespace errors. |

Counts from overlapping runs are not summed into a fabricated full-suite total. No broad suite, media backend qualification, product platform rebuild or hosted Actions run was performed in this pass.

The owner approved downloading the repository's checksum-pinned CPython 3.13.15/Tk runtime into an isolated nonsynced temporary lab. Native checks used that runtime and exact generated settings/selections; processing services and file pickers were stubbed where appropriate. A temporary native host made the same generated-only interface available to Computer Use. Observed keyboard navigation, reduced-motion editing and Command-S saving worked. Individual Tk controls were absent from the Mac accessibility tree, so screen-reader usability cannot be inferred from keyboard success. No test-host wrapper, media, settings file or screenshot is included in the repository.

One early test-harness attempt destroyed and recreated a root inside a single test and exited with a native fault. That harness was corrected to set text scale before constructing its isolated Application; the final combined native run passed. The fault was not treated as evidence of a production rendering failure or a qualified root-recreation lifecycle. An initially blank test-host capture rendered after the dedicated window received focus; the observed screenshots then supported the limited appearance review above. The final idle-bar/correction-routing follow-up passed all seven controller checks and two targeted native checks; this nine-check run overlaps the groups above.

The 1,000-entry persistence check exercises the layout representation, using a generated marker input. It is not a 1,000-video processing or throughput test. Native scaling changes are Tk test settings, not changes to the operator's display or proof of mixed-DPI monitor compatibility.

## Fresh user journeys

1. A cautious first-time user starts with Sensitive enabled, sees what it does and what it does not do, chooses Inspect, and understands that inspection creates no recovered copy.
2. A user repairing a few videos chooses Repair, retains defaults or a named profile, sees the output location and knows that originals remain untouched and results require verification.
3. A user migrating a folder sees empty-destination requirements, unresolved-file policy and session/restart recovery choices before starting. Local filename permission remains separate from diagnostic privacy.
4. An offline user with an approved bundle selects it without a redundant download. Metadata and help commands remain available when media tools are absent.
5. A keyboard user on a small display can reach settings, see validation guidance and stop long work without needing a pointer or scrolling to a hidden control.

## Follow up work and release gates

After this pass, plan a separately authorized native checkpoint: keyboard and screen-reader behavior, real display scaling, Windows/macOS/Linux clean installs, offline first launch, large generated queues, interrupted generated jobs, and signed package verification. Representative operator experience can be assessed only from deliberately supplied sanitized feedback; assistants must never join operator sessions.

The next slices below address remaining measured or source-confirmed gaps. Completing this audit does not authorize publishing a release, rebuilding all platforms or inspecting operator sessions.

## Implementation alternatives and decision

Keep the current Tk interface for this improvement cycle and retain the shared Python inspection, recovery, migration and diagnostic services. A new toolkit would not resolve verification, interruption recovery or distribution qualification by itself. The immediate goal is a predictable first experience, with clear task choices, editable settings, useful progress and accessible controls. A replacement should earn its migration cost by improving measured user tasks.

The comparison below is an architectural recommendation based on the current [service boundaries](../architecture.md) and the official toolkit documentation. It is not evidence that another implementation has been built, benchmarked or qualified.

| Approach | Goal and fit | Cost and tradeoffs | Decision for VideoMate |
| --- | --- | --- | --- |
| Current Tk/ttk | Improve the existing offline native application while reusing its Python services, launchers and packaging. | The application must manage layout, styling, asynchronous work and focus carefully. Tk uses an event loop; long event handlers block interaction. Rich visual transitions require additional application work. | Preferred for the current rounds. Improve task flow and responsiveness before considering a rewrite. |
| PySide6 with Qt Widgets or Qt Quick/QML | Explore a richer native interface while retaining the Python processing engine. Widgets suit conventional forms; Qt Quick provides visual models, animation and transitions. | Adds toolkit dependencies, packaging and license inventory, plus a new view/controller integration. Accessibility and platform appearance still need actual checks. | First replacement candidate if a small prototype demonstrates a meaningful advantage over improved Tk. |
| Tauri with bundled web assets and a Python sidecar | Explore CSS-based layout and interaction with a native desktop shell. | Adds Rust/JavaScript and a typed IPC boundary. Each sidecar architecture must be packaged; system WebView availability and behavior become deployment dependencies. Capability configuration does not isolate arbitrary backend code or FFmpeg. | A later candidate when the desired interaction demonstrably warrants the extra runtime and security surfaces. |
| Local browser with a localhost backend | Reuse browser layout and rendering for the application interface. | A listening server conflicts with the current no-listener contract. Authentication, process lifetime, browser state and local endpoint access become additional concerns. A static page alone cannot replace the existing worker orchestration. | Not part of the present plan. Requires a separate architecture/privacy decision before implementation. |

Tk's event-loop constraints are described in the [Python Tkinter threading model](https://docs.python.org/3/library/tkinter.html#threading-model). Qt provides official [Python bindings](https://doc.qt.io/qtforpython-6/), and [Qt Quick](https://doc.qt.io/qt-6/qtquick-index.html) explicitly supports visual components, models, animation and transitions. These capabilities motivate a prototype; they do not establish better usability for this application.

Tauri uses the [system WebView](https://v2.tauri.app/start/), supports [external sidecar binaries for each target architecture](https://v2.tauri.app/develop/sidecar/), and exposes backend functionality through [capabilities with explicit security limits](https://v2.tauri.app/security/capabilities/). A VideoMate prototype would bundle all fonts, scripts, images and documentation; expose only narrow, typed commands; disable remote content and navigation; and use IPC without a network listener. The Python engine would continue launching FFmpeg through argument arrays. No toolkit change may add telemetry, media upload, automatic updates or runtime dependency downloads.

### Prototype scope and comparison criteria

A prototype should implement one vertical slice: a fresh generated configuration, task selection, output configuration, a generated batch, Stop, continuation, results and settings persistence. Use the same service API and generated scenario in every toolkit. Keep it isolated from the operator application and default settings. Do not rebuild the recovery engine merely to compare presentation layers.

| Criterion | Proposed acceptance target | Evidence to retain |
| --- | --- | --- |
| First use | A new evaluator can distinguish Inspect, Repair and Migrate and explain where outputs go without reading a separate manual. | A generated-data task script, observed errors and an identifier-free summary of confusing labels. |
| Interaction | Target visible acknowledgement within 200 ms for navigation, validation and Stop on declared reference hardware. Long worker shutdown remains a separate bounded operation. | Measured event-loop delays and the exact source/package revision; report percentiles and exceptions rather than a single favorable sample. |
| Small screens | Complete the task at 800×600, 1024×768 and 1440×900 with 100%, 150% and 200% text scaling. No unreachable primary action, hidden privacy choice or clipped correction message. | Dedicated generated-settings viewport checks plus physical-display review at the native checkpoint. |
| Keyboard and assistive technology | Every required control is reachable; focus remains visible and follows validation; status meaning is available without relying on color or motion. | Native keyboard and screen-reader observations on each supported platform. Widget existence alone is insufficient. |
| Long jobs | Navigation, Stop and progress remain usable with a large generated queue; event delivery and displayed history stay bounded. | A defined generated queue size, peak memory, event-loop delay, completion counts and cancellation outcome. |
| Recovery | A stopped generated migration can continue under the existing policy; unavailable tools and invalid settings remain correctable. | Verification of retained publications, rejected unsafe reuse and the route back to Settings. |
| Offline/privacy | First launch and processing use only supplied software and local assets; exports retain their closed schema; no listener or unexpected persistence appears. | Focused network-boundary/source checks, generated export validation and an inventory of newly created test-owned state. |
| Deployment | Record startup time, package size, memory use, offline prerequisites and license inventory for the same native target. | Actual prototype artifacts and measurements, clearly separated from production release qualification. |

These targets are goals, not measurements from this pass. Choose a replacement only after it meets all preservation/privacy gates, has no unresolved core-task regression and improves the agreed usability measures enough to justify maintaining a second interface during migration. A more animated screenshot is insufficient evidence.

### Motion and loading design

Use motion to explain state changes: a brief control acknowledgement, a quiet busy indicator while tools are checked, and a stable transition from queued to running to verified or needing review. Show determinate progress only when a meaningful total exists. For unknown work, pair an indeterminate indicator with the current stage and keep Stop accessible. A skeleton is useful only while actual information is pending; it should not conceal an error, imply a successful scan or suggest progress that the engine has not reported.

Reduced motion must preserve every status and action while removing continuous or decorative animation. Avoid shimmering across dense settings forms, auto-scrolling away from the user's reading position, and success effects before independent verification completes. Establish typography, spacing, field alignment, focus styling and error placement before adding further animation.

## Platform findings: confirmed changes and remaining unknowns

The following launch defects were confirmed from source and focused generated/mocked checks, then corrected during round 5:

| Confirmed defect | Corrected behavior | Evidence |
| --- | --- | --- |
| Source launch prepared the default FFmpeg bundle before respecting custom settings or CLI tool selection. | Resolve the selected bundle first and verify it directly. Never install a fallback for an unavailable custom bundle. | [Bootstrap](../../tools/bootstrap.py), [launcher checks](../../tests/test_launchers.py). |
| Metadata commands, doctor and command help unnecessarily depended on backend provisioning. | Dispatch these commands without a backend prerequisite. Explicit runtime setup remains available. | The focused launcher file passed 21 tests. Command execution is mocked where it could access selected files. |
| A stale custom tool location could prevent the GUI from opening Settings. | Keep Settings reachable; the GUI independently checks readiness and leaves processing disabled. CLI and explicit checks still fail closed. | Generated configuration cases cover GUI recovery, CLI failure and check failure. |
| Linux ignored `XDG_STATE_HOME` and treated empty/relative `XDG_CONFIG_HOME` as a usable default. | Honor absolute XDG values; use home defaults for empty or relative values. Existing saved workspace paths are unchanged. | [Default-path checks](../../tests/test_platform_defaults.py): four tests passed with filesystem reads guarded. This follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/). |

These checks establish dispatch, configuration and path-selection behavior. They do not establish a clean Windows/Linux install, a screen-reader experience, signed distribution or a new performance result. Historical evidence and exact platform limits remain in [implementation status](../implementation-status.md), [desktop packaging](../desktop.md) and the [Mac validation record](validation.md).

The remaining items below are recommendations or unqualified areas, not newly confirmed defects. Windows publisher signing, macOS Developer ID/notarization, clean-machine execution, native Windows/Linux ARM64 execution and complete public-distribution materials remain open release gates. The current documented Mac development package is ad hoc signed and Gatekeeper rejected it; this audit does not change that status.

## Prioritized execution backlog after these rounds

Complete each slice with finding, implementation, focused evidence and independent review. Keep the original-preservation, independent-verification and closed-diagnostics rules as acceptance conditions throughout. Broad suites and native rebuilds belong to a separately agreed checkpoint; Actions remains disabled, and no runner service is installed by this plan.

| Priority and slice | Concrete next work | Completion gate |
| --- | --- | --- |
| P0: wider native interaction checkpoint | Extend the completed Mac source/stub checks to actual generated backend work, Windows/Linux and packaged entry points. Include invalid settings, stale tools and a stopped migration. | Every primary action has a visible result; Stop remains reachable; stale worker events cannot restore an obsolete readiness or success state. Record actual native evidence and every skip. |
| P0: release boundary | Reconcile package version, release notes, compatibility claims and qualification evidence for the exact revision intended for distribution. | Each downloadable artifact maps to its source revision, checksums and completed platform gates. No development-only artifact is described as generally qualified. |
| P1: portable processing profiles | Add an explicit versioned import/export format for processing-only profiles. Exclude storage paths, selected inputs, hardware calibration, secrets and privacy permissions. Preview changes before applying; leave machine limits local unless deliberately selected. | Generated round trips; unknown fields and oversized documents rejected; importing cannot enable retained history, mappings or local-name consent. The settings file is not advertised as a portable profile. |
| P1: settings safety and clarity | Build on the completed sections, save/undo/reset and dirty-state work. Distinguish the global Start action from Save on Settings and explain active-versus-resumed-job policy. Apply field guidance consistently to remaining unusual invalid enum/profile cases. | Fresh-user tasks can change output, privacy and performance settings without unintentionally changing another category; rejected saves preserve prior configuration. |
| P1: failure priority | Protect ordinary scan/repair processing and cancellation errors from secondary reporting/storage errors, extending the completed unconfirmed-worker safeguard. Retain secondary failures as closed categories rather than raw text. | Generated fault injection preserves the primary reason, stops/joins workers and reports safe secondary categories without changing export privacy. |
| P1: accessibility and display | Qualify focus order, assistive labels, contrast, reduced motion, keyboard-only dialogs and mixed-DPI monitor changes. Correct platform-specific differences behind adapters or presentation helpers. | Native evidence for each supported OS, including error states and compact layouts. A simulated Tk scale test is recorded separately from physical monitor behavior. |
| P1: language and terminology | Consolidate recurring task, stage, result and error labels. Use plain language first and disclose technical detail progressively. Prepare an offline string catalog before adding languages; do not translate fixed diagnostic enums. | A terminology review finds one meaning per visible label; longer translated strings fit; no raw exception text or private value is introduced into guidance. |
| P1: long-job responsiveness | Measure bounded queue rendering, progress/event backlog, settings responsiveness and Stop acknowledgement under large generated workloads. Separate filesystem preparation from the UI event loop where measurements identify blocking work. | Declared fixture sizes and reference machines, measured UI latency and memory, complete counts, preserved sources and bounded worker shutdown. No timing claim based on mocks alone. |
| P1: first-install recovery | Exercise source and packaged entry points with absent, damaged and supplied tools; unwritable generated locations; no Tk/display; spaces/Unicode; stale custom settings; and an offline environment. | Every failure gives a safe corrective route. Missing tools never silently select a different custom bundle, replace existing software or trigger media processing. |
| P2: toolkit pilot | Build the limited Qt prototype only if the improved Tk interaction still misses agreed usability goals; evaluate Tauri only if a web presentation brings a specific demonstrated benefit. | The comparison criteria above are met, migration cost is documented, and no privacy/recovery behavior is weakened. |
| P2: maintainability | Extract view state, validation, settings sections and job-control coordination behind explicit interfaces as those areas change. Keep one authoritative policy and settings model. | Focused checks demonstrate the same behavior through GUI and CLI; refactoring does not duplicate verification or export policy. |

### Native and distribution gates

The next release checkpoint should name the exact target OS versions and CPU architectures before building. A build on a recent OS does not prove compatibility with the oldest claimed version. Qualify the extracted or installed artifact in addition to the source checkout, and record failed gates alongside successful ones.

| Target or gate | Required evidence before widening the release claim |
| --- | --- |
| Windows x64 | Fresh generated user profile; offline extracted-package launch; path/Unicode handling; GUI task and cancellation checks; worker-tree shutdown; declared DPI behavior; signature and publisher verification if distributing a signed build. |
| Windows ARM64 | Actual native execution of the matching Python, bootloader, FFmpeg and FFprobe binaries. Verify interpreter ABI selection separately from x64 emulation; archive extraction and header checks alone do not qualify execution. |
| Apple Silicon | Signed app and packaged nested tools from the intended Apple team, notarized/stapled distribution where applicable, downloaded-artifact Gatekeeper assessment, and generated workflow checks on a clean system and the declared minimum macOS. Existing ad hoc validation is not a substitute. |
| Linux x64 and ARM64 | Actual native execution on the chosen minimum glibc baseline; GUI/display dependencies; extracted ZIP permissions; AppImage direct launch and supported fallback where FUSE is unavailable; offline workflow and shutdown checks. Keep WSL results explicitly identified. |
| Offline installation | A complete kit or supplied verified archives succeeds without network access. Installed tools are reused without update checks. Missing dependencies fail with actionable offline instructions; no setup client is reachable through processing code. |
| Distribution integrity | Exact artifact/source association, checksum manifest verification, architecture inventory and authenticated publisher delivery appropriate to the platform. Preserve existing artifacts on failed or repeated builds. |
| License and source delivery | Complete the software/license inventory and corresponding-source materials required by the selected FFmpeg build and dependencies before public distribution. The present development artifact is not documented as completing this gate. |
| Privacy and containment claims | Retain the distinction between application Sensitive treatment and OS isolation/encryption. Any future containment adapter needs its own escape, filesystem, network and process-lifecycle checks; changing the UI toolkit proves none of these properties. |

Signing credentials, notarization services and distribution publication require their own concrete authorized handoff; this plan does not access credentials or publish an artifact. Operator-media feedback remains operator-controlled and may enter the development process only through deliberately supplied, locally reviewed sanitized information. All assistant-run qualification described here uses generated inputs and isolated test state.
