"""Adversarial diagnostic tests use invented canaries and owned temporary logs."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from videomate.cli import main
from videomate.backend import classify_log
from videomate.diagnostics import create_export, environment
from videomate.errors import VideoMateError
from videomate.event_log import EventLog
from videomate.models import ScanResult
from videomate.preferences import Preferences
from videomate.runner import ProcessResult
from videomate.support import support_summary
from videomate.trace import record_trace, worker_trace, validate_trace


class WorkerDiagnosticTests(unittest.TestCase):
    def test_every_fixed_worker_error_can_be_exported_without_free_text(self):
        from videomate.errors import MESSAGES
        from videomate.schema import validate_export
        for code in MESSAGES:
            result = ScanResult()
            record_trace(result, worker_trace("inspection", outcome="blocked", error_code=code))
            document = create_export([result], uuid4(), bytes(32), environment("0.8.0", "9.0.2"), synthetic=True)
            validate_export(json.loads(document))
    def result(self):
        result = ScanResult(integrity="unreadable")
        process = ProcessResult(1, stderr=b"[error] invalid NAL in PRIVATE_CANARY.mp4\nSECRET/DRIVER/PATH", elapsed_ms=29)
        record_trace(result, worker_trace("decode", process, decoder="cuda", outcome="fallback", threads=4))
        return result

    def test_export_and_summary_contain_only_closed_worker_facts(self):
        encoded = create_export([self.result()], uuid4(), bytes(32), environment("9.0.2", "9.0.2"), synthetic=True)
        self.assertNotIn(b"PRIVATE_CANARY", encoded)
        self.assertNotIn(b"SECRET", encoded)
        doc = json.loads(encoded)
        details = doc["files"][0]["diagnostics"][0]
        self.assertEqual(details["elapsed_ms"], 29)
        self.assertEqual(details["error_code"], "ffmpeg_process_failed")
        self.assertEqual(details["messages"][0]["category"], "decoder_error")
        summary = support_summary(doc)
        self.assertNotIn(doc["files"][0]["file_ref"], json.dumps(summary))

    def test_unknown_fields_types_and_raw_strings_fail_closed(self):
        original = self.result().diagnostics[0]
        for patch_fields in ({"path": "PRIVATE_CANARY"}, {"decoder": "PRIVATE_CANARY"}, {"decoder": []},
                             {"threads": True}, {"return_code": 2**40}, {"messages": [{"raw": "PRIVATE_CANARY"}]}):
            with self.assertRaises(VideoMateError):
                validate_trace({**original, **patch_fields})

    def test_sensitive_detailed_log_requires_separate_opt_in(self):
        with tempfile.TemporaryDirectory(prefix="videomate-safe-logs-generated-") as directory:
            root = Path(directory).resolve()
            job = SimpleNamespace(workspace=root, id="PRIVATE_CANARY")
            with patch("videomate.event_log.storage_directory", side_effect=AssertionError("Forbidden default logging")):
                EventLog(job, {"sensitive": True, "write_logs": True}).close()
            log = EventLog(job, {"sensitive": True, "diagnostic_logs": True})
            log.write("started")
            log.details(self.result(), 1)
            with self.assertRaises(VideoMateError):
                log.details(ScanResult(diagnostics=[{"path": "PRIVATE_CANARY"}]), 1)
            log.close()
            log.close()
            logs = list((root / "logs").glob("*.log"))
            self.assertEqual(len(logs), 1)
            content = logs[0].read_text()
            self.assertNotIn("PRIVATE_CANARY", content)
            self.assertNotIn(str(root), content)
            self.assertIn("decoder=cuda", content)
            self.assertIn("exit=1", content)
            self.assertIn("decoder_error", content)

    def test_trace_cap_and_limit_reason(self):
        result = ScanResult()
        for _ in range(1027):
            record_trace(result, worker_trace("decode", ProcessResult(1, limited=True)))
        self.assertEqual(len(result.diagnostics), 1024)
        self.assertEqual(result.diagnostics_omitted, 3)
        self.assertEqual(result.diagnostics[0]["limit_reason"], "unknown")

    def test_thread_advisory_is_retained_without_hiding_media_warnings(self):
        advisory = b"[ffv1 @ 000001ab] [warning] Application has requested 30 threads. Using a thread count greater than 16 is not recommended.\r\n"
        self.assertEqual(classify_log(advisory), [])
        detail = worker_trace("decode", ProcessResult(0, stderr=advisory + b"[warning] invalid NAL"))
        self.assertEqual({m["category"] for m in detail["messages"]}, {"thread_advisory", "decoder_error"})
        self.assertEqual(classify_log(advisory + b"[warning] invalid NAL")[0].category, "decoder_error")
        self.assertEqual(classify_log(advisory.replace(b"[warning]", b"[error]"))[0].category, "unclassified_error")

    def test_cli_flags_forward_and_defaults_prefer_hardware(self):
        self.assertTrue(Preferences().hardware_decoding)
        self.assertTrue(Preferences().hardware_encoding)
        with tempfile.TemporaryDirectory(prefix="videomate-flags-generated-") as directory:
            with patch("videomate.cli.scan_local", return_value=0) as scan, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["scan", "--workspace", directory, "--input", "INVENTED", "--diagnostic-logs",
                                       "--cpu-threads", "6", "--max-runners", "2", "--no-hardware-decoding"]), 0)
            self.assertTrue(scan.call_args.kwargs["sensitive"])
            self.assertTrue(scan.call_args.kwargs["diagnostic_logs"])
            self.assertFalse(scan.call_args.kwargs["hardware_decoding"])
            self.assertEqual(scan.call_args.kwargs["cpu_threads"], 6)
            self.assertEqual(scan.call_args.kwargs["max_runners"], 2)
