"""Bounded recovery to new candidates, followed by independent full verification."""

import hashlib
import shutil
import copy
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from .backend import FFmpegBackend, FORMATS
from .errors import VideoMateError
from .inspection import Inspector, _fingerprint
from .models import Depth, ScanResult
from .policy import LocalFileScope, plain_local_path
from .hardware import ENCODERS, HARDWARE_CODECS, select_encoder, video_encoder_args, decoder_args, hardware_slot, qualify_codec_routes
from .trace import record_trace, worker_trace
from .encoding import RATE_MODES, LOUDNESS_MODES, SOFTWARE_PRESETS, video_rates, rate_args, audio_rates, candidate_limit, size_target
from .media_output import process_findings
from .publication import filesystem_reason, publish


PROFILES = ("preserve_decoded_samples", "compatible_sdr")
PIXELS = {"yuv420p", "yuv422p", "yuv444p", "yuv420p10le", "yuv422p10le", "yuv444p10le", "gray"}
PCM = {"u8": "pcm_u8", "u8p": "pcm_u8", "s16": "pcm_s16le", "s16p": "pcm_s16le",
       "s32": "pcm_s32le", "s32p": "pcm_s32le", "s64": "pcm_s64le", "s64p": "pcm_s64le",
       "flt": "pcm_f32le", "fltp": "pcm_f32le", "dbl": "pcm_f64le", "dblp": "pcm_f64le"}
MP4_COPY_CODECS = {"video": {"h264", "hevc", "mpeg4", "av1"},
                   "audio": {"aac", "mp3", "ac3", "eac3", "alac", "dts"}}
AAC_LAYOUTS = {"mono": 1, "stereo": 2, "2.1": 3, "3.0": 3, "4.0": 4,
               "quad": 4, "5.0": 5, "5.1": 6, "7.1": 8}


def mp4_copy_eligible(result, options):
    return all(s["codec"] in MP4_COPY_CODECS[s["kind"]] for s in selected_streams(result, options))


@dataclass(frozen=True)
class RecoveryOptions:
    strategy: str = "auto"
    profile: str = "preserve_decoded_samples"
    force: bool = False
    allow_track_loss: bool = False
    allow_shorter: bool = False
    partial_salvage: bool = False
    max_output_bytes: int = 0
    keep_start_us: int | None = None
    keep_end_us: int | None = None
    hardware_encoding: bool = True
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

    def resolved(self):
        self.validate()
        if self.convert_noncompliant_hevc:
            return replace(self, strategy="reencode", profile="compatible_sdr", force=True,
                           video_codec="hevc", audio_normalization="playback")
        return replace(self, strategy="auto", profile="compatible_sdr", force=True) if self.convert_all_mp4 else self

    def validate(self):
        if any(type(getattr(self, key)) is not bool for key in ("hardware_encoding", "convert_all_mp4", "convert_noncompliant_hevc", "force", "allow_track_loss", "allow_shorter", "partial_salvage", "mp4_faststart")):
            raise VideoMateError("invalid_arguments")
        if type(self.video_codec) is not str or self.video_codec not in {"h264", "hevc"} or (self.convert_all_mp4 and self.convert_noncompliant_hevc):
            raise VideoMateError("invalid_arguments")
        if self.video_codec == "hevc" and self.profile != "compatible_sdr" and not (self.convert_noncompliant_hevc or self.convert_all_mp4):
            raise VideoMateError("encoding_options_conflict")
        if (type(self.rate_control) is not str or self.rate_control not in RATE_MODES
                or type(self.size_policy) is not str or self.size_policy not in {"strict", "best_effort"}):
            raise VideoMateError("invalid_arguments")
        for key, low, high in (("video_bitrate_kbps", 50, 200000), ("target_size_mib", 1, 1048576),
                               ("quality_crf", 0, 51), ("max_shorter_percent", 0, 100), ("max_source_percent", 0, 10000),
                               ("size_tolerance_percent", 5, 100)):
            if type(getattr(self, key)) is not int or not low <= getattr(self, key) <= high:
                raise VideoMateError("invalid_arguments")
        if (type(self.strategy) is not str or self.strategy not in {"auto", "remux", "reencode"}
                or type(self.profile) is not str or self.profile not in PROFILES):
            raise VideoMateError("invalid_arguments")
        if type(self.max_output_bytes) is not int or (self.max_output_bytes != 0 and not 1024 * 1024 <= self.max_output_bytes <= 1024 ** 4):
            raise VideoMateError("invalid_arguments")
        if (type(self.audio_normalization) is not str or self.audio_normalization not in LOUDNESS_MODES
                or type(self.software_preset) is not str or self.software_preset not in SOFTWARE_PRESETS):
            raise VideoMateError("invalid_arguments")
        if type(self.audio_bitrate_kbps) is not int or self.audio_bitrate_kbps not in {0, 64, 96, 128, 160, 192, 256, 320}:
            raise VideoMateError("invalid_arguments")
        if (self.audio_normalization != "off" or self.audio_bitrate_kbps) and not (self.convert_all_mp4 or self.convert_noncompliant_hevc) and (self.profile != "compatible_sdr" or self.strategy == "remux"):
            raise VideoMateError("encoding_options_conflict")
        if self.convert_noncompliant_hevc and (self.rate_control != "auto" or self.keep_start_us is not None):
            raise VideoMateError("encoding_options_conflict")
        if (self.keep_start_us is None) != (self.keep_end_us is None):
            raise VideoMateError("invalid_arguments")
        if self.keep_start_us is not None:
            if (type(self.keep_start_us) is not int or type(self.keep_end_us) is not int
                    or not 0 <= self.keep_start_us < self.keep_end_us <= 9007199254740991
                    or self.strategy == "remux"):
                raise VideoMateError("invalid_arguments")


def empty_recovery(state="planned"):
    return {"recovery_state": state, "output_duration_us": None, "attempts": [], "edits": [], "losses": [],
            "notes": [],
            "verification": {"decode_check": "not_run", "stream_check": "not_run", "timing_check": "not_run"}}


def selected_streams(result, options):
    streams = [s for s in result.streams if s["kind"] in {"audio", "video"}
               and not result.technical.get("streams", {}).get(str(s["index"]), {}).get("attached_pic")]
    if not streams:
        raise VideoMateError("plan_no_av_streams")
    if len(streams) != len(result.streams) and not options.allow_track_loss:
        raise VideoMateError("plan_auxiliary_tracks")
    return streams


def plan(result: ScanResult, options: RecoveryOptions) -> list[str]:
    options = options.resolved()
    categories = {f.category for f in result.findings}
    if result.state in {"failed", "blocked", "cancelled"}:
        raise VideoMateError("plan_inspection_failed")
    if result.integrity in {"unreadable", "unsupported"}:
        raise VideoMateError("plan_input_" + result.integrity)
    if categories & {"input_changed", "resource_limit", "missing_initialization", "io_error", "policy_blocked"}:
        raise VideoMateError("plan_source_evidence")
    selected_streams(result, options)
    audio_changes = options.audio_normalization != "off" or options.audio_bitrate_kbps != 0
    def feasible(strategies):
        selected = []
        blocked = None
        for strategy in strategies:
            try:
                if strategy == "remux" and options.profile == "compatible_sdr" and not mp4_copy_eligible(result, options):
                    raise VideoMateError("plan_mp4_codec")
                if strategy == "remux" and options.profile == "compatible_sdr" and options.video_codec == "hevc" and any(
                        s["kind"] == "video" and s["codec"] != "hevc" for s in selected_streams(result, options)):
                    raise VideoMateError("plan_mp4_codec")
                if strategy != "remux":
                    encoding_options(result, selected_streams(result, options), options.profile, options=options)
                selected.append(strategy)
            except VideoMateError as error:
                blocked = error
                continue
        if not selected:
            raise blocked or VideoMateError("recovery_blocked")
        return selected
    if options.keep_start_us is not None:
        if result.duration_us is None or options.keep_end_us > result.duration_us:
            raise VideoMateError("plan_trim_range")
        return feasible(["section_salvage"])
    if result.integrity == "no_errors_detected" and not options.force:
        return []
    if audio_changes:
        return feasible(["reencode"])
    if options.strategy != "auto":
        return feasible([options.strategy])
    if options.profile == "compatible_sdr" and options.video_codec == "hevc" and any(
            s["kind"] == "video" and s["codec"] != "hevc" for s in selected_streams(result, options)):
        return feasible(["reencode"])
    if options.profile == "compatible_sdr" and options.rate_control in {"quality", "bitrate"}:
        return feasible(["reencode"])
    if options.profile == "compatible_sdr":
        return feasible(["remux", "reencode"])
    if categories & {"decoder_error", "packet_error"}:
        return feasible(["reencode"])
    return feasible(["remux", "reencode"])


def encoding_options(result, streams, profile, encoder="libx264", *, options=None, rate_factor=1.0, codec_threads=None):
    args, video_number, audio_number = [], 0, 0
    options = options or RecoveryOptions(profile=profile)
    rates = video_rates(result, streams, options) if profile == "compatible_sdr" else []
    rates = [max(50000, min(200000000, int(rate * rate_factor))) for rate in rates]
    audio = audio_rates(result, streams, options) if profile == "compatible_sdr" else []
    for stream in streams:
        props = result.technical.get("streams", {}).get(str(stream["index"]), {})
        if stream["kind"] == "video":
            pix = stream.get("pixel_format")
            if pix not in PIXELS:
                raise VideoMateError("plan_pixel_format")
            if props.get("field_order", "unknown") not in {"unknown", "progressive"}:
                raise VideoMateError("plan_interlaced")
            # HDR side-data preservation is not yet verified for transcoding.
            if props.get("color_transfer") in {"smpte2084", "arib-std-b67"}:
                raise VideoMateError("plan_hdr")
            if profile == "compatible_sdr":
                if pix != "yuv420p":
                    raise VideoMateError("plan_pixel_format")
                if stream.get("width", 1) % 2 or stream.get("height", 1) % 2:
                    raise VideoMateError("plan_dimensions")
                if props.get("color_transfer") in {"smpte2084", "arib-std-b67"} or props.get("color_primaries") == "bt2020":
                    raise VideoMateError("plan_hdr")
                # Encoder readiness uses its own bounded synthetic policy; the
                # actual candidate uses the operator's chosen rate policy.
                video_encoder_args(encoder, video_number)  # Closed encoder validation.
                args += [f"-c:v:{video_number}", encoder, *rate_args(encoder, video_number, rates[video_number], options)]
                if encoder == "libx265" and codec_threads is not None:
                    args += [f"-x265-params:v:{video_number}", f"pools={codec_threads}:frame-threads=1"]
                if encoder in {"h264_videotoolbox", "hevc_videotoolbox"}:
                    args += [f"-allow_sw:v:{video_number}", "0"]
            else:
                args += [f"-c:v:{video_number}", "ffv1", f"-level:v:{video_number}", "3", f"-slicecrc:v:{video_number}", "1"]
            args += [f"-pix_fmt:v:{video_number}", "+" + pix, f"-fps_mode:v:{video_number}", "passthrough"]
            for key, flag in (("color_range", "color_range"), ("color_transfer", "color_trc"),
                              ("color_primaries", "color_primaries"), ("color_space", "colorspace")):
                if props.get(key) not in (None, "unknown"):
                    args += [f"-{flag}:v:{video_number}", props[key]]
            video_number += 1
        else:
            if not stream.get("sample_rate") or not stream.get("channels"):
                raise VideoMateError("plan_audio_properties")
            if profile == "compatible_sdr":
                layout = {1: "mono", 2: "stereo"}.get(stream["channels"], props.get("channel_layout"))
                if AAC_LAYOUTS.get(layout) != stream["channels"] or stream["sample_rate"] not in {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 88200, 96000}:
                    raise VideoMateError("plan_audio_layout")
                args += [f"-c:a:{audio_number}", "aac", f"-b:a:{audio_number}", str(audio[audio_number])]
                args += [f"-channel_layout:a:{audio_number}", layout]
                if options.audio_normalization != "off":
                    loudness = -16 if options.audio_normalization == "playback" else -23
                    args += [f"-filter:a:{audio_number}", f"loudnorm=I={loudness}:TP=-1.5:LRA=11:linear=false:print_format=none"]
            else:
                codec = PCM.get(props.get("sample_fmt"))
                if codec is None:
                    raise VideoMateError("plan_audio_samples")
                args += [f"-c:a:{audio_number}", codec]
            args += [f"-ar:a:{audio_number}", str(stream["sample_rate"])]
            audio_number += 1
    return args


def command(backend, source, target, result, strategy, options, encoder="libx264", decoder="software", *, rate_factor=1.0):
    options = options.resolved()
    streams = selected_streams(result, options)
    codec_threads = max(1, getattr(backend, "threads", 1) // max(1, 2 * len(streams)))
    args = [str(backend.ffmpeg), "-nostdin", "-hide_banner", "-nostats", "-n", "-v", "repeat+level+warning",
            "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS, "-threads", str(codec_threads),
            "-filter_threads", "1", "-filter_complex_threads", "1",
            "-guess_layout_max", "0", "-copyts", "-start_at_zero"]
    if strategy != "remux":
        args += ["-err_detect", "ignore_err", *decoder_args(decoder)]
        device = getattr(backend, 'gpu_index', None)
        if device is not None:
            if type(device) is not int or not 0 <= device < 16:
                raise VideoMateError('invalid_arguments')
            if decoder == 'cuda':
                args += ['-hwaccel_device', str(device)]
    args += ["-i", str(source)]
    for stream in streams:
        args += ["-map", f"0:{stream['index']}"]
    # Metadata is deliberately excluded, disclosed in the recovery result.
    args += ["-map_metadata", "-1", "-map_metadata:s", "-1", "-map_chapters", "-1"]
    if strategy == "remux":
        args += ["-c", "copy"]
    else:
        args += encoding_options(result, streams, options.profile, encoder, options=options,
                                 rate_factor=rate_factor, codec_threads=codec_threads)
        if encoder in {'h264_nvenc', 'hevc_nvenc'} and getattr(backend, 'gpu_index', None) is not None:
            args += ['-gpu', str(backend.gpu_index)]
        if decoder != "software" and options.profile == "compatible_sdr":
            # GPU download commonly yields NV12. Explicitly repack the same
            # 8-bit 4:2:0 samples into planar YUV without changing dimensions.
            # Keep '+' pixel-format enforcement: no other implicit conversion.
            for number, stream in enumerate(s for s in streams if s["kind"] == "video"):
                args += [f"-filter:v:{number}", "scale=iw:ih:flags=bitexact,format=yuv420p"]
    if strategy == "section_salvage":
        args += ["-ss", f"{options.keep_start_us / 1000000:.6f}", "-t", f"{(options.keep_end_us - options.keep_start_us) / 1000000:.6f}"]
    if options.profile == "compatible_sdr":
        args += ["-movflags", "+faststart+write_colr" if options.mp4_faststart else "+write_colr", "-f", "mp4"]
    else:
        args += ["-f", "matroska"]
    # Runner watches size and checks again after exit. FFmpeg -fs can finish a
    # truncated file successfully, which must not be mistaken for allowed loss.
    args += ["-threads", str(codec_threads), "-max_muxing_queue_size", "4096", "-progress", "pipe:1", str(target)]
    return args


def verification(original, candidate, strategy, options, issues=None):
    issues = issues if issues is not None else []
    checks = {"decode_check": "passed" if candidate.state == "complete" and candidate.integrity == "no_errors_detected" else "failed",
              "stream_check": "passed", "timing_check": "passed"}
    expected = selected_streams(original, options)
    if checks["decode_check"] != "passed":
        issues.append("decode_check_failed")
    actual = candidate.streams
    if len(expected) != len(actual):
        checks["stream_check"] = "failed"
        issues.append("stream_count_changed")
    for before, after in zip(expected, actual):
        fields = ("width", "height", "pixel_format") if before["kind"] == "video" else ("sample_rate", "channels")
        if before["kind"] != after["kind"] or any(before.get(k) != after.get(k) for k in fields):
            checks["stream_check"] = "failed"
            issues.append("stream_properties_changed")
        if strategy == "remux" and before["codec"] != after["codec"]:
            checks["stream_check"] = "failed"
            issues.append("codec_changed")
        if strategy != "remux" and options.profile == "compatible_sdr":
            codec = options.video_codec if before["kind"] == "video" else "aac"
            if after.get("codec") != codec:
                checks["stream_check"] = "failed"
                issues.append("codec_changed")
        # avg_frame_rate reflects observed frames, so damaged sources can
        # legitimately report a different average after packet concealment.
        if before["kind"] == "video" and original.integrity == "no_errors_detected":
            bn, bd = before.get("frame_rate_numerator"), before.get("frame_rate_denominator")
            an, ad = after.get("frame_rate_numerator"), after.get("frame_rate_denominator")
            if all(isinstance(v, int) and v > 0 for v in (bn, bd, an, ad)) and abs(bn / bd - an / ad) > max(0.01, bn / bd * 0.001):
                checks["timing_check"] = "failed"
                issues.append("frame_rate_changed")
        bp = original.technical.get("streams", {}).get(str(before["index"]), {})
        ap = candidate.technical.get("streams", {}).get(str(after["index"]), {})
        for key in ("color_transfer", "color_primaries", "color_space", "color_range", "sar", "channel_layout"):
            if bp.get(key) not in (None, "unknown") and bp.get(key) != ap.get(key):
                checks["stream_check"] = "failed"
                issues.append("color_or_layout_changed")
        # Compare relative starts only; absolute input times never enter reports.
        bs, cs = bp.get("start_us"), ap.get("start_us")
        origin, corigin = original.technical.get("start_us"), candidate.technical.get("start_us")
        if all(x is not None for x in (bs, cs, origin, corigin)) and strategy != "section_salvage":
            if abs((bs - origin) - (cs - corigin)) > 100000:
                checks["timing_check"] = "failed"
                issues.append("av_start_offset_changed")
        bdur, cdur = bp.get("decoded_us"), ap.get("decoded_us")
        if strategy != "section_salvage" and bdur is not None and cdur is not None:
            delta = cdur - bdur
            if delta > 250000 or (delta < -250000 and not options.allow_shorter):
                checks["timing_check"] = "failed"
                issues.append("decoded_duration_changed")
            if delta < -250000 and options.allow_shorter and -delta * 100 > bdur * options.max_shorter_percent:
                checks["timing_check"] = "failed"
                issues.append("shortening_budget_exceeded")
    expected_duration = options.keep_end_us - options.keep_start_us if strategy == "section_salvage" else original.duration_us
    if expected_duration is None or candidate.duration_us is None:
        checks["timing_check"] = "inconclusive" if checks["timing_check"] != "failed" else "failed"
        issues.append("duration_unknown")
    else:
        delta = candidate.duration_us - expected_duration
        if delta > 250000 or (delta < -250000 and not options.allow_shorter):
            checks["timing_check"] = "failed"
            issues.append("output_longer" if delta > 0 else "output_shorter")
        if delta < -250000 and options.allow_shorter and -delta * 100 > expected_duration * options.max_shorter_percent:
            checks["timing_check"] = "failed"
            issues.append("shortening_budget_exceeded")
    return checks


class RecoveryEngine:
    def __init__(self, backend, scope, candidate_root, output_root, source_root, *, output_stem=None, output_hash=True, publication_hook=None):
        self.backend, self.scope = backend, scope
        self.candidate_root, self.output_root, self.source_root = candidate_root, output_root, source_root
        if output_stem is not None and (Path(output_stem).name != output_stem or output_stem in {"", ".", ".."}):
            raise VideoMateError("input_rejected")
        self.output_stem = output_stem
        self.output_hash = output_hash
        self.publication_hook = publication_hook

    def recover(self, source: Path, original: ScanResult, options: RecoveryOptions, *, execute=True):
        self.scope.authorize(source)
        options = options.resolved()
        state = original.recovery = empty_recovery()
        state["private_candidate_limit"] = candidate_limit(original, options)
        state["rate_control"] = options.rate_control if options.profile == "compatible_sdr" else "lossless"
        try:
            strategies = plan(original, options)
        except VideoMateError as error:
            state["recovery_state"] = "blocked"
            state["notes"] = ["plan_blocked"]
            record_trace(original, worker_trace("plan", outcome="blocked", error_code=error.code))
            return original
        if not strategies:
            state["recovery_state"] = "not_needed"
            return original
        if original.technical.get("size_estimate_fallback"):
            state["notes"].append("size_estimate_fallback")
        if not execute:
            state["private_plan"] = strategies
            return original
        if original.fingerprint is None or tuple(original.fingerprint) != _fingerprint(source):
            state["recovery_state"] = "blocked"
            return original
        software_encoder = "libx265" if options.video_codec == "hevc" else "libx264"
        routes = ()
        if options.hardware_encoding and options.profile == "compatible_sdr" and any(s != "remux" for s in strategies) and any(s["kind"] == "video" for s in original.streams):
            routes = (getattr(self.backend, "hardware_routes", None)
                      if getattr(self.backend, "hardware_route_codec", options.video_codec) == options.video_codec else None)
            if routes is None:
                ready = select_encoder(self.backend, all_ready=True, codec=options.video_codec)
                ready = (ready,) if isinstance(ready, str) else ready
                routes = tuple((getattr(self.backend, "decoder", "software"), encoder,
                                getattr(self.backend, f"_ready_{options.video_codec}_nvenc_device", None)
                                if encoder in {"h264_nvenc", "hevc_nvenc"} else getattr(self.backend, "gpu_index", None))
                               for encoder in ready
                               if encoder in ENCODERS[options.video_codec])
                self.backend.hardware_routes = routes
                self.backend.hardware_route_codec = options.video_codec
            routes = tuple(route for route in routes if route[1] in ENCODERS[options.video_codec])
        attempts = []
        videos = [s for s in selected_streams(original, options) if s["kind"] == "video"]
        decoder_eligible = bool(videos) and all(s["codec"] in HARDWARE_CODECS for s in videos)
        for strategy in strategies:
            if strategy == "remux":
                attempts.append((strategy, "none", "software", None, False))
                continue
            if options.profile == "preserve_decoded_samples":
                attempts.append((strategy, "ffv1", "software", None, False))
                continue
            # Every qualified GPU encoder gets a chance before software encoding.
            # An unsupported source decoder does not disqualify its GPU encoder.
            for route_decoder, encoder, device in routes:
                decoder = route_decoder if decoder_eligible else "software"
                if decoder != "software" and not hasattr(self.backend, "hardware_route_gates"):
                    decoder, encoder = qualify_codec_routes(self.backend, ((decoder, encoder),))[0]
                attempts.append((strategy, encoder, decoder, device, False))
                if decoder != "software":
                    attempts.append((strategy, encoder, "software", device, False))
            # With hardware encoding disabled or unavailable, a qualified
            # hardware decoder can still precede the full-software route.
            if not routes and decoder_eligible and getattr(self.backend, "decoder", "software") != "software":
                decoder, _ = qualify_codec_routes(self.backend, ((self.backend.decoder, software_encoder),))[0]
                if decoder != "software":
                    attempts.append((strategy, software_encoder, decoder, None, False))
            attempts.append((strategy, software_encoder, "software", None, False))
        if options.partial_salvage and options.strategy != "remux" and (original.integrity != "no_errors_detected" or original.completeness == 'suspected_truncated') and original.duration_us:
            attempts.append(("reencode", software_encoder if options.profile == "compatible_sdr" else "ffv1", "software", None, True))
        rate_factor, size_retried = 1.0, False
        metadata_preflight = False
        for attempt_index, (strategy, encoder, decoder, device, salvage) in enumerate(attempts):
            profile = "container_repair" if strategy == "remux" else options.profile
            attempt = {"strategy": strategy, "profile": profile, "outcome": "failed", "reason": "backend_error", "encoder": encoder,
                       "decoder": decoder, "verification_issues": []}
            state["attempts"].append(attempt)
            suffix = ".mp4" if options.profile == "compatible_sdr" else ".mkv"
            token = uuid4().hex
            candidate = self.candidate_root / (token + suffix)
            stage = "encode"
            try:
                self.scope.authorize(source)
                if tuple(original.fingerprint) != _fingerprint(source):
                    attempt.update(outcome="blocked", reason="input_changed")
                    break
                route_backend = copy.copy(self.backend)
                route_backend.gpu_index = device
                args = command(route_backend, source, candidate, original, strategy, options, encoder, decoder, rate_factor=rate_factor)
                if shutil.disk_usage(self.candidate_root).free < 64 * 1024 ** 2:
                    raise VideoMateError("disk_limit")
                gate = getattr(self.backend, "hardware_route_gates", {}).get((encoder, device))
                with hardware_slot(self.backend, decoder != "software" or encoder in ENCODERS[options.video_codec], gate=gate):
                    outcome = self.backend.runner.run(args, self.backend.scratch, watch_file=candidate,
                        max_file_bytes=state["private_candidate_limit"], media_output=True)
                record_trace(original, worker_trace("encode", outcome, threads=getattr(self.backend, "threads", 1),
                                                   decoder=decoder, encoder=encoder))
                if outcome.limited:
                    attempt["reason"] = "resource_limit"
                    # A single GPU timeout is not evidence that every other
                    # qualified encoder is unusable. Runner has already joined
                    # the process (or raised worker_cleanup_failed) here.
                    if outcome.limit_reason == "timeout" and encoder in ENCODERS[options.video_codec]:
                        continue
                    break
                if tuple(original.fingerprint) != _fingerprint(source):
                    attempt.update(outcome="blocked", reason="input_changed")
                    break
                if not candidate.is_file() or candidate.stat().st_size == 0:
                    continue
                if state["private_candidate_limit"] is not None and candidate.stat().st_size >= state["private_candidate_limit"]:
                    attempt["reason"] = "resource_limit"
                    break
                if outcome.returncode != 0 and not salvage:
                    continue
                target_bytes = size_target(original, options)
                finished_bytes = candidate.stat().st_size
                if target_bytes and finished_bytes * 100 > target_bytes * (100 + options.size_tolerance_percent):
                    attempt["reason"] = "size_target_exceeded"
                    if strategy == "remux":
                        # Stream copy cannot adjust bitrate. Try the planned
                        # encoder instead, retaining its one adjustment retry.
                        if attempt_index + 1 == len(attempts) and options.size_policy == "strict":
                            state["notes"].append("size_target_exceeded")
                        if attempt_index + 1 < len(attempts) or options.size_policy == "strict":
                            continue
                    if strategy != "remux" and not size_retried and videos:
                        # One extra pass, with the same qualified backend first.
                        # All remaining fallbacks inherit the revised video rate.
                        rate_factor = max(0.01, min(0.95, target_bytes * 0.95 / finished_bytes))
                        size_retried = True
                        state["notes"].append("size_adjustment_retry")
                        attempts.insert(attempt_index + 1, (strategy, encoder, decoder, device, salvage))
                        continue
                    if options.size_policy == "strict":
                        if attempt_index + 1 == len(attempts):
                            state["notes"].append("size_target_exceeded")
                            break
                        continue
                # A successful exit is necessary but insufficient. After a
                # previous timing/stream rejection, cheaply reject later
                # candidates with the same probe-visible mismatch before a
                # full software decode. Any candidate that passes this screen
                # still receives the original independent full verification.
                candidate_scope = LocalFileScope(frozenset({candidate}), self.source_root)
                backend = FFmpegBackend(self.backend.ffmpeg, self.backend.ffprobe, self.backend.scratch,
                                        self.backend.runner, scope=candidate_scope, threads=getattr(self.backend, "threads", 1))
                checked_options = replace(options, allow_shorter=True, max_shorter_percent=100) if salvage else options
                if metadata_preflight:
                    quick = Inspector(backend, candidate_scope).inspect(candidate, Depth.QUICK)
                    for detail in quick.diagnostics:
                        record_trace(original, {**detail, "stage": "verify_probe"})
                    if quick.state == "complete" and quick.integrity == "quick_check_only":
                        quick_issues = []
                        quick_checks = verification(original, quick, strategy, checked_options, quick_issues)
                        if quick_checks["stream_check"] != "passed" or quick_checks["timing_check"] != "passed":
                            quick_checks["decode_check"] = "not_run"
                            quick_issues = [issue for issue in quick_issues if issue != "decode_check_failed"]
                            attempt["verification"] = dict(quick_checks)
                            attempt["verification_issues"] = sorted(set(quick_issues))
                            attempt["reason"] = "verification_failed"
                            state["verification"], state["output_duration_us"] = quick_checks, quick.duration_us
                            continue
                checked = Inspector(backend, candidate_scope).inspect(candidate, Depth.FULL)
                for detail in checked.diagnostics:
                    record_trace(original, {**detail, "stage": "verify_probe" if detail["stage"] == "probe" else "verify_decode"})
                issues = []
                checks = verification(original, checked, strategy, checked_options, issues)
                metadata_preflight |= checks["stream_check"] != "passed" or checks["timing_check"] != "passed"
                if salvage and (checked.duration_us is None or checked.duration_us < max(1, min(original.duration_us // 100, 1_000_000))):
                    checks["timing_check"] = "failed"
                    issues.append("salvage_too_short")
                attempt["verification"] = dict(checks)
                attempt["verification_issues"] = sorted(set(issues))
                state["verification"], state["output_duration_us"] = checks, checked.duration_us
                if any(f.category == "resource_limit" for f in checked.findings):
                    attempt["reason"] = "resource_limit"
                    break
                if any(check != "passed" for check in checks.values()):
                    attempt["reason"] = "verification_failed"
                    continue
                if tuple(original.fingerprint) != _fingerprint(source):
                    attempt.update(outcome="blocked", reason="input_changed")
                    break
                losses = ["metadata_removed"]
                if strategy != "remux" and options.profile == "compatible_sdr":
                    losses.append("lossy_encoding")
                    if options.audio_normalization != "off" and any(s["kind"] == "audio" for s in selected_streams(original, options)):
                        losses.append("audio_normalized")
                        state["notes"].append("loudness_playback" if options.audio_normalization == "playback" else "loudness_broadcast")
                if salvage and (outcome.returncode != 0 or checked.duration_us < original.duration_us - 250000):
                    losses.append("partial_salvage")
                    state["notes"].append("partial_salvage_verified")
                if len(selected_streams(original, options)) != len(original.streams):
                    losses.append("tracks_omitted")
                if original.completeness == "suspected_truncated":
                    losses.append("source_incomplete")
                if original.integrity != "no_errors_detected" or process_findings(outcome) or outcome.returncode:
                    losses.append("concealment_possible" if strategy != "remux" else "packet_drop_possible")
                    if strategy != "remux":
                        state["edits"].append({"action": "decoder_concealment_suspected", "input_interval": None,
                                               "output_interval": None, "timing_confidence": "unknown"})
                if original.duration_us is not None and checked.duration_us is not None and abs(original.duration_us - checked.duration_us) > 250000:
                    losses.append("timing_changed")
                if strategy == "section_salvage":
                    for start, end, output in ((0, options.keep_start_us, 0), (options.keep_end_us, original.duration_us, options.keep_end_us - options.keep_start_us)):
                        if end > start:
                            state["edits"].append({"action": "cut", "input_interval": {"start_us": start, "end_us": end},
                                                   "output_interval": {"start_us": output, "end_us": output}, "timing_confidence": "reported"})
                stage = "publish"
                plain_local_path(self.output_root)
                self.output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
                plain_local_path(self.output_root)
                checksum = None
                if self.output_hash:
                    value = hashlib.sha256()
                    with candidate.open("rb") as verified_file:
                        while block := verified_file.read(1024 * 1024):
                            if self.backend.runner.cancel_event and self.backend.runner.cancel_event.is_set():
                                raise KeyboardInterrupt()
                            value.update(block)
                    checksum = value.hexdigest()
                if self.backend.runner.cancel_event and self.backend.runner.cancel_event.is_set():
                    raise KeyboardInterrupt()
                candidate_bytes = candidate.stat().st_size
                attempt.update(outcome="succeeded", reason="partial_salvage" if "partial_salvage" in losses else "none")
                state["losses"] = sorted(set(losses))
                if "timing_changed" in losses:
                    state["notes"].append("duration_changed")
                if target_bytes:
                    state["notes"].append("size_target_approximate")
                    state["notes"].append("size_above_target" if candidate_bytes * 100 > target_bytes * (100 + options.size_tolerance_percent)
                        else "size_below_target" if candidate_bytes * 100 < target_bytes * (100 - options.size_tolerance_percent) else "size_target_met")
                state["recovery_state"] = "verified_with_losses" if losses else "verified"
                for collision in range(1001):
                    name = token if self.output_stem is None else self.output_stem + ("" if collision == 0 else f".recovered-{collision}")
                    destination = self.output_root / (name + suffix)
                    if self.publication_hook:
                        state["private_output"] = str(destination)
                        state["private_output_bytes"] = candidate_bytes
                        self.publication_hook(candidate, destination, original, bytes.fromhex(checksum))
                    try:
                        publish(candidate, destination)
                        break
                    except VideoMateError as error:
                        if error.code != "output_exists" or self.output_stem is None or collision == 1000:
                            raise
                record_trace(original, worker_trace("publish"))
                state["private_output"] = str(destination)
                state["private_output_bytes"] = candidate_bytes
                if checksum is not None:
                    state["private_output_sha256"] = checksum
                if encoder in ENCODERS[options.video_codec]:
                    # Each migration lane owns its backend. Prefer a route that
                    # actually published a verified file on later inputs.
                    preferred_decoder = decoder if decoder_eligible else next(
                        (route[0] for route in self.backend.hardware_routes if route[1:] == (encoder, device)), decoder)
                    preferred = (preferred_decoder, encoder, device)
                    self.backend.hardware_routes = (preferred,) + tuple(
                        route for route in self.backend.hardware_routes if route[1:] != preferred[1:])
                return original
            except KeyboardInterrupt:
                attempt.update(outcome="cancelled", reason="operator_cancelled")
                state["recovery_state"] = "failed"
                raise
            except VideoMateError as error:
                if error.code == "worker_cleanup_failed":
                    self.backend.runner.cleanup_blocked.set()
                    raise
                attempt.update(outcome="blocked", reason="resource_limit" if error.code == "disk_limit" else "policy_limit")
                record_trace(original, worker_trace(stage, outcome="blocked", error_code=error.code, decoder=decoder, encoder=encoder))
                if stage == "publish":
                    state["private_failure_code"] = error.code
                    break
            except OSError as error:
                code = filesystem_reason(error, "output_publish_failed") if stage == "publish" else "io_error"
                attempt.update(reason="backend_error")
                record_trace(original, worker_trace(stage, outcome="failed", error_code=code, decoder=decoder, encoder=encoder))
                if stage == "publish":
                    state["private_failure_code"] = code
                    break
            finally:
                # Failed attempts are never reused by resume. Remove only this
                # exact random candidate after its workers have exited; do not
                # accumulate full rejected encodes until the batch ends.
                if not self.backend.runner.cleanup_blocked.is_set() and candidate.exists():
                    plain_local_path(candidate).unlink()
        state["recovery_state"] = "verification_inconclusive" if any(a["reason"] == "verification_failed" for a in state["attempts"]) else "failed"
        return original
