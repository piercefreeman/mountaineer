"""Small runtime used to exercise the real fork strategy without a web server."""

import json
import os
import signal
import sys
from pathlib import Path


class RuntimePayload:
    model_validate_json = staticmethod(json.loads)


def serve_runtime(payload):
    result = {"pid": os.getpid(), "parent": os.getppid()}
    exec(payload["code"], {"result": result, "os": os, "sys": sys})
    path = Path(payload["result"])
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(result))
    pending.replace(path)
    while True:
        signal.pause()
