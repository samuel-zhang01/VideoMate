"""Encoding options use invented metadata and freshly generated media only."""
import os
import re
import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from videomate.diagnostics import create_export, environment
from videomate.encoding import audio_rates, candidate_limit, size_target
from videomate.errors import VideoMateError
from videomate.models import ScanResult
from videomate.preferences import Preferences
from videomate.profiles import apply, extract
from videomate.recovery import RecoveryEngine, RecoveryOptions, command, plan
from videomate.runner import ProcessResult
from videomate.schema import load_json
from videomate.support import support_summary


class EncodingExtraTests(unittest.TestCase):
    def sample(self):
        return ScanResult(integrity="damage_detected", duration_us=10000000,
            streams=[{"kind": "video", "index": 0, "codec": "h264", "width": 128, "height": 128, "pixel_format": "yuv420p"},
                     {"kind": "audio", "index": 1, "codec": "aac", "channels": 1, "sample_rate": 48000}],
            technical={"source_size": 2*1024**2, "streams": {}})

    def test_explicit_audio_options_and_faststart_only_make_closed_arguments(self):
        options = RecoveryOptions(profile="compatible_sdr", audio_normalization="playback", audio_bitrate_kbps=96,
            software_preset="fast", mp4_faststart=False)
        sample = self.sample()
        self.assertEqual(plan(sample, options), ["reencode"])
        args = command(SimpleNamespace(ffmpeg=Path("invented-ffmpeg"), threads=4), Path("invented-source"), Path("invented-output"), sample, "reencode", options)
        self.assertEqual(args[args.index("-filter:a:0")+1], "loudnorm=I=-16:TP=-1.5:LRA=11:linear=false:print_format=none")
        self.assertEqual(args[args.index("-ar:a:0")+1], "48000")
        self.assertEqual(args[args.index("-preset:v:0")+1], "fast")
        self.assertEqual(args[args.index("-b:a:0")+1], "96000")
        self.assertEqual(args[args.index("-movflags")+1], "+write_colr")
        self.assertEqual(audio_rates(sample, sample.streams, options), [96000])
        for changed in (replace(options, audio_normalization="PRIVATE_CANARY"), replace(options, software_preset="PRIVATE_CANARY"),
                        replace(options, profile="preserve_decoded_samples"), replace(options, strategy="remux"), replace(options, mp4_faststart=1)):
            with self.assertRaises(VideoMateError):
                changed.validate()

    def test_mp4_profiles_target_finished_size_without_temporary_caps_or_privacy_changes(self):
        original = Preferences(sensitive=True, migration_local_names=False, max_source_percent=300, max_output_mib=20480)
        for preset in ("Repair — compatible MP4", "Migrate — repair to MP4", "Migrate — MP4 video"):
            selected = apply(original, preset)
            self.assertEqual(selected.rate_control, "source_size")
            self.assertEqual((selected.max_source_percent, selected.max_output_mib), (0, 0))
            self.assertTrue(selected.sensitive)
            self.assertFalse(selected.migration_local_names)
            self.assertIn("audio_normalization", extract(selected))
        self.assertIsNone(candidate_limit(self.sample(), RecoveryOptions()))
        self.assertEqual(size_target(self.sample(), RecoveryOptions(profile="compatible_sdr", rate_control="source_size")), 2*1024**2)
        self.assertIsNone(size_target(self.sample(), RecoveryOptions()))

    def test_cli_and_saved_profiles_keep_encoding_choices_without_source_history(self):
        from videomate.cli import main
        from videomate.preferences import save_preferences, load_preferences
        with tempfile.TemporaryDirectory(prefix="videomate-encoding-settings-generated-") as temporary:
            root = Path(temporary).resolve()
            selected = Preferences(audio_normalization="broadcast", audio_bitrate_kbps=128, software_preset="slow",
                mp4_faststart=False, size_tolerance_percent=15, profile="compatible_sdr")
            selected = replace(selected, profiles={"Generated encoding profile": extract(selected)})
            save_preferences(root / "settings.json", selected)
            loaded = load_preferences(root / "settings.json")
            self.assertEqual(loaded, selected)
            self.assertEqual(apply(Preferences(), "Repair — compatible MP4").audio_normalization, "off")
            with patch("videomate.migration.migrate_local", return_value=0) as migrate, contextlib.redirect_stdout(io.StringIO()):
                code = main(["migrate", "--workspace", str(root / "workspace"), "--input", "GENERATED_SELECTION",
                    "--preset", "Migrate — repair to MP4", "--audio-normalization", "playback", "--audio-bitrate-kbps", "96",
                    "--software-preset", "fast", "--no-mp4-faststart", "--size-tolerance-percent", "20"])
            self.assertEqual(code, 0)
            options = migrate.call_args.kwargs["recovery"]
            self.assertEqual((options.audio_normalization, options.audio_bitrate_kbps, options.software_preset), ("playback", 96, "fast"))
            self.assertFalse(options.mp4_faststart)
            self.assertEqual(options.size_tolerance_percent, 20)
            self.assertEqual(options.max_output_bytes, 0)


@unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_FFMPEG") and os.environ.get("VIDEOMATE_TEST_FFPROBE"), "Explicit generated-media backend not configured")
class EncodingExtraIntegrationTests(unittest.TestCase):
    def setUp(self):
        from test_recovery_integration import RecoveryIntegrationTests
        self.fixture = RecoveryIntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_best_effort_oversize_still_requires_full_verification(self):
        f = self.fixture
        with patch('videomate.recovery.size_target', return_value=1):
            result = f.recover(f.source, RecoveryOptions(strategy='reencode', profile='compatible_sdr', force=True,
                rate_control='source_size', size_policy='best_effort', hardware_encoding=False))
        self.assertEqual(result.recovery['recovery_state'], 'verified_with_losses')
        self.assertTrue(all(v == 'passed' for v in result.recovery['verification'].values()))
        self.assertIn('size_above_target', result.recovery['notes'])
        self.assertNotIn('size_target_met', result.recovery['notes'])
        self.assertEqual(len(result.recovery['attempts']), 2)
        encoded = create_export([result], uuid4(), b'G' * 32, environment('9.0.2', '9.0.2'), synthetic=True)
        self.assertIn(b'size_above_target', encoded)

    def test_generated_loudness_conversion_preserves_shape_and_exports_only_fixed_notes(self):
        f = self.fixture
        from videomate.inspection import Inspector
        from videomate.policy import SyntheticScope
        before = Inspector(f.backend, f.scope).inspect(f.source)
        result = f.recover(f.source, RecoveryOptions(strategy="reencode", profile="compatible_sdr", force=True,
            audio_normalization="playback", audio_bitrate_kbps=96, software_preset="fast", hardware_encoding=False,
            rate_control="source_size"))
        self.assertEqual(result.recovery["recovery_state"], "verified_with_losses", result.recovery)
        self.assertIn("audio_normalized", result.recovery["losses"])
        output = Path(result.recovery["private_output"])
        self.assertLessEqual(output.stat().st_size, f.source.stat().st_size * 1.25)
        original_scope = f.backend.scope
        try:
            f.backend.scope = SyntheticScope(frozenset({output}))
            after = Inspector(f.backend, f.backend.scope).inspect(output)
        finally:
            f.backend.scope = original_scope
        self.assertEqual(after.integrity, "no_errors_detected")
        def mean_volume(path):
            measured = f.backend.runner.run([str(f.backend.ffmpeg), "-nostdin", "-v", "info", "-i", str(path),
                "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"], f.root)
            self.assertEqual(measured.returncode, 0)
            return float(re.search(rb"mean_volume: (-?[0-9.]+) dB", measured.stderr)[1])
        self.assertGreater(mean_volume(output) - mean_volume(f.source), 3)
        for original, converted in zip(before.streams, after.streams):
            for key in ("width", "height", "sample_rate", "channels"):
                self.assertEqual(original.get(key), converted.get(key))
        encoded = create_export([result], uuid4(), b"G" * 32, environment("9.0.2", "9.0.2"), synthetic=True)
        self.assertNotIn(b"synthetic-private-canary", encoded)
        summary = support_summary(load_json(encoded))
        self.assertEqual(summary["recovery_notes"]["loudness_playback"], 1)
        bad = load_json(encoded)
        bad["files"][0]["recovery_notes"].append("PRIVATE_CANARY")
        with self.assertRaises(VideoMateError):
            support_summary(bad)

    def test_oversized_finished_encode_gets_one_retry_and_is_never_published(self):
        f = self.fixture
        calls = []
        def too_large(args, scratch, **kwargs):
            calls.append(args)
            Path(args[-1]).write_bytes(b"x" * (2 * 1024**2))
            return ProcessResult(0)
        from videomate.inspection import Inspector
        original = Inspector(f.backend, f.scope).inspect(f.source)
        engine = RecoveryEngine(f.backend, f.scope, f.candidates, f.outputs, f.root / "code")
        with patch.object(f.backend.runner, "run", side_effect=too_large):
            result = engine.recover(f.source, original, RecoveryOptions(profile="compatible_sdr", strategy="reencode", force=True,
                hardware_encoding=False, rate_control="target_size", target_size_mib=1))
        self.assertEqual(len(calls), 2)
        self.assertLess(int(calls[1][calls[1].index("-b:v:0")+1]), int(calls[0][calls[0].index("-b:v:0")+1]))
        self.assertEqual(result.recovery["recovery_state"], "failed")
        self.assertIn("size_target_exceeded", result.recovery["notes"])
        self.assertEqual(list(f.outputs.iterdir()), [])
        self.assertEqual(list(f.candidates.iterdir()), [])
        encoded = create_export([result], uuid4(), b"G" * 32, environment("9.0.2", "9.0.2"), synthetic=True)
        self.assertEqual(support_summary(load_json(encoded))["attempts"], {"failed:size_target_exceeded": 2})

    def test_size_adjustment_retry_can_produce_a_fully_verified_output(self):
        f = self.fixture
        run = f.backend.runner.run
        encoded_attempts = []
        def first_oversized(args, scratch, **kwargs):
            if kwargs.get("watch_file") is not None:
                encoded_attempts.append(args)
                if len(encoded_attempts) == 1:
                    Path(args[-1]).write_bytes(b"Generated rejected size trial" * 80000)
                    return ProcessResult(0)
            return run(args, scratch, **kwargs)
        with patch.object(f.backend.runner, "run", side_effect=first_oversized):
            result = f.recover(f.source, RecoveryOptions(strategy="reencode", profile="compatible_sdr", force=True,
                rate_control="target_size", target_size_mib=1, hardware_encoding=False))
        self.assertEqual(len(encoded_attempts), 2)
        self.assertEqual(result.recovery["recovery_state"], "verified_with_losses")
        self.assertTrue(all(value == "passed" for value in result.recovery["verification"].values()))
        self.assertIn("size_adjustment_retry", result.recovery["notes"])
        self.assertLessEqual(Path(result.recovery["private_output"]).stat().st_size, 1.25 * 1024**2)
        self.assertEqual(list(f.candidates.iterdir()), [])
