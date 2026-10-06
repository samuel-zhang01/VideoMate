"""Windows worker lifecycle support, not filesystem/network containment.

Assignment occurs immediately after Popen. This does not close the pre-assignment
spawn race and must not be represented as a qualified security boundary.
"""

import ctypes
import time
from ctypes import wintypes

from .errors import VideoMateError


class _BasicLimit(ctypes.Structure):
    _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
                ("Flags", wintypes.DWORD), ("MinWorkingSet", ctypes.c_size_t),
                ("MaxWorkingSet", ctypes.c_size_t), ("ActiveProcesses", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("Priority", wintypes.DWORD),
                ("Scheduling", wintypes.DWORD)]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [("Basic", _BasicLimit), ("IO", _IOCounters),
                ("ProcessMemory", ctypes.c_size_t), ("JobMemory", ctypes.c_size_t),
                ("PeakProcessMemory", ctypes.c_size_t), ("PeakJobMemory", ctypes.c_size_t)]


class _BasicAccounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in ("UserTime", "KernelTime", "PeriodUserTime", "PeriodKernelTime")] + [
        (name, wintypes.DWORD) for name in ("PageFaults", "TotalProcesses", "ActiveProcesses", "TerminatedProcesses")]


class WindowsJob:
    def __init__(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.TerminateJobObject.restype = wintypes.BOOL
        self.api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.api.QueryInformationJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise VideoMateError("backend_unavailable")
        limits = _ExtendedLimit()
        limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise VideoMateError("backend_unavailable")

    def assign(self, process):
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise VideoMateError("backend_unavailable")

    def close(self):
        if self.handle:
            try:
                # Closing alone requests asynchronous termination. Keep the
                # handle until all assigned workers exit before scratch cleanup.
                if not self.api.TerminateJobObject(self.handle, 1):
                    raise VideoMateError("worker_cleanup_failed")
                deadline = time.monotonic() + 5
                while True:
                    state = _BasicAccounting()
                    if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(state), ctypes.sizeof(state), None):
                        raise VideoMateError("worker_cleanup_failed")
                    if state.ActiveProcesses == 0:
                        break
                    if time.monotonic() >= deadline:
                        raise VideoMateError("worker_cleanup_failed")
                    time.sleep(0.01)
            finally:
                self.api.CloseHandle(self.handle)
                self.handle = None
