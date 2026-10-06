"""Local job services shared by the CLI and native desktop UI."""
import json
import hashlib
import secrets
import sys
import threading
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from uuid import UUID, uuid4

from .backend import FFmpegBackend
from .dependencies import load_bundle
from .diagnostics import create_export, environment
from .diagnostic_report import write_bundle
from .discovery import discover
from .errors import VideoMateError
from .inspection import Inspector, _fingerprint
from .jobs import Job, job_lock, unpack_result
from .models import Depth, recovery_suggestion
from .policy import LocalFileScope, plain_local_path, validate_workspace
from .preferences import Preferences, storage_directory
from .event_log import EventLog
from .recovery import RecoveryEngine, RecoveryOptions
from .runner import Runner
from .schema import load_json
from .execution import cpu_budget, thread_slots, parallel_inspect
from .hardware import select_decoder
from .private_state import MemoryJob, LIVE_REPORTS, finalize_session, fresh_report, session_exports, report_pages
from .checkpoint import Checkpoint
from .output_layout import plan_layout, destination_root


def workspace_path(workspace):
    return validate_workspace(workspace, Path(__file__).absolute().parents[2])


def export_job(job, version, *, technical_json=False):
    if isinstance(job, MemoryJob):
        # Session-only jobs never retain a filename mapping. Stream bounded
        # documents so migration size cannot invalidate a completed package.
        directory = storage_directory(job.settings().get('diagnostics_dir', ''), job.workspace / 'export-review')
        return write_bundle(directory, session_exports(job, version), summary=getattr(job, 'migration_summary', None),
                            environment=environment(version, version), technical_json=technical_json)
    pairs = [(row, unpack_result(row['result'])) for row in job.rows() if row['result']]
    if not pairs:
        return None
    encoded = create_export([p[1] for p in pairs], UUID(hex=job.id), secrets.token_bytes(32), environment(version, version))
    report = load_json(encoded)
    token = secrets.token_hex(12)
    export_name = 'diagnostics-' + token + '.json'
    settings = job.settings()
    mapped = settings.get('retain_mappings', False) and not settings.get('sensitive', False)
    if mapped:
        mapping = {'schema_version': 1, 'job': job.id, 'export_file': export_name,
                   'files': [{'file_ref': item['file_ref'], 'input_number': row['number'],
                              'private_input_path': row['path'],
                              'private_output_path': (result.recovery or {}).get('private_output')}
                             for item, (row, result) in zip(report['files'], pairs)]}
        with (job.workspace / 'state' / ('mapping-' + token + '.json')).open('x', encoding='utf-8') as output:
            json.dump(mapping, output, ensure_ascii=True, indent=2)
    directory = storage_directory(job.settings().get('diagnostics_dir', ''), job.workspace / 'export-review')
    from .diagnostic_report import Report
    readable = Report()
    try:
        readable.add(encoded, export_name)
        if technical_json or mapped:
            with (directory / export_name).open('xb') as output:
                output.write(encoded)
        log_name = 'diagnostics-' + token + '.log'
        with (directory / log_name).open('x', encoding='utf-8') as output:
            readable.write_text(output)
        return log_name
    finally:
        readable.close()



def result_code(result):
    recovery = result.recovery or {}
    if recovery.get('recovery_state') in {'failed', 'blocked'}:
        return 2
    if recovery.get('recovery_state') in {'verified_with_losses', 'verification_inconclusive', 'planned'}:
        return 1
    return result.exit_code


def run_job(job, dependencies=None, *, emit=print, cancel_event=None, checkpoint=None):
    from .execution import processing_session
    with processing_session(job.workspace), job_lock(job.directory):
        settings = job.settings()
        sensitive = settings.get('sensitive', False)  # Older test jobs used automatic exports.
        cancel_event = cancel_event or threading.Event()
        budget = cpu_budget(settings.get('cpu_threads', 0))
        timeout = settings.get('timeout')
        if type(timeout) is not int or not 1 <= timeout <= 86400:
            raise VideoMateError('job_invalid')
        depth = Depth(settings['depth'])
        recovery = RecoveryOptions(**settings['recovery']) if settings.get('recovery') else None
        if recovery:
            recovery.validate()
        bundle = load_bundle(dependencies)
        previous_backend = settings.get('backend_version')
        settings['backend_version'] = bundle.version
        job.update_settings(settings)
        source_root = Path(__file__).absolute().parents[2]
        rows = job.rows()
        paths = [Path(row['path']) for row in rows]
        scope = LocalFileScope(frozenset(paths), source_root)
        for path in paths:
            scope.authorize(path)
        scratch = plain_local_path(job.directory / 'scratch')
        scratch.mkdir(mode=0o700, exist_ok=True)
        recovered_root = storage_directory(settings.get('recovered_dir', ''), job.workspace / 'recovered')
        # Keep candidates on the selected output filesystem for atomic no-overwrite publication.
        if isinstance(job, MemoryJob) and settings.get('recovered_dir'):
            candidates = plain_local_path(recovered_root / '.candidates' / ('candidates-' + uuid4().hex))
            candidates.mkdir(mode=0o700, parents=True, exist_ok=False)
            job.own_directory(candidates)
        else:
            candidates = plain_local_path(recovered_root / '.candidates' / job.id if settings.get('recovered_dir') else job.directory / 'candidates')
            candidates.mkdir(mode=0o700, parents=True, exist_ok=True)
        cleanup_blocked = getattr(job, 'cleanup_blocked', threading.Event())
        backend = FFmpegBackend(bundle.ffmpeg, bundle.ffprobe, scratch, Runner(timeout=timeout, cancel_event=cancel_event, cleanup_blocked=cleanup_blocked), scope=scope, threads=budget)
        emit('Job: ' + job.id)
        emit('Sensitive: ' + ('Yes' if sensitive else 'No') + ' (job policy).')
        if isinstance(job, MemoryJob):
            emit('Minimal retention: source paths stay in memory. Session reports remain available until the app closes; no persistent job history or export mappings.')
        if checkpoint:
            checkpoint.bind_sources(job, paths, scope, cancel_event, emit)
            for row, source in zip(rows, paths):
                restored = checkpoint.restore(row['number'], source, recovered_root, bundle.version, cancel_event)
                if restored is not None:
                    job.save(row['number'], 'done', restored)
                    emit(f"input-{row['number']}: private checkpoint matched; completed work reused.")
            rows = job.rows()
            previous_backend = bundle.version
        items = []
        for row, source in zip(rows, paths):
            if cancel_event is not None and cancel_event.is_set():
                raise KeyboardInterrupt()
            if previous_backend == bundle.version and row['status'] == 'done' and row['result']:
                previous = unpack_result(row['result'])
                output = (previous.recovery or {}).get('private_output')
                # Completed output must remain under this job's output root.
                output_ok = not output
                if output:
                    selected = plain_local_path(Path(output))
                    permitted = recovered_root / job.id
                    output_ok = permitted in selected.parents and selected.is_file()
                    if output_ok:
                        with selected.open('rb') as existing:
                            output_ok = hashlib.file_digest(existing, 'sha256').hexdigest() == previous.recovery.get('private_output_sha256')
                if tuple(previous.fingerprint or ()) == _fingerprint(source) and output_ok and previous.technical.get('backend_version') == bundle.version:
                    continue
            items.append((row, source))
        events = EventLog(job, settings)
        iterator = None
        runners = 1
        try:
            events.write('started')
            if items and recovery and settings.get('hardware_decoding', True):
                backend.decoder = select_decoder(backend)
            emit('Processing budget: ' + str(budget) + ' codec threads; integrity checks use software; preferred repair decoder: ' + backend.decoder + '.')
            if recovery:
                iterator = ((item, None) for item in items)
            elif items:
                slots = thread_slots(budget, len(items), settings.get('max_runners', 0))
                runners = len(slots)
                gate = threading.Semaphore(2)
                workers = []
                for slot, threads in enumerate(slots):
                    work = plain_local_path(scratch / ('worker-' + str(slot + 1)))
                    work.mkdir(mode=0o700, exist_ok=True)
                    workers.append(FFmpegBackend(bundle.ffmpeg, bundle.ffprobe, work,
                        Runner(timeout=timeout, cancel_event=cancel_event, cleanup_blocked=cleanup_blocked), scope=scope,
                        threads=threads, decoder=backend.decoder, hardware_gate=gate))
                emit('Parallel inspection runners: ' + str(len(workers)) + '.')
                def started(item):
                    row, _ = item
                    job.save(row['number'], 'inspecting')
                    emit(f"Inspecting input {row['number']}/{len(rows)}...")
                    events.write('input_started', row['number'])
                def inspect(worker, item):
                    return Inspector(worker, scope).inspect(item[1], depth)
                iterator = parallel_inspect(items, workers, inspect, started, cancel_event)
            else:
                iterator = iter(())
            for (row, source), scanned in iterator:
                if cancel_event.is_set():
                    raise KeyboardInterrupt()
                number = row['number']
                if scanned is None:
                    job.save(number, 'inspecting')
                    emit(f'Inspecting input {number}/{len(rows)}...')
                    events.write('input_started', number)
                result = scanned if scanned is not None else Inspector(backend, scope).inspect(source, Depth.FULL)
                result.technical['backend_version'] = bundle.version
                result.technical['processing'] = {'cpu_budget': budget, 'runners': runners,
                                                  'hardware_decoding': 'enabled' if settings.get('hardware_decoding', True) else 'disabled'}
                job.save(number, 'inspected', result)
                try:
                    if recovery:
                        emit(f'input-{number}: planning recovery')
                        output_root, output_stem = recovered_root / job.id / f'input-{number}', None
                        relative = settings.get('private_output_layout', {}).get(str(number)) if not sensitive else None
                        if relative:
                            output_root, output_stem = destination_root(recovered_root / job.id, relative)
                        engine = RecoveryEngine(backend, scope, candidates, output_root, source_root, output_stem=output_stem)
                        engine.recover(source, result, recovery, execute=settings['execute'])
                    job.save(number, 'done', result)
                    if checkpoint:
                        checkpoint.remember(number, result, bundle.version, recovered_root)
                except KeyboardInterrupt:
                    job.save(number, 'interrupted', result)
                    raise
                state = (result.recovery or {}).get('recovery_state', recovery_suggestion(result))
                emit(f'input-{number}: {result.integrity}; {state}')
                events.write('input_finished', number)
                events.details(result, number)
                if result.recovery:
                    checks = result.recovery['verification']
                    emit(f"input-{number}: verification — decode {checks['decode_check']}, streams {checks['stream_check']}, timing {checks['timing_check']}.")
                    for attempt_number, attempt in enumerate(result.recovery['attempts'], 1):
                        issues = ', '.join(attempt.get('verification_issues', [])) or attempt['reason']
                        emit(f"input-{number}: attempt {attempt_number} {attempt['strategy']} / {attempt.get('encoder', 'none')}: {attempt['outcome']}; {issues}.")
                    duration = result.recovery.get('output_duration_us')
                    if duration is not None and result.duration_us is not None:
                        emit(f"input-{number}: output duration change {(duration - result.duration_us) / 1000000:+.3f} seconds.")
                    if result.recovery.get('losses'):
                        emit(f"input-{number}: disclosures — " + ', '.join(result.recovery['losses']) + '.')
                if (result.recovery or {}).get('private_plan'):
                    emit('Plan: ' + ' then '.join(result.recovery['private_plan']) + '; metadata excluded; profile ' + recovery.profile)
                    emit('Guided preview only. Run recover with --execute to carry out the selected policy.')
                if (result.recovery or {}).get('private_output'):
                    emit(f'input-{number}: copy saved in the configured recovered-files folder.')
            events.write('finished')
            if checkpoint:
                checkpoint.finish()
                emit('Private checkpoint removed: this job completed.')
        except BaseException:
            cancel_event.set()
            events.write('interrupted')
            raise
        finally:
            try:
                try:
                    if iterator is not None and hasattr(iterator, 'close'):
                        iterator.close()
                finally:
                    events.close()
            finally:
                # A secondary log/storage failure must never hide an
                # unconfirmed worker shutdown: processing_session must observe
                # this category and block every later coordinator.
                if cleanup_blocked.is_set():
                    raise VideoMateError('worker_cleanup_failed') from None
            if sensitive:
                emit('Sensitive: automatic exports are off. Detailed diagnostics are available through explicit export; disk diagnostics require opt-in.')
            elif export_job(job, bundle.version):
                emit('Sanitized diagnostics saved in the configured diagnostics folder; review locally before sharing.')
                emit('Saved job state and any opt-in filename mappings are private and must not be shared.')
        codes = {result_code(unpack_result(row['result'])) for row in job.rows() if row['result']}
        return 2 if 2 in codes else 1 if 1 in codes else 0


def scan_local(inputs, workspace, *, dependencies=None, depth=Depth.FULL, timeout=3600, recursive=False,
               recovery=None, execute=True, emit=print, cancel_event=None, sensitive=True,
               recovered_dir='', diagnostics_dir='', logs_dir='', write_logs=False, diagnostic_logs=False,
               cpu_threads=0, max_runners=0, hardware_decoding=True, output_layout='neutral',
               retain_history=False, retain_mappings=False, private_resume=False, checkpoint_id=None,
               passphrase=None, export_on_completion=False):
    Preferences(sensitive=sensitive, recovered_dir=recovered_dir, diagnostics_dir=diagnostics_dir,
                logs_dir=logs_dir, write_logs=write_logs, diagnostic_logs=diagnostic_logs,
                cpu_threads=cpu_threads, max_runners=max_runners, hardware_decoding=hardware_decoding,
                output_layout=output_layout, retain_history=retain_history, retain_mappings=retain_mappings,
                private_resume=private_resume).validate()
    if (type(timeout) is not int or not 1 <= timeout <= 86400 or not isinstance(depth, Depth)
            or type(recursive) is not bool or type(execute) is not bool
            or type(export_on_completion) is not bool
            or (recovery is not None and not isinstance(recovery, RecoveryOptions))):
        raise VideoMateError('invalid_arguments')
    workspace = workspace_path(workspace)
    if recovery:
        recovery.validate()
    exclusions = [Path(path) for path in (recovered_dir, diagnostics_dir, logs_dir) if path]
    paths = discover(inputs, workspace, Path(__file__).absolute().parents[2], recursive, exclusions=exclusions)
    bundle = load_bundle(dependencies)
    if (private_resume or checkpoint_id) and (not sensitive or not execute):
        raise VideoMateError('invalid_arguments')
    with job_lock(workspace / 'state') if (private_resume or checkpoint_id) else nullcontext():
        checkpoint = None
        if private_resume or checkpoint_id:
            policy = {'depth': depth.value, 'recovery': asdict(recovery.resolved()) if recovery else None,
                      'backend_version': bundle.version, 'hardware_decoding': hardware_decoding}
            checkpoint = Checkpoint(workspace, passphrase, policy, identifier=checkpoint_id)
        settings = {'scope': 'local_files', 'sensitive': sensitive, 'recovered_dir': recovered_dir,
                    'diagnostics_dir': diagnostics_dir, 'logs_dir': logs_dir, 'write_logs': write_logs,
                    'diagnostic_logs': diagnostic_logs, 'cpu_threads': cpu_threads, 'max_runners': max_runners,
                    'hardware_decoding': hardware_decoding,
                    'output_layout': 'neutral' if sensitive else output_layout,
                    'private_output_layout': plan_layout(inputs, paths, output_layout, sensitive),
                    'retain_history': retain_history, 'retain_mappings': retain_mappings if not sensitive else False,
                    'private_resume': bool(checkpoint),
                    'depth': depth.value, 'timeout': timeout,
                    'recovery': asdict(recovery) if recovery else None, 'execute': execute}
        job = MemoryJob.create(workspace, paths, settings, identifier=checkpoint.id if checkpoint else None) if sensitive and (not retain_history or checkpoint) else Job.create(workspace, paths, settings)
        try:
            code = run_job(job, dependencies, emit=emit, cancel_event=cancel_event, checkpoint=checkpoint)
            if export_on_completion:
                export_job(job, bundle.version)
                emit('Explicitly requested sanitized export saved. Review it locally before sharing.')
            return code
        finally:
            finalize_session(job, bundle.version, emit, primary_error=sys.exception())


def resume_local(identifier, workspace, *, dependencies=None, emit=print, cancel_event=None):
    job = Job(workspace_path(workspace), identifier)
    try:
        return run_job(job, dependencies, emit=emit, cancel_event=cancel_event)
    finally:
        job.close()


def job_inputs(identifier, workspace, *, sensitive=True):
    job = Job(workspace_path(workspace), identifier)
    try:
        with job_lock(job.directory):
            if job.settings().get('sensitive', False) and not sensitive:
                raise VideoMateError('privacy_downgrade')
            return [row['path'] for row in job.rows()]
    finally:
        job.close()


def report_local(identifier, workspace, *, export=False, technical_json=False, emit=print):
    if identifier in LIVE_REPORTS:
        selected_workspace, diagnostics_dir, encoded = LIVE_REPORTS[identifier]
        if str(workspace_path(workspace)) != selected_workspace:
            raise VideoMateError('job_invalid')
        emit('Session report: source paths and mappings were not retained.')
        from .result_summary import summarize
        emit(summarize(encoded)['text'])
        if export:
            directory = storage_directory(diagnostics_dir, Path(selected_workspace) / 'export-review')
            pages = report_pages(encoded)
            name = write_bundle(directory, (fresh_report(page) for page in pages), technical_json=technical_json)
            emit('Diagnostic log saved: ' + (name or 'no records') + '. Use the Diagnostics folder configured when this job started. No filename mapping was written.')
            if technical_json:
                emit(f'{len(pages)} optional technical JSON batch(es) also saved.')
        return 0
    job = Job(workspace_path(workspace), identifier)
    try:
        with job_lock(job.directory):
            settings = job.settings()
            emit('Sensitive: ' + ('Yes' if settings.get('sensitive', False) else 'No') + ' (saved job setting).')
            groups = {}
            for row in job.rows():
                result = unpack_result(row['result']) if row['result'] else None
                status = result.integrity if result else 'pending'
                if result and result.recovery:
                    status += ' / ' + result.recovery['recovery_state']
                groups.setdefault(status, []).append(row['number'])
            for status, numbers in sorted(groups.items()):
                emit(status + f' ({len(numbers)}): ' + ', '.join('input-' + str(n) for n in numbers))
            if export:
                if export_job(job, job.settings().get('backend_version', '0.0.0'), technical_json=technical_json):
                    emit('Sanitized diagnostics saved in the configured diagnostics folder. Review locally before sharing.')
            return 0
    finally:
        job.close()
