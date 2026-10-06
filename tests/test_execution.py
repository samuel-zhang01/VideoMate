"""Scheduler and fallback tests use invented work, never operator media."""
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from videomate.backend import FFmpegBackend
from videomate.errors import VideoMateError
from videomate.execution import automatic_cpu_lane_allowed, cpu_budget, thread_slots, parallel_inspect, migration_slots, hybrid_migration_slots, resource_slot
from videomate.hardware import select_decoder
from videomate.runner import Runner, ProcessResult


class ExecutionTests(unittest.TestCase):
    def test_automatic_cpu_lane_uses_process_visible_budget(self):
        with patch("videomate.execution.os.process_cpu_count", return_value=32, create=True):
            self.assertEqual(cpu_budget(), 30)
        self.assertTrue(automatic_cpu_lane_allowed(30, 30))
        self.assertFalse(automatic_cpu_lane_allowed(14, 30))
        self.assertFalse(automatic_cpu_lane_allowed(30, 14))
        self.assertFalse(automatic_cpu_lane_allowed(30, 30, False))
        slots, copy_lane, cpu_lane = hybrid_migration_slots(30, 20, 100, 4, 2, True)
        self.assertEqual((slots, copy_lane, cpu_lane), ((11, 11, 7, 1), True, 2))

    def test_cpu_encoding_lane_never_displaces_qualified_gpu_routes(self):
        slots, copy_lane, cpu_lane = hybrid_migration_slots(14, 20, 100, 4, 2, True)
        self.assertEqual((slots, copy_lane, cpu_lane), ((5, 5, 3, 1), True, 2))
        self.assertEqual(sum(slots), 14)
        self.assertEqual(hybrid_migration_slots(14, 20, 0, 2, 2, True)[2], None)
        self.assertEqual(hybrid_migration_slots(14, 20, 0, 3, 0, True)[2], None)
        self.assertEqual(hybrid_migration_slots(14, 2, 0, 3, 2, True)[2], None)
        self.assertEqual(hybrid_migration_slots(14, 20, 0, 3, 2, False)[2], None)
        self.assertEqual(hybrid_migration_slots(6, 20, 0, 4, 2, True)[2], None)
        self.assertEqual(hybrid_migration_slots(30, 20, 100, 4, 2, True)[0], (11, 11, 7, 1))

    def test_migration_lanes_share_budget_and_keep_ordinary_copy_progressing(self):
        for budget in (1, 2, 6, 30):
            slots, separate_copy = migration_slots(budget, 20, 100, 0)
            self.assertLessEqual(len(slots), 4)
            self.assertEqual(sum(slots), budget)
            self.assertEqual(separate_copy, budget > 1)
        self.assertEqual(migration_slots(30, 100, 0, 8)[0], thread_slots(30, 100, 8))
        self.assertEqual(migration_slots(30, 0, 100, 0), ((30,), False))
        barrier = threading.Barrier(3, timeout=5)
        video_queue, copy_queue = iter([1, 2]), iter([3])
        def work(slot, item):
            barrier.wait()
            self.assertEqual(slot == "copy", item == 3)
            return item
        results = list(parallel_inspect([], ["video-a", "video-b", "copy"], work, lambda _: None,
            threading.Event(), queues=[video_queue, video_queue, copy_queue], drain_on_cancel=True))
        self.assertEqual(sorted(item for item, _ in results), [1, 2, 3])

    def test_cancel_drains_completed_results_and_waiting_resource_is_stoppable(self):
        cancel = threading.Event()
        barrier = threading.Barrier(2, timeout=5)
        def work(slot, item):
            barrier.wait()
            if item == 1:
                cancel.set()
                raise KeyboardInterrupt()
            self.assertTrue(cancel.wait(5))
            return "already published"
        completed = []
        with self.assertRaises(KeyboardInterrupt):
            for item, result in parallel_inspect([1, 2, 3], [object(), object()], work, lambda _: None,
                                                cancel, drain_on_cancel=True):
                completed.append((item, result))
        self.assertEqual(completed, [(2, "already published")])
        with self.assertRaises(KeyboardInterrupt):
            with resource_slot(threading.Semaphore(0), cancel):
                self.fail("Must not enter a cancelled GPU/copy slot")

    def test_dispatch_failure_drains_published_result(self):
        cancel = threading.Event()
        def work(slot, item):
            self.assertTrue(cancel.wait(5))
            return "published"
        def started(item):
            if item == 2:
                raise VideoMateError("io_error")
        completed = []
        with self.assertRaisesRegex(VideoMateError, "filesystem"):
            for result in parallel_inspect([1, 2, 3], [1, 2], work, started, cancel, drain_on_cancel=True):
                completed.append(result)
        self.assertEqual(completed, [(1, "published")])

    def test_fatal_shutdown_takes_priority_over_sibling_cancel(self):
        barrier = threading.Barrier(2, timeout=5)
        def work(slot, item):
            barrier.wait()
            if item == 1:
                raise KeyboardInterrupt()
            raise VideoMateError("worker_cleanup_failed")
        with self.assertRaises(VideoMateError) as error:
            list(parallel_inspect([1, 2], [1, 2], work, lambda _: None, threading.Event(), drain_on_cancel=True))
        self.assertEqual(error.exception.code, "worker_cleanup_failed")

    def test_shared_cpu_budget_and_explicit_runner_limit(self):
        for available, expected in ((None, 1), (1, 1), (2, 1), (16, 14)):
            with patch("videomate.execution.os.process_cpu_count", return_value=available, create=True):
                self.assertEqual(cpu_budget(), expected)
                self.assertEqual(cpu_budget(6), 6)
        for count in (1, 3, 30):
            slots = thread_slots(14, count)
            self.assertEqual(sum(slots), 14)
            self.assertEqual(len(slots), min(14, count))
        self.assertEqual(thread_slots(14, 30, 3), (5, 5, 4))
        for invalid in (-1, 1025, True, "8"):
            with self.assertRaises(VideoMateError):
                cpu_budget(invalid)

    def test_work_overlaps_but_start_and_result_callbacks_stay_on_caller(self):
        caller = threading.get_ident()
        barrier = threading.Barrier(2, timeout=5)
        active, workers = set(), set()
        lock = threading.Lock()
        def inspect(backend, item):
            with lock:
                self.assertNotIn(backend, active)
                active.add(backend)
                workers.add(threading.get_ident())
            barrier.wait()
            with lock:
                active.remove(backend)
            return item * 2
        def started(item):
            self.assertEqual(threading.get_ident(), caller)
        results = []
        for item, result in parallel_inspect(list(range(6)), ("slot-a", "slot-b"), inspect, started, threading.Event()):
            self.assertEqual(threading.get_ident(), caller)
            results.append((item, result))
        self.assertEqual(sorted(results), [(i, i * 2) for i in range(6)])
        self.assertEqual(len(workers), 2)

    def test_cancellation_and_generator_close_stop_pending_work(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(KeyboardInterrupt):
            list(parallel_inspect([1], [object()], lambda *_: self.fail(), lambda _: None, cancel))
        cancel.clear()
        entered = threading.Event()
        def inspect(backend, item):
            if item == 1:
                self.assertTrue(entered.wait(5))
            else:
                entered.set()
                self.assertTrue(cancel.wait(5))
            return item
        iterator = parallel_inspect([1, 2, 3], [object(), object()], inspect, lambda _: None, cancel)
        self.assertEqual(next(iterator), (1, 1))
        iterator.close()
        self.assertTrue(cancel.is_set())

    def test_decoder_failure_falls_back_but_resource_limit_stops(self):
        backend = object.__new__(FFmpegBackend)
        backend.scope = SimpleNamespace(authorize=lambda _: None)
        backend.decoder, backend.stream_codecs = "cuda", {0: "h264"}
        backend.hardware_gate, backend.runner = None, Runner()
        for outcome, calls in ((ProcessResult(1, stderr=b"PRIVATE_CANARY"), 2),
                               (ProcessResult(0, b"progress=end\n", b"[warning] unknown"), 2),
                               (ProcessResult(0, b"progress=end\n"), 1),
                               (ProcessResult(1, limited=True), 1)):
            with patch.object(backend, "_decode", side_effect=[outcome, ProcessResult(0, b"progress=end\n")]) as decode:
                backend.decode(Path("invented.mp4"), 0)
                self.assertEqual(decode.call_count, calls)
                self.assertEqual([step[1] for step in backend.last_decode_steps], ["cuda", "software"] if calls == 2 else ["cuda"])

    def test_decoder_listing_requires_forced_hardware_frame_check(self):
        with tempfile.TemporaryDirectory(prefix="videomate-decoder-generated-") as directory:
            backend = SimpleNamespace(ffmpeg=Path(directory) / "fake.exe", scratch=Path(directory), runner=Runner())
            for hw_result, selected in ((ProcessResult(1), "software"), (ProcessResult(0), "d3d11va")):
                with patch("videomate.hardware.platform.system", return_value="Windows"), \
                        patch("videomate.hardware.Runner.run", side_effect=[ProcessResult(0, b"d3d11va"), ProcessResult(0), hw_result]) as run:
                    self.assertEqual(select_decoder(backend), selected)
                    self.assertIn("hwdownload,format=nv12", run.call_args.args[0])
                    self.assertIn("-hwaccel_output_format", run.call_args.args[0])
