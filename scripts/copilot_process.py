"""Own and stop one execution's process family, including orphan descendants.

Windows: a trusted Python wrapper joins a KILL_ON_JOB_CLOSE job before launching
the requested command. The parent keeps the only surviving job handle. POSIX:
the requested command starts a private session/process group. Call close() in
every exit path, even when guard.process has already exited.

This is process lifecycle isolation, not a replacement for an execution sandbox.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

_INHERIT_LOCK = threading.Lock()


def _windows_api():
    """Lazy Win32 declarations, allowing this module to import on POSIX."""
    from ctypes import wintypes as w

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", w.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", w.DWORD), ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    api.CreateJobObjectW.restype = w.HANDLE
    api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    api.SetInformationJobObject.restype = w.BOOL
    api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    api.AssignProcessToJobObject.restype = w.BOOL
    api.GetCurrentProcess.argtypes = []
    api.GetCurrentProcess.restype = w.HANDLE
    api.CloseHandle.argtypes = [w.HANDLE]
    api.CloseHandle.restype = w.BOOL
    return api, ExtendedLimits


class _WindowsJob:
    def __init__(self):
        self.api, limits_type = _windows_api()
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = limits_type()
            # No BREAKAWAY_OK or SILENT_BREAKAWAY_OK: descendants stay owned.
            limits.BasicLimitInformation.LimitFlags = 0x00002000
            if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle is not None:
            if not self.api.CloseHandle(self.handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


class ProcessGuard:
    def __init__(self, process, *, job=None, process_group=None):
        self.process = process
        self._job = job
        self._process_group = process_group
        self._closed = False
        self._close_lock = threading.Lock()

    def close(self):
        """Stop only this execution family; safe after leader exit and on retry."""
        with self._close_lock:
            if self._closed:
                return
            try:
                if self._job is not None:
                    # Close even when the wrapper/CLI exited: descendants may
                    # still be running, and ownership does not depend on a PID.
                    self._job.close()
                else:
                    try:
                        os.killpg(self._process_group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            finally:
                # If the Windows wrapper has not joined its job yet, killing
                # the wrapper closes its inherited handle before it can launch.
                # Do not close stdin here: another thread may be blocked in write.
                if self.process.poll() is None:
                    self.process.kill()
                self.process.wait(timeout=5)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def spawn(argv, *, cwd, stdin, stdout, stderr):
    """Return a guard with a binary Popen interface; never use a shell.

    Windows Job creation/configuration failure raises before any CLI launches.
    Assignment failure makes the trusted wrapper exit nonzero without launching
    the CLI; its diagnostic goes to stderr. No unguarded fallback is permitted.
    """
    if not isinstance(argv, (list, tuple)) or not argv or any(not isinstance(x, str) or not x for x in argv):
        raise ValueError("Process arguments must be a nonempty list of strings")
    if os.name != "nt":
        process = subprocess.Popen(argv, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr,
                                   start_new_session=True, close_fds=True)
        return ProcessGuard(process, process_group=process.pid)
    job = _WindowsJob()
    process = None
    try:
        wrapper = [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
                   "_job-wrapper", str(job.handle), json.dumps(list(argv), ensure_ascii=True)]
        info = subprocess.STARTUPINFO()
        info.lpAttributeList = {"handle_list": [job.handle]}
        # Only the job handle (plus Python-managed standard streams) is given
        # to the trusted wrapper, which closes it before starting the CLI.
        with _INHERIT_LOCK:
            os.set_handle_inheritable(job.handle, True)
            try:
                process = subprocess.Popen(wrapper, cwd=cwd, stdin=stdin, stdout=stdout, stderr=stderr,
                    startupinfo=info, close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW)
            finally:
                os.set_handle_inheritable(job.handle, False)
        return ProcessGuard(process, job=job)
    except BaseException:
        try:
            job.close()
        finally:
            if process is not None:
                process.kill()
                process.wait(timeout=5)
        raise


def _run_windows_wrapper(handle, argv):
    """No untrusted command is launched until this process owns the job."""
    api, _ = _windows_api()
    try:
        if not api.AssignProcessToJobObject(handle, api.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        # The parent retains its non-inheritable handle. No CLI descendant can
        # keep the job alive after the parent closes the guard.
        if not api.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    child = subprocess.Popen(argv, stdin=sys.stdin.buffer, stdout=sys.stdout.buffer,
                             stderr=sys.stderr.buffer, close_fds=True,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    return child.wait()


if __name__ == "__main__":
    if os.name != "nt" or len(sys.argv) != 4 or sys.argv[1] != "_job-wrapper":
        raise SystemExit("This module is an internal process guard, not a shell entrypoint")
    try:
        command = json.loads(sys.argv[3])
        if not isinstance(command, list) or not command or any(not isinstance(x, str) for x in command):
            raise ValueError("Invalid guarded command")
        raise SystemExit(_run_windows_wrapper(int(sys.argv[2]), command))
    except (OSError, ValueError) as exc:
        print("Process guard unavailable; command not run: " + str(exc), file=sys.stderr, flush=True)
        raise SystemExit(125)
