"""Opt-in, bounded text logs built exclusively from closed diagnostic facts."""
from collections import Counter
import os
import secrets
import time

from .errors import MESSAGES, VideoMateError
from .log_text import step_text
from .preferences import storage_directory
from .schema import get_schema, validate_value
from .trace import validate_trace


class EventLog:
    EVENTS = {"started", "input_started", "input_finished", "finished", "interrupted"}
    MAX_BYTES = 4 * 1024 * 1024
    MAX_SEGMENTS = 4

    def __init__(self, job, settings):
        self.handle = None
        self.handles = []
        self.slot = 0
        self.bytes = 0
        self.started_at = time.monotonic()
        self.totals, self.stages, self.errors = Counter(), Counter(), Counter()
        self.elapsed, self.messages = Counter(), Counter()
        self.patterns = Counter()
        self.suppressed = 0
        self.rotations = 0
        self.schema = get_schema()
        self.detailed = settings.get("diagnostic_logs", False)
        if not self.detailed and (not settings.get("write_logs", False) or settings.get("sensitive", False)):
            return
        self.root = storage_directory(settings.get("logs_dir", ""), job.workspace / "logs")
        self.token = secrets.token_hex(16)
        self._segment()

    def _segment(self):
        if self.handle:
            self.handle.flush()
            self.slot = (self.slot + 1) % self.MAX_SEGMENTS
            self.rotations += 1
        if self.slot == len(self.handles):
            target = self.root / (f"events-{self.token}-{self.slot + 1}.log")
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self.handles.append(os.fdopen(descriptor, "w", encoding="utf-8", newline="\n"))
        self.handle = self.handles[self.slot]
        # Reuse only our still-open descriptor, never reopen a path that might be replaced.
        self.handle.seek(0)
        self.handle.truncate()
        self.bytes = 0
        self._raw(f"VideoMate safe activity log; segment sequence {self.rotations + 1}. Relative elapsed time only.\n")
        if self.rotations:
            self._raw("Rotation retains the latest four segments; older detail may be replaced.\n")
            self._raw(self._summary() + "\n")

    def _raw(self, text):
        self.handle.write(text)
        self.bytes += len(text.encode('utf-8'))

    def _line(self, text):
        if not self.handle:
            return
        text = f"+{int((time.monotonic() - self.started_at) * 1000)}ms " + text + "\n"
        if self.bytes + len(text.encode('utf-8')) > self.MAX_BYTES:
            self._segment()
        self._raw(text)
        self.handle.flush()

    def _summary(self):
        parts = [f"started={self.totals['input_started']}; completed={self.totals['input_finished']}; repeated detail suppressed={self.suppressed}"]
        if self.stages:
            parts.append('workers: ' + ', '.join(f'{k} x{v}/{self.elapsed[k]}ms' for k, v in sorted(self.stages.items())))
        if self.errors:
            parts.append('errors: ' + ', '.join(f'{k} x{v}' for k, v in sorted(self.errors.items())))
        if self.messages:
            parts.append('worker messages: ' + ', '.join(f'{k} x{v}' for k, v in sorted(self.messages.items())))
        return 'Progress: ' + ' | '.join(parts)

    def write(self, event, number=None):
        if not self.handle:
            return
        if event not in self.EVENTS or (number is not None and (type(number) is not int or number < 1)):
            raise ValueError("Invalid event")
        self.totals[event] += 1
        if event in {'input_started', 'input_finished'}:
            if event == 'input_finished' and self.totals[event] % 1000 == 0:
                self._line(self._summary())
            return
        self._line(event + '; ' + self._summary())

    def issue(self, stage, code):
        if not self.handle:
            return
        from .diagnostic_report import STAGE_LABELS
        if stage not in STAGE_LABELS or code not in {*MESSAGES, 'operator_cancelled'}:
            raise VideoMateError('invalid_export')
        self.errors[stage + ':' + code] += 1
        self._line(f'PIPELINE FAILURE {stage} [{code}]')

    def details(self, result, number):
        if not self.handle or not self.detailed:
            return
        if type(number) is not int or number < 1:
            raise ValueError("Invalid event")
        # Validate every record before writing any part of this result.
        steps = [validate_trace(detail) for detail in result.diagnostics]
        migration = result.technical.get('migration')
        if migration is not None:
            validate_value(migration, self.schema['$defs']['file']['properties']['migration'], self.schema)
        if migration and migration['reason'] != 'none':
            self.errors['file:' + migration['reason']] += 1
            self._line(f"input {number}: {migration['action']} [{migration['reason']}]; copy_check={migration['copy_check']}")
        for step in steps:
            self.stages[step['stage'] + ':' + step['outcome']] += 1
            self.elapsed[step['stage'] + ':' + step['outcome']] += step['elapsed_ms']
            for message in step['messages']:
                self.messages[message['severity'] + ':' + message['category']] += message['count']
            if step['error_code'] != 'none':
                self.errors[step['stage'] + ':' + step['error_code']] += 1
            if step['outcome'] == 'completed' and not step['messages'] and step['error_code'] == 'none':
                continue
            pattern = step_text(step, timing=False)
            if pattern not in self.patterns and len(self.patterns) >= 128:
                self.patterns.clear()
            self.patterns[pattern] += 1
            if self.patterns[pattern] <= 3:
                self._line(f'input {number}: ' + step_text(step))
            else:
                self.suppressed += 1
                if self.patterns[pattern] % 1000 == 0:
                    self._line(f'Repeated worker pattern x{self.patterns[pattern]}: ' + pattern)

    def close(self):
        failure = None
        try:
            if self.handle:
                self._line('Log closed; ' + self._summary())
        except BaseException as error:
            failure = error
        finally:
            handles, self.handles = self.handles, []
            self.handle = None
            for handle in handles:
                try:
                    handle.close()
                except BaseException as error:
                    failure = failure or error
        if failure is not None:
            raise failure
