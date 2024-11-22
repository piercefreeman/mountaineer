# NOTE: Only import on dev
import inspect
import linecache
import traceback
from dataclasses import dataclass
from typing import Dict, List

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer, guess_lexer_for_filename
from pygments.util import ClassNotFound


@dataclass
class ExceptionFrame:
    file_name: str
    line_number: int
    function_name: str
    code_context: str
    local_values: Dict[str, str]


@dataclass
class ParsedException:
    exc_type: str
    exc_value: str
    frames: List[ExceptionFrame]


class ExceptionParser:
    def __init__(self):
        self.formatter = HtmlFormatter(style="monokai")
        self.python_lexer = PythonLexer()

    def _get_lexer(self, filename: str, code: str):
        try:
            return guess_lexer_for_filename(filename, code)
        except ClassNotFound:
            return self.python_lexer

    def _get_context(self, filename: str, lineno: int, context_lines: int = 5) -> str:
        lines = []
        for i in range(lineno - context_lines, lineno + context_lines + 1):
            line = linecache.getline(filename, i)
            if line:
                lines.append(line)
        code = "".join(lines)
        lexer = self._get_lexer(filename, code)
        return highlight(code, lexer, self.formatter)

    def _format_value(self, value: object) -> str:
        try:
            if inspect.isclass(value) or inspect.isfunction(value):
                return str(value)
            formatted = highlight(repr(value), self.python_lexer, self.formatter)
            return formatted
        except Exception:
            return str(value)

    def parse_exception(self, exc: BaseException) -> ParsedException:
        frames = []
        tb = traceback.extract_tb(exc.__traceback__)

        for frame_summary in tb:
            filename = frame_summary.filename
            lineno = frame_summary.lineno
            function = frame_summary.name

            # Get locals from the frame
            frame = None
            tb_frame = exc.__traceback__
            while tb_frame is not None:
                if (
                    tb_frame.tb_frame.f_code.co_filename == filename
                    and tb_frame.tb_lineno == lineno
                ):
                    frame = tb_frame.tb_frame
                    break
                tb_frame = tb_frame.tb_next

            locals_dict = {}
            if frame is not None:
                for key, value in frame.f_locals.items():
                    if not key.startswith("__"):
                        locals_dict[key] = self._format_value(value)

            code_context = self._get_context(filename, lineno)

            frames.append(
                ExceptionFrame(
                    file_name=filename,
                    line_number=lineno,
                    function_name=function,
                    code_context=code_context,
                    local_values=locals_dict,
                )
            )

        return ParsedException(
            exc_type=exc.__class__.__name__, exc_value=str(exc), frames=frames
        )

    def get_style_defs(self) -> str:
        """Get CSS style definitions for syntax highlighting"""
        return self.formatter.get_style_defs()
