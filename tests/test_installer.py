"""Exercise provisioning with invented archives; no network or executable launch."""

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("videomate_installer", Path(__file__).resolve().parents[1] / "tools" / "install_ffmpeg.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videomate-synthetic-installer-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "dependencies").mkdir()
        self.archive = self.root / "synthetic.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name in ("ffmpeg.exe", "ffprobe.exe", "LICENSE", "README.txt"):
                archive.writestr("synthetic/" + name, b"Invented fixture; not executable: " + name.encode())
            archive.writestr("../../escape.txt", b"Must never be extracted")
        spec = {"windows-x86_64": {"version": "1.2.3", "url": "https://invalid.example/synthetic.zip",
                                  "sha256": hashlib.sha256(self.archive.read_bytes()).hexdigest()}}
        (self.root / "dependencies" / "sources.json").write_text(json.dumps(spec))
        self.args = argparse.Namespace(platform="windows-x86_64", archive=str(self.archive),
                                       import_directory=None, version=None, ffmpeg_sha256=None,
                                       ffprobe_sha256=None, license_file=None)

    def install(self):
        with patch.object(installer, "ROOT", self.root), contextlib.redirect_stdout(io.StringIO()):
            installer.install(self.args)

    def test_offline_archive_extracts_only_tools_and_provenance(self):
        with patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("No network permitted")):
            self.install()
        target = self.root / "dependencies" / "ffmpeg" / "windows-x86_64"
        manifest = json.loads((target / "manifest.json").read_text())
        for name in ("ffmpeg", "ffprobe"):
            self.assertEqual(installer.digest(target / "bin" / (name + ".exe")), manifest["binaries"][name]["sha256"])
        self.assertFalse((self.root / "dependencies" / "escape.txt").exists())
        self.assertEqual(len(list(target.rglob("*"))), 6)
        with self.assertRaises(ValueError):
            self.install()  # Never replace an installed bundle.

    def test_changed_archive_never_becomes_executable_bundle(self):
        with self.archive.open("ab") as archive:
            archive.write(b"changed fixture")
        with self.assertRaises(ValueError):
            self.install()
        self.assertFalse((self.root / "dependencies" / "ffmpeg" / "windows-x86_64").exists())

    def test_download_never_deletes_an_existing_partial(self):
        cache = self.root / "dependencies" / "cache"
        cache.mkdir()
        part = cache / "ffmpeg-windows-x86_64-1.2.3.zip.part"
        part.write_bytes(b"another install owns this")
        self.args.archive = None
        with patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("No network permitted")):
            with self.assertRaises(FileExistsError):
                self.install()
        self.assertEqual(part.read_bytes(), b"another install owns this")

    def test_failed_download_cleans_only_its_owned_partial(self):
        self.args.archive = None
        with patch.object(installer.urllib.request, "urlopen", side_effect=OSError("Synthetic network failure")):
            with self.assertRaises(OSError):
                self.install()
        part = self.root / "dependencies" / "cache" / "ffmpeg-windows-x86_64-1.2.3.zip.part"
        self.assertFalse(part.exists())

    def apple_archives(self, header=bytes.fromhex("cffaedfe0c000001")):
        assets = []
        for name in ("ffmpeg", "ffprobe"):
            file = self.root / (name + "-macos-arm64-1.2.3.zip")
            with zipfile.ZipFile(file, "w") as archive:
                archive.writestr(name, header + b"synthetic native header stand-in; never execute")
                archive.writestr("../../outside", b"Do not extract")
            assets.append({"name": name, "url": "https://invalid.example/" + name,
                           "sha256": installer.digest(file)})
        spec = {"macos-arm64": {"version": "1.2.3", "publisher": "Synthetic publisher", "assets": assets,
                                "source_url": "https://invalid.example/source"}}
        (self.root / "dependencies" / "sources.json").write_text(json.dumps(spec))
        licenses = self.root / "dependencies" / "licenses"
        licenses.mkdir()
        (licenses / "ffmpeg-GPLv3.txt").write_text("Synthetic license stand-in")
        self.args.platform, self.args.archive, self.args.archive_directory = "macos-arm64", None, str(self.root)

    def test_apple_silicon_offline_archives_and_native_architecture_check(self):
        self.apple_archives()
        with patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("No network permitted")):
            self.install()
        from videomate.dependencies import load_bundle
        bundle = load_bundle(self.root / "dependencies" / "ffmpeg", for_platform="macos-arm64")
        self.assertEqual(bundle.platform, "macos-arm64")
        self.assertEqual(bundle.version, "1.2.3")
        self.assertFalse((self.root / "dependencies" / "outside").exists())

    def test_apple_silicon_rejects_intel_executable_even_with_matching_hash(self):
        self.apple_archives(header=bytes.fromhex("cffaedfe07000001"))
        with self.assertRaises(ValueError):
            self.install()
        self.assertFalse((self.root / "dependencies" / "ffmpeg" / "macos-arm64").exists())

    def test_linux_archives_validate_elf_architecture_and_preserve_offline_mode(self):
        self.apple_archives()
        spec = json.loads((self.root / "dependencies/sources.json").read_text())["macos-arm64"]
        self.args.platform = "linux-x86_64"
        for asset in spec["assets"]:
            file = self.root / (asset["name"] + "-linux-x86_64-1.2.3.zip")
            header = bytearray(20)
            header[:6] = b"\x7fELF\x02\x01"
            header[18] = 62
            with zipfile.ZipFile(file, "w") as archive:
                archive.writestr(asset["name"], header + b"Invented ELF, never executed")
            asset["sha256"] = installer.digest(file)
        (self.root / "dependencies/sources.json").write_text(json.dumps({"linux-x86_64":spec}))
        self.args.offline = True
        with patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("No network")):
            self.install()
        from videomate.dependencies import load_bundle
        self.assertEqual(load_bundle(self.root / "dependencies/ffmpeg", for_platform="linux-x86_64").version, "1.2.3")

    def test_offline_missing_archive_never_downloads_and_preserves_other_lock(self):
        self.args.archive, self.args.offline = None, True
        with patch.object(installer.urllib.request, "urlopen", side_effect=AssertionError("No network")):
            with self.assertRaises(ValueError):
                self.install()
        lock = self.root / "dependencies/ffmpeg/.install-windows-x86_64.lock"
        self.assertFalse(lock.exists())
        lock.write_text("owned by another setup")
        with self.assertRaises(FileExistsError):
            self.install()
        self.assertEqual(lock.read_text(), "owned by another setup")
