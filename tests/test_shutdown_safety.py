"""Fault injection uses owned marker files and generated video only."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videomate.errors import VideoMateError
from videomate.hardware import qualification_scratch, select_decoder, select_encoder
from videomate.inspection import Inspector
from videomate.policy import SyntheticScope, create_workspace
from videomate.private_state import MemoryJob
from videomate.runner import Runner


class ShutdownSafetyTests(unittest.TestCase):
    def test_shutdown_failure_blocks_future_jobs_even_when_logging_also_fails(self):
        from videomate.execution import processing_session
        from videomate.jobs import Job
        from videomate.local_scan import run_job
        with tempfile.TemporaryDirectory(prefix="videomate-shutdown-log-generated-") as temporary:
            root = Path(temporary).resolve()
            workspace = create_workspace(root / "workspace", root / "code")
            source = root / "generated.mp4"
            source.write_bytes(b"Generated marker; never decoded")
            fake = root / "generated.exe"
            fake.write_bytes(b"Generated executable placeholder; never launched")
            bundle = SimpleNamespace(ffmpeg=fake, ffprobe=fake, version="0.0.0")
            for fault in ("interrupted_write", "close"):
                with self.subTest(fault=fault):
                    job = Job.create(workspace, [source], {"scope": "local_files", "sensitive": False,
                        "timeout": 1, "depth": "full", "cpu_threads": 1, "max_runners": 1})
                    blocked = threading.Event()
                    def failed(inspector, *_):
                        inspector.backend.runner.cleanup_blocked.set()
                        raise VideoMateError("worker_cleanup_failed")
                    def write(event, *_):
                        if fault == "interrupted_write" and event == "interrupted":
                            raise OSError("Generated log-write failure")
                    try:
                        with patch("videomate.local_scan.load_bundle", return_value=bundle), \
                                patch("videomate.local_scan.Inspector.inspect", autospec=True, side_effect=failed), \
                                patch("videomate.local_scan.EventLog") as log, \
                                patch("videomate.execution._PROCESSING_BLOCKED", blocked), \
                                patch("videomate.local_scan.export_job") as export:
                            log.return_value.write.side_effect = write
                            if fault == "close":
                                log.return_value.close.side_effect = OSError("Generated log-close failure")
                            with self.assertRaises(VideoMateError) as failure:
                                run_job(job, emit=lambda _: None)
                            self.assertEqual(failure.exception.code, "worker_cleanup_failed")
                            self.assertTrue(blocked.is_set())
                            log.return_value.close.assert_called_once()
                            export.assert_not_called()
                            with self.assertRaises(VideoMateError) as next_failure:
                                with processing_session(workspace):
                                    self.fail("An unconfirmed worker must block a new coordinator")
                            self.assertEqual(next_failure.exception.code, "worker_cleanup_failed")
                    finally:
                        job.close()

    def test_shared_runner_poison_blocks_new_workers_and_retains_session(self):
        with tempfile.TemporaryDirectory(prefix="videomate-shutdown-generated-") as temporary:
            root = Path(temporary).resolve()
            workspace = create_workspace(root / "workspace", root / "code")
            job = MemoryJob.create(workspace, [], {})
            cancel = threading.Event()
            runner = Runner(cancel_event=cancel, cleanup_blocked=job.cleanup_blocked)
            sibling = Runner(cleanup_blocked=job.cleanup_blocked)
            marker = job.directory / "owned-marker"
            marker.write_bytes(b"Invented candidate; no worker launched")
            with patch.object(runner, "_run", side_effect=VideoMateError("worker_cleanup_failed")):
                with self.assertRaises(VideoMateError):
                    runner.run([], root)
            self.assertTrue(cancel.is_set())
            with patch.object(sibling, "_run") as launch:
                with self.assertRaises(VideoMateError):
                    sibling.run([], root)
                launch.assert_not_called()
            with self.assertRaises(VideoMateError) as failure:
                job.close()
            self.assertEqual(failure.exception.code, "worker_cleanup_failed")
            self.assertTrue(marker.is_file())

    def test_inspection_and_hardware_do_not_hide_shutdown_failure(self):
        with tempfile.TemporaryDirectory(prefix="videomate-shutdown-generated-") as temporary:
            root = Path(temporary).resolve()
            source = root / "invented.mp4"
            source.write_bytes(b"Invented probe marker")
            backend = SimpleNamespace(ffmpeg=root / "fake", scratch=root, runner=Runner())
            scope = SyntheticScope(frozenset({source}))
            with patch.object(Inspector, "_inspect", side_effect=VideoMateError("worker_cleanup_failed")):
                with self.assertRaises(VideoMateError):
                    Inspector(backend, scope).inspect(source)
            for select in (select_decoder, select_encoder):
                with patch.object(Runner, "_run", side_effect=VideoMateError("worker_cleanup_failed")):
                    with self.assertRaises(VideoMateError):
                        select(backend)

    def test_qualification_staging_only_removed_after_confirmed_shutdown(self):
        with tempfile.TemporaryDirectory(prefix="videomate-shutdown-generated-") as temporary:
            root = Path(temporary)
            runner = Runner()
            with qualification_scratch(runner, root, "owned-") as normal:
                (normal / "marker").write_bytes(b"generated")
            self.assertFalse(normal.exists())
            with qualification_scratch(runner, root, "owned-") as retained:
                runner.cleanup_blocked.set()
            self.assertTrue(retained.exists())

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_FFMPEG"), "Generated-media backend not configured")
    def test_recovery_never_retries_or_unlinks_an_unconfirmed_worker_candidate(self):
        from test_recovery_integration import RecoveryIntegrationTests
        from videomate.recovery import RecoveryEngine, RecoveryOptions
        fixture = RecoveryIntegrationTests()
        try:
            fixture.setUp()
            result = Inspector(fixture.backend, fixture.scope).inspect(fixture.source)
            def failed(args, *unused, **kwargs):
                kwargs["watch_file"].write_bytes(b"Invented live-worker marker")
                raise VideoMateError("worker_cleanup_failed")
            with patch.object(fixture.backend.runner, "run", side_effect=failed) as run:
                with self.assertRaises(VideoMateError):
                    RecoveryEngine(fixture.backend, fixture.scope, fixture.candidates, fixture.outputs, fixture.root / "code").recover(
                        fixture.source, result, RecoveryOptions(force=True, strategy="reencode", hardware_encoding=False))
                self.assertEqual(run.call_count, 1)
            self.assertEqual(len(list(fixture.candidates.iterdir())), 1)
            self.assertEqual(list(fixture.outputs.iterdir()), [])
        finally:
            fixture.doCleanups()
