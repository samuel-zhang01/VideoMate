# Launchers and dependency setup

VideoMate 0.8.4 prepares missing pinned public software before starting. Missing Python/Tk downloads ask first and default to No; --yes permits unattended setup. Pass `--offline` to prohibit downloads, including on the very first launch. Media processing never installs packages or makes network requests. Installed tools are reused without update checks; `--setup-online` remains an explicit approval alias for online setup.

## Choose a package

| Edition | Launch | What it needs |
| --- | --- | --- |
| Windows x64 desktop | `start.bat` or `VideoMate/VideoMate.exe` | Entire extracted folder; Python/Tk/tools included |
| Windows ARM64 desktop (native build pending) | `start.bat` or `VideoMate/VideoMate.exe` | Matching ARM64 bundle; requires native qualification before release |
| Linux x64/ARM64 desktop (native build pending) | `./start.sh` or `VideoMate/VideoMate` | Matching desktop ZIP or AppImage; requires native qualification before release |
| Apple Silicon desktop | `start.command`, `sh start.sh` or `VideoMate.app` | Entire extracted folder; Python/Tk/tools included |
| Source / Python kit | `start.bat`, `start.command`, `sh start.sh` | Automatic local Python/Tk and tool provisioning, or supplied offline archives |
| Python kit with runtime | Same launchers | Entire kit; includes pinned Python/Tk and tools |

Use the matching OS/architecture bundle. GitHub Actions is disabled; see release notes for this version platform evidence. Extract Linux runtime kits with `unzip` on a native Linux filesystem to preserve permissions and case. They still require compatible OS libraries and a graphical display for the GUI. Alpine/musl, older distributions and older macOS versions are not qualified.

If no compatible Python is installed, the launchers offer to provision pinned portable Python/Tk locally. The prompt also points to python.org and explains how to select an existing interpreter. Declining downloads nothing; non-interactive setup requires --yes. Windows 10/11 x64/ARM64 uses built-in Windows PowerShell, curl and tar; macOS/Linux uses curl, tar, and sha256sum or shasum. Checksums are verified before extraction or execution. If required OS tools or an approved script execution policy are unavailable, use a complete desktop/runtime kit or set VIDEOMATE_PYTHON to an approved Python. Setup never changes security policies or installs system packages.

## Source and Python-kit commands

On Windows use `.\start.bat` in PowerShell; replace that prefix with `sh start.sh` on macOS/Linux. Launchers resolve software relative to themselves, including paths with spaces and Unicode, regardless of the current directory.

In a source checkout, the launchers prefer current source even if an older desktop binary is beside it. Packaged desktop folders still use their included binary. The current source GUI creates missing settings and workspace/output folders at startup, preserving existing preferences. **Prepare workspace** recreates missing folders, saves current preferences to the selected settings file and verifies that it can be read back. A blank settings-file field uses the default. Existing unrelated or invalid files are never replaced; select another settings filename or resolve the conflict locally. The Settings page reports preparation success or a fixed failure reason.

```powershell
.\start.bat                         # prepare missing software, then open GUI
.\start.bat --source                # use source/Python launcher explicitly
.\start.bat --check                 # check tools/encoders and Tk; no media
.\start.bat --self-test             # generate test media and exercise GUI/repair
.\start.bat --cli --help            # CLI arguments must come last
.\start.bat --cli doctor
.\start.bat --offline --check
.\start.bat --yes --install-runtime --check
```

`--check` returns zero when the backend is ready, even if Tk is missing; its JSON reports that distinction. Tk import does not prove a display is available. `--self-test` needs a display and accepts no existing media. The native desktop launcher supports GUI startup, `--check`, and `--self-test NEW-REPORT.json`, plus `--config SETTINGS.json`; use a source/Python kit for CLI commands or provisioning flags.

Automatic setup downloads missing pinned FFmpeg/FFprobe and, when requested or needed for the GUI, portable Python/Tk. No administrator access, sudo, PATH changes, pip installation or Conda environment modification is performed. The application itself has no online-setup button.

## Fully offline setup

Prepare software on an approved connected machine, then transfer the complete matching desktop/runtime kit. Alternatively transfer the source/Python kit plus the exact pinned archives in `dependencies/sources.json` and `dependencies/python-sources.json`.

Windows FFmpeg uses one ZIP. macOS/Linux use two ZIPs; required local filenames are recorded in the catalog.

```powershell
.\start.bat --offline --archive "E:\ApprovedSoftware\ffmpeg-9.0.2.zip" --check
.\start.bat --offline --archive "E:\ApprovedSoftware\ffmpeg-9.0.2.zip" --runtime-archive "E:\ApprovedSoftware\pinned-python.tar.gz" --check
```

```sh
sh start.sh --offline --archive-directory /approved/archives --check
sh start.sh --offline --archive-directory /approved/archives --runtime-archive /approved/pinned-python.tar.gz --check
```

Archives are checksum checked before extraction; existing invalid bundles are refused, never silently replaced. Cached matching archives in `dependencies/cache` work without flags. After preparation, startup reuses installed software. Keep --offline set when no setup download is permitted. There are no runtime pip requirements.

Source runtimes normally live at `dependencies/python/<platform>/python`. For WSL checkouts on Windows drives (`/mnt/c/...`), the installer instead uses `${XDG_CACHE_HOME:-$HOME/.cache}/videomate-software/python/<platform>` on native Linux storage because some runtime filenames differ only by case. `VIDEOMATE_RUNTIME_ROOT` selects a runtime parent; `VIDEOMATE_PYTHON` selects an existing interpreter. These variables contain software locations, never media locators or secrets.

## Saved settings

Use start.bat --config C:\ApprovedLocal\settings.json (or sh start.sh --config /approved/local/settings.json) to choose a GUI settings file. VIDEOMATE_CONFIG also selects the default GUI settings file. In the CLI, pass --config after the media command, for example --cli scan --config /approved/local/settings.json --input /local/video.mp4. CLI options override saved preferences. [All configurable options](settings-and-privacy.md).

## Troubleshooting

- **No Python:** start.bat/start.sh install pinned Python locally when required. With --offline, supply --runtime-archive or cache the matching archive first. A bare .pyz still requires an interpreter.
- **Tk missing:** CLI remains usable. Supply pinned Python/Tk offline or use `--install-runtime`. Approved system Python with Tk also works.
- **No Linux display:** use a desktop/WSLg session, CLI, or Xvfb for CI. Tk import alone is not a GUI test.
- **Invalid bundle/checksum mismatch:** verify software locally; restore a complete package into a new software folder. Startup never overwrites suspect dependencies. Manifests detect changes; they are not publisher signatures.
- **Install lock or partial file exists:** another setup may be active. After a crash, the operator can review the exact software-only lock/partial locally and relocate it once no installer owns it. Another process's lock is never removed automatically.
- **Linux libraries or permissions:** use a glibc-based distribution and extract with Unix permissions on native Linux storage. Tk requires the host X11/display libraries; the launcher does not install OS packages or support Alpine/musl. Use CLI on headless hosts. No automatic sudo/package-manager fallback occurs.
- **Source changes not visible:** launch from the repository root. It always uses current source; packaged desktop launchers open their adjacent executable. Old dist builds are not selected automatically.
- **Sensitive treatment:** use the GUI Yes/No flag or CLI --sensitive yes/no for new jobs. Both remain offline. See [settings and privacy](settings-and-privacy.md). The old --test-files alias remains available as Sensitive: No for older scripts; it cannot be combined with --sensitive.

Do not share raw logs containing private arguments. Review sanitized exports locally. [Dependency provenance](../dependencies/README.md) and [validation status](implementation-status.md) describe the limits.

Activated venv and Conda environments are honored before automatic runtime selection. Set VIDEOMATE_PYTHON to override this explicitly. Source launchers do not create a venv or install Conda: the portable runtime already isolates application dependencies, and the application has no pip requirements. Complete desktop/runtime release ZIPs need no preinstalled Python.
