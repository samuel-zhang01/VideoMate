"""Offline first-launch checks and private workspace preparation."""
import os
import platform
import tempfile
from pathlib import Path

from .backend import FFmpegBackend
from .dependencies import load_bundle, platform_tag
from .errors import VideoMateError
from .policy import _non_synced_location, plain_local_path, validate_workspace
from .runner import Runner


def default_workspace():
    if platform.system() == "Windows":
        parent = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    elif platform.system() == "Darwin":
        parent = Path.home() / "Library" / "Application Support"
    else:
        configured = os.environ.get("XDG_STATE_HOME", "")
        parent = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / ".local" / "state"
    return parent / "VideoMate" / "Workspace"


def ensure_workspace(path):
    path = plain_local_path(Path(path))
    source = Path(__file__).absolute().parents[2]
    _non_synced_location(path, source)
    if (path / ".git").exists() or (path / "pyproject.toml").is_file():
        raise VideoMateError("workspace_rejected")
    directories = [path, *(plain_local_path(path / name) for name in ("state", "jobs", "recovered", "export-review", "logs"))]
    # Check every fixed destination before creating anything. Never enumerate or
    # overwrite existing files; an empty or partially prepared workspace is OK.
    if any(directory.exists() and not directory.is_dir() for directory in directories):
        raise VideoMateError("workspace_rejected")
    for directory in directories:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return validate_workspace(path, source)


def prepare_application(preferences, config_path, *, save_current=False):
    """Prepare operator-selected app storage, never scan inputs or purge history."""
    from dataclasses import replace
    from .preferences import load_preferences, save_preferences, storage_directory
    preferences.validate()
    source = Path(__file__).absolute().parents[2]
    try:
        config_path = Path(config_path)
        if not config_path.is_absolute():
            raise VideoMateError("settings_location")
        config_path = plain_local_path(config_path)
        _non_synced_location(config_path, source)
        if config_path.is_dir():
            raise VideoMateError("settings_location")
        exists = config_path.exists()
    except (OSError, VideoMateError):
        raise VideoMateError("settings_location") from None
    if exists:
        load_preferences(config_path)  # Refuse an unrelated/invalid existing file.
    workspace = Path(preferences.workspace) if preferences.workspace else default_workspace()
    # Validate custom destinations before creating the default workspace.
    try:
        for value in (preferences.recovered_dir, preferences.diagnostics_dir, preferences.logs_dir):
            if value:
                target = plain_local_path(Path(value))
                _non_synced_location(target, source)
                if target.exists() and not target.is_dir():
                    raise VideoMateError("workspace_rejected")
        workspace = ensure_workspace(workspace)
        for value, name in ((preferences.recovered_dir, "recovered"), (preferences.diagnostics_dir, "export-review"), (preferences.logs_dir, "logs")):
            storage_directory(value, workspace / name)
    except OSError:
        raise VideoMateError("workspace_rejected") from None
    if not exists or save_current:
        selected = replace(preferences, workspace=str(workspace))
        save_preferences(config_path, selected)
        # A missing file normally loads defaults; require actual existence and
        # exact round-trip here before displaying a successful preparation.
        if not config_path.is_file() or load_preferences(config_path) != selected:
            raise VideoMateError("settings_invalid")
    return workspace


def check_backend(root=None):
    """Hash and launch public software only; never touch a media workspace."""
    bundle = load_bundle(root)
    with tempfile.TemporaryDirectory(prefix="videomate-software-check-") as temporary:
        scratch = Path(temporary).resolve()
        runner = Runner(timeout=15)
        for executable in (bundle.ffmpeg, bundle.ffprobe):
            FFmpegBackend._executable(executable)
            outcome = runner.run([str(executable), "-version"], scratch)
            if outcome.limited or outcome.returncode != 0:
                raise VideoMateError("dependency_unavailable")
        encoders = runner.run([str(bundle.ffmpeg), "-hide_banner", "-encoders"], scratch)
        if encoders.limited or encoders.returncode != 0:
            raise VideoMateError("dependency_unavailable")
        available = {parts[1] for line in encoders.stdout.decode("ascii", errors="replace").splitlines()
                     if len(parts := line.split()) >= 2 and len(parts[0]) == 6}
        if not {"libx264", "aac", "ffv1", "pcm_s16le"} <= available:
            raise VideoMateError("dependency_unavailable")
    return {"status": "ready", "version": bundle.version, "platform": platform_tag()}
