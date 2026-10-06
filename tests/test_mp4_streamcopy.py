"""MP4 copy/fallback regressions use generated media, never operator media."""
import hashlib
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videomate.inspection import Inspector
from videomate.models import ScanResult
from videomate.policy import SyntheticScope
from videomate.recovery import RecoveryEngine, RecoveryOptions, command, plan
from videomate.runner import ProcessResult


class MP4PlanTests(unittest.TestCase):
    def test_hardware_conversion_explicitly_repacks_nv12_without_resizing(self):
        result = ScanResult(integrity="no_errors_detected", streams=[
            {"index": 0, "kind": "video", "codec": "h264", "pixel_format": "yuv420p", "width": 128, "height": 128}])
        backend = SimpleNamespace(ffmpeg=Path("invented"), threads=8)
        options = RecoveryOptions(profile="compatible_sdr")
        gpu = command(backend, Path("source"), Path("target"), result, "reencode", options, "h264_amf", "d3d11va")
        self.assertEqual(gpu[gpu.index("-filter:v:0")+1], "scale=iw:ih:flags=bitexact,format=yuv420p")
        self.assertEqual(gpu[gpu.index("-pix_fmt:v:0")+1], "+yuv420p")
        cpu = command(backend, Path("source"), Path("target"), result, "reencode", options)
        self.assertNotIn("-filter:v:0", cpu)

    def test_copy_can_preserve_ten_bit_and_multichannel_without_claiming_sdr_conversion(self):
        original = ScanResult(integrity="no_errors_detected", streams=[
            {"index": 0, "kind": "video", "codec": "hevc", "pixel_format": "yuv420p10le", "width": 1920, "height": 1080},
            {"index": 1, "kind": "audio", "codec": "aac", "channels": 6, "sample_rate": 48000}],
            technical={"streams": {"0": {"color_transfer": "smpte2084"}}})
        options = RecoveryOptions(convert_all_mp4=True)
        self.assertEqual(plan(original, options), ["remux"])
        args = command(SimpleNamespace(ffmpeg=Path("invented"), threads=8), Path("source"), Path("target"), original, "remux", options)
        self.assertEqual(args[args.index("-c") + 1], "copy")
        self.assertEqual(args[args.index("-f") + 1], "mp4")
        self.assertNotIn("-pix_fmt:v:0", args)
        self.assertNotIn("-hwaccel", args)


@unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_FFMPEG"), "Generated-media backend not configured")
class MP4StreamCopyTests(unittest.TestCase):
    def setUp(self):
        from test_recovery_integration import RecoveryIntegrationTests
        self.fixture = f = RecoveryIntegrationTests()
        self.addCleanup(f.doCleanups)
        f.setUp()
        self.source = f.root / "generated-h264-aac.mkv"
        outcome = f.backend.runner.run([str(f.backend.ffmpeg), "-nostdin", "-v", "error", "-n", "-i", str(f.source),
            "-c:v", "libx264", "-threads", "2", "-c:a", "aac", str(self.source)], f.root)
        self.assertEqual(outcome.returncode, 0)
        self.scope = SyntheticScope(frozenset({self.source}))
        f.backend.scope = self.scope
        self.result = Inspector(f.backend, self.scope).inspect(self.source)
        self.before = hashlib.sha256(self.source.read_bytes()).digest()
        self.engine = RecoveryEngine(f.backend, self.scope, f.candidates, f.outputs, f.root / "code")

    def test_healthy_copy_preserves_decoded_video_and_never_claims_lossy_encoding(self):
        f = self.fixture
        self.engine.recover(self.source, self.result, RecoveryOptions(convert_all_mp4=True, hardware_encoding=False))
        recovery = self.result.recovery
        self.assertEqual(recovery["attempts"][0]["strategy"], "remux")
        self.assertEqual(len(recovery["attempts"]), 1)
        self.assertEqual(recovery["attempts"][0]["encoder"], "none")
        self.assertNotIn("lossy_encoding", recovery["losses"])
        output = Path(recovery["private_output"])
        self.assertEqual(output.suffix, ".mp4")
        hashes = []
        for source in (self.source, output):
            hashed = f.backend.runner.run([str(f.backend.ffmpeg), "-nostdin", "-v", "error", "-i", str(source),
                "-map", "0:v:0", "-f", "hash", "-hash", "sha256", "-"], f.root)
            self.assertEqual(hashed.returncode, 0)
            hashes.append(hashed.stdout)
        self.assertEqual(*hashes)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.before)

    def test_failed_copy_falls_back_to_verified_encoding(self):
        f = self.fixture
        original_run = f.backend.runner.run
        def fail_copy(args, *positional, **kwargs):
            if "-c" in args and args[args.index("-c") + 1] == "copy":
                return ProcessResult(1)
            return original_run(args, *positional, **kwargs)
        with patch.object(f.backend.runner, "run", side_effect=fail_copy):
            self.engine.recover(self.source, self.result, RecoveryOptions(convert_all_mp4=True, hardware_encoding=False))
        recovery = self.result.recovery
        self.assertEqual([a["strategy"] for a in recovery["attempts"]], ["remux", "reencode"])
        self.assertEqual(recovery["recovery_state"], "verified_with_losses")
        self.assertIn("lossy_encoding", recovery["losses"])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.before)

    def test_audio_processing_and_explicit_quality_require_encoding(self):
        for options in (RecoveryOptions(convert_all_mp4=True, audio_normalization="playback"),
                        RecoveryOptions(convert_all_mp4=True, rate_control="quality"),
                        RecoveryOptions(convert_all_mp4=True, rate_control="bitrate")):
            self.assertEqual(plan(self.result, options), ["reencode"])

    def test_integrity_never_trusts_a_silent_hardware_decoder(self):
        f = self.fixture
        f.backend.decoder = "cuda"
        original_decode = f.backend._decode
        with patch.object(f.backend, "decode", return_value=ProcessResult(0)) as fast, \
                patch.object(f.backend, "_decode", wraps=original_decode) as verified:
            result = Inspector(f.backend, self.scope).inspect(self.source)
        fast.assert_not_called()
        self.assertTrue(verified.call_args_list)
        self.assertTrue(all(call.args[2] == "software" for call in verified.call_args_list))
        self.assertEqual(result.integrity, "no_errors_detected")

    def test_multichannel_aac_fallback_preserves_channel_layout(self):
        f = self.fixture
        source = f.root / "generated-surround.mkv"
        tones = "|".join(f"0.05*sin(2*PI*{220 + channel*110}*t)" for channel in range(6))
        generated = f.backend.runner.run([str(f.backend.ffmpeg), "-nostdin", "-v", "error", "-n", "-i", str(self.source),
            "-f", "lavfi", "-i", "aevalsrc=" + tones + ":s=48000:channel_layout=5.1", "-t", "2",
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "flac", str(source)], f.root)
        self.assertEqual(generated.returncode, 0)
        scope = SyntheticScope(frozenset({source}))
        f.backend.scope = scope
        result = Inspector(f.backend, scope).inspect(source)
        engine = RecoveryEngine(f.backend, scope, f.candidates, f.outputs, f.root / "code")
        engine.recover(source, result, RecoveryOptions(convert_all_mp4=True, hardware_encoding=False))
        self.assertEqual(result.recovery["recovery_state"], "verified_with_losses", result.recovery)
        self.assertEqual(result.recovery["verification"]["stream_check"], "passed")
        self.assertEqual(result.streams[1]["channels"], 6)
