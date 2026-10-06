"""Projection from typed inspection results, never redaction of raw logs."""

import hashlib
import hmac
import platform
import secrets
from itertools import islice
from uuid import UUID

from . import __version__
from .errors import VideoMateError
from .models import ScanResult
from .schema import encode_export, get_schema
from .trace import MAX_RECORDS, validate_trace


class ExportScope:
    def __init__(self, key: bytes, nonce: bytes | None = None):
        if type(key) is not bytes or len(key) != 32:
            raise VideoMateError("invalid_export")
        nonce = secrets.token_bytes(16) if nonce is None else nonce
        if type(nonce) is not bytes or len(nonce) != 16:
            raise VideoMateError("invalid_export")
        self.nonce = nonce.hex()
        self._key = hmac.digest(key, b"videomate/export/v1\0" + nonce, hashlib.sha256)

    def reference(self, kind: str, identifier: UUID) -> str:
        if kind not in {"file", "job"} or not isinstance(identifier, UUID):
            raise VideoMateError("invalid_export")
        return kind[0] + "_" + hmac.digest(self._key, kind.encode("ascii") + b"\0" + identifier.bytes, hashlib.sha256).hex()


def environment(ffmpeg_version: str, ffprobe_version: str) -> dict:
    system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(platform.system())
    arch = {"AMD64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine(), "other")
    return {"app_version": __version__, "ffmpeg_version": ffmpeg_version,
            "ffprobe_version": ffprobe_version, "os": system, "architecture": arch}


def create_export_batches(results, job_id, key, env, *, migration_summary=None):
    """Stream independently scoped documents, preserving every input result.

    Keep schema/byte limits per document. Dense diagnostics can split a batch
    further; a single invalid or oversized record still fails closed.
    """
    def encode(batch):
        try:
            document = create_export(batch, job_id, key, env, **({"migration_summary": migration_summary} if migration_summary is not None else {}))
        except VideoMateError as error:
            if error.code != "export_too_large" or len(batch) == 1:
                raise
            middle = len(batch) // 2
            yield from encode(batch[:middle])
            yield from encode(batch[middle:])
        else:
            yield document
    iterator = iter(results)
    emitted = False
    while batch := list(islice(iterator, 1000)):
        emitted = True
        yield from encode(batch)
    if not emitted and migration_summary is not None:
        yield from encode([])


def create_export(results: list[ScanResult], job_id: UUID, key: bytes, env: dict,
                  *, synthetic: bool = False, nonce: bytes | None = None, migration_summary=None) -> bytes:
    # Reject over-budget jobs rather than silently dropping files.
    if not 0 <= len(results) <= 1000 or not results and migration_summary is None:
        raise VideoMateError("export_too_large")
    scope = ExportScope(key, nonce)
    schema = get_schema()
    stream_fields = schema["$defs"]["stream"]["properties"]
    entries = []
    # Build bounded typed entries only. Never include __dict__ or backend strings.
    construction_budget = 0
    for result in results:
        streams = []
        for source in result.streams[:256]:
            streams.append({k: v for k, v in source.items() if k in stream_fields})
        findings = [{"category": f.category, "severity": f.severity,
                     "evidence": f.evidence, "count": f.count,
                     "stream_index": f.stream_index, "interval": None,
                     "localization": "unknown"} for f in result.findings[:2048]]
        entry = {
            "file_ref": scope.reference("file", result.input_id),
            "scan_depth": result.depth.value, "scan_state": result.state,
            "integrity": result.integrity, "completeness": result.completeness,
            "container": result.container, "input_duration_us": result.duration_us,
            "output_duration_us": None, "streams": streams,
            "streams_omitted": max(0, len(result.streams) - len(streams)),
            "findings": findings, "findings_omitted": max(0, len(result.findings) - len(findings)),
            "recovery_state": "not_requested", "attempts": [], "edits": [],
            "edits_omitted": 0,
            "verification": {"decode_check": "not_run", "stream_check": "not_run", "timing_check": "not_run"},
        }
        details = [dict(validate_trace(detail)) for detail in result.diagnostics[:MAX_RECORDS]]
        entry["diagnostics"] = details
        entry["diagnostics_omitted"] = result.diagnostics_omitted + max(0, len(result.diagnostics) - len(details))
        if result.recovery is not None:
            recovery = result.recovery
            for name in ("recovery_state", "output_duration_us"):
                entry[name] = recovery[name]
            entry["attempts"] = [{k: a[k] for k in ("strategy", "profile", "outcome", "reason", "encoder", "decoder", "verification", "verification_issues") if k in a} for a in recovery["attempts"]]
            entry["verification"] = {k: recovery["verification"][k] for k in ("decode_check", "stream_check", "timing_check")}
            entry["edits"] = [{k: edit[k] for k in ("action", "input_interval", "output_interval", "timing_confidence")} for edit in recovery["edits"]]
            entry["losses"] = list(recovery["losses"])
            entry["recovery_notes"] = list(recovery.get("notes", []))
            entry["rate_control"] = recovery.get("rate_control", "lossless")
        if "processing" in result.technical:
            entry["processing"] = {k: result.technical["processing"][k] for k in ("cpu_budget", "runners", "hardware_decoding")}
        if "migration" in result.technical:
            entry["migration"] = {k: result.technical["migration"][k] for k in ("input_kind", "action", "copy_check", "timestamps", "reason")}
        # Conservative construction cap; final serialized bytes have their own cap.
        construction_budget += 2048 + len(streams) * 2048 + len(findings) * 1024 + sum(1024 + len(d["messages"]) * 256 for d in details)
        if construction_budget > 16 * 1024 * 1024:
            raise VideoMateError("export_too_large")
        entries.append(entry)
    approved_env = {k: env[k] for k in schema["$defs"]["environment"]["properties"] if k in env}
    return encode_export({"schema_version": 1,
                          "data_origin": "synthetic_example" if synthetic else "operator_export",
                          "export_profile": "detailed", "export_scope": scope.nonce,
                          "job_ref": scope.reference("job", job_id),
                          "environment": approved_env, "files": entries, "files_omitted": 0,
                          **({"migration_summary": migration_summary} if migration_summary is not None else {})})
