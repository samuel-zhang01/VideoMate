"""Exercise native pre-Python failures using invented archives, with no downloads."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoPythonBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="videomate-bootstrap-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "Software space & unicode Ω"
        for name in ("tools/bootstrap_runtime.ps1", "tools/bootstrap_runtime.sh", "dependencies/python-sources.json",
                     "dependencies/runtime-bootstrap.tsv"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("VIDEOMATE_")}
        self.env["VIDEOMATE_RUNTIME_ROOT"] = str(self.root / "runtime")

    def run_helper(self, *args):
        from videomate.dependencies import platform_tag
        if os.name == "nt":
            shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            command = [str(shell), "-NoProfile", "-File", str(self.root / "tools/bootstrap_runtime.ps1")]
        else:
            command = ["/bin/sh", str(self.root / "tools/bootstrap_runtime.sh"), platform_tag()]
        result = subprocess.run(command + list(args), cwd=self.temporary.name, env=self.env, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "runtime" / platform_tag()).exists())
        self.assertEqual(list((self.root / "runtime").glob(".bootstrap-*")), [])
        self.assertNotIn(b"SYNTHETIC_SECRET_PATH", result.stdout + result.stderr)
        return result

    def test_offline_without_archive_fails_without_installing(self):
        self.run_helper("--offline")

    def test_bad_archive_is_refused_before_extraction(self):
        archive = self.root / "SYNTHETIC_SECRET_PATH.tar.gz"
        archive.write_bytes(b"invented invalid software archive")
        result = self.run_helper("--offline", "--runtime-archive", str(archive))
        self.assertIn(b"checksum", result.stdout + result.stderr)
        self.assertEqual(archive.read_bytes(), b"invented invalid software archive")

    def test_unattended_runtime_download_requires_explicit_yes(self):
        result = self.run_helper()
        self.assertIn(b"--yes", result.stdout + result.stderr)
        self.assertIn(b"python.org/downloads", result.stdout + result.stderr)
        self.assertEqual(list((self.root / "dependencies/cache").iterdir()), [])
