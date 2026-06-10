import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from os import PathLike
from typing import Mapping

from rich.ansi import AnsiDecoder
from rich.console import Console
from rich.markup import escape
from rich.padding import Padding
from rich.text import Text
from rich.theme import Theme

THEME = Theme(
    {
        "command": "bold cyan",
        "error": "bold red",
        "heading": "bold blue",
        "label": "dim",
        "muted": "dim",
        "success": "bold green",
        "warning": "bold yellow",
    }
)

CONSOLE = Console(theme=THEME)
ERROR_CONSOLE = Console(stderr=True, theme=THEME)
ANSI_DECODER = AnsiDecoder()


def section(title: str) -> None:
    CONSOLE.print()
    CONSOLE.print(f"[heading]{escape(title)}[/heading]")


def detail(label: str, value: object) -> None:
    label_text = f"{label}:".ljust(17)
    CONSOLE.print(f"  [label]{escape(label_text)}[/label]{escape(str(value))}")


def command(command_parts: list[str]) -> None:
    CONSOLE.print(f"  [command]RUN  [/command] {escape(' '.join(command_parts))}")


def command_output(line: str) -> None:
    if not line:
        CONSOLE.print()
        return

    output = Text()
    for segment in ANSI_DECODER.decode(line):
        output.append_text(segment)
    CONSOLE.print(Padding(output, (0, 0, 0, 4)))


def run_command(
    command_parts: list[str],
    *,
    cwd: str | PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    command(command_parts)
    with subprocess.Popen(
        command_parts,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as process:
        if process.stdout is not None:
            for raw_line in process.stdout:
                for line in raw_line.rstrip("\n").split("\r"):
                    command_output(line)

        returncode = process.wait()
    if returncode:
        raise subprocess.CalledProcessError(returncode, command_parts)


def success(message: str) -> None:
    CONSOLE.print(f"  [success]OK   [/success] {escape(message)}")


def warning(message: str) -> None:
    CONSOLE.print(f"  [warning]WARN [/warning] {escape(message)}")


def error(message: str) -> None:
    ERROR_CONSOLE.print(f"  [error]ERROR[/error] {escape(message)}")


@contextmanager
def status(message: str) -> Iterator[None]:
    with CONSOLE.status(f"[heading]{escape(message)}[/heading]", spinner="dots"):
        yield
