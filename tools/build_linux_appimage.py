"""Turn a locally tested Linux desktop build into a pinned, offline AppImage.

Only public software is read. AppImage tooling is pinned to immutable releases;
--offline uses verified cached copies. Run on the matching native Linux CPU.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from videomate import __version__
from videomate.dependencies import platform_tag


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def pinned_tool(spec, *, offline):
    cache = ROOT / "dependencies/devtools/appimage"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / spec["filename"]
    if not target.exists():
        if offline:
            raise ValueError("Pinned AppImage build tool is not cached; supply it before an offline build")
        part = cache / (spec["filename"] + ".part")
        with part.open("xb") as output:
            try:
                request = urllib.request.Request(spec["url"], headers={"User-Agent": "VideoMate release builder"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    if not response.geturl().startswith("https://"):
                        raise ValueError("HTTPS required for public build tooling")
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > 32 * 1024 * 1024:
                            raise ValueError("AppImage build tool exceeds size limit")
                        output.write(chunk)
                if digest(part) != spec["sha256"]:
                    raise ValueError("AppImage build tool checksum mismatch")
                part.rename(target)
            finally:
                if part.exists():
                    part.unlink()
    if not target.is_file() or target.is_symlink() or digest(target) != spec["sha256"]:
        raise ValueError("Pinned AppImage build tool checksum mismatch")
    target.chmod(0o755)
    return target


def check_desktop(directory, tag):
    if directory.name != f"videomate-{__version__}-{tag}-desktop":
        raise ValueError("Expected the current version's native Linux desktop build")
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Expected a local desktop build directory")
    manifest_path = directory / "package-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Desktop build manifest is invalid")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("app_version") != __version__ or manifest.get("platform") != tag:
        raise ValueError("Desktop build metadata does not match this host")
    files = manifest.get("files")
    if not isinstance(files, dict) or "synthetic-test-results.json" not in files or len(files) > 20000:
        raise ValueError("Desktop build manifest is invalid")
    for relative, expected in files.items():
        if (not isinstance(relative, str) or not relative or "\\" in relative
                or ".." in Path(relative).parts or Path(relative).is_absolute()
                or not re.fullmatch(r"[0-9a-f]{64}", str(expected))):
            raise ValueError("Desktop build file checksum mismatch")
        path = directory / relative
        if (path.is_symlink() or not path.resolve().is_relative_to(directory.resolve())
                or not path.is_file() or digest(path) != expected):
            raise ValueError("Desktop build file checksum mismatch")
    report = json.loads((directory / "synthetic-test-results.json").read_text(encoding="utf-8"))
    checks = report.get("checks")
    if (report.get("status") != "passed" or report.get("synthetic_only") is not True
            or not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values())):
        raise ValueError("Desktop build did not pass generated-media checks")
    executable = directory / "VideoMate/VideoMate"
    if ((directory / "VideoMate").is_symlink() or executable.is_symlink()
            or not executable.is_file() or not os.access(executable, os.X_OK)):
        raise ValueError("Native Linux desktop executable is missing")
    for entry in directory.rglob("*"):
        relative = entry.relative_to(directory).as_posix()
        if entry.is_symlink():
            try:
                resolved = entry.resolve(strict=True)
            except (OSError, RuntimeError):
                raise ValueError("Desktop build contains an invalid software link") from None
            if not resolved.is_relative_to(directory.resolve()) or relative.split("/", 1)[0] != "VideoMate":
                raise ValueError("Desktop build contains an external software link")
        elif entry.is_file() and relative != "package-manifest.json" and relative not in files:
            raise ValueError("Desktop build contains an unlisted file")


def build(desktop, output_root, *, offline=False):
    tag = platform_tag()
    if tag not in {"linux-x86_64", "linux-arm64"}:
        raise ValueError("AppImages must be built on a matching native Linux host")
    desktop = Path(desktop).absolute()
    output_root = Path(output_root).absolute()
    check_desktop(desktop, tag)
    catalog = json.loads((ROOT / "dependencies/appimage-sources.json").read_text(encoding="utf-8"))
    tools = catalog["platforms"][tag]
    appimagetool = pinned_tool(tools["appimagetool"], offline=offline)
    runtime = pinned_tool(tools["runtime"], offline=offline)
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / f"videomate-{__version__}-{tag}.AppImage"
    if output.exists() or output.with_suffix(".AppImage.sha256").exists():
        raise ValueError("AppImage destination already exists; it was not replaced")
    with tempfile.TemporaryDirectory(prefix="videomate-appimage-") as temporary:
        stage = Path(temporary)
        appdir = stage / "VideoMate.AppDir"
        program = appdir / "usr/lib/videomate"
        program.mkdir(parents=True)
        shutil.copytree(desktop / "VideoMate", program / "VideoMate", symlinks=True)
        docs = appdir / "usr/share/doc/videomate"
        docs.mkdir(parents=True)
        for name in ("START-HERE.txt", "README.md", "THIRD_PARTY_NOTICES.md", "package-manifest.json", "synthetic-test-results.json"):
            shutil.copyfile(desktop / name, docs / name)
        shutil.copytree(desktop / "docs", docs / "docs")
        shutil.copytree(desktop / "assets", docs / "assets")
        icon = ROOT / "assets/videomate-mark.png"
        shutil.copyfile(icon, appdir / "videomate.png")
        shutil.copyfile(icon, appdir / ".DirIcon")
        (appdir / "videomate.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=VideoMate\nComment=Offline video integrity and recovery\n"
            "Exec=VideoMate\nIcon=videomate\nCategories=AudioVideo;Video;\nTerminal=false\n", encoding="utf-8")
        run = appdir / "AppRun"
        run.write_text('#!/bin/sh\nHERE=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd -P)\n'
                       'exec "$HERE/usr/lib/videomate/VideoMate/VideoMate" "$@"\n', encoding="utf-8")
        run.chmod(0o755)
        environment = os.environ.copy()
        environment["ARCH"] = "x86_64" if tag.endswith("x86_64") else "aarch64"
        environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"  # Works on build hosts without FUSE.
        try:
            subprocess.run([str(appimagetool), "--runtime-file", str(runtime), str(appdir), str(output)],
                           check=True, timeout=600, cwd=stage, env=environment)
            if not output.is_file():
                raise ValueError("AppImage tool returned without an artifact")
            subprocess.run([str(output), "--check"], check=True, timeout=120, cwd=stage, env=environment)
            report = stage / "appimage-self-test.json"
            subprocess.run([str(output), "--self-test", str(report)], check=True, timeout=300, cwd=stage, env=environment)
            if json.loads(report.read_text(encoding="utf-8")).get("status") != "passed":
                raise ValueError("AppImage generated-media self-test failed")
            output.with_suffix(".AppImage.sha256").write_text(digest(output) + "\n", encoding="ascii")
        except BaseException:
            if output.exists():
                output.unlink()  # Exact artifact created by this invocation only.
            raise
    print("Built and tested " + output.name)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "dist")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    build(args.desktop_dir, args.output_root, offline=args.offline)
