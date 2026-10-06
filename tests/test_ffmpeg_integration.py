"""Opt-in real backend test; every media input is generated in this test.

Set VIDEOMATE_TEST_FFMPEG and VIDEOMATE_TEST_FFPROBE to explicit trusted
executables. There is deliberately no environment option for existing media.
"""

import hashlib
import contextlib
import io
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from videomate.backend import FFmpegBackend
from videomate.cli import main
from videomate.dependencies import load_bundle
from videomate.inspection import Inspector
from videomate.policy import SyntheticScope, create_workspace
from videomate.runner import Runner
from videomate.schema import validate_export


@unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_FFMPEG") and os.environ.get("VIDEOMATE_TEST_FFPROBE"),
                     "Explicit synthetic-test FFmpeg/FFprobe binaries not configured")
class FFmpegIntegrationTests(unittest.TestCase):
    def test_generated_audio_video_and_unreadable_input(self):
        with tempfile.TemporaryDirectory(prefix="videomate-generated-media-") as temporary:
            root = Path(temporary).resolve()
            ffmpeg = Path(os.environ["VIDEOMATE_TEST_FFMPEG"])
            ffprobe = Path(os.environ["VIDEOMATE_TEST_FFPROBE"])
            source = root / "synthetic.mkv"
            invalid = root / "synthetic-invalid.bin"
            scope = SyntheticScope(frozenset({source, invalid}))
            backend = FFmpegBackend(ffmpeg, ffprobe, root, Runner(timeout=30), scope=scope)
            outcome = backend.runner.run([
                str(backend.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-n",
                "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-t", "1", "-c:v", "ffv1", "-c:a", "pcm_s16le",
                "-metadata", "title=SYNTHETIC_PRIVATE_CANARY", str(source),
            ], root)
            self.assertEqual(outcome.returncode, 0, "Synthetic media generation failed (raw logs intentionally omitted)")
            self.assertFalse(outcome.limited)
            before = hashlib.sha256(source.read_bytes()).digest()
            invalid.write_bytes(b"intentionally non-media synthetic fixture")
            inspector = Inspector(backend, scope)
            result = inspector.inspect(source)
            self.assertEqual(result.integrity, "no_errors_detected")
            self.assertEqual(len(result.streams), 2)
            self.assertNotIn("SYNTHETIC_PRIVATE_CANARY", repr(result))
            self.assertEqual(before, hashlib.sha256(source.read_bytes()).digest())
            self.assertEqual(inspector.inspect(invalid).integrity, "unreadable")

    def test_generated_legacy_formats_mp4_truncation_and_cli(self):
        with tempfile.TemporaryDirectory(prefix="videomate-generated-media-") as temporary:
            root = Path(temporary).resolve()
            ffmpeg, ffprobe = Path(os.environ["VIDEOMATE_TEST_FFMPEG"]), Path(os.environ["VIDEOMATE_TEST_FFPROBE"])
            inputs = [root / "synthetic-private-canary.mp4", root / "synthetic.avi", root / "synthetic.flv"]
            broken = root / "synthetic-missing-moov.mp4"
            scope = SyntheticScope(frozenset([*inputs, broken]))
            backend = FFmpegBackend(ffmpeg, ffprobe, root, Runner(timeout=30), scope=scope)
            for source, codec in zip(inputs, ("libx264", "mpeg4", "flv")):
                outcome = backend.runner.run([
                    str(backend.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-n",
                    "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25",
                    "-t", "1", "-c:v", codec, "-metadata", "title=synthetic-private-canary", str(source),
                ], root)
                self.assertEqual(outcome.returncode, 0, "Synthetic format generation failed; raw logs omitted")
                result = Inspector(backend, scope).inspect(source)
                self.assertEqual(result.integrity, "no_errors_detected", source.suffix)
            # Deliberately remove a top-level moov box from this test's own MP4.
            data = inputs[0].read_bytes()
            position = 0
            while position + 8 <= len(data):
                size, kind = struct.unpack_from(">I4s", data, position)
                self.assertGreaterEqual(size, 8)
                if kind == b"moov":
                    broken.write_bytes(data[:position] + data[position + size:])
                    break
                position += size
            self.assertTrue(broken.is_file(), "Synthetic MP4 had no removable moov box")
            result = Inspector(backend, scope).inspect(broken)
            self.assertEqual(result.integrity, "unreadable")
            self.assertIn("missing_initialization", {finding.category for finding in result.findings})
            # Exercise the public CLI only on the files generated above.
            dependency_root = ffmpeg.parents[2]
            if not (ffmpeg.parent.parent / "manifest.json").is_file():
                return  # Direct external test binaries may not be provisioned as a bundle.
            load_bundle(dependency_root)
            workspace = create_workspace(root / "workspace", root / "code")
            before = {file: hashlib.sha256(file.read_bytes()).digest() for file in (inputs[0], broken)}
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = main(["scan", "--test-files", "--workspace", str(workspace),
                               "--dependencies", str(dependency_root), "--input", str(inputs[0]), "--input", str(broken)])
            self.assertEqual(status, 1, "Synthetic CLI scan failed; private messages omitted")
            self.assertNotIn("synthetic-private-canary", out.getvalue() + err.getvalue())
            reports = list((workspace / "export-review").glob("*.log"))
            self.assertEqual(len(reports), 1)
            text = reports[0].read_text()
            self.assertNotIn("synthetic-private-canary", text)
            self.assertNotIn(str(root), text)
            self.assertIn("no_errors_detected: 1", text)
            self.assertIn("unreadable: 1", text)
            for file, digest in before.items():
                self.assertEqual(hashlib.sha256(file.read_bytes()).digest(), digest)
