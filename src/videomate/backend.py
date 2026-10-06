import os
import re
from pathlib import Path

from .errors import VideoMateError
from .models import Finding
from .policy import DeniedScope, plain_local_path
from .runner import Runner
from .execution import cpu_budget
from .hardware import HARDWARE_CODECS, decoder_args
from .media_output import process_findings

FORMATS = "mov,matroska,webm,avi,flv,mpeg,mpegts,asf,ogg,mxf,rm,yuv4mpegpipe,wav"
PROBE_ENTRIES = (
    "format=format_name,duration,start_time:"
    "stream=index,codec_type,codec_name,profile,pix_fmt,width,height,bits_per_raw_sample,"
    "avg_frame_rate,sample_rate,channels,duration,start_time,sample_fmt,channel_layout,bit_rate,"
    "color_transfer,color_primaries,color_space,color_range,sample_aspect_ratio,field_order:"
    "stream_disposition=attached_pic"
)


class FFmpegBackend:
    def __init__(self, ffmpeg: Path, ffprobe: Path, scratch: Path, runner: Runner | None = None, *, scope=None, threads=0, decoder="software", hardware_gate=None):
        self.ffmpeg, self.ffprobe = self._executable(ffmpeg), self._executable(ffprobe)
        self.scratch, self.runner = scratch, runner or Runner()
        self.scope = scope or DeniedScope()
        self.threads, self.decoder = cpu_budget(threads), decoder
        self.hardware_gate, self.stream_codecs, self.last_decode_steps = hardware_gate, {}, []

    @staticmethod
    def _executable(path: Path) -> Path:
        if not path.is_absolute():
            raise VideoMateError("backend_invalid")
        result = plain_local_path(path)
        if not result.is_file() or result.suffix.lower() in {".bat", ".cmd", ".ps1", ".py", ".sh"}:
            raise VideoMateError("backend_invalid")
        if os.name == "nt" and result.suffix.lower() != ".exe":
            raise VideoMateError("backend_invalid")
        return result

    def probe(self, source: Path):
        self.scope.authorize(source)
        return self.runner.run([str(self.ffprobe), "-hide_banner", "-v", "repeat+level+warning",
                                "-protocol_whitelist", "file", "-format_whitelist", FORMATS,
                                "-threads", "1", "-show_entries", PROBE_ENTRIES, "-of", "json", str(source)], self.scratch)

    def decode(self, source: Path, index: int):
        self.scope.authorize(source)
        if type(index) is not int or not 0 <= index <= 4095:
            raise VideoMateError("input_rejected")
        self.last_decode_steps = []
        if self.decoder != "software" and self.stream_codecs.get(index) in HARDWARE_CODECS:
            # Serialize GPU admission separately from the CPU pool. Cancellation
            # is checked while waiting, so queued GPU work remains stoppable.
            from .hardware import hardware_slot
            with hardware_slot(self):
                hardware = self._decode(source, index, self.decoder)
            fallback = not hardware.limited and bool(hardware.returncode != 0 or process_findings(hardware) or b"progress=end" not in hardware.stdout)
            self.last_decode_steps.append((hardware, self.decoder, fallback))
            if not fallback:
                return hardware
        software = self._decode(source, index, "software")
        self.last_decode_steps.append((software, "software", False))
        return software

    def integrity_decode(self, source: Path, index: int):
        # Hardware decoders can silently conceal damaged packets. Full health
        # decisions use software; hardware remains useful for recovery encoding.
        self.scope.authorize(source)
        if type(index) is not int or not 0 <= index <= 4095:
            raise VideoMateError("input_rejected")
        outcome = self._decode(source, index, "software")
        self.last_decode_steps = [(outcome, "software", False)]
        return outcome

    def _decode(self, source, index, decoder):
        return self.runner.run([str(self.ffmpeg), "-hide_banner", "-nostdin", "-nostats",
                                "-v", "repeat+level+warning", "-protocol_whitelist", "file,pipe",
                                "-format_whitelist", FORMATS, "-threads", str(self.threads),
                                "-filter_threads", "1", "-filter_complex_threads", "1",
                                # Inspection does not need a guessed speaker layout. Avoid
                                # FFmpeg's layout-guess warning without hiding other warnings.
                                "-guess_layout_max", "0", *decoder_args(decoder, native_frames=True), "-i", str(source),
                                "-map", f"0:{index}", "-progress", "pipe:1",
                                "-threads", "1", "-fps_mode", "passthrough", "-enc_time_base", "demux", "-f", "null", "-"], self.scratch, media_output=True)


_RULES = (
    (r"protocol .*not on whitelist|format .*not on whitelist", "policy_blocked", "policy"),
    (r"permission denied|input/output error|no such file", "io_error", "io_reported"),
    (r"decoder .*not found|unknown decoder|no decoder found|unsupported codec", "unsupported_codec", "decoder_reported"),
    (r"encrypted|decryption", "encrypted_stream", "container_reported"),
    (r"moov atom not found", "missing_initialization", "container_reported"),
    (r"partial file|truncated|premature end|ended prematurely", "suspected_truncation", "container_reported"),
    (r"invalid.*index|index.*invalid", "index_error", "container_reported"),
    (r"non.monoton|invalid.*timestamp|invalid.*dts", "timestamp_error", "container_reported"),
    (r"packet corrupt|corrupt.*packet", "packet_error", "container_reported"),
    (r"error.*decod|error submitting packet|invalid nal|decode_slice|corrupt decoded frame", "decoder_error", "decoder_reported"),
    (r"invalid data found|invalid.*header", "container_error", "container_reported"),
)


def classify_log(data: bytes, index: int | None = None, *, include_advisories=False) -> list[Finding]:
    aggregated = {}
    for line in data.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        level = re.search(r"\[(warning|error|fatal|panic)\]", line)
        severity = "warning" if level and level.group(1) == "warning" else "error"
        category, evidence = "unclassified_error", "decoder_reported"
        # This exact FFmpeg threading advisory is operational, not a media
        # finding. Keep it in diagnostics without suppressing other warnings.
        if re.fullmatch(r"(?:\[[A-Za-z0-9_]+ @ (?:0x)?[a-fA-F0-9]+\]\s*)?\[warning\] Application has requested [0-9]{1,4} threads\. Using a thread count greater than 16 is not recommended\.\s*", line):
            if not include_advisories:
                continue
            category, evidence = "thread_advisory", "policy"
        else:
            for pattern, code, source in _RULES:
                if re.search(pattern, line, re.IGNORECASE):
                    category, evidence = code, source
                    break
        key = (category, severity, evidence)
        aggregated[key] = min(1000000000, aggregated.get(key, 0) + 1)
    return [Finding(code, severity, evidence, count, index)
            for (code, severity, evidence), count in aggregated.items()]
