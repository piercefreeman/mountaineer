import inspect
import linecache
import traceback
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer, guess_lexer_for_filename
from pygments.util import ClassNotFound


class ExceptionFrame(BaseModel):
    id: UUID
    file_name: str
    line_number: int
    function_name: str
    local_values: dict[str, str]
    code_context: str
    start_line_number: int
    end_line_number: int


class ParsedException(BaseModel):
    exc_type: str
    exc_value: str
    frames: list[ExceptionFrame]


class ExceptionParser:
    def __init__(self):
        self.formatter = HtmlFormatter(style="github-dark")
        self.python_lexer = PythonLexer()

    def _get_lexer(self, filename: str, code: str):
        try:
            return guess_lexer_for_filename(filename, code)
        except ClassNotFound:
            return self.python_lexer

    def _get_context(
        self, filename: str, lineno: int, context_lines: int = 5
    ) -> tuple[str, int, int]:
        """
        Get the code context and starting line number for the given error location.

        :param filename: Path to the source file
        :param lineno: Line number where the error occurred
        :param context_lines: Number of lines to show before and after the error

        """
        start_line = max(lineno - context_lines, 1)  # Don't go below line 1
        end_line = lineno + context_lines + 1

        lines = []
        for i in range(start_line, end_line):
            line = linecache.getline(filename, i)
            if line:
                lines.append(line)
        code = "".join(lines)

        lexer = self._get_lexer(filename, code)
        highlighted = highlight(code, lexer, self.formatter)

        return highlighted, start_line, end_line

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

            code_context, start_line, end_line = self._get_context(
                filename, lineno or -1
            )

            frames.append(
                ExceptionFrame(
                    id=uuid4(),
                    file_name=self.get_package_path(filename),
                    line_number=lineno or -1,
                    function_name=function,
                    code_context=code_context,
                    local_values=locals_dict,
                    start_line_number=start_line,
                    end_line_number=end_line,
                )
            )

        return ParsedException(
            exc_type=exc.__class__.__name__, exc_value=str(exc), frames=frames
        )

    def get_style_defs(self) -> str:
        """Get CSS style definitions for syntax highlighting"""
        return self.formatter.get_style_defs()  # type: ignore

    def get_package_path(self, filepath: str) -> str:
        """
        Extract the relevant package path from a full system path.

        Args:
            filepath: Full system path to a Python file

        Returns:
            Shortened path relative to closest parent package
        """
        path = Path(filepath)

        # Find closest parent directory with __init__.py
        current = path.parent
        package_root = None

        while True:
            if (current / "__init__.py").exists():
                package_root = current
                current = current.parent
            else:
                break

        if package_root is None:
            # No package found, use filename only
            return path.name

        # Get relative path from package root
        try:
            rel_path = path.relative_to(package_root.parent)
            return str(rel_path)
        except ValueError:
            # Fallback to filename if relative_to fails
            return path.name
