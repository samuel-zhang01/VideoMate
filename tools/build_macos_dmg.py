"""Create, notarize and verify a Developer ID signed Apple Silicon DMG.

The input is an already-built VideoMate desktop directory containing only public
software and synthetic test evidence. Credentials stay in the operator's
notarytool Keychain profile; this command never reads or prints them.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from build_desktop import mac_signing_team, validate_mac_signing, verify_mac_signature


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def run_checked(stage, command):
    result = subprocess.run([str(value) for value in command], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(stage + " failed; review the release machine locally")
    return result.stdout


def validate_input(desktop_dir, identity, profile):
    if platform.system() != "Darwin" or platform.machine().lower() != "arm64":
        raise ValueError("A native Apple Silicon host is required")
    validate_mac_signing("macos-arm64", identity, "local.videomate.validation")
    if not profile or any(character in profile for character in "\r\n\0"):
        raise ValueError("An existing notarytool Keychain profile is required")
    desktop_dir = Path(desktop_dir).absolute()
    manifest = json.loads((desktop_dir / "package-manifest.json").read_text(encoding="utf-8"))
    report = json.loads((desktop_dir / "synthetic-test-results.json").read_text(encoding="utf-8"))
    checks = report.get("checks")
    if (manifest.get("platform") != "macos-arm64" or report.get("status") != "passed"
            or report.get("synthetic_only") is not True or not isinstance(checks, dict)
            or not checks or not all(value is True for value in checks.values())):
        raise ValueError("Input is not a tested Apple Silicon development package")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > 20000:
        raise ValueError("Package manifest is invalid")
    for name, expected in files.items():
        relative = PurePosixPath(name)
        if (not isinstance(name, str) or relative.is_absolute() or ".." in relative.parts
                or "\\" in name or not re.fullmatch(r"[0-9a-f]{64}", str(expected))):
            raise ValueError("Package manifest is invalid")
        item = desktop_dir.joinpath(*relative.parts)
        if not item.resolve().is_relative_to(desktop_dir) or not item.is_file() or item.is_symlink() or digest(item) != expected:
            raise ValueError("Package contents differ from the build manifest")
    archive = desktop_dir.with_name(desktop_dir.name + ".zip")
    checksum = archive.with_suffix(".zip.sha256")
    if not archive.is_file() or not checksum.is_file() or checksum.read_text(encoding="ascii").strip() != digest(archive):
        raise ValueError("Desktop ZIP checksum gate failed")
    app = desktop_dir / "VideoMate.app"
    if not app.is_dir() or app.is_symlink():
        raise ValueError("Expected a local VideoMate.app bundle")
    app_root = app.resolve()
    for entry in app.rglob("*"):
        if entry.is_symlink():
            try:
                resolved = entry.resolve(strict=True)
            except (OSError, RuntimeError):
                raise ValueError("Mac app contains an invalid software link") from None
            if not resolved.is_relative_to(app_root):
                raise ValueError("Mac app contains an external software link")
    app_team = verify_mac_signature(app, signed=True)
    if app_team != mac_signing_team(identity):
        raise ValueError("Signed app belongs to a different Apple team than the selected DMG identity")
    tools = app / "Contents/Resources/dependencies/ffmpeg/macos-arm64/bin"
    for name in ("ffmpeg", "ffprobe"):
        if verify_mac_signature(tools / name, signed=True) != app_team:
            raise ValueError("A packaged FFmpeg tool has a different Apple signing team")
    return desktop_dir, app, manifest


def build(desktop_dir, *, sign_identity, notary_profile):
    desktop_dir, app, manifest = validate_input(desktop_dir, sign_identity, notary_profile)
    version = manifest.get("app_version")
    if not isinstance(version, str) or not version or any(c not in "0123456789." for c in version):
        raise ValueError("Invalid package version")
    output = desktop_dir.parent / f"videomate-{version}-macos-arm64.dmg"
    sidecar = output.with_suffix(".dmg.sha256")
    evidence = output.with_suffix(".dmg-evidence.json")
    if any(path.exists() for path in (output, sidecar, evidence)):
        raise ValueError("DMG destination already exists; existing artifacts were preserved")
    with tempfile.TemporaryDirectory(prefix="videomate-macos-dmg-") as temporary:
        stage = Path(temporary) / "contents"
        stage.mkdir()
        run_checked("App staging", ["/usr/bin/ditto", app, stage / "VideoMate.app"])
        os.symlink("/Applications", stage / "Applications")
        run_checked("DMG creation", ["/usr/bin/hdiutil", "create", "-format", "UDZO", "-fs", "HFS+",
                                      "-volname", "VideoMate", "-srcfolder", stage, output])
    run_checked("DMG signing", ["/usr/bin/codesign", "--force", "--sign", sign_identity,
                                "--timestamp", output])
    run_checked("DMG signature verification", ["/usr/bin/codesign", "--verify", "--strict", output])
    response = run_checked("Apple notarization", ["/usr/bin/xcrun", "notarytool", "submit", output,
                                                    "--keychain-profile", notary_profile, "--wait",
                                                    "--output-format", "json"])
    try:
        accepted = json.loads(response).get("status") == "Accepted"
    except (ValueError, TypeError):
        accepted = False
    if not accepted:
        raise RuntimeError("Apple notarization did not accept the DMG; review the release machine locally")
    run_checked("Ticket stapling", ["/usr/bin/xcrun", "stapler", "staple", output])
    run_checked("Ticket validation", ["/usr/bin/xcrun", "stapler", "validate", output])
    run_checked("Gatekeeper DMG assessment", ["/usr/sbin/spctl", "--assess", "--type", "open",
                                               "--context", "context:primary-signature", output])
    run_checked("Final DMG signature verification", ["/usr/bin/codesign", "--verify", "--strict", output])
    sha256 = digest(output)
    sidecar.write_text(sha256 + "\n", encoding="ascii")
    evidence.write_text(json.dumps({"schema_version": 1, "platform": "macos-arm64", "version": version,
                                    "synthetic_tests": "passed", "developer_id_signed": True,
                                    "notarization": "Accepted", "ticket_stapled": True,
                                    "gatekeeper_dmg_assessment": "passed", "dmg_sha256": sha256}, indent=2) + "\n",
                        encoding="utf-8")
    print("Built and verified " + output.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop-dir", type=Path, required=True, help="Tested, signed Mac desktop output")
    parser.add_argument("--sign-identity", required=True, help="Developer ID Application identity in Keychain")
    parser.add_argument("--notary-profile", required=True, help="Existing notarytool Keychain profile")
    args = parser.parse_args()
    try:
        build(args.desktop_dir, sign_identity=args.sign_identity, notary_profile=args.notary_profile)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error, (ValueError, RuntimeError)) else "Mac DMG preparation failed", file=sys.stderr)
        raise SystemExit(1) from None
