import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .demo import run_demo
from .dependencies import load_bundle
from .errors import VideoMateError
from .models import Depth, recovery_suggestion
from .local_scan import job_inputs, report_local, resume_local, scan_local
from .inspection import duration_us
from .recovery import PROFILES, RecoveryOptions
from .policy import create_workspace
from .preferences import Preferences, load_preferences
from .schema import MAX_EXPORT_BYTES, get_schema, load_json, validate_export
from .encoding import RATE_MODES
from .output_layout import LAYOUTS


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error includes the offending private argument.
        raise VideoMateError("invalid_arguments")


def parser():
    result = SafeParser(prog="videomate", description="Inspect, repair and verify local videos. Offline by default; originals are preserved.")
    result.add_argument("--version", action="version", version=f"VideoMate {__version__} (development)")
    commands = result.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Verify local tool hashes, executable compatibility and recovery encoders without reading media.")
    doctor.add_argument("--dependencies", type=Path)
    init = commands.add_parser("init", help="Create a local workspace for saved jobs and results.")
    init.add_argument("--workspace", required=True)
    demo = commands.add_parser("demo", help="Run scripted synthetic scenarios; no media or FFmpeg required.")
    demo.add_argument("--export", help="Write a synthetic diagnostic example to a new file.")
    validate = commands.add_parser("validate-export", help="Validate an already-sanitized diagnostic JSON without echoing contents.")
    validate.add_argument("input")
    summary = commands.add_parser("support-summary", help="Summarize an already-sanitized export without IDs, paths, timestamps or raw logs.")
    summary.add_argument("input")
    scan = commands.add_parser("scan", help="Inspect selected local videos; never alters originals.")
    scan.add_argument("--input", required=True, action="append", help="One local file or an explicitly recursive folder; repeat for a batch.")
    scan.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=None, help="Include subfolders, excluding links and result folders.")
    scan.add_argument("--depth", choices=("quick", "full"), default="full")
    scan.add_argument("--workspace", type=Path)
    scan.add_argument("--dependencies", type=Path)
    scan.add_argument("--timeout", type=int, help="Maximum seconds per worker, 1-86400 (default 3600).")
    recover = commands.add_parser("recover", help="Recover into separate verified outputs. Guided mode previews unless --execute is set.")
    target = recover.add_mutually_exclusive_group(required=True)
    target.add_argument("--job", help="Use the input list from a previous local job; re-inspects every input.")
    target.add_argument("--input", action="append")
    recover.add_argument("--workspace", type=Path)
    recover.add_argument("--dependencies", type=Path)
    recover.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=None)
    recover.add_argument("--timeout", type=int)
    recover.add_argument("--mode", choices=("guided", "auto"), default="guided")
    recover.add_argument("--execute", action="store_true")
    migrate = commands.add_parser("migrate", help="Build a new folder package from healthy copies, verified repairs and other files.")
    migrate.add_argument("--input", action="append", required=True, help="Exactly one local source folder; includes its subfolders and other files.")
    migrate.add_argument("--workspace", type=Path)
    migrate.add_argument("--dependencies", type=Path)
    migrate.add_argument("--timeout", type=int)
    migrate.add_argument("--preview", action="store_true", help="Inventory the selection without creating a package.")
    migrate.add_argument("--local-output-names", action=argparse.BooleanOptionalAction, default=None,
                         help="Explicitly permit preserved names/folders in Sensitive local migration output.")
    migrate.add_argument("--preserve-file-times", action=argparse.BooleanOptionalAction, default=None)
    migrate.add_argument("--unresolved", choices=("exclude", "copy", "review"), help="Choose before starting: exclude unresolved files from output (default), copy unchanged, or use a separate review folder. Sources stay untouched.")
    for command in (recover, migrate):
        command.add_argument("--strategy", choices=("auto", "remux", "reencode"))
        command.add_argument("--profile", choices=PROFILES)
        command.add_argument("--hardware-encoding", action=argparse.BooleanOptionalAction, default=None,
                             help="Try a generated-frame-qualified hardware encoder for Compatible SDR; fall back to software.")
        command.add_argument("--force", action=argparse.BooleanOptionalAction, default=None, help="Explicit conversion even if no damage is detected.")
        command.add_argument("--allow-track-loss", action=argparse.BooleanOptionalAction, default=None, help="Permit omitting non-audio/video tracks and attached pictures.")
        command.add_argument("--allow-shorter", action=argparse.BooleanOptionalAction, default=None, help="Permit verified shorter outputs, recording possible loss.")
        command.add_argument("--partial-salvage", action=argparse.BooleanOptionalAction, default=None,
                             help="After normal repair fails, try software recovery of a verified playable portion; mark partial outputs for review.")
        command.add_argument("--max-output-mib", type=int, help="Optional temporary candidate cap in MiB; 0 (default) disables it. Low-disk protection remains enabled.")
        command.add_argument("--max-source-percent", type=int, help="Optional temporary candidate cap as percent of source; 0 (default) disables it. This is separate from the finished-size target.")
        command.add_argument("--size-policy", choices=("strict", "best_effort"), help="Strict withholds outputs above the size target; best_effort permits fully verified outputs with a size warning.")
        command.add_argument("--size-tolerance-percent", type=int, help="Allowed finished-size overshoot for source/target size modes, 5-100 (default 25). One bitrate adjustment retry is allowed.")
        command.add_argument("--audio-normalization", choices=("off", "playback", "broadcast"), help="Optional single-pass loudness normalization for MP4 re-encoding: playback -16 LUFS or broadcast -23 LUFS. Default off.")
        command.add_argument("--audio-bitrate-kbps", type=int, choices=(0, 64, 96, 128, 160, 192, 256, 320), help="AAC bitrate per track; 0 keeps adaptive budgeting.")
        command.add_argument("--software-preset", choices=("fast", "medium", "slow"), help="Software encoding speed/compression tradeoff; hardware remains preferred.")
        command.add_argument("--mp4-faststart", action=argparse.BooleanOptionalAction, default=None, help="Place the MP4 index first for quicker playback start (default enabled).")
        command.add_argument("--convert-all-mp4", action=argparse.BooleanOptionalAction, default=None, help="Convert all eligible inputs to MP4: compatible stream copy first, then verified H.264/AAC fallback.")
        command.add_argument("--convert-noncompliant-hevc", action=argparse.BooleanOptionalAction, default=None,
                             help="Migration: copy healthy MP4 H.264/HEVC unchanged; convert other videos to verified HEVC MP4 with playback loudness.")
        command.add_argument("--video-codec", choices=("h264", "hevc"), help="Codec for compatible MP4 re-encoding; default H.264.")
        command.add_argument("--rate-control", choices=RATE_MODES, help="Auto source bitrate, software CRF quality, approximate source/target size, or explicit bitrate.")
        command.add_argument("--video-bitrate-kbps", type=int, help="Per-video-stream bitrate for bitrate mode, 50-200000.")
        command.add_argument("--target-size-mib", type=int, help="Approximate total size per output in target_size mode; not a hard size guarantee.")
        command.add_argument("--quality-crf", type=int, help="Software quality mode CRF, 0-51. Hardware uses the automatic bitrate estimate.")
        command.add_argument("--max-shorter-percent", type=int, help="Maximum duration loss when --allow-shorter is enabled, 0-100 (default 10).")
        command.add_argument("--keep-start", help="Keep only a selected common interval, in playback-relative seconds.")
        command.add_argument("--keep-end")
    for command in (scan, recover, migrate):
        command.add_argument("--preset", help="Apply a built-in or saved local processing profile; explicit flags override it.")
        command.add_argument("--config", type=Path, help="Read saved preferences; explicit command options take precedence.")
        command.add_argument("--sensitive", choices=("yes", "no"), help="Sensitive treatment (default yes): automatic exports off; safe disk diagnostics require separate opt-in.")
        command.add_argument("--test-files", action="store_true", help=argparse.SUPPRESS)
        command.add_argument("--recovered-dir", help="Recovered-files root; default workspace/recovered.")
        command.add_argument("--diagnostics-dir", help="Sanitized diagnostics root; default workspace/export-review.")
        command.add_argument("--logs-dir", help="Event log root; default workspace/logs.")
        command.add_argument("--write-logs", action=argparse.BooleanOptionalAction, default=None, help="Write fixed event codes/counters; disabled for Sensitive: Yes.")
        command.add_argument("--diagnostic-logs", action=argparse.BooleanOptionalAction, default=None, help="Opt in to detailed sanitized disk diagnostics, including Sensitive jobs. Never writes raw backend text.")
        command.add_argument("--cpu-threads", type=int, help="Shared codec thread budget; 0 uses available logical CPUs minus two (minimum one).")
        command.add_argument("--max-runners", type=int, help="Parallel file limit: Inspect uses CPU budget; Migrate defaults to up to four. Standalone Repair remains serial.")
        if command is migrate:
            command.add_argument("--hardware-preference", choices=("auto", "nvidia", "amd", "intel", "apple"),
                                 help="Prefer a qualified encoder vendor; auto uses saved synthetic calibration.")
            command.add_argument("--migration-gpu-jobs", type=int, help="Concurrent GPU jobs for migration, 1-16 (default 2).")
            command.add_argument("--migration-cpu-auto", action=argparse.BooleanOptionalAction, default=None,
                                 help="Automatically add a CPU encoding lane beside qualified GPUs when at least 16 codec threads are available (default enabled).")
            command.add_argument("--migration-cpu-encoding", action=argparse.BooleanOptionalAction, default=None,
                                 help="Force a CPU encoding lane when eligible; --no-migration-cpu-encoding disables automatic and forced CPU lanes.")
        command.add_argument("--hardware-decoding", action=argparse.BooleanOptionalAction, default=None, help="Prefer a generated-frame-qualified hardware decoder; fall back to software (default enabled).")
        command.add_argument("--output-layout", choices=LAYOUTS, help="neutral, filename or folders; Sensitive jobs always use neutral output names.")
        command.add_argument("--retain-history", action=argparse.BooleanOptionalAction, default=None, help="Opt in to persistent sensitive job history, including private source paths.")
        command.add_argument("--retain-mappings", action=argparse.BooleanOptionalAction, default=None, help="Opt in to export-to-path mappings for non-sensitive jobs only.")
        command.add_argument("--interruption-recovery", action=argparse.BooleanOptionalAction, default=None, help="Migration: reconnect verified storage and retry transient failures up to three times.")
        command.add_argument("--private-resume", action=argparse.BooleanOptionalAction, default=None, help="Keyed restart checkpoint; prompts locally for a passphrase and never saves source paths.")
        command.add_argument("--checkpoint", help="Resume a private checkpoint ID with reselected inputs and the same policy/passphrase.")
        command.add_argument("--export-on-completion", action="store_true", help="Explicitly request a sanitized export before a minimal-retention CLI job exits.")
    cleanup = commands.add_parser("cleanup", help="Separate operator cleanup of individually selected originals. Never automatic.")
    cleanup.add_argument("--input", action="append", required=True)
    cleanup.add_argument("--action", choices=("quarantine", "delete"), required=True)
    cleanup.add_argument("--confirm", required=True, help="Exact phrase: QUARANTINE N or DELETE N, where N is the selected file count.")
    for name in ("resume", "report", "export-diagnostics"):
        sub = commands.add_parser(name)
        sub.add_argument("--job", required=True)
        sub.add_argument("--workspace", type=Path)
        sub.add_argument("--config", type=Path)
        sub.add_argument("--test-files", action="store_true", help=argparse.SUPPRESS)
        if name == "export-diagnostics":
            sub.add_argument("--technical-json", action="store_true", help="Also write validated technical JSON batches alongside the compact text log.")
        if name == "resume":
            sub.add_argument("--dependencies", type=Path)
    gui = commands.add_parser("gui", help="Open the desktop interface.")
    gui.add_argument("--config", type=Path, help="Use a different local settings file.")
    return result


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if args.command in {"scan", "recover", "migrate", "resume", "report", "export-diagnostics"}:
            cpu_force_override = getattr(args, "migration_cpu_encoding", None)
            cpu_auto_override = getattr(args, "migration_cpu_auto", None)
            if cpu_force_override is not None and cpu_auto_override is not None:
                raise VideoMateError("invalid_arguments")
            preferences = load_preferences(args.config) if args.config else Preferences()
            if getattr(args, "preset", None):
                from .profiles import apply
                preferences = apply(preferences, args.preset)
                if preferences.workflow != {"scan": "inspect", "recover": "repair", "migrate": "migrate"}[args.command]:
                    raise VideoMateError("invalid_arguments")
            args.workspace = args.workspace or (Path(preferences.workspace) if preferences.workspace else None)
            if args.workspace is None:
                raise VideoMateError("invalid_arguments")
            for name in ("timeout", "recursive", "strategy", "profile", "force", "allow_shorter", "partial_salvage", "allow_track_loss", "max_output_mib",
                         "recovered_dir", "diagnostics_dir", "logs_dir", "write_logs", "hardware_encoding",
                         "diagnostic_logs", "cpu_threads", "max_runners", "hardware_decoding", "output_layout", "retain_history", "retain_mappings",
                         "private_resume", "interruption_recovery", "convert_all_mp4", "convert_noncompliant_hevc", "video_codec", "rate_control", "video_bitrate_kbps", "target_size_mib", "quality_crf", "max_shorter_percent", "max_source_percent", "migration_gpu_jobs", "migration_cpu_auto", "migration_cpu_encoding",
                          "size_policy", "size_tolerance_percent", "audio_normalization", "audio_bitrate_kbps", "software_preset", "mp4_faststart", "hardware_preference"):
                if hasattr(args, name) and getattr(args, name) is None:
                    setattr(args, name, getattr(preferences, name))
            if hasattr(args, "dependencies") and args.dependencies is None and preferences.dependencies:
                args.dependencies = Path(preferences.dependencies)
            if args.command in {"scan", "recover", "migrate"}:
                if args.test_files and args.sensitive is not None:
                    raise VideoMateError("invalid_arguments")
                args.sensitive = False if args.test_files else preferences.sensitive if args.sensitive is None else args.sensitive == "yes"
                storage = {name: getattr(args, name) for name in ("sensitive", "recovered_dir", "diagnostics_dir", "logs_dir", "write_logs",
                           "diagnostic_logs", "cpu_threads", "max_runners", "hardware_decoding", "output_layout", "retain_history", "retain_mappings", "private_resume")}
                storage.update(checkpoint_id=args.checkpoint, export_on_completion=args.export_on_completion)
                if args.command == "recover" and not (args.execute or args.mode == "auto"):
                    if args.checkpoint:
                        raise VideoMateError("invalid_arguments")
                    args.private_resume = storage['private_resume'] = False
                if args.command == "migrate":
                    if cpu_force_override is not None:
                        args.migration_cpu_auto = False
                    args.local_output_names = preferences.migration_local_names if args.local_output_names is None else args.local_output_names
                    args.preserve_file_times = preferences.migration_preserve_times if args.preserve_file_times is None else args.preserve_file_times
                    args.unresolved = preferences.migration_unresolved if args.unresolved is None else args.unresolved
                if args.private_resume or args.checkpoint:
                    if (not args.sensitive and args.command != "migrate") or not sys.stdin.isatty():
                        raise VideoMateError("passphrase_required")
                    import getpass
                    storage['passphrase'] = getpass.getpass("Private checkpoint passphrase (not saved): ")
        if args.command == "scan":
            if args.workspace is None:
                raise VideoMateError("invalid_arguments")
            print("Inspecting selected videos. Originals are read only.")
            return scan_local(args.input, args.workspace, dependencies=args.dependencies,
                              depth=Depth(args.depth), timeout=args.timeout, recursive=args.recursive, **storage)
        if args.command in {"recover", "migrate"}:
            start, end = duration_us(args.keep_start), duration_us(args.keep_end)
            if (args.keep_start is not None and start is None) or (args.keep_end is not None and end is None):
                raise VideoMateError("invalid_arguments")
            options = RecoveryOptions(strategy=args.strategy, profile=args.profile, force=args.force,
                                      allow_track_loss=args.allow_track_loss, allow_shorter=args.allow_shorter,
                                      partial_salvage=args.partial_salvage,
                                      max_output_bytes=args.max_output_mib * 1024 ** 2,
                                      keep_start_us=start, keep_end_us=end, hardware_encoding=args.hardware_encoding,
                                      convert_all_mp4=args.convert_all_mp4, convert_noncompliant_hevc=args.convert_noncompliant_hevc,
                                      video_codec=args.video_codec, rate_control=args.rate_control,
                                      video_bitrate_kbps=args.video_bitrate_kbps, target_size_mib=args.target_size_mib,
                                      quality_crf=args.quality_crf, max_shorter_percent=args.max_shorter_percent, max_source_percent=args.max_source_percent,
                                      size_policy=args.size_policy, size_tolerance_percent=args.size_tolerance_percent, audio_normalization=args.audio_normalization,
                                      audio_bitrate_kbps=args.audio_bitrate_kbps, software_preset=args.software_preset, mp4_faststart=args.mp4_faststart)
            options.validate()
            if args.command == "migrate":
                from .migration import migrate_local
                selected = {key: storage[key] for key in ("sensitive", "recovered_dir", "diagnostics_dir", "logs_dir", "write_logs", "diagnostic_logs", "cpu_threads", "max_runners", "hardware_decoding", "export_on_completion")}
                selected["migration_gpu_jobs"] = args.migration_gpu_jobs
                selected["migration_cpu_auto"] = args.migration_cpu_auto
                selected["migration_cpu_encoding"] = args.migration_cpu_encoding
                selected["hardware_preference"] = args.hardware_preference
                selected["hardware_calibration"] = preferences.hardware_calibration
                selected.update(interruption_recovery=args.interruption_recovery, private_resume=args.private_resume,
                                checkpoint_id=args.checkpoint, passphrase=storage.get("passphrase"))
                return migrate_local(args.input, args.workspace, dependencies=args.dependencies, recovery=options,
                                     execute=not args.preview, local_names=args.local_output_names,
                                     preserve_file_times=args.preserve_file_times, unresolved=args.unresolved,
                                     package_layout='direct', timeout=args.timeout, **selected)
            inputs = job_inputs(args.job, args.workspace, sensitive=args.sensitive) if args.job else args.input
            return scan_local(inputs, args.workspace, dependencies=args.dependencies, timeout=args.timeout,
                              recursive=args.recursive, recovery=options, execute=args.execute or args.mode == "auto", **storage)
        if args.command == "resume":
            return resume_local(args.job, args.workspace, dependencies=args.dependencies)
        if args.command == "cleanup":
            import threading
            from .cleanup import manage_originals
            manage_originals(args.input, args.action, args.confirm, cancel_event=threading.Event())
            return 0
        if args.command in {"report", "export-diagnostics"}:
            return report_local(args.job, args.workspace, export=args.command == "export-diagnostics", technical_json=getattr(args, "technical_json", False))
        if args.command == "gui":
            from .gui import launch
            return launch(config_path=args.config)
        if args.command == "doctor":
            get_schema()
            from .setup_local import check_backend
            try:
                bundle = check_backend(args.dependencies)
            except VideoMateError:
                bundle = None
            print(json.dumps({"version": __version__, "stage": "development",
                              "schema": "available", "runtime_dependencies": "standard_library",
                              "ffmpeg_bundle": "verified" if bundle else "missing_or_invalid",
                              "ffmpeg_version": bundle["version"] if bundle else None,
                              "required_encoders": "available" if bundle else "unverified",
                              "inspection": "available" if bundle else "needs_dependencies",
                              "recovery": "available" if bundle else "needs_dependencies",
                              "sensitive_treatment": "available", "os_sandbox": "not_implemented",
                              "workspace_encryption": "not_implemented"}, indent=2))
            return 0 if bundle else 2
        if args.command == "init":
            # Source checkout path only. Zipapp's package directory is similarly excluded.
            create_workspace(Path(args.workspace), Path(__file__).resolve().parents[2])
            print("Workspace ready for saved jobs and results.")
            return 0
        if args.command == "demo":
            results, export = run_demo()
            if args.export:
                try:
                    with open(args.export, "xb") as output:
                        output.write(export)
                except FileExistsError:
                    raise VideoMateError("output_exists") from None
            print("Synthetic demonstration: scripted backend responses; no real media was read.")
            for i, result in enumerate(results, 1):
                print(f"sample-{i}: {result.integrity}; {recovery_suggestion(result)}")
            if args.export:
                print("Synthetic diagnostic export created. Identifiers use a public test key.")
            return 1  # Expected: simulated damaged/unreadable inputs require attention.
        if args.command in {"validate-export", "support-summary"}:
            with open(args.input, "rb") as source:
                data = source.read(MAX_EXPORT_BYTES + 1)
            document = load_json(data)
            validate_export(document)
            if args.command == "support-summary":
                from .support import support_summary
                print(json.dumps(support_summary(document), indent=2))
            else:
                print("Diagnostic structure and semantic checks passed. No contents displayed.")
            return 0
        raise VideoMateError("invalid_arguments")
    except VideoMateError as error:
        print(str(error), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(str(VideoMateError("cancelled")), file=sys.stderr)
        return 130
    except OSError:
        print(str(VideoMateError("io_error")), file=sys.stderr)
        return 2
    except Exception:
        # Never print arbitrary exception text, traceback, command line or locals.
        print(str(VideoMateError("internal_error")), file=sys.stderr)
        return 2
