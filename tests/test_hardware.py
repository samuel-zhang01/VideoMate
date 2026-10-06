import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videomate.hardware import select_encoder, select_decoder, codec_routes, video_encoder_args, qualify_codec_routes, qualify_devices
from videomate.runner import ProcessResult, Runner
from videomate.errors import VideoMateError


class HardwareTests(unittest.TestCase):
    def test_multiple_nvenc_devices_are_explicit_and_software_verified(self):
        with tempfile.TemporaryDirectory(prefix='videomate-devices-generated-') as directory:
            backend = SimpleNamespace(ffmpeg=Path(directory) / 'fake.exe', scratch=Path(directory), runner=Runner(), threads=2)
            devices, checks = [], []
            def run(args, scratch, **kwargs):
                if '-f' in args and 'lavfi' in args:
                    self.assertIn('testsrc2=size=320x240:rate=24', args)
                if '-gpu' in args:
                    index = int(args[args.index('-gpu') + 1])
                    devices.append(index)
                    if index not in {0, 2}:
                        return ProcessResult(1)
                    self.assertEqual(args[args.index('-hwaccel_device') + 1], str(index))
                elif '-hwaccel' in args:
                    checks.append(args[args.index('-hwaccel') + 1])
                if 'watch_file' in kwargs:
                    kwargs['watch_file'].write_bytes(b'Generated qualification marker')
                return ProcessResult(0)
            with patch('videomate.hardware.Runner.run', side_effect=run):
                routes = qualify_devices(backend, (('cuda', 'h264_nvenc'), ('qsv', 'h264_qsv')))
            self.assertEqual(routes, (('qsv', 'h264_qsv', None), ('cuda', 'h264_nvenc', 0), ('cuda', 'h264_nvenc', 2)))
            self.assertEqual(checks, ['none', 'none'])
            self.assertEqual(set(devices), set(range(16)))

    def test_combined_routes_reject_cross_adapter_failure_and_cache_qualification(self):
        with tempfile.TemporaryDirectory(prefix="videomate-route-generated-") as directory:
            for usable in (False, True):
                backend = SimpleNamespace(ffmpeg=Path(directory) / "fake.exe", scratch=Path(directory), runner=Runner(), threads=2)
                def run(args, scratch, **kwargs):
                    if 'lavfi' in args:
                        self.assertIn('testsrc2=size=320x240:rate=24', args)
                    if "-c:v:0" in args and not usable:
                        return ProcessResult(1)
                    if "watch_file" in kwargs:
                        kwargs["watch_file"].write_bytes(b"Synthetic route marker")
                    return ProcessResult(0)
                with patch("videomate.hardware.Runner.run", side_effect=run) as worker:
                    route = (("d3d11va", "h264_amf"),)
                    result = qualify_codec_routes(backend, route)
                    self.assertEqual(result, route if usable else (("software", "h264_amf"),))
                    calls = worker.call_count
                    self.assertEqual(qualify_codec_routes(backend, route), result)
                    self.assertEqual(worker.call_count, calls)
    def test_all_qualified_backends_are_routed_without_counting_decoder_aliases(self):
        with tempfile.TemporaryDirectory(prefix="videomate-multi-codec-generated-") as directory:
            backend = SimpleNamespace(ffmpeg=Path(directory) / "fake.exe", scratch=Path(directory), runner=Runner())
            def run(args, scratch, **kwargs):
                if "-encoders" in args:
                    return ProcessResult(0, b" V....D h264_nvenc Fake\n V....D h264_qsv Fake\n V....D h264_amf Fake")
                if "-hwaccels" in args:
                    return ProcessResult(0, b"d3d11va dxva2 cuda qsv")
                if "lavfi" in args:
                    if "h264_amf" in args:
                        return ProcessResult(1)  # Listed but not usable.
                    Path(args[-1]).write_bytes(b"Generated qualification stand-in")
                return ProcessResult(0)
            with patch("videomate.hardware.platform.system", return_value="Windows"), patch("videomate.hardware.Runner.run", side_effect=run):
                encoders = select_encoder(backend, all_ready=True)
                decoders = select_decoder(backend, all_ready=True)
            self.assertEqual(encoders, ("h264_nvenc", "h264_qsv"))
            self.assertEqual(codec_routes(decoders, encoders), (("cuda", "h264_nvenc"), ("qsv", "h264_qsv")))
            self.assertEqual(codec_routes(decoders, ("libx264",)), (("cuda", "libx264"), ("qsv", "libx264")))
            with patch("videomate.hardware.Runner.run", side_effect=AssertionError("Qualification must be reused")):
                self.assertEqual(select_encoder(backend, all_ready=True), encoders)
            self.assertEqual(codec_routes(("software",), encoders)[0], ("software", "h264_nvenc"))

    def test_listing_alone_never_qualifies_an_encoder(self):
        with tempfile.TemporaryDirectory(prefix="videomate-hardware-test-") as directory:
            backend = SimpleNamespace(ffmpeg=Path(directory) / "fake.exe", scratch=Path(directory), runner=Runner())
            def run(args, scratch, **kwargs):
                return ProcessResult(0, b" V....D h264_nvenc Fake") if "-encoders" in args else ProcessResult(1)
            with patch("videomate.hardware.platform.system", return_value="Windows"), \
                    patch("videomate.hardware.Runner.run", side_effect=run) as worker:
                self.assertEqual(select_encoder(backend), "libx264")
                self.assertEqual(select_encoder(backend), "libx264")
                self.assertEqual(worker.call_count, 18)  # Listing, default, 16 bounded indices.

    def test_generated_output_requires_software_decode(self):
        with tempfile.TemporaryDirectory(prefix="videomate-hardware-test-") as directory:
            for decode_status, expected in ((1, "libx264"), (0, "h264_nvenc")):
                backend = SimpleNamespace(ffmpeg=Path(directory) / "fake.exe", scratch=Path(directory), runner=Runner())
                commands = []
                def run(args, scratch, **kwargs):
                    commands.append(args)
                    if "-encoders" in args:
                        return ProcessResult(0, b" V....D h264_nvenc Fake")
                    if "lavfi" in args:
                        self.assertIn("color=c=black:s=320x240:r=24", args)
                        Path(args[-1]).write_bytes(b"invented output")
                        return ProcessResult(0)
                    self.assertEqual(args[args.index("-hwaccel") + 1], "none")
                    return ProcessResult(decode_status)
                with patch("videomate.hardware.platform.system", return_value="Windows"), patch("videomate.hardware.Runner.run", side_effect=run):
                    self.assertEqual(select_encoder(backend), expected)
                self.assertEqual(len(commands), 3 if decode_status == 0 else 35)

    def test_nondefault_nvenc_adapter_can_qualify_after_default_fails(self):
        with tempfile.TemporaryDirectory(prefix="videomate-nvenc-device-generated-") as directory:
            backend = SimpleNamespace(ffmpeg=Path(directory) / "fake.exe", scratch=Path(directory), runner=Runner())
            def run(args, scratch, **kwargs):
                if "-encoders" in args:
                    return ProcessResult(0, b" V....D hevc_nvenc Synthetic")
                if "lavfi" in args:
                    if any(part.startswith("testsrc2=") for part in args):
                        kwargs["watch_file"].write_bytes(b"Generated H.264 route source")
                        return ProcessResult(0)
                    if "-gpu" not in args or args[args.index("-gpu") + 1] != "2":
                        return ProcessResult(1)
                    kwargs["watch_file"].write_bytes(b"Generated HEVC sample")
                elif "hevc_nvenc" in args:
                    if "-gpu" not in args or args[args.index("-gpu") + 1] != "2":
                        return ProcessResult(1)
                    kwargs["watch_file"].write_bytes(b"Generated HEVC route output")
                return ProcessResult(0)
            with patch("videomate.hardware.platform.system", return_value="Windows"), \
                    patch("videomate.hardware.Runner.run", side_effect=run):
                self.assertEqual(select_encoder(backend, all_ready=True, codec="hevc"), ("hevc_nvenc",))
                self.assertEqual(qualify_codec_routes(backend, (("cuda", "hevc_nvenc"),)),
                                 (("cuda", "hevc_nvenc"),))
                self.assertEqual(qualify_devices(backend, (("cuda", "hevc_nvenc"),)),
                                 (("cuda", "hevc_nvenc", 2),))
            self.assertEqual(backend._ready_hevc_nvenc_device, 2)

    def test_hevc_encoder_qualifies_with_ordinary_generated_dimensions(self):
        with tempfile.TemporaryDirectory(prefix="videomate-hevc-check-generated-") as directory:
            backend = SimpleNamespace(ffmpeg=Path(directory) / "fake.exe", scratch=Path(directory), runner=Runner())
            def run(args, scratch, **kwargs):
                if "-encoders" in args:
                    return ProcessResult(0, b" V....D hevc_amf Synthetic")
                if "lavfi" in args:
                    if "color=c=black:s=320x240:r=24" not in args:
                        return ProcessResult(1)  # This synthetic encoder rejects tiny frames.
                    kwargs["watch_file"].write_bytes(b"Generated HEVC sample")
                return ProcessResult(0)
            with patch("videomate.hardware.platform.system", return_value="Windows"), \
                    patch("videomate.hardware.Runner.run", side_effect=run):
                self.assertEqual(select_encoder(backend, codec="hevc"), "hevc_amf")

    def test_encoder_names_are_closed(self):
        with self.assertRaises(VideoMateError):
            video_encoder_args("PRIVATE_CANARY")
