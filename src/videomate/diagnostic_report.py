"""Compact text logs from validated exports only; never source locators."""
from collections import Counter
import io
import shutil
import tempfile
from .log_text import entry_lines, needs_detail
import secrets
import re

from .errors import MESSAGES, VideoMateError
from .schema import get_schema, load_json, validate_export, validate_value


STAGE_LABELS = {
    "prepare_output": "Prepare output and staging", "hardware_check": "Qualify hardware",
    "process_files": "Process file queue", "final_source_check": "Check source stability",
    "write_status": "Save package status", "write_event_log": "Write activity log",
    "close_event_log": "Close activity log", "save_session_report": "Retain session diagnostics",
    "export_diagnostics": "Export diagnostics", "cleanup": "Remove session temporary files",
    "probe": "Read container and codec information", "decode": "Decode source for integrity",
    "inspection": "Inspect source", "plan": "Select eligible recovery plan", "encode": "Write recovery candidate",
    "verify_probe": "Check candidate structure", "verify_decode": "Decode candidate for verification",
    "publish": "Publish verified output", "none": "No stop stage recorded",
}


def words(value):
    return value.replace("_", " ").replace(":", " / ")


def explanation(code):
    return MESSAGES.get(code, {"none": "No failure recorded.", "operator_cancelled": "Stopped by the operator."}.get(code, words(code)))


class Report:
    def __init__(self):
        self.detail_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        self.groups = {}
        self.files = 0
        self.batches = []
        self.environment = None
        self.summary = None
        self.integrity, self.actions, self.reasons = Counter(), Counter(), Counter()
        self.attempts, self.verification, self.findings = Counter(), Counter(), Counter()
        self.copy_checks, self.final_checks = Counter(), Counter()
        self.stages, self.limits, self.stage_errors, self.elapsed = Counter(), Counter(), Counter(), Counter()
        self.worker_exits, self.worker_messages = Counter(), Counter()
        self.omitted = 0

    def add(self, encoded, filename):
        if not re.fullmatch(r"diagnostics-[a-f0-9]{24}\.json", filename):
            raise VideoMateError("invalid_export")
        document = load_json(encoded)
        validate_export(document)
        if self.batches and (self.environment != document["environment"] or self.summary != document.get("migration_summary")):
            raise VideoMateError("invalid_export")
        self.environment = document["environment"]
        self.summary = document.get("migration_summary")
        self.batches.append((filename, len(document["files"])))
        for entry in document["files"]:
            self.files += 1
            if needs_detail(entry):
                lines = tuple(entry_lines(entry))
                duration = sum(step['elapsed_ms'] for step in entry.get('diagnostics', []))
                if lines not in self.groups:
                    if len(self.groups) >= 128:
                        self.flush_groups()
                    self.groups[lines] = [0, self.files, duration, duration, {}]
                group = self.groups[lines]
                group[0] += 1
                group[2], group[3] = min(group[2], duration), max(group[3], duration)
                for step in entry.get('diagnostics', []):
                    key, value = step['stage'], step['elapsed_ms']
                    timing = group[4].setdefault(key, [value, value, 0, 0])
                    timing[0], timing[1] = min(timing[0], value), max(timing[1], value)
                    timing[2] += value
                    timing[3] += 1
            self.integrity[entry["integrity"]] += 1
            migration = entry.get("migration", {})
            self.actions[migration.get("action", entry["recovery_state"])] += 1
            if migration:
                self.copy_checks[migration["copy_check"]] += 1
            if entry["recovery_state"] != "not_requested":
                self.final_checks.update(k + ":" + v for k, v in entry["verification"].items())
            if migration.get("reason", "none") != "none":
                self.reasons[migration["reason"]] += 1
            for finding in entry["findings"]:
                self.findings[finding["category"]] += finding["count"]
            for attempt in entry["attempts"]:
                key = ":".join((attempt["strategy"], attempt.get("decoder", "software"), attempt.get("encoder", "none"), attempt["outcome"], attempt["reason"]))
                self.attempts[key] += 1
                self.verification.update(attempt.get("verification_issues", []))
            for step in entry.get("diagnostics", []):
                self.stages[step["stage"] + ":" + step["outcome"]] += 1
                self.elapsed[step["stage"] + ":" + step["outcome"]] += step["elapsed_ms"]
                if step["error_code"] != "none":
                    self.stage_errors[step["stage"] + ":" + step["error_code"]] += 1
                if step['return_code'] not in (None, 0):
                    self.worker_exits[step['stage'] + ':exit=' + str(step['return_code'])] += 1
                for message in step['messages']:
                    self.worker_messages[step['stage'] + ':' + message['severity'] + ':' + message['category']] += message['count']
                if step["limit_reason"] != "none":
                    self.limits[step["stage"] + ":" + step["limit_reason"]] += 1
            self.omitted += entry.get("diagnostics_omitted", 0) + entry["findings_omitted"]

    def flush_groups(self):
        for lines, (count, first, low, high, timings) in self.groups.items():
            self.detail_file.write(f"\nPattern: {count:,} file(s); first anonymous record {first}; worker time per file {low}..{high}ms\n")
            self.detail_file.write('\n'.join('  ' + line for line in lines) + '\n')
            for stage, (minimum, maximum, total, calls) in sorted(timings.items()):
                self.detail_file.write(f'  Timing {stage}: {calls} calls; {minimum}..{maximum}ms each; {total}ms total\n')
        self.groups.clear()

    def write_text(self, output):
        self.flush_groups()
        def line(text=''):
            output.write(text + '\n')
        def counts(title, values):
            if values:
                line(title + ':')
                for key, count in sorted(values.items()):
                    line(f'  {key}: {count:,}')
        line('VideoMate diagnostic log')
        line('Source names, paths, raw worker output and recording dates are excluded.')
        line('Environment: ' + '; '.join(f'{k}={v}' for k, v in (self.environment or {}).items()))
        if self.summary:
            s = self.summary
            line('Migration ' + s['state'])
            line(f"Files: {s['processed_files']:,}/{s['planned_files']:,} processed; {s['unprocessed_files']:,} not processed; {s['published_files']:,} published (including {s.get('partial_files', 0):,} partial); {s['excluded_files']:,} excluded; {s['failed_files']:,} failed.")
            if h := s.get('hardware'):
                line(f"Hardware: decode requested={h['decode_requested']}; encode requested={h['encode_requested']}; decode selection={h['decode_selection']}; integrity decoder=software; peak hardware jobs={h['peak_gpu_jobs']}; peak active route slots={h['peak_active_routes']}.")
                for route in h['routes']:
                    line(f"  Route {route['slot']}: {route['decoder']} / {route['encoder']}; peak jobs={route['peak_jobs']}.")
                if h['encode_requested'] and h['decode_selection'] != 'preservation_software' and h['routes'] and all(
                        route['encoder'] in {'libx264', 'libx265'} for route in h['routes']):
                    line('Hardware encoding: requested, but no hardware encoder route qualified; software encoding selected.')
            if s['stop_reason'] != 'none':
                line(f"STOP at {s['stop_stage']} [{s['stop_reason']}]: {explanation(s['stop_reason'])}")
            for issue, count in Counter((i['stage'], i['reason']) for i in s['pipeline_issues']).items():
                line(f'Secondary failure x{count}: {issue[0]} [{issue[1]}]: {explanation(issue[1])}')
        else:
            line('No whole-job completion summary was recorded; these results do not establish job completion.')
        line(f'Coverage: {self.files:,} file records from {len(self.batches):,} validated batches.')
        counts('File outcomes', self.actions)
        counts('Integrity', self.integrity)
        counts('Copy verification', self.copy_checks)
        counts('File operation errors', self.reasons)
        line('Pipeline activity (summed worker time, not wall-clock time):')
        for key, count in sorted(self.stages.items()):
            line(f'  {key}: {count:,} calls; {self.elapsed[key]}ms total')
        if not self.stages:
            line('  No worker steps recorded; absence does not mean success.')
        counts('Stage failures', self.stage_errors)
        counts('FFmpeg nonzero exits', self.worker_exits)
        counts('FFmpeg classified messages', self.worker_messages)
        counts('Limits', self.limits)
        counts('Recovery attempts (strategy:decoder:encoder:outcome:reason)', self.attempts)
        counts('Verification disagreements', self.verification)
        counts('Final verification', self.final_checks)
        counts('Media findings', self.findings)
        if self.omitted:
            line(f'Collection limits omitted {self.omitted:,} findings/worker records.')
        line()
        line('Failure, warning and recovery details; identical patterns grouped in bounded windows.')
        line('Ordinary successful copies are counted above. Worker steps retain order; repeated adjacent steps are counted.')
        self.detail_file.seek(0)
        shutil.copyfileobj(self.detail_file, output)
        self.detail_file.seek(0, 2)
        line('End of diagnostic log. Unresolved does not mean irrecoverable. New migrations need an empty destination; retry or authenticated resume can reuse an owned package.')

    def text(self):
        output = io.StringIO()
        self.write_text(output)
        return output.getvalue()

    def close(self):
        self.detail_file.close()


def write_bundle(directory, pages, *, summary=None, environment=None, technical_json=False):
    report = Report()
    try:
        if summary is not None:
            schema = get_schema()
            validate_value(summary, schema["$defs"]["migration_summary"], schema)
            validate_value(environment, schema["$defs"]["environment"], schema)
            report.summary, report.environment = summary, environment
        for encoded in pages:
            name = "diagnostics-" + secrets.token_hex(12) + ".json"
            report.add(encoded, name)
            if technical_json:
                with (directory / name).open("xb") as output:
                    output.write(encoded)
        if report.batches:
            name = "diagnostics-" + secrets.token_hex(12) + ".log"
            with (directory / name).open("x", encoding="utf-8") as output:
                report.write_text(output)
            return name
        return None
    finally:
        report.close()
