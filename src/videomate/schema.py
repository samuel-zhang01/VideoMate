"""Offline validator for the exact schema vocabulary shipped with VideoMate.

This is deliberately not a general JSON Schema implementation. Unsupported
schema keywords fail closed. CI also checks against a reference validator when
available. No URI resolution, format plug-ins or network operations exist here.
"""

import json
import math
import re
from importlib.resources import files

from .errors import VideoMateError

MAX_EXPORT_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 32


def _reject() -> None:
    raise VideoMateError("invalid_export")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        _reject()
    return value


def load_json(data: bytes, *, limit: int = MAX_EXPORT_BYTES):
    if len(data) > limit:
        raise VideoMateError("export_too_large")
    # Bound nesting before json.loads, respecting escaped string contents.
    depth, quoted, escaped = 0, False, False
    for char in data:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            if depth > MAX_JSON_DEPTH:
                _reject()
        elif char in (93, 125):
            depth -= 1
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_float=_finite_float,
                          parse_constant=lambda _: _reject())
    except (ValueError, UnicodeError, RecursionError):
        _reject()


def get_schema() -> dict:
    return json.loads(files("videomate").joinpath("export-schema.json").read_text(encoding="utf-8"))


def _matches_type(value, kind):
    return {
        "object": type(value) is dict,
        "array": type(value) is list,
        "string": type(value) is str,
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "null": value is None,
    }.get(kind, False)


_KEYWORDS = {
    "$schema", "$defs", "$ref", "title", "description", "type",
    "additionalProperties", "required", "properties", "const", "enum",
    "pattern", "minLength", "maxLength", "minimum", "maximum",
    "minItems", "maxItems", "items", "oneOf", "dependentRequired",
}


def validate_value(value, spec: dict, root: dict, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH or set(spec) - _KEYWORDS:
        _reject()
    if "$ref" in spec:
        ref = spec["$ref"]
        if not ref.startswith("#/$defs/") or ref.count("/") != 2:
            _reject()
        target = root["$defs"].get(ref.split("/")[-1])
        if target is None:
            _reject()
        validate_value(value, target, root, depth + 1)
        return
    if "oneOf" in spec:
        matches = 0
        for option in spec["oneOf"]:
            try:
                validate_value(value, option, root, depth + 1)
                matches += 1
            except VideoMateError:
                pass
        if matches != 1:
            _reject()
        return
    types = spec.get("type")
    if types and not any(_matches_type(value, t) for t in (types if isinstance(types, list) else [types])):
        _reject()
    if "const" in spec and (type(value) is not type(spec["const"]) or value != spec["const"]):
        _reject()
    if "enum" in spec and value not in spec["enum"]:
        _reject()
    if type(value) is dict:
        props = spec.get("properties", {})
        if spec.get("additionalProperties") is not False:
            _reject()
        if set(value) - set(props) or set(spec.get("required", [])) - set(value):
            _reject()
        for key, item in value.items():
            validate_value(item, props[key], root, depth + 1)
        for key, others in spec.get("dependentRequired", {}).items():
            if key in value and not set(others) <= set(value):
                _reject()
    elif type(value) is list:
        if not spec.get("minItems", 0) <= len(value) <= spec.get("maxItems", -1):
            _reject()
        for item in value:
            validate_value(item, spec["items"], root, depth + 1)
    elif type(value) is str:
        if not spec.get("minLength", 0) <= len(value) <= spec.get("maxLength", MAX_EXPORT_BYTES):
            _reject()
        if "pattern" in spec and re.search(spec["pattern"], value) is None:
            _reject()
    elif type(value) is int:
        if not spec.get("minimum", -math.inf) <= value <= spec.get("maximum", math.inf):
            _reject()


VIDEO_CODECS = frozenset({"h264", "hevc", "av1", "vp8", "vp9", "mpeg1video", "mpeg2video", "mpeg4", "msmpeg4v3", "wmv1", "wmv2", "wmv3", "vc1", "flv1", "vp6", "vp6f", "theora", "mjpeg", "ffv1", "dvvideo", "prores"})
AUDIO_CODECS = frozenset({"aac", "mp2", "mp3", "opus", "vorbis", "pcm", "flac", "ac3", "eac3", "dts", "wmav1", "wmav2"})


def validate_export(value: dict) -> None:
    schema = get_schema()
    validate_value(value, schema, schema)
    if not value["files"] and "migration_summary" not in value:
        _reject()
    if "migration_summary" in value:
        summary = value["migration_summary"]
        if (summary["processed_files"] + summary["unprocessed_files"] != summary["planned_files"]
                or summary["published_files"] + summary["excluded_files"] + summary["failed_files"] != summary["processed_files"]
                or summary.get("partial_files", 0) > summary["published_files"]
                or len(value["files"]) > summary["processed_files"]
                or any("migration" not in entry for entry in value["files"])):
            _reject()
        if summary["state"] == "complete" and (summary["unprocessed_files"] or summary["failed_files"]
                or summary["excluded_files"] or summary.get("partial_files", 0) or summary["stop_reason"] != "none"):
            _reject()
    references = set()
    for entry in value["files"]:
        if entry["file_ref"] in references:
            _reject()
        references.add(entry["file_ref"])
        indices = {s["index"] for s in entry["streams"]}
        if len(indices) != len(entry["streams"]):
            _reject()
        for stream in entry["streams"]:
            if stream["codec"] in VIDEO_CODECS and stream["kind"] != "video":
                _reject()
            if stream["codec"] in AUDIO_CODECS and stream["kind"] != "audio":
                _reject()
        av = [s for s in entry["streams"] if s["kind"] in {"audio", "video"}]
        if entry["integrity"] == "no_errors_detected":
            if entry["scan_depth"] != "full" or entry["scan_state"] != "complete":
                _reject()
            if not av or any(s["coverage"] != "full" or s["decode_status"] != "no_errors_detected" for s in av):
                _reject()
            if any(f["severity"] == "error" for f in entry["findings"]):
                _reject()
        for finding in entry["findings"]:
            idx = finding["stream_index"]
            if idx is not None and idx not in indices and not entry["streams_omitted"]:
                _reject()
            if (finding["interval"] is None) != (finding["localization"] == "unknown"):
                _reject()
        for item in entry["findings"] + entry["edits"]:
            for key in ("interval", "input_interval", "output_interval"):
                interval = item.get(key)
                if interval and interval["start_us"] > interval["end_us"]:
                    _reject()
        if entry["recovery_state"] in {"verified", "verified_with_losses"}:
            if any(check != "passed" for check in entry["verification"].values()):
                _reject()
            if not any(a["outcome"] == "succeeded" for a in entry["attempts"]):
                _reject()
            if entry["recovery_state"] == "verified" and entry.get("losses"):
                _reject()


def encode_export(value: dict) -> bytes:
    validate_export(value)
    parts, size = [], 0
    encoder = json.JSONEncoder(ensure_ascii=True, allow_nan=False, indent=2)
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode("utf-8")
        size += len(encoded)
        if size + 1 > MAX_EXPORT_BYTES:
            raise VideoMateError("export_too_large")
        parts.append(encoded)
    return b"".join(parts) + b"\n"
