"""
Utilities to generate some common Typescript objects from
Python definitions.

"""
from typing import Any

from inflection import camelize


class TSLiteral(str):
    """
    This string should not be quoted when used in a Typescript insert.
    """

    def __add__(self, other):
        # Concatenate self (TSLiteral) with other (any string)
        # and return a new TSLiteral object
        if isinstance(other, str):
            return TSLiteral(super(TSLiteral, self).__add__(other))
        return NotImplemented

    def __radd__(self, other):
        # Handle right-side addition, where a string is added to a TSLiteral
        if isinstance(other, str):
            return TSLiteral(other.__add__(self))
        return NotImplemented


def python_payload_to_typescript(
    payload: Any, dict_equality: str = ":", current_indent: int = 0
) -> str:
    """
    Take an element with python tokens that should be outputted to
    Typescript and consolidate them into a valid payload.

    """
    indent_str = " " * current_indent
    inner_indent_str = " " * (current_indent + 2)

    if isinstance(payload, dict):
        # Convert the children
        children_lines: list[str] = []
        for key, value in payload.items():
            if isinstance(value, TSLiteral):
                # If the literal is the same as the key, we don't need to include it since it's referencing
                # the same variable.
                if key == value:
                    children_lines.append(f"{inner_indent_str}{key}")
                    continue

            key = python_payload_to_typescript(key)
            value = python_payload_to_typescript(
                value, current_indent=current_indent + 2
            )
            children_lines.append(f"{inner_indent_str}{key}{dict_equality} {value}")

        children_str = ",\n".join(children_lines)
        return "\n".join(
            [
                "{",
                children_str,
                f"{indent_str}}}",
            ]
        )
    elif isinstance(payload, list):
        children_lines = [python_payload_to_typescript(child) for child in payload]
        children_str = ",\n".join(
            [f"{inner_indent_str}{child}" for child in children_lines]
        )
        return f"[\n{children_str}\n{indent_str}]"
    elif isinstance(payload, TSLiteral):
        return payload
    elif isinstance(payload, str):
        return f"'{payload}'"
    elif isinstance(payload, bool):
        return str(payload).lower()
    elif isinstance(payload, (int, float)):
        return str(payload)
    elif payload is None:
        return "null"
    else:
        raise ValueError(
            f"Unknown payload type {type(payload) } for Typescript conversion."
        )


def normalize_interface(title: str):
    replace_chars = {" ", "[", "]"}

    for char in replace_chars:
        title = title.strip(char)
        title = title.replace(char, "_")

    return camelize(title)
