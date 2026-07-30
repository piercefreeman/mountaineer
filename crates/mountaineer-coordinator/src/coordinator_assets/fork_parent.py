"""Warm Python import template controlled by the Rust coordinator."""

import importlib
import json
import os
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


for line in sys.stdin:
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

for generation in list(children):
    stop(generation)
