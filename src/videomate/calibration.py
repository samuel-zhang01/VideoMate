"""Synthetic-only encoder calibration and bounded route ordering.

Saved records contain neutral encoder IDs and speeds, never source information.
"""
import copy
import hashlib
import math
import re
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .backend import FFmpegBackend
from .errors import VideoMateError
from .hardware import codec_routes, qualify_codec_routes, qualify_devices, select_decoder, select_encoder
from .models import ScanResult
from .recovery import RecoveryOptions, command
from .runner import Runner


SAMPLE_FRAMES = 480
SAMPLE_SIZE = "1280x720"
VALID_PREFERENCES = frozenset({"auto", "nvidia", "amd", "intel", "apple"})
_ROUTE_ID = re.compile(r"(?:h264|hevc)_(?:nvenc|amf|qsv|videotoolbox)(?:#[0-9]{1,2})?")
_VENDORS = {"nvenc": "nvidia", "amf": "amd", "qsv": "intel", "videotoolbox": "apple"}


def route_id(route):
    _, encoder, device = route
    return encoder + (f"#{device}" if device is not None else "")


def vendor(route):
    return _VENDORS.get(route[1].split("_")[-1], "")


def bundle_signature(bundle):
    value = "|".join((bundle.platform, bundle.version, getattr(bundle, "digest", "")))
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def validate_calibrations(value):
    if type(value) is not dict or set(value) - {"h264", "hevc"}:
        raise VideoMateError("settings_invalid")
    for codec, record in value.items():
        if type(record) is not dict or set(record) != {"signature", "expires_at", "routes"}:
            raise VideoMateError("settings_invalid")
        if type(record["signature"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", record["signature"]):
            raise VideoMateError("settings_invalid")
        if type(record["expires_at"]) is not int or not 0 <= record["expires_at"] <= 4102444800:
            raise VideoMateError("settings_invalid")
        routes = record["routes"]
        if type(routes) is not list or not 1 <= len(routes) <= 32:
            raise VideoMateError("settings_invalid")
        seen = set()
        for item in routes:
            if type(item) is not dict or set(item) != {"id", "fps", "jobs"}:
                raise VideoMateError("settings_invalid")
            identity, fps = item["id"], item["fps"]
            if (type(identity) is not str or not _ROUTE_ID.fullmatch(identity) or not identity.startswith(codec + "_")
                    or identity in seen or type(fps) not in {int, float} or not 0 < fps <= 100000 or not math.isfinite(fps)):
                raise VideoMateError("settings_invalid")
            if type(item["jobs"]) is not int or item["jobs"] not in {1, 2}:
                raise VideoMateError("settings_invalid")
            seen.add(identity)
    return value


def valid_record(calibrations, codec, bundle, now=None):
    record = calibrations.get(codec) if type(calibrations) is dict else None
    if not record:
        return None
    try:
        validate_calibrations({codec: record})
    except VideoMateError:
        return None
    return record if record["signature"] == bundle_signature(bundle) and record["expires_at"] > (time.time() if now is None else now) else None


def rank_devices(devices, *, preference="auto", calibrations=None, codec="h264", bundle=None):
    """Only order already qualified devices; stale records never create routes."""
    if preference not in VALID_PREFERENCES:
        raise VideoMateError("settings_invalid")
    record = valid_record(calibrations or {}, codec, bundle) if bundle else None
    speeds = {item["id"]: item["fps"] for item in record["routes"]} if record else {}
    indexed = list(enumerate(devices))
    indexed.sort(key=lambda pair: (0 if preference != "auto" and vendor(pair[1]) == preference else 1,
                                   -speeds.get(route_id(pair[1]), 0), pair[0])
                 if preference != "auto" else (-speeds.get(route_id(pair[1]), 0), pair[0]))
    return tuple(route for _, route in indexed), speeds


def calibrated_jobs(calibrations, codec, bundle):
    record = valid_record(calibrations or {}, codec, bundle)
    return {item["id"]: item["jobs"] for item in record["routes"]} if record else {}


def lane_routes(devices, lane_count, speeds, preference="auto", limits=None):
    """Give each qualified route a lane, then apportion spare lanes by speed."""
    if not devices or lane_count <= 0:
        return ()
    starts = list(range(min(len(devices), lane_count)))
    allocations = [int(index in starts) for index in range(len(devices))]
    measured_max = max((speeds.get(route_id(route), 0) for route in devices), default=0)
    for _ in range(len(starts), lane_count):
        candidates = [index for index in range(len(devices))
                      if allocations[index] < (limits or {}).get(route_id(devices[index]), lane_count)]
        chosen = max(candidates or range(len(devices)), key=lambda index:
                     ((max(1, measured_max * 4) if preference != "auto" and vendor(devices[index]) == preference
                       else speeds.get(route_id(devices[index]), 1)) / (allocations[index] + 1), -index))
        allocations[chosen] += 1
        starts.append(chosen)
    return tuple(devices[index:] + devices[:index] for index in starts)


def _verified_frames(backend, output, scratch):
    checked = backend.runner.run([str(backend.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-hwaccel", "none",
                                  "-err_detect", "explode", "-i", str(output), "-map", "0:v:0", "-f", "null",
                                  "-progress", "pipe:1", "-"], scratch)
    if checked.limited or checked.returncode or checked.stderr.strip():
        return 0
    frames = re.findall(rb"(?:^|\n)frame=(\d+)(?:\r?\n|$)", checked.stdout)
    return int(frames[-1]) if frames else 0


def optimize_generated(bundle, codec, *, cancel_event=None):
    """Benchmark only an internally generated clip; never accepts a media path."""
    if codec not in {"h264", "hevc"}:
        raise VideoMateError("settings_invalid")
    root = Path(tempfile.mkdtemp(prefix="videomate-calibration-")).absolute()
    runner = Runner(timeout=45, output_limit=262144, cancel_event=cancel_event)
    try:
        backend = FFmpegBackend(bundle.ffmpeg, bundle.ffprobe, root, runner, threads=4)
        decoders = select_decoder(backend, all_ready=True)
        encoders = select_encoder(backend, all_ready=True, codec=codec)
        routes = qualify_devices(backend, qualify_codec_routes(backend, codec_routes(decoders, encoders)))
        routes = tuple(route for route in routes if route[1].endswith(("_nvenc", "_amf", "_qsv", "_videotoolbox")))
        if not routes:
            raise VideoMateError("dependency_unavailable")
        source = root / "generated-source.mp4"
        generated = runner.run([str(bundle.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-n", "-f", "lavfi",
                                "-i", f"testsrc2=size={SAMPLE_SIZE}:rate=30", "-frames:v", str(SAMPLE_FRAMES),
                                "-an", "-c:v", "libx264", "-preset", "ultrafast", "-threads", "4",
                                "-pix_fmt", "yuv420p", str(source)], root, watch_file=source, max_file_bytes=96 * 1024**2)
        if generated.limited or generated.returncode or not source.is_file() or not source.stat().st_size:
            raise VideoMateError("dependency_unavailable")
        sample = ScanResult(duration_us=16_000_000, streams=[{"index": 0, "kind": "video", "codec": "h264",
            "width": 1280, "height": 720, "pixel_format": "yuv420p", "frame_rate_numerator": 30,
            "frame_rate_denominator": 1}], technical={"source_size": source.stat().st_size})
        options = RecoveryOptions(profile="compatible_sdr", video_codec=codec, rate_control="bitrate",
                                  video_bitrate_kbps=3000, mp4_faststart=False)
        measured = []
        for index, (decoder, encoder, device) in enumerate(routes):
            if cancel_event and cancel_event.is_set():
                raise KeyboardInterrupt()
            output = root / f"generated-route-{index}.mp4"
            probe = copy.copy(backend)
            probe.gpu_index = device
            args = command(probe, source, output, sample, "reencode", options, encoder, decoder)
            outcome = runner.run(args, root, watch_file=output, max_file_bytes=96 * 1024**2)
            if (outcome.limited or outcome.returncode or not output.is_file() or not output.stat().st_size
                    or _verified_frames(backend, output, root) != SAMPLE_FRAMES):
                continue
            solo_fps = SAMPLE_FRAMES / max(0.001, outcome.elapsed_ms / 1000)

            def concurrent_encode(number):
                concurrent_output = root / f"generated-concurrent-{index}-{number}.mp4"
                candidate = copy.copy(backend)
                candidate.gpu_index = device
                candidate_args = command(candidate, source, concurrent_output, sample, "reencode", options, encoder, decoder)
                result = runner.run(candidate_args, root, watch_file=concurrent_output, max_file_bytes=96 * 1024**2)
                return concurrent_output, result

            jobs, effective_fps = 1, solo_fps
            parallel_start = time.monotonic()
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="videomate-calibration") as pool:
                futures = [pool.submit(concurrent_encode, number) for number in (0, 1)]
                parallel = [future.result() for future in futures]
            parallel_elapsed = max(time.monotonic() - parallel_start,
                                   max(result.elapsed_ms for _, result in parallel) / 1000)
            if all(not result.limited and result.returncode == 0 and output.is_file() and output.stat().st_size
                   and _verified_frames(backend, output, root) == SAMPLE_FRAMES for output, result in parallel):
                parallel_fps = SAMPLE_FRAMES * 2 / max(0.001, parallel_elapsed)
                if parallel_fps >= solo_fps * 1.15:
                    jobs, effective_fps = 2, parallel_fps
            measured.append({"id": route_id((decoder, encoder, device)), "fps": round(min(100000, effective_fps), 2),
                             "jobs": jobs})
        if not measured:
            raise VideoMateError("dependency_unavailable")
        measured.sort(key=lambda item: -item["fps"])
        record = {"signature": bundle_signature(bundle), "expires_at": int(time.time()) + 30 * 86400,
                  "routes": measured}
        validate_calibrations({codec: record})
        return record
    finally:
        if not runner.cleanup_blocked.is_set():
            shutil.rmtree(root)
