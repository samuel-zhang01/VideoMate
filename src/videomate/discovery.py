"""Explicit operator folder discovery; assistant tests use generated directories only."""
import os
from pathlib import Path
from .errors import VideoMateError
from .policy import LocalFileScope, _non_synced_location, plain_local_path

EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv", ".f4v", ".mpg", ".mpeg", ".vob", ".ts", ".mts", ".m2ts", ".wmv", ".asf", ".ogv", ".ogg", ".rm", ".rmvb", ".mxf", ".3gp", ".3g2"}


def discover(inputs, workspace, source_root, recursive=False, *, exclusions=()):
    if not 1 <= len(inputs) <= 1000:
        raise VideoMateError("invalid_arguments")
    selected, identities = [], set()
    visited = 0
    excluded = [workspace, *(plain_local_path(path) for path in exclusions)]
    def is_excluded(path):
        return any(path == root or root in path.parents for root in excluded)
    def add(path):
        if is_excluded(path):
            raise VideoMateError("input_rejected")
        LocalFileScope(frozenset({path}), source_root).authorize(path)
        info = path.stat()
        identity = (info.st_dev, info.st_ino) if info.st_ino else str(path)
        if identity not in identities:
            identities.add(identity)
            selected.append(path)
        if len(selected) > 1000:
            raise VideoMateError("input_rejected")
    for value in inputs:
        path = plain_local_path(Path(value).absolute())
        _non_synced_location(path, source_root)
        if is_excluded(path):
            raise VideoMateError("input_rejected")
        if path.is_dir():
            if not recursive:
                raise VideoMateError("input_rejected")
            device = path.stat().st_dev
            def fail(_):
                raise VideoMateError("io_error")
            for directory, folders, files in os.walk(path, topdown=True, followlinks=False, onerror=fail):
                root = Path(directory)
                accepted = []
                for name in sorted(folders):
                    if name == ".videomate-review":
                        continue
                    child = root / name
                    visited += 1
                    if visited > 100000:
                        raise VideoMateError("input_rejected")
                    try:
                        plain_local_path(child)
                        _non_synced_location(child, source_root)
                        # pathlib did not implement Windows is_mount until Python 3.12.
                        # os.path.ismount covers mounted volumes on supported runtimes.
                        if not is_excluded(child) and child != source_root and child.stat().st_dev == device and not os.path.ismount(child):
                            accepted.append(name)
                    except VideoMateError:
                        continue
                folders[:] = accepted
                for name in sorted(files):
                    visited += 1
                    if visited > 100000:
                        raise VideoMateError("input_rejected")
                    if Path(name).suffix.lower() in EXTENSIONS:
                        child = root / name
                        try:
                            plain_local_path(child)
                        except VideoMateError:
                            continue
                        add(child)
        else:
            add(path)
    if not selected:
        raise VideoMateError("input_rejected")
    return selected
