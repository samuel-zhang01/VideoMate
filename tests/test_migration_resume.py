"""Disconnect/crash tests use only generated markers in owned temporary trees."""
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videomate.errors import VideoMateError
from videomate.execution import processing_session
from videomate.inspection import _fingerprint
from videomate.migration import migrate_local, process_file, publish, write_status
from videomate.migration_resume import MigrationJournal, SESSION_RETRIES, sweep_staging
from videomate.models import ScanResult
from videomate.private_state import LIVE_REPORTS, MemoryJob
from videomate.setup_local import ensure_workspace
from videomate.trace import record_trace, worker_trace


class FastCancel(threading.Event):
    def wait(self, timeout=None):
        return self.is_set()


class MigrationResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='videomate-resume-generated-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'PRIVATE_CANARY'
        self.source.mkdir()
        for i in range(3):
            (self.source / f'PRIVATE_CANARY_{i}.txt').write_bytes(f'Invented marker {i}'.encode())
        self.workspace = ensure_workspace(self.root / 'workspace')
        executable = self.root / 'never-run.exe'
        executable.write_bytes(b'Generated stub; never executed')
        self.bundle = SimpleNamespace(ffmpeg=executable, ffprobe=executable, version='9.0.2')
        self.messages = []
        self.addCleanup(LIVE_REPORTS.clear)
        self.addCleanup(SESSION_RETRIES.clear)

    def run_job(self, **kwargs):
        with patch('videomate.migration.load_bundle', return_value=self.bundle):
            return migrate_local([str(self.source)], self.workspace, sensitive=True, local_names=True,
                                 hardware_decoding=False, max_runners=1, cancel_event=FastCancel(),
                                 emit=self.messages.append, **kwargs)

    def identifier(self):
        return next(m[5:] for m in self.messages if m.startswith('Job: '))

    def test_invalid_migration_controls_fail_before_source_inventory(self):
        for controls in ({'execute': 'false'}, {'recovery': {'strategy': 'auto'}},
                         {'recovery': False}, {'export_on_completion': 'yes'}):
            with self.subTest(controls=controls), self.assertRaises(VideoMateError) as caught:
                self.run_job(**controls)
            self.assertIn(caught.exception.code, {'invalid_arguments', 'settings_invalid'})

    def test_direct_package_continues_in_session_without_overwriting_verified_output(self):
        destination = self.root / 'destination'
        def stop_after_first_copy(candidate, target):
            publish(candidate, target)
            raise KeyboardInterrupt()
        with patch('videomate.migration.publish', side_effect=stop_after_first_copy):
            with self.assertRaises(KeyboardInterrupt):
                self.run_job(package_layout='direct', recovered_dir=str(destination))
        identifier = self.identifier()
        self.assertEqual(SESSION_RETRIES[identifier]['mode'], 'continue')
        first = next(destination.glob('*.txt'))
        original = (first.read_bytes(), first.stat().st_mtime_ns)
        self.assertEqual(self.run_job(package_layout='direct', recovered_dir=str(destination), retry_id=identifier), 0)
        self.assertEqual(len(list(destination.glob('*.txt'))), 3)
        self.assertEqual((first.read_bytes(), first.stat().st_mtime_ns), original)

    def test_direct_private_checkpoint_resumes_after_session_is_gone(self):
        destination = self.root / 'destination'
        def stop_after_first_copy(candidate, target):
            publish(candidate, target)
            raise KeyboardInterrupt()
        with patch('videomate.migration.publish', side_effect=stop_after_first_copy):
            with self.assertRaises(KeyboardInterrupt):
                self.run_job(package_layout='direct', recovered_dir=str(destination),
                             private_resume=True, passphrase='invented passphrase only')
        identifier = self.identifier()
        checkpoint = self.workspace / 'state' / ('migration-' + identifier + '.sqlite3')
        self.assertTrue(checkpoint.exists())
        SESSION_RETRIES.clear()  # Simulate a new application process.
        self.assertEqual(self.run_job(package_layout='direct', recovered_dir=str(destination),
                                      checkpoint_id=identifier, passphrase='invented passphrase only'), 0)
        self.assertEqual(len(list(destination.glob('*.txt'))), 3)
        self.assertFalse(checkpoint.exists())

    def test_session_only_job_cannot_be_resumed_after_session_is_gone(self):
        destination = self.root / 'destination'
        def stop_after_first_copy(candidate, target):
            publish(candidate, target)
            raise KeyboardInterrupt()
        with patch('videomate.migration.publish', side_effect=stop_after_first_copy):
            with self.assertRaises(KeyboardInterrupt):
                self.run_job(package_layout='direct', recovered_dir=str(destination))
        identifier = self.identifier()
        SESSION_RETRIES.clear()  # A diagnostic log cannot recreate this snapshot.
        with self.assertRaises(VideoMateError) as caught:
            self.run_job(package_layout='direct', recovered_dir=str(destination),
                         checkpoint_id=identifier, passphrase='invented passphrase only')
        self.assertEqual(caught.exception.code, 'checkpoint_invalid')

    def test_private_checkpoint_remains_after_completed_needs_review_package(self):
        destination = self.root / 'destination'
        def unresolved(backend, item, **kwargs):
            result = ScanResult(state='failed', integrity='unreadable')
            result.fingerprint = _fingerprint(item[1])
            result.technical['source_size'] = result.fingerprint[2]
            result.technical['migration'] = {'input_kind': 'other', 'action': 'excluded_unresolved',
                'copy_check': 'not_run', 'timestamps': 'not_requested', 'reason': 'recovery_unverified'}
            return result
        with patch('videomate.migration.process_file', side_effect=unresolved):
            self.assertEqual(self.run_job(package_layout='direct', recovered_dir=str(destination),
                                          private_resume=True, passphrase='invented passphrase only'), 1)
        identifier = self.identifier()
        self.assertTrue((self.workspace / 'state' / ('migration-' + identifier + '.sqlite3')).exists())
        self.assertTrue(any('Private restart checkpoint retained.' in message for message in self.messages))

    def test_failed_package_setup_does_not_claim_restart_checkpoint(self):
        with patch.object(MigrationJournal, 'initialize_package', side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.run_job(package_layout='direct', recovered_dir=str(self.root / 'destination'),
                             private_resume=True, passphrase='invented passphrase only')
        self.assertFalse(any('Private restart checkpoint retained.' in message for message in self.messages))
        self.assertTrue(any('Private checkpoint setup did not finish.' in message for message in self.messages))

    def test_restart_adopts_verified_publication_after_crash_without_overwrite(self):
        def crash(candidate, target):
            publish(candidate, target)
            raise KeyboardInterrupt()
        with patch('videomate.migration.publish', side_effect=crash):
            with self.assertRaises(KeyboardInterrupt):
                self.run_job(private_resume=True, passphrase='invented passphrase only')
        identifier = self.identifier()
        package = self.workspace / 'recovered' / ('migration-' + identifier)
        first = next(package.glob('*.txt'))
        before = (first.read_bytes(), first.stat().st_mtime_ns)
        journal = self.workspace / 'state' / ('migration-' + identifier + '.sqlite3')
        encoded = journal.read_bytes()
        for forbidden in (b'PRIVATE_CANARY', str(self.source).encode(), b'invented passphrase only',
                          hashlib.sha256(before[0]).hexdigest().encode()):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(self.run_job(private_resume=True, checkpoint_id=identifier, passphrase='invented passphrase only'), 0)
        self.assertEqual(len(list(package.glob('*.txt'))), 3)
        self.assertFalse(journal.exists())
        self.assertEqual((first.read_bytes(), first.stat().st_mtime_ns), before)
        self.assertEqual(len(list((self.workspace / 'recovered').glob('migration-*'))), 3)  # package, status, ownership
        self.assertNotIn('PRIVATE_CANARY', '\n'.join(self.messages))

    def test_transient_failures_get_three_retries_then_remain_failed(self):
        calls = []
        def fail(backend, item, **kwargs):
            calls.append(item[0])
            result = ScanResult(state='failed', integrity='unreadable')
            result.technical['migration'] = {'input_kind': 'other', 'action': 'failed', 'copy_check': 'not_run',
                                            'timestamps': 'not_requested', 'reason': 'output_busy'}
            return result
        with patch('videomate.migration.process_file', side_effect=fail):
            self.assertEqual(self.run_job(), 2)
        self.assertEqual({i: calls.count(i) for i in range(1, 4)}, {1: 4, 2: 4, 3: 4})
        self.assertEqual(len(list(self.source.iterdir())), 3)
        self.assertEqual(list((self.workspace / 'state').iterdir()), [])

    def test_reconnect_wait_then_rediscovery_preserves_original_package(self):
        calls = []
        def transient(backend, item, **kwargs):
            calls.append(item[0])
            if len(calls) == 1:
                result = ScanResult(state='failed', integrity='unreadable')
                result.technical['migration'] = {'input_kind': 'other', 'action': 'failed', 'copy_check': 'not_run',
                                                'timestamps': 'not_requested', 'reason': 'source_read_failed'}
                return result
            return process_file(backend, item, **kwargs)
        original_check = MigrationJournal.check_storage
        checks = []
        def storage(journal):
            checks.append(True)
            if len(checks) == 1:
                raise OSError('Invented disconnect')
            return original_check(journal)
        with patch('videomate.migration.process_file', side_effect=transient), patch.object(MigrationJournal, 'check_storage', storage):
            self.assertEqual(self.run_job(), 0)
        self.assertEqual(calls, [1, 1, 2, 3])
        self.assertTrue(any('Storage unavailable' in m for m in self.messages))
        self.assertTrue(any('Rediscovery complete' in m for m in self.messages))

    def test_inspection_io_evidence_retries_instead_of_misclassifying_media(self):
        calls = []
        def transient(backend, item, **kwargs):
            calls.append(item[0])
            if len(calls) == 1:
                result = ScanResult(state='failed', integrity='unreadable')
                result.technical['migration'] = {'input_kind': 'other', 'action': 'excluded_unresolved', 'copy_check': 'not_run',
                                                'timestamps': 'not_requested', 'reason': 'recovery_unverified'}
                record_trace(result, worker_trace('inspection', outcome='failed', error_code='io_error'))
                return result
            return process_file(backend, item, **kwargs)
        with patch('videomate.migration.process_file', side_effect=transient):
            self.assertEqual(self.run_job(), 0)
        self.assertEqual(calls, [1, 1, 2, 3])

    def interrupted_complete(self):
        def interrupt(package, phase, *args):
            if phase == 'finished':
                raise KeyboardInterrupt()
            return write_status(package, phase, *args)
        with patch('videomate.migration.write_status', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_job(private_resume=True, passphrase='invented passphrase only')

    def test_wrong_passphrase_changed_output_and_foreign_owner_stop_resume(self):
        self.interrupted_complete()
        identifier = self.identifier()
        with self.assertRaises(VideoMateError) as caught:
            self.run_job(private_resume=True, checkpoint_id=identifier, passphrase='wrong invented passphrase')
        self.assertEqual(caught.exception.code, 'checkpoint_invalid')
        with self.assertRaises(VideoMateError) as caught:
            self.run_job(private_resume=True, checkpoint_id=identifier,
                         passphrase='invented passphrase only', unresolved='copy')
        self.assertEqual(caught.exception.code, 'checkpoint_policy_changed')
        package = self.workspace / 'recovered' / ('migration-' + identifier)
        target = next(package.glob('*.txt'))
        target.write_bytes(b'Changed generated output; must remain untouched')
        with self.assertRaises(VideoMateError) as caught:
            self.run_job(private_resume=True, checkpoint_id=identifier, passphrase='invented passphrase only')
        self.assertEqual(caught.exception.code, 'resume_output_conflict')
        self.assertEqual(target.read_bytes(), b'Changed generated output; must remain untouched')
        package.with_name(package.name + '.owner').write_bytes(b'foreign marker')
        with self.assertRaises(VideoMateError) as caught:
            self.run_job(private_resume=True, checkpoint_id=identifier, passphrase='invented passphrase only')
        self.assertEqual(caught.exception.code, 'resume_storage_changed')

    def test_changed_source_and_concurrent_coordinator_are_rejected(self):
        self.interrupted_complete()
        identifier = self.identifier()
        next(self.source.iterdir()).write_bytes(b'Changed generated input')
        with self.assertRaises(VideoMateError) as caught:
            self.run_job(private_resume=True, checkpoint_id=identifier, passphrase='invented passphrase only')
        self.assertEqual(caught.exception.code, 'checkpoint_sources_changed')
        with processing_session(self.workspace):
            with self.assertRaises(VideoMateError) as caught:
                self.run_job()
        self.assertEqual(caught.exception.code, 'job_busy')

    def test_wait_can_be_stopped_and_sweep_retains_unknown_or_live_worker_files(self):
        journal = object.__new__(MigrationJournal)
        journal.cancel = FastCancel()
        journal.check_storage = lambda: (_ for _ in ()).throw(OSError('Generated disconnect'))
        tracker = SimpleNamespace(update=lambda *a, **k: None)
        with patch.object(journal.cancel, 'wait', side_effect=lambda _: journal.cancel.set() or True):
            with self.assertRaises(KeyboardInterrupt):
                journal.wait_storage(self.messages.append, tracker)
        job = MemoryJob.create(self.workspace, [], {})
        staging = self.workspace / 'recovered' / ('candidates-' + '1' * 32)
        staging.mkdir()
        job.own_directory(staging)
        owned = staging / ('a' * 32 + '.part')
        owned.write_bytes(b'Generated partial candidate')
        unknown = staging / 'unrecognized'
        unknown.write_bytes(b'Generated unknown marker')
        job.cleanup_blocked.set()
        with self.assertRaises(VideoMateError) as caught:
            sweep_staging(job, staging, self.messages.append)
        self.assertEqual(caught.exception.code, 'worker_cleanup_failed')
        self.assertTrue(owned.exists())
        job.cleanup_blocked.clear()
        sweep_staging(job, staging, self.messages.append)
        self.assertFalse(owned.exists())
        job.close()
        self.assertTrue(unknown.exists())

    def test_private_manifest_above_1000_inputs_and_foreign_cleanup_root(self):
        for i in range(1001):
            (self.source / f'generated-{i}.txt').write_bytes(b'Generated scale marker')
        files = [(p, p.relative_to(self.source), False) for p in sorted(self.source.iterdir())]
        journal = MigrationJournal(self.workspace, files, [], self.source, self.workspace / 'recovered', {}, FastCancel(),
                                   persistent=True, passphrase='generated scale passphrase')
        identifier = journal.id
        self.assertEqual(len(journal.tokens), 1004)
        journal.close()
        resumed = MigrationJournal(self.workspace, files, [], self.source, self.workspace / 'recovered', {}, FastCancel(),
                                   persistent=True, passphrase='generated scale passphrase', identifier=identifier)
        self.assertEqual(len(resumed.tokens), 1004)
        resumed.close()
        job = MemoryJob.create(self.workspace, [], {})
        old = job.directory.with_name(job.directory.name + '-old')
        job.directory.rename(old)  # Only this newly generated fixture is moved.
        job.directory.mkdir()
        marker = job.directory / 'foreign-marker'
        marker.write_bytes(b'Generated replacement directory')
        with self.assertRaises(VideoMateError):
            job.close()
        self.assertTrue(marker.exists())

    def test_unconfirmed_shutdown_blocks_new_coordinators_in_same_process(self):
        with patch('videomate.execution._PROCESSING_BLOCKED', threading.Event()):
            with self.assertRaises(VideoMateError):
                with processing_session(self.workspace):
                    raise VideoMateError('worker_cleanup_failed')
            with self.assertRaises(VideoMateError) as caught:
                self.run_job()
            self.assertEqual(caught.exception.code, 'worker_cleanup_failed')
