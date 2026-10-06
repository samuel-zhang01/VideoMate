"""Package public application/software files only. No media discovery or downloads.

A compatible Python is required unless --include-runtime bundles Python/Tk.
This development kit is not a signed, self-contained production release.
"""
import argparse
import hashlib
import json
import shutil
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from videomate import __version__
from videomate.dependencies import load_bundle


def build(destination, platform=None, include_runtime=False):
    bundle = load_bundle(for_platform=platform)
    directory = bundle.ffmpeg.parent.parent
    selected = [(ROOT / "dist" / "videomate.pyz", "videomate.pyz")]
    from release_documents import source_documents
    selected += [(ROOT / name, name) for name in source_documents(ROOT)]
    for name in ("manifest.json", "bin/ffmpeg.exe", "bin/ffprobe.exe", "bin/ffmpeg", "bin/ffprobe", "LICENSE", "LICENSE.txt", "README.txt"):
        source = directory / name
        if source.is_file():
            selected.append((source, "dependencies/ffmpeg/" + bundle.platform + "/" + name))
    for name in ("assets/videomate-mark.png", "assets/videomate-mark.svg", "start.bat", "start.sh", "start.command",
                 "tools/bootstrap.py", "tools/install_ffmpeg.py", "tools/install_python.py", "tools/bootstrap_runtime.sh", "tools/bootstrap_runtime.ps1", "dependencies/runtime-bootstrap.tsv",
                 "dependencies/sources.json", "dependencies/python-sources.json", "dependencies/appimage-sources.json",
                 "dependencies/licenses/ffmpeg-GPLv3.txt",
                 "schemas/diagnostic-export-v1.schema.json", "examples/diagnostic-export.synthetic.json"):
        selected.append((ROOT / name, name))
    if include_runtime:
        from install_python import verify, runtime_path
        verify(bundle.platform)
        runtime = runtime_path(bundle.platform)
        # This exact directory contains provisioned public software, never media.
        for source in sorted(runtime.rglob("*")):
            if source.is_symlink():
                raise ValueError("Runtime links must be materialized before packaging")
            if source.is_file() and "__pycache__" not in source.parts and source.suffix != ".pyc":
                selected.append((source, "dependencies/python/" + bundle.platform + "/" + source.relative_to(runtime).as_posix()))
    hashes = {}
    # Exclusive creation; never replace an existing release or unrelated file.
    with destination.open("xb") as output, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for source, name in selected:
            with source.open("rb") as file:
                hashes[name] = hashlib.file_digest(file, "sha256").hexdigest()
            if name.endswith(("/bin/ffmpeg", "/bin/ffprobe", ".sh", ".command")) or (name.startswith("dependencies/python/") and source.stat().st_mode & 0o111):
                # A Windows host preparing a Mac kit must retain Unix execution
                # permissions for Finder/unzip on the destination machine.
                info = zipfile.ZipInfo.from_file(source, name)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o755) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with source.open("rb") as input_file, archive.open(info, "w") as packaged:
                    shutil.copyfileobj(input_file, packaged)
            else:
                archive.write(source, name)
        notice = ("VideoMate " + __version__ + " development kit\n\n"
                  "Extract the entire archive to a software folder. " + ("Python/Tk is included.\n" if include_runtime else "Python 3.11+ with Tk is required; see docs/launchers.md.\n") +
                  "Windows: start.bat; macOS: start.command; Linux: sh start.sh.\n"
                  "Use --check for dependency checks or --cli --help for CLI commands.\n"
                  "On Linux, extract with unzip on a native Linux filesystem to retain permissions and case.\n"
                  "Keep all media and runtime workspaces outside this software folder and cloud sync.\n"
                  "See docs/local-testing.md. No network is used at runtime.\n"
                  "Development release; no OS sandbox or workspace encryption is claimed.\n")
        archive.writestr("START-HERE.txt", notice)
        hashes["START-HERE.txt"] = hashlib.sha256(notice.encode()).hexdigest()
        archive.writestr("bundle-manifest.json", json.dumps({"app_version": __version__, "platform": bundle.platform,
                         "ffmpeg_version": bundle.version, "python_included": include_runtime, "files": hashes}, indent=2))
    with destination.open("rb") as output:
        checksum = hashlib.file_digest(output, "sha256").hexdigest()
    with destination.with_suffix(destination.suffix + ".sha256").open("x", encoding="ascii") as sidecar:
        sidecar.write(checksum + "\n")
    print("Built an offline development kit for " + bundle.platform + (" with Python/Tk." if include_runtime else ". Compatible Python is required separately."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", choices=("windows-x86_64", "windows-arm64", "macos-arm64", "linux-x86_64", "linux-arm64"),
                        help="Package already provisioned software for this platform; does not execute or test it")
    parser.add_argument("--include-runtime", action="store_true", help="Include an already provisioned pinned Python/Tk runtime")
    args = parser.parse_args()
    build(args.output, args.platform, args.include_runtime)
