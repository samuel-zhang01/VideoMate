"""Offline setup policy and optional native GUI checks; never user media."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomate.dependencies import default_root, platform_tag
from videomate.errors import VideoMateError
from videomate.setup_local import check_backend, ensure_workspace, prepare_application


class DesktopSetupTests(unittest.TestCase):
    def test_prepare_recreates_removed_settings_and_saves_explicit_changes(self):
        from dataclasses import replace
        from videomate.preferences import Preferences, load_preferences
        with tempfile.TemporaryDirectory(prefix="videomate-prepare-settings-generated-") as temporary:
            root = Path(temporary).resolve()
            config = root / "config" / "settings.json"
            initial = Preferences(workspace=str(root / "workspace"))
            prepare_application(initial, config)
            config.unlink()  # Exact file created above, not discovered operator state.
            (root / "workspace" / "jobs").rmdir()
            changed = replace(initial, recovered_dir=str(root / "new-output"), diagnostic_logs=True)
            prepare_application(changed, config, save_current=True)
            self.assertEqual(load_preferences(config), changed)
            self.assertTrue((root / "workspace" / "jobs").is_dir())
            second = replace(changed, logs_dir=str(root / "new-logs"))
            prepare_application(second, config)  # Automatic startup leaves saved choices alone.
            self.assertEqual(load_preferences(config), changed)
            prepare_application(second, config, save_current=True)
            self.assertEqual(load_preferences(config), second)
            for bad in (root / "config", Path("relative.json")):
                with self.assertRaises(VideoMateError) as error:
                    prepare_application(second, bad, save_current=True)
                self.assertEqual(error.exception.code, "settings_location")
            config.write_bytes(b"Generated unrelated content")
            with self.assertRaises(VideoMateError):
                prepare_application(second, config, save_current=True)
            self.assertEqual(config.read_bytes(), b"Generated unrelated content")
            with patch("videomate.setup_local.ensure_workspace", side_effect=PermissionError("PRIVATE_CANARY")):
                with self.assertRaises(VideoMateError) as error:
                    prepare_application(second, root / "missing.json")
                self.assertEqual(error.exception.code, "workspace_rejected")
                self.assertNotIn("PRIVATE_CANARY", str(error.exception))
            with patch("videomate.preferences.save_preferences"):
                with self.assertRaises(VideoMateError) as error:
                    prepare_application(second, root / "missing.json")
                self.assertEqual(error.exception.code, "settings_invalid")

    def test_automatic_workspace_is_idempotent_and_rejects_sync(self):
        with tempfile.TemporaryDirectory(prefix="videomate-setup-test-") as temporary:
            root = Path(temporary).resolve()
            path = root / "private" / "workspace"
            self.assertEqual(ensure_workspace(path), path)
            self.assertEqual(ensure_workspace(path), path)
            with self.assertRaises(VideoMateError):
                ensure_workspace(root / "OneDrive" / "workspace")
            self.assertFalse((root / "OneDrive").exists())

    def test_partial_workspace_and_custom_storage_are_prepared_without_overwrite(self):
        from videomate.preferences import Preferences, load_preferences
        with tempfile.TemporaryDirectory(prefix="videomate-partial-setup-generated-") as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            (workspace / "jobs").mkdir(parents=True)
            marker = workspace / "jobs" / "invented-state.txt"
            marker.write_bytes(b"Generated existing marker")
            preferences = Preferences(workspace=str(workspace), recovered_dir=str(root / "output"),
                                      diagnostics_dir=str(root / "exports"), logs_dir=str(root / "logs"))
            config = root / "config" / "settings.json"
            self.assertEqual(prepare_application(preferences, config), workspace)
            before = config.read_bytes()
            for name in ("state", "jobs", "recovered", "export-review", "logs"):
                self.assertTrue((workspace / name).is_dir())
            for name in ("output", "exports", "logs"):
                self.assertTrue((root / name).is_dir())
            prepare_application(preferences, config)
            self.assertEqual(config.read_bytes(), before)
            self.assertEqual(load_preferences(config), preferences)
            self.assertEqual(marker.read_bytes(), b"Generated existing marker")
            collision = root / "conflict"
            collision.mkdir()
            (collision / "state").write_bytes(b"Generated unrelated file")
            with self.assertRaises(VideoMateError):
                ensure_workspace(collision)
            self.assertFalse((collision / "jobs").exists())
            self.assertEqual((collision / "state").read_bytes(), b"Generated unrelated file")
            software = root / "other-source"
            software.mkdir()
            (software / "pyproject.toml").write_text("# Generated source marker")
            with self.assertRaises(VideoMateError):
                ensure_workspace(software)
            self.assertFalse((software / "jobs").exists())

    def test_missing_bundle_never_launches_a_worker(self):
        with tempfile.TemporaryDirectory(prefix="videomate-no-tools-") as temporary:
            with patch("videomate.setup_local.Runner.run", side_effect=AssertionError("Must not launch")):
                with self.assertRaises(VideoMateError):
                    check_backend(Path(temporary).resolve())

    def test_platform_resolution_and_frozen_resource_path(self):
        with patch("platform.system", return_value="Darwin"), patch("platform.machine", return_value="arm64"):
            self.assertEqual(platform_tag(), "macos-arm64")
        with patch("platform.system", return_value="Windows"), patch("sysconfig.get_platform", return_value="win-amd64"):
            self.assertEqual(platform_tag(), "windows-x86_64")
        # Windows ARM can host an emulated x64 Python: bundle for the ABI in use.
        with patch("platform.system", return_value="Windows"), patch("platform.machine", return_value="ARM64"):
            with patch("sysconfig.get_platform", return_value="win-amd64"):
                self.assertEqual(platform_tag(), "windows-x86_64")
            with patch("sysconfig.get_platform", return_value="win-arm64"):
                self.assertEqual(platform_tag(), "windows-arm64")
        with tempfile.TemporaryDirectory(prefix="videomate-frozen-") as temporary:
            root = Path(temporary).resolve()
            with patch("sys.frozen", True, create=True), patch("sys._MEIPASS", str(root), create=True):
                self.assertEqual(default_root(), root / "dependencies" / "ffmpeg")

    @unittest.skipUnless(os.environ.get("VIDEOMATE_TEST_GUI") == "1", "Explicit native GUI testing not enabled")
    def test_native_gui_generated_media_workflow(self):
        from videomate.selftest import run_self_test
        report = run_self_test()
        self.assertEqual(report["status"], "passed")
        self.assertTrue(all(report["checks"].values()))
