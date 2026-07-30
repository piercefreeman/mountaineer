"""Pre-import dependencies, then wait to become one Windows app worker."""

import importlib
import json
import signal
import sys

from mountaineer.runtime import RuntimePayload, serve_runtime

for module in json.loads(sys.argv[1]):
    try:
        importlib.import_module(module)
    except ImportError as error:
        sys.stderr.write(f"Skipping optional warm import {module!r}: {error}\n")

signal.signal(signal.SIGINT, signal.SIG_IGN)
command = json.loads(sys.stdin.readline())
signal.signal(signal.SIGINT, signal.default_int_handler)

payload = RuntimePayload.model_validate_json(open(command["payload_path"]).read())
serve_runtime(payload)
