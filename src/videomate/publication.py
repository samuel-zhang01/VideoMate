"""Exclusive output publication and fixed filesystem failure categories."""
import errno
import os
import tempfile
from pathlib import Path

from .errors import VideoMateError
from .policy import plain_local_path


def filesystem_reason(error, default):
    """Use numeric OS categories only; never forward exception text/locators."""
    if isinstance(error, FileExistsError):
        return "output_exists"
    if error.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)} or getattr(error, "winerror", None) == 112:
        return "disk_limit"
    if default == "source_read_failed":
        return default
    if getattr(error, "winerror", None) in {32, 33}:
        return "output_busy"
    if error.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
        return "output_access_denied"
    if error.errno == errno.ENAMETOOLONG or getattr(error, "winerror", None) == 206:
        return "output_path_too_long"
    if error.errno in {errno.EXDEV, errno.ENOSYS, errno.ENOTSUP} or getattr(error, "winerror", None) in {1, 50}:
        return "output_filesystem_unsupported"
    return default


def publish(candidate: Path, destination: Path):
    """Atomic, exclusive same-filesystem publication; never replace a file.

    Windows rename refuses existing destinations and works without hard links.
    POSIX rename replaces files, so POSIX keeps exclusive hard-link publication.
    """
    plain_local_path(candidate)
    plain_local_path(destination.parent)
    try:
        if os.name == "nt":
            os.rename(candidate, destination)
        else:
            os.link(candidate, destination)
            candidate.unlink()
    except OSError as error:
        raise VideoMateError(filesystem_reason(error, "output_publish_failed")) from None


def qualify_publication(staging, output):
    """Exercise only newly created markers before processing any source bytes."""
    try:
        with tempfile.TemporaryDirectory(prefix="publication-check-", dir=staging) as incoming, tempfile.TemporaryDirectory(prefix="publication-check-", dir=output) as outgoing:
            candidate, destination = Path(incoming) / "marker", Path(outgoing) / "marker"
            candidate.write_bytes(b"VideoMate generated publication check")
            publish(candidate, destination)
            if candidate.exists() or destination.read_bytes() != b"VideoMate generated publication check":
                raise VideoMateError("output_publish_failed")
            candidate.write_bytes(b"VideoMate generated collision check")
            try:
                publish(candidate, destination)
            except VideoMateError as error:
                if error.code != "output_exists":
                    raise
            else:
                raise VideoMateError("output_publish_failed")
            if destination.read_bytes() != b"VideoMate generated publication check":
                raise VideoMateError("output_publish_failed")
    except OSError as error:
        raise VideoMateError(filesystem_reason(error, "output_write_failed")) from None
