"""Run the Unix fork parent used by ``mountaineer-hot-reload-fork``.

Invocation::

    python -c "$SCRIPT" '["module.to.preload", "another.module"]'

The first positional argument is a JSON array of import names. Each module is
imported before any backend is forked; missing optional imports are reported to
stderr and skipped.

After startup, read newline-delimited JSON commands from stdin:

* ``{"command": "start", "generation": 1, "payload_path": "/abs/payload.json",
  "exit_status_path": "/abs/payload.1.exit"}`` forks a backend that loads the
  runtime payload and reports its eventual wait status at ``exit_status_path``.
* ``{"command": "stop", "generation": 1}`` terminates that generation.
* ``{"command": "exit"}`` terminates every generation and exits the parent.

Backend failures are printed to stdout; it carries no machine protocol.
Backend exits are reported individually so a failed replacement
does not terminate the last working backend.
"""

import importlib
import json
import os
import select
import signal
import sys
import traceback
from pathlib import Path
from textwrap import indent

for module in json.loads(sys.argv[1]):
    try:
        importlib.import_module(module)
    except ImportError as error:
        sys.stderr.write(f"Skipping optional warm import {module!r}: {error}\n")

signal.signal(signal.SIGINT, signal.SIG_IGN)
children: dict[int, tuple[int, Path]] = {}
stdin = sys.stdin.buffer.raw


def stop(generation: int) -> None:
    child = children.pop(generation, None)
    if child is None:
        return
    pid, _ = child
    try:
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, 0)
    except ProcessLookupError:
        pass


try:
    while True:
        for generation, (pid, exit_status_path) in list(children.items()):
            exited_pid, status = os.waitpid(pid, os.WNOHANG)
            if exited_pid:
                children.pop(generation)
                # Publish atomically so the Rust waiter cannot read a partial status.
                temporary_path = exit_status_path.with_suffix(".tmp")
                temporary_path.write_text(json.dumps(status))
                temporary_path.replace(exit_status_path)

        readable, _, _ = select.select([stdin], [], [], 0.1)
        if not readable:
            continue
        line = stdin.readline()
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
                    sys.stdout.write(
                        "\nFailed Python backend\n"
                        + indent(traceback.format_exc(), "  ")
                        + "\n"
                    )
                    sys.stdout.flush()
                finally:
                    os._exit(1)
            children[generation] = pid, Path(command["exit_status_path"])
        elif command["command"] == "stop":
            stop(command["generation"])
        elif command["command"] == "exit":
            break
finally:
    for generation in list(children):
        stop(generation)
