"""Focused Mac release-signing guards; no Keychain or media is accessed."""

import sys
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_desktop
import build_macos_dmg
import build_release


class MacSigningTests(unittest.TestCase):
    def test_distribution_options_require_developer_id_and_approved_bundle_id(self):
        build_desktop.validate_mac_signing("macos-arm64", None, None)
        build_desktop.validate_mac_signing("macos-arm64", "Developer ID Application: Invented (ABCDEFGHIJ)",
                                           "example.videomate.desktop")
        for tag, identity, bundle_id in (
            ("linux-arm64", "Developer ID Application: Invented", "example.videomate.desktop"),
            ("macos-arm64", "Mac Development: Invented", "example.videomate.desktop"),
            ("macos-arm64", "Developer ID Application: Invented", "bad bundle id"),
            ("macos-arm64", "Developer ID Application: Invented", "example.videomate.desktop"),
            ("macos-arm64", "Developer ID Application: Invented", None),
        ):
            with self.subTest(tag=tag, bundle_id=bundle_id), self.assertRaises(ValueError):
                build_desktop.validate_mac_signing(tag, identity, bundle_id)

    def test_missing_identity_fails_before_release_setup(self):
        identity = "Developer ID Application: Invented (ABCDEFGHIJ)"
        with patch.object(build_desktop.subprocess, "run", return_value=CompletedProcess([], 0, stdout="0 valid identities found\n")):
            with self.assertRaisesRegex(ValueError, "not available in Keychain"):
                build_desktop.check_mac_signing_identity(identity)
        available = f'  1) {"A" * 40} "{identity}"\n     1 valid identities found\n'
        with patch.object(build_desktop.subprocess, "run", return_value=CompletedProcess([], 0, stdout=available)):
            build_desktop.check_mac_signing_identity(identity)
        with patch.object(build_release, "check_mac_signing_identity", side_effect=ValueError("identity missing")), \
                patch.object(build_release, "build_python") as build_python:
            with self.assertRaisesRegex(ValueError, "identity missing"):
                build_release.build(Path("/synthetic/release"), mac_sign_identity=identity,
                                    mac_bundle_id="example.videomate.desktop")
            build_python.assert_not_called()

    def test_dmg_rejects_a_different_signing_team(self):
        with tempfile.TemporaryDirectory(prefix="videomate-mac-signing-generated-") as temporary:
            desktop = Path(temporary).resolve() / "videomate-0.8.3-macos-arm64-desktop"
            app = desktop / "VideoMate.app"
            app.mkdir(parents=True)
            marker = desktop / "marker.txt"
            marker.write_bytes(b"invented software marker")
            manifest = {"platform": "macos-arm64", "files": {
                "marker.txt": hashlib.sha256(marker.read_bytes()).hexdigest()}}
            (desktop / "package-manifest.json").write_text(json.dumps(manifest))
            (desktop / "synthetic-test-results.json").write_text(json.dumps({
                "status": "passed", "synthetic_only": True, "checks": {"invented": True}}))
            archive = desktop.with_name(desktop.name + ".zip")
            archive.write_bytes(b"invented desktop archive")
            archive.with_suffix(".zip.sha256").write_text(hashlib.sha256(archive.read_bytes()).hexdigest())
            external = Path(temporary).resolve() / "invented-external-software"
            external.write_bytes(b"invented software marker")
            link = app / "external-link"
            link.symlink_to(external)
            with patch.object(build_macos_dmg.platform, "system", return_value="Darwin"), \
                    patch.object(build_macos_dmg.platform, "machine", return_value="arm64"), \
                    patch.object(build_macos_dmg, "verify_mac_signature", return_value="ZZZZZZZZZZ"):
                with self.assertRaisesRegex(ValueError, "external software link"):
                    build_macos_dmg.validate_input(desktop,
                        "Developer ID Application: Invented (ABCDEFGHIJ)", "invented-profile")
                link.unlink()
                with self.assertRaisesRegex(ValueError, "different Apple team"):
                    build_macos_dmg.validate_input(desktop,
                        "Developer ID Application: Invented (ABCDEFGHIJ)", "invented-profile")

    def test_signature_guard_requires_team_and_hardened_runtime(self):
        verified = CompletedProcess([], 0)
        good = CompletedProcess([], 0, stdout="", stderr="flags=0x10000(runtime)\nTeamIdentifier=ABCDEFGHIJ\nTimestamp=Sep 28, 2026 at 12:00:00\n")
        with patch.object(build_desktop.subprocess, "run", side_effect=[verified, good]):
            self.assertEqual(build_desktop.verify_mac_signature(Path("/synthetic/VideoMate.app"), signed=True),
                             "ABCDEFGHIJ")
        for details in ("Signature=adhoc\nTeamIdentifier=not set\n",
                        "flags=0x0(none)\nTeamIdentifier=ABCDEFGHIJ\nTimestamp=Sep 28, 2026\n",
                        "flags=0x10000(runtime)\nTeamIdentifier=ABCDEFGHIJ\n"):
            with self.subTest(details=details):
                displayed = CompletedProcess([], 0, stdout="", stderr=details)
                with patch.object(build_desktop.subprocess, "run", side_effect=[verified, displayed]):
                    with self.assertRaises(ValueError):
                        build_desktop.verify_mac_signature(Path("/synthetic/VideoMate.app"), signed=True)


if __name__ == "__main__":
    unittest.main()
