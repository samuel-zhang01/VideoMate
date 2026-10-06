"""Private resume checks read only marker files created in their own temp root."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videomate.errors import VideoMateError
from videomate.inspection import _fingerprint
from videomate.local_scan import scan_local
from videomate.models import ScanResult
from videomate.policy import create_workspace
from videomate.private_state import LIVE_REPORTS


class PrivateResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videomate-private-resume-generated-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = create_workspace(self.root / "workspace", self.root / "code")
        self.sources = [self.root / "PRIVATE_CANARY_ONE.mp4", self.root / "PRIVATE_CANARY_TWO.mp4"]
        for index, path in enumerate(self.sources):
            path.write_bytes(b"Generated non-media marker " + bytes([index]))
        exe = self.root / "fake.exe"
        exe.write_bytes(b"Never executed; inspection is mocked")
        self.bundle = SimpleNamespace(ffmpeg=exe, ffprobe=exe, version="9.0.2")
        self.passphrase = "invented test-only passphrase"
        self.patch_bundle = patch("videomate.local_scan.load_bundle", return_value=self.bundle)
        self.patch_bundle.start()
        self.addCleanup(self.patch_bundle.stop)
        self.inspections = []
        def fake_inspect(instance, source, depth=None):
            self.inspections.append(source)
            return ScanResult(integrity="unreadable", fingerprint=_fingerprint(source))
        self.patch_inspect = patch("videomate.local_scan.Inspector.inspect", fake_inspect)
        self.patch_inspect.start()
        self.addCleanup(self.patch_inspect.stop)

    def call(self, inputs, **kwargs):
        return scan_local([str(p) for p in inputs], self.workspace, hardware_decoding=False,
                          cpu_threads=1, max_runners=1, private_resume=True, passphrase=self.passphrase, **kwargs)

    def interrupted_checkpoint(self):
        cancel = threading.Event()
        messages = []
        def emit(message):
            messages.append(message)
            if message.startswith("input-1: unreadable;"):
                cancel.set()
        with self.assertRaises(KeyboardInterrupt):
            self.call(self.sources, cancel_event=cancel, emit=emit)
        identifier = next(message[5:] for message in messages if message.startswith("Job: "))
        self.addCleanup(lambda: LIVE_REPORTS.pop(identifier, None))
        return identifier

    def test_interrupt_reselect_renamed_inputs_resume_and_erase_checkpoint(self):
        identifier = self.interrupted_checkpoint()
        checkpoint = self.workspace / "state" / ("checkpoint-" + identifier + ".json")
        encoded = checkpoint.read_text()
        self.assertNotIn("PRIVATE_CANARY", encoded)
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn(self.passphrase, encoded)
        self.assertEqual(list((self.workspace / "jobs").iterdir()), [])
        self.assertEqual(len(json.loads(encoded)["payload"]["entries"]), 1)
        moved = self.root / "renamed-generated.mp4"
        self.sources[0].rename(moved)
        self.inspections.clear()
        self.assertEqual(self.call([self.sources[1], moved], checkpoint_id=identifier, emit=lambda _: None), 1)
        self.assertEqual(self.inspections, [self.sources[1]])
        self.assertFalse(checkpoint.exists())
        self.assertEqual(list((self.workspace / "jobs").iterdir()), [])
        self.assertEqual(list((self.workspace / "state").glob("mapping-*.json")), [])

    def test_wrong_passphrase_tampering_and_changed_sources_fail_closed(self):
        identifier = self.interrupted_checkpoint()
        checkpoint = self.workspace / "state" / ("checkpoint-" + identifier + ".json")
        original = checkpoint.read_bytes()
        phrase = self.passphrase
        self.passphrase = "wrong but sufficiently long passphrase"
        with self.assertRaises(VideoMateError) as error:
            self.call(self.sources, checkpoint_id=identifier, emit=lambda _: None)
        self.assertEqual(error.exception.code, "checkpoint_invalid")
        self.passphrase = phrase
        envelope = json.loads(original)
        envelope["payload"]["sources"][0] = "0" * 64
        checkpoint.write_text(json.dumps(envelope))
        with self.assertRaises(VideoMateError) as error:
            self.call(self.sources, checkpoint_id=identifier, emit=lambda _: None)
        self.assertEqual(error.exception.code, "checkpoint_invalid")
        checkpoint.write_bytes(original)
        self.sources[1].write_bytes(b"Changed generated marker")
        with self.assertRaises(VideoMateError) as error:
            self.call(self.sources, checkpoint_id=identifier, emit=lambda _: None)
        self.assertEqual(error.exception.code, "checkpoint_sources_changed")
        self.assertEqual(list((self.workspace / "jobs").iterdir()), [])
