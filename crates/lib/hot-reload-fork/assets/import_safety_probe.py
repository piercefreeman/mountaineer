"""Probe one Python import in a fresh interpreter before retaining it across fork.

Invocation::

    python -c "$SCRIPT" module.to.probe

The Rust caller starts a fresh interpreter per import. Probing in an already
forked child can change native library initialization and miss thread creation.

The script reads no stdin. It writes one JSON object to stdout::

    {
      "module": "module.to.probe",
      "safe": false,
      "thread_count": 2,
      "reason": "import left 2 process threads running"
    }

An import is accepted only when it succeeds and leaves exactly one process thread.
On macOS, it must also never have started another native thread, even one that
has already exited: the Objective-C runtime retains that history across fork.
``thread_count`` is ``null`` when the import fails or cannot report a result.
"""

import importlib
import json
import os
import sys
import threading
from contextlib import redirect_stdout


def thread_count() -> int:
    if sys.platform.startswith("linux"):
        return len(os.listdir("/proc/self/task"))
    if sys.platform == "darwin":
        import ctypes

        class ProcTaskInfo(ctypes.Structure):
            _fields_ = [
                ("pti_virtual_size", ctypes.c_uint64),
                ("pti_resident_size", ctypes.c_uint64),
                ("pti_total_user", ctypes.c_uint64),
                ("pti_total_system", ctypes.c_uint64),
                ("pti_threads_user", ctypes.c_uint64),
                ("pti_threads_system", ctypes.c_uint64),
                ("pti_policy", ctypes.c_int32),
                ("pti_faults", ctypes.c_int32),
                ("pti_pageins", ctypes.c_int32),
                ("pti_cow_faults", ctypes.c_int32),
                ("pti_messages_sent", ctypes.c_int32),
                ("pti_messages_received", ctypes.c_int32),
                ("pti_syscalls_mach", ctypes.c_int32),
                ("pti_syscalls_unix", ctypes.c_int32),
                ("pti_csw", ctypes.c_int32),
                ("pti_threadnum", ctypes.c_int32),
                ("pti_numrunning", ctypes.c_int32),
                ("pti_priority", ctypes.c_int32),
            ]

        info = ProcTaskInfo()
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        size = libproc.proc_pidinfo(
            os.getpid(), 4, 0, ctypes.byref(info), ctypes.sizeof(info)
        )
        if size == ctypes.sizeof(info):
            return info.pti_threadnum
    return threading.active_count()


def probe(module: str) -> dict[str, object]:
    try:
        importlib.import_module(module)
        threads = thread_count()
        reason = (
            "" if threads == 1 else f"import left {threads} process threads running"
        )
        if sys.platform == "darwin":
            import ctypes

            # This native flag stays set after threads exit, unlike thread_count().
            if ctypes.CDLL(None).pthread_is_threaded_np():
                reason = "import started native threads; unsafe to fork on macOS"
        return {
            "module": module,
            "safe": not reason,
            "thread_count": threads,
            "reason": reason,
        }
    except BaseException as error:
        return {
            "module": module,
            "safe": False,
            "thread_count": None,
            "reason": f"import failed: {error}",
        }


with redirect_stdout(sys.stderr):
    result = probe(sys.argv[1])
sys.stdout.write(json.dumps(result))
sys.stdout.flush()
# Imports may leave non-daemon threads behind; do not wait for them at shutdown.
os._exit(0)
