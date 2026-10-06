"""Plain text from closed technical facts. Never format backend text."""
from itertools import groupby

from .trace import validate_trace


def step_text(step, *, timing=True):
    validate_trace(step)
    parts = [step['stage'] + ': ' + step['outcome']]
    for key, label in (("stream_index", "stream"), ("return_code", "exit"),
                       ("decoder", "decoder"), ("encoder", "encoder"), ("threads", "threads")):
        if step[key] is not None and step[key] != "none":
            parts.append(f"{label}={step[key]}")
    if timing:
        parts.append(f"elapsed={step['elapsed_ms']}ms")
    for key in ("error_code", "limit_reason"):
        if step[key] != "none":
            parts.append(f"{key}={step[key]}")
    if step['messages']:
        parts.append('messages=' + ', '.join(f"{m['severity']}:{m['category']} x{m['count']}" for m in step['messages']))
    return '; '.join(parts)


def entry_lines(entry):
    """Caller must validate the entire export before using this projection."""
    migration = entry.get('migration', {})
    yield f"Result: {entry['integrity']}; scan={entry['scan_depth']}/{entry['scan_state']}; recovery={entry['recovery_state']}"
    if migration:
        yield 'Migration: ' + '; '.join(f'{k}={v}' for k, v in migration.items())
    yield f"Media: {entry['container']}; completeness={entry['completeness']}"
    if entry['input_duration_us'] is not None or entry['output_duration_us'] is not None:
        yield f"Playback duration (us): input={entry['input_duration_us']}; output={entry['output_duration_us']}"
    if entry.get('processing'):
        yield 'Allocation: ' + '; '.join(f'{k}={v}' for k, v in entry['processing'].items())
    for stream in entry['streams']:
        yield 'Stream: ' + '; '.join(f'{k}={v}' for k, v in stream.items())
    for finding in entry['findings']:
        interval = finding['interval']
        location = f"; relative_us={interval['start_us']}..{interval['end_us']}" if interval else ''
        yield f"Finding: {finding['severity']} {finding['category']} x{finding['count']}; stream={finding['stream_index']}; evidence={finding['evidence']}" + location
    for text, steps in groupby(step_text(step, timing=False) for step in entry.get('diagnostics', [])):
        count = sum(1 for _ in steps)
        yield 'Worker: ' + text + (f' (repeated {count} times)' if count > 1 else '')
    for index, attempt in enumerate(entry['attempts'], 1):
        yield f"Attempt {index}: " + '; '.join(f'{k}={attempt[k]}' for k in ('strategy', 'profile', 'decoder', 'encoder', 'outcome', 'reason') if k in attempt)
        if attempt.get('verification_issues'):
            yield '  Verification issues: ' + ', '.join(attempt['verification_issues'])
    if entry['attempts']:
        yield 'Final verification: ' + '; '.join(f'{k}={v}' for k, v in entry['verification'].items())
    for key in ('losses', 'recovery_notes'):
        if entry.get(key):
            yield key + ': ' + ', '.join(entry[key])
    for edit in entry['edits']:
        intervals = []
        for key in ('input_interval', 'output_interval'):
            interval = edit[key]
            intervals.append(key + '=' + (f"{interval['start_us']}..{interval['end_us']}us" if interval else 'unknown'))
        yield f"Edit: {edit['action']}; " + '; '.join(intervals) + f"; timing={edit['timing_confidence']}"
    omitted = sum(entry.get(key, 0) for key in ('streams_omitted', 'findings_omitted', 'diagnostics_omitted', 'edits_omitted'))
    if omitted:
        yield f'Bounded collection omitted {omitted} technical records.'


def needs_detail(entry):
    migration = entry.get('migration', {})
    return (migration.get('reason', 'none') != 'none'
            or migration.get('action') in {'failed', 'excluded_unresolved', 'retained_for_review', 'copied_unresolved', 'repaired'}
            or entry['integrity'] not in {'quick_check_only', 'no_errors_detected'}
            or entry['recovery_state'] != 'not_requested' or bool(entry['findings'])
            or any(s['outcome'] != 'completed' or s['messages'] or s['error_code'] != 'none'
                   for s in entry.get('diagnostics', [])))
