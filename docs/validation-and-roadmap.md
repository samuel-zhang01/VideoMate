# Validation and roadmap

All assistant media tests create their own fixtures. Existing operator media, folders, private journals, mappings and keys are excluded from development and CI. [Current evidence](implementation-status.md).

## Windows suite

```powershell
.\start.bat --check
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:VIDEOMATE_TEST_FFMPEG = Join-Path (Get-Location) 'dependencies/ffmpeg/windows-x86_64/bin/ffmpeg.exe'
$env:VIDEOMATE_TEST_FFPROBE = Join-Path (Get-Location) 'dependencies/ffmpeg/windows-x86_64/bin/ffprobe.exe'
$env:VIDEOMATE_TEST_GUI = '1'
py -3.13 -m unittest discover -s tests -v
.\start.bat --self-test
```

## Unix suite

Run the launcher to provision missing pinned software, or supply archives with --offline. Use Python 3.13 with Tk for the full suite (the pinned runtime is suitable); a system Python 3.12 without Tk will fail the GUI and CPU-budget tests. A desktop/WSLg session or Xvfb is required for GUI tests.

```sh
sh start.sh --check
export PYTHONPATH="$PWD/src"
export VIDEOMATE_TEST_FFMPEG="$PWD/dependencies/ffmpeg/linux-x86_64/bin/ffmpeg"
export VIDEOMATE_TEST_FFPROBE="$PWD/dependencies/ffmpeg/linux-x86_64/bin/ffprobe"
export VIDEOMATE_TEST_GUI=1
python3.13 -m unittest discover -s tests -v
sh start.sh --self-test
```

On Apple Silicon use `macos-arm64`. Dependency checks do not replace native execution. Tests skip backend/GUI paths unless configured; always report skips. The optional third-party JSON Schema reference-validator test skips if that library is absent; the bundled validator tests still run.

The GUI self-test supplies its own temporary settings file so it never loads an operator profile. It checks settings persistence, hidden/revealed synthetic filenames, custom output locations, explicit-only sensitive export, logging suppression and standard-mode event logging.

## Coverage

Generated MP4/AVI/FLV/Matroska, missing moov, damaged packets, truncation, quick/full scans, remux, both re-encode profiles, interval salvage, original preservation/change, publication collision, locks, cancel/resume, reports, export privacy, hostile diagnostics, resource limits, archive traversal/links/checksums, offline setup, missing Tk and launcher paths with spaces/Unicode.

`tools/gui_qa.py` creates an isolated generated-media window for Computer Use/manual checks, accepts no existing media and checks source preservation on close. No file chooser is needed. The old screenshot helper is archived. Native package builds run GUI/media tests before and after extraction with Python/Conda/Tcl overrides removed.

## Release gates

1. Native Apple Silicon and Linux ARM64 execution; clean Windows/Linux hosts and supported OS-version matrix.
2. GUI accessibility, high DPI, keyboard navigation, multi-monitor and extended resource/cancellation tests.
3. OS-enforced filesystem/network isolation, encrypted storage/key policy and crash/paging controls for environments that require those additional protections.
4. Signed/authenticated distribution, trusted offline provisioning, corresponding-source/license delivery and update/rollback procedures.
5. Broader generated corruption corpus and codec/profile coverage before expanding automatic recovery.

Reference-assisted reconstruction, multi-interval cuts and automatic localization are future features. No test proves source completeness without independent evidence. GitHub Actions is disabled. The retained workflows require explicit dispatch and future owner authorization. Local prereleases must state exactly which native packages passed; older native evidence does not qualify newer code.

Software kits can be checked with python tools/verify_kit.py dist/<kit>.zip. Add --execute only on the matching native platform to extract into an owned temporary software directory, verify every manifest hash and run launcher checks plus the generated-media GUI self-test. No operator inputs are accepted.

## Repository and installer checks

`python tools/check_repository.py` checks only the Git index, rejecting non-source paths before reading blobs. Native pre-Python unit tests use invented corrupt archives and --offline; they verify refusal and cleanup without network access.

`python tools/verify_fresh_setup.py --download` creates a fresh software-only copy, downloads pinned public runtimes/tools, checks them and repeats startup offline. Windows clears Python from PATH; Unix invokes the no-Python helper directly before the launcher. This explicit installation test accepts no operator inputs.

Retained workflow definitions cover Python 3.11/3.13 on Windows, Apple Silicon macOS and Linux x64/ARM64, using [GitHub's documented runner labels](https://docs.github.com/en/actions/reference/runners/github-hosted-runners). These workflows are prepared, not remotely executed evidence.
