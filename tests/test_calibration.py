"""Generated-route optimization never needs or records operator media."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videomate.calibration import (bundle_signature, lane_routes, optimize_generated,
                                   rank_devices, validate_calibrations)
from videomate.errors import VideoMateError
from videomate.preferences import Preferences, load_preferences, save_preferences
from videomate.runner import ProcessResult


class CalibrationTests(unittest.TestCase):
    def test_rank_is_local_bounded_and_never_adds_an_unqualified_route(self):
        bundle = SimpleNamespace(platform="windows-x86_64", version="8.0", digest="a" * 64)
        record = {"signature": bundle_signature(bundle), "expires_at": int(time.time()) + 300,
                  "routes": [{"id": "hevc_nvenc#0", "fps": 310.0, "jobs": 2}, {"id": "hevc_amf", "fps": 80.0, "jobs": 1}]}
        devices = (("d3d11va", "hevc_amf", None), ("cuda", "hevc_nvenc", 0))
        ranked, speeds = rank_devices(devices, calibrations={"hevc": record}, codec="hevc", bundle=bundle)
        self.assertEqual(ranked[0][1], "hevc_nvenc")
        lanes = lane_routes(ranked, 4, speeds)
        self.assertEqual([lane[0][1] for lane in lanes], ["hevc_nvenc", "hevc_amf", "hevc_nvenc", "hevc_nvenc"])
        manual, _ = rank_devices(devices, preference="amd", calibrations={"hevc": record}, codec="hevc", bundle=bundle)
        self.assertEqual(manual[0][1], "hevc_amf")
        expired = {**record, "expires_at": 1}
        fallback, measured = rank_devices(devices, calibrations={"hevc": expired}, codec="hevc", bundle=bundle)
        self.assertEqual((fallback, measured), (devices, {}))
        self.assertEqual(len(ranked), len(devices))

    def test_calibration_settings_reject_private_text_and_round_trip(self):
        bundle = SimpleNamespace(platform="windows-x86_64", version="8.0", digest="a" * 64)
        record = {"signature": bundle_signature(bundle), "expires_at": int(time.time()) + 300,
                  "routes": [{"id": "h264_nvenc#0", "fps": 100.0, "jobs": 2}]}
        with tempfile.TemporaryDirectory(prefix="videomate-calibration-generated-") as temporary:
            path = Path(temporary).resolve() / "settings.json"
            chosen = Preferences(hardware_preference="nvidia", hardware_calibration={"h264": record})
            save_preferences(path, chosen)
            self.assertEqual(load_preferences(path), chosen)
            with self.assertRaises(VideoMateError):
                validate_calibrations({"h264": {**record, "routes": [{"id": "PRIVATE_FILE_NAME", "fps": 100.0, "jobs": 2}]}})

    def test_untrusted_large_integer_fps_fails_with_safe_settings_error(self):
        record = {"signature": "a" * 64, "expires_at": 1,
                  "routes": [{"id": "h264_nvenc", "fps": 10 ** 400, "jobs": 1}]}
        with tempfile.TemporaryDirectory(prefix="videomate-calibration-malformed-generated-") as temporary:
            path = Path(temporary).resolve() / "settings.json"
            path.write_text(json.dumps({"schema_version": 1, "hardware_calibration": {"h264": record}}), encoding="utf-8")
            with self.assertRaises(VideoMateError) as failure:
                load_preferences(path)
            self.assertEqual(failure.exception.code, "settings_invalid")

    def test_optimize_reads_only_its_generated_clip_and_requires_full_decode(self):
        with tempfile.TemporaryDirectory(prefix="videomate-calibration-test-") as temporary:
            fake = Path(temporary).resolve() / "generated-ffmpeg.exe"
            fake.write_bytes(b"synthetic executable placeholder")
            bundle = SimpleNamespace(ffmpeg=fake, ffprobe=fake, platform="windows-x86_64", version="8.0", digest="b" * 64)
            seen = []
            def run(_self, args, scratch, **kwargs):
                seen.append(args)
                if "watch_file" in kwargs:
                    kwargs["watch_file"].write_bytes(b"generated test marker")
                return ProcessResult(0, stdout=b"frame=480\nprogress=end\n", elapsed_ms=4000)
            with patch("videomate.calibration.select_decoder", return_value=("software",)), \
                    patch("videomate.calibration.select_encoder", return_value=("hevc_nvenc",)), \
                    patch("videomate.calibration.qualify_codec_routes", return_value=(("software", "hevc_nvenc"),)), \
                    patch("videomate.calibration.qualify_devices", return_value=(("software", "hevc_nvenc", 0),)), \
                    patch("videomate.calibration.Runner.run", autospec=True, side_effect=run):
                record = optimize_generated(bundle, "hevc")
            self.assertEqual(record["routes"], [{"id": "hevc_nvenc#0", "fps": 240.0, "jobs": 2}])
            self.assertEqual(len(seen), 7)
            self.assertTrue(all("PRIVATE_FILE_NAME" not in " ".join(args) for args in seen))
            self.assertTrue(any("testsrc2=size=1280x720:rate=30" in args for args in seen))


if __name__ == "__main__":
    unittest.main()
