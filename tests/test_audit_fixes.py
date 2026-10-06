"""Audit regressions: exclusively invented data in owned temporary directories."""
import json
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

from test_migration_resume import MigrationResumeTests
from videomate.errors import VideoMateError
from videomate.migration import process_file
from videomate.migration_resume import MigrationJournal, SESSION_RETRIES
from videomate.private_state import LIVE_REPORTS
from videomate.models import ScanResult
from videomate.recovery import RecoveryOptions, plan, selected_streams
from videomate.result_summary import summarize
from videomate.encoding import video_rates
from videomate.trace import worker_trace, record_trace


class AuditMigrationTests(unittest.TestCase):
    def setUp(self):
        self.f = MigrationResumeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.addCleanup(SESSION_RETRIES.clear)

    def test_reconnect_rejects_altered_completed_output(self):
        f = self.f
        def process(backend, item, **kwargs):
            if item[0] == 2:
                first = kwargs['package'] / 'PRIVATE_CANARY_0.txt'
                first.write_bytes(b'Invented output changed during disconnect')
                result = ScanResult(state='failed', integrity='unreadable')
                result.technical['migration'] = dict(input_kind='other', action='failed', copy_check='not_run', timestamps='not_requested', reason='source_read_failed')
                return result
            return process_file(backend, item, **kwargs)
        with patch('videomate.migration.process_file', side_effect=process):
            with self.assertRaises(VideoMateError) as caught:
                f.run_job(private_resume=True, passphrase='generated passphrase only')
        self.assertEqual(caught.exception.code, 'resume_output_conflict')
        self.assertTrue((f.workspace / 'state' / ('migration-' + f.identifier() + '.sqlite3')).exists())

    def make_excluded(self, **job_options):
        f = self.f
        def process(backend, item, **kwargs):
            if item[0] != 2:
                return process_file(backend, item, **kwargs)
            from videomate.inspection import _fingerprint
            r = ScanResult(integrity='unsupported', fingerprint=_fingerprint(item[1]))
            r.technical['migration'] = dict(input_kind='other', action='excluded_unresolved', copy_check='not_run', timestamps='not_requested', reason='recovery_unverified')
            return r
        with patch('videomate.migration.process_file', side_effect=process):
            self.assertEqual(f.run_job(**job_options), 1)
        return f.identifier()

    def test_session_retry_preserves_verified_outputs_and_contains_no_locators(self):
        f = self.f
        identifier = self.make_excluded()
        state = SESSION_RETRIES[identifier]
        self.assertNotIn(b'PRIVATE_CANARY', state['database'])
        self.assertNotIn(str(f.source), repr({k: v for k, v in state.items() if k != 'database'}))
        package = f.workspace / 'recovered' / ('migration-' + identifier)
        first = package / 'PRIVATE_CANARY_0.txt'
        before = (first.read_bytes(), first.stat().st_mtime_ns)
        with patch('videomate.migration.process_file', wraps=process_file) as process:
            self.assertEqual(f.run_job(retry_id=identifier, recovery=RecoveryOptions(size_policy='best_effort')), 0)
        self.assertEqual(process.call_count, 1)
        self.assertEqual((first.read_bytes(), first.stat().st_mtime_ns), before)
        self.assertEqual(len(list(package.glob('*.txt'))), 3)
        self.assertNotIn(identifier, SESSION_RETRIES)
        self.assertEqual(list((f.workspace / 'state').iterdir()), [])

    def test_direct_destination_retry_reuses_owned_package(self):
        f = self.f
        destination = f.root / 'generated-direct-package'
        identifier = self.make_excluded(recovered_dir=str(destination), package_layout='direct')
        first = destination / 'PRIVATE_CANARY_0.txt'
        before = first.read_bytes(), first.stat().st_mtime_ns
        self.assertEqual(f.run_job(recovered_dir=str(destination), package_layout='direct', retry_id=identifier), 0)
        self.assertEqual((first.read_bytes(), first.stat().st_mtime_ns), before)
        self.assertEqual(len(list(destination.glob('*.txt'))), 3)
        self.assertFalse(any(p.name.startswith('migration-') for p in destination.iterdir()))
        self.assertNotIn(identifier, SESSION_RETRIES)

    def test_session_retry_rejects_missing_output_or_changed_source(self):
        f = self.f
        identifier = self.make_excluded()
        output = f.workspace / 'recovered' / ('migration-' + identifier) / 'PRIVATE_CANARY_0.txt'
        output.unlink()  # Exact generated output from this test only.
        with self.assertRaises(VideoMateError) as caught:
            f.run_job(retry_id=identifier)
        self.assertEqual(caught.exception.code, 'resume_output_conflict')
        self.assertFalse(output.exists())

    def test_interrupted_retry_keeps_new_publication_intent(self):
        from videomate.migration import publish
        f = self.f
        identifier = self.make_excluded()
        def interrupt(candidate, target):
            publish(candidate, target)
            raise KeyboardInterrupt()
        with patch('videomate.migration.publish', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                f.run_job(retry_id=identifier)
        with patch('videomate.migration.process_file', wraps=process_file) as process:
            self.assertEqual(f.run_job(retry_id=identifier), 0)
        process.assert_not_called()
        self.assertNotIn(identifier, SESSION_RETRIES)

    def test_restart_accepts_only_the_historical_strict_size_default(self):
        f = self.f
        files = [(p, p.relative_to(f.source), False) for p in sorted(f.source.iterdir())]
        arguments = (f.workspace, files, [], f.source, f.workspace / 'recovered')
        old = MigrationJournal(*arguments, {'recovery': {'strategy': 'auto'}}, threading.Event(),
                               persistent=True, passphrase='invented migration passphrase')
        identifier = old.id
        old.close()
        resumed = MigrationJournal(*arguments, {'recovery': {'strategy': 'auto', 'size_policy': 'strict'}}, threading.Event(),
                                   persistent=True, identifier=identifier, passphrase='invented migration passphrase')
        resumed.close()
        with self.assertRaises(VideoMateError):
            MigrationJournal(*arguments, {'recovery': {'strategy': 'auto', 'size_policy': 'best_effort'}}, threading.Event(),
                             persistent=True, identifier=identifier, passphrase='invented migration passphrase')

    def test_summary_keeps_omissions_and_hardware_evidence(self):
        identifier = self.make_excluded()
        result = summarize(LIVE_REPORTS[identifier][2])
        self.assertIn('omissions', result['title'])
        self.assertIn('excluded 1', result['text'])
        self.assertIn('Hardware decode: disabled', result['text'])
        self.assertNotIn('PRIVATE_CANARY', result['text'])

    def test_backend_start_failure_is_operational_and_retried(self):
        from videomate.inspection import _fingerprint
        f = self.f
        video = f.source / 'invented.mp4'
        video.write_bytes(b'Generated marker for mocked inspection')
        calls = []
        def inspect(inspector, path, *args):
            calls.append(True)
            r = ScanResult(integrity='no_errors_detected', fingerprint=_fingerprint(path), streams=[
                dict(index=0, kind='video', codec='h264', coverage='full', decode_status='no_errors_detected')])
            if len(calls) == 1:
                r.state, r.integrity = 'failed', 'inconclusive'
                record_trace(r, worker_trace('inspection', outcome='failed', error_code='backend_unavailable'))
            return r
        with patch('videomate.migration.Inspector.inspect', autospec=True, side_effect=inspect):
            self.assertEqual(f.run_job(), 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(any('temporary failure [backend_unavailable]' in m for m in f.messages))


class AuditPolicyTests(unittest.TestCase):
    def test_size_estimate_fallback_is_explicit_and_strict_stays_strict(self):
        r = ScanResult(streams=[dict(index=0, kind='video', codec='h264', width=128, height=128, pixel_format='yuv420p')])
        options = RecoveryOptions(profile='compatible_sdr', rate_control='source_size')
        with self.assertRaises(VideoMateError) as caught:
            video_rates(r, r.streams, options)
        self.assertEqual(caught.exception.code, 'rate_target_unavailable')
        self.assertGreater(video_rates(r, r.streams, replace(options, size_policy='best_effort'))[0], 0)
        self.assertTrue(r.technical['size_estimate_fallback'])

    def test_refusal_is_specific_and_exportable(self):
        from videomate.diagnostics import create_export, environment
        from uuid import uuid4
        r = ScanResult(integrity='unreadable')
        with self.assertRaises(VideoMateError) as caught:
            plan(r, RecoveryOptions())
        self.assertEqual(caught.exception.code, 'plan_input_unreadable')
        record_trace(r, worker_trace('plan', outcome='blocked', error_code=caught.exception.code))
        self.assertIn(b'plan_input_unreadable', create_export([r], uuid4(), b'x'*32, environment('9.0.2','9.0.2'), synthetic=True))

    def test_hardware_counter_measures_overlap_without_device_identifiers(self):
        from videomate.hardware_activity import HardwareActivity
        a = HardwareActivity()
        one, two = a.gate(1, 2), a.gate(2, 2)
        one.acquire(); two.acquire(); one.acquire()
        self.assertEqual((a.peak_jobs, a.peak_routes, one.peak), (3, 2, 2))
        one.release(); one.release(); two.release()
        self.assertEqual(sum(a.active.values()), 0)
