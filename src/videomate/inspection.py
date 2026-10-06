"""Backend-neutral inspection. Source access is preceded by an execution gate."""

from decimal import Decimal, InvalidOperation
from pathlib import Path

from .backend import classify_log
from .errors import VideoMateError
from .models import Depth, Finding, ScanResult
from .policy import DeniedScope
from .schema import AUDIO_CODECS, VIDEO_CODECS, get_schema, load_json
from .trace import record_trace, worker_trace
from .media_output import process_findings


def _integer(value, minimum=0, maximum=1000000000):
    try:
        if isinstance(value, bool) or not str(value).lstrip("-").isdigit():
            return None
        result = int(value)
        return result if minimum <= result <= maximum else None
    except (ValueError, TypeError):
        return None


def duration_us(value):
    try:
        seconds = Decimal(str(value))
        if not seconds.is_finite() or seconds < 0 or seconds > Decimal(9007199254):
            return None
        return int(seconds * 1000000)
    except (ValueError, InvalidOperation):
        return None


def _stream(raw):
    index = _integer(raw.get("index"), maximum=4095)
    if index is None:
        raise VideoMateError("invalid_export")
    props = get_schema()["$defs"]["stream"]["properties"]
    kind = raw.get("codec_type", "unknown")
    kind = kind if kind in props["kind"]["enum"] else "unknown"
    codec = raw.get("codec_name", "unknown")
    if isinstance(codec, str) and codec.startswith("pcm_"):
        codec = "pcm"
    allowed = VIDEO_CODECS if kind == "video" else AUDIO_CODECS if kind == "audio" else frozenset()
    codec = codec if codec in allowed else "unknown" if codec == "unknown" else "other"
    result = {"index": index, "kind": kind, "codec": codec,
              "coverage": "not_checked", "decode_status": "not_run"}
    for source, target in (("width", "width"), ("height", "height"), ("bits_per_raw_sample", "bit_depth"),
                           ("sample_rate", "sample_rate"), ("channels", "channels")):
        if source in raw:
            value = _integer(raw[source], props[target]["minimum"], props[target]["maximum"])
            if value is not None:
                result[target] = value
    for source, target in (("profile", "profile"), ("pix_fmt", "pixel_format")):
        if source in raw:
            value = str(raw[source]).lower().replace(" ", "")
            result[target] = value if value in props[target]["enum"] else "other"
    rate = str(raw.get("avg_frame_rate", "")).split("/")
    if len(rate) == 2:
        num, den = _integer(rate[0]), _integer(rate[1], minimum=1)
        if num is not None and den is not None:
            result.update(frame_rate_numerator=num, frame_rate_denominator=den)
    result["duration_us"] = duration_us(raw.get("duration"))
    return result


def _container(raw):
    names = str(raw).split(",")
    for aliases, name in (
        ({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}, "mp4_mov"),
        ({"matroska", "webm"}, "matroska_webm"), ({"asf"}, "asf_wmv"),
        ({"mpeg"}, "mpeg_ps"), ({"mpegts"}, "mpeg_ts"), ({"rm"}, "realmedia"),
        ({"avi"}, "avi"), ({"flv"}, "flv"), ({"ogg"}, "ogg"), ({"mxf"}, "mxf"),
    ):
        if aliases.intersection(names):
            return name
    return "other" if raw else "unknown"


def _fingerprint(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _technical(data):
    """Private numeric timing/properties used by recovery, never exported or printed."""
    def timestamp(value):
        try:
            number = Decimal(str(value)) * 1000000
            return int(number) if number.is_finite() and abs(number) <= 9007199254740991 else None
        except (ValueError, InvalidOperation):
            return None
    allowed = {
        "sample_fmt": {"u8", "u8p", "s16", "s16p", "s32", "s32p", "s64", "s64p", "flt", "fltp", "dbl", "dblp"},
        "channel_layout": {"mono", "stereo", "2.1", "3.0", "4.0", "quad", "5.0", "5.1", "5.1(side)", "7.1"},
        "color_transfer": {"unknown", "bt709", "gamma22", "gamma28", "smpte170m", "smpte240m", "linear", "iec61966-2-1", "bt2020-10", "bt2020-12", "smpte2084", "arib-std-b67"},
        "color_primaries": {"unknown", "bt709", "bt470m", "bt470bg", "smpte170m", "smpte240m", "film", "bt2020"},
        "color_space": {"unknown", "bt709", "fcc", "bt470bg", "smpte170m", "smpte240m", "rgb", "bt2020nc", "bt2020c"},
        "color_range": {"unknown", "tv", "pc"},
        "field_order": {"unknown", "progressive", "tt", "bb", "tb", "bt"},
    }
    result = {"start_us": timestamp(data.get("format", {}).get("start_time")), "streams": {}}
    for raw in data["streams"]:
        props = {name: raw.get(name) if raw.get(name) in values else "unknown" for name, values in allowed.items()}
        props["start_us"] = timestamp(raw.get("start_time"))
        props["bit_rate"] = _integer(raw.get("bit_rate"), minimum=1, maximum=2000000000)
        props["attached_pic"] = raw.get("disposition", {}).get("attached_pic") == 1 if type(raw.get("disposition", {})) is dict else False
        ratio = str(raw.get("sample_aspect_ratio", "")).split(":")
        props["sar"] = ratio if len(ratio) == 2 and all(x.isdigit() and len(x) <= 6 for x in ratio) else None
        result["streams"][str(raw["index"])] = props
    return result


def _decoded_something(output: bytes, kind: str) -> bool:
    # Progress values are used only for completion, NEVER exported as media times.
    values = {}
    for line in output.decode("ascii", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and key in {"progress", "frame", "out_time_us"}:
            values[key] = value.strip()
    counter = _integer(values.get("frame" if kind == "video" else "out_time_us"), minimum=1,
                       maximum=9007199254740991)
    return values.get("progress") == "end" and counter is not None


class Inspector:
    def __init__(self, backend, scope=None):
        self.backend, self.scope = backend, scope or DeniedScope()

    def inspect(self, source: Path, depth: Depth = Depth.FULL) -> ScanResult:
        self.scope.authorize(source)  # Must precede ANY source filesystem operation.
        source = source.absolute()
        result = ScanResult(depth=depth)
        try:
            before = _fingerprint(source)
            result.fingerprint = before
            self._inspect(source, result)
            result.technical["source_size"] = before[2]
            if before != _fingerprint(source):
                result.state, result.integrity = "partial", "inconclusive"
                result.findings.append(Finding("input_changed", evidence="io_reported"))
        except OSError:
            result.state, result.integrity = "failed", "inconclusive"
            result.findings.append(Finding("io_error", evidence="io_reported"))
            record_trace(result, worker_trace("inspection", outcome="failed", error_code="io_error"))
        except VideoMateError as error:
            if error.code == "worker_cleanup_failed":
                raise
            result.state, result.integrity = "failed", "inconclusive"
            result.findings.append(Finding("unclassified_error"))
            record_trace(result, worker_trace("inspection", outcome="failed", error_code=error.code))
        return result

    def _inspect(self, source: Path, result: ScanResult) -> None:
        probe = self.backend.probe(source)
        record_trace(result, worker_trace("probe", probe))
        result.findings.extend(classify_log(probe.stderr))
        if probe.limited:
            result.state = "partial"
            result.findings.append(Finding("resource_limit", evidence="policy"))
            return
        if probe.returncode != 0:
            result.integrity = "unreadable"
            self._operational_status(result)
            return
        try:
            data = load_json(probe.stdout, limit=2 * 1024 * 1024)
            if type(data) is not dict or type(data.get("streams")) is not list or len(data["streams"]) > 256:
                raise VideoMateError("invalid_export")
            if type(data.get("format", {})) is not dict or any(type(s) is not dict for s in data["streams"]):
                raise VideoMateError("invalid_export")
            result.streams = [_stream(raw) for raw in data["streams"]]
            if len({s["index"] for s in result.streams}) != len(result.streams):
                raise VideoMateError("invalid_export")
            result.container = _container(data.get("format", {}).get("format_name"))
            result.duration_us = duration_us(data.get("format", {}).get("duration"))
            result.technical = _technical(data)
            if hasattr(self.backend, "stream_codecs"):
                self.backend.stream_codecs = {s["index"]: s["codec"] for s in result.streams}
        except (VideoMateError, TypeError, ValueError, AttributeError):
            result.streams = []
            result.state = "partial"
            result.findings.append(Finding("unclassified_error"))
            record_trace(result, worker_trace("probe", outcome="failed", error_code="invalid_export"))
            return
        av = [s for s in result.streams if s["kind"] in {"video", "audio"}]
        if not av:
            result.integrity = "unsupported"
            result.findings.append(Finding("unsupported_format", evidence="container_reported"))
            return
        if result.depth == Depth.QUICK:
            result.integrity = "quick_check_only"
            self._operational_status(result)
            return
        for stream in av:
            decode = getattr(self.backend, "integrity_decode", self.backend.decode)
            outcome = decode(source, stream["index"])
            steps = getattr(self.backend, "last_decode_steps", [(outcome, "software", False)])
            for process, decoder, fallback in steps:
                record_trace(result, worker_trace("decode", process, stream_index=stream["index"],
                             threads=getattr(self.backend, "threads", 1), decoder=decoder,
                             outcome="fallback" if fallback else None))
            # Worker progress is private verification evidence, not an exported timestamp.
            progress = dict(line.split("=", 1) for line in outcome.stdout.decode("ascii", errors="replace").splitlines() if "=" in line)
            result.technical["streams"][str(stream["index"])]["decoded_us"] = _integer(progress.get("out_time_us"), maximum=9007199254740991)
            findings = process_findings(outcome, stream["index"])
            if not findings and any(fallback and any(f.category in {"decoder_error", "packet_error", "suspected_truncation"}
                    for f in process_findings(process)) for process, _, fallback in steps):
                findings.append(Finding("verification_error", severity="warning", evidence="verification", stream_index=stream["index"]))
            result.findings.extend(findings)
            stream["coverage"] = "full"
            stream["decode_status"] = "no_errors_detected"
            if outcome.limited:
                result.findings.append(Finding("resource_limit", evidence="policy", stream_index=stream["index"]))
                stream["coverage"], stream["decode_status"] = "partial", "failed"
            elif outcome.returncode != 0:
                stream["coverage"], stream["decode_status"] = "partial", "failed"
                if not findings:
                    result.findings.append(Finding("unclassified_error", stream_index=stream["index"]))
            elif not _decoded_something(outcome.stdout, stream["kind"]):
                stream["coverage"], stream["decode_status"] = "partial", "failed"
                result.findings.append(Finding("unclassified_error", stream_index=stream["index"]))
            elif findings:
                stream["decode_status"] = "errors_detected"
            if any(f.category == "unsupported_codec" for f in findings):
                stream["coverage"], stream["decode_status"] = "unsupported", "unsupported"
            if stream["coverage"] != "full":
                result.state = "partial"
        result.integrity = "no_errors_detected" if not result.findings else "inconclusive"
        self._operational_status(result)

    @staticmethod
    def _operational_status(result):
        categories = {f.category for f in result.findings}
        if "suspected_truncation" in categories:
            result.completeness = "suspected_truncated"
        if "io_error" in categories:
            result.state, result.integrity = "failed", "inconclusive"
        elif "policy_blocked" in categories:
            result.state, result.integrity = "blocked", "inconclusive"
        elif categories & {"unsupported_codec", "unsupported_format", "encrypted_stream"}:
            result.integrity = "unsupported"
        elif result.integrity != "unreadable" and categories & {"decoder_error", "packet_error", "container_error", "index_error", "timestamp_error", "missing_initialization", "suspected_truncation"}:
            result.integrity = "damage_detected" if any(f.severity == "error" for f in result.findings) else "suspected_damage"
        if "resource_limit" in categories:
            result.state, result.integrity = "partial", "inconclusive"
