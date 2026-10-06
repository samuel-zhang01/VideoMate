import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from videomate.backend import FFmpegBackend
from videomate.cli import main
from videomate.errors import VideoMateError
from videomate.policy import SyntheticScope, create_workspace
from videomate.runner import ProcessResult, Runner, worker_environment


class CLITests(unittest.TestCase):
    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_missing_workspace_rejects_without_reading(self):
        with patch.object(Path, "stat", side_effect=AssertionError("No path access allowed")):
            code, out, err = self.invoke(["scan", "--input", "PRIVATE_INPUT_CANARY"])
        self.assertEqual(code, 2)
        self.assertNotIn("PRIVATE_INPUT_CANARY", out + err)
        self.assertIn("Invalid arguments", err)

    def test_parser_does_not_echo_unknown_private_arguments(self):
        for args in (["PRIVATE_COMMAND"], ["scan", "--input", "PRIVATE_FILE", "--depth", "PRIVATE_DEPTH"],
                     ["demo", "--PRIVATE_ARGUMENT"]):
            code, out, err = self.invoke(args)
            self.assertEqual(code, 2)
            self.assertNotIn("PRIVATE", out + err)

    def test_demo_and_export_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="videomate-synthetic-") as temporary:
            dest = Path(temporary) / "synthetic-diagnostics.json"
            code, out, err = self.invoke(["demo", "--export", str(dest)])
            self.assertEqual(code, 1)
            self.assertIn("scripted", out)
            data = dest.read_bytes()
            self.assertNotIn(b"SYNTHETIC_PRIVATE", data)
            self.assertEqual(self.invoke(["validate-export", str(dest)])[0], 0)
            self.assertEqual(self.invoke(["demo", "--export", str(dest)])[0], 2)
            self.assertEqual(dest.read_bytes(), data)

    def test_invalid_json_no_echo(self):
        with tempfile.TemporaryDirectory(prefix="videomate-synthetic-") as temporary:
            source = Path(temporary) / "PRIVATE_CANARY.json"
            source.write_text('{"private": "PRIVATE_CANARY"}')
            code, out, err = self.invoke(["validate-export", str(source)])
            self.assertEqual(code, 2)
            self.assertNotIn("PRIVATE_CANARY", out + err)

    def test_doctor_is_honest_about_readiness(self):
        with patch("videomate.setup_local.check_backend", side_effect=VideoMateError("dependency_unavailable")):
            code, out, err = self.invoke(["doctor"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["sensitive_treatment"], "available")
        self.assertEqual(json.loads(out)["os_sandbox"], "not_implemented")

    def test_private_internal_exception_is_not_printed(self):
        with patch("videomate.cli.run_demo", side_effect=RuntimeError("PRIVATE_ERROR_CANARY")):
            code, out, err = self.invoke(["demo"])
        self.assertEqual(code, 2)
        self.assertNotIn("PRIVATE_ERROR_CANARY", out + err)
        self.assertNotIn("Traceback", err)

    def test_workspace_rejects_source_sync_and_existing(self):
        with tempfile.TemporaryDirectory(prefix="videomate-synthetic-") as temporary:
            base = Path(temporary).resolve()
            for destination, source in ((base / "inside", base),
                                        (base / "OneDrive" / "private", base / "code"),
                                        (base, base / "code")):
                with self.assertRaises(VideoMateError):
                    create_workspace(destination, source)
            output = create_workspace(base / "private", base / "code")
            self.assertTrue((output / "state").is_dir())
            self.assertTrue((output / "export-review").is_dir())

    def test_workspace_rejects_repository_ancestor_even_from_archive(self):
        with tempfile.TemporaryDirectory(prefix="videomate-synthetic-") as temporary:
            base = Path(temporary).resolve()
            (base / "pyproject.toml").write_text("# synthetic source marker")
            with self.assertRaises(VideoMateError):
                create_workspace(base / "private", base / "dist")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videomate-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.scratch = Path(self.temp.name).resolve()

    def run_code(self, code, runner=None):
        return (runner or Runner(timeout=10)).run([sys.executable, "-I", "-c", code], self.scratch)

    def test_worker_pipes_and_safe_repr(self):
        outcome = self.run_code("import sys; print('PRIVATE_STDOUT'); print('PRIVATE_STDERR', file=sys.stderr)")
        self.assertEqual(outcome.returncode, 0)
        self.assertIn(b"PRIVATE_STDOUT", outcome.stdout)
        self.assertIn(b"PRIVATE_STDERR", outcome.stderr)
        self.assertNotIn("PRIVATE", repr(outcome))

    def test_environment_not_inherited(self):
        with patch.dict(os.environ, {"FFREPORT": "file=PRIVATE_LOG", "SYNTHETIC_SECRET": "PRIVATE_SECRET", "HTTP_PROXY": "PRIVATE_PROXY"}):
            outcome = self.run_code("import os; print(any(k in os.environ for k in ('FFREPORT','SYNTHETIC_SECRET','HTTP_PROXY')))")
        self.assertEqual(outcome.stdout.strip(), b"False")
        self.assertNotIn("PATH", worker_environment(self.scratch))

    def test_output_limit_both_pipes(self):
        outcome = self.run_code("import sys; sys.stdout.write('x'*100000); sys.stderr.write('y'*100000)", Runner(timeout=10, output_limit=1024))
        self.assertTrue(outcome.limited)
        self.assertLessEqual(len(outcome.stdout), 1024)
        self.assertLessEqual(len(outcome.stderr), 1024)

    def test_timeout(self):
        started = time.monotonic()
        outcome = self.run_code("import time; time.sleep(20)", Runner(timeout=0.3))
        self.assertTrue(outcome.limited)
        self.assertLess(time.monotonic() - started, 8)

    def test_low_output_disk_stops_generated_worker_with_closed_reason(self):
        started = time.monotonic()
        with patch("videomate.runner.shutil.disk_usage", return_value=Mock(free=1024)):
            outcome = Runner(timeout=10).run([sys.executable, "-I", "-c", "import time; time.sleep(20)"], self.scratch,
                watch_file=self.scratch / "generated-candidate.bin", max_file_bytes=1024**2)
        self.assertTrue(outcome.limited)
        self.assertEqual(outcome.limit_reason, "disk_limit")
        self.assertLess(time.monotonic() - started, 8)

    def test_fast_generated_output_is_rejected_at_candidate_cap(self):
        outcome = Runner(timeout=10).run([sys.executable, "-I", "-c",
            "from pathlib import Path; Path('generated-candidate.bin').write_bytes(b'x'*4096)"], self.scratch,
            watch_file=self.scratch / "generated-candidate.bin", max_file_bytes=4096)
        self.assertTrue(outcome.limited)
        self.assertEqual(outcome.limit_reason, "candidate_limit")

    def test_posix_group_permission_race_only_tolerates_an_exited_worker(self):
        from videomate.runner import _terminate_tree
        for returncode in (0, None):
            with self.subTest(returncode=returncode):
                process = Mock(pid=12345)
                process.poll.return_value = returncode
                with patch("videomate.runner.os.name", "posix"), patch("videomate.runner.signal.SIGKILL", 9, create=True), \
                        patch("videomate.runner.os.killpg", create=True, side_effect=PermissionError):
                    if returncode is None:
                        with self.assertRaises(PermissionError):
                            _terminate_tree(process)
                    else:
                        _terminate_tree(process)
                process.kill.assert_not_called()

    def test_windows_job_waits_for_exit_and_fails_closed_if_unconfirmed(self):
        from videomate.windows_job import WindowsJob
        for scenario in ("drained", "terminate_failed", "query_failed", "timeout"):
            with self.subTest(scenario=scenario):
                job = WindowsJob.__new__(WindowsJob)
                job.handle = 12345
                job.api = Mock()
                job.api.TerminateJobObject.return_value = scenario != "terminate_failed"
                remaining = iter((1, 0))
                def query(handle, kind, state, size, returned):
                    state._obj.ActiveProcesses = next(remaining) if scenario == "drained" else 1
                    return scenario != "query_failed"
                job.api.QueryInformationJobObject.side_effect = query
                with patch("videomate.windows_job.time.sleep"), patch("videomate.windows_job.time.monotonic", side_effect=(0, 1, 6)):
                    if scenario == "drained":
                        job.close()
                        self.assertEqual(job.api.QueryInformationJobObject.call_count, 2)
                    else:
                        with self.assertRaises(VideoMateError) as error:
                            job.close()
                        self.assertEqual(error.exception.code, "worker_cleanup_failed")
                job.api.CloseHandle.assert_called_once_with(12345)
                self.assertIsNone(job.handle)

    def test_failed_windows_assignment_requires_confirmed_worker_shutdown(self):
        from videomate.runner import _discard_unassigned_worker
        for scenario in ("exited_during_assignment", "wait_timeout", "job_close_failed"):
            with self.subTest(scenario=scenario):
                process, job = Mock(), Mock()
                if scenario == "exited_during_assignment":
                    process.kill.side_effect = ProcessLookupError
                elif scenario == "wait_timeout":
                    process.wait.side_effect = subprocess.TimeoutExpired("synthetic worker", 5)
                else:
                    job.close.side_effect = VideoMateError("worker_cleanup_failed")
                if scenario == "exited_during_assignment":
                    _discard_unassigned_worker(process, job)
                else:
                    with self.assertRaises(VideoMateError) as failure:
                        _discard_unassigned_worker(process, job)
                    self.assertEqual(failure.exception.code, "worker_cleanup_failed")
                process.wait.assert_called_once_with(timeout=5)
                job.close.assert_called_once()
                process.stdout.close.assert_called_once()
                process.stderr.close.assert_called_once()

    def test_shell_metacharacters_remain_literal(self):
        marker = "$(SYNTHETIC_CANARY); & echo x"
        outcome = Runner(timeout=10).run([sys.executable, "-I", "-c", "import sys; print(sys.argv[1])", marker], self.scratch)
        self.assertEqual(outcome.stdout.decode().strip(), marker)

    def test_backend_command_maps_selected_stream_and_no_metadata_tags(self):
        class Recorder:
            def run(self, args, scratch, *, media_output=False):
                self.args = args
                self.media_output = media_output
                return ProcessResult(0)
        recorder = Recorder()
        source = self.scratch / "synthetic-marker.bin"
        source.write_bytes(b"synthetic marker")
        scope = SyntheticScope(frozenset({source}))
        backend = FFmpegBackend(Path(sys.executable).resolve(), Path(sys.executable).resolve(), self.scratch, recorder, scope=scope)
        backend.probe(source)
        self.assertFalse(recorder.media_output)
        self.assertNotIn("tags", recorder.args[recorder.args.index("-show_entries") + 1])
        self.assertIn("-protocol_whitelist", recorder.args)
        backend.decode(source, 3)
        self.assertTrue(recorder.media_output)
        self.assertEqual(recorder.args[recorder.args.index("-map") + 1], "0:3")
        self.assertNotIn("-c", recorder.args)  # Decode, never stream-copy as a health check.

    def test_native_backend_is_also_gated_by_default(self):
        backend = FFmpegBackend(Path(sys.executable).resolve(), Path(sys.executable).resolve(), self.scratch)
        with patch.object(backend.runner, "run", side_effect=AssertionError("Worker must not start")):
            with self.assertRaisesRegex(VideoMateError, "Select local files"):
                backend.probe(Path("NEVER_READ_THIS"))

    def test_backend_rejects_shell_wrapper(self):
        wrapper = self.scratch / "synthetic.cmd"
        wrapper.write_text("synthetic")
        with self.assertRaises(VideoMateError):
            FFmpegBackend(wrapper, wrapper, self.scratch)

    def test_descendant_holding_pipe_is_terminated(self):
        # Only a generated worker and its child, not any user process.
        script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(20)']); print('spawned',flush=True); time.sleep(20)"
        started = time.monotonic()
        outcome = self.run_code(script, Runner(timeout=1.0))
        self.assertTrue(outcome.limited)
        self.assertIn(b"spawned", outcome.stdout)
        self.assertLess(time.monotonic() - started, 8)
