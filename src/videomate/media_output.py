"""Streaming, bounded worker output. Raw messages never survive classification."""
from collections import Counter

from .models import Finding


class MediaOutput:
    def __init__(self, progress=False):
        self.progress = progress
        self.pending = bytearray()
        self.dropping = False
        self.counts, self.values = Counter(), {}

    def _line(self, line):
        if self.progress:
            key, sep, value = line.partition(b"=")
            if sep and key in {b"frame", b"out_time_us"} and len(value) <= 18 and value.strip().lstrip(b"-").isdigit():
                self.values[key] = value.strip()
            elif key == b"progress" and value.strip() in {b"continue", b"end"}:
                self.values[key] = value.strip()
            return
        from .backend import classify_log
        for finding in classify_log(line, include_advisories=True):
            key = finding.category, finding.severity, finding.evidence
            self.counts[key] = min(1000000000, self.counts[key] + finding.count)

    def feed(self, block):
        for part in block.splitlines(keepends=True):
            ended = part.endswith((b"\n", b"\r"))
            if not self.dropping:
                if len(self.pending) + len(part) > 8192:
                    self.pending.clear()
                    self.dropping = True
                    if not self.progress:
                        key = ("unclassified_error", "error", "decoder_reported")
                        self.counts[key] = min(1000000000, self.counts[key] + 1)
                else:
                    self.pending.extend(part)
            if ended:
                if not self.dropping:
                    self._line(bytes(self.pending).rstrip(b"\r\n"))
                self.pending.clear()
                self.dropping = False

    def finish(self):
        if self.pending and not self.dropping:
            self._line(bytes(self.pending))
        self.pending.clear()

    def output(self):
        return b"\n".join(key + b"=" + value for key, value in self.values.items()) + b"\n"

    def findings(self):
        return tuple(Finding(category, severity, evidence, count) for (category, severity, evidence), count in self.counts.items())


def process_findings(process, index=None, *, include_advisories=False):
    from .backend import classify_log
    messages = getattr(process, "messages", None)
    if messages is None:
        return classify_log(process.stderr, index, include_advisories=include_advisories)
    return [Finding(f.category, f.severity, f.evidence, f.count, index) for f in messages
            if include_advisories or f.category != "thread_advisory"]
