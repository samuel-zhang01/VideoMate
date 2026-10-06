"""Synthetic-only diagnostics, late failures, compaction and bounded rotation."""
import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock, patch

from videomate.diagnostic_report import write_bundle
from videomate.diagnostics import create_export_batches, environment
from videomate.event_log import EventLog
from videomate.errors import VideoMateError
from videomate.cli import main
from videomate.models import ScanResult
from videomate.runner import ProcessResult
from videomate.trace import record_trace, worker_trace


class TextLogTests(unittest.TestCase):
    def failure(self, stream=0):
        result = ScanResult(integrity='unreadable')
        record_trace(result, worker_trace('decode', ProcessResult(1, stderr=b'[error] invalid NAL PRIVATE_CANARY', elapsed_ms=29),
                                          stream_index=stream, decoder='software', threads=6))
        return result

    def test_default_is_one_text_log_with_repetition_grouped_and_json_optional(self):
        with tempfile.TemporaryDirectory(prefix='videomate-text-generated-') as directory:
            root = Path(directory)
            def pages():
                return create_export_batches([self.failure() for _ in range(1005)], uuid4(), bytes(32), environment('9.0.2', '9.0.2'))
            name = write_bundle(root, pages())
            self.assertEqual([p.name for p in root.iterdir()], [name])
            content = (root / name).read_text()
            self.assertIn('Pattern: 1,005 file(s)', content)
            self.assertEqual(content.count('Worker: decode:'), 1)
            self.assertIn('exit=1; decoder=software; threads=6', content)
            self.assertIn('worker time per file 29..29ms', content)
            self.assertIn('FFmpeg nonzero exits:', content)
            self.assertIn('decode:exit=1: 1,005', content)
            self.assertIn('FFmpeg classified messages:', content)
            self.assertNotIn('PRIVATE_CANARY', content)
            self.assertNotIn('file_ref', content)
            write_bundle(root, pages(), technical_json=True)
            self.assertEqual(len(list(root.glob('*.json'))), 2)
            self.assertFalse(list(root.glob('*.html')))

    def test_distinct_patterns_are_flushed_without_losing_late_details(self):
        with tempfile.TemporaryDirectory(prefix='videomate-text-generated-') as directory:
            root = Path(directory)
            pages = create_export_batches([self.failure(i) for i in range(300)], uuid4(), bytes(32), environment('9.0.2', '9.0.2'))
            content = (root / write_bundle(root, pages)).read_text()
            self.assertEqual(content.count('Pattern:'), 300)
            self.assertIn('stream=299', content)

    def test_unknown_private_field_is_rejected_before_export_and_json_flag_is_explicit(self):
        with tempfile.TemporaryDirectory(prefix='videomate-text-generated-') as directory:
            root = Path(directory)
            document = json.loads(next(create_export_batches([self.failure()], uuid4(), bytes(32), environment('9.0.2', '9.0.2'))))
            document['files'][0]['private_path'] = 'PRIVATE_CANARY'
            with self.assertRaises(VideoMateError):
                write_bundle(root, [json.dumps(document).encode()])
            self.assertEqual(list(root.iterdir()), [])
            with patch('videomate.cli.report_local', return_value=0) as report:
                self.assertEqual(main(['export-diagnostics', '--job', 'invented', '--workspace', str(root), '--technical-json']), 0)
                self.assertTrue(report.call_args.kwargs['technical_json'])

    def test_live_log_keeps_late_failure_after_many_successes(self):
        with tempfile.TemporaryDirectory(prefix='videomate-text-generated-') as directory:
            root = Path(directory).resolve()
            log = EventLog(SimpleNamespace(workspace=root), {'sensitive': True, 'diagnostic_logs': True})
            try:
                log.write('started')
                for i in range(1, 6002):
                    log.write('input_started', i)
                    log.write('input_finished', i)
                log.details(self.failure(), 6001)
                log.issue('write_status', 'output_write_failed')
                log.write('interrupted')
            finally:
                log.close()
            text = next((root / 'logs').glob('*.log')).read_text()
            self.assertIn('input 6001: decode: failed', text)
            self.assertIn('PIPELINE FAILURE write_status [output_write_failed]', text)
            self.assertIn('completed=6001', text)
            self.assertLess(len(text.splitlines()), 20)
            self.assertNotIn('PRIVATE_CANARY', text)

    def test_repeated_failures_are_counted_and_rotation_keeps_latest_failure(self):
        with tempfile.TemporaryDirectory(prefix='videomate-text-generated-') as directory:
            root = Path(directory).resolve()
            log = EventLog(SimpleNamespace(workspace=root), {'diagnostic_logs': True})
            log.MAX_BYTES = 2048
            try:
                for i in range(50):
                    log.details(self.failure(), i + 1)
                self.assertEqual(log.suppressed, 47)
                for i in range(200):
                    log.issue('process_files', 'source_read_failed')
                log.issue('write_status', 'output_write_failed')
            finally:
                log.close()
            logs = list((root / 'logs').glob('*.log'))
            self.assertEqual(len(logs), 4)
            text = '\n'.join(p.read_text() for p in logs)
            self.assertIn('write_status [output_write_failed]', text)
            self.assertIn('process_files:source_read_failed x200', text)
            self.assertIn('repeated detail suppressed=47', text)
            self.assertTrue(all(p.stat().st_size <= 2048 for p in logs))

    def test_rotation_handles_all_close_even_if_one_close_fails(self):
        log = EventLog(SimpleNamespace(), {'sensitive': True})
        failure = OSError('PRIVATE_CANARY')
        first, second = Mock(), Mock()
        first.close.side_effect = failure
        log.handles = [first, second]
        with self.assertRaises(OSError) as caught:
            log.close()
        self.assertIs(caught.exception, failure)
        second.close.assert_called_once()
        self.assertEqual(log.handles, [])
        log.close()
