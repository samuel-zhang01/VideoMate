"""Offline, platform-specific native bundle resolution. Never downloads."""

import hashlib
import json
import platform
import re
import sys
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path

from .errors import VideoMateError
from .policy import plain_local_path


def platform_tag() -> str:
    system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(platform.system())
    # On Windows ARM, an emulated x64 Python can report the ARM host machine.
    # Its frozen bootloader and dependencies must follow the interpreter ABI.
    machine_name = sysconfig.get_platform().lower() if system == "windows" else platform.machine().lower()
    machine = {"win-amd64": "x86_64", "win-arm64": "arm64", "amd64": "x86_64",
               "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(machine_name)
    if not system or not machine:
        raise VideoMateError("dependency_unavailable")
    return system + "-" + machine


def default_root() -> Path:
    if getattr(sys, "frozen", False):
        # Canonicalize only the trusted software location. PyInstaller macOS apps
        # use internal symlinks between Frameworks and Resources; media rules stay strict.
        return (Path(sys._MEIPASS) / "dependencies" / "ffmpeg").resolve()
    location = Path(__file__).absolute()
    archive = next((p for p in location.parents if p.suffix == ".pyz"), None)
    if archive:
        root = archive.parent.parent if archive.parent.name == "dist" else archive.parent
    else:
        root = location.parents[2]
    return root / "dependencies" / "ffmpeg"


@dataclass(frozen=True)
class Bundle:
    ffmpeg: Path = field(repr=False)
    ffprobe: Path = field(repr=False)
    version: str
    platform: str
    digest: str = ""


def load_bundle(root: Path | None = None, *, for_platform: str | None = None) -> Bundle:
    tag = for_platform or platform_tag()
    if tag not in {"windows-x86_64", "windows-arm64", "macos-arm64", "macos-x86_64", "linux-x86_64", "linux-arm64"}:
        raise VideoMateError("dependency_unavailable")
    directory = (root or default_root()).absolute() / tag
    try:
        def software_path(path):
            if root is None and getattr(sys, "frozen", False):
                # macOS app bundles cross-link DATA and BINARY directories.
                # Resolve these software-only links within the application;
                # supplied tool bundles and all media keep the strict rule.
                path = path.resolve(strict=True)
                package = Path(sys._MEIPASS).resolve().parent
                if not path.is_relative_to(package):
                    raise ValueError()
            return plain_local_path(path)

        manifest_file = software_path(directory / "manifest.json")
        if manifest_file.stat().st_size > 16384:
            raise ValueError()
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if manifest["schema_version"] != 1 or manifest["platform"] != tag:
            raise ValueError()
        version = manifest["version"]
        if not isinstance(version, str) or not re.fullmatch(r"\d{1,4}\.\d{1,4}(?:\.\d{1,4})?", version):
            raise ValueError()
        suffix = ".exe" if tag.startswith("windows-") else ""
        paths = {}
        for name in ("ffmpeg", "ffprobe"):
            metadata = manifest["binaries"][name]
            relative = "bin/" + name + suffix
            if metadata["file"] != relative or not re.fullmatch(r"[a-f0-9]{64}", metadata["sha256"]):
                raise ValueError()
            path = software_path(directory / "bin" / (name + suffix))
            if not path.is_file() or path.stat().st_size > 512 * 1024 * 1024:
                raise ValueError()
            with path.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != metadata["sha256"]:
                    raise ValueError()
            paths[name] = path
        return Bundle(paths["ffmpeg"], paths["ffprobe"], version, tag, manifest["binaries"]["ffmpeg"]["sha256"])
    except (OSError, ValueError, TypeError, KeyError, VideoMateError):
        raise VideoMateError("dependency_unavailable") from None
