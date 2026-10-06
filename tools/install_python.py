"""Provision a pinned, relocatable Python/Tk runtime without system changes."""
import argparse
import hashlib
import json
import os
import posixpath
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE, MAX_EXPANDED = 256 * 1024 * 1024, 1024 * 1024 * 1024


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def safe_name(name):
    value = PurePosixPath(name)
    if value.is_absolute() or ".." in value.parts or "\\" in name or ":" in name or not value.parts or value.parts[0] != "python":
        raise ValueError("Invalid runtime archive path")
    return value


def extract_runtime(archive, stage):
    """Extract regular files and materialize internal links, never external links."""
    with tarfile.open(archive, "r:gz") as package:
        entries, links, total, names = package.getmembers(), [], 0, set()
        if len(entries) > 40000:
            raise ValueError("Runtime archive exceeds entry limit")
        for info in entries:
            relative = safe_name(info.name)
            if relative in names:
                raise ValueError("Duplicate runtime archive member")
            names.add(relative)
            target = stage.joinpath(*relative.parts)
            if info.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif info.isfile():
                total += info.size
                if info.size > MAX_ARCHIVE or total > MAX_EXPANDED:
                    raise ValueError("Runtime archive exceeds size limit")
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.extractfile(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if info.mode & 0o111 else 0o644)
            elif info.issym() or info.islnk():
                name = info.linkname if info.islnk() else posixpath.join(str(relative.parent), info.linkname)
                # Check before normalization, so absolute / outside targets cannot hide.
                if PurePosixPath(info.linkname).is_absolute() or "\\" in info.linkname or ":" in info.linkname:
                    raise ValueError("External runtime link")
                resolved = safe_name(posixpath.normpath(name))
                links.append((target, stage.joinpath(*resolved.parts)))
            else:
                raise ValueError("Unsupported runtime archive member")
        # Materialization also works on Windows without symlink privileges.
        for _ in range(20):
            pending = []
            for target, source in links:
                if source.is_file() and not source.is_symlink():
                    total += source.stat().st_size
                    if total > MAX_EXPANDED or target.exists():
                        raise ValueError("Runtime link exceeds limits or collides")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                else:
                    pending.append((target, source))
            if not pending:
                return
            if len(pending) == len(links):
                break
            links = pending
        raise ValueError("Unresolved runtime links")


def runtime_path(tag):
    if os.environ.get("VIDEOMATE_RUNTIME_ROOT"):
        parent = Path(os.environ["VIDEOMATE_RUNTIME_ROOT"]).expanduser().absolute()
    elif platform.system() == "Linux" and len(ROOT.parts) > 2 and ROOT.parts[1] == "mnt" and len(ROOT.parts[2]) == 1:
        # A WSL checkout on a Windows drive cannot store case-distinct terminfo
        # files. Public runtime software belongs on the native Linux filesystem.
        parent = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "videomate-software/python"
    else:
        parent = ROOT / "dependencies/python"
    return parent / tag


def executable(tag):
    return runtime_path(tag) / "python" / ("python.exe" if tag.startswith("windows-") else "bin/python3")


def verify(tag):
    path = executable(tag)
    record = json.loads((runtime_path(tag) / "runtime-manifest.json").read_text(encoding="utf-8"))
    if record.get("platform") != tag or path.is_symlink() or digest(path) != record.get("executable_sha256"):
        raise ValueError("Local Python runtime failed verification")
    return path


def install(tag, *, archive=None, online=False):
    catalog = json.loads((ROOT / "dependencies/python-sources.json").read_text(encoding="utf-8"))
    spec = catalog["platforms"][tag]
    destination = runtime_path(tag)
    if destination.exists():
        return verify(tag)
    cache = ROOT / "dependencies/cache"
    cache.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.parent / (".install-" + tag + ".lock")
    handle = lock.open("x")
    try:
        if destination.exists():
            return verify(tag)
        supplied = archive is not None
        archive = Path(archive) if supplied else cache / spec["filename"]
        if not archive.exists() and not supplied:
            if not online:
                raise ValueError("Pinned Python archive is not cached")
            partial = archive.with_name(archive.name + ".part")
            owned = False
            try:
                with partial.open("xb") as output:
                    owned = True
                    request = urllib.request.Request(spec["url"], headers={"User-Agent": "VideoMate dependency setup/0.6"})
                    with urllib.request.urlopen(request, timeout=60) as response:
                        if not response.geturl().startswith("https://"):
                            raise ValueError("HTTPS required")
                        total = 0
                        while chunk := response.read(1024 * 1024):
                            total += len(chunk)
                            if total > MAX_ARCHIVE:
                                raise ValueError("Python archive exceeds limit")
                            output.write(chunk)
                if digest(partial) != spec["sha256"]:
                    raise ValueError("Python archive checksum mismatch")
                partial.rename(archive)
            finally:
                if owned and partial.exists():
                    partial.unlink()
        if not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE or digest(archive) != spec["sha256"]:
            raise ValueError("Python archive checksum mismatch")
        with tempfile.TemporaryDirectory(prefix=".python-install-", dir=destination.parent) as temporary:
            stage = Path(temporary)
            extract_runtime(archive, stage)
            relative = "python/python.exe" if tag.startswith("windows-") else "python/bin/python3"
            record = {"schema_version":1, "platform":tag, "version":spec["version"], "source":spec["url"],
                      "archive_sha256":spec["sha256"], "executable_sha256":digest(stage / relative)}
            (stage / "runtime-manifest.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            stage.rename(destination)
        print("Prepared local Python/Tk runtime for " + tag + ". No system packages changed.", flush=True)
        return verify(tag)
    finally:
        handle.close()
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=("windows-x86_64", "windows-arm64", "macos-arm64", "linux-x86_64", "linux-arm64"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    install(args.platform, archive=args.archive, online=args.online)
