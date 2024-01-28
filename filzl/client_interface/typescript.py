"""
Utilities to generate some common Typescript objects from
Python definitions.

"""
from typing import Any


class TSLiteral(str):
    """
    This string should not be quoted when used in a Typescript insert.
    """

    pass


def python_payload_to_typescript(payload: Any) -> str:
    """
    Take an element with python tokens that should be outputted to
    Typescript and consolidate them into a valid payload.

    """
    if isinstance(payload, dict):
        # Convert the children
        children_lines: list[str] = []
        for key, value in payload.items():
            if isinstance(value, TSLiteral):
                # If the literal is the same as the key, we don't need to include it since it's referencing
                # the same variable.
                if key == value:
                    children_lines.append(key)
                    continue

            key = python_payload_to_typescript(key)
            value = python_payload_to_typescript(value)
            children_lines.append(f"{key}: {value}")

        children_str = ",\n".join(children_lines)
        return f"{{\n{children_str}\n}}"
    elif isinstance(payload, list):
        children_lines = [python_payload_to_typescript(child) for child in payload]
        children_str = ",\n".join(children_lines)
        return f"[\n{children_str}\n]"
    elif isinstance(payload, TSLiteral):
        return payload
    elif isinstance(payload, str):
        return f"'{payload}'"
    elif isinstance(payload, bool):
        return str(payload).lower()
    elif isinstance(payload, (int, float)):
        return str(payload)
    else:
        raise ValueError(
            f"Unknown payload type {type(payload) } for Typescript conversion."
        )
