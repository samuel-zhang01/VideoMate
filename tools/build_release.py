"""Automatically build the native VideoMate desktop release on this host.

This command handles only public source and pinned public software. It never
searches for or accepts media. Each architecture must execute on its own host.
Developer ID signing and notarization are optional on a native Mac with the
required account setup. GitHub Actions, uploading and tagging are separate.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from videomate import __version__
from videomate.dependencies import load_bundle, platform_tag
from videomate.errors import VideoMateError
from install_python import install as install_python, verify as verify_python
from build_desktop import check_mac_signing_identity, validate_mac_signing

TARGETS = {"windows-x86_64", "windows-arm64", "linux-x86_64", "linux-arm64", "macos-arm64"}


def run(command, **kwargs):
    subprocess.run([str(part) for part in command], check=True, cwd=ROOT, **kwargs)


def has_tk(executable):
    return subprocess.run([str(executable), "-I", "-c", "import tkinter; assert tkinter.TkVersion >= 8.6"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode == 0


def build_python(tag, offline):
    if sys.version_info >= (3, 11) and has_tk(sys.executable):
        return Path(sys.executable)
    try:
        python = verify_python(tag)
    except (OSError, ValueError):
        python = install_python(tag, online=not offline)
    if not has_tk(python):
        raise ValueError("Pinned build Python does not have working Tcl/Tk")
    return python


def build_environment(base_python, tag, *, offline, wheelhouse):
    requirements = ROOT / "tools/requirements-build.txt"
    requirements_hash = hashlib.sha256(requirements.read_bytes()).hexdigest()
    cache = Path(os.environ.get("VIDEOMATE_RELEASE_BUILD_CACHE",
                                os.environ.get("LOCALAPPDATA", str(Path.home() / ".cache")))) / "VideoMate/ReleaseBuild"
    cache.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output([str(base_python), "-I", "-c", "import sys; print(f'{sys.version_info.major}{sys.version_info.minor}')"], text=True).strip()
    directory = cache / f"{tag}-py{version}"
    marker = directory / "videomate-builder.json"
    expected = {"schema_version": 1, "platform": tag, "base_python": str(base_python),
                "requirements_sha256": requirements_hash}
    if directory.exists():
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) != expected:
            raise ValueError("Existing release build environment differs; choose a clean native host or review it locally")
    else:
        directory.mkdir()
        marker.write_text(json.dumps(expected, indent=2), encoding="utf-8")
        run([base_python, "-m", "venv", directory])
    python = directory / ("Scripts/python.exe" if tag.startswith("windows-") else "bin/python")
    installed = subprocess.run([str(python), "-I", "-c", "import importlib.metadata as m; assert m.version('pyinstaller') == '6.22.0'"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode == 0
    if not installed:
        command = [python, "-m", "pip", "install", "-r", requirements]
        if offline:
            if not wheelhouse:
                raise ValueError("Offline build needs an installed build environment or --wheelhouse")
            command += ["--no-index", "--find-links", wheelhouse]
        run(command)
    if not has_tk(python):
        raise ValueError("Isolated release build Python cannot load Tcl/Tk")
    return python


def ensure_ffmpeg(python, tag, offline):
    try:
        load_bundle(for_platform=tag)
        return
    except VideoMateError:
        pass
    command = [python, ROOT / "tools/install_ffmpeg.py", "--platform", tag]
    if offline:
        command.append("--offline")
    run(command)
    load_bundle(for_platform=tag)


def build(output_root, *, offline=False, wheelhouse=None, appimage=True,
          mac_sign_identity=None, mac_bundle_id=None, mac_notary_profile=None):
    tag = platform_tag()
    if tag not in TARGETS:
        raise ValueError("No native desktop release target for this operating system/architecture")
    if any((mac_sign_identity, mac_bundle_id, mac_notary_profile)) and tag != "macos-arm64":
        raise ValueError("Mac signing options require a native Apple Silicon host")
    if bool(mac_sign_identity) != bool(mac_bundle_id) or (mac_notary_profile and not mac_sign_identity):
        raise ValueError("Mac signing needs both a Developer ID Application identity and bundle ID; notarization also needs signing")
    if mac_sign_identity:
        validate_mac_signing(tag, mac_sign_identity, mac_bundle_id)
        check_mac_signing_identity(mac_sign_identity)
    output_root = Path(output_root).absolute()
    name = f"videomate-{__version__}-{tag}-desktop"
    if ((output_root / name).exists() or (output_root / (name + ".zip")).exists()
            or (output_root / (name + ".zip.sha256")).exists()):
        raise ValueError("Release destination already exists; existing artifacts were preserved")
    base_python = build_python(tag, offline)
    ensure_ffmpeg(base_python, tag, offline)
    python = build_environment(base_python, tag, offline=offline, wheelhouse=wheelhouse)
    command = [python, ROOT / "tools/build_desktop.py", "--output-root", output_root]
    if mac_sign_identity:
        command += ["--mac-sign-identity", mac_sign_identity, "--mac-bundle-id", mac_bundle_id]
    run(command)
    if mac_notary_profile:
        run([python, ROOT / "tools/build_macos_dmg.py", "--desktop-dir", output_root / name,
             "--sign-identity", mac_sign_identity, "--notary-profile", mac_notary_profile])
    if tag.startswith("linux-") and appimage:
        command = [python, ROOT / "tools/build_linux_appimage.py", "--desktop-dir", output_root / name,
                   "--output-root", output_root]
        if offline:
            command.append("--offline")
        run(command)
    print(f"Local {tag} build passed packaged generated-media checks. Publish only after native platform review.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "dist")
    parser.add_argument("--offline", action="store_true", help="Use cached pinned dependencies and an optional wheelhouse only")
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--no-appimage", action="store_true", help="Build Linux desktop ZIP only")
    parser.add_argument("--mac-sign-identity", help="Developer ID Application identity already available to codesign")
    parser.add_argument("--mac-bundle-id", help="Approved reverse-DNS identifier for the signed Mac app")
    parser.add_argument("--mac-notary-profile", help="Existing notarytool keychain profile; signs, notarizes and staples a DMG")
    args = parser.parse_args()
    build(args.output_root, offline=args.offline, wheelhouse=args.wheelhouse, appimage=not args.no_appimage,
          mac_sign_identity=args.mac_sign_identity, mac_bundle_id=args.mac_bundle_id,
          mac_notary_profile=args.mac_notary_profile)
