"""Run one idle worker owned by ``mountaineer-hot-reload-pool``.

Invocation::

    python -c "$SCRIPT" '["module.to.preload", "another.module"]'

The first positional argument is a JSON array of import names. Each module is
imported while the worker is idle; missing optional imports are reported to
stderr and skipped.

The worker then reads exactly one newline-delimited JSON command from stdin::

    {"command": "start", "generation": 1, "payload_path": "/abs/payload.json"}

``payload_path`` must reference a serialized ``RuntimePayload``. The
``generation`` field is carried for protocol consistency but is not interpreted
by this process. After activation, the worker restores normal SIGINT handling,
loads the payload, and serves until the Mountaineer runtime exits. It produces
no stdout protocol.
"""

import importlib
import json
import signal
import sys

for module in json.loads(sys.argv[1]):
    try:
        importlib.import_module(module)
    except ImportError as error:
        sys.stderr.write(f"Skipping optional warm import {module!r}: {error}\n")

signal.signal(signal.SIGINT, signal.SIG_IGN)
command = json.loads(sys.stdin.readline())
signal.signal(signal.SIGINT, signal.default_int_handler)

runtime = importlib.import_module("mountaineer.runtime")
payload = runtime.RuntimePayload.model_validate_json(
    open(command["payload_path"]).read()
)
runtime.serve_runtime(payload)
