"""Path-free batch progress. ETA is a file-rate estimate, not a media guarantee."""
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Progress:
    phase: str
    completed: int
    total: int | None
    discovered: int
    elapsed: float
    remaining: float | None
    sampled_at: float
    active: int = 0


class BatchProgress:
    def __init__(self, callback=None):
        self.callback = callback
        self.started = time.monotonic()
        self.processing_started = None
        self.last_sent = None
        self.total, self.completed, self.discovered = None, 0, 0
        self.active = 0
        self.recent = deque(maxlen=4096)

    def update(self, phase, *, completed=None, discovered=None, active=None, force=False):
        now = time.monotonic()
        if completed is not None:
            if completed > self.completed and self.processing_started is not None:
                self.recent.append((now, completed))
                while self.recent and self.recent[0][0] < now - 60:
                    self.recent.popleft()
            self.completed = completed
        if discovered is not None:
            self.discovered = discovered
        if active is not None:
            self.active = active
        if not force and self.last_sent is not None and now - self.last_sent < 0.2:
            return
        remaining = None
        if self.processing_started is not None and self.completed and self.completed < self.total:
            elapsed = now - self.processing_started
            if elapsed < 60:
                remaining = elapsed / self.completed * (self.total - self.completed)
            elif len(self.recent) >= 2 and now - self.recent[-1][0] < 30:
                first, last = self.recent[0], self.recent[-1]
                if last[0] > first[0] and last[1] > first[1]:
                    remaining = (last[0] - first[0]) / (last[1] - first[1]) * (self.total - self.completed)
        if self.callback:
            self.callback(Progress(phase, self.completed, self.total, self.discovered,
                                   now - self.started, remaining, now, self.active))
        self.last_sent = now

    def plan(self, total):
        self.total = total
        self.update("preparing", force=True)

    def begin(self):
        self.processing_started = time.monotonic()
        self.update("processing", force=True)


def duration(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {seconds:02d}s"


def describe(progress, *, now=None, running=True):
    """Render only counts, relative time and fixed phase labels for the GUI."""
    age = max(0, (time.monotonic() if now is None else now) - progress.sampled_at) if running else 0
    elapsed = duration(progress.elapsed + age)
    if progress.total is None:
        text = f"Finding files: {progress.discovered:,} found · Elapsed {elapsed}"
        return text + " · Time remaining: estimating…" if running else text
    text = f"{progress.completed:,} / {progress.total:,} files · Elapsed {elapsed}"
    if not running or progress.phase == "finished":
        return text
    if progress.active:
        text += f" · {progress.active} running"
    if progress.phase == "waiting_storage":
        return text + " · Waiting for verified storage; Stop remains available…"
    if progress.phase == "retrying":
        return text + " · Rediscovering and retrying unfinished work…"
    if progress.phase == "checking":
        return text + " · Final source checks…"
    if progress.phase == "reporting":
        return text + " · Preparing diagnostics…"
    if progress.remaining is None:
        return text + " · Time remaining: estimating…"
    left = progress.remaining - age
    return text + (f" · About {duration(left)} remaining" if left > 0 else " · Time remaining: re-estimating…")
