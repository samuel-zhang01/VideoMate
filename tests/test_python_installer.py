import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vm_python_installer_tests", ROOT / "tools/install_python.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class PythonInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videomate-runtime-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "dependencies").mkdir()
        self.archive = self.root / "invented-runtime.tar.gz"
        self.patch = patch.object(installer, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def make_archive(self, *, bad_name=None, link_target="python3.13", cycle=False):
        with tarfile.open(self.archive, "w:gz") as package:
            data = b"Invented runtime stand-in. Never executed."
            info = tarfile.TarInfo(bad_name or "python/bin/python3.13")
            info.size, info.mode = len(data), 0o755
            package.addfile(info, io.BytesIO(data))
            link = tarfile.TarInfo("python/bin/python3")
            link.type, link.linkname = tarfile.SYMTYPE, "python3" if cycle else link_target
            package.addfile(link)
        spec = {"platforms":{"linux-x86_64":{"version":"3.13.15", "filename":self.archive.name,
                "url":"https://invalid.example/runtime.tar.gz", "sha256":hashlib.sha256(self.archive.read_bytes()).hexdigest()}}}
        (self.root / "dependencies/python-sources.json").write_text(json.dumps(spec))

    def test_offline_install_materializes_internal_links_and_is_idempotent(self):
        self.make_archive()
        with patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("No network")):
            executable = installer.install("linux-x86_64", archive=self.archive)
            self.assertFalse(executable.is_symlink())
            self.assertIn(b"Never executed", executable.read_bytes())
            self.assertEqual(installer.install("linux-x86_64"), executable)
        executable.write_bytes(b"tampered synthetic software")
        with self.assertRaises(ValueError):
            installer.install("linux-x86_64", archive=self.archive)

    def test_default_does_not_download_and_releases_its_lock(self):
        self.make_archive()
        with patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("No network")):
            with self.assertRaises(ValueError):
                installer.install("linux-x86_64")
        self.assertFalse((self.root / "dependencies/python/.install-linux-x86_64.lock").exists())

    def test_different_installer_lock_is_preserved(self):
        self.make_archive()
        directory = self.root / "dependencies/python"
        directory.mkdir()
        lock = directory / ".install-linux-x86_64.lock"
        lock.write_text("Another installer owns this")
        with self.assertRaises(FileExistsError):
            installer.install("linux-x86_64", archive=self.archive)
        self.assertEqual(lock.read_text(), "Another installer owns this")

    def test_external_paths_links_and_cycles_are_rejected(self):
        for options in ({"bad_name":"../escape"}, {"bad_name":"/absolute"},
                        {"link_target":"../../../escape"}, {"link_target":"/absolute"}, {"cycle":True}):
            with self.subTest(options=options):
                self.make_archive(**options)
                with self.assertRaises(ValueError):
                    installer.install("linux-x86_64", archive=self.archive)
                self.assertFalse((self.root / "dependencies/python/linux-x86_64").exists())

    def test_changed_archive_never_installs(self):
        self.make_archive()
        with self.archive.open("ab") as file:
            file.write(b"mutation")
        with self.assertRaises(ValueError):
            installer.install("linux-x86_64", archive=self.archive)
