import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from videomate.cli import main
from videomate.discovery import discover
from videomate.errors import VideoMateError
from videomate.jobs import Job, job_lock, pack_result, unpack_result
from videomate.models import ScanResult
from videomate.policy import create_workspace
from videomate.runner import Runner


class JobAndLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videomate-synthetic-jobs-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = create_workspace(self.root / "workspace", self.root / "code")
        self.source = self.root / "generated.mp4"
        self.source.write_bytes(b"Generated marker, never decoded")

    def test_job_roundtrip_and_lock_contention(self):
        job = Job.create(self.workspace, [self.source], {"scope": "non_sensitive_tests"})
        self.addCleanup(job.close)
        with job_lock(job.directory):
            with self.assertRaises(VideoMateError):
                with job_lock(job.directory):
                    self.fail("The second writer acquired the job lock")
            job.save(1, "done", ScanResult(integrity="unreadable"))
        self.assertEqual(unpack_result(job.rows()[0]["result"]).integrity, "unreadable")
        with job_lock(job.directory):
            self.assertEqual(job.settings()["scope"], "non_sensitive_tests")

    def test_thousand_generated_layout_entries_roundtrip_and_update(self):
        # Locator strings and the marker are invented here; no media is decoded.
        settings = {"scope": "local_files", "sensitive": False,
                    "private_output_layout": {str(i): f"generated/output-name-{i:04d}.mp4" for i in range(1, 1001)}}
        self.assertGreater(len(json.dumps(settings).encode()), 16384)
        job = Job.create(self.workspace, [self.source], settings)
        self.addCleanup(job.close)
        self.assertEqual(job.settings(), settings)
        settings["backend_version"] = "0.0.0"
        job.update_settings(settings)
        self.assertEqual(job.settings(), settings)

    def test_oversized_settings_do_not_create_or_change_jobs(self):
        settings = {"scope": "non_sensitive_tests"}
        job = Job.create(self.workspace, [self.source], settings)
        self.addCleanup(job.close)
        before = set((self.workspace / "jobs").iterdir())
        # Reduce the same production bound for this fault injection so the test
        # exercises rejection without manufacturing a multi-megabyte document.
        oversized = {**settings, "generated_marker": "x" * 1024}
        with patch("videomate.jobs.MAX_JOB_SETTINGS_BYTES", 512):
            for action in (lambda: Job.create(self.workspace, [self.source], oversized),
                           lambda: job.update_settings(oversized)):
                with self.assertRaises(VideoMateError) as failure:
                    action()
                self.assertEqual(failure.exception.code, "job_invalid")
            self.assertEqual(job.settings(), settings)
        self.assertEqual(set((self.workspace / "jobs").iterdir()), before)

    def test_job_identifiers_cannot_escape_workspace(self):
        for identifier in ("../private", "x" * 32, "a" * 31):
            with self.assertRaises(VideoMateError):
                Job(self.workspace, identifier)

    def test_private_job_result_cannot_inject_console_or_export_values(self):
        encoded = pack_result(ScanResult(integrity="PRIVATE_CANARY"))
        with self.assertRaises(VideoMateError):
            unpack_result(encoded)

    def test_recursive_discovery_is_explicit_and_excludes_workspace(self):
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "created.flv").write_bytes(b"synthetic marker")
        (nested / "ignore.txt").write_text("synthetic")
        (self.workspace / "recovered" / "never-traverse.mp4").write_bytes(b"synthetic marker")
        with self.assertRaises(VideoMateError):
            discover([str(self.root)], self.workspace, self.root / "code")
        found = discover([str(self.root)], self.workspace, self.root / "code", recursive=True)
        self.assertEqual(set(found), {self.source, nested / "created.flv"})

    def test_duplicate_explicit_inputs_are_scanned_once(self):
        found = discover([str(self.source), str(self.source)], self.workspace, self.root / "code")
        self.assertEqual(found, [self.source])

    def test_discovery_prunes_mounts_without_pathlib_mount_support(self):
        nested = self.root / "mounted"
        nested.mkdir()
        (nested / "generated.flv").write_bytes(b"synthetic marker")
        with patch.object(Path, "is_mount", side_effect=NotImplementedError), \
                patch("videomate.discovery.os.path.ismount", side_effect=lambda path: path == nested):
            found = discover([str(self.root)], self.workspace, self.root / "code", recursive=True)
        self.assertEqual(found, [self.source])

    def test_missing_workspace_rejects_before_any_path_access(self):
        for command, target in (("recover", ["--input", "PRIVATE_FILE"]), ("resume", ["--job", "a" * 32]), ("report", ["--job", "a" * 32])):
            out = io.StringIO()
            with patch.object(Path, "stat", side_effect=AssertionError("No source/state read allowed")), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                self.assertEqual(main([command, *target]), 2)
            self.assertNotIn("PRIVATE", out.getvalue())

    def test_cancellation_stops_worker(self):
        event = threading.Event()
        timer = threading.Timer(0.15, event.set)
        timer.start()
        try:
            with self.assertRaises(KeyboardInterrupt):
                Runner(timeout=20, cancel_event=event).run([sys.executable, "-I", "-c", "import time; time.sleep(30)"], self.root)
        finally:
            timer.cancel()

    def test_candidate_disk_budget_is_enforced_even_if_worker_exits_zero(self):
        output = self.root / "generated-output.bin"
        code = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'x'*8192)"
        result = Runner(timeout=10).run([sys.executable, "-I", "-c", code, str(output)], self.root, watch_file=output, max_file_bytes=4096)
        self.assertTrue(result.limited)
