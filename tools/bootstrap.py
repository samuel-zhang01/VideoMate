"""Prepare missing pinned software, then start VideoMate. Use --offline to prohibit downloads."""
import argparse
import importlib.util
import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Runtime has no pip requirements. Source is preferred so edits take effect.
for candidate in (ROOT / "src", ROOT / "videomate.pyz", ROOT / "dist" / "videomate.pyz"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))
        break


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid launcher arguments. Run start --help for usage.\n")


def arguments(argv):
    parser = SafeParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup-online", action="store_true", help="Compatibility alias for automatic missing-software setup")
    mode.add_argument("--offline", action="store_true", help="Use installed, supplied or cached dependencies only; never download")
    parser.add_argument("--yes", action="store_true", help="Approve a missing Python/Tk download without an interactive prompt; setup only")
    parser.add_argument("--source", action="store_true", help="Use the source/Python edition instead of a bundled desktop")
    parser.add_argument("--config", type=Path, help="Use this local GUI settings file (CLI commands accept their own --config)")
    parser.add_argument("--archive", type=Path, help="Offline Windows FFmpeg ZIP")
    parser.add_argument("--archive-directory", type=Path, help="Offline directory with both macOS/Linux tool ZIPs")
    parser.add_argument("--runtime-archive", type=Path, help="Offline pinned Python/Tk archive")
    parser.add_argument("--install-runtime", action="store_true", help="Prepare pinned local Python/Tk even when a suitable Python is already installed")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="Check tools and report GUI availability without opening media")
    action.add_argument("--self-test", action="store_true", help="Test the GUI using freshly generated synthetic media only")
    action.add_argument("--cli", nargs=argparse.REMAINDER, help="Run a CLI command; place all its arguments last")
    return parser.parse_args(argv)


def prepare(args, *, dependencies=None):
    from videomate.dependencies import load_bundle, default_root, platform_tag
    from videomate.errors import VideoMateError
    from videomate.setup_local import check_backend
    if dependencies is not None:
        # Selected software is verification-only. Never replace it or silently
        # provision a different bundle when the operator chose an offline one.
        return check_backend(dependencies)
    try:
        load_bundle()
    except VideoMateError:
        # A damaged existing installation must never be silently overwritten.
        if (default_root() / platform_tag()).exists():
            raise VideoMateError("dependency_unavailable") from None
        spec = importlib.util.spec_from_file_location("videomate_provision", ROOT / "tools" / "install_ffmpeg.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        installer.install(argparse.Namespace(platform=platform_tag(), archive=args.archive,
            archive_directory=args.archive_directory, offline=args.offline, import_directory=None,
            version=None, ffmpeg_sha256=None, ffprobe_sha256=None, license_file=None))
    return check_backend()


def selected_dependencies(args, cli_args=None):
    """Match the GUI/CLI's settings precedence without reading media state."""
    from videomate.preferences import default_config_path, load_preferences
    if cli_args is not None:
        config = getattr(cli_args, "config", None)
        if cli_args.command == "gui":
            config = config if config is not None else default_config_path()
        explicit = getattr(cli_args, "dependencies", None)
    else:
        # A plain software check and generated self-test must not read settings.
        config = None if args.self_test else args.config
        if config is None and not args.check and not args.self_test:
            config = default_config_path()
        explicit = None
    preferences = load_preferences(config) if config is not None else None
    return explicit if explicit is not None else (
        Path(preferences.dependencies) if preferences and preferences.dependencies else None)


def tkinter_available():
    try:
        import tkinter  # No root/window or user data is created by this check.
        return True
    except (ImportError, OSError):
        return False


def approve_runtime_download(args, tag):
    if args.offline or args.runtime_archive is not None or args.yes or args.setup_online:
        return True
    pins = json.loads((ROOT / "dependencies/python-sources.json").read_text(encoding="utf-8"))
    if (ROOT / "dependencies/cache" / pins["platforms"][tag]["filename"]).is_file():
        return True
    print("VideoMate needs a local Python/Tk runtime for this setup. It can download the pinned runtime without changing system Python, venv or Conda.\n"
          "Alternatively use Python 3.11+ with Tk from https://www.python.org/downloads/ or set VIDEOMATE_PYTHON to an approved interpreter.")
    if not sys.stdin.isatty():
        print("No interactive terminal is available. Add --yes to approve setup, or supply --runtime-archive with --offline.")
        return False
    try:
        approved = input("Download and install local Python/Tk? [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        approved = False
    if not approved:
        print("Setup cancelled. No software was downloaded.")
    return approved


def main(argv=None):
    if sys.version_info < (3, 11) or struct.calcsize("P") != 8:
        print("VideoMate needs 64-bit Python 3.11+ or the self-contained desktop package.")
        return 2
    args = arguments(argv)
    try:
        from videomate.errors import VideoMateError
        cli_args = None
        cli_backend_required = False
        if args.cli is not None:
            from videomate.cli import main as cli, parser as cli_parser
            # Parse before installing anything: help, invalid arguments and
            # metadata commands need no backend or Python/Tk provisioning.
            cli_args = cli_parser().parse_args(args.cli or ["--help"])
            cli_backend_required = cli_args.command in {"scan", "recover", "migrate", "resume", "gui"}
            if not cli_backend_required and not (args.install_runtime or args.runtime_archive is not None):
                return cli(args.cli)
        from videomate.dependencies import platform_tag
        tag = platform_tag()
        spec = importlib.util.spec_from_file_location("videomate_python", ROOT / "tools/install_python.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        runtime_root = installer.runtime_path(tag)
        runtime_requested = args.install_runtime or args.runtime_archive is not None or (not args.offline and args.cli is None and not args.check and not tkinter_available())
        using_runtime = Path(sys.executable).resolve().is_relative_to(runtime_root.resolve())
        prefer_local = runtime_root.exists() and not os.environ.get("VIDEOMATE_PYTHON")
        if not using_runtime and (prefer_local or runtime_requested):
            if not runtime_root.exists() and not approve_runtime_download(args, tag):
                return 2
            selected = installer.install(tag, archive=args.runtime_archive, online=not args.offline)
            os.execv(str(selected), [str(selected), "-I", "-X", "utf8", str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv)])
        elif using_runtime and runtime_root.exists():
            installer.verify(tag)
        if cli_args is not None and not cli_backend_required:
            return cli(args.cli)
        gui_launch = (cli_args is not None and cli_args.command == "gui") or (
            cli_args is None and not args.check and not args.self_test)
        try:
            dependencies = selected_dependencies(args, cli_args)
        except VideoMateError:
            if not gui_launch:
                raise
            # Let the GUI show its existing settings-repair flow. An invalid
            # config is not permission to download a fallback tool bundle.
            tools = None
        else:
            try:
                tools = prepare(args, dependencies=dependencies)
            except VideoMateError:
                if not gui_launch or dependencies is None:
                    raise
                # A stale custom location must remain editable in Settings.
                # The GUI independently checks it and keeps processing disabled.
                tools = None
        if args.check:
            print(json.dumps({"platform": tools["platform"], "ffmpeg_version": tools["version"],
                              "backend": "ready", "tkinter": "available" if tkinter_available() else "missing",
                              "setup_policy": "offline" if args.offline else "download_missing_pinned_software",
                              "processing_network": "disabled"}, indent=2))
            return 0  # CLI remains usable without Tk or a desktop session.
        if args.cli is not None:
            from videomate.cli import main as cli
            return cli(args.cli)
        if not tkinter_available():
            print("The CLI is ready, but this Python lacks Tk. Use --cli, --install-runtime, or --runtime-archive with a pinned offline Python/Tk archive.\n"
                  "You can also use an approved system Python with Tk.\n"
                  "See docs/launchers.md. No system packages were changed.")
            return 2
        if args.self_test:
            from videomate.selftest import run_self_test
            print(json.dumps(run_self_test(), indent=2))
            return 0
        from videomate.gui import launch
        return launch(config_path=args.config)
    except KeyboardInterrupt:
        print("Setup or launch cancelled. Existing dependencies were preserved.")
        return 130
    except Exception as error:
        # Unknown errors may include private input paths. Do not echo them.
        from videomate.errors import VideoMateError
        if isinstance(error, VideoMateError):
            print(str(error))
        else:
            print("Local setup failed. No private error details were displayed.")
        print("Offline: supply pinned archives with --archive / --archive-directory.\n"
              "Missing software downloads automatically unless --offline is set. Existing invalid bundles require local review; they are never overwritten.\n"
              "See docs/launchers.md for runtime, permissions and dependency troubleshooting.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
