"""Job-scoped resource counters. No adapter identity or wall-clock timestamps."""
import threading


class HardwareActivity:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = {}
        self.peak_jobs = self.peak_routes = 0

    def gate(self, slot, limit):
        return MeasuredGate(self, slot, limit)


class MeasuredGate:
    def __init__(self, activity, slot, limit):
        self.activity, self.slot = activity, slot
        self.semaphore = threading.Semaphore(limit)
        self.peak = 0

    def acquire(self, *args, **kwargs):
        if not self.semaphore.acquire(*args, **kwargs):
            return False
        a = self.activity
        with a.lock:
            a.active[self.slot] = a.active.get(self.slot, 0) + 1
            self.peak = max(self.peak, a.active[self.slot])
            a.peak_jobs = max(a.peak_jobs, sum(a.active.values()))
            a.peak_routes = max(a.peak_routes, sum(n > 0 for n in a.active.values()))
        return True

    def release(self):
        with self.activity.lock:
            self.activity.active[self.slot] -= 1
        self.semaphore.release()


def report(activity, devices, gates, decode_requested, encode_requested, selection):
    return {'decode_requested': decode_requested, 'encode_requested': encode_requested,
            'integrity_decoder': 'software', 'decode_selection': selection,
            'peak_active_routes': activity.peak_routes, 'peak_gpu_jobs': activity.peak_jobs,
            'routes': [{'slot': n, 'decoder': d, 'encoder': e,
                        'peak_jobs': gates[(e, device)].peak} for n, (d, e, device) in enumerate(devices, 1)]}
