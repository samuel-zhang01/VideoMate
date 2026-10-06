"""Local application preferences. Never stores input selections, logs or keys."""
import json
import os
import platform
import secrets
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .errors import VideoMateError
from .policy import _non_synced_location, plain_local_path
from .setup_local import default_workspace

MAX_PREFERENCES_BYTES = 256 * 1024
INTEGER_BOUNDS = {
    "timeout": (1, 86400),
    "max_output_mib": (0, 1048576),
    "cpu_threads": (0, 1024),
    "max_runners": (0, 1024),
    "migration_gpu_jobs": (1, 16),
    "video_bitrate_kbps": (50, 200000),
    "target_size_mib": (1, 1048576),
    "quality_crf": (0, 51),
    "max_shorter_percent": (0, 100),
    "max_source_percent": (0, 10000),
    "size_tolerance_percent": (5, 100),
}


def default_config_path():
    if os.environ.get("VIDEOMATE_CONFIG"):
        return Path(os.environ["VIDEOMATE_CONFIG"]).expanduser().absolute()
    if platform.system() == "Windows":
        parent = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    elif platform.system() == "Darwin":
        parent = Path.home() / "Library/Application Support"
    else:
        configured = os.environ.get("XDG_CONFIG_HOME", "")
        parent = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / ".config"
    return parent / "VideoMate/settings.json"


@dataclass(frozen=True)
class Preferences:
    sensitive: bool = True
    workspace: str = ""
    recovered_dir: str = ""
    diagnostics_dir: str = ""
    logs_dir: str = ""
    dependencies: str = ""
    write_logs: bool = False
    timeout: int = 3600
    max_output_mib: int = 0
    recursive: bool = False
    strategy: str = "auto"
    profile: str = "preserve_decoded_samples"
    force: bool = False
    allow_shorter: bool = False
    partial_salvage: bool = True
    allow_track_loss: bool = False
    hardware_encoding: bool = True
    hardware_decoding: bool = True
    hardware_preference: str = "auto"
    hardware_calibration: dict = field(default_factory=dict)
    cpu_threads: int = 0
    max_runners: int = 0
    migration_gpu_jobs: int = 2
    migration_cpu_auto: bool = True
    migration_cpu_encoding: bool = False
    diagnostic_logs: bool = False
    output_layout: str = "neutral"
    convert_all_mp4: bool = False
    convert_noncompliant_hevc: bool = False
    video_codec: str = "h264"
    rate_control: str = "auto"
    video_bitrate_kbps: int = 8000
    target_size_mib: int = 500
    quality_crf: int = 18
    max_shorter_percent: int = 10
    max_source_percent: int = 0
    size_tolerance_percent: int = 25
    size_policy: str = "strict"
    audio_normalization: str = "off"
    audio_bitrate_kbps: int = 0
    software_preset: str = "medium"
    mp4_faststart: bool = True
    retain_history: bool = False
    retain_mappings: bool = False
    private_resume: bool = False
    interruption_recovery: bool = True
    workflow: str = "inspect"
    migration_local_names: bool = False
    migration_preserve_times: bool = True
    migration_unresolved: str = "exclude"
    profiles: dict = field(default_factory=dict)
    reduce_motion: bool = False

    def validate(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not field.type:
                raise VideoMateError("settings_invalid")
        for name, (low, high) in INTEGER_BOUNDS.items():
            if not low <= getattr(self, name) <= high:
                raise VideoMateError("settings_invalid")
        from .calibration import VALID_PREFERENCES, validate_calibrations
        if self.hardware_preference not in VALID_PREFERENCES:
            raise VideoMateError("settings_invalid")
        validate_calibrations(self.hardware_calibration)
        from .encoding import RATE_MODES, LOUDNESS_MODES, SOFTWARE_PRESETS
        if self.audio_normalization not in LOUDNESS_MODES or self.software_preset not in SOFTWARE_PRESETS or self.audio_bitrate_kbps not in {0, 64, 96, 128, 160, 192, 256, 320}:
            raise VideoMateError("settings_invalid")
        from .output_layout import LAYOUTS
        if self.output_layout not in LAYOUTS or self.rate_control not in RATE_MODES or self.size_policy not in {"strict", "best_effort"} or self.video_codec not in {"h264", "hevc"}:
            raise VideoMateError("settings_invalid")
        if self.convert_all_mp4 and self.convert_noncompliant_hevc:
            raise VideoMateError("settings_invalid")
        if self.convert_noncompliant_hevc and self.rate_control != "auto":
            raise VideoMateError("settings_invalid")
        if self.video_codec == "hevc" and self.profile != "compatible_sdr" and not (self.convert_noncompliant_hevc or self.convert_all_mp4):
            raise VideoMateError("settings_invalid")
        if self.strategy not in {"auto", "remux", "reencode"} or self.profile not in {"preserve_decoded_samples", "compatible_sdr"}:
            raise VideoMateError("settings_invalid")
        if self.workflow not in {"inspect", "repair", "migrate"}:
            raise VideoMateError("settings_invalid")
        if self.migration_unresolved not in {"exclude", "copy", "review"}:
            raise VideoMateError("settings_invalid")
        from .profiles import validate_profiles
        if self.profiles:
            validate_profiles(self.profiles)
        for name in ("workspace", "recovered_dir", "diagnostics_dir", "logs_dir", "dependencies"):
            value = getattr(self, name)
            if len(value) > 4096 or (value and (not Path(value).is_absolute() or "\0" in value)):
                raise VideoMateError("settings_invalid")
        return self


def load_preferences(path):
    try:
        path = plain_local_path(path)
        if not path.exists():
            return Preferences(workspace=str(default_workspace()))
        from .schema import load_json
        with path.open("rb") as source:
            value = load_json(source.read(MAX_PREFERENCES_BYTES + 1), limit=MAX_PREFERENCES_BYTES)
        if type(value) is not dict or value.pop("schema_version", None) != 1:
            raise ValueError()
        return Preferences(**value).validate()
    except (OSError, ValueError, TypeError, VideoMateError):
        raise VideoMateError("settings_invalid") from None


def save_preferences(path, preferences):
    preferences.validate()
    # Check the exact bytes before replacing a valid file or creating storage.
    # The reader and writer share this bound, including JSON escape expansion.
    encoded = json.dumps({"schema_version": 1, **asdict(preferences)}, indent=2,
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    if len(encoded) > MAX_PREFERENCES_BYTES:
        raise VideoMateError("settings_invalid")
    temporary = None
    owned = False
    try:
        path = plain_local_path(path)
        _non_synced_location(path, Path(__file__).absolute().parents[2])
        if path.exists():
            load_preferences(path)  # Never overwrite an unrelated existing file.
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_name(".videomate-settings-" + secrets.token_hex(12) + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        owned = True
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
        os.replace(temporary, path)
    except (OSError, VideoMateError):
        raise VideoMateError("settings_invalid") from None
    finally:
        if owned and temporary is not None and temporary.exists():
            temporary.unlink()


def storage_directory(value, fallback):
    path = plain_local_path(Path(value) if value else fallback)
    _non_synced_location(path, Path(__file__).absolute().parents[2])
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise VideoMateError("workspace_rejected")
    return path
