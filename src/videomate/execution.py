"""Per-job CPU budgets and a bounded inspection scheduler. No database workers."""
import os
import threading
from contextlib import contextmanager
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .errors import VideoMateError

_PROCESSING = threading.Lock()
_PROCESSING_BLOCKED = threading.Event()


@contextmanager
def processing_session(workspace):
    """One coordinator per process/workspace; its workers share the CPU budget."""
    from .jobs import job_lock
    if _PROCESSING_BLOCKED.is_set():
        raise VideoMateError('worker_cleanup_failed')
    if not _PROCESSING.acquire(blocking=False):
        raise VideoMateError('job_busy')
    try:
        if _PROCESSING_BLOCKED.is_set():
            raise VideoMateError('worker_cleanup_failed')
        try:
            with job_lock(workspace):
                yield
        except VideoMateError as error:
            if error.code == 'worker_cleanup_failed':
                _PROCESSING_BLOCKED.set()
            raise
    finally:
        _PROCESSING.release()


@contextmanager
def resource_slot(gate, cancel):
    if gate:
        while not gate.acquire(timeout=0.1):
            if cancel and cancel.is_set():
                raise KeyboardInterrupt()
    try:
        if cancel and cancel.is_set():
            raise KeyboardInterrupt()
        yield
    finally:
        if gate:
            gate.release()


def cpu_budget(requested=0):
    if type(requested) is not int or not 0 <= requested <= 1024:
        raise VideoMateError("settings_invalid")
    available = (getattr(os, "process_cpu_count", os.cpu_count)() or 1)
    return requested or max(1, min(1024, available - 2))


def thread_slots(budget, count, max_runners=0):
    if type(max_runners) is not int or not 0 <= max_runners <= 1024:
        raise VideoMateError("settings_invalid")
    workers = min(budget, count, max_runners or budget)
    if workers < 1:
        return ()
    share, remainder = divmod(budget, workers)
    return tuple(share + (slot < remainder) for slot in range(workers))


def parallel_inspect(items, backends, inspect, on_start, cancel, *, queues=None, drain_on_cancel=False):
    """Submit at most one task per slot; callbacks and yielded writes stay on caller."""
    pending = iter(items)
    queues = queues if queues is not None else [pending] * len(backends)
    pool = ThreadPoolExecutor(max_workers=len(backends), thread_name_prefix="videomate-inspect")
    active = {}
    failure = None
    def failed(error):
        nonlocal failure
        # Fatal shutdown errors must not be hidden by a sibling's cancellation.
        if failure is None or isinstance(failure, KeyboardInterrupt) or getattr(error, "code", None) == "worker_cleanup_failed":
            failure = error
        cancel.set()

    def submit(slot):
        if cancel.is_set():
            if drain_on_cancel:
                return
            raise KeyboardInterrupt()
        try:
            item = next(queues[slot], None)
            if item is not None:
                on_start(item)
                active[pool.submit(inspect, backends[slot], item)] = (slot, item)
        except BaseException as error:
            if not drain_on_cancel:
                raise
            failed(error)
    try:
        for slot in range(len(backends)):
            submit(slot)
        while active:
            if cancel.is_set() and not drain_on_cancel:
                raise KeyboardInterrupt()
            done, _ = wait(active, timeout=0.1, return_when=FIRST_COMPLETED)
            completed = []
            available = []
            for future in done:
                slot, item = active.pop(future)
                available.append(slot)
                try:
                    result = future.result()
                except BaseException as error:
                    if not drain_on_cancel:
                        raise
                    failed(error)
                else:
                    completed.append((item, result))
            # Observe every finished failure before admitting replacement work.
            yield from completed
            if not cancel.is_set():
                for slot in available:
                    submit(slot)
        if failure is not None:
            raise failure
        if cancel.is_set():
            raise KeyboardInterrupt()
    except BaseException:
        cancel.set()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def migration_slots(budget, video_count, other_count, max_runners=0):
    """Reserve one copy lane for mixed trees; avoid many competing disk copies."""
    if type(max_runners) is not int or not 0 <= max_runners <= 1024:
        raise VideoMateError("settings_invalid")
    count = min(budget, video_count + other_count, max_runners or 4)
    if count <= 1 or not video_count:
        return (budget,), False
    copy_lane = bool(other_count)
    videos = min(video_count, count - int(copy_lane))
    return thread_slots(budget - int(copy_lane), videos, videos) + ((1,) if copy_lane else ()), copy_lane


def automatic_cpu_lane_allowed(budget, available_budget, enabled=True):
    """Admit optional software encoding only with ample process-visible CPU capacity."""
    return bool(enabled and min(budget, available_budget) >= 16)


def hybrid_migration_slots(budget, video_count, other_count, max_runners, gpu_routes, cpu_encoding):
    """Optionally dedicate one video lane to software encoding beside every GPU route.

    CPU threads are advisory FFmpeg limits, not core affinity. Admit the lane
    only when every video lane can request at least two codec threads. Cap its
    share so software encoding cannot consume most of a large CPU budget.
    """
    slots, copy_lane = migration_slots(budget, video_count, other_count, max_runners)
    video_lanes = len(slots) - int(copy_lane)
    gpu_lanes = video_lanes - 1
    video_budget = budget - int(copy_lane)
    if (not cpu_encoding or not gpu_routes or video_lanes <= gpu_routes
            or video_budget < 2 * video_lanes):
        return slots, copy_lane, None
    software_threads = min(8, max(2, video_budget // 4), video_budget - 2 * gpu_lanes)
    gpu_threads = thread_slots(video_budget - software_threads, gpu_lanes, gpu_lanes)
    return gpu_threads + (software_threads,) + ((1,) if copy_lane else ()), copy_lane, gpu_lanes
