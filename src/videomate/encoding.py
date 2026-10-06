"""Explicit MP4 rate policies. Size targets are estimates, never guarantees."""
from .errors import VideoMateError

RATE_MODES = ("auto", "quality", "source_size", "target_size", "bitrate")
LOUDNESS_MODES = ("off", "playback", "broadcast")
SOFTWARE_PRESETS = ("fast", "medium", "slow")


def size_target(result, options):
    if options.profile != "compatible_sdr":
        return None
    if options.rate_control == "source_size":
        return result.technical.get("source_size") or None
    if options.rate_control == "target_size":
        return options.target_size_mib * 1024**2
    return None


def candidate_limit(result, options):
    size = result.technical.get("source_size")
    cap = options.max_output_bytes or None
    if options.max_source_percent and size:
        relative = max(1024 ** 2, size * options.max_source_percent // 100)
        cap = min(cap, relative) if cap else relative
    return cap


def audio_rates(result, streams, options):
    rates = []
    for stream in streams:
        if stream["kind"] != "audio":
            continue
        if options.audio_bitrate_kbps:
            rates.append(options.audio_bitrate_kbps * 1000)
            continue
        channels = stream.get("channels") or 2
        default = 64000 * min(8, channels)
        source = result.technical.get("streams", {}).get(str(stream["index"]), {}).get("bit_rate")
        if type(source) is not int or source <= 0:
            source = None
        rates.append(min(max(192000, default), max(32000, source or default)))
    return rates


def video_rates(result, streams, options):
    videos = [s for s in streams if s["kind"] == "video"]
    if not videos:
        return []
    duration = (options.keep_end_us - options.keep_start_us if options.keep_start_us is not None else result.duration_us)
    size = result.technical.get("source_size")
    audio_rate = sum(audio_rates(result, streams, options))
    if options.rate_control in {"source_size", "target_size"}:
        target = size if options.rate_control == "source_size" else options.target_size_mib * 1024 ** 2
        if not target or not duration:
            if options.size_policy == "best_effort":
                from dataclasses import replace
                result.technical['size_estimate_fallback'] = True
                return video_rates(result, streams, replace(options, rate_control="auto"))
            raise VideoMateError("rate_target_unavailable")
        # Reserve 3% for container overhead; all selected audio tracks get a budget.
        total = int(target * 8 * 1000000 * 0.97 / duration) - audio_rate
        if total < 50000 * len(videos) or total > 200000000 * len(videos):
            if options.size_policy == "best_effort":
                from dataclasses import replace
                result.technical['size_estimate_fallback'] = True
                return video_rates(result, streams, replace(options, rate_control="auto"))
            raise VideoMateError("rate_target_unavailable")
        return [total // len(videos)] * len(videos)
    if options.rate_control == "bitrate":
        return [options.video_bitrate_kbps * 1000] * len(videos)
    rates = []
    # Container size bounds implausible/damaged stream bitrate claims. In auto
    # mode keep room for audio/container overhead rather than inflating a tiny
    # low-bitrate source to the old unconditional 250 kbit/s video floor.
    source_budget = int(size * 8 * 1000000 * 0.97 / duration) - audio_rate if size and duration else None
    for stream in videos:
        props = result.technical.get("streams", {}).get(str(stream["index"]), {})
        rate = props.get("bit_rate")
        if type(rate) is not int or rate <= 0:
            rate = None
        if not rate and size and duration:
            rate = (int(size * 8 * 1000000 / duration) - audio_rate) // len(videos)
        if not rate or rate <= 0:
            fps = (stream.get("frame_rate_numerator") or 25) / max(1, stream.get("frame_rate_denominator") or 1)
            rate = int((stream.get("width") or 1280) * (stream.get("height") or 720) * min(120, max(1, fps)) * 0.1)
        if source_budget is not None and options.rate_control == "auto":
            rate = min(rate, max(50000, source_budget // len(videos)))
        # HEVC conversion aims for a smaller video stream than non-HEVC source
        # without changing dimensions or cadence. Existing HEVC uses its source
        # estimate. This is a bitrate goal, not a quality or size guarantee.
        if options.video_codec == "hevc" and stream.get("codec") != "hevc":
            rate = int(rate * 0.8)
        rates.append(min(200000000, max(50000, rate)))
    return rates


def rate_args(encoder, number, rate, options):
    if encoder in {"libx264", "libx265"} and options.rate_control == "quality":
        return [f"-crf:v:{number}", str(options.quality_crf), f"-preset:v:{number}", options.software_preset]
    # A common average-bitrate policy works across the qualified hardware vendors.
    # Quality mode uses a geometry/source estimate on hardware, not a CRF claim.
    args = [f"-b:v:{number}", str(rate), f"-maxrate:v:{number}", str(rate * 2),
            f"-bufsize:v:{number}", str(rate * 4)]
    if encoder in {"libx264", "libx265"}:
        args += [f"-preset:v:{number}", options.software_preset]
    return args
