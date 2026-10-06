"""Large migration and progress checks use only fresh, invented fixture files."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from videomate.diagnostics import create_export, create_export_batches, environment
from videomate.errors import VideoMateError
from videomate.local_scan import report_local
from videomate.migration import inventory, migrate_local, path_key, repair_stem, validate_layout
from videomate.models import Depth, ScanResult
from videomate.private_state import LIVE_REPORTS, report_pages
from videomate.progress import BatchProgress, describe
from videomate.schema import validate_export
from videomate.setup_local import ensure_workspace


class MigrationScaleTests(unittest.TestCase):
    def test_more_than_1000_files_complete_log_and_export_without_mappings(self):
        with tempfile.TemporaryDirectory(prefix="videomate-large-generated-") as temporary:
            root = Path(temporary).resolve()
            source = root / "INVENTED_PRIVATE_CANARY"
            source.mkdir()
            for number in range(1005):
                (source / f"invented-{number:04d}.txt").write_bytes(b"Generated fixture only")
            workspace = ensure_workspace(root / "workspace")
            executable = root / "generated-never-run.exe"
            executable.write_bytes(b"Test stub; must never be launched")
            bundle = SimpleNamespace(ffmpeg=executable, ffprobe=executable, version="9.0.2")
            messages, progress = [], []
            def emit(message):
                messages.append(message)
                if message.startswith("Job: "):
                    self.addCleanup(lambda identifier=message[5:]: LIVE_REPORTS.pop(identifier, None))
            with patch("videomate.migration.load_bundle", return_value=bundle), \
                    patch("videomate.runner.Runner.run", side_effect=AssertionError("No media workers expected")):
                self.assertEqual(migrate_local([str(source)], workspace, local_names=True,
                    diagnostic_logs=True, export_on_completion=True, emit=emit, progress=progress.append), 0)
            identifier = next(message[5:] for message in messages if message.startswith("Job: "))
            package = workspace / "recovered" / ("migration-" + identifier)
            status = json.loads(package.with_name(package.name + ".status.json").read_bytes())
            self.assertEqual((status["state"], status["completed_files"], status["output_files"], status["omitted_from_output"]),
                             ("complete", 1005, 1005, 0))
            for number in range(1005):
                name = f"invented-{number:04d}.txt"
                self.assertEqual((package / name).read_bytes(), b"Generated fixture only")
                self.assertEqual((source / name).read_bytes(), b"Generated fixture only")
            pages = report_pages(LIVE_REPORTS[identifier][2])
            self.assertEqual(len(pages), 2)
            self.assertEqual(sum(len(json.loads(page)["files"]) for page in pages), 1005)
            exports = list((workspace / "export-review").glob("*.json"))
            self.assertEqual(len(exports), 0)
            self.assertEqual(len(list((workspace / "export-review").glob("*.log"))), 1)
            summaries = []
            report_local(identifier, workspace, export=True, technical_json=True, emit=summaries.append)
            self.assertIn("Processed 1,005/1,005", "\n".join(summaries))
            self.assertIn("copied_other: 1,005", next((workspace / "export-review").glob("*.log")).read_text())
            exports = list((workspace / "export-review").glob("*.json"))
            self.assertEqual(len(exports), 2)
            scopes = set()
            for export in exports:
                encoded = export.read_text()
                self.assertNotIn("INVENTED_PRIVATE_CANARY", encoded)
                self.assertNotIn("invented-", encoded)
                document = json.loads(encoded)
                validate_export(document)
                self.assertEqual(document["files_omitted"], 0)
                scopes.add(document["export_scope"])
            self.assertEqual(len(scopes), 2)
            logs = list((workspace / "logs").glob("*.log"))
            self.assertIn("completed=1005", logs[0].read_text())
            self.assertNotIn("INVENTED_PRIVATE_CANARY", logs[0].read_text())
            self.assertEqual(list((workspace / "state").iterdir()), [])
            self.assertEqual(list((workspace / "jobs").iterdir()), [])
            self.assertEqual(progress[0].phase, "discovering")
            self.assertEqual((progress[-1].phase, progress[-1].completed, progress[-1].total), ("finished", 1005, 1005))
            self.assertEqual(sorted(p.completed for p in progress), [p.completed for p in progress])
            self.assertTrue(any(p.remaining is not None for p in progress))

    def test_folder_roles_fail_before_stat_without_disclosing_paths(self):
        with tempfile.TemporaryDirectory(prefix="videomate-layout-generated-") as temporary:
            root = Path(temporary).resolve()
            workspace, output, code = (root / name for name in ("workspace", "output", "code"))
            for source, expected in ((workspace, "migration_workspace_overlap"),
                                     (workspace / "invented", "migration_workspace_overlap"),
                                     (root, "migration_workspace_overlap"), (output, "migration_output_overlap"),
                                     (code, "migration_software_overlap"), (root / "logs", "migration_storage_overlap")):
                with self.subTest(expected=expected), patch.object(Path, "stat", side_effect=AssertionError("No stat permitted")):
                    with self.assertRaises(VideoMateError) as error:
                        validate_layout([str(source)], workspace, output, code, excluded=[root / "logs"])
                    self.assertEqual(error.exception.code, expected)
                    self.assertNotIn(str(root), str(error.exception))

    def test_inventory_errors_distinguish_empty_missing_access_and_names(self):
        with tempfile.TemporaryDirectory(prefix="videomate-inventory-generated-") as temporary:
            root = Path(temporary).resolve()
            source = root / "PRIVATE_CANARY"
            args = ([str(source)], root / "workspace", root / "output", root / "code")
            with self.assertRaises(VideoMateError) as error:
                inventory(*args)
            self.assertEqual(error.exception.code, "migration_not_folder")
            source.mkdir()
            with self.assertRaises(VideoMateError) as error:
                inventory(*args)
            self.assertEqual(error.exception.code, "migration_empty")
            with patch("videomate.migration.os.walk", side_effect=PermissionError("PRIVATE_CANARY")):
                with self.assertRaises(VideoMateError) as error:
                    inventory(*args)
                self.assertEqual(error.exception.code, "migration_access")
                self.assertNotIn("PRIVATE_CANARY", str(error.exception))
            (source / "invented.txt").write_bytes(b"Generated")
            with patch("videomate.migration.os.walk", return_value=[(source, [], ["invented.txt", "invented.txt"])]):
                with self.assertRaises(VideoMateError) as error:
                    inventory(*args)
                self.assertEqual(error.exception.code, "migration_name_conflict")
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(KeyboardInterrupt):
                inventory(*args, cancel=cancel)

    def test_repaired_name_suffix_can_exceed_1000(self):
        relative = Path("generated.avi")
        reserved = {path_key(Path("generated.mkv"))}
        reserved.update(path_key(Path(f"generated.repaired-{i}.mkv")) for i in range(1, 1005))
        self.assertEqual(repair_stem(relative, reserved), "generated.repaired-1005")

    def test_dense_export_batches_split_and_validation_still_fails_closed(self):
        items = [ScanResult(depth=Depth.QUICK, integrity="quick_check_only") for _ in range(5)]
        def bounded(batch, *args, **kwargs):
            if len(batch) > 2:
                raise VideoMateError("export_too_large")
            return create_export(batch, *args, **kwargs)
        with patch("videomate.diagnostics.create_export", side_effect=bounded):
            pages = list(create_export_batches(iter(items), uuid4(), bytes(32), environment("9.0.2", "9.0.2")))
        self.assertEqual(sum(len(json.loads(page)["files"]) for page in pages), 5)
        self.assertEqual(len(pages), 3)
        items[0].integrity = "PRIVATE_CANARY"
        with self.assertRaises(VideoMateError) as error:
            list(create_export_batches(items, uuid4(), bytes(32), environment("9.0.2", "9.0.2")))
        self.assertEqual(error.exception.code, "invalid_export")

    def test_progress_estimates_elapsed_stalls_and_terminal_states(self):
        events = []
        with patch("videomate.progress.time.monotonic", return_value=10) as clock:
            tracker = BatchProgress(events.append)
            tracker.update("discovering", discovered=1005, force=True)
            self.assertIn("1,005 found", describe(events[-1], now=10))
            tracker.plan(5)
            tracker.begin()
            self.assertIsNone(events[-1].remaining)
            clock.return_value = 30
            tracker.update("processing", completed=1)
            self.assertEqual(events[-1].remaining, 80)
            self.assertIn("About 1m 15s remaining", describe(events[-1], now=35))
            self.assertIn("re-estimating", describe(events[-1], now=120))
            self.assertNotIn("remaining", describe(events[-1], now=120, running=False))
            tracker.update("checking", completed=5, force=True)
            self.assertIn("Final source checks", describe(events[-1], now=30))
            tracker.update("finished", force=True)
            self.assertNotIn("estimating", describe(events[-1], now=30))

    def test_progress_tail_uses_recent_rate_after_fast_copies(self):
        events = []
        with patch("videomate.progress.time.monotonic", return_value=0) as clock:
            tracker = BatchProgress(events.append)
            tracker.plan(100)
            tracker.begin()
            clock.return_value = 30
            tracker.update("processing", completed=80)
            self.assertEqual(events[-1].remaining, 7.5)
            clock.return_value = 61
            tracker.update("processing", completed=81)
            self.assertEqual(events[-1].remaining, 31 * 19)
            clock.return_value = 125
            tracker.update("processing", force=True)
            self.assertIsNone(events[-1].remaining)
