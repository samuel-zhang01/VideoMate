"""Explicit dependency provisioning. Never imported by the offline application.

Windows x64/ARM64, Apple Silicon and Linux: pinned downloads or offline archives.
Alternative builds can be imported using explicit binary hashes.
No system install, PATH changes, media discovery or backend execution occurs.
"""

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import urllib.request
import zipfile
import platform
import struct
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ("windows-x86_64", "windows-arm64", "macos-x86_64", "macos-arm64", "linux-x86_64", "linux-arm64")
MAX_ARCHIVE = 512 * 1024 * 1024


def native_platform():
    system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(platform.system())
    arch = {"AMD64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine())
    if not system or not arch:
        raise ValueError("Unsupported native platform")
    return system + "-" + arch


def install_native_assets(spec, stage, args):
    cache = ROOT / "dependencies" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    if args.archive:
        raise ValueError("Use --archive-directory for the two pinned native archives")
    for asset in spec["assets"]:
        name = asset["name"]
        if name not in {"ffmpeg", "ffprobe"}:
            raise ValueError("Unexpected backend asset")
        filename = name + "-" + args.platform + "-" + spec["version"] + ".zip"
        supplied = getattr(args, "archive_directory", None)
        archive = Path(supplied) / filename if supplied else cache / filename
        if not archive.exists() and not supplied:
            if getattr(args, "offline", False):
                raise ValueError("Pinned archive is not cached. Supply --archive-directory or explicitly use online setup")
            part = archive.with_suffix(".zip.part")
            owned = False
            try:
                with part.open("xb") as output:
                    owned = True
                    request = urllib.request.Request(asset["url"], headers={"User-Agent": "VideoMate dependency setup/0.4"})
                    with urllib.request.urlopen(request, timeout=60) as response:
                        if not response.geturl().startswith("https://"):
                            raise ValueError("HTTPS required")
                        total = 0
                        while chunk := response.read(1024 * 1024):
                            total += len(chunk)
                            if total > MAX_ARCHIVE:
                                raise ValueError("Archive exceeds limit")
                            output.write(chunk)
                if digest(part) != checked_digest(asset["sha256"]):
                    raise ValueError("Archive checksum mismatch")
                part.rename(archive)
            except BaseException:
                if owned and part.is_file():
                    part.unlink()
                raise
        if not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE or digest(archive) != checked_digest(asset["sha256"]):
            raise ValueError("Archive checksum mismatch")
        with zipfile.ZipFile(archive) as package:
            matches = [info for info in package.infolist() if PurePosixPath(info.filename).name == name
                       and ".." not in PurePosixPath(info.filename).parts and not PurePosixPath(info.filename).is_absolute()
                       and not info.is_dir() and info.file_size <= MAX_ARCHIVE]
            if len(matches) != 1:
                raise ValueError("Expected one native tool")
            target = stage / "bin" / name
            with package.open(matches[0]) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            with target.open("rb") as binary:
                header = binary.read(20)
            if args.platform == "macos-arm64":
                if header[:8] != bytes.fromhex("cffaedfe0c000001"):
                    raise ValueError("Expected an Apple Silicon Mach-O executable")
            else:
                machine = {"linux-x86_64": 62, "linux-arm64": 183}[args.platform]
                if len(header) < 20 or header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 18)[0] != machine:
                    raise ValueError("Expected a native 64-bit Linux ELF executable for the selected architecture")
            target.chmod(0o755)
        print("Verified " + args.platform + " " + name + ".", flush=True)
    shutil.copyfile(ROOT / "dependencies" / "licenses" / "ffmpeg-GPLv3.txt", stage / "LICENSE.txt")
    (stage / "README.txt").write_text("FFmpeg/FFprobe static release by Martin Riedl.\nSource/build information: " + spec["source_url"] + "\n", encoding="utf-8")


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def checked_digest(value):
    if not re.fullmatch(r"[a-fA-F0-9]{64}", value or ""):
        raise ValueError("An explicit SHA-256 digest is required")
    return value.lower()


def install(args):
    if args.platform not in PLATFORMS:
        raise ValueError("Unsupported platform")
    parent = ROOT / "dependencies" / "ffmpeg"
    parent.mkdir(parents=True, exist_ok=True)
    lock = parent / (".install-" + args.platform + ".lock")
    # Exclusive, per-platform lock. Never remove another installer's lock.
    handle = lock.open("x", encoding="ascii")
    try:
        _install(args)
    finally:
        handle.close()
        lock.unlink()


def _install(args):
    parent = ROOT / "dependencies" / "ffmpeg"
    destination = parent / args.platform
    if destination.exists():
        raise ValueError("Platform bundle already exists; no files were replaced")
    parent.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((ROOT / "dependencies" / "sources.json").read_text(encoding="utf-8"))
    binaries = {}
    archive_hash, source_label = None, "operator-supplied native binary bundle"
    with tempfile.TemporaryDirectory(prefix=".install-", dir=parent) as temporary:
        stage = Path(temporary)
        (stage / "bin").mkdir()
        if args.import_directory:
            if args.archive or getattr(args, "archive_directory", None) or not re.fullmatch(r"\d{1,4}\.\d{1,4}(?:\.\d{1,4})?", args.version or ""):
                raise ValueError("Native imports require a numeric --version and no --archive")
            version = args.version
            supplied = Path(args.import_directory)
            suffix = ".exe" if args.platform.startswith("windows-") else ""
            for name, expected in (("ffmpeg", args.ffmpeg_sha256), ("ffprobe", args.ffprobe_sha256)):
                source = supplied / (name + suffix)
                if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_ARCHIVE or digest(source) != checked_digest(expected):
                    raise ValueError("Native binary hash or file check failed")
                target = stage / "bin" / source.name
                shutil.copyfile(source, target)
                if suffix == "":
                    target.chmod(0o755)
            if not args.license_file:
                raise ValueError("Native imports require the accompanying --license-file")
            shutil.copyfile(args.license_file, stage / "LICENSE.txt")
        elif args.platform in {"macos-arm64", "linux-x86_64", "linux-arm64"}:
            spec = catalog[args.platform]
            version, source_label = spec["version"], spec["publisher"]
            install_native_assets(spec, stage, args)
        else:
            spec = catalog.get(args.platform)
            if not isinstance(spec, dict):
                raise ValueError("No download is pinned for this platform; use a verified native import")
            version, archive_hash, source_label = spec["version"], checked_digest(spec["sha256"]), spec["url"]
            if args.archive:
                archive = Path(args.archive)
            else:
                if getattr(args, "archive_directory", None):
                    raise ValueError("Windows takes --archive, not --archive-directory")
                cache = ROOT / "dependencies" / "cache"
                cache.mkdir(parents=True, exist_ok=True)
                archive = cache / ("ffmpeg-" + args.platform + "-" + version + ".zip")
                if not archive.exists():
                    if getattr(args, "offline", False):
                        raise ValueError("Pinned archive is not cached. Supply --archive or explicitly use online setup")
                    part = cache / (archive.name + ".part")
                    print("Downloading the pinned public FFmpeg archive; no media is involved.", flush=True)
                    owns_partial = False
                    try:
                        with part.open("xb") as output:
                            owns_partial = True
                            with urllib.request.urlopen(source_label, timeout=60) as response:
                                if not response.geturl().startswith("https://"):
                                    raise ValueError("Dependency download requires HTTPS")
                                total = 0
                                while chunk := response.read(1024 * 1024):
                                    total += len(chunk)
                                    if total > MAX_ARCHIVE:
                                        raise ValueError("Archive exceeds the download limit")
                                    output.write(chunk)
                        if digest(part) != archive_hash:
                            raise ValueError("Archive SHA-256 differs from the pinned publisher checksum")
                        part.rename(archive)
                    except BaseException:
                        # Only this exact installer-owned partial download is removed.
                        if owns_partial and part.is_file():
                            part.unlink()
                        raise
            if not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE or digest(archive) != archive_hash:
                raise ValueError("Archive SHA-256 check failed")
            print("Archive checksum verified. Extracting the two processing tools and license.", flush=True)
            with zipfile.ZipFile(archive) as package:
                license_name = "LICENSE.txt" if args.platform == "windows-arm64" else "LICENSE"
                wanted_names = ("ffmpeg.exe", "ffprobe.exe", license_name)
                if args.platform == "windows-x86_64":
                    wanted_names += ("README.txt",)
                for wanted in wanted_names:
                    matches = [i for i in package.infolist() if PurePosixPath(i.filename).name == wanted
                               and not i.is_dir() and ".." not in PurePosixPath(i.filename).parts
                               and not PurePosixPath(i.filename).is_absolute()]
                    if len(matches) != 1:
                        raise ValueError("Archive does not have exactly one required member")
                    info = matches[0]
                    if info.file_size > MAX_ARCHIVE:
                        raise ValueError("Archive member exceeds the extraction limit")
                    target = stage / "bin" / wanted if wanted.endswith(".exe") else stage / wanted
                    with package.open(info) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
            if args.platform == "windows-arm64":
                # A checksum alone cannot detect a mislabeled architecture.
                for name in ("ffmpeg.exe", "ffprobe.exe"):
                    with (stage / "bin" / name).open("rb") as binary:
                        header = binary.read(512)
                    if len(header) < 64 or header[:2] != b"MZ":
                        raise ValueError("Expected a Windows ARM64 PE executable")
                    pe_offset = struct.unpack_from("<I", header, 60)[0]
                    if pe_offset + 6 > len(header) or header[pe_offset:pe_offset + 4] != b"PE\0\0" or struct.unpack_from("<H", header, pe_offset + 4)[0] != 0xAA64:
                        raise ValueError("Expected a Windows ARM64 PE executable")
                (stage / "README.txt").write_text("FFmpeg/FFprobe ARM64 GPL build by BtbN.\nSource/build information: " + spec["source_url"] + "\n", encoding="utf-8")
        suffix = ".exe" if args.platform.startswith("windows-") else ""
        for name in ("ffmpeg", "ffprobe"):
            file = stage / "bin" / (name + suffix)
            binaries[name] = {"file": "bin/" + file.name, "sha256": digest(file)}
        manifest = {"schema_version": 1, "platform": args.platform, "version": version,
                    "source": source_label, "archive_sha256": archive_hash, "binaries": binaries}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        # Destination is new. Stage and destination are on the same filesystem.
        stage.rename(destination)
    print("Installed dependencies/ffmpeg/" + args.platform + "; no system settings changed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default=native_platform(), choices=PLATFORMS)
    parser.add_argument("--archive", help="Offline archive matching the pinned catalog checksum")
    parser.add_argument("--archive-directory", help="Offline directory containing both pinned macOS/Linux archives")
    parser.add_argument("--offline", action="store_true", help="Never use the network; use only supplied or cached archives")
    parser.add_argument("--import-directory", help="Native directory containing ffmpeg and ffprobe")
    parser.add_argument("--version")
    parser.add_argument("--ffmpeg-sha256")
    parser.add_argument("--ffprobe-sha256")
    parser.add_argument("--license-file")
    try:
        install(parser.parse_args())
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        # This standalone installer handles public software, never media or keys.
        print("Dependency installation failed: " + str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
