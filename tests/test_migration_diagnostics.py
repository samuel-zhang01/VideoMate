"""Storage loss is injected against generated markers, never real drives."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from videomate.diagnostic_report import Report
from videomate.diagnostics import create_export, create_export_batches, environment
from videomate.errors import VideoMateError
from videomate.migration import migrate_local, migration_summary, process_file, write_status
from videomate.models import Depth, ScanResult
from videomate.private_state import LIVE_REPORTS, MemoryJob, finalize_session, report_pages
from videomate.schema import load_json, validate_export
from videomate.setup_local import ensure_workspace
from videomate.support import support_summary


class MigrationDiagnosticsTests(unittest.TestCase):
    def test_failure_before_first_result_still_has_a_shareable_job_report(self):
        counts = dict.fromkeys(("copied_healthy", "copied_other", "repaired", "salvaged_partial", "retained_for_review", "excluded_unresolved", "copied_unresolved", "failed"), 0)
        summary = migration_summary("interrupted", 12, counts, "output_access_denied", "prepare_output")
        pages = list(create_export_batches([], uuid4(), bytes(32), environment("9.0.2", "9.0.2"), migration_summary=summary))
        self.assertEqual(len(pages), 1)
        doc = load_json(pages[0]);validate_export(doc)
        self.assertEqual(doc["files"], [])
        self.assertEqual(doc["migration_summary"]["unprocessed_files"], 12)
        doc.pop("migration_summary")
        with self.assertRaises(VideoMateError):validate_export(doc)

    def test_disconnected_output_error_survives_status_log_and_cleanup_failures(self):
        with tempfile.TemporaryDirectory(prefix="videomate-disconnect-generated-") as temporary:
            root = Path(temporary).resolve()
            source = root / "PRIVATE_CANARY_SOURCE"
            source.mkdir()
            for i in range(3):
                (source / f"PRIVATE_CANARY_{i}.txt").write_bytes(b"Generated disconnect test marker")
            workspace = ensure_workspace(root / "workspace")
            messages = []
            (root / "never-run.exe").write_bytes(b"Generated backend stub; never executed")
            bundle = SimpleNamespace(ffmpeg=root / "never-run.exe", ffprobe=root / "never-run.exe", version="9.0.2")
            def process(backend, item, **kwargs):
                if item[0] == 2:
                    raise VideoMateError("output_write_failed")
                return process_file(backend, item, **kwargs)
            def status(package, phase, *args):
                if phase == "interrupted":
                    raise OSError("PRIVATE_CANARY disconnected storage")
                return write_status(package, phase, *args)
            with patch("videomate.migration.load_bundle", return_value=bundle), \
                    patch("videomate.migration.process_file", side_effect=process), \
                    patch("videomate.migration.write_status", side_effect=status), \
                    patch("videomate.event_log.EventLog.close", side_effect=OSError("PRIVATE_CANARY log")), \
                    patch.object(MemoryJob, "cleanup_owned", side_effect=VideoMateError("cleanup_incomplete")):
                with self.assertRaises(VideoMateError) as caught:
                    migrate_local([str(source)], workspace, sensitive=False, max_runners=1, emit=messages.append)
            self.assertEqual(caught.exception.code, "output_write_failed")
            identifier = next(m[5:] for m in messages if m.startswith("Job: "))
            self.addCleanup(lambda: LIVE_REPORTS.pop(identifier, None))
            pages = report_pages(LIVE_REPORTS[identifier][2])
            document = load_json(pages[0]);validate_export(document)
            summary = document["migration_summary"]
            self.assertEqual((summary["planned_files"], summary["processed_files"], summary["unprocessed_files"]), (3, 1, 2))
            self.assertEqual((summary["stop_reason"], summary["stop_stage"]), ("output_write_failed", "process_files"))
            self.assertEqual({i["stage"] for i in summary["pipeline_issues"]}, {"write_status", "close_event_log", "cleanup"})
            self.assertIn("1/3 processed", "\n".join(messages))
            self.assertNotIn("PRIVATE_CANARY", "\n".join(messages))
            text_log = next((workspace / "export-review").glob("*.log")).read_text(encoding="utf-8")
            self.assertIn("Migration interrupted", text_log)
            self.assertIn("2 not processed", text_log)
            self.assertIn("Secondary failure", text_log)
            self.assertNotIn("PRIVATE_CANARY", text_log)
            self.assertNotIn(str(root), text_log)
            package = workspace / "recovered" / ("migration-" + identifier)
            self.assertEqual(len(list(package.glob("*.txt"))), 1)
            self.assertEqual(len(list(source.glob("*.txt"))), 3)

    def test_secondary_snapshot_failure_does_not_replace_primary(self):
        with tempfile.TemporaryDirectory(prefix="videomate-finalize-generated-") as temporary:
            root = Path(temporary).resolve();workspace = ensure_workspace(root / "workspace")
            job = MemoryJob.create(workspace, [], {})
            messages = []
            original = VideoMateError("output_write_failed")
            with patch("videomate.private_state.snapshot", side_effect=OSError("PRIVATE_CANARY")):
                # Caller owns the pending exception; finalization must not mask it.
                with self.assertRaises(VideoMateError) as caught:
                    try:
                        raise original
                    finally:
                        finalize_session(job, "9.0.2", messages.append, primary_error=original)
                self.assertIs(caught.exception, original)

    def test_whole_job_summary_is_closed_consistent_and_present_in_support_summary(self):
        result = ScanResult(depth=Depth.QUICK, integrity="quick_check_only")
        result.technical["migration"] = {"input_kind": "other", "action": "copied_other", "copy_check": "passed", "timestamps": "preserved", "reason": "none"}
        counts = dict.fromkeys(("copied_healthy", "copied_other", "repaired", "salvaged_partial", "retained_for_review", "excluded_unresolved", "copied_unresolved", "failed"), 0)
        counts["copied_other"] = 1
        summary = migration_summary("interrupted", 50000, counts, "io_error", "write_status")
        summary["hardware"] = {"decode_requested": True, "encode_requested": True,
                               "integrity_decoder": "software", "decode_selection": "qualified",
                               "peak_active_routes": 0, "peak_gpu_jobs": 0,
                               "routes": [{"slot": 1, "decoder": "cuda", "encoder": "libx265", "peak_jobs": 0}]}
        document = load_json(create_export([result], uuid4(), bytes(32), environment("9.0.2", "9.0.2"), synthetic=True, migration_summary=summary))
        self.assertEqual(support_summary(document)["migration_summary"]["unprocessed_files"], 49999)
        report = Report();self.addCleanup(report.close);report.add(json.dumps(document).encode(), "diagnostics-" + "0" * 24 + ".json")
        self.assertIn("49,999 not processed", report.text())
        self.assertIn("encode requested=True", report.text())
        self.assertIn("no hardware encoder route qualified", report.text())
        with self.assertRaises(VideoMateError):
            report.add(json.dumps(document).encode(), "javascript:PRIVATE_CANARY")
        document["migration_summary"]["processed_files"] = 2
        with self.assertRaises(VideoMateError):validate_export(document)
        document["migration_summary"]["processed_files"] = 1
        document["migration_summary"]["filename"] = "PRIVATE_CANARY"
        with self.assertRaises(VideoMateError):validate_export(document)
        del document["migration_summary"]["filename"]
        document["files"][0]["recovery_state"] = "failed"
        document["files"][0]["attempts"] = [
            {"strategy": "reencode", "profile": "compatible_sdr", "outcome": "failed",
             "reason": "backend_error", "encoder": "hevc_nvenc", "decoder": "software"}
            for _ in range(6)]
        validate_export(document)  # More than five qualified-route attempts remain exportable.
