"""Dispatch a Python process requested by Mountaineer's Rust runtime.

Invocation::

    python -m mountaineer.runtime_cli serve /absolute/runtime-payload.json
    python -m mountaineer.runtime_cli build-generated /absolute/runtime-payload.json

The final argument must contain a serialized ``RuntimePayload``. ``serve``
starts the configured production server; ``build-generated`` loads the
development controller, regenerates its managed TypeScript client files, and
exits. Diagnostics go to stderr and the exit status reports success or failure.
"""

from pathlib import Path
from sys import argv

from mountaineer.runtime import RuntimePayload, build_generated, serve_runtime


def main() -> None:
    try:
        command, payload_path = argv[1:]
    except ValueError:
        raise SystemExit(
            "usage: python -m mountaineer.runtime_cli {serve|build-generated} PAYLOAD"
        ) from None

    payload = RuntimePayload.model_validate_json(Path(payload_path).read_text())
    if command == "serve":
        serve_runtime(payload)
    elif command == "build-generated":
        build_generated(payload)
    else:
        raise SystemExit(f"unknown runtime command: {command}")


if __name__ == "__main__":
    main()
