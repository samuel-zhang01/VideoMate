"""Closed technical worker diagnostics. No raw messages, paths or absolute time."""
from .errors import MESSAGES, VideoMateError

STAGES = {"probe", "decode", "encode", "verify_probe", "verify_decode", "plan", "publish", "inspection"}
DECODERS = {"none", "software", "d3d11va", "dxva2", "cuda", "qsv", "vaapi", "videotoolbox"}
ENCODERS = {"none", "libx264", "libx265", "ffv1", "h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox",
            "hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_videotoolbox"}
FIELDS = {"stage", "stream_index", "outcome", "return_code", "limit_reason", "elapsed_ms", "threads", "decoder", "encoder", "error_code", "messages"}
MESSAGE_CATEGORIES = {"policy_blocked", "io_error", "unsupported_codec", "encrypted_stream", "missing_initialization",
                      "suspected_truncation", "index_error", "timestamp_error", "packet_error", "decoder_error",
                      "container_error", "unclassified_error", "thread_advisory"}
MAX_RECORDS = 1024


def validate_trace(value):
    if type(value) is not dict or set(value) != FIELDS:
        raise VideoMateError("invalid_export")
    if any(type(value[key]) is not str for key in ("stage", "decoder", "encoder", "outcome", "limit_reason", "error_code")):
        raise VideoMateError("invalid_export")
    if (value["stage"] not in STAGES or value["decoder"] not in DECODERS or value["encoder"] not in ENCODERS
            or value["outcome"] not in {"completed", "failed", "limited", "fallback", "blocked", "cancelled"}
            or value["limit_reason"] not in {"none", "timeout", "output_limit", "candidate_limit", "disk_limit", "unknown"}
            or value["error_code"] not in {"none", *MESSAGES}):
        raise VideoMateError("invalid_export")
    for name, low, high, nullable in (("stream_index", 0, 4095, True), ("return_code", -2147483648, 4294967295, True),
                                     ("elapsed_ms", 0, 9007199254740991, False), ("threads", 1, 1024, False)):
        item = value[name]
        if nullable and item is None:
            continue
        if type(item) is not int or not low <= item <= high:
            raise VideoMateError("invalid_export")
    if type(value["messages"]) is not list or len(value["messages"]) > 32:
        raise VideoMateError("invalid_export")
    for item in value["messages"]:
        if (type(item) is not dict or set(item) != {"category", "severity", "count"}
                or type(item["category"]) is not str or item["category"] not in MESSAGE_CATEGORIES
                or type(item["severity"]) is not str or item["severity"] not in {"warning", "error"}
                or type(item["count"]) is not int or not 1 <= item["count"] <= 1000000000):
            raise VideoMateError("invalid_export")
    return value


def worker_trace(stage, process=None, *, stream_index=None, threads=1, decoder="none", encoder="none", outcome=None, error_code="none"):
    from .media_output import process_findings
    status = outcome or ("limited" if process and process.limited else "failed" if process and process.returncode else "completed")
    limit = getattr(process, "limit_reason", "none")
    if process and process.limited and limit == "none":
        limit = "unknown"
    if process and process.returncode and error_code == "none" and not process.limited:
        error_code = "ffmpeg_process_failed"
    record = {"stage": stage, "stream_index": stream_index, "outcome": status,
              "return_code": process.returncode if process else None,
              "limit_reason": limit,
              "elapsed_ms": getattr(process, "elapsed_ms", 0), "threads": threads,
              "decoder": decoder, "encoder": encoder, "error_code": error_code,
              "messages": [{"category": f.category, "severity": f.severity, "count": f.count}
                           for f in process_findings(process, include_advisories=True)[:32]] if process else []}
    return validate_trace(record)


def record_trace(result, record):
    validate_trace(record)
    if len(result.diagnostics) < MAX_RECORDS:
        result.diagnostics.append(dict(record))
    else:
        result.diagnostics_omitted += 1
