import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from videomate.dependencies import load_bundle
from videomate.errors import VideoMateError
from videomate.policy import LocalTestScope, create_workspace, validate_workspace


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="videomate-synthetic-bundle-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.platform = self.root / "windows-x86_64"
        (self.platform / "bin").mkdir(parents=True)
        self.manifest = {"schema_version": 1, "platform": "windows-x86_64", "version": "9.0.2", "binaries": {}}
        for name in ("ffmpeg", "ffprobe"):
            data = b"Synthetic public binary stand-in; never executed " + name.encode()
            (self.platform / "bin" / (name + ".exe")).write_bytes(data)
            self.manifest["binaries"][name] = {"file": "bin/" + name + ".exe", "sha256": hashlib.sha256(data).hexdigest()}
        self.save()

    def save(self):
        (self.platform / "manifest.json").write_text(json.dumps(self.manifest))

    def load(self):
        with patch("videomate.dependencies.platform_tag", return_value="windows-x86_64"):
            return load_bundle(self.root)

    def test_valid_bundle_integrity(self):
        bundle = self.load()
        self.assertEqual(bundle.version, "9.0.2")
        self.assertNotIn(str(self.root), repr(bundle))

    def test_changed_binary_rejected(self):
        (self.platform / "bin" / "ffprobe.exe").write_bytes(b"changed synthetic bytes")
        with self.assertRaises(VideoMateError):
            self.load()

    def test_manifest_cannot_redirect_to_unrelated_file(self):
        self.manifest["binaries"]["ffmpeg"]["file"] = "../../UNRELATED_FILE"
        self.save()
        with self.assertRaises(VideoMateError):
            self.load()

    def test_wrong_platform_and_missing_tools_rejected(self):
        self.manifest["platform"] = "linux-x86_64"
        self.save()
        with self.assertRaises(VideoMateError):
            self.load()
        self.manifest["platform"] = "windows-x86_64"
        self.save()
        (self.platform / "bin" / "ffprobe.exe").unlink()
        with self.assertRaises(VideoMateError):
            self.load()

    def test_local_test_scope_is_exact_file_only(self):
        file = self.root / "generated-marker.bin"
        file.write_bytes(b"synthetic marker")
        scope = LocalTestScope(frozenset({file}), self.root / "code")
        scope.authorize(file)
        with self.assertRaises(VideoMateError):
            scope.authorize(self.root / "NEVER_OPEN_THIS")
        with self.assertRaises(VideoMateError):
            LocalTestScope(frozenset({self.root}), self.root / "code").authorize(self.root)

    def test_local_test_source_and_workspace_exclude_sync_folders(self):
        synced = self.root / "OneDrive" / "test.bin"
        synced.parent.mkdir()
        synced.write_bytes(b"synthetic marker")
        with self.assertRaises(VideoMateError):
            LocalTestScope(frozenset({synced}), self.root / "code").authorize(synced)
        workspace = create_workspace(self.root / "workspace", self.root / "code")
        self.assertEqual(validate_workspace(workspace, self.root / "code"), workspace)
