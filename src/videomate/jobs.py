"""Private per-job SQLite journals and exclusive local job locks."""
import contextlib
import json
import os
import re
import sqlite3
from uuid import UUID, uuid4

from .diagnostics import create_export, environment
from .errors import VideoMateError
from .models import Depth, Finding, ScanResult
from .policy import plain_local_path
from .schema import load_json

# Includes up to 1,000 private output-layout entries. Persistent job writers and
# settings readers share this bound, avoiding immediately unreadable saved jobs.
MAX_JOB_SETTINGS_BYTES = 16 * 1024 * 1024


def _encode_settings(settings):
    try:
        encoded = json.dumps(settings, ensure_ascii=True, allow_nan=False)
        load_json(encoded.encode("ascii"), limit=MAX_JOB_SETTINGS_BYTES)
        return encoded
    except (ValueError, TypeError, RecursionError, VideoMateError):
        raise VideoMateError("job_invalid") from None


def pack_result(result):
    return json.dumps({"input_id": result.input_id.hex, "depth": result.depth.value, "state": result.state,
                       "integrity": result.integrity, "completeness": result.completeness,
                       "container": result.container, "duration_us": result.duration_us,
                       "streams": result.streams, "findings": [vars(f) for f in result.findings],
                       "technical": result.technical, "fingerprint": result.fingerprint,
                       "recovery": result.recovery, "diagnostics": result.diagnostics,
                       "diagnostics_omitted": result.diagnostics_omitted}, ensure_ascii=True, allow_nan=False)


def unpack_result(encoded):
    try:
        value = load_json(encoded.encode())
        result = ScanResult(input_id=UUID(hex=value["input_id"]), depth=Depth(value["depth"]),
                            **{key: value[key] for key in ("state", "integrity", "completeness", "container", "duration_us", "streams", "technical", "fingerprint", "recovery")})
        result.findings = [Finding(**entry) for entry in value["findings"]]
        result.diagnostics = value.get("diagnostics", [])
        result.diagnostics_omitted = value.get("diagnostics_omitted", 0)
        create_export([result], uuid4(), bytes(32), environment("0.0.0", "0.0.0"), synthetic=True)
        return result
    except (ValueError, TypeError, KeyError, VideoMateError):
        raise VideoMateError("job_invalid") from None


@contextlib.contextmanager
def job_lock(directory):
    path = plain_local_path(directory / "active.lock")
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise VideoMateError("job_busy") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Job:
    def __init__(self, workspace, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise VideoMateError("job_invalid")
        self.id, self.workspace = identifier, workspace
        self.directory = plain_local_path(workspace / "jobs" / identifier)
        self.database = plain_local_path(self.directory / "job.sqlite3")
        if not self.database.is_file() or self.database.stat().st_size > 256 * 1024 ** 2:
            raise VideoMateError("job_invalid")
        self.connection = sqlite3.connect(self.database.as_uri() + "?mode=rw", uri=True, timeout=1)
        self.connection.execute("PRAGMA trusted_schema=OFF")
        self.connection.row_factory = sqlite3.Row

    @classmethod
    def create(cls, workspace, paths, settings):
        encoded_settings = _encode_settings(settings)
        identifier = uuid4().hex
        directory = workspace / "jobs" / identifier
        directory.mkdir(mode=0o700)
        with contextlib.closing(sqlite3.connect(directory / "job.sqlite3")) as database, database:
            database.execute("CREATE TABLE settings (value TEXT NOT NULL)")
            database.execute("INSERT INTO settings VALUES (?)", (encoded_settings,))
            database.execute("CREATE TABLE inputs (number INTEGER PRIMARY KEY, path TEXT NOT NULL, status TEXT NOT NULL, result TEXT)")
            database.executemany("INSERT INTO inputs VALUES (?, ?, 'pending', NULL)", [(i, str(p)) for i, p in enumerate(paths, 1)])
            database.execute("PRAGMA user_version=1")
        return cls(workspace, identifier)

    def close(self):
        self.connection.close()

    def settings(self):
        try:
            if self.connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise VideoMateError("job_invalid")
            rows = self.connection.execute("SELECT value FROM settings").fetchmany(2)
            if len(rows) != 1:
                raise VideoMateError("job_invalid")
            value = load_json(rows[0][0].encode(), limit=MAX_JOB_SETTINGS_BYTES)
            if type(value) is not dict or value.get("scope") not in {"non_sensitive_tests", "local_files"}:
                raise VideoMateError("job_invalid")
            if value["scope"] == "local_files":
                from .preferences import Preferences
                names = ("sensitive", "recovered_dir", "diagnostics_dir", "logs_dir", "write_logs",
                         "diagnostic_logs", "cpu_threads", "max_runners", "hardware_decoding", "output_layout",
                         "retain_history", "retain_mappings", "private_resume")
                if "sensitive" not in value:
                    raise VideoMateError("job_invalid")
                try:
                    Preferences(**{name: value[name] for name in names if name in value}).validate()
                except VideoMateError:
                    raise VideoMateError("job_invalid") from None
            return value
        except (sqlite3.Error, VideoMateError):
            raise VideoMateError("job_invalid") from None

    def rows(self):
        try:
            rows = self.connection.execute("SELECT * FROM inputs ORDER BY number").fetchmany(1001)
            if not 1 <= len(rows) <= 1000:
                raise VideoMateError("job_invalid")
            return rows
        except sqlite3.Error:
            raise VideoMateError("job_invalid") from None

    def save(self, number, status, result=None):
        with self.connection:
            self.connection.execute("UPDATE inputs SET status=?, result=? WHERE number=?", (status, pack_result(result) if result else None, number))

    def update_settings(self, settings):
        encoded_settings = _encode_settings(settings)
        with self.connection:
            self.connection.execute("UPDATE settings SET value=?", (encoded_settings,))
