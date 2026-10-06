"""Build a native desktop on Windows, Linux, or Apple Silicon; public software only.

Provision FFmpeg first. No network access is performed here. For an offline build,
install requirements-build.txt from a predownloaded platform-specific wheelhouse.
The output includes Python, Tcl/Tk, FFmpeg, FFprobe and their collected licenses.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from videomate import __version__
from videomate.dependencies import load_bundle, platform_tag
from videomate.setup_local import check_backend


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def test_environment():
    # Deliberately exclude Python/Conda/Tcl overrides and non-system PATH entries.
    # A Linux GUI needs its host display socket; these are build-host controls,
    # not media or runtime workspace paths.
    result = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "TMPDIR",
                                              "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XAUTHORITY")
              if name in os.environ}
    result["PATH"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32") if os.name == "nt" else "/usr/bin:/bin"
    return result


def find_python_license(prefix, stdlib):
    # Framework/Unix builds keep this beside the standard library; Windows
    # distributions commonly put it at sys.base_prefix instead.
    for directory in (Path(prefix), Path(stdlib)):
        for name in ("LICENSE.txt", "LICENSE_PYTHON.txt", "LICENSE"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
    raise SystemExit("The build runtime must supply its Python license file.")


def validate_mac_signing(tag, identity, bundle_id):
    if not identity and not bundle_id:
        return
    if tag != "macos-arm64" or not identity or not bundle_id:
        raise ValueError("Mac signing needs a native Apple Silicon host, identity and bundle ID")
    mac_signing_team(identity)
    if len(bundle_id) > 255 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z][A-Za-z0-9-]*)+", bundle_id):
        raise ValueError("Use an approved reverse-DNS Mac bundle ID")


def mac_signing_team(identity):
    if not isinstance(identity, str) or any(character in identity for character in "\r\n\0"):
        raise ValueError("A full Developer ID Application identity with Apple team ID is required")
    match = re.fullmatch(r"Developer ID Application: .+ \(([A-Z0-9]{10})\)", identity)
    if not match:
        raise ValueError("A full Developer ID Application identity with Apple team ID is required")
    return match.group(1)


def check_mac_signing_identity(identity):
    """Fail before packaging when the selected signing identity is unavailable."""
    if not identity:
        return
    mac_signing_team(identity)
    result = subprocess.run(["/usr/bin/security", "find-identity", "-v", "-p", "codesigning"],
                            text=True, capture_output=True)
    labels = re.findall(r'^\s*\d+\) [0-9a-fA-F]{40} "([^"]+)"\s*$', result.stdout, re.MULTILINE)
    if result.returncode or identity not in labels:
        raise ValueError("Selected Developer ID Application signing identity is not available in Keychain")


def verify_mac_signature(path, *, signed):
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(path)],
                   check=True, stdout=subprocess.DEVNULL)
    if signed:
        result = subprocess.run(["/usr/bin/codesign", "--display", "--verbose=2", str(path)],
                                check=True, text=True, capture_output=True)
        details = result.stdout + result.stderr
        team = re.search(r"^TeamIdentifier=([A-Z0-9]{10})$", details, re.MULTILINE)
        if "Signature=adhoc" in details or not team:
            raise ValueError("Mac distribution signature has no Apple team identifier")
        if not re.search(r"^flags=.*\(runtime\)", details, re.MULTILINE):
            raise ValueError("Mac distribution signature lacks hardened runtime")
        if not re.search(r"^Timestamp=.+$", details, re.MULTILINE):
            raise ValueError("Mac distribution signature lacks a secure timestamp")
        return team.group(1)
    return None


def build(output_root=None, *, mac_sign_identity=None, mac_bundle_id=None):
    tag = platform_tag()
    if tag not in {"windows-x86_64", "windows-arm64", "macos-arm64", "linux-x86_64", "linux-arm64"}:
        raise SystemExit("Build on a supported native 64-bit host. Cross-compilation is not supported.")
    validate_mac_signing(tag, mac_sign_identity, mac_bundle_id)
    check_mac_signing_identity(mac_sign_identity)
    check_backend()
    bundle = load_bundle()
    destination = (Path(output_root) if output_root else ROOT / "dist") / ("videomate-" + __version__ + "-" + tag + "-desktop")
    archive = destination.with_name(destination.name + ".zip")
    if destination.exists() or archive.exists() or archive.with_suffix(".zip.sha256").exists():
        raise SystemExit("Release destination already exists; it was not replaced.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="videomate-desktop-build-") as temporary:
        stage = Path(temporary).resolve()
        software = stage / "software"
        software.mkdir()
        licenses = stage / "licenses"
        licenses.mkdir()
        python_license = find_python_license(sys.base_prefix, sysconfig.get_path("stdlib"))
        shutil.copyfile(python_license, licenses / "Python-LICENSE.txt")
        shutil.copyfile(ROOT / "tools/tcl-license.txt", licenses / "Tcl-license.terms")
        shutil.copyfile(ROOT / "tools/tk-license.txt", licenses / "Tk-license.terms")
        pyinstaller = importlib.metadata.distribution("pyinstaller")
        for file in pyinstaller.files:
            if str(file).endswith("licenses/COPYING.txt"):
                shutil.copyfile(pyinstaller.locate_file(file), licenses / "PyInstaller-COPYING.txt")
        # Include only the exact selected public dependency directory.
        shutil.copytree(bundle.ffmpeg.parent.parent, software / tag)
        args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed", "--noupx",
                "--name", "VideoMate", "--paths", str(ROOT / "src"), "--distpath", str(stage / "dist"),
                "--workpath", str(stage / "work"), "--specpath", str(stage),
                "--add-data", str(software) + ":dependencies/ffmpeg", "--add-data", str(licenses) + ":licenses",
                "--add-data", str(ROOT / "assets/videomate-mark.png") + ":assets"]
        # schema.py prefers the packaged export-schema.json. Supply that exact name.
        shutil.copyfile(ROOT / "schemas" / "diagnostic-export-v1.schema.json", stage / "export-schema.json")
        args += ["--add-data", str(stage / "export-schema.json") + ":videomate"]
        if tag == "macos-arm64":
            args += ["--target-arch", "arm64", "--osx-bundle-identifier", mac_bundle_id or "local.videomate.desktop",
                     "--icon", str(ROOT / "assets/videomate.icns")]
            if mac_sign_identity:
                # PyInstaller signs every collected Mach-O after rewriting load paths.
                args += ["--codesign-identity", mac_sign_identity]
        elif tag.startswith("windows-"):
            args += ["--manifest", str(ROOT / "tools/windows.manifest"), "--icon", str(ROOT / "assets/videomate.ico")]
        args.append(str(ROOT / "tools" / "desktop_entry.py"))
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        if tag.startswith("windows-"):
            # A venv can be backed by Anaconda. Help the build-time DLL resolver
            # collect that runtime's libraries; the finished app needs no Conda.
            environment["PATH"] = os.pathsep.join([str(Path(sys.base_prefix) / "Library/bin"),
                                                  str(Path(sys.base_prefix) / "DLLs"), environment.get("PATH", "")])
        subprocess.run(args, check=True, cwd=ROOT, env=environment)
        built = stage / "dist" / ("VideoMate.app" if tag == "macos-arm64" else "VideoMate")
        if tag == "macos-arm64":
            # Native bundling can rewrite Mach-O signatures. Record the resulting
            # software hashes, then re-sign only the outer app resource seal.
            native = (built / "Contents/Resources/dependencies/ffmpeg" / tag).resolve()
            manifest = json.loads((native / "manifest.json").read_text(encoding="utf-8"))
            for name in ("ffmpeg", "ffprobe"):
                manifest["binaries"][name]["sha256"] = digest(native / "bin" / name)
            (native / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            sign_command = ["/usr/bin/codesign", "--force", "--sign", mac_sign_identity or "-"]
            if mac_sign_identity:
                sign_command += ["--options", "runtime", "--timestamp"]
            subprocess.run(sign_command + [str(built)], check=True)
            team = verify_mac_signature(built, signed=bool(mac_sign_identity))
            if mac_sign_identity:
                for name in ("ffmpeg", "ffprobe"):
                    if verify_mac_signature(native / "bin" / name, signed=True) != team:
                        raise ValueError("Packaged FFmpeg tool is signed by a different Apple team")
        executable = built / ("Contents/MacOS/VideoMate" if tag == "macos-arm64" else
                              "VideoMate.exe" if tag.startswith("windows-") else "VideoMate")
        report = stage / "desktop-self-test.json"
        subprocess.run([str(executable), "--self-test", str(report)], check=True, timeout=240, cwd=stage, env=test_environment())
        evidence = json.loads(report.read_text(encoding="utf-8"))
        if evidence.get("status") != "passed":
            raise SystemExit("The bundled desktop did not pass its generated-media GUI test.")
        destination.mkdir()
        shutil.copytree(built, destination / built.name, symlinks=True)
        shutil.copyfile(report, destination / "synthetic-test-results.json")
        from release_documents import source_documents
        for file in (*source_documents(ROOT), "dependencies/sources.json", "dependencies/python-sources.json",
                     "dependencies/appimage-sources.json", "dependencies/runtime-bootstrap.tsv",
                     "dependencies/licenses/ffmpeg-GPLv3.txt", "schemas/diagnostic-export-v1.schema.json",
                     "examples/diagnostic-export.synthetic.json"):
            target = destination / file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / file, target)
        brand_assets = destination / "assets"
        brand_assets.mkdir(parents=True, exist_ok=True)
        for name in ("videomate-mark.svg", "videomate-mark.png"):
            shutil.copyfile(ROOT / "assets" / name, brand_assets / name)
        launcher_name = "start.bat" if tag.startswith("windows-") else "start.sh"
        shutil.copyfile(ROOT / "tools" / ("desktop-" + launcher_name), destination / launcher_name)
        if not tag.startswith("windows-"):
            (destination / launcher_name).chmod(0o755)
        if tag == "macos-arm64":
            shutil.copyfile(ROOT / "start.command", destination / "start.command")
            (destination / "start.command").chmod(0o755)
        notice = ("VideoMate " + __version__ + " — offline desktop\n\n"
                  "Extract the entire package. Open start.bat on Windows, start.command on Apple Silicon, or ./start.sh on Linux.\n"
                  "Python, Tcl/Tk, FFmpeg and FFprobe are included. No installation, PATH changes or runtime internet required.\n"
                  "Sensitive: Yes is the default; see docs/settings-and-privacy.md for the exact behaviour.\n"
                  + ("This ZIP is Developer ID signed, but not notarized. Use the separately notarized DMG for Gatekeeper distribution.\n"
                     if mac_sign_identity else
                     "The package is not publisher-signed/notarized. See docs/desktop.md for platform limitations and provenance.\n"))
        (destination / "START-HERE.txt").write_text(notice, encoding="utf-8")
        # These paths are solely this newly built software tree, never media or workspaces.
        hashes = {file.relative_to(destination).as_posix(): digest(file) for file in destination.rglob("*")
                  if file.is_file() and not file.is_symlink()}
        (destination / "package-manifest.json").write_text(json.dumps({"app_version": __version__, "platform": tag,
                     "python_included": True, "ffmpeg_version": bundle.version, "files": hashes}, indent=2), encoding="utf-8")
        if tag == "macos-arm64":
            # ditto preserves the internal app symlinks and executable permission bits.
            subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(destination), str(archive)], check=True)
        else:
            with archive.open("xb") as output, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as package:
                for file in destination.rglob("*"):
                    if file.is_file():
                        package.write(file, str(Path(destination.name) / file.relative_to(destination)))
        extracted = stage / "extracted"
        extracted.mkdir()
        if tag == "macos-arm64":
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), str(extracted)], check=True)
        else:
            with zipfile.ZipFile(archive) as package:
                package.extractall(extracted)  # This exact archive was just built from our software tree.
                if tag.startswith("linux-"):
                    for member in package.infolist():
                        if not member.is_dir():
                            (extracted / member.filename).chmod((member.external_attr >> 16) & 0o777 or 0o644)
        relocated = extracted / destination.name / built.name
        relocated_exe = relocated / ("Contents/MacOS/VideoMate" if tag == "macos-arm64" else
                                     "VideoMate.exe" if tag.startswith("windows-") else "VideoMate")
        launcher = extracted / destination.name / launcher_name
        command = [str(launcher), "--check"] if os.name == "nt" else ["/bin/sh", str(launcher), "--check"]
        subprocess.run(command, shell=os.name == "nt", check=True, timeout=60, cwd=stage, env=test_environment())
        second_report = stage / "extracted-self-test.json"
        subprocess.run([str(relocated_exe), "--self-test", str(second_report)], check=True, timeout=240, cwd=stage, env=test_environment())
        if json.loads(second_report.read_text(encoding="utf-8")).get("status") != "passed":
            raise SystemExit("Extracted package did not pass its generated-media GUI test.")
        if tag == "macos-arm64":
            verify_mac_signature(relocated, signed=bool(mac_sign_identity))
        archive.with_suffix(".zip.sha256").write_text(digest(archive) + "\n", encoding="ascii")
    print("Built and tested " + archive.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, help="New release directory (defaults to dist); existing artifacts are never overwritten")
    parser.add_argument("--mac-sign-identity", help="Developer ID Application identity already available to codesign")
    parser.add_argument("--mac-bundle-id", help="Approved reverse-DNS identifier for the signed Mac app")
    args = parser.parse_args()
    build(args.output_root, mac_sign_identity=args.mac_sign_identity, mac_bundle_id=args.mac_bundle_id)
