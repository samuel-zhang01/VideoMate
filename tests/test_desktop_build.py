"""Packaging checks against invented software trees, never operator files."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("build_desktop", Path(__file__).resolve().parents[1] / "tools/build_desktop.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DesktopBuildTests(unittest.TestCase):
    def test_license_lookup_covers_windows_and_unix_layouts(self):
        with tempfile.TemporaryDirectory(prefix="videomate-license-test-") as directory:
            root = Path(directory)
            stdlib = root / "lib" / "python3.13"
            stdlib.mkdir(parents=True)
            with self.assertRaises(SystemExit):
                builder.find_python_license(root, stdlib)
            unix_license = stdlib / "LICENSE.txt"
            unix_license.write_text("Invented license marker")
            self.assertEqual(builder.find_python_license(root, stdlib), unix_license)
            windows_license = root / "LICENSE.txt"
            windows_license.write_text("Invented license marker")
            self.assertEqual(builder.find_python_license(root, stdlib), windows_license)
