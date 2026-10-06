"""New policies use invented metadata and exact freshly generated fixtures only."""
import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from videomate.cleanup import manage_originals
from videomate.encoding import video_rates, audio_rates, candidate_limit
from videomate.errors import VideoMateError
from videomate.local_scan import scan_local
from videomate.models import ScanResult
from videomate.output_layout import plan_layout, destination_root
from videomate.recovery import RecoveryOptions, plan, verification
from videomate.media_output import MediaOutput, process_findings
from videomate.runner import Runner


class RecoveryOptionTests(unittest.TestCase):
    def test_source_relative_cap_and_small_source_auto_bitrate(self):
        streams = [{"kind": "video", "index": 0}, {"kind": "audio", "index": 1, "channels": 1}]
        result = ScanResult(duration_us=60000000, streams=streams,
            technical={"source_size": 1024**2, "streams": {"0": {"bit_rate": 200000000}}})
        options = RecoveryOptions(max_source_percent=300)
        self.assertEqual(candidate_limit(result, options), 3 * 1024**2)
        self.assertIsNone(candidate_limit(result, RecoveryOptions()))
        self.assertEqual(candidate_limit(result, RecoveryOptions(max_output_bytes=2 * 1024**2)), 2 * 1024**2)
        self.assertLess(video_rates(result, streams, options)[0], 100000)
        self.assertEqual(audio_rates(result, streams, options), [64000])
        result.technical["source_size"] = 50
        self.assertEqual(candidate_limit(result, options), 1024**2)
        result.technical.clear()
        streams[0].update(frame_rate_numerator=None, frame_rate_denominator=None, width=None, height=None)
        self.assertGreater(video_rates(result, streams, options)[0], 0)
        with self.assertRaises(VideoMateError):
            RecoveryOptions(max_source_percent=True).validate()

    def test_rate_targets_reserve_audio_and_reject_impossible_sizes(self):
        streams = [{"kind": "video", "index": 0}, {"kind": "audio", "index": 1}]
        result = ScanResult(duration_us=60000000, streams=streams, technical={"source_size": 20 * 1024**2, "streams": {"0": {"bit_rate": 1500000}}})
        self.assertEqual(video_rates(result, streams, RecoveryOptions()), [1500000])
        self.assertEqual(video_rates(result, streams, RecoveryOptions(rate_control="bitrate", video_bitrate_kbps=4000)), [4000000])
        rate = video_rates(result, streams, RecoveryOptions(rate_control="source_size"))[0]
        self.assertLess(rate * 60 / 8, 20 * 1024**2)
        self.assertEqual(rate, video_rates(result, streams, RecoveryOptions(rate_control="target_size", target_size_mib=20))[0])
        with self.assertRaises(VideoMateError):
            video_rates(result, streams, RecoveryOptions(rate_control="target_size", target_size_mib=1))
        with self.assertRaises(VideoMateError) as error:
            plan(result, RecoveryOptions(strategy="reencode", profile="compatible_sdr", rate_control="target_size", target_size_mib=1))
        self.assertEqual(error.exception.code, "rate_target_unavailable")

    def test_convert_all_resolves_explicit_policy_and_duration_loss_is_bounded(self):
        options = RecoveryOptions(convert_all_mp4=True).resolved()
        self.assertTrue(options.force)
        self.assertEqual((options.profile, options.strategy), ("compatible_sdr", "auto"))
        stream = {"index": 0, "kind": "video", "codec": "h264", "pixel_format": "yuv420p", "width": 128, "height": 128}
        original = ScanResult(integrity="no_errors_detected", streams=[stream], duration_us=10000000)
        shortened = ScanResult(integrity="no_errors_detected", streams=[dict(stream)], duration_us=5000000)
        issues = []
        checks = verification(original, shortened, "reencode", RecoveryOptions(allow_shorter=True, max_shorter_percent=10), issues)
        self.assertEqual(checks["timing_check"], "failed")
        self.assertIn("shortening_budget_exceeded", issues)

    def test_selective_hevc_policy_and_codec_verification(self):
        options = RecoveryOptions(convert_noncompliant_hevc=True).resolved()
        self.assertEqual((options.strategy, options.profile, options.video_codec, options.audio_normalization),
                         ("reencode", "compatible_sdr", "hevc", "playback"))
        source = ScanResult(integrity="no_errors_detected", duration_us=1000000, streams=[{
            "index": 0, "kind": "video", "codec": "h264", "width": 128, "height": 128,
            "pixel_format": "yuv420p", "frame_rate_numerator": 25, "frame_rate_denominator": 1}])
        candidate = ScanResult(integrity="no_errors_detected", duration_us=1000000, streams=[{
            **source.streams[0], "codec": "h264", "frame_rate_numerator": 30}])
        issues = []
        checks = verification(source, candidate, "reencode", options, issues)
        self.assertEqual((checks["stream_check"], checks["timing_check"]), ("failed", "failed"))
        self.assertEqual(set(issues), {"codec_changed", "frame_rate_changed"})
        video = source.streams
        source.technical = {"source_size": 1000000, "streams": {"0": {"bit_rate": 1000000}}}
        self.assertEqual(video_rates(source, video, options), [800000])
        with self.assertRaises(VideoMateError):
            RecoveryOptions(convert_all_mp4=True, convert_noncompliant_hevc=True).validate()

    def test_invalid_option_types_use_closed_error(self):
        for setting, value in (
            ("video_codec", []), ("rate_control", []), ("size_policy", []),
            ("strategy", []), ("profile", []), ("audio_normalization", []),
            ("software_preset", []), ("keep_start_us", "0"),
            ("keep_start_us", False), ("keep_end_us", "100"),
            ("keep_end_us", True),
        ):
            with self.subTest(setting=setting, value=value):
                kwargs = {setting: value}
                if setting.startswith("keep_"):
                    kwargs.setdefault("keep_start_us", 0)
                    kwargs.setdefault("keep_end_us", 100)
                with self.assertRaises(VideoMateError) as caught:
                    RecoveryOptions(**kwargs).validate()
                self.assertEqual(caught.exception.code, "invalid_arguments")

    def test_invalid_scan_controls_fail_before_workspace_access(self):
        for controls in ({"timeout": "3600"}, {"timeout": True}, {"depth": "full"},
                         {"recursive": "yes"}, {"execute": 1}, {"export_on_completion": "yes"},
                         {"recovery": {"strategy": "auto"}}, {"recovery": False}):
            with self.subTest(controls=controls), self.assertRaises(VideoMateError) as caught:
                scan_local(["generated-only-placeholder"], Path("missing-workspace"), **controls)
            self.assertEqual(caught.exception.code, "invalid_arguments")

    def test_layout_keeps_selected_root_structure_and_sensitive_names_stay_neutral(self):
        with tempfile.TemporaryDirectory(prefix="videomate-layout-policy-") as temp:
            root = Path(temp).resolve()
            source = root / "selection" / "nested" / "invented.mov"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"synthetic marker")
            layout = plan_layout([str(root / "selection")], [source], "folders", False)
            self.assertEqual(layout, {"1": str(Path("nested/invented.mov"))})
            self.assertEqual(plan_layout([str(source)], [source], "filename", True), {})
            with self.assertRaises(VideoMateError):
                destination_root(root, "../outside.mp4")

    def test_streamed_diagnostics_are_bounded_and_never_keep_raw_text(self):
        output = MediaOutput()
        for _ in range(3000):
            output.feed(b"[error] invalid NAL PRIVATE_CANARY\n")
        output.feed(b"SECRET" * 4000 + b"\n")
        output.finish()
        self.assertLessEqual(len(output.pending), 8192)
        self.assertEqual(sum(f.count for f in output.findings()), 3001)
        self.assertNotIn("PRIVATE_CANARY", repr(output.findings()))
        self.assertNotIn("SECRET", repr(output.findings()))

    def test_noisy_worker_does_not_hit_raw_output_cap_in_streaming_mode(self):
        import sys
        with tempfile.TemporaryDirectory(prefix="videomate-streaming-worker-") as temp:
            result = Runner(timeout=20, output_limit=128).run([sys.executable, "-c",
                "import sys; sys.stderr.write('[error] invalid NAL PRIVATE_CANARY\\n'*20000); print('frame=1\\nout_time_us=1000000\\nprogress=end')"], Path(temp), media_output=True)
            self.assertFalse(result.limited)
            self.assertEqual(result.stderr, b"")
            self.assertEqual(process_findings(result)[0].count, 20000)
            self.assertIn(b"progress=end", result.stdout)

    def test_cleanup_requires_exact_confirmation_and_only_changes_selected_files(self):
        with tempfile.TemporaryDirectory(prefix="videomate-cleanup-generated-") as temp:
            root = Path(temp).resolve()
            selected, untouched = root / "invented.mp4", root / "untouched.mp4"
            selected.write_bytes(b"Generated cleanup fixture")
            untouched.write_bytes(b"Keep this generated fixture")
            cancel = threading.Event()
            with self.assertRaises(VideoMateError):
                manage_originals([str(selected)], "delete", "", cancel_event=cancel)
            self.assertTrue(selected.exists())
            manage_originals([str(selected)], "quarantine", "QUARANTINE 1", cancel_event=cancel, emit=lambda _: None)
            self.assertFalse(selected.exists())
            copies = list((root / ".videomate-review").iterdir())
            self.assertEqual(copies[0].read_bytes(), b"Generated cleanup fixture")
            self.assertEqual(untouched.read_bytes(), b"Keep this generated fixture")
            selected.write_bytes(b"Separate generated deletion fixture")
            manage_originals([str(selected)], "delete", "DELETE 1", cancel_event=cancel, emit=lambda _: None)
            self.assertFalse(selected.exists())
            self.assertTrue(untouched.exists())


@unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_FFMPEG") and os.environ.get("VIDEOMATE_TEST_FFPROBE"), "Explicit generated-media backend not configured")
class NewRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        from test_recovery_integration import RecoveryIntegrationTests
        self.fixture = RecoveryIntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_convert_all_mp4_and_filename_collision_preserve_originals(self):
        from videomate.inspection import Inspector
        from videomate.recovery import RecoveryEngine
        f = self.fixture
        before = hashlib.sha256(f.source.read_bytes()).digest()
        for _ in range(2):
            result = Inspector(f.backend, f.scope).inspect(f.source)
            engine = RecoveryEngine(f.backend, f.scope, f.candidates, f.outputs, f.root / "code", output_stem="generated-output")
            engine.recover(f.source, result, RecoveryOptions(convert_all_mp4=True, rate_control="bitrate", video_bitrate_kbps=1000))
            self.assertEqual(result.recovery["recovery_state"], "verified_with_losses", result.recovery)
            self.assertEqual(result.recovery["attempts"][-1]["verification_issues"], [])
        self.assertTrue((f.outputs / "generated-output.mp4").is_file())
        self.assertTrue((f.outputs / "generated-output.recovered-1.mp4").is_file())
        self.assertEqual(hashlib.sha256(f.source.read_bytes()).digest(), before)

    def test_default_sensitive_scan_keeps_no_path_journal_and_explicit_export_still_works(self):
        from types import SimpleNamespace
        from videomate.local_scan import scan_local, report_local
        from videomate.private_state import LIVE_REPORTS
        f = self.fixture
        bundle = SimpleNamespace(ffmpeg=f.backend.ffmpeg, ffprobe=f.backend.ffprobe, version="9.0.2")
        messages = []
        with patch("videomate.local_scan.load_bundle", return_value=bundle):
            self.assertEqual(scan_local([str(f.source)], f.workspace, emit=messages.append, hardware_decoding=False), 0)
        identifier = next(m[5:] for m in messages if m.startswith("Job: "))
        self.assertNotIn("synthetic-private-canary", LIVE_REPORTS[identifier][2].decode())
        self.assertEqual(list((f.workspace / "jobs").iterdir()), [f.candidates])
        self.assertEqual(list((f.workspace / "state").glob("mapping-*.json")), [])
        self.assertEqual(report_local(identifier, f.workspace, export=True, technical_json=True, emit=lambda _: None), 0)
        reports = list((f.workspace / "export-review").glob("*.json"))
        self.assertEqual(len(reports), 1)
        self.assertNotIn(str(f.source), reports[0].read_text())
        LIVE_REPORTS.pop(identifier)

    def test_private_recovery_resume_reuses_only_unchanged_verified_outputs(self):
        from types import SimpleNamespace
        from videomate.local_scan import scan_local
        from videomate.private_state import LIVE_REPORTS
        from videomate.recovery import RecoveryEngine
        f = self.fixture
        second = f.root / "generated-second.mkv"
        second.write_bytes(f.source.read_bytes())
        bundle = SimpleNamespace(ffmpeg=f.backend.ffmpeg, ffprobe=f.backend.ffprobe, version="9.0.2")
        options = RecoveryOptions(strategy="remux", force=True, hardware_encoding=False)
        settings = dict(recovery=options, hardware_decoding=False, cpu_threads=2, private_resume=True,
                        passphrase="synthetic checkpoint test passphrase")
        for mutation in ("unchanged", "missing", "altered"):
            with self.subTest(output=mutation), patch("videomate.local_scan.load_bundle", return_value=bundle):
                cancel, messages = threading.Event(), []
                def emit(message):
                    messages.append(message)
                    if message.startswith("input-1: no_errors_detected; verified"):
                        cancel.set()
                with self.assertRaises(KeyboardInterrupt):
                    scan_local([str(f.source), str(second)], f.workspace, emit=emit, cancel_event=cancel, **settings)
                identifier = next(m[5:] for m in messages if m.startswith("Job: "))
                self.addCleanup(lambda key=identifier: LIVE_REPORTS.pop(key, None))
                checkpoint = f.workspace / "state" / ("checkpoint-" + identifier + ".json")
                document = json.loads(checkpoint.read_bytes())
                artifact = document["payload"]["entries"][0]["artifact"]
                output = f.outputs / identifier / ("input-" + str(artifact["number"])) / (artifact["token"] + artifact["suffix"])
                before = (output.stat().st_mtime_ns, output.read_bytes())
                self.assertNotIn(hashlib.sha256(f.source.read_bytes()).hexdigest(), checkpoint.read_text())
                if mutation == "missing":
                    output.unlink()  # Exact output created in this synthetic subtest.
                elif mutation == "altered":
                    output.write_bytes(b"Synthetic replacement of a generated output")
                original_recover = RecoveryEngine.recover
                with patch.object(RecoveryEngine, "recover", autospec=True, side_effect=original_recover) as recover:
                    code = scan_local([str(second), str(f.source)], f.workspace, checkpoint_id=identifier,
                                      emit=lambda _: None, **settings)
                    self.assertEqual(code, 1)
                    self.assertEqual(recover.call_count, 1 if mutation == "unchanged" else 2)
                if mutation == "unchanged":
                    self.assertEqual((output.stat().st_mtime_ns, output.read_bytes()), before)
                self.assertFalse(checkpoint.exists())
                self.assertEqual(list((f.workspace / "jobs").iterdir()), [f.candidates])

    def test_variable_timestamps_decode_without_null_encoder_rounding_errors(self):
        from videomate.inspection import Inspector
        from videomate.policy import SyntheticScope
        f = self.fixture
        source = f.root / "generated-variable-timestamps.mkv"
        generated = f.backend.runner.run([str(f.backend.ffmpeg), "-nostdin", "-v", "error", "-n",
            "-f", "lavfi", "-i", "testsrc2=size=128x128:rate=120", "-frames:v", "60",
            "-vf", "setpts=if(lt(N\\,30)\\,4*N\\,120+(N-30))",
            "-fps_mode", "passthrough", "-enc_time_base", "1:1000", "-c:v", "ffv1", str(source)], f.root)
        self.assertEqual(generated.returncode, 0)
        scope = SyntheticScope(frozenset({source}))
        previous_scope = f.backend.scope
        f.backend.scope = scope
        try:
            result = Inspector(f.backend, scope).inspect(source)
        finally:
            f.backend.scope = previous_scope
        self.assertEqual(result.integrity, "no_errors_detected", result.findings)
