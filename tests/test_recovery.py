import copy
import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomate.errors import VideoMateError
from videomate.models import Finding, ScanResult
from videomate.recovery import RecoveryOptions, encoding_options, plan, publish, verification


def result():
    return ScanResult(integrity="damage_detected", duration_us=2000000,
                      streams=[{"index": 0, "kind": "video", "codec": "mpeg4", "width": 160, "height": 120, "pixel_format": "yuv420p"}],
                      findings=[Finding("decoder_error")],
                      technical={"start_us": 0, "streams": {"0": {"start_us": 0, "decoded_us": 2000000, "field_order": "progressive"}}})


class RecoveryTests(unittest.TestCase):
    def test_planner_does_not_blindly_attempt_unreadable_or_healthy_files(self):
        r = result()
        self.assertEqual(plan(r, RecoveryOptions()), ["reencode"])
        r.integrity = "unreadable"
        with self.assertRaises(VideoMateError):
            plan(r, RecoveryOptions(force=True))
        r.integrity, r.findings = "no_errors_detected", []
        self.assertEqual(plan(r, RecoveryOptions()), [])
        self.assertEqual(plan(r, RecoveryOptions(force=True, strategy="remux")), ["remux"])

    def test_mismatched_gpu_routes_are_tried_before_software(self):
        from videomate.backend import FFmpegBackend
        from videomate.hardware_activity import HardwareActivity
        from videomate.inspection import _fingerprint
        from videomate.policy import SyntheticScope
        from videomate.recovery import RecoveryEngine
        from videomate.runner import ProcessResult, Runner

        with tempfile.TemporaryDirectory(prefix="videomate-gpu-fallback-generated-") as directory:
            root = Path(directory).resolve()
            source = root / "generated.avi"
            source.write_bytes(b"Generated source marker")
            executable = root / "fake.exe"
            executable.write_bytes(b"Generated backend marker")
            scope = SyntheticScope(frozenset({source}))
            backend = FFmpegBackend(executable, executable, root, Runner(), scope=scope)
            routes = (("software", "hevc_nvenc", 0), ("software", "hevc_amf", None),
                      ("software", "hevc_nvenc", 2), ("software", "hevc_qsv", None),
                      ("software", "hevc_nvenc", 3))
            activity = HardwareActivity()
            backend.hardware_routes = routes
            backend.hardware_route_gates = {(encoder, device): activity.gate(index, 1)
                                            for index, (_, encoder, device) in enumerate(routes, 1)}
            original = result()
            original.fingerprint = _fingerprint(source)
            candidates = root / "candidates"
            candidates.mkdir()
            commands = []
            def unavailable(args, scratch, **kwargs):
                commands.append(args)
                return ProcessResult(1)
            engine = RecoveryEngine(backend, scope, candidates, root / "output", root / "code")
            with patch.object(backend.runner, "run", side_effect=unavailable):
                recovered = engine.recover(source, original, RecoveryOptions(strategy="reencode",
                    profile="compatible_sdr", video_codec="hevc", force=True))
            self.assertEqual([attempt["encoder"] for attempt in recovered.recovery["attempts"]],
                             [route[1] for route in routes] + ["libx265"])
            self.assertEqual([args[args.index("-gpu") + 1] for args in commands if "-gpu" in args],
                             ["0", "2", "3"])
            self.assertEqual([gate.peak for gate in backend.hardware_route_gates.values()], [1] * len(routes))
            self.assertEqual(recovered.recovery["recovery_state"], "failed")

    def test_repeated_timing_mismatch_skips_redundant_full_decodes(self):
        from videomate.backend import FFmpegBackend
        from videomate.inspection import _fingerprint
        from videomate.models import Depth
        from videomate.policy import SyntheticScope
        from videomate.recovery import RecoveryEngine
        from videomate.runner import ProcessResult, Runner

        with tempfile.TemporaryDirectory(prefix="videomate-generated-preflight-") as directory:
            root = Path(directory).resolve()
            source = root / "generated.avi"
            source.write_bytes(b"Generated source marker")
            executable = root / "fake.exe"
            executable.write_bytes(b"Generated backend marker")
            candidates = root / "candidates"
            candidates.mkdir()
            backend = FFmpegBackend(executable, executable, root, Runner(),
                                    scope=SyntheticScope(frozenset({source})))
            backend.hardware_routes = (("software", "hevc_nvenc", 0), ("software", "hevc_amf", None))
            backend.hardware_route_codec = "hevc"
            backend.hardware_route_gates = {}
            original = result()
            original.fingerprint = _fingerprint(source)
            bad = copy.deepcopy(original)
            bad.integrity, bad.findings, bad.duration_us = "no_errors_detected", [], 3_000_000
            bad.streams[0]["codec"] = "hevc"
            quick = copy.deepcopy(bad)
            quick.depth, quick.integrity = Depth.QUICK, "quick_check_only"
            depths = []

            def encode(args, scratch, **kwargs):
                Path(args[-1]).write_bytes(b"Generated candidate marker")
                return ProcessResult(0)

            def inspect(candidate, depth=Depth.FULL):
                depths.append(depth)
                return copy.deepcopy(quick if depth == Depth.QUICK else bad)

            engine = RecoveryEngine(backend, backend.scope, candidates, root / "output", root)
            with patch.object(backend.runner, "run", side_effect=encode), \
                 patch("videomate.recovery.Inspector.inspect", side_effect=inspect):
                recovered = engine.recover(source, original, RecoveryOptions(strategy="reencode",
                    profile="compatible_sdr", video_codec="hevc", force=True))
            self.assertEqual(depths, [Depth.FULL, Depth.QUICK, Depth.QUICK])
            self.assertEqual(recovered.recovery["recovery_state"], "verification_inconclusive")
            self.assertEqual([attempt["reason"] for attempt in recovered.recovery["attempts"]],
                             ["verification_failed"] * 3)
            self.assertEqual(recovered.recovery["attempts"][1]["verification"]["decode_check"], "not_run")

    def test_auxiliary_tracks_require_explicit_permission(self):
        r = result()
        r.streams.append({"index": 1, "kind": "subtitle"})
        with self.assertRaises(VideoMateError):
            plan(r, RecoveryOptions())
        self.assertEqual(plan(r, RecoveryOptions(allow_track_loss=True)), ["reencode"])

    def test_compatible_profile_rejects_hdr_and_unapproved_pixel_conversion(self):
        r = result()
        r.technical["streams"]["0"]["color_transfer"] = "smpte2084"
        with self.assertRaises(VideoMateError):
            encoding_options(r, r.streams, "compatible_sdr")
        r.technical["streams"]["0"]["color_transfer"] = "bt709"
        r.streams[0]["pixel_format"] = "yuv420p10le"
        with self.assertRaises(VideoMateError):
            encoding_options(r, r.streams, "compatible_sdr")

    def test_verification_rejects_decode_geometry_track_and_timing_failures(self):
        original = result()
        good = copy.deepcopy(original)
        good.integrity, good.findings = "no_errors_detected", []
        options = RecoveryOptions()
        self.assertTrue(all(x == "passed" for x in verification(original, good, "reencode", options).values()))
        for mutate, failed in [
            (lambda r: setattr(r, "integrity", "damage_detected"), "decode_check"),
            (lambda r: r.streams[0].update(width=80), "stream_check"),
            (lambda r: setattr(r, "streams", []), "stream_check"),
            (lambda r: setattr(r, "duration_us", 1000000), "timing_check"),
            (lambda r: r.technical["streams"]["0"].update(start_us=1000000), "timing_check"),
        ]:
            bad = copy.deepcopy(good)
            mutate(bad)
            self.assertEqual(verification(original, bad, "reencode", options)[failed], "failed")

    def test_shorter_output_requires_policy_and_never_accepts_longer_output(self):
        original, shorter = result(), result()
        shorter.integrity, shorter.duration_us = "no_errors_detected", 1000000
        self.assertEqual(verification(original, shorter, "reencode", RecoveryOptions())["timing_check"], "failed")
        self.assertEqual(verification(original, shorter, "reencode", RecoveryOptions(allow_shorter=True))["timing_check"], "failed")
        permitted = RecoveryOptions(allow_shorter=True, max_shorter_percent=50)
        self.assertEqual(verification(original, shorter, "reencode", permitted)["timing_check"], "passed")
        shorter.duration_us = 3000000
        self.assertEqual(verification(original, shorter, "reencode", permitted)["timing_check"], "failed")

    def test_publication_never_overwrites_and_preserves_candidate_on_collision(self):
        with tempfile.TemporaryDirectory(prefix="videomate-synthetic-publish-") as temporary:
            root = Path(temporary).resolve()
            candidate, target = root / "candidate.bin", root / "existing.bin"
            candidate.write_bytes(b"synthetic candidate")
            target.write_bytes(b"unrelated synthetic output")
            with self.assertRaises(VideoMateError):
                publish(candidate, target)
            self.assertEqual(target.read_bytes(), b"unrelated synthetic output")
            self.assertTrue(candidate.exists())
            fresh = root / "new.bin"
            publish(candidate, fresh)
            self.assertEqual(fresh.read_bytes(), b"synthetic candidate")
            self.assertFalse(candidate.exists())

    def test_manual_interval_is_bounded_and_requires_reencoding(self):
        with self.assertRaises(VideoMateError):
            RecoveryOptions(keep_start_us=100, keep_end_us=50).validate()
        with self.assertRaises(VideoMateError):
            RecoveryOptions(strategy="remux", keep_start_us=0, keep_end_us=100).validate()
        with self.assertRaises(VideoMateError):
            plan(result(), RecoveryOptions(keep_start_us=0, keep_end_us=3000000))

    def test_publication_preflight_uses_only_owned_markers_and_cleans_them(self):
        from videomate.publication import qualify_publication
        with tempfile.TemporaryDirectory(prefix="videomate-generated-publication-") as temporary:
            root = Path(temporary).resolve()
            staging, output = root / "staging", root / "output"
            staging.mkdir()
            output.mkdir()
            qualify_publication(staging, output)
            self.assertEqual(list(staging.iterdir()), [])
            self.assertEqual(list(output.iterdir()), [])
            if os.name == "nt":
                with patch("videomate.publication.os.link", side_effect=OSError(errno.ENOTSUP, "GENERATED_PRIVATE_CANARY")):
                    qualify_publication(staging, output)
            with patch("videomate.publication.publish", side_effect=VideoMateError("output_access_denied")):
                with self.assertRaises(VideoMateError) as error:
                    qualify_publication(staging, output)
                self.assertEqual(error.exception.code, "output_access_denied")
            self.assertEqual(list(staging.iterdir()), [])
            self.assertEqual(list(output.iterdir()), [])

    def test_filesystem_reasons_are_fixed_and_stage_specific(self):
        from videomate.publication import filesystem_reason
        for number, expected in ((errno.ENOSPC, "disk_limit"), (errno.EACCES, "output_access_denied"),
                                 (errno.ENOTSUP, "output_filesystem_unsupported"), (errno.EXDEV, "output_filesystem_unsupported"),
                                 (errno.ENAMETOOLONG, "output_path_too_long"), (errno.EIO, "output_publish_failed")):
            self.assertEqual(filesystem_reason(OSError(number, "GENERATED_PRIVATE_CANARY"), "output_publish_failed"), expected)
        self.assertEqual(filesystem_reason(PermissionError(errno.EACCES, "GENERATED_PRIVATE_CANARY"), "source_read_failed"), "source_read_failed")
