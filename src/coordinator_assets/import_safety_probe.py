"""Keep only warm imports that remain single-threaded after a fork."""

import importlib
import json
import os
import sys
import threading


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
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            importlib.import_module(module)
            threads = thread_count()
            result = {
                "module": module,
                "safe": threads == 1,
                "thread_count": threads,
                "reason": (
                    ""
                    if threads == 1
                    else f"import left {threads} process threads running"
                ),
            }
        except BaseException as error:
            result = {
                "module": module,
                "safe": False,
                "thread_count": None,
                "reason": f"import failed: {error}",
            }
        with os.fdopen(write_fd, "w") as stream:
            json.dump(result, stream)
        os._exit(0)

    os.close(write_fd)
    with os.fdopen(read_fd) as stream:
        raw_result = stream.read()
    os.waitpid(pid, 0)
    if not raw_result:
        return {
            "module": module,
            "safe": False,
            "thread_count": None,
            "reason": "probe child exited before reporting",
        }
    return json.loads(raw_result)


results = [probe(str(module)) for module in json.loads(sys.argv[1])]
sys.stdout.write(
    json.dumps(
        {
            "safe": [result["module"] for result in results if result["safe"]],
            "excluded": [result for result in results if not result["safe"]],
        }
    )
)
