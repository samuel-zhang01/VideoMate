"""Bounded hardware codec readiness checks using generated frames only."""
import platform
import copy
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .errors import VideoMateError
from .runner import Runner
from .execution import resource_slot

ENCODERS = {"h264": ("h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"),
            "hevc": ("hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_videotoolbox")}
DECODER_FORMATS = {"d3d11va": "d3d11", "dxva2": "dxva2_vld", "cuda": "cuda", "qsv": "qsv",
                   "vaapi": "vaapi", "videotoolbox": "videotoolbox_vld"}
HARDWARE_CODECS = {"h264", "hevc", "av1", "vp8", "vp9", "mpeg2video", "vc1", "wmv3"}
# Some hardware encoders reject tiny frames even when they can encode ordinary
# video. Keep qualification synthetic but use a representative SD frame size.
ENCODER_CHECK_SIZE = "320x240"


@contextmanager
def qualification_scratch(runner, parent, prefix):
    scratch = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    try:
        yield scratch
    finally:
        if not runner.cleanup_blocked.is_set():
            shutil.rmtree(scratch)


@contextmanager
def hardware_slot(backend, enabled=True, *, gate=None):
    gate = (gate if gate is not None else getattr(backend, "hardware_gate", None)) if enabled else None
    with resource_slot(gate, backend.runner.cancel_event):
        yield


def decoder_args(decoder, *, native_frames=False):
    if decoder in {"none", "software"}:
        return ["-hwaccel", "none"]
    if decoder not in DECODER_FORMATS:
        raise VideoMateError("invalid_arguments")
    args = ["-hwaccel", decoder]
    if native_frames:
        args += ["-hwaccel_output_format", DECODER_FORMATS[decoder]]
    return args


def select_decoder(backend, *, all_ready=False):
    """Require a real hardware-frame download from a freshly generated sample."""
    runner = Runner(timeout=min(10, backend.runner.timeout), output_limit=262144,
                    cancel_event=backend.runner.cancel_event, cleanup_blocked=backend.runner.cleanup_blocked)
    system = platform.system()
    choices = {"Windows": ("d3d11va", "dxva2", "cuda", "qsv"), "Darwin": ("videotoolbox",)}.get(system, ("cuda", "vaapi", "qsv"))
    selected = []
    try:
        listing = runner.run([str(backend.ffmpeg), "-hide_banner", "-hwaccels"], backend.scratch)
        available = set(listing.stdout.decode("ascii", errors="replace").split()) & set(choices)
        if listing.returncode or listing.limited or not available:
            return ("software",) if all_ready else "software"
        with qualification_scratch(runner, backend.scratch, "decoder-check-") as temporary:
            scratch = Path(temporary)
            sample = scratch / "generated.mp4"
            encoded = runner.run([str(backend.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-n",
                "-f", "lavfi", "-i", "color=c=black:s=128x128:r=24", "-frames:v", "3", "-an",
                "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(sample)], scratch,
                watch_file=sample, max_file_bytes=4194304)
            if encoded.returncode or encoded.limited:
                return ("software",) if all_ready else "software"
            for decoder in choices:
                if decoder not in available:
                    continue
                decoded = runner.run([str(backend.ffmpeg), "-nostdin", "-hide_banner", "-v", "error",
                    *decoder_args(decoder, native_frames=True), "-i", str(sample), "-map", "0:v:0",
                    "-vf", "hwdownload,format=nv12", "-filter_threads", "1", "-frames:v", "3", "-f", "null", "-"], scratch)
                if not decoded.returncode and not decoded.limited and not decoded.stderr.strip():
                    if not all_ready:
                        return decoder
                    selected.append(decoder)
    except (VideoMateError, OSError) as error:
        if isinstance(error, VideoMateError) and error.code == "worker_cleanup_failed":
            raise
    return (tuple(selected) or ("software",)) if all_ready else "software"


def video_encoder_args(encoder, index=0):
    if encoder in {"libx264", "libx265"}:
        return [f"-c:v:{index}", encoder, f"-crf:v:{index}", "18", f"-preset:v:{index}", "medium"]
    if encoder not in ENCODERS["h264"] + ENCODERS["hevc"]:
        raise VideoMateError("invalid_arguments")
    # A fixed bitrate makes the cross-vendor policy explicit. This is a lossy
    # compatibility profile, never a replacement for FFV1 preservation.
    args = [f"-c:v:{index}", encoder, f"-b:v:{index}", "8M"]
    if encoder in {"h264_videotoolbox", "hevc_videotoolbox"}:
        args += [f"-allow_sw:v:{index}", "0"]
    return args


def select_encoder(backend, *, all_ready=False, codec="h264"):
    if codec not in ENCODERS:
        raise VideoMateError("invalid_arguments")
    cache_name = f"_ready_{codec}_encoders" if all_ready else f"_ready_{codec}_encoder"
    if hasattr(backend, cache_name):
        return getattr(backend, cache_name)
    runner = Runner(timeout=min(15, backend.runner.timeout), output_limit=262144,
                    cancel_event=backend.runner.cancel_event, cleanup_blocked=backend.runner.cleanup_blocked)
    device_runner = Runner(timeout=min(5, backend.runner.timeout), output_limit=262144,
                           cancel_event=backend.runner.cancel_event, cleanup_blocked=backend.runner.cleanup_blocked)
    software = "libx265" if codec == "hevc" else "libx264"
    selected = software
    qualified = []
    try:
        listing = runner.run([str(backend.ffmpeg), "-hide_banner", "-encoders"], backend.scratch)
        available = {parts[1] for line in listing.stdout.decode("ascii", errors="replace").splitlines()
                     if len(parts := line.split()) >= 2 and parts[1] in ENCODERS[codec]}
        candidates = (ENCODERS[codec][3],) if platform.system() == "Darwin" else ENCODERS[codec][:3]
        if not listing.limited and listing.returncode == 0:
            for encoder in candidates:
                if encoder not in available:
                    continue
                with qualification_scratch(runner, backend.scratch, "encoder-check-") as temporary:
                    scratch = Path(temporary)
                    def qualifies(device=None):
                        output = scratch / ("generated-default.mp4" if device is None else f"generated-{device}.mp4")
                        args = [str(backend.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-n",
                            "-f", "lavfi", "-i", f"color=c=black:s={ENCODER_CHECK_SIZE}:r=24", "-frames:v", "3", "-an",
                            *video_encoder_args(encoder), "-pix_fmt", "+yuv420p", "-f", "mp4"]
                        if device is not None:
                            args += ["-gpu", str(device)]
                        probe = runner if device is None else device_runner
                        encoded = probe.run([*args, str(output)], scratch, watch_file=output, max_file_bytes=4194304)
                        if encoded.limited or encoded.returncode or not output.is_file() or not output.stat().st_size:
                            return False
                        decoded = probe.run([str(backend.ffmpeg), "-nostdin", "-hide_banner", "-v", "error",
                            "-hwaccel", "none", "-err_detect", "explode", "-protocol_whitelist", "file,pipe",
                            "-i", str(output), "-f", "null", "-"], scratch)
                        return not decoded.limited and decoded.returncode == 0 and not decoded.stderr.strip()

                    if qualifies():
                        qualified.append(encoder)
                        if not all_ready:
                            break
                    elif encoder in {"h264_nvenc", "hevc_nvenc"}:
                        # The default NVIDIA adapter can be unusable while a
                        # different enumerated adapter is viable. Only accept
                        # a device after encoding and software decoding a
                        # generated sample; never trust the encoder listing.
                        for device in range(16):
                            if qualifies(device):
                                setattr(backend, f"_ready_{codec}_nvenc_device", device)
                                qualified.append(encoder)
                                break
                        if qualified and qualified[-1] == encoder and not all_ready:
                            break
    except (VideoMateError, OSError) as error:
        if isinstance(error, VideoMateError) and error.code == "worker_cleanup_failed":
            raise
    selected = qualified[0] if qualified else software
    setattr(backend, f"_ready_{codec}_encoder", selected)
    if all_ready:
        setattr(backend, cache_name, tuple(qualified) or (software,))
        return getattr(backend, cache_name)
    return selected


def codec_routes(decoders, encoders):
    """Prefer matching API families; do not count generic decoder aliases twice.

    API readiness is not physical device enumeration. Multiple identical GPUs
    behind one API still use that API's default device until device routing is
    explicitly qualified on each platform.
    """
    preferred = {"h264_nvenc": ("cuda", "d3d11va", "dxva2"), "h264_qsv": ("qsv",),
                 "h264_amf": ("d3d11va", "dxva2", "vaapi"), "h264_videotoolbox": ("videotoolbox",),
                 "hevc_nvenc": ("cuda", "d3d11va", "dxva2"), "hevc_qsv": ("qsv",),
                 "hevc_amf": ("d3d11va", "dxva2", "vaapi"), "hevc_videotoolbox": ("videotoolbox",)}
    if not all(e in {"libx264", "libx265"} for e in encoders):
        return tuple((next((d for d in preferred[e] if d in decoders), "software"), e) for e in encoders)
    distinct = [d for d in ("cuda", "qsv", "videotoolbox") if d in decoders]
    return tuple((d, encoders[0]) for d in (distinct or decoders[:1]))


def qualify_codec_routes(backend, routes):
    """Test combined decode/encode paths, which may select different adapters."""
    from .models import ScanResult
    from .recovery import RecoveryOptions, command
    cache = getattr(backend, "_codec_route_checks", {})
    backend._codec_route_checks = cache
    runner = Runner(timeout=min(15, backend.runner.timeout), output_limit=262144,
                    cancel_event=backend.runner.cancel_event, cleanup_blocked=backend.runner.cleanup_blocked)
    selected = []
    for decoder, encoder in routes:
        pair = (decoder, encoder)
        if decoder == "software":
            cache[pair] = True
        if pair not in cache:
            cache[pair] = False
            try:
                with qualification_scratch(runner, backend.scratch, "route-check-") as scratch:
                    source, output = scratch / "generated.mp4", scratch / "converted.mp4"
                    generated = runner.run([str(backend.ffmpeg), "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
                        f"testsrc2=size={ENCODER_CHECK_SIZE}:rate=24", "-frames:v", "3", "-c:v", "libx264", "-threads", "1", str(source)], scratch,
                        watch_file=source, max_file_bytes=4194304)
                    if not generated.returncode and not generated.limited:
                        sample = ScanResult(streams=[{"index": 0, "kind": "video", "codec": "h264",
                            "width": 320, "height": 240, "pixel_format": "yuv420p"}])
                        probe = copy.copy(backend)
                        if encoder in {"h264_nvenc", "hevc_nvenc"}:
                            device = getattr(backend, f"_ready_{'hevc' if encoder == 'hevc_nvenc' else 'h264'}_nvenc_device", None)
                            if device is not None:
                                probe.gpu_index = device
                        encoded = runner.run(command(probe, source, output, sample, "reencode", RecoveryOptions(profile="compatible_sdr", video_codec="hevc" if encoder.startswith("hevc_") or encoder == "libx265" else "h264"),
                            encoder, decoder), scratch, watch_file=output, max_file_bytes=4194304)
                        if not encoded.returncode and not encoded.limited and output.is_file() and output.stat().st_size:
                            decoded = runner.run([str(backend.ffmpeg), "-nostdin", "-v", "error", "-hwaccel", "none",
                                "-i", str(output), "-map", "0:v:0", "-f", "null", "-"], scratch)
                            cache[pair] = not decoded.returncode and not decoded.limited and not decoded.stderr.strip()
            except (VideoMateError, OSError) as error:
                if isinstance(error, VideoMateError) and error.code == "worker_cleanup_failed":
                    raise
        choice = pair if cache[pair] else ("software", encoder)
        if choice not in selected:
            selected.append(choice)
    return tuple(selected)


def qualify_devices(backend, routes):
    """Explicit NVENC device routing, qualified with generated frames only.

    Other APIs retain their qualified default adapter; aliases are not treated
    as additional devices. Never export adapter names or driver output.
    """
    selected = [(d, e, None) for d, e in routes if e not in {'h264_nvenc', 'hevc_nvenc'}]
    nvenc = next((e for _, e in routes if e in {'h264_nvenc', 'hevc_nvenc'}), None)
    if nvenc is None:
        return tuple(selected)
    from .models import ScanResult
    from .recovery import RecoveryOptions, command
    runner = Runner(timeout=min(10, backend.runner.timeout), output_limit=262144,
                    cancel_event=backend.runner.cancel_event, cleanup_blocked=backend.runner.cleanup_blocked)
    with qualification_scratch(runner, backend.scratch, 'devices-check-') as scratch:
        source = scratch / 'generated.mp4'
        generated = runner.run([str(backend.ffmpeg), '-nostdin', '-v', 'error', '-n', '-f', 'lavfi',
            '-i', f'testsrc2=size={ENCODER_CHECK_SIZE}:rate=24', '-frames:v', '3', '-c:v', 'libx264', '-threads', '1', str(source)],
            scratch, watch_file=source, max_file_bytes=4194304)
        if generated.returncode or generated.limited:
            return tuple(selected) or (('software', 'libx265' if nvenc == 'hevc_nvenc' else 'libx264', None),)
        sample = ScanResult(streams=[{'index': 0, 'kind': 'video', 'codec': 'h264', 'width': 320,
                                     'height': 240, 'pixel_format': 'yuv420p'}])
        preferred = next(d for d, e in routes if e == nvenc)
        # A bounded 16-device probe tolerates unavailable/unsupported indices.
        cached = getattr(backend, f"_ready_{'hevc' if nvenc == 'hevc_nvenc' else 'h264'}_nvenc_device", None)
        indices = ((cached,) + tuple(index for index in range(16) if index != cached)) if cached is not None else range(16)
        for device in indices:
            probe = copy.copy(backend)
            probe.gpu_index = device
            for decoder in (('cuda', 'software') if preferred == 'cuda' else ('software',)):
                output = scratch / f'generated-{device}-{decoder}.mp4'
                encoded = runner.run(command(probe, source, output, sample, 'reencode', RecoveryOptions(profile='compatible_sdr', video_codec='hevc' if nvenc == 'hevc_nvenc' else 'h264'),
                                             nvenc, decoder), scratch, watch_file=output, max_file_bytes=4194304)
                if encoded.returncode or encoded.limited or not output.is_file() or not output.stat().st_size:
                    continue
                checked = runner.run([str(backend.ffmpeg), '-nostdin', '-v', 'error', '-hwaccel', 'none',
                    '-i', str(output), '-map', '0:v:0', '-f', 'null', '-'], scratch)
                if not checked.returncode and not checked.limited and not checked.stderr.strip():
                    selected.append((decoder, nvenc, device))
                    break
    return tuple(selected) or (('software', 'libx265' if nvenc == 'hevc_nvenc' else 'libx264', None),)
