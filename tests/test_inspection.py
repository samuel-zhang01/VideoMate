import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomate.backend import classify_log
from videomate.demo import SyntheticBackend
from videomate.errors import VideoMateError
from videomate.inspection import Inspector, duration_us
from videomate.models import Depth, recovery_suggestion
from videomate.policy import SyntheticScope
from videomate.runner import ProcessResult


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videomate-test-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name).resolve() / "synthetic-marker.bin"
        self.source.write_bytes(b"synthetic fixture marker")
        self.scope = SyntheticScope(frozenset({self.source}))

    def test_explicit_selection_precedes_every_source_operation(self):
        backend = SyntheticBackend("healthy")
        with patch.object(Path, "stat", side_effect=AssertionError("Input was accessed")):
            with self.assertRaisesRegex(VideoMateError, "Select local files"):
                Inspector(backend).inspect(Path("NEVER_READ_THIS"))

    def test_scope_rejects_unlisted_path_before_stat(self):
        with patch.object(Path, "stat", side_effect=AssertionError("Input was accessed")):
            with self.assertRaises(VideoMateError):
                self.scope.authorize(Path("NEVER_READ_THIS"))

    def test_full_healthy_and_original_unchanged(self):
        before = self.source.read_bytes()
        result = Inspector(SyntheticBackend("healthy"), self.scope).inspect(self.source)
        self.assertEqual(result.integrity, "no_errors_detected")
        self.assertEqual(result.completeness, "unknown")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(len(result.streams), 2)
        self.assertEqual(self.source.read_bytes(), before)

    def test_quick_is_never_full_pass(self):
        result = Inspector(SyntheticBackend("healthy"), self.scope).inspect(self.source, Depth.QUICK)
        self.assertEqual(result.integrity, "quick_check_only")
        self.assertTrue(all(s["coverage"] == "not_checked" for s in result.streams))

    def test_audio_damage_detected_even_when_video_healthy(self):
        result = Inspector(SyntheticBackend("damaged_audio"), self.scope).inspect(self.source)
        self.assertEqual(result.integrity, "damage_detected")
        self.assertEqual(result.findings[0].stream_index, 1)
        self.assertEqual(recovery_suggestion(result), "reencode_candidate")

    def test_unreadable_is_not_declared_unrecoverable(self):
        result = Inspector(SyntheticBackend("unreadable"), self.scope).inspect(self.source)
        self.assertEqual(result.integrity, "unreadable")
        self.assertEqual(recovery_suggestion(result), "specialist_review")

    def test_resource_limit_is_inconclusive(self):
        backend = SyntheticBackend("healthy")
        backend.decode = lambda source, index: ProcessResult(-1, limited=True)
        result = Inspector(backend, self.scope).inspect(self.source)
        self.assertEqual((result.state, result.integrity), ("partial", "inconclusive"))

    def test_unsupported_decoder_not_corrupt(self):
        backend = SyntheticBackend("healthy")
        backend.decode = lambda source, index: ProcessResult(1, stderr=b"[error] Decoder synthetic not found\n")
        result = Inspector(backend, self.scope).inspect(self.source)
        self.assertEqual(result.integrity, "unsupported")
        self.assertTrue(all(s["coverage"] == "unsupported" for s in result.streams))

    def test_no_output_despite_exit_zero_is_not_pass(self):
        backend = SyntheticBackend("healthy")
        backend.decode = lambda source, index: ProcessResult(0, b"frame=0\nprogress=end\n")
        result = Inspector(backend, self.scope).inspect(self.source)
        self.assertEqual((result.state, result.integrity), ("partial", "inconclusive"))

    def test_unknown_warning_is_inconclusive_not_corrupt(self):
        backend = SyntheticBackend("healthy")
        backend.decode = lambda source, index: ProcessResult(0, b"frame=1\nout_time_us=1\nprogress=end\n", b"[warning] arbitrary private text\n")
        result = Inspector(backend, self.scope).inspect(self.source)
        self.assertEqual(result.integrity, "inconclusive")
        self.assertNotIn("private", repr(result))

    def test_changed_source_invalidates_result(self):
        backend = SyntheticBackend("healthy")
        original = backend.decode
        def change(source, index):
            source.write_bytes(b"synthetic changed marker" * (index + 1))
            return original(source, index)
        backend.decode = change
        result = Inspector(backend, self.scope).inspect(self.source)
        self.assertEqual((result.state, result.integrity), ("partial", "inconclusive"))
        self.assertIn("input_changed", {f.category for f in result.findings})

    def test_bad_probe_json_and_duplicate_streams(self):
        for data in (b'{"streams":[]', b'{"streams":[],"streams":[]}',
                     json.dumps({"streams": [{"index": 0}, {"index": 0}]}).encode()):
            backend = SyntheticBackend("healthy")
            backend.probe = lambda source: ProcessResult(0, data)
            result = Inspector(backend, self.scope).inspect(self.source)
            self.assertEqual(result.integrity, "inconclusive")

    def test_raw_timestamps_not_collected_or_exported(self):
        backend = SyntheticBackend("healthy")
        original = backend.probe
        def probe(source):
            data = json.loads(original(source).stdout)
            for stream in data["streams"]:
                stream.update(start_time="1700000000.0", timecode="PRIVATE_TIMECODE")
            return ProcessResult(0, json.dumps(data).encode())
        backend.probe = probe
        result = Inspector(backend, self.scope).inspect(self.source)
        self.assertNotIn("1700000000", repr(result))
        self.assertNotIn("PRIVATE_TIMECODE", repr(result))

    def test_invalid_durations_remain_unknown(self):
        for value in ("NaN", "Infinity", "-1", "private text", None, "1e999999"):
            self.assertIsNone(duration_us(value))
        self.assertEqual(duration_us("1.25"), 1250000)

    def test_repeated_errors_aggregated_without_text(self):
        findings = classify_log(b"[error] Invalid NAL PRIVATE_A\n[error] Invalid NAL PRIVATE_B\n")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].count, 2)
        self.assertNotIn("PRIVATE", repr(findings))

    def test_matroska_premature_end_is_classified(self):
        findings = classify_log(b"[warning] File ended prematurely\n")
        self.assertEqual(findings[0].category, "suspected_truncation")
