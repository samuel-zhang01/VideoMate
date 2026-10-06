"""Platform defaults use invented environment values; no user files are read."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from videomate.preferences import default_config_path
from videomate.setup_local import default_workspace


class PlatformDefaultTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(Path.cwd().anchor) / "videomate-generated-home"
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        patch("platform.system", return_value="Linux").start()
        patch.object(Path, "home", return_value=self.home).start()
        for method in ("stat", "lstat", "open"):
            patch.object(Path, method, side_effect=AssertionError("Defaults must not inspect storage")).start()

    def test_unset_empty_and_relative_xdg_values_use_home_defaults(self):
        for value in (None, "", "relative", "../relative", "~/relative"):
            with self.subTest(value=value):
                for variable in ("XDG_CONFIG_HOME", "XDG_STATE_HOME"):
                    if value is None:
                        os.environ.pop(variable, None)
                    else:
                        os.environ[variable] = value
                self.assertEqual(default_config_path(), self.home / ".config/VideoMate/settings.json")
                self.assertEqual(default_workspace(), self.home / ".local/state/VideoMate/Workspace")

    def test_absolute_xdg_values_are_independent_and_preserve_spaces_unicode(self):
        config = self.home / "Generated config Ω"
        state = self.home / "Generated state Ω"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config), "XDG_STATE_HOME": str(state)}):
            self.assertEqual(default_config_path(), config / "VideoMate/settings.json")
            self.assertEqual(default_workspace(), state / "VideoMate/Workspace")

    def test_explicit_config_override_takes_precedence(self):
        selected = self.home / "selected-settings.json"
        with patch.dict(os.environ, {"VIDEOMATE_CONFIG": str(selected), "XDG_CONFIG_HOME": str(self.home / "ignored")}):
            self.assertEqual(default_config_path(), selected)

    def test_macos_defaults_ignore_xdg_values(self):
        with patch("platform.system", return_value="Darwin"), patch.dict(os.environ, {
                "XDG_CONFIG_HOME": str(self.home / "ignored-config"), "XDG_STATE_HOME": str(self.home / "ignored-state")}):
            parent = self.home / "Library/Application Support/VideoMate"
            self.assertEqual(default_config_path(), parent / "settings.json")
            self.assertEqual(default_workspace(), parent / "Workspace")
