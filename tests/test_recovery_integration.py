"""Real recovery tests. Every input is generated here, never operator-supplied."""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from videomate.backend import FFmpegBackend
from videomate.cli import main
from videomate.inspection import Inspector
from videomate.jobs import Job, unpack_result
from videomate.policy import SyntheticScope, create_workspace
from videomate.recovery import RecoveryEngine, RecoveryOptions
from videomate.runner import ProcessResult, Runner
from videomate.schema import load_json, validate_export


@unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_FFMPEG") and os.environ.get("VIDEOMATE_TEST_FFPROBE"), "Explicit generated-media backend not configured")
class RecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videomate-recovery-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "synthetic-private-canary.mkv"
        self.damaged = self.root / "synthetic-damaged.avi"
        self.workspace = create_workspace(self.root / "workspace", self.root / "code")
        self.scope = SyntheticScope(frozenset({self.source, self.damaged}))
        self.backend = FFmpegBackend(Path(os.environ["VIDEOMATE_TEST_FFMPEG"]), Path(os.environ["VIDEOMATE_TEST_FFPROBE"]), self.root, Runner(timeout=30), scope=self.scope)
        generated = self.backend.runner.run([str(self.backend.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-n", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2", "-c:v", "ffv1", "-c:a", "pcm_s16le", "-metadata", "title=synthetic-private-canary", str(self.source)], self.root)
        self.assertEqual(generated.returncode, 0)
        self.candidates, self.outputs = self.workspace / "jobs" / "candidates", self.workspace / "recovered"
        self.candidates.mkdir()

    def recover(self, source, options):
        original = Inspector(self.backend, self.scope).inspect(source)
        before = hashlib.sha256(source.read_bytes()).digest()
        engine = RecoveryEngine(self.backend, self.scope, self.candidates, self.outputs, self.root / "code")
        result = engine.recover(source, original, options)
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)
        self.assertNotIn("synthetic-private-canary", repr(result))
        return result

    def sample_hash(self, source):
        outcome = self.backend.runner.run([str(self.backend.ffmpeg), "-nostdin", "-v", "error", "-guess_layout_max", "0", "-i", str(source), "-map", "0:v", "-map", "0:a", "-c:v", "rawvideo", "-c:a", "pcm_s16le", "-f", "streamhash", "-hash", "sha256", "-"], self.root)
        self.assertEqual(outcome.returncode, 0)
        return outcome.stdout

    def test_remux_and_lossless_reencode_preserve_generated_decoded_samples(self):
        for strategy in ("remux", "reencode"):
            with self.subTest(strategy=strategy):
                result = self.recover(self.source, RecoveryOptions(strategy=strategy, force=True))
                self.assertEqual(result.recovery["recovery_state"], "verified_with_losses", result.recovery)
                self.assertEqual(result.recovery["losses"], ["metadata_removed"])
                output = Path(result.recovery["private_output"])
                self.assertEqual(self.sample_hash(self.source), self.sample_hash(output))

    def test_compatible_reencode_and_manual_interval(self):
        for options in (RecoveryOptions(strategy="reencode", profile="compatible_sdr", force=True),
                        RecoveryOptions(keep_start_us=400000, keep_end_us=1600000)):
            with self.subTest(profile=options.profile):
                result = self.recover(self.source, options)
                self.assertEqual(result.recovery["recovery_state"], "verified_with_losses", result.recovery)
                if options.keep_start_us is not None:
                    self.assertAlmostEqual(result.recovery["output_duration_us"], 1200000, delta=100000)
                    self.assertEqual(len(result.recovery["edits"]), 2)
                else:
                    self.assertIn("lossy_encoding", result.recovery["losses"])

    def test_hevc_reencode_matches_generated_geometry_and_uses_software_fallback(self):
        run = self.backend.runner.run
        def fail_hevc_hardware(args, scratch, **kwargs):
            if "hevc_nvenc" in args:
                return ProcessResult(1, stderr=b"SYNTHETIC_DRIVER_ERROR")
            return run(args, scratch, **kwargs)
        options = RecoveryOptions(strategy="reencode", profile="compatible_sdr", video_codec="hevc",
                                  audio_normalization="playback", force=True, hardware_encoding=True)
        with patch("videomate.recovery.select_encoder", return_value="hevc_nvenc"), \
                patch.object(self.backend.runner, "run", side_effect=fail_hevc_hardware):
            result = self.recover(self.source, options)
        self.assertEqual(result.recovery["recovery_state"], "verified_with_losses", result.recovery)
        self.assertEqual([a["encoder"] for a in result.recovery["attempts"]], ["hevc_nvenc", "libx265"])
        self.assertIn("audio_normalized", result.recovery["losses"])
        output = Path(result.recovery["private_output"])
        output_scope = SyntheticScope(frozenset({output}))
        output_backend = FFmpegBackend(self.backend.ffmpeg, self.backend.ffprobe, self.root,
                                      Runner(timeout=30), scope=output_scope)
        inspected = Inspector(output_backend, output_scope).inspect(output)
        self.assertEqual(inspected.container, "mp4_mov")
        video = next(s for s in inspected.streams if s["kind"] == "video")
        self.assertEqual((video["codec"], video["width"], video["height"]), ("hevc", 160, 120))
        self.assertEqual((video["frame_rate_numerator"], video["frame_rate_denominator"]), (25, 1))
        self.assertTrue(all(c == "passed" for c in result.recovery["verification"].values()))
        self.assertNotIn("SYNTHETIC_DRIVER_ERROR", json.dumps(result.recovery))

    def make_damaged(self):
        generated = self.backend.runner.run([str(self.backend.ffmpeg), "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25", "-t", "2", "-c:v", "mpeg4", "-g", "5", str(self.damaged)], self.root)
        self.assertEqual(generated.returncode, 0)
        packets = self.backend.runner.run([str(self.backend.ffprobe), "-v", "error", "-select_streams", "v:0", "-show_packets", "-show_entries", "packet=pos,size", "-of", "json", str(self.damaged)], self.root)
        packet = load_json(packets.stdout)["packets"][8]
        data = bytearray(self.damaged.read_bytes())
        pos, size = int(packet["pos"]), int(packet["size"])
        data[pos:pos+size] = bytes(size)
        self.damaged.write_bytes(data)

    def test_failed_hardware_attempt_falls_back_and_verifies_software_output(self):
        run = self.backend.runner.run
        def fail_hardware(args, scratch, **kwargs):
            if "h264_nvenc" in args:
                Path(args[-1]).write_bytes(b"Generated rejected attempt")
                return ProcessResult(1, stderr=b"PRIVATE_DRIVER_CANARY")
            if kwargs.get("watch_file") is not None:
                self.assertEqual(list(self.candidates.iterdir()), [])
            return run(args, scratch, **kwargs)
        with patch("videomate.recovery.select_encoder", return_value="h264_nvenc"), \
                patch.object(self.backend.runner, "run", side_effect=fail_hardware):
            result = self.recover(self.source, RecoveryOptions(strategy="reencode", profile="compatible_sdr", force=True))
        self.assertEqual(result.recovery["recovery_state"], "verified_with_losses")
        self.assertEqual([a["encoder"] for a in result.recovery["attempts"]], ["h264_nvenc", "libx264"])
        self.assertTrue(all(check == "passed" for check in result.recovery["verification"].values()))
        self.assertNotIn("PRIVATE_DRIVER_CANARY", json.dumps(result.recovery))

    def test_candidate_limit_never_publishes_even_when_shorter_output_is_allowed(self):
        original = Inspector(self.backend, self.scope).inspect(self.source)
        engine = RecoveryEngine(self.backend, self.scope, self.candidates, self.outputs, self.root / "code")
        def oversized(args, scratch, **kwargs):
            Path(args[-1]).write_bytes(b"Generated candidate" * 131072)
            return ProcessResult(0)
        with patch.object(self.backend.runner, "run", side_effect=oversized):
            result = engine.recover(self.source, original, RecoveryOptions(strategy="reencode", force=True,
                max_output_bytes=1024**2, allow_shorter=True, max_shorter_percent=100))
        self.assertEqual(result.recovery["recovery_state"], "failed")
        self.assertEqual(result.recovery["attempts"][0]["reason"], "resource_limit")
        self.assertEqual(list(self.outputs.iterdir()), [])
        self.assertEqual(list(self.candidates.iterdir()), [])

    def test_publish_failure_is_identified_without_repeating_the_encode(self):
        from videomate.errors import VideoMateError
        with patch("videomate.recovery.publish", side_effect=VideoMateError("output_filesystem_unsupported")) as publish:
            result = self.recover(self.source, RecoveryOptions(strategy="reencode", force=True))
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(result.recovery["private_failure_code"], "output_filesystem_unsupported")
        self.assertEqual(result.diagnostics[-1]["stage"], "publish")
        self.assertEqual(result.diagnostics[-1]["error_code"], "output_filesystem_unsupported")
        self.assertEqual(list(self.candidates.iterdir()), [])

    def test_parallel_sensitive_batch_and_hardware_first_recovery(self):
        from videomate.hardware import select_decoder
        from videomate.local_scan import run_job
        sample = self.root / "GENERATED_H264_CANARY.mp4"
        made = self.backend.runner.run([str(self.backend.ffmpeg), "-nostdin", "-v", "error", "-n",
            "-f", "lavfi", "-i", "testsrc2=size=160x128:rate=25", "-t", "1", "-c:v", "libx264",
            "-threads", "2", "-pix_fmt", "yuv420p", str(sample)], self.root)
        self.assertEqual(made.returncode, 0)
        sources = [sample, self.source]
        before = [hashlib.sha256(p.read_bytes()).digest() for p in sources]
        settings = {"scope": "local_files", "sensitive": True, "diagnostic_logs": True,
                    "cpu_threads": 4, "max_runners": 2, "hardware_decoding": True,
                    "depth": "full", "timeout": 30}
        job = Job.create(self.workspace, sources, settings)
        self.addCleanup(job.close)
        bundle = SimpleNamespace(ffmpeg=self.backend.ffmpeg, ffprobe=self.backend.ffprobe, version="9.0.2")
        with patch("videomate.local_scan.load_bundle", return_value=bundle):
            self.assertEqual(run_job(job, emit=lambda _: None), 0)
        self.assertTrue(all(row["status"] == "done" for row in job.rows()))
        self.assertFalse(list((self.workspace / "export-review").iterdir()))
        for row in job.rows():
            result = unpack_result(row["result"])
            self.assertEqual(result.integrity, "no_errors_detected")
            self.assertTrue(all(d["threads"] == 2 for d in result.diagnostics if d["stage"] == "decode"))
        for log in (self.workspace / "logs").glob("*.log"):
            self.assertNotIn("CANARY", log.read_text())
            self.assertNotIn(str(self.root), log.read_text())
        self.backend.scope = self.scope = SyntheticScope(frozenset({sample}))
        self.backend.decoder = select_decoder(self.backend)
        result = self.recover(sample, RecoveryOptions(strategy="reencode", profile="compatible_sdr", force=True))
        self.assertEqual(result.recovery["recovery_state"], "verified_with_losses")
        verified = [d for d in result.diagnostics if d["stage"] == "verify_decode"]
        self.assertTrue(verified)
        self.assertTrue(all(d["decoder"] == "software" for d in verified))
        self.assertEqual([hashlib.sha256(p.read_bytes()).digest() for p in sources], before)

    def test_decoder_failure_retains_hardware_encoder_before_cpu_fallback(self):
        original = Inspector(self.backend, self.scope).inspect(self.source)
        # Model H.264 eligibility without decoding any additional file.
        original.streams[0]["codec"] = "h264"
        self.backend.decoder = "cuda"
        self.backend._codec_route_checks = {("cuda", "h264_nvenc"): True}
        attempts = []
        def failed(args, scratch, **kwargs):
            attempts.append(args)
            return ProcessResult(1, stderr=b"PRIVATE_DRIVER_CANARY")
        engine = RecoveryEngine(self.backend, self.scope, self.candidates, self.outputs, self.root / "code")
        with patch("videomate.recovery.select_encoder", return_value="h264_nvenc"), patch.object(self.backend.runner, "run", side_effect=failed):
            result = engine.recover(self.source, original, RecoveryOptions(strategy="reencode", profile="compatible_sdr", force=True))
        traces = [d for d in result.diagnostics if d["stage"] == "encode"]
        self.assertEqual([(d["decoder"], d["encoder"]) for d in traces],
                         [("cuda", "h264_nvenc"), ("software", "h264_nvenc"), ("software", "libx264")])
        self.assertNotIn("PRIVATE_DRIVER_CANARY", json.dumps(traces))

    def test_verification_resource_limit_stops_fallback_attempts(self):
        from videomate.models import Finding, ScanResult
        original = Inspector(self.backend, self.scope).inspect(self.source)
        limited = ScanResult(state="partial", findings=[Finding("resource_limit")])
        engine = RecoveryEngine(self.backend, self.scope, self.candidates, self.outputs, self.root / "code")
        with patch("videomate.recovery.Inspector.inspect", return_value=limited):
            result = engine.recover(self.source, original, RecoveryOptions(strategy="auto", force=True))
        self.assertEqual(len(result.recovery["attempts"]), 1)
        self.assertEqual(result.recovery["attempts"][0]["reason"], "resource_limit")
        self.assertNotIn("private_output", result.recovery)

    def test_reencodes_actual_corrupt_packet_and_exports_no_private_names(self):
        self.make_damaged()
        initial = Inspector(self.backend, self.scope).inspect(self.damaged)
        self.assertIn(initial.integrity, {"damage_detected", "suspected_damage"})
        result = self.recover(self.damaged, RecoveryOptions(strategy="auto", allow_shorter=True))
        self.assertEqual(result.recovery["recovery_state"], "verified_with_losses", result.recovery)
        self.assertIn("concealment_possible", result.recovery["losses"])
        self.assertTrue(all(x == "passed" for x in result.recovery["verification"].values()))

    def test_cli_job_report_resume_and_sanitized_recovery_export(self):
        if not (self.backend.ffmpeg.parent.parent / "manifest.json").is_file():
            self.skipTest("CLI requires a provisioned bundle")
        out = io.StringIO()
        args = ["recover", "--test-files", "--workspace", str(self.workspace), "--dependencies", str(self.backend.ffmpeg.parents[2]), "--input", str(self.source), "--mode", "auto", "--force", "--strategy", "reencode"]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            status = main(args)
        self.assertEqual(status, 1, out.getvalue())
        self.assertNotIn("synthetic-private-canary", out.getvalue())
        identifier = next(line.split(": ")[1] for line in out.getvalue().splitlines() if line.startswith("Job: "))
        job = Job(self.workspace, identifier)
        row = job.rows()[0]
        output = Path(unpack_result(row["result"]).recovery["private_output"])
        job.close()
        before = (output.stat().st_mtime_ns, output.read_bytes())
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.assertEqual(main(["resume", "--test-files", "--workspace", str(self.workspace), "--job", identifier, "--dependencies", str(self.backend.ffmpeg.parents[2])]), 1)
            self.assertEqual(main(["report", "--test-files", "--workspace", str(self.workspace), "--job", identifier]), 0)
        self.assertEqual((output.stat().st_mtime_ns, output.read_bytes()), before)
        for file in (self.workspace / "export-review").glob("*.json"):
            data = file.read_bytes()
            self.assertNotIn(b"synthetic-private-canary", data)
            self.assertNotIn(b"private_output", data)
            value = json.loads(data)
            validate_export(value)
            self.assertEqual(value["files"][0]["recovery_state"], "verified_with_losses")

    def test_unreadable_source_produces_no_recovered_output(self):
        self.damaged.write_bytes(b"Wholly synthetic non-media file")
        result = self.recover(self.damaged, RecoveryOptions())
        self.assertEqual(result.recovery["recovery_state"], "blocked")
        self.assertEqual(list(self.outputs.iterdir()), [])

    def test_truncated_source_requires_explicit_shorter_policy(self):
        data = self.source.read_bytes()
        self.source.write_bytes(data[:len(data) * 2 // 3])
        result = self.recover(self.source, RecoveryOptions(strategy="reencode"))
        self.assertNotIn(result.recovery["recovery_state"], {"verified", "verified_with_losses"})
        result = self.recover(self.source, RecoveryOptions(strategy="reencode", allow_shorter=True, max_shorter_percent=100))
        self.assertEqual(result.recovery["recovery_state"], "verified_with_losses", result.recovery)
        self.assertIn("source_incomplete", result.recovery["losses"])
        self.assertIn("timing_changed", result.recovery["losses"])

    def test_partial_salvage_publishes_only_verified_shorter_synthetic_video(self):
        data = self.source.read_bytes()
        self.source.write_bytes(data[:len(data) * 2 // 3])
        result = self.recover(self.source, RecoveryOptions(strategy="reencode", partial_salvage=True))
        self.assertEqual(result.recovery["recovery_state"], "verified_with_losses", result.recovery)
        self.assertIn("partial_salvage", result.recovery["losses"])
        self.assertEqual(result.recovery["attempts"][-1]["reason"], "partial_salvage")
        self.assertTrue(all(value == "passed" for value in result.recovery["verification"].values()))
        self.assertLess(result.recovery["output_duration_us"], result.duration_us)
        self.assertTrue(Path(result.recovery["private_output"]).is_file())
        from videomate.diagnostics import create_export, environment
        from uuid import uuid4
        validate_export(json.loads(create_export([result], uuid4(), bytes(32), environment('0.8.2', '9.0.2'), synthetic=True)))

    def test_source_change_during_encode_prevents_publication(self):
        original = Inspector(self.backend, self.scope).inspect(self.source)
        run = self.backend.runner.run
        def change(args, scratch, **kwargs):
            output = run(args, scratch, **kwargs)
            if kwargs.get("watch_file"):
                with self.source.open("ab") as file:
                    file.write(b"Synthetic concurrent source change")
            return output
        with patch.object(self.backend.runner, "run", side_effect=change):
            engine = RecoveryEngine(self.backend, self.scope, self.candidates, self.outputs, self.root / "code")
            engine.recover(self.source, original, RecoveryOptions(strategy="reencode", force=True))
        self.assertEqual(original.recovery["attempts"][0]["reason"], "input_changed")
        self.assertEqual(list(self.outputs.iterdir()), [])

    def test_guided_preview_and_interrupted_job_resume(self):
        if not (self.backend.ffmpeg.parent.parent / "manifest.json").is_file():
            self.skipTest("CLI requires a provisioned bundle")
        out = io.StringIO()
        args = ["recover", "--test-files", "--workspace", str(self.workspace), "--dependencies", str(self.backend.ffmpeg.parents[2]), "--input", str(self.source), "--force"]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.assertEqual(main(args), 1)
        self.assertIn("Plan:", out.getvalue())
        self.assertEqual(list(self.outputs.iterdir()), [])
        out = io.StringIO()
        # Cancel a new job just as encoding begins, after its inspection is saved.
        original_run = Runner.run
        def interrupt(runner, args, scratch, **kwargs):
            if kwargs.get("watch_file"):
                raise KeyboardInterrupt()
            return original_run(runner, args, scratch, **kwargs)
        with patch.object(Runner, "run", interrupt), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.assertEqual(main(args + ["--mode", "auto"]), 130)
        identifier = next(line.split(": ")[1] for line in out.getvalue().splitlines() if line.startswith("Job: "))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.assertEqual(main(["resume", "--test-files", "--workspace", str(self.workspace), "--job", identifier, "--dependencies", str(self.backend.ffmpeg.parents[2])]), 1)
        job = Job(self.workspace, identifier)
        try:
            self.assertEqual(unpack_result(job.rows()[0]["result"]).recovery["recovery_state"], "verified_with_losses")
        finally:
            job.close()
