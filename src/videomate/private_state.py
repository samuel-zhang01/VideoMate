"""Minimal-retention jobs and sanitized session reports. No persistent locators."""
import json
import os
import secrets
import shutil
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from uuid import UUID, uuid4

from .diagnostics import ExportScope, create_export_batches, environment
from .errors import VideoMateError
from .jobs import Job, unpack_result
from .models import Depth, Finding, ScanResult
from .policy import plain_local_path
from .schema import encode_export, load_json, validate_export

LIVE_REPORTS = OrderedDict()


class MemoryJob(Job):
    @classmethod
    def create(cls, workspace, paths, settings, *, identifier=None):
        job = object.__new__(cls)
        job.id, job.workspace = identifier or uuid4().hex, workspace
        job.directory = plain_local_path(workspace / "jobs" / ("session-" + uuid4().hex))
        job.directory.mkdir(mode=0o700)
        job.owned_directories = [job.directory]
        info = job.directory.stat()
        job.owned_identities = {job.directory: (info.st_dev, info.st_ino)}
        job.retained_directories = set()
        job.cleanup_blocked = threading.Event()
        job.connection = sqlite3.connect(":memory:")
        job.connection.row_factory = sqlite3.Row
        job.connection.execute("PRAGMA trusted_schema=OFF")
        job.connection.execute("PRAGMA temp_store=MEMORY")
        job.connection.execute("CREATE TABLE settings (value TEXT NOT NULL)")
        job.connection.execute("INSERT INTO settings VALUES (?)", (json.dumps(settings),))
        job.connection.execute("CREATE TABLE inputs (number INTEGER PRIMARY KEY, path TEXT NOT NULL, status TEXT NOT NULL, result TEXT)")
        job.connection.executemany("INSERT INTO inputs VALUES (?, ?, 'pending', NULL)", ((i, str(p)) for i, p in enumerate(paths, 1)))
        job.connection.execute("PRAGMA user_version=1")
        return job

    def iter_rows(self):
        # This database is created in memory by the current session, not loaded
        # from an untrusted retained job. Migration has no record-count ceiling.
        return self.connection.execute("SELECT * FROM inputs ORDER BY number")

    def rows(self):
        return list(self.iter_rows())

    def close(self):
        try:
            self.cleanup_owned()
        finally:
            self.connection.close()

    def cleanup_owned(self):
        if self.cleanup_blocked.is_set():
            # A worker may still hold these files. Stop the job and retain only
            # its already-created staging files for operator review.
            raise VideoMateError("worker_cleanup_failed")
        # Only directories exclusively created by this session can enter this
        # list. Never discover or remove legacy jobs, mappings or source folders.
        failure = False
        for directory in reversed(self.owned_directories):
            if directory in self.retained_directories:
                continue
            try:
                root = plain_local_path(directory)
                if root != directory or not root.name.startswith(("session-", "candidates-")):
                    raise VideoMateError("cleanup_incomplete")
                info = root.stat()
                if self.owned_identities.get(root) != (info.st_dev, info.st_ino):
                    raise VideoMateError('cleanup_incomplete')
                for current, folders, files in os.walk(root, followlinks=False):
                    for name in folders + files:
                        plain_local_path(Path(current) / name)
                shutil.rmtree(root)
            except (OSError, VideoMateError):
                failure = True
        if failure:
            raise VideoMateError("cleanup_incomplete")

    def own_directory(self, directory):
        info = directory.stat()
        self.owned_directories.append(directory)
        self.owned_identities[directory] = (info.st_dev, info.st_ino)


def snapshot(job, version):
    pages = tuple(session_exports(job, version))
    if not pages:
        return
    encoded = pages[0] if len(pages) == 1 else pages
    settings = job.settings()
    LIVE_REPORTS[job.id] = (str(job.workspace), settings.get("diagnostics_dir", ""), encoded)
    LIVE_REPORTS.move_to_end(job.id)
    while len(LIVE_REPORTS) > 8:
        LIVE_REPORTS.popitem(last=False)


def session_exports(job, version):
    return create_export_batches((unpack_result(row["result"]) for row in job.iter_rows() if row["result"]),
                                UUID(hex=job.id), secrets.token_bytes(32), environment(version, version),
                                migration_summary=getattr(job, "migration_summary", None))


def failure_code(error):
    """Closed categories only; exception text can contain private paths."""
    if isinstance(error, KeyboardInterrupt):
        return "operator_cancelled"
    if isinstance(error, VideoMateError):
        return error.code
    return "io_error" if isinstance(error, OSError) else "internal_error"


def session_issue(job, stage, error):
    summary = getattr(job, "migration_summary", None)
    if summary is not None:
        issues = summary.setdefault("pipeline_issues", [])
        if len(issues) < 32:
            issues.append({"stage": stage, "reason": failure_code(error)})


def finalize_session(job, version, emit, *, primary_error=None, export_callback=None):
    """Keep the processing error when reporting or cleanup also fails."""
    failure = primary_error
    try:
        if isinstance(job, MemoryJob):
            try:
                # SQLite is memory-only. Cleanup first so retained diagnostics
                # include failures here, before closing the in-memory journal.
                job.cleanup_owned()
            except Exception as error:
                session_issue(job, "cleanup", error)
                emit("Session cleanup issue [" + failure_code(error) + "]. Existing published outputs were not removed.")
                if failure is None or failure_code(error) == "worker_cleanup_failed":
                    failure = error
            try:
                snapshot(job, version)
            except Exception as error:
                session_issue(job, "save_session_report", error)
                emit("Session diagnostics could not be finalized [" + failure_code(error) + "].")
                failure = failure or error
        if export_callback:
            try:
                export_callback()
            except Exception as error:
                session_issue(job, "export_diagnostics", error)
                emit("Diagnostic export failed [" + failure_code(error) + "]. Try Export diagnostic log after local storage is available.")
                failure = failure or error
    finally:
        if isinstance(job, MemoryJob):
            job.connection.close()
        else:
            job.close()
    if failure is not None and failure is not primary_error:
        raise failure


def report_pages(encoded):
    return (encoded,) if isinstance(encoded, bytes) else encoded


def fresh_report(encoded):
    document = load_json(encoded)
    validate_export(document)
    scope = ExportScope(secrets.token_bytes(32))
    document["export_scope"] = scope.nonce
    document["job_ref"] = scope.reference("job", uuid4())
    for item in document["files"]:
        item["file_ref"] = scope.reference("file", uuid4())
    return encode_export(document)


def from_report(document):
    """Restore only an authenticated, already schema-validated checkpoint item."""
    validate_export(document)
    if len(document["files"]) != 1:
        raise VideoMateError("checkpoint_invalid")
    item = document["files"][0]
    result = ScanResult(depth=Depth(item["scan_depth"]), state=item["scan_state"], integrity=item["integrity"],
                        completeness=item["completeness"], container=item["container"], duration_us=item["input_duration_us"],
                        streams=item["streams"], diagnostics=item.get("diagnostics", []), diagnostics_omitted=item.get("diagnostics_omitted", 0))
    result.findings = [Finding(**{k: f[k] for k in ("category", "severity", "evidence", "count", "stream_index")}) for f in item["findings"]]
    if item["recovery_state"] != "not_requested":
        result.recovery = {k: item[k] for k in ("recovery_state", "output_duration_us", "attempts", "edits", "verification")}
        result.recovery.update(losses=item.get("losses", []), notes=item.get("recovery_notes", []), rate_control=item.get("rate_control", "lossless"))
    return result
