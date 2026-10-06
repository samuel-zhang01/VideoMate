"""Privacy/configuration tests use only owned temporary state and invented results."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomate.cli import main, parser
from videomate.errors import VideoMateError
from videomate.event_log import EventLog
from videomate.jobs import Job
from videomate.local_scan import export_job, job_inputs
from videomate.models import ScanResult
from videomate.preferences import MAX_PREFERENCES_BYTES, Preferences, load_preferences, save_preferences, storage_directory
from videomate.policy import create_workspace
from videomate.discovery import discover


class PreferencesAndSensitivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videomate-settings-generated-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = create_workspace(self.root / "workspace", self.root / "code")

    def job(self, **settings):
        source = self.root / "SYNTHETIC_PRIVATE_INPUT.mp4"
        source.write_bytes(b"Invented fixture; not decoded")
        job = Job.create(self.workspace, [source], {"scope": "local_files", "sensitive": True, **settings})
        self.addCleanup(job.close)
        return job

    def test_settings_roundtrip_and_no_input_history(self):
        target = self.root / "preferences/settings.json"
        prefs = Preferences(workspace=str(self.workspace), diagnostics_dir=str(self.root / "diagnostics"),
                            timeout=81, max_output_mib=256, sensitive=False, write_logs=True)
        save_preferences(target, prefs)
        self.assertEqual(load_preferences(target), prefs)
        save_preferences(target, Preferences(workspace=str(self.workspace)))
        self.assertTrue(load_preferences(target).sensitive)
        self.assertNotIn("inputs", json.loads(target.read_text()))

    def test_full_profile_configuration_roundtrips_beyond_old_byte_limit(self):
        from videomate.profiles import extract
        locations = {name: str(self.root / ("generated/" * 390)) for name in
                     ("workspace", "recovered_dir", "diagnostics_dir", "logs_dir", "dependencies")}
        prefs = Preferences(**locations, profiles={f"Generated profile {i}": extract(Preferences()) for i in range(12)})
        target = self.root / "large-generated-settings.json"
        save_preferences(target, prefs)
        self.assertGreater(target.stat().st_size, 32768)
        self.assertEqual(load_preferences(target), prefs)

    def test_oversized_escaped_settings_preserve_previous_file_and_create_nothing(self):
        from videomate.profiles import extract
        prefix = self.root.anchor
        locations = {name: prefix + "\U0001f600" * (4096 - len(prefix)) for name in
                     ("workspace", "recovered_dir", "diagnostics_dir", "logs_dir", "dependencies")}
        prefs = Preferences(**locations, profiles={f"{i:02d}" + "\U0001f600" * 38: extract(Preferences()) for i in range(12)})
        prefs.validate()
        target = self.root / "existing-generated-settings.json"
        save_preferences(target, Preferences())
        original = target.read_bytes()
        for path in (target, self.root / "must-not-exist" / "settings.json"):
            with self.assertRaises(VideoMateError) as failure:
                save_preferences(path, prefs)
            self.assertEqual(failure.exception.code, "settings_invalid")
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse((self.root / "must-not-exist").exists())
        self.assertEqual(list(self.root.glob(".videomate-settings-*.tmp")), [])

    def test_reader_keeps_byte_bound_and_legacy_motion_default(self):
        target = self.root / "generated-settings.json"
        target.write_text('{"schema_version":1}', encoding="utf-8")
        self.assertFalse(load_preferences(target).reduce_motion)
        target.write_bytes(b" " * (MAX_PREFERENCES_BYTES + 1))
        with self.assertRaises(VideoMateError) as failure:
            load_preferences(target)
        self.assertEqual(failure.exception.code, "settings_invalid")

    def test_reject_invalid_types_limits_unknown_fields_and_preserve_unrelated_file(self):
        for prefs in (Preferences(sensitive="yes"), Preferences(timeout=0), Preferences(max_output_mib=True),
                      Preferences(workspace="relative"), Preferences(strategy="PRIVATE_CANARY")):
            with self.assertRaises(VideoMateError):
                prefs.validate()
        target = self.root / "existing.json"
        original = '{"schema_version":1,"private_unknown":"CANARY"}'
        target.write_text(original)
        with self.assertRaises(VideoMateError):
            save_preferences(target, Preferences())
        self.assertEqual(target.read_text(), original)

    def test_storage_and_settings_reject_cloud_sync(self):
        with self.assertRaises(VideoMateError):
            storage_directory(str(self.root / "OneDrive/logs"), self.workspace / "logs")
        with self.assertRaises(VideoMateError):
            save_preferences(self.root / "OneDrive/settings.json", Preferences())
        self.assertFalse((self.root / "OneDrive").exists())

    def test_storage_rejects_other_repository_roots_and_descendants(self):
        for number, (marker_name, directory_marker) in enumerate(((".git", True), (".git", False), ("pyproject.toml", False))):
            repository = self.root / f"generated-project-{number}"
            repository.mkdir()
            marker = repository / marker_name
            if directory_marker:
                marker.mkdir()
            else:
                marker.write_text("Generated project marker; not an actual repository.", encoding="utf-8")
            for destination in (repository, repository / "generated-output"):
                with self.subTest(marker=number, root=destination == repository):
                    with self.assertRaises(VideoMateError) as failure:
                        storage_directory(str(destination), self.workspace / "logs")
                    self.assertEqual(failure.exception.code, "workspace_rejected")
            self.assertEqual(set(repository.iterdir()), {marker})

    def test_sensitive_logging_never_touches_configured_log_location(self):
        job = self.job(write_logs=True, logs_dir=str(self.root / "logs"))
        with patch("videomate.event_log.storage_directory", side_effect=AssertionError("No disk logging for sensitive jobs")):
            log = EventLog(job, job.settings())
            log.write("started")
            log.close()
        self.assertFalse((self.root / "logs").exists())

    def test_event_logs_only_allow_codes_and_counters(self):
        job = self.job(sensitive=False, write_logs=True, logs_dir=str(self.root / "events"))
        log = EventLog(job, job.settings())
        try:
            log.write("started")
            log.write("input_finished", 1)
            with self.assertRaises(ValueError):
                log.write("SYNTHETIC_PRIVATE_INPUT")
        finally:
            log.close()
        files = list((self.root / "events").glob("*.log"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text()
        self.assertNotIn("PRIVATE", text)
        self.assertNotIn(str(self.root), text)
        self.assertIn("completed=1", text)

    def test_sensitive_explicit_export_uses_selected_directory_without_mapping(self):
        job = self.job(diagnostics_dir=str(self.root / "chosen-diagnostics"), retain_mappings=True)
        job.save(1, "done", ScanResult(integrity="unreadable"))
        name = export_job(job, "0.0.0")
        encoded = (self.root / "chosen-diagnostics" / name).read_text()
        self.assertNotIn("PRIVATE", encoded)
        self.assertNotIn(str(self.root), encoded)
        self.assertFalse(list((self.workspace / "export-review").iterdir()))
        self.assertEqual(len(list((self.workspace / "state").glob("mapping-*.json"))), 0)

    def test_non_sensitive_export_mapping_requires_explicit_opt_in(self):
        job = self.job(sensitive=False)
        job.save(1, "done", ScanResult(integrity="unreadable"))
        export_job(job, "0.0.0")
        self.assertEqual(list((self.workspace / "state").glob("mapping-*.json")), [])
        settings = job.settings()
        settings["retain_mappings"] = True
        job.update_settings(settings)
        export_job(job, "0.0.0")
        self.assertEqual(len(list((self.workspace / "state").glob("mapping-*.json"))), 1)

    def test_sensitive_saved_job_cannot_be_reused_as_non_sensitive(self):
        job = self.job()
        with self.assertRaises(VideoMateError) as error:
            job_inputs(job.id, self.workspace, sensitive=False)
        self.assertEqual(error.exception.code, "privacy_downgrade")
        self.assertEqual(len(job_inputs(job.id, self.workspace)), 1)

    def test_new_jobs_require_valid_sensitive_boolean_legacy_jobs_still_load(self):
        for value in (None, "false", 0):
            job = self.job(sensitive=value)
            with self.assertRaises(VideoMateError):
                job.settings()

    def test_cli_sensitive_defaults_and_config_overrides(self):
        settings = self.root / "settings.json"
        save_preferences(settings, Preferences(workspace=str(self.workspace), sensitive=False, timeout=81))
        out = io.StringIO()
        with patch("videomate.cli.scan_local", return_value=0) as scan, contextlib.redirect_stdout(out):
            self.assertEqual(main(["scan", "--input", "SYNTHETIC_MARKER", "--config", str(settings), "--sensitive", "yes", "--timeout", "29"]), 0)
            self.assertTrue(scan.call_args.kwargs["sensitive"])
            self.assertEqual(scan.call_args.kwargs["timeout"], 29)
            self.assertEqual(main(["scan", "--input", "SYNTHETIC_MARKER", "--workspace", str(self.workspace)]), 0)
            self.assertTrue(scan.call_args.kwargs["sensitive"])
            self.assertEqual(main(["scan", "--input", "SYNTHETIC_MARKER", "--workspace", str(self.workspace), "--test-files"]), 0)
            self.assertFalse(scan.call_args.kwargs["sensitive"])
        self.assertNotIn("SYNTHETIC_MARKER", out.getvalue())

    def test_discovery_skips_configured_output_directories(self):
        source = self.root / "source.mp4"
        source.write_bytes(b"Generated marker")
        output = self.root / "custom-recovered"
        output.mkdir()
        (output / "generated-result.mp4").write_bytes(b"Generated marker")
        found = discover([str(self.root)], self.workspace, self.root / "code", True, exclusions=[output])
        self.assertEqual(found, [source])
