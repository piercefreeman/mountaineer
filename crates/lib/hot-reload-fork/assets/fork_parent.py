"""Run the Unix fork parent used by ``mountaineer-hot-reload-fork``.

Invocation::

    python -c "$SCRIPT" '["module.to.preload", "another.module"]'

The first positional argument is a JSON array of import names. Each module is
imported before any backend is forked; missing optional imports are reported to
stderr and skipped.

After startup, read newline-delimited JSON commands from stdin:

* ``{"command": "start", "generation": 1, "payload_path": "/abs/payload.json"}``
  forks a backend that loads the Mountaineer runtime payload at ``payload_path``.
* ``{"command": "stop", "generation": 1}`` terminates that generation.
* ``{"command": "exit"}`` terminates every generation and exits the parent.

The process writes diagnostics to stderr and intentionally produces no stdout
protocol. It exits unsuccessfully if an active backend dies unexpectedly so
the Rust owner can treat parent exit as a fatal lifecycle event.
"""

import importlib
import json
import os
import select
import signal
import sys
import traceback

for module in json.loads(sys.argv[1]):
    try:
        importlib.import_module(module)
    except ImportError as error:
        sys.stderr.write(f"Skipping optional warm import {module!r}: {error}\n")

signal.signal(signal.SIGINT, signal.SIG_IGN)
children: dict[int, int] = {}


def stop(generation: int) -> None:
    pid = children.pop(generation, None)
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, 0)
    except ProcessLookupError:
        pass


try:
    while True:
        for generation, pid in list(children.items()):
            exited_pid, status = os.waitpid(pid, os.WNOHANG)
            if exited_pid:
                children.pop(generation)
                raise RuntimeError(
                    f"backend generation {generation} exited unexpectedly "
                    f"with status {status}"
                )

        readable, _, _ = select.select([sys.stdin], [], [], 0.1)
        if not readable:
            continue
        line = sys.stdin.readline()
        if not line:
            break
        command = json.loads(line)
        if command["command"] == "start":
            generation = command["generation"]
            pid = os.fork()
            if pid == 0:
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                try:
                    from mountaineer.runtime import RuntimePayload, serve_runtime

                    payload = RuntimePayload.model_validate_json(
                        open(command["payload_path"]).read()
                    )
                    serve_runtime(payload)
                except BaseException:
                    traceback.print_exc()
                finally:
                    os._exit(1)
            children[generation] = pid
        elif command["command"] == "stop":
            stop(command["generation"])
        elif command["command"] == "exit":
            break
finally:
    for generation in list(children):
        stop(generation)
