import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from videomate.cli import main
from videomate.errors import VideoMateError
from videomate.support import support_summary


class SupportTests(unittest.TestCase):
    def setUp(self):
        self.example = json.loads((Path(__file__).resolve().parents[1] / "examples/diagnostic-export.synthetic.json").read_text())

    def test_summary_omits_identifiers_durations_and_stream_details(self):
        summary = support_summary(self.example)
        encoded = json.dumps(summary)
        self.assertEqual(summary["files_count"], len(self.example["files"]))
        for forbidden in (self.example["job_ref"], self.example["export_scope"], "duration_us", "streams", "file_ref"):
            self.assertNotIn(forbidden, encoded)
        self.assertTrue(summary["findings"])

    def test_unknown_text_or_encoder_cannot_reach_summary_or_console(self):
        for position in ("extra", "encoder"):
            doc = copy.deepcopy(self.example)
            if position == "extra":
                doc["private_path"] = "PRIVATE_CANARY"
            else:
                doc["files"][0]["attempts"][0]["encoder"] = "PRIVATE_CANARY"
            with self.assertRaises(VideoMateError):
                support_summary(doc)
            with tempfile.TemporaryDirectory(prefix="videomate-support-test-") as directory:
                export = Path(directory) / "invented.json"
                export.write_text(json.dumps(doc))
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    self.assertEqual(main(["support-summary", str(export)]), 2)
                self.assertNotIn("PRIVATE_CANARY", output.getvalue())
                self.assertNotIn(str(export), output.getvalue())
