"""AppImage build gates use invented software files only."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from videomate import __version__

spec = importlib.util.spec_from_file_location("appimage_builder", Path(__file__).resolve().parents[1] / "tools/build_linux_appimage.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class AppImageBuildTests(unittest.TestCase):
    def test_desktop_manifest_must_match_exact_software(self):
        with tempfile.TemporaryDirectory(prefix="videomate-appimage-invented-") as temporary:
            root = Path(temporary) / f"videomate-{__version__}-linux-x86_64-desktop"
            executable = root / "VideoMate/VideoMate"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"invented executable marker")
            executable.chmod(0o755)
            (root / "synthetic-test-results.json").write_text(json.dumps({
                "status": "passed", "synthetic_only": True, "checks": {"invented": True}}))
            report = root / "synthetic-test-results.json"
            manifest = {"app_version": __version__, "platform": "linux-x86_64",
                        "files": {"VideoMate/VideoMate": hashlib.sha256(executable.read_bytes()).hexdigest(),
                                  "synthetic-test-results.json": hashlib.sha256(report.read_bytes()).hexdigest()}}
            (root / "package-manifest.json").write_text(json.dumps(manifest))
            builder.check_desktop(root, "linux-x86_64")
            extra = root / "VideoMate" / "unlisted.txt"
            extra.write_text("invented software marker")
            with self.assertRaisesRegex(ValueError, "unlisted file"):
                builder.check_desktop(root, "linux-x86_64")
            extra.unlink()
            manifest["files"][""] = "0" * 64
            (root / "package-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                builder.check_desktop(root, "linux-x86_64")
            del manifest["files"][""]
            (root / "package-manifest.json").write_text(json.dumps(manifest))
            executable.write_bytes(b"changed marker")
            with self.assertRaises(ValueError):
                builder.check_desktop(root, "linux-x86_64")

    def test_rejects_failed_report_and_external_link(self):
        with tempfile.TemporaryDirectory(prefix="videomate-appimage-links-invented-") as temporary:
            parent = Path(temporary)
            root = parent / f"videomate-{__version__}-linux-x86_64-desktop"
            executable = root / "VideoMate/VideoMate"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"invented executable marker")
            executable.chmod(0o755)
            report = root / "synthetic-test-results.json"
            report.write_text(json.dumps({"status": "failed", "synthetic_only": True, "checks": {"invented": True}}))
            manifest = {"app_version": __version__, "platform": "linux-x86_64",
                        "files": {"VideoMate/VideoMate": hashlib.sha256(executable.read_bytes()).hexdigest(),
                                  "synthetic-test-results.json": hashlib.sha256(report.read_bytes()).hexdigest()}}
            (root / "package-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "generated-media checks"):
                builder.check_desktop(root, "linux-x86_64")
            report.write_text(json.dumps({"status": "passed", "synthetic_only": True, "checks": {"invented": True}}))
            manifest["files"]["synthetic-test-results.json"] = hashlib.sha256(report.read_bytes()).hexdigest()
            (root / "package-manifest.json").write_text(json.dumps(manifest))
            outside = parent / "invented-external-software"
            outside.write_bytes(b"invented software marker")
            (root / "VideoMate" / "external-link").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "external software link"):
                builder.check_desktop(root, "linux-x86_64")
