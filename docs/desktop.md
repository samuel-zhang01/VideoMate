# VideoMate desktop

The desktop build contains Python, Tcl/Tk, FFmpeg and FFprobe. The operator does not need Anaconda, pip, PATH configuration or an internet connection. Extract the entire archive, retaining its directory structure. On Windows open start.bat or VideoMate/VideoMate.exe; on Apple Silicon open start.command or VideoMate.app; on Linux run ./start.sh or VideoMate/VideoMate. Native launchers support --check, --self-test NEW-REPORT.json and --config SETTINGS.json. Source/Python kit launchers additionally provide CLI and provisioning options; see [launchers](launchers.md). Linux desktop ZIP and AppImage builders are now available but still need native qualification on each architecture; the previously tested runtime kit remains a fallback.

Use **Start** to choose Inspect, Repair or Migrate, select the source and set the output folder. The Start button stays visible at the bottom of every page; migration asks for Sensitive local-name permission if needed. **Options** contains optional profiles and tuning. Every repair is decoded again before publication. **Activity** provides findings and resume/export controls. New Sensitive jobs have session-only reports; export before closing. Startup prepares missing settings/workspace/output directories and checks the tools. **Prepare workspace** fills in missing app folders, saves current preferences and verifies the selected settings file, preserving unrelated contents. You can configure a different private workspace or offline tool bundle. Migration has no artificial file-count ceiling; its progress bar shows processed/total files, elapsed time and an approximate remaining time.

Settings lets you configure the workspace, recovered files, diagnostics, event logs, settings file, tool bundle, timeout and candidate-size limit. Job-specific locations/privacy are retained on resume. [Settings guide](settings-and-privacy.md).

Default workspace locations:

- Windows: `%LOCALAPPDATA%/VideoMate/Workspace`
- macOS: `~/Library/Application Support/VideoMate/Workspace`
- Linux source edition: `~/.local/state/VideoMate/Workspace`

Neutral recovered files are under `recovered/<job-id>/input-<number>/`. Sensitive: No can instead retain basenames or selected folder structure beneath the job root. Recovery also offers all-eligible-file MP4 conversion, bitrate/approximate-size controls and a shortening limit. Originals are preserved by recovery; separate manual cleanup actions require individual selection and typed confirmation. Free-form metadata and chapters are omitted from recovered copies. Lossy conversion, shorter output, auxiliary track removal and possible concealment are disclosed. Successful decoding cannot prove that missing original content has been restored. [Recovery and private resume guide](recovery-options.md).

Sensitive: Yes is the default. New Sensitive journals stay in memory and write no filename mappings, while queue names are hidden and automatic diagnostics/basic logs are suppressed. Private resume is an optional passphrase-authenticated checkpoint with reselected files; it is not encryption. Additional diagnostics independently opts in to safe technical disk logs. The 0.8.4 source includes these controls. Sensitive: No retains the same offline/export baseline. There are no uploads, telemetry, previews, runtime dependency downloads or update checks. Share only reviewed sanitized exports; never share checkpoints, private state, mappings, filenames or raw FFmpeg logs.

## Native builds

Current source also provides Inspect/Repair/Migrate task selection, custom processing presets and collapsible advanced controls. The persistent Start action follows the selected task. Navigation uses themed buttons instead of classic Tk buttons whose background styling differs on macOS. A native Apple Silicon development check covered the main screens and generated-media layout matrix; screen-reader behavior remains unverified. Actions is disabled. These controls were included in the 0.8.3 Windows preview and remain in 0.8.4 source. Source checkouts prefer current source over an older adjacent binary. [Profiles and migration](migration-and-profiles.md).

Build each target on its matching native host: Windows x64/ARM64, Linux x64/ARM64, or Apple Silicon. No Intel Mac or 32-bit package is planned. Native builds must pass the packaged GUI self-test before an archive is produced. That test generates its own fixture, deliberately damages one packet, exercises inspection, remux, both re-encoding profiles, repair, resume, grouped reports and sanitized exports, and checks source preservation. It accepts no operator media inputs.

```text
python tools/build_release.py
```

The release builder installs pinned public tools into an isolated local build environment and never replaces an existing release artifact. For an offline build, prepare a same-architecture wheelhouse and catalog-pinned archives, then use `--offline --wheelhouse PATH`. Windows uses one pinned FFmpeg archive; Mac/Linux use two tool archives. On Linux, the builder also emits an AppImage using pinned appimagetool and a pinned runtime. [Native-host release handoff](release_development.md) has the commands, Mac plan and qualification gates.

GitHub Actions is disabled. Local release checks and platform limits are recorded in [release notes](release-notes.md).

## Distribution status

Earlier source/runtime-kit GUI/recovery tests covered Windows x64, Apple Silicon and Linux x64/ARM64. The 0.8.3 local preview qualified a Windows x64 desktop and Linux x64 runtime kit under WSL. New Windows ARM64 and Linux frozen/AppImage build paths require fresh native execution before release. A 0.8.4 Apple Silicon development package has a separate validation record; Mac distribution and clean-machine qualification remain open. Actions remains disabled.

Windows packages are currently unsigned; default macOS builds use ad-hoc signing. An opt-in Developer ID and notarization path exists but has not been exercised with an approved certificate or Apple account. Publisher signing, macOS Gatekeeper distribution testing, clean-machine compatibility and production containment qualification remain release work. Do not bypass organization controls to install the development build. Building on a particular macOS runner does not establish compatibility with older macOS versions.

FFmpeg is separately launched software. `dependencies/sources.json` records upstream provenance and pinned downloads. The dependency bundle retains its license and build-source information; Python/Tk and packaging libraries retain their collected licenses. A public distribution must include the corresponding source/license materials required by the selected FFmpeg build and its dependencies. This development artifact is not a completed public-release compliance package.

## Window sizing and display scale

The current source organizes Settings into Storage, Privacy, Performance, Application and Display. Save, undo and session reset show whether preferences have unsaved edits. Display's reduced-motion option keeps status/counts while disabling continuous progress animation. Fixed correction messages reveal the relevant field; compact layouts retain privacy/export/logging disclosures. See the [4 October audit](development/app-improvement-audit.md) for executed checks and remaining accessibility/release gaps.

The GUI uses a sidebar on wide windows and a top navigation bar when space is limited. Descriptive text and action rows wrap to fit. Every page scrolls when needed; keyboard focus brings controls into view. The Stop job control stays outside the scrolling page. Compact layouts omit decorative summary cards and the subtitle to leave room for the task.

Automated viewport checks cover 800×600, 1024×768 and 1440×900 at 100%, 150% and 200% Tk text scales. Windows source startup and the native manifest request system DPI awareness, following [Microsoft's process DPI guidance](https://learn.microsoft.com/en-us/windows/win32/hidpi/setting-the-default-dpi-awareness-for-a-process). Tests do not change OS display settings. The same layout matrix is available for future native Apple Silicon qualification. Mixed-DPI monitor switching, physical-display appearance and screen-reader behavior still need qualification.
