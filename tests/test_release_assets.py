"""Checksum gate tests use invented software-archive bytes, never media."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("vm_release_assets", Path(__file__).resolve().parents[1] / "tools/verify_release_assets.py")
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class ReleaseAssetTests(unittest.TestCase):
    def test_missing_or_modified_asset_fails_checksum_gate(self):
        with tempfile.TemporaryDirectory(prefix="videomate-release-check-") as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                assets.verify(root)
            archive = root / "videomate-0.6.1-windows-x86_64-desktop.zip"
            archive.write_bytes(b"invented release file")
            archive.with_suffix(".zip.sha256").write_text(hashlib.sha256(archive.read_bytes()).hexdigest())
            assets.verify(root)
            archive.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                assets.verify(root)

    def test_linux_appimage_sidecar_is_required(self):
        with tempfile.TemporaryDirectory(prefix="videomate-appimage-check-") as temporary:
            root = Path(temporary)
            appimage = root / "videomate-0.8.3-linux-arm64.AppImage"
            appimage.write_bytes(b"invented AppImage marker")
            with self.assertRaises(FileNotFoundError):
                assets.verify(root)
            appimage.with_suffix(".AppImage.sha256").write_text(hashlib.sha256(appimage.read_bytes()).hexdigest())
            assets.verify(root)

    def test_macos_dmg_is_included_in_checksum_gate(self):
        with tempfile.TemporaryDirectory(prefix="videomate-dmg-check-") as temporary:
            root = Path(temporary)
            dmg = root / "videomate-0.8.3-macos-arm64.dmg"
            dmg.write_bytes(b"invented DMG marker")
            with self.assertRaises(FileNotFoundError):
                assets.verify(root)
            dmg.with_suffix(".dmg.sha256").write_text(hashlib.sha256(dmg.read_bytes()).hexdigest())
            assets.verify(root)
            dmg.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                assets.verify(root)
