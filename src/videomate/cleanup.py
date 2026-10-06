"""Explicit operator cleanup, never an inspection/recovery side effect."""
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from .errors import VideoMateError
from .inspection import _fingerprint
from .policy import LocalFileScope, plain_local_path


def manage_originals(inputs, action, confirmation, *, cancel_event, emit=print):
    if action not in {"quarantine", "delete"} or not 1 <= len(inputs) <= 1000:
        raise VideoMateError("cleanup_confirmation")
    if confirmation != action.upper() + " " + str(len(inputs)):
        raise VideoMateError("cleanup_confirmation")
    paths = [plain_local_path(Path(p).absolute()) for p in inputs]
    if len(set(paths)) != len(paths):
        raise VideoMateError("cleanup_confirmation")
    scope = LocalFileScope(frozenset(paths), Path(__file__).absolute().parents[2])
    snapshots = []
    for path in paths:
        scope.authorize(path)  # Individual regular files only; never recurse.
        if ".videomate-review" in path.parts:
            raise VideoMateError("cleanup_confirmation")
        snapshots.append(_fingerprint(path))
    done = 0
    for number, (source, before) in enumerate(zip(paths, snapshots), 1):
        if cancel_event.is_set():
            raise KeyboardInterrupt()
        scope.authorize(source)
        if before != _fingerprint(source):
            raise VideoMateError("input_changed")
        if action == "quarantine":
            root = plain_local_path(source.parent / ".videomate-review")
            root.mkdir(mode=0o700, exist_ok=True)
            target = root / (uuid4().hex + source.suffix)
            # Same-filesystem exclusive link is cheap and preserves bytes. For
            # filesystems without links, verify a new exclusive copy first.
            try:
                os.link(source, target)
            except OSError:
                expected = hashlib.sha256()
                try:
                    with target.open("xb") as output, source.open("rb") as incoming:
                        while block := incoming.read(1024 * 1024):
                            if cancel_event.is_set():
                                raise KeyboardInterrupt()
                            expected.update(block)
                            output.write(block)
                    with target.open("rb") as copied:
                        if hashlib.file_digest(copied, "sha256").digest() != expected.digest():
                            raise VideoMateError("io_error")
                except BaseException:
                    # The source is still intact. An incomplete review copy is
                    # retained on interruption; no hidden recursive deletion.
                    raise
            scope.authorize(source)
            if before != _fingerprint(source):
                raise VideoMateError("input_changed")
        # Deletion is a separate, explicitly confirmed action. Unreadable does
        # not mean irrecoverable, and there is deliberately no automatic rule.
        if cancel_event.is_set():
            raise KeyboardInterrupt()
        source.unlink()
        done += 1
        emit(f"input-{number}: " + ("moved to the private .videomate-review folder beside its source." if action == "quarantine" else "deleted by explicit operator request."))
    return done
