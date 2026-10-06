"""Local processing presets. Never contain locators, secrets or privacy switches."""
from dataclasses import asdict, replace

from .errors import VideoMateError

PROFILE_FIELDS = frozenset({"workflow", "recursive", "strategy", "profile", "force", "allow_shorter", "partial_salvage",
    "allow_track_loss", "hardware_encoding", "hardware_decoding", "cpu_threads", "max_runners", "timeout",
    "max_output_mib", "output_layout", "convert_all_mp4", "convert_noncompliant_hevc", "video_codec", "rate_control", "video_bitrate_kbps",
    "target_size_mib", "quality_crf", "max_shorter_percent", "max_source_percent", "migration_gpu_jobs", "migration_cpu_auto", "migration_cpu_encoding",
    "migration_preserve_times", "migration_unresolved", "size_tolerance_percent", "audio_normalization",
    "audio_bitrate_kbps", "software_preset", "mp4_faststart", "size_policy"})

MACHINE_FIELDS = {"cpu_threads", "max_runners", "migration_gpu_jobs", "migration_cpu_auto", "migration_cpu_encoding", "timeout"}
ALIASES = {"Migrate — keep healthy formats": "Keep healthy · lossless recovery",
           "Migrate — repair to MP4": "Keep healthy · MP4 recovery", "Migrate — MP4 video": "Convert eligible videos to MP4"}


def builtins():
    from .preferences import Preferences
    base = {k: v for k, v in extract(Preferences()).items() if k not in MACHINE_FIELDS}
    return {
        "Inspect only": {**base, "workflow": "inspect"},
        "Repair — preserve quality": {**base, "workflow": "repair", "partial_salvage": True},
        "Repair — compatible MP4": {**base, "workflow": "repair", "partial_salvage": True, "profile": "compatible_sdr", "strategy": "auto", "rate_control": "source_size", "size_policy": "best_effort"},
        "Keep healthy · lossless recovery": {**base, "workflow": "migrate", "recursive": True, "partial_salvage": True},
        "Keep healthy · MP4 recovery": {**base, "workflow": "migrate", "recursive": True,
                                    "partial_salvage": True, "profile": "compatible_sdr", "strategy": "auto", "rate_control": "source_size", "size_policy": "best_effort"},
        "Convert eligible videos to MP4": {**base, "workflow": "migrate", "recursive": True, "partial_salvage": True, "convert_all_mp4": True,
                                "profile": "compatible_sdr", "strategy": "auto", "rate_control": "source_size", "size_policy": "best_effort"},
        "Migrate · selective HEVC MP4": {**base, "workflow": "migrate", "recursive": True, "partial_salvage": True,
                                "convert_noncompliant_hevc": True, "video_codec": "hevc", "profile": "compatible_sdr",
                                "strategy": "reencode", "rate_control": "auto", "size_policy": "best_effort",
                                "audio_normalization": "playback", "software_preset": "fast"},
    }


def extract(preferences):
    values = asdict(preferences)
    return {name: values[name] for name in sorted(PROFILE_FIELDS)}


def validate_profiles(profiles):
    from .preferences import Preferences
    if type(profiles) is not dict or len(profiles) > 12:
        raise VideoMateError("settings_invalid")
    for name, options in profiles.items():
        if (type(name) is not str or name != name.strip() or not 1 <= len(name) <= 40
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or type(options) is not dict or set(options) - PROFILE_FIELDS):
            raise VideoMateError("settings_invalid")
        Preferences(**options).validate()


def apply(preferences, name):
    name = ALIASES.get(name, name)
    registry = {**builtins(), **preferences.profiles}
    if name not in registry:
        raise VideoMateError("settings_invalid")
    validate_profiles({name: registry[name]})
    return replace(preferences, **registry[name]).validate()


def describe_policy(preferences):
    p = preferences
    if p.workflow == "inspect":
        return "Inspect only. No recovery output; originals remain unchanged."
    mp4 = p.convert_all_mp4 or p.convert_noncompliant_hevc or p.profile == "compatible_sdr"
    scope = ("Copy healthy MP4/H.264 or MP4/HEVC unchanged; encode other videos as HEVC MP4 with playback loudness"
             if p.convert_noncompliant_hevc else "Convert eligible videos, including healthy ones" if p.convert_all_mp4
             else "Copy healthy videos unchanged; recover damaged videos" if p.workflow == "migrate" else "Recover selected videos")
    strategy = "Verified HEVC encoding with bounded hardware/software fallbacks" if p.convert_noncompliant_hevc else "Encoding required by audio changes" if p.audio_normalization != "off" or p.audio_bitrate_kbps else "Encoding required by rate/quality choice" if mp4 and p.rate_control in {"quality", "bitrate"} else "Stream copy first, then verified encoding" if p.convert_all_mp4 or p.strategy == "auto" else "Stream copy only" if p.strategy == "remux" else "Re-encode"
    format_text = "MP4; encoding is lossy" if p.convert_noncompliant_hevc else "MP4; encoding fallback is lossy" if mp4 else "MKV; lossless decoded samples can be much larger"
    size = f"Size: {p.rate_control.replace('_', ' ')}; {p.size_policy.replace('_', ' ')}" if mp4 else "No comparable-size promise"
    unresolved = {"exclude": "omit unresolved outputs; keep originals", "copy": "copy unresolved unchanged", "review": "copy unresolved into a separate review folder"}[p.migration_unresolved]
    salvage = "A final partial recovery is attempted for damaged videos and verified results need review. " if p.partial_salvage else ""
    hybrid = " One software-encoding lane can run beside qualified GPU routes when the automatic CPU budget or forced setting permits." if p.workflow == "migrate" and (p.migration_cpu_auto or p.migration_cpu_encoding) else ""
    return f"{scope}. {format_text}. {strategy}. {size}. Audio: {p.audio_normalization}. " + (f"Unresolved: {unresolved}. " if p.workflow == "migrate" else "") + salvage + "Hardware preferred where enabled and qualified; integrity verification uses software." + hybrid
