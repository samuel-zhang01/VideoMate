"""Fixed local correction guidance; never includes a user-entered value."""
from pathlib import Path

from .preferences import INTEGER_BOUNDS


FIELD_LABELS = {
    "timeout": "Worker timeout", "max_output_mib": "Temporary size cap",
    "cpu_threads": "CPU thread budget", "max_runners": "Parallel files",
    "migration_gpu_jobs": "Concurrent GPU jobs", "video_bitrate_kbps": "Video bitrate",
    "target_size_mib": "Target output size", "quality_crf": "Software quality",
    "max_shorter_percent": "Maximum duration loss", "max_source_percent": "Source size cap",
    "size_tolerance_percent": "Finished-size tolerance", "workspace": "Workspace",
    "recovered_dir": "Output location", "diagnostics_dir": "Diagnostics folder",
    "logs_dir": "Event logs folder", "dependencies": "Processing tools",
    "config_file": "Settings file",
}


def correction(values):
    """Return a field and closed message, or None; runtime validation still decides."""
    for name, (low, high) in INTEGER_BOUNDS.items():
        raw = values.get(name, "")
        try:
            value = int(raw)
            valid = type(raw) is not bool and low <= value <= high
        except (ValueError, TypeError, OverflowError):
            valid = False
        if not valid:
            return name, f"{FIELD_LABELS[name]}: enter a whole number from {low:,} to {high:,}."
    for name in ("workspace", "recovered_dir", "diagnostics_dir", "logs_dir", "dependencies", "config_file"):
        value = values.get(name, "")
        if value and (len(value) > 4096 or "\0" in value or not Path(value).is_absolute()):
            return name, f"{FIELD_LABELS[name]}: choose an absolute local path, or leave it blank for the default."
    if values.get("video_codec") == "hevc" and values.get("profile") != "compatible_sdr" and not (
            values.get("convert_all_mp4") or values.get("convert_noncompliant_hevc")):
        return "video_codec", "HEVC needs the MP4 repaired-video format. Choose MP4 above, or select H.264."
    return None
