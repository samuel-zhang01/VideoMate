"""Bounded, non-shell worker execution. Not a production security sandbox."""

import os
import signal
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .errors import VideoMateError


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes = field(default=b"", repr=False)
    stderr: bytes = field(default=b"", repr=False)
    limited: bool = False
    limit_reason: str = "none"
    elapsed_ms: int = 0
    messages: tuple | None = None


def worker_environment(scratch: Path) -> dict[str, str]:
    # Deliberately excludes FFREPORT, proxy variables, credentials and PATH.
    result = {"LANG": "C", "LC_ALL": "C", "AV_LOG_FORCE_NOCOLOR": "1",
              "TMP": str(scratch), "TEMP": str(scratch), "TMPDIR": str(scratch)}
    if os.name == "nt":
        for name in ("SystemRoot", "WINDIR"):
            if name in os.environ:
                result[name] = os.environ[name]
    return result


def _terminate_tree(process: subprocess.Popen, job=None) -> None:
    if job is not None:
        job.close()
    elif os.name == "nt":
        # Development lifecycle cleanup only; this is not Windows containment.
        tool = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            subprocess.run([str(tool), "/PID", str(process.pid), "/T", "/F"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5, check=False,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Some POSIX hosts can deny signaling a group as its last worker
            # exits. Ignore this only after reaping the worker; a live-worker
            # denial must still fail closed. Resource limits remain enforced.
            if process.poll() is None:
                raise
    if process.poll() is None:
        process.kill()


def _discard_unassigned_worker(process: subprocess.Popen, job) -> None:
    """Confirm a worker stopped when Windows Job assignment did not succeed."""
    try:
        process.kill()
    except OSError:
        # It may have exited between creation and assignment. wait() below is
        # authoritative; an unconfirmed live worker still blocks cleanup.
        pass
    confirmed = True
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        confirmed = False
    try:
        job.close()
    except Exception:
        confirmed = False
    finally:
        process.stdout.close()
        process.stderr.close()
    if not confirmed:
        raise VideoMateError("worker_cleanup_failed")


class Runner:
    def __init__(self, *, timeout: float = 60, output_limit: int = 2 * 1024 * 1024, cancel_event=None, cleanup_blocked=None):
        if timeout <= 0 or output_limit < 1:
            raise ValueError("Invalid worker budget")
        self.timeout, self.output_limit = timeout, output_limit
        self.cancel_event = cancel_event
        self.cleanup_blocked = cleanup_blocked if cleanup_blocked is not None else threading.Event()

    def run(self, args: list[str], scratch: Path, *, watch_file: Path | None = None, max_file_bytes: int | None = None, media_output=False) -> ProcessResult:
        if self.cleanup_blocked.is_set():
            raise VideoMateError("worker_cleanup_failed")
        try:
            return self._run(args, scratch, watch_file=watch_file, max_file_bytes=max_file_bytes, media_output=media_output)
        except VideoMateError as error:
            if error.code == "worker_cleanup_failed":
                self.cleanup_blocked.set()
                if self.cancel_event is not None:
                    self.cancel_event.set()
            raise

    def _run(self, args, scratch, *, watch_file=None, max_file_bytes=None, media_output=False):
        started = time.monotonic()
        if not args or not Path(args[0]).is_absolute():
            raise VideoMateError("backend_invalid")
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise KeyboardInterrupt()
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        job = None
        if os.name == "nt":
            from .windows_job import WindowsJob
            job = WindowsJob()
        try:
            process = subprocess.Popen(args, shell=False, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       cwd=scratch, env=worker_environment(scratch), **options)
        except OSError:
            if job:
                job.close()
            raise VideoMateError("backend_unavailable") from None
        if job:
            try:
                job.assign(process)
            except VideoMateError:
                _discard_unassigned_worker(process, job)
                raise
        exceeded = threading.Event()
        buffers = [bytearray(), bytearray()]
        from .media_output import MediaOutput
        collectors = [MediaOutput(progress=True), MediaOutput()] if media_output else [None, None]

        def drain(pipe, buffer, collector):
            try:
                while True:
                    block = pipe.read1(8192)
                    if not block:
                        if collector:
                            collector.finish()
                        return
                    if collector:
                        collector.feed(block)
                        continue
                    remaining = self.output_limit - len(buffer)
                    buffer.extend(block[:max(0, remaining)])
                    if len(block) > remaining:
                        exceeded.set()
            except Exception:
                # Do not let a parser failure emit an uncaught reader-thread
                # traceback or silently permit incomplete verification.
                exceeded.set()
            finally:
                pipe.close()

        readers = [threading.Thread(target=drain, args=(pipe, buffer, collector), daemon=True)
                   for pipe, buffer, collector in zip((process.stdout, process.stderr), buffers, collectors)]
        for reader in readers:
            reader.start()
        deadline, limited, limit_reason = time.monotonic() + self.timeout, False, "none"
        next_disk_check, disk_low = 0, False
        try:
            while process.poll() is None or any(reader.is_alive() for reader in readers):
                if self.cancel_event is not None and self.cancel_event.is_set():
                    raise KeyboardInterrupt()
                oversized = watch_file is not None and max_file_bytes is not None and watch_file.exists() and watch_file.stat().st_size >= max_file_bytes
                if watch_file is not None and time.monotonic() >= next_disk_check:
                    disk_low = shutil.disk_usage(watch_file.parent).free < 64 * 1024 ** 2
                    next_disk_check = time.monotonic() + 0.25
                if exceeded.is_set() or time.monotonic() >= deadline or oversized or disk_low:
                    limited = True
                    limit_reason = "output_limit" if exceeded.is_set() else "disk_limit" if disk_low else "candidate_limit" if oversized else "timeout"
                    _terminate_tree(process, job)
                    break
                time.sleep(0.01)
            process.wait(timeout=5)
        except BaseException:
            try:
                _terminate_tree(process, job)
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                raise VideoMateError("worker_cleanup_failed") from None
            raise
        finally:
            try:
                if job:
                    job.close()
            finally:
                for reader in readers:
                    reader.join(timeout=1)
        limited = limited or exceeded.is_set() or any(reader.is_alive() for reader in readers)
        if watch_file is not None and max_file_bytes is not None and watch_file.exists():
            limited = limited or watch_file.stat().st_size >= max_file_bytes
            if limited and limit_reason == "none" and watch_file.stat().st_size >= max_file_bytes:
                limit_reason = "candidate_limit"
        if limited and limit_reason == "none":
            limit_reason = "output_limit"
        return ProcessResult(process.returncode, collectors[0].output() if media_output else bytes(buffers[0]),
                             b"" if media_output else bytes(buffers[1]), limited,
                             limit_reason, max(0, int((time.monotonic() - started) * 1000)),
                             collectors[1].findings() if media_output else None)
