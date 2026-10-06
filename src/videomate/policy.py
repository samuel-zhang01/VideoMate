"""Explicit local file selection. Assistant tests remain synthetic-only."""

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .errors import VideoMateError


def plain_local_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if str(path).startswith(("\\\\", "//")):
        raise VideoMateError("input_rejected")
    for parent in (path, *path.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise VideoMateError("input_rejected")
    return path


@dataclass(frozen=True)
class DeniedScope:
    def authorize(self, path: Path) -> None:
        # Intentionally before path parsing, stat(), probing or directory discovery.
        raise VideoMateError("selection_required")


@dataclass(frozen=True)
class SyntheticScope:
    """Internal development scope. Never exposed as an unsafe CLI switch.

    Tests/demo must supply only exact files they just generated. This scope is
    not a sandbox, attestation, nor authorization to use production inputs.
    """
    generated_files: frozenset[Path] = field(repr=False)

    def authorize(self, path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        if absolute not in self.generated_files:
            raise VideoMateError("input_rejected")
        checked = plain_local_path(absolute)
        if not stat.S_ISREG(checked.stat().st_mode):
            raise VideoMateError("input_rejected")


def _non_synced_location(target: Path, source: Path) -> None:
    if target == source or source in target.parents:
        raise VideoMateError("workspace_rejected")
    # A custom output may name a project root itself, not just a child folder.
    if any((parent / ".git").exists() or (parent / "pyproject.toml").is_file() for parent in (target, *target.parents)):
        raise VideoMateError("workspace_rejected")
    sync_names = {"onedrive", "dropbox", "google drive", "icloud drive"}
    if any(any(part.casefold().startswith(name) for name in sync_names) for part in target.parts):
        raise VideoMateError("workspace_rejected")
    for variable in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(variable):
            synced = Path(os.path.abspath(os.environ[variable]))
            if target == synced or synced in target.parents:
                raise VideoMateError("workspace_rejected")
    if os.name == "nt":
        import ctypes
        # Mapped Windows network drives are not local merely because they use a drive letter.
        if ctypes.windll.kernel32.GetDriveTypeW(str(target.anchor)) == 4:
            raise VideoMateError("workspace_rejected")


def validate_workspace(path: Path, source_root: Path) -> Path:
    target = plain_local_path(path)
    _non_synced_location(target, source_root.absolute())
    if not target.is_dir():
        raise VideoMateError("workspace_rejected")
    for name in ("state", "jobs", "recovered", "export-review"):
        if not plain_local_path(target / name).is_dir():
            raise VideoMateError("workspace_rejected")
    return target


@dataclass(frozen=True)
class LocalFileScope:
    """Explicit operator selections, with conservative local path restrictions.

    This is not an OS sandbox. Assistant tests still use only generated files.
    """
    selected_files: frozenset[Path] = field(repr=False)
    source_root: Path = field(repr=False)

    def authorize(self, path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        if absolute not in self.selected_files:
            raise VideoMateError("input_rejected")
        checked = plain_local_path(absolute)
        _non_synced_location(checked, self.source_root.absolute())
        if not stat.S_ISREG(checked.stat().st_mode):
            raise VideoMateError("input_rejected")


def create_workspace(path: Path, source_root: Path) -> Path:
    target = plain_local_path(path)
    source = Path(os.path.abspath(source_root))
    _non_synced_location(target, source)
    try:
        target.mkdir(mode=0o700, parents=False, exist_ok=False)
        for name in ("state", "jobs", "recovered", "export-review"):
            (target / name).mkdir(mode=0o700)
    except OSError:
        raise VideoMateError("workspace_rejected") from None
    # Directory creation alone does not qualify storage or Windows ACLs.
    return target


# Import compatibility for older clients; the default-deny boundary is retained.
ProductionScope = DeniedScope
LocalTestScope = LocalFileScope
