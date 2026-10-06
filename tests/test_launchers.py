"""Launcher tests use private temporary source copies and invented software only."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vm_bootstrap_tests", ROOT / "tools/bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videomate-launcher-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tools").mkdir()
        shutil.copyfile(ROOT / "tools/install_python.py", self.root / "tools/install_python.py")
        self.addCleanup(patch.stopall)
        patch.object(bootstrap, "ROOT", self.root).start()
        patch("videomate.preferences.default_config_path", return_value=self.root / "settings.json").start()

    def call(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = bootstrap.main(args)
        return code, output.getvalue()

    def test_automatic_setup_default_and_explicit_offline(self):
        self.assertFalse(bootstrap.arguments([]).offline)
        self.assertTrue(bootstrap.arguments(["--offline"]).offline)
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit):
            bootstrap.arguments(["--offline", "--setup-online", "SYNTHETIC_PRIVATE_CANARY"])
        self.assertNotIn("SYNTHETIC_PRIVATE_CANARY", output.getvalue())

    def test_missing_tk_keeps_headless_check_usable_and_gui_actionable(self):
        ready = {"platform":"linux-x86_64", "version":"9.0.2"}
        with patch.object(bootstrap, "prepare", return_value=ready), patch.object(bootstrap, "tkinter_available", return_value=False):
            code, output = self.call(["--check"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["tkinter"], "missing")
            code, output = self.call(["--offline"])
            self.assertEqual(code, 2)
            self.assertIn("--runtime-archive", output)

    def test_runtime_prompt_accepts_yes_and_defaults_to_decline(self):
        (self.root / "dependencies").mkdir()
        (self.root / "dependencies/python-sources.json").write_text(json.dumps({"platforms":{"linux-x86_64":{"filename":"invented.tar.gz"}}}))
        for answer, allowed in (("", False), ("no", False), ("yes", True), (" Y ", True)):
            with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=answer), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bootstrap.approve_runtime_download(bootstrap.arguments([]), "linux-x86_64"), allowed)
        with patch("sys.stdin.isatty", return_value=False), patch("builtins.input", side_effect=AssertionError("Cannot prompt")), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(bootstrap.approve_runtime_download(bootstrap.arguments([]), "linux-x86_64"))
            self.assertTrue(bootstrap.approve_runtime_download(bootstrap.arguments(["--yes"]), "linux-x86_64"))
            self.assertTrue(bootstrap.approve_runtime_download(bootstrap.arguments(["--offline"]), "linux-x86_64"))

    def test_cached_runtime_does_not_prompt(self):
        (self.root / "dependencies/cache").mkdir(parents=True)
        (self.root / "dependencies/python-sources.json").write_text(json.dumps({"platforms":{"linux-x86_64":{"filename":"invented.tar.gz"}}}))
        (self.root / "dependencies/cache/invented.tar.gz").write_bytes(b"fake software; the installer still must verify it")
        with patch("builtins.input", side_effect=AssertionError("No prompt for offline cache")):
            self.assertTrue(bootstrap.approve_runtime_download(bootstrap.arguments([]), "linux-x86_64"))

    def test_explicit_interpreter_does_not_switch_to_an_unselected_runtime(self):
        runtime = self.root / "unselected-runtime"
        runtime.mkdir()
        installer = SimpleNamespace(runtime_path=lambda _: runtime, install=Mock(), verify=Mock())
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: None))
        with patch.dict(os.environ, {"VIDEOMATE_PYTHON": sys.executable}), \
                patch.object(bootstrap.importlib.util, "spec_from_file_location", return_value=spec), \
                patch.object(bootstrap.importlib.util, "module_from_spec", return_value=installer):
            with self.assertRaises(SystemExit) as exited:
                self.call(["--cli", "--version"])
            self.assertEqual(exited.exception.code, 0)
            installer.install.assert_not_called()
            installer.verify.assert_not_called()

    def test_unexpected_setup_failure_does_not_echo_private_values(self):
        with patch.object(bootstrap, "prepare", side_effect=RuntimeError("SYNTHETIC_PRIVATE_CANARY")):
            code, output = self.call(["--check"])
        self.assertEqual(code, 2)
        self.assertNotIn("SYNTHETIC_PRIVATE_CANARY", output)

    def test_cancellation_returns_130(self):
        with patch.object(bootstrap, "prepare", side_effect=KeyboardInterrupt()):
            self.assertEqual(self.call(["--check"])[0], 130)

    def test_help_and_version_need_no_ffmpeg(self):
        with patch.object(bootstrap, "prepare", side_effect=AssertionError("No setup needed")):
            with self.assertRaises(SystemExit) as exited:
                self.call(["--cli", "--version"])
            self.assertEqual(exited.exception.code, 0)

    def test_metadata_and_doctor_commands_skip_all_provisioning(self):
        commands = (
            ["support-summary", str(self.root / "synthetic-export.json")],
            ["report", "--job", "generated-id", "--workspace", str(self.root / "workspace")],
            ["export-diagnostics", "--job", "generated-id", "--workspace", str(self.root / "workspace")],
            ["cleanup", "--input", str(self.root / "generated-input"), "--action", "delete", "--confirm", "DELETE 1"],
            ["doctor", "--dependencies", str(self.root / "selected-tools")],
        )
        with patch.object(bootstrap, "prepare", side_effect=AssertionError("No setup needed")), \
                patch.object(bootstrap.importlib.util, "spec_from_file_location", side_effect=AssertionError("No runtime setup")), \
                patch("videomate.cli.main", return_value=0) as cli:
            for command in commands:
                self.assertEqual(self.call(["--offline", "--cli", *command])[0], 0)
                cli.assert_called_with(command)

    def test_command_help_and_invalid_arguments_skip_provisioning(self):
        with patch.object(bootstrap, "prepare", side_effect=AssertionError("No setup needed")), \
                patch.object(bootstrap.importlib.util, "spec_from_file_location", side_effect=AssertionError("No runtime setup")):
            with self.assertRaises(SystemExit) as exited:
                self.call(["--cli", "scan", "--help"])
            self.assertEqual(exited.exception.code, 0)
            code, output = self.call(["--cli", "scan", "--unknown", "SYNTHETIC_PRIVATE_CANARY"])
            self.assertEqual(code, 2)
            self.assertNotIn("SYNTHETIC_PRIVATE_CANARY", output)

    def test_explicit_runtime_setup_remains_available_for_metadata_commands(self):
        runtime = self.root / "requested-runtime"
        selected = runtime / "python"
        installer = SimpleNamespace(runtime_path=lambda _: runtime, install=Mock(return_value=selected))
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: None))
        with patch.object(bootstrap.importlib.util, "spec_from_file_location", return_value=spec), \
                patch.object(bootstrap.importlib.util, "module_from_spec", return_value=installer), \
                patch.object(bootstrap.os, "execv", side_effect=SystemExit(0)) as execute, \
                patch.object(bootstrap, "prepare", side_effect=AssertionError("No backend setup")):
            with self.assertRaises(SystemExit):
                self.call(["--offline", "--install-runtime", "--cli", "doctor"])
            installer.install.assert_called_once()
            self.assertFalse(installer.install.call_args.kwargs["online"])
            execute.assert_called_once()

    def test_selected_tool_bundle_used_for_offline_gui_and_cli(self):
        from dataclasses import asdict
        from videomate.preferences import Preferences
        tools = self.root / "selected-tools"
        explicit_tools = self.root / "explicit-tools"
        config = self.root / "settings.json"
        config.write_text(json.dumps({"schema_version": 1, **asdict(Preferences(dependencies=str(tools)))}))
        with patch("videomate.setup_local.check_backend", return_value={"platform": "linux-x86_64", "version": "9.0.2"}) as check, \
                patch("videomate.dependencies.load_bundle", side_effect=AssertionError("Do not use default tools")), \
                patch.object(bootstrap, "tkinter_available", return_value=True), \
                patch("videomate.gui.launch", return_value=0) as launch, \
                patch("videomate.cli.main", return_value=0):
            for gui_args in ([], ["--config", str(config)], ["--cli", "gui", "--config", str(config)]):
                self.assertEqual(self.call(["--offline", *gui_args])[0], 0)
                check.assert_called_with(tools)
            launch.assert_called()
            for overrides, expected in (([], tools), (["--dependencies", str(explicit_tools)], explicit_tools)):
                command = ["--offline", "--cli", "scan", "--config", str(config), "--input", str(self.root / "generated-input"), *overrides]
                self.assertEqual(self.call(command)[0], 0)
                check.assert_called_with(expected)

    def test_unavailable_selected_bundle_never_provisions_fallback(self):
        from videomate.errors import VideoMateError
        with patch("videomate.setup_local.check_backend", side_effect=VideoMateError("dependency_unavailable")), \
                patch.object(bootstrap.importlib.util, "spec_from_file_location", side_effect=AssertionError("No installer allowed")):
            with self.assertRaises(VideoMateError):
                bootstrap.prepare(bootstrap.arguments([]), dependencies=self.root / "selected-tools")

    def test_stale_custom_bundle_keeps_gui_settings_reachable(self):
        from dataclasses import asdict
        from videomate.errors import VideoMateError
        from videomate.preferences import Preferences
        config = self.root / "settings.json"
        config.write_text(json.dumps({"schema_version": 1, **asdict(Preferences(dependencies=str(self.root / "missing-tools")))}))
        with patch("videomate.setup_local.check_backend", side_effect=VideoMateError("dependency_unavailable")), \
                patch("videomate.dependencies.load_bundle", side_effect=AssertionError("No fallback bundle")), \
                patch.object(bootstrap, "tkinter_available", return_value=True), \
                patch("videomate.gui.launch", return_value=0) as launch, \
                patch("videomate.cli.main", return_value=0) as cli:
            self.assertEqual(self.call(["--offline", "--config", str(config)])[0], 0)
            launch.assert_called_once_with(config_path=config)
            self.assertEqual(self.call(["--offline", "--check", "--config", str(config)])[0], 2)
            self.assertEqual(self.call(["--offline", "--cli", "scan", "--config", str(config), "--input", str(self.root / "generated-input")])[0], 2)
            cli.assert_not_called()

    def test_invalid_gui_settings_reach_repair_flow_without_fallback_setup(self):
        config = self.root / "invalid-settings.json"
        config.write_text("Generated invalid settings")
        with patch.object(bootstrap, "prepare", side_effect=AssertionError("No fallback setup")), \
                patch.object(bootstrap, "tkinter_available", return_value=True), \
                patch("videomate.gui.launch", return_value=0) as launch:
            self.assertEqual(self.call(["--offline", "--config", str(config)])[0], 0)
            launch.assert_called_once_with(config_path=config)

    def test_software_check_and_self_test_do_not_load_preferences(self):
        with patch("videomate.preferences.load_preferences", side_effect=AssertionError("Do not read preferences")):
            for flags in (["--check"], ["--self-test"], ["--self-test", "--config", str(self.root / "unused.json")]):
                self.assertIsNone(bootstrap.selected_dependencies(bootstrap.arguments(flags)))

    def test_missing_backend_downloads_only_when_not_offline(self):
        from videomate.errors import VideoMateError
        install = Mock()
        module = SimpleNamespace(install=install)
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: None))
        with patch("videomate.dependencies.load_bundle", side_effect=VideoMateError("dependency_unavailable")), \
                patch("videomate.dependencies.default_root", return_value=self.root), \
                patch("videomate.dependencies.platform_tag", return_value="windows-x86_64"), \
                patch("videomate.setup_local.check_backend", return_value={"ready": True}), \
                patch.object(bootstrap.importlib.util, "spec_from_file_location", return_value=spec), \
                patch.object(bootstrap.importlib.util, "module_from_spec", return_value=module):
            for flags, offline in (([], False), (["--offline"], True), (["--setup-online"], False)):
                bootstrap.prepare(bootstrap.arguments(flags))
                self.assertEqual(install.call_args.args[0].offline, offline)
            install.reset_mock()
            (self.root / "windows-x86_64").mkdir()
            with self.assertRaises(VideoMateError):
                bootstrap.prepare(bootstrap.arguments([]))
            install.assert_not_called()

    def test_valid_backend_does_not_invoke_provisioning(self):
        with patch("videomate.dependencies.load_bundle"), patch("videomate.setup_local.check_backend", return_value={"ready": True}), \
                patch.object(bootstrap.importlib.util, "spec_from_file_location", side_effect=AssertionError("No installer allowed")):
            self.assertEqual(bootstrap.prepare(bootstrap.arguments([])), {"ready": True})

    def test_native_shell_launcher_from_unrelated_directory_with_spaces_and_unicode(self):
        # The source copy contains only known application source, never media.
        copy = self.root / "Software space & unicode Ω"
        (copy / "tools").mkdir(parents=True)
        shutil.copytree(ROOT / "src", copy / "src", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "tools/bootstrap.py", copy / "tools/bootstrap.py")
        shutil.copyfile(ROOT / "tools/install_python.py", copy / "tools/install_python.py")
        launcher = "start.bat" if os.name == "nt" else "start.sh"
        shutil.copyfile(ROOT / launcher, copy / launcher)
        env = os.environ.copy()
        env["VIDEOMATE_PYTHON"] = sys.executable
        args = [str(copy / launcher)] if os.name == "nt" else ["/bin/sh", str(copy / launcher)]
        result = subprocess.run(args + ["--cli", "--version"], shell=os.name == "nt", cwd=self.root, env=env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        from videomate import __version__
        self.assertIn(("VideoMate " + __version__).encode(), result.stdout)

    def test_native_desktop_check_never_opens_gui(self):
        spec = importlib.util.spec_from_file_location("vm_native_entry", ROOT / "tools/desktop_entry.py")
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        with patch.object(sys, "argv", ["VideoMate", "--check"]), patch("videomate.setup_local.check_backend") as check, patch.dict(sys.modules, {"tkinter": object()}):
            self.assertEqual(entry.main(), 0)
            check.assert_called_once()
            check.side_effect = RuntimeError("SYNTHETIC_PRIVATE_CANARY")
            self.assertEqual(entry.main(), 2)

    def test_native_desktop_rejects_unknown_flags_without_opening_gui(self):
        spec = importlib.util.spec_from_file_location("vm_native_entry", ROOT / "tools/desktop_entry.py")
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        with patch.object(sys, "argv", ["VideoMate", "--unknown"]):
            self.assertEqual(entry.main(), 2)
