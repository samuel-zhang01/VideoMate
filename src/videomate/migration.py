"""Operator-only folder migration. All assistant tests use newly generated trees."""
import hashlib
import json
import os
import shutil
import stat
import sys
import threading
import time
import unicodedata
from itertools import chain, count
from pathlib import Path
from uuid import uuid4

from .backend import FFmpegBackend
from .dependencies import load_bundle
from .discovery import EXTENSIONS
from .errors import MESSAGES, VideoMateError
from .event_log import EventLog
from .execution import automatic_cpu_lane_allowed, cpu_budget, hybrid_migration_slots, migration_slots, parallel_inspect, resource_slot
from .hardware import ENCODERS, select_decoder, select_encoder, codec_routes
from .encoding import candidate_limit
from .inspection import Inspector, _fingerprint
from .jobs import job_lock
from .models import Depth, ScanResult
from .policy import LocalFileScope, _non_synced_location, plain_local_path
from .preferences import Preferences, storage_directory
from .progress import BatchProgress
from .private_state import MemoryJob, finalize_session, failure_code, session_issue
from .recovery import RecoveryEngine, RecoveryOptions, publish
from .runner import Runner
from .publication import filesystem_reason, qualify_publication

COPY_FAILURES = {"input_changed", "disk_limit", "io_error", "source_read_failed", "output_write_failed",
                 "copy_verification_failed", "output_publish_failed", "output_access_denied",
                 "output_filesystem_unsupported", "output_path_too_long", "output_busy", "output_exists", "backend_unavailable"}


def path_key(path):
    return unicodedata.normalize("NFC", path.as_posix()).casefold()


def validate_layout(inputs, workspace, output, source_root, *, excluded=()):
    """Check folder roles without inspecting any selected directory or file."""
    if len(inputs) != 1:
        raise VideoMateError("migration_selection")
    root = Path(os.path.abspath(inputs[0]))
    boundaries = [(workspace, "migration_workspace_overlap"), (output, "migration_output_overlap"),
                  (source_root, "migration_software_overlap"), *((p, "migration_storage_overlap") for p in excluded)]
    for path, reason in boundaries:
        boundary = Path(os.path.abspath(path))
        if root == boundary or root in boundary.parents or boundary in root.parents:
            raise VideoMateError(reason)
    return root


def eligible_path(path, source_root):
    if str(path).startswith(("\\\\", "//")):
        raise VideoMateError("migration_network")
    try:
        path = plain_local_path(path)
    except VideoMateError:
        raise VideoMateError("migration_link") from None
    try:
        _non_synced_location(path, source_root)
    except VideoMateError:
        raise VideoMateError("migration_source_location") from None
    return path


def inventory(inputs, workspace, output, source_root, *, excluded=(), cancel=None, progress=None):
    """Fail with a precise path-free reason; never silently omit source entries."""
    root = validate_layout(inputs, workspace, output, source_root, excluded=excluded)
    files, directories, keys = [], [], set()
    def fail(_):
        raise VideoMateError("migration_access")
    try:
        root = eligible_path(root, source_root)
        if not root.is_dir():
            raise VideoMateError("migration_not_folder")
        device = root.stat().st_dev
        for current, folders, names in os.walk(root, topdown=True, followlinks=False, onerror=fail):
            if cancel and cancel.is_set():
                raise KeyboardInterrupt()
            folders.sort()
            for name in [*folders, *sorted(names)]:
                if cancel and cancel.is_set():
                    raise KeyboardInterrupt()
                path = eligible_path(Path(current) / name, source_root)
                relative = path.relative_to(root)
                key = path_key(relative)
                if key in keys:
                    raise VideoMateError("migration_name_conflict")
                info = path.stat()
                if info.st_dev != device or os.path.ismount(path):
                    raise VideoMateError("migration_mount")
                keys.add(key)
                if stat.S_ISDIR(info.st_mode):
                    directories.append(relative)
                else:
                    if not stat.S_ISREG(info.st_mode):
                        raise VideoMateError("migration_special_file")
                    files.append((path, relative, path.suffix.lower() in EXTENSIONS))
                if progress:
                    progress(len(files))
    except OSError:
        raise VideoMateError("migration_access") from None
    if not files:
        raise VideoMateError("migration_empty")
    return files, directories


def digest(path, cancel):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            if cancel.is_set():
                raise KeyboardInterrupt()
            value.update(block)
    return value.digest()


def preserve_times(source_info, target, enabled):
    if not enabled:
        return "not_requested"
    try:
        os.utime(target, ns=(source_info.st_atime_ns, source_info.st_mtime_ns))
        return "preserved"
    except OSError:
        return "not_preserved"


def verified_copy(source, destination, staging, scope, cancel, *, expected, keep_times, before_publish=None):
    temporary = plain_local_path(staging / (uuid4().hex + ".part"))
    checksum = hashlib.sha256()
    stage = "source_read_failed"
    try:
        scope.authorize(source)
        if _fingerprint(source) != tuple(expected or ()):
            raise VideoMateError("input_changed")
        info = source.stat()
        stage = "output_write_failed"
        if shutil.disk_usage(staging).free < info.st_size + 64 * 1024 ** 2:
            raise VideoMateError("disk_limit")
        stage = "source_read_failed"
        with source.open("rb") as incoming:
            stage = "output_write_failed"
            with temporary.open("xb") as outgoing:
                while True:
                    if cancel.is_set():
                        raise KeyboardInterrupt()
                    stage = "source_read_failed"
                    block = incoming.read(1024 * 1024)
                    stage = "output_write_failed"
                    if not block:
                        break
                    checksum.update(block)
                    outgoing.write(block)
        stage = "copy_verification_failed"
        if digest(temporary, cancel) != checksum.digest():
            raise VideoMateError("copy_verification_failed")
        stage = "source_read_failed"
        scope.authorize(source)
        if _fingerprint(source) != tuple(expected) or cancel.is_set():
            if cancel.is_set():
                raise KeyboardInterrupt()
            raise VideoMateError("input_changed")
        stage = "output_write_failed"
        destination = plain_local_path(destination)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = preserve_times(info, temporary, keep_times)
        if before_publish:
            before_publish(temporary, destination, checksum.digest(), metadata)
        publish(temporary, destination)
        return metadata
    except OSError as error:
        raise VideoMateError(filesystem_reason(error, stage)) from None
    finally:
        # Exact session-created candidate, never a source or discovered path.
        if temporary.exists():
            plain_local_path(temporary).unlink()


def process_file(backend, item, *, options, scope, staging, package, source_root, keep_times, unresolved, copy_gate, journal=None):
    """Each worker owns its backend/results. Journals, logs and UI stay on caller."""
    number, source, relative, is_video, stem = item
    cancel = backend.runner.cancel_event
    result = ScanResult(state="failed", integrity="unreadable")
    migration = {"input_kind": "video" if is_video else "other", "action": "failed",
                 "copy_check": "not_run", "timestamps": "not_requested", "reason": "none"}
    def copy(target, action):
        def intent(candidate, destination, checksum, metadata):
            migration.update(action=action, copy_check="passed", timestamps=metadata)
            result.technical["migration"] = migration
            if journal:
                journal.stage(item, result, destination, checksum, checksum)

        with resource_slot(copy_gate, cancel):
            migration["copy_check"] = "failed"
            return verified_copy(source, target, staging, scope, cancel,
                                 expected=result.fingerprint, keep_times=keep_times, before_publish=intent)
    try:
        scope.authorize(source)
        result = Inspector(backend, scope).inspect(source) if is_video else ScanResult(
            depth=Depth.QUICK, integrity="quick_check_only", fingerprint=_fingerprint(source))
        result.technical["source_size"] = result.fingerprint[2] if result.fingerprint else 0
        compliant_hevc_preset = (options.convert_noncompliant_hevc and source.suffix.lower() == ".mp4"
                                 and result.container == "mp4_mov"
                                 and any(s["kind"] == "video" for s in result.streams)
                                 and all(s["codec"] in {"h264", "hevc"} for s in result.streams if s["kind"] == "video"))
        if not is_video or (result.integrity == "no_errors_detected" and (not options.convert_all_mp4)
                            and (not options.convert_noncompliant_hevc or compliant_hevc_preset)):
            migration["timestamps"] = copy(package / relative, "copied_healthy" if is_video else "copied_other")
            migration.update(action="copied_healthy" if is_video else "copied_other", copy_check="passed")
            result.technical["private_package_bytes"] = result.technical["source_size"]
        else:
            def repair_intent(candidate, destination, recovered, checksum):
                from .migration_resume import file_hash
                action = "salvaged_partial" if "partial_salvage" in recovered.recovery.get("losses", []) else "repaired"
                migration.update(action=action, timestamps=preserve_times(source.stat(), candidate, keep_times))
                recovered.technical["migration"] = migration
                source_checksum = file_hash(source, cancel)
                if _fingerprint(source) != tuple(recovered.fingerprint):
                    raise VideoMateError("input_changed")
                journal.stage(item, recovered, destination, source_checksum, checksum)
            engine = RecoveryEngine(backend, scope, staging, package / relative.parent, source_root, output_stem=stem,
                                    output_hash=journal is not None, publication_hook=repair_intent if journal else None)
            engine.recover(source, result, options)
            if result.recovery.get("private_failure_code"):
                raise VideoMateError(result.recovery["private_failure_code"])
            if result.recovery["recovery_state"] not in {"verified", "verified_with_losses"}:
                from .migration_resume import TRANSIENT
                operational = next((d['error_code'] for d in reversed(result.diagnostics) if d['error_code'] in TRANSIENT), None)
                if operational:
                    raise VideoMateError(operational)
            if result.recovery["recovery_state"] in {"verified", "verified_with_losses"}:
                action = "salvaged_partial" if "partial_salvage" in result.recovery.get("losses", []) else "repaired"
                migration.update(action=action, timestamps=preserve_times(source.stat(), Path(result.recovery["private_output"]), keep_times))
                result.technical["private_package_bytes"] = result.recovery["private_output_bytes"]
            elif unresolved == "exclude":
                migration.update(action="excluded_unresolved", reason="recovery_unverified")
            else:
                target = (package if unresolved == "copy" else package.with_name(package.name + ".review")) / relative
                migration["timestamps"] = copy(target, "copied_unresolved" if unresolved == "copy" else "retained_for_review")
                migration.update(action="copied_unresolved" if unresolved == "copy" else "retained_for_review", copy_check="passed", reason="recovery_unverified")
                result.technical["private_package_bytes" if unresolved == "copy" else "private_review_bytes"] = result.technical["source_size"]
    except (VideoMateError, OSError) as error:
        code = error.code if isinstance(error, VideoMateError) else "io_error"
        if code in {"worker_cleanup_failed", "checkpoint_invalid", "checkpoint_sources_changed", "resume_storage_changed", "resume_output_conflict"}:
            raise
        migration.update(action="failed", reason=code if code in COPY_FAILURES else "io_error")
    result.technical["migration"] = migration
    return result


def repair_stem(relative, reserved):
    for number in count():
        stem = relative.stem + ("" if number == 0 else f".repaired-{number}")
        alternatives = [relative.parent / (stem + suffix) for suffix in (".mkv", ".mp4")]
        if all(path_key(p) not in reserved or p == relative for p in alternatives):
            reserved.update(path_key(p) for p in alternatives)
            return stem


def migration_summary(phase, planned, counts, reason="none", stage="none"):
    processed = sum(counts.values())
    published = sum(counts[k] for k in ("copied_healthy", "copied_other", "repaired", "salvaged_partial", "copied_unresolved", "retained_for_review"))
    return {"state": phase, "planned_files": planned, "processed_files": processed,
            "published_files": published, "excluded_files": counts["excluded_unresolved"],
            "partial_files": counts["salvaged_partial"],
            "failed_files": counts["failed"], "unprocessed_files": max(0, planned - processed),
            "stop_reason": reason, "stop_stage": stage, "pipeline_issues": []}


def emit_summary(summary, emit):
    emit(f"Migration totals: {summary['processed_files']}/{summary['planned_files']} processed; "
         f"{summary['published_files']} published (including {summary['partial_files']} partial); {summary['excluded_files']} excluded; "
         f"{summary['failed_files']} failed; {summary['unprocessed_files']} not processed.")


def write_status(package, phase, planned, counts, timestamp_warnings, sizes=None):
    if phase == "finished":
        phase = "incomplete" if counts["failed"] or sum(counts.values()) != planned else "needs_review" if any(counts[k] for k in ("salvaged_partial", "retained_for_review", "excluded_unresolved", "copied_unresolved")) else "complete"
    output_files = sum(counts[k] for k in ("copied_healthy", "copied_other", "repaired", "salvaged_partial", "copied_unresolved"))
    payload = {"schema_version": 1, "workflow": "migration", "state": phase,
               "planned_files": planned, "completed_files": sum(counts.values()) - counts["failed"], "counts": counts,
               "output_files": output_files,
               "omitted_from_output": planned - output_files,
               "timestamp_warnings": timestamp_warnings}
    if sizes is not None:
        payload.update(sizes)
    temporary = package.parent / ("status-" + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        os.replace(temporary, plain_local_path(package.with_name(package.name + ".status.json")))
    finally:
        if temporary.exists():
            temporary.unlink()
    return phase


def migrate_local(inputs, workspace, **kwargs):
    from .local_scan import workspace_path
    from .execution import processing_session
    if type(kwargs.get('execute', True)) is not bool:
        raise VideoMateError('invalid_arguments')
    if kwargs.get('sensitive', True) and not kwargs.get('local_names', False) and kwargs.get('execute', True):
        raise VideoMateError('migration_names_required')
    workspace = workspace_path(workspace)
    with processing_session(workspace):
        return _migrate_local(inputs, workspace, **kwargs)


def _migrate_local(inputs, workspace, *, dependencies=None, recovery=None, execute=True,
                  sensitive=True, local_names=False, preserve_file_times=True, unresolved="exclude", recovered_dir="",
                  diagnostics_dir="", logs_dir="", write_logs=False, diagnostic_logs=False,
                  cpu_threads=0, max_runners=0, migration_gpu_jobs=2, migration_cpu_auto=True, migration_cpu_encoding=False,
                  hardware_decoding=True, hardware_preference="auto", hardware_calibration=None,
                  timeout=3600, export_on_completion=False,
                  interruption_recovery=True, private_resume=False, checkpoint_id=None, passphrase=None, retry_id=None,
                  emit=print, cancel_event=None, progress=None, package_layout='versioned'):
    from .local_scan import export_job, workspace_path
    Preferences(sensitive=sensitive, migration_local_names=local_names, migration_preserve_times=preserve_file_times, migration_unresolved=unresolved,
                recovered_dir=recovered_dir, diagnostics_dir=diagnostics_dir, logs_dir=logs_dir, write_logs=write_logs,
                diagnostic_logs=diagnostic_logs, cpu_threads=cpu_threads, max_runners=max_runners,
                migration_gpu_jobs=migration_gpu_jobs, migration_cpu_auto=migration_cpu_auto,
                migration_cpu_encoding=migration_cpu_encoding,
                hardware_decoding=hardware_decoding, hardware_preference=hardware_preference,
                hardware_calibration={} if hardware_calibration is None else hardware_calibration,
                timeout=timeout).validate()
    if sensitive and not local_names and execute:
        raise VideoMateError("migration_names_required")
    if (type(interruption_recovery) is not bool or type(private_resume) is not bool
            or type(execute) is not bool or type(export_on_completion) is not bool
            or (recovery is not None and not isinstance(recovery, RecoveryOptions))):
        raise VideoMateError("settings_invalid")
    if package_layout not in {'direct', 'versioned'}:
        raise VideoMateError('invalid_arguments')
    options = recovery or RecoveryOptions()
    options.validate()
    if options.keep_start_us is not None:
        raise VideoMateError("invalid_arguments")
    source_root = Path(__file__).absolute().parents[2]
    if workspace is not None:
        validate_layout(inputs, workspace, Path(recovered_dir) if recovered_dir else Path(workspace) / "recovered", source_root,
                        excluded=[Path(p) for p in (diagnostics_dir, logs_dir) if p])
    workspace = workspace_path(workspace)
    output = plain_local_path(Path(recovered_dir) if recovered_dir else workspace / "recovered")
    _non_synced_location(output, source_root)
    cancel = cancel_event or threading.Event()
    tracker = BatchProgress(progress)
    tracker.update("discovering", force=True)
    files, directories = inventory(inputs, workspace, output, source_root,
        excluded=[plain_local_path(Path(p)) for p in (diagnostics_dir, logs_dir) if p], cancel=cancel,
        progress=lambda found: tracker.update("discovering", discovered=found))
    tracker.plan(len(files))
    videos = sum(item[2] for item in files)
    emit(f"Migration plan: {len(files)} files, {videos} video inputs, {len(files) - videos} other files, {len(directories)} folders.")
    policies = {"exclude": "exclude from the output and report omissions", "copy": "copy unchanged into the matching output location", "review": "copy into a separate review folder"}
    from .profiles import describe_policy
    from dataclasses import asdict
    policy_preferences = Preferences(workflow="migrate", migration_unresolved=unresolved,
        migration_cpu_auto=migration_cpu_auto, migration_cpu_encoding=migration_cpu_encoding,
        **{k: v for k, v in asdict(options.resolved()).items() if k in Preferences.__dataclass_fields__})
    emit(describe_policy(policy_preferences))
    emit("Other files are copied. Unresolved policy: " + policies[unresolved] + ". Sources remain unchanged.")
    from .migration_resume import SESSION_RETRIES
    retry_state = SESSION_RETRIES.get(retry_id) if retry_id else None
    if retry_id and not retry_state:
        raise VideoMateError('retry_session_unavailable')
    if retry_state:
        if retry_state.get('mode') == 'continue':
            emit(f"Continue interrupted migration: {retry_state['unresolved']} inputs remain unpublished. Existing outputs will be verified before reuse.")
        else:
            emit(f"Retry unresolved: {retry_state['unresolved']} previous exclusions/failures. Existing outputs will be verified before reuse; unchanged unresolved copies are retained.")
        emit('Previous policy: ' + retry_state['policy'])
        emit('Requested policy: ' + describe_policy(policy_preferences))
    if not execute:
        emit("Preview only. No output package was created.")
        tracker.update("preview", force=True)
        return 0
    bundle = load_bundle(dependencies)
    output = storage_directory(recovered_dir, workspace / "recovered")
    if package_layout == 'direct' and not (checkpoint_id or retry_id):
        if any(output.iterdir()) or any(p.exists() for p in (output.with_name(output.name + '.status.json'),
                                                               output.with_name(output.name + '.owner'),
                                                               output.with_name(output.name + '.review'))):
            raise VideoMateError('migration_output_not_empty')
    settings = {"scope": "local_files", "sensitive": sensitive, "retain_mappings": False,
                "recovered_dir": recovered_dir, "diagnostics_dir": diagnostics_dir, "logs_dir": logs_dir,
                "write_logs": write_logs, "diagnostic_logs": diagnostic_logs}
    from dataclasses import asdict
    from .migration_resume import MigrationJournal, retry_queue, sweep_staging, SESSION_RETRIES
    retry_state = SESSION_RETRIES.get(retry_id) if retry_id else None
    if retry_id and not retry_state:
        raise VideoMateError('retry_session_unavailable')
    if retry_state:
        if checkpoint_id or private_resume:
            raise VideoMateError('checkpoint_policy_changed')
    if checkpoint_id:
        private_resume = True
    journal = MigrationJournal(workspace, files, directories, Path(inputs[0]).absolute(), output,
        {"recovery": asdict(options), "unresolved": unresolved, "keep_times": preserve_file_times,
         "sensitive": sensitive, "local_names": local_names, "backend": bundle.version}, cancel,
        persistent=private_resume, passphrase=passphrase, identifier=checkpoint_id, version=bundle.version,
        retry_state=retry_state, package_layout=package_layout) if interruption_recovery or private_resume or retry_state else None
    paths = [item[0] for item in files]
    try:
        job = MemoryJob.create(workspace, paths, settings, identifier=journal.id if journal else None)
    except BaseException:
        if journal:
            journal.close()
        raise
    package = journal.package if journal else output if package_layout == 'direct' else output / ("migration-" + job.id)
    fingerprints, events, initialized = [None] * len(files), None, False
    counts = {name: 0 for name in ("copied_healthy", "copied_other", "repaired", "salvaged_partial", "retained_for_review", "excluded_unresolved", "copied_unresolved", "failed")}
    timestamp_warnings, had_recovery, finished = 0, False, False
    sizes = {"source_bytes_processed": 0, "package_bytes": 0, "review_bytes": 0}
    stage = "prepare_output"
    hardware_report = None
    published_numbers = set()
    try:
        with job_lock(job.directory):
            if journal:
                journal.initialize_package()
            else:
                plain_local_path(package).mkdir(mode=0o700, exist_ok=package == output)
            initialized = True
            staging = plain_local_path((output.parent / ('candidates-' + uuid4().hex)) if package == output
                                       else (output / ".candidates" / ("candidates-" + uuid4().hex)))
            staging.mkdir(mode=0o700, parents=True)
            job.own_directory(staging)
            qualify_publication(staging, package)
            scratch = job.directory / "scratch"
            scratch.mkdir(mode=0o700)
            write_status(package, "building", len(files), counts, timestamp_warnings, sizes)
            for relative in directories:
                if cancel.is_set():
                    raise KeyboardInterrupt()
                plain_local_path(package / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
            scope = LocalFileScope(frozenset(paths), source_root)
            budget = cpu_budget(cpu_threads)
            available_budget = cpu_budget(0)
            auto_cpu_lane = automatic_cpu_lane_allowed(budget, available_budget, migration_cpu_auto)
            allow_cpu_lane = migration_cpu_encoding or auto_cpu_lane
            slots, copy_lane = migration_slots(budget, videos, len(files) - videos, max_runners)
            gate, copy_gate = threading.Semaphore(migration_gpu_jobs), threading.Semaphore(1)
            workers = []
            for slot, threads in enumerate(slots):
                work = scratch / ("worker-" + str(slot + 1))
                work.mkdir(mode=0o700)
                workers.append(FFmpegBackend(bundle.ffmpeg, bundle.ffprobe, work,
                    Runner(timeout=timeout, cancel_event=cancel, cleanup_blocked=job.cleanup_blocked), scope=scope, threads=threads, hardware_gate=gate))
            emit("Job: " + job.id)
            emit("Migration restart checkpoint enabled. Reselect the same source/output and use this job ID and passphrase to resume." if private_resume else
                 "Migration reconnect recovery is session-only. Export diagnostics before closing; enable Private resume before starting for restart recovery.")
            stage = "hardware_check"
            decoders = select_decoder(workers[0], all_ready=True) if videos and hardware_decoding else ("software",)
            resolved = options.resolved()
            software_encoder = "libx265" if resolved.video_codec == "hevc" else "libx264"
            encoders = select_encoder(workers[0], all_ready=True, codec=resolved.video_codec) if videos and resolved.hardware_encoding and resolved.profile == "compatible_sdr" else (software_encoder,)
            from .hardware import qualify_codec_routes
            routes = qualify_codec_routes(workers[0], codec_routes(decoders, encoders)) if resolved.profile == "compatible_sdr" else (("software", "ffv1"),)
            from .hardware import qualify_devices
            devices = qualify_devices(workers[0], routes)
            from .calibration import calibrated_jobs, lane_routes, rank_devices, route_id
            devices, calibrated_speeds = rank_devices(devices, preference=hardware_preference,
                calibrations=hardware_calibration, codec=resolved.video_codec, bundle=bundle)
            calibrated_limits = calibrated_jobs(hardware_calibration, resolved.video_codec, bundle)
            # Automatic admission requires spare logical CPUs; neither mode displaces a qualified GPU route.
            gpu_devices = tuple(route for route in devices if route[1] in ENCODERS[resolved.video_codec])
            calibrated_extra = min(2, sum(max(0, min(migration_gpu_jobs,
                calibrated_limits.get(route_id(route), 1)) - 1) for route in gpu_devices)) if calibrated_speeds else 0
            base_limit = max(4, len(gpu_devices) + int(bool(len(files) - videos)) +
                int(allow_cpu_lane and bool(gpu_devices)))
            runner_limit = max_runners or base_limit + min(calibrated_extra, max(0, 6 - base_limit))
            slots, copy_lane, cpu_lane = hybrid_migration_slots(
                budget, videos, len(files) - videos, runner_limit, len(gpu_devices), allow_cpu_lane)
            from .hardware_activity import HardwareActivity, report as activity_report
            activity = HardwareActivity()
            device_gates = {(route[1], route[2]): activity.gate(index,
                min(migration_gpu_jobs, calibrated_limits.get(route_id(route), migration_gpu_jobs)))
                for index, route in enumerate(devices, 1)}
            selection = "disabled" if not hardware_decoding else "preservation_software" if resolved.profile != "compatible_sdr" else "qualified" if any(d != "software" for d, _, _ in devices) else "decoder_unavailable" if decoders == ("software",) else "combined_route_failed"
            hardware_report = lambda: activity_report(activity, devices, device_gates, hardware_decoding, resolved.hardware_encoding, selection)
            emit("Hardware decode selection: " + selection + ". Actual route usage is recorded in the job summary.")
            workers = []
            lane_devices = gpu_devices if cpu_lane is not None else devices
            route_limits = {route_id(route): min(migration_gpu_jobs,
                calibrated_limits.get(route_id(route), migration_gpu_jobs)) for route in lane_devices}
            ranked_lanes = lane_routes(lane_devices, len(slots) - int(copy_lane) - int(cpu_lane is not None),
                                       calibrated_speeds, hardware_preference, route_limits)
            for index, threads in enumerate(slots):
                work = scratch / ("worker-" + str(index + 1))
                work.mkdir(mode=0o700, exist_ok=True)
                is_cpu_lane = index == cpu_lane
                assigned = ranked_lanes[index] if index < len(ranked_lanes) else lane_devices
                decoder, encoder, device = (("software", software_encoder, None) if is_cpu_lane
                                             else assigned[0])
                backend = FFmpegBackend(bundle.ffmpeg, bundle.ffprobe, work,
                    Runner(timeout=timeout, cancel_event=cancel, cleanup_blocked=job.cleanup_blocked), scope=scope,
                    threads=threads, hardware_gate=None if is_cpu_lane else device_gates[(encoder, device)])
                backend.decoder, backend.gpu_index = decoder, device
                backend.hardware_routes = () if is_cpu_lane else assigned
                backend.hardware_route_codec = resolved.video_codec
                backend.hardware_route_gates = {} if is_cpu_lane else device_gates
                setattr(backend, f"_ready_{resolved.video_codec}_encoder", encoder)
                backend._codec_route_checks = {(decoder, encoder): True}
                workers.append(backend)
            emit(f"Migration queue: {len(workers)} parallel files; {budget} shared codec threads; up to {migration_gpu_jobs} GPU jobs per qualified device (possibly reduced by synthetic calibration); one verified copy at a time.")
            emit("Encoder routing: " + ("synthetic calibration" if calibrated_speeds else "qualified default order") +
                 (" with local preferred vendor" if hardware_preference != "auto" else "") + ".")
            if migration_cpu_auto or migration_cpu_encoding:
                mode = 'forced' if migration_cpu_encoding else 'automatic'
                reason = ('requires at least 16 available/budgeted codec threads' if not allow_cpu_lane else
                          'requires a qualified GPU route, enough video inputs and at least two codec threads per video lane')
                emit(f"CPU encoding lane ({mode}): {'active with ' + str(slots[cpu_lane]) + ' codec threads' if cpu_lane is not None else 'unavailable (' + reason + ')'}. Available CPU budget: {available_budget}; requested codec budget: {budget}.")
            emit("Qualified codec routes: " + ", ".join(d + " / " + e for d, e, _ in devices) + ". Preservation uses software FFV1.")
            emit("Full integrity checks use software decoding: GPU concealment can hide packet damage. Hardware remains preferred for eligible repairs.")
            if resolved.profile == "preserve_decoded_samples":
                emit("Preservation repair can be much larger than the source. Compatible SDR trades quality for smaller, hardware-eligible outputs.")
            tracker.begin()
            stage = "write_event_log"
            events = EventLog(job, settings)
            events.write("started")
            reserved = {path_key(relative) for _, relative, _ in files} | {path_key(relative) for relative in directories}
            items = [(number, source, relative, is_video, repair_stem(relative, reserved) if is_video else None)
                     for number, (source, relative, is_video) in enumerate(files, 1)]
            if journal:
                journal.revalidate_outputs = lambda: journal.revalidate_published(item for item in items if item[0] in published_numbers)
                if retry_state:
                    journal.revalidate_published(item for item in items if item[0] in retry_state['published'])
            if copy_lane:
                video_queue = iter(item for item in items if item[3])
                other_queue = iter(item for item in items if not item[3])
                queues = [video_queue] * (len(workers) - 1) + [chain(other_queue, video_queue)]
            else:
                queues = None
            active = 0
            def started(item):
                nonlocal active, stage
                active += 1
                stage = "write_event_log"
                events.write("input_started", item[0])
                stage = "process_files"
                emit(f"Starting input ID {item[0]}; completed {sum(counts.values())}/{len(files)} files.")
                tracker.update("processing", active=active, force=True)
            def process(backend, item):
                if journal:
                    try:
                        with resource_slot(copy_gate, backend.runner.cancel_event):
                            restored = journal.restore(item)
                        if restored is not None:
                            return restored
                    except OSError:
                        failed = ScanResult(state="failed", integrity="unreadable")
                        failed.technical["migration"] = {"input_kind": "video" if item[3] else "other", "action": "failed",
                            "copy_check": "not_run", "timestamps": "not_requested", "reason": "io_error"}
                        return failed
                return process_file(backend, item, options=options, scope=scope, staging=staging,
                    package=package, source_root=source_root, keep_times=preserve_file_times,
                    unresolved=unresolved, copy_gate=copy_gate, journal=journal)
            def rediscover():
                nonlocal active
                active = 0
                discovered, found_directories = inventory(inputs, workspace, output, source_root, cancel=cancel)
                if discovered != files or found_directories != directories:
                    raise VideoMateError("checkpoint_sources_changed")
                journal.revalidate_outputs()
            def retry_notice(result, number):
                nonlocal active
                active -= 1
                reason = result.technical["migration"]["reason"]
                events.issue("process_files", reason if reason in MESSAGES else "io_error")
            iterator = retry_queue(items, workers, process, started, cancel, journal, rediscover, emit, tracker,
                                   on_retry=retry_notice, copy_lane=copy_lane, sweep=lambda: sweep_staging(job, staging, emit)) if journal and interruption_recovery else parallel_inspect(items, workers, process, started, cancel, queues=queues, drain_on_cancel=True)
            stage = "process_files"
            last_status = time.monotonic()
            try:
                for item, result in iterator:
                    number = item[0]
                    active -= 1
                    result.technical["processing"] = {"cpu_budget": budget, "runners": len(workers),
                        "hardware_decoding": "enabled" if hardware_decoding else "disabled"}
                    migration = result.technical["migration"]
                    job.save(number, "done", result)
                    fingerprints[number - 1] = result.fingerprint
                    had_recovery |= bool(result.recovery)
                    counts[migration["action"]] += 1
                    if migration['action'] in {'copied_healthy', 'copied_other', 'repaired', 'salvaged_partial', 'copied_unresolved', 'retained_for_review'}:
                        published_numbers.add(number)
                    timestamp_warnings += migration["timestamps"] == "not_preserved"
                    sizes["source_bytes_processed"] += result.technical.get("source_size", 0)
                    sizes["package_bytes"] += result.technical.get("private_package_bytes", 0)
                    sizes["review_bytes"] += result.technical.get("private_review_bytes", 0)
                    # Persist aggregate status at most twice per second. A crash
                    # still leaves a building state; final/cancelled states flush.
                    if time.monotonic() - last_status >= 0.5:
                        stage = "write_status"
                        try:
                            write_status(package, "building", len(files), counts, timestamp_warnings, sizes)
                        except OSError:
                            if not journal or not interruption_recovery:
                                raise
                            emit("Package status write delayed [io_error]; recorded results remain in this session. Storage will be checked before finalization.")
                        stage = "process_files"
                        last_status = time.monotonic()
                    stage = "write_event_log"
                    events.write("input_finished", number)
                    events.details(result, number)
                    stage = "process_files"
                    emit(f"input-{number}: {result.integrity}; {migration['action']}")
                    if migration["action"] == "failed":
                        emit(f"input-{number}: {MESSAGES[migration['reason']]} [{migration['reason']}]")
                    if result.recovery:
                        for attempt_number, attempt in enumerate(result.recovery.get("attempts", []), 1):
                            details = ", ".join(attempt.get("verification_issues", [])) or attempt["reason"]
                            emit(f"input-{number}: attempt {attempt_number} {attempt['strategy']} / {attempt['encoder']}: {attempt['outcome']}; {details}.")
                        if result.recovery["recovery_state"] == "blocked":
                            reason = next((d['error_code'] for d in reversed(result.diagnostics) if d['stage'] == 'plan'), 'recovery_blocked')
                            emit(f"input-{number}: {MESSAGES.get(reason, MESSAGES['recovery_blocked'])} [{reason}]")
                        source_mib = result.technical.get("source_size", 0) / 1024**2
                        cap = candidate_limit(result, options)
                        cap_note = f"temporary cap {cap / 1024**2:.2f} MiB" if cap else "temporary size cap off"
                        output_bytes = result.recovery.get("private_output_bytes")
                        output_note = f"output {output_bytes / 1024**2:.2f} MiB" if output_bytes is not None else "no verified output"
                        emit(f"input-{number}: source {source_mib:.2f} MiB; {cap_note}; {output_note}.")
                        if "size_above_target" in result.recovery.get("notes", []):
                            emit(f"input-{number}: best-effort size target was exceeded; output passed full verification and was published with a size warning.")
                        elif "size_target_exceeded" in result.recovery.get("notes", []):
                            emit(f"input-{number}: finished output exceeded the selected size tolerance after adjustment; no oversized repair was published.")
                        elif "size_below_target" in result.recovery.get("notes", []):
                            emit(f"input-{number}: verified output is smaller than the size target; no padding was added.")
                        if any(d["limit_reason"] == "candidate_limit" for d in result.diagnostics):
                            emit(f"input-{number}: optional temporary size cap reached; raise or disable it in Settings/Options. Finished-size targets are separate.")
                    tracker.update("processing", completed=sum(counts.values()), active=active)
            finally:
                iterator.close()  # Join every worker before session candidates are removed.
            if journal and interruption_recovery:
                if journal.wait_storage(emit, tracker):
                    journal.revalidate_outputs()
            tracker.update("checking", force=True)
            stage = "final_source_check"
            def final_check():
                final_files, final_directories = inventory(inputs, workspace, output, source_root, cancel=cancel)
                if final_files != files or final_directories != directories:
                    return False
                for (source, _, _), fingerprint in zip(files, fingerprints):
                    if cancel.is_set():
                        raise KeyboardInterrupt()
                    if _fingerprint(source) != tuple(fingerprint or ()):
                        return False
                return True
            if journal and interruption_recovery:
                unchanged = journal.storage_operation(final_check, emit, tracker)
            else:
                try:
                    unchanged = final_check()
                except (VideoMateError, OSError):
                    unchanged = False
            stage = "write_status"
            finish_status = lambda: write_status(package, "finished" if unchanged else "incomplete", len(files), counts, timestamp_warnings, sizes)
            phase = journal.storage_operation(finish_status, emit, tracker) if journal and interruption_recovery else finish_status()
            job.migration_summary = migration_summary(phase, len(files), counts, "input_changed" if not unchanged else "none", "final_source_check" if not unchanged else "none")
            job.migration_summary['hardware'] = hardware_report()
            emit_summary(job.migration_summary, emit)
            if not unchanged:
                emit("The source folder changed or could not be checked again. This package is incomplete; review locally and rerun.")
            stage = "write_event_log"
            events.write("finished")
            emit("Package status: " + phase + ". The status JSON is beside the migration destination.")
            tracker.update("reporting", force=True)
            finished = True
            return 2 if phase == "incomplete" else 1 if phase == "needs_review" or had_recovery else 0
    except BaseException as error:
        job.migration_summary = migration_summary("interrupted", len(files), counts, failure_code(error), stage)
        if hardware_report:
            job.migration_summary['hardware'] = hardware_report()
        emit("Migration interrupted [" + failure_code(error) + "]. Completed outputs remain; this package is not complete.")
        emit_summary(job.migration_summary, emit)
        # A disconnected output/log drive must not mask the original failure.
        try:
            if events:
                events.issue(stage, failure_code(error))
                events.write("interrupted")
        except Exception as secondary:
            session_issue(job, "write_event_log", secondary)
            emit("Could not record interruption in the local event log [" + failure_code(secondary) + "].")
        try:
            if initialized:
                write_status(package, "interrupted", len(files), counts, timestamp_warnings, sizes)
        except Exception as secondary:
            session_issue(job, "write_status", secondary)
            emit("Could not update package status [" + failure_code(secondary) + "]. It may still show building; do not treat it as complete.")
        raise
    finally:
        primary_error = sys.exception()
        log_error = None
        try:
            if events:
                events.close()
        except Exception as error:
            log_error = error
            session_issue(job, "close_event_log", error)
            emit("Could not close the local event log [" + failure_code(error) + "].")
        def export_diagnostics():
            export_job(job, bundle.version)
            emit("Detailed diagnostic text log saved for local review.")
        if journal:
            try:
                eligible = counts['excluded_unresolved'] + counts['failed']
                if initialized and (not finished or eligible) and not journal.persistent and not job.cleanup_blocked.is_set():
                    protected = published_numbers | set(retry_state['published'] if retry_state else ())
                    remaining = eligible if finished else max(0, len(files) - len(protected))
                    mode = 'retry' if finished else 'continue'
                    SESSION_RETRIES[job.id] = journal.retry_snapshot(workspace, sensitive, protected, remaining,
                        describe_policy(policy_preferences), mode=mode)
                    SESSION_RETRIES.move_to_end(job.id)
                    while len(SESSION_RETRIES) > 8:
                        SESSION_RETRIES.popitem(last=False)
                    emit(('Continue this interrupted migration from Start or Activity while this app stays open.' if mode == 'continue'
                          else 'Retry unresolved is available in this session with reselected unchanged source/output folders.') +
                         ' Matching uses keyed tokens; no source names or paths are retained by the session snapshot.')
                elif finished and not eligible:
                    SESSION_RETRIES.pop(job.id, None)
                complete_checkpoint = finished and primary_error is None and log_error is None and phase == 'complete'
                retain_checkpoint = journal.persistent and initialized and not complete_checkpoint
                journal.close(complete=complete_checkpoint)
                if complete_checkpoint and journal.persistent:
                    emit('Private restart checkpoint removed after complete package.')
                if retain_checkpoint:
                    emit('Private restart checkpoint retained. Reselect the same source/output and use Resume from private checkpoint with this job ID and passphrase.'
                         if not finished else
                         'Private restart checkpoint retained. This package needs review; resume with the same source/output, options, job ID and passphrase to retry unresolved work.')
                elif journal.persistent and not initialized:
                    emit('Private checkpoint setup did not finish. Do not assume this job can resume after closing.')
            except Exception as error:
                session_issue(job, "save_session_report", error)
                emit("Restart checkpoint finalization failed [" + failure_code(error) + "]. Keep the checkpoint for local review.")
                log_error = log_error or error
        finalize_session(job, bundle.version, emit, primary_error=primary_error or log_error,
                         export_callback=export_diagnostics if not sensitive or export_on_completion else None)
        if primary_error is None and log_error is not None:
            raise log_error
        if finished:
            tracker.update("finished", force=True)
