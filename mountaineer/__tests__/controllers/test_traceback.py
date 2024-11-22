from textwrap import dedent

import pytest

from mountaineer.controllers.traceback import ExceptionParser


def nested_function(x: int) -> None:
    local_var = "test string"
    nested_dict = {"key": "value"}
    raise ValueError(f"Test error with {x}")


def function_with_locals() -> None:
    x = 42
    y = "string"
    z = [1, 2, 3]
    nested_function(x)


@pytest.fixture
def parser():
    return ExceptionParser()


@pytest.fixture
def complex_exception() -> ValueError:
    try:
        function_with_locals()
    except ValueError as e:
        return e
    raise RuntimeError("Expected ValueError was not raised")


def test_basic_exception_parsing(parser):
    try:
        raise ValueError("Test error")
    except ValueError as e:
        result = parser.parse_exception(e)

    assert result.exc_type == "ValueError"
    assert result.exc_value == "Test error"
    assert len(result.frames) > 0

    frame = result.frames[-1]
    assert frame.file_name.endswith(f"{__name__}.py")
    assert isinstance(frame.line_number, int)
    assert frame.function_name == "test_basic_exception_parsing"
    assert isinstance(frame.code_context, str)
    assert "<span" in frame.code_context
    assert isinstance(frame.local_values, dict)


def test_nested_exception_with_locals(parser, complex_exception):
    result = parser.parse_exception(complex_exception)

    assert result.exc_type == "ValueError"
    assert "Test error with 42" in result.exc_value
    assert len(result.frames) >= 2

    nested_frame = None
    for frame in result.frames:
        if frame.function_name == "nested_function":
            nested_frame = frame
            break

    assert nested_frame is not None
    assert "local_var" in nested_frame.local_values
    assert "nested_dict" in nested_frame.local_values
    assert isinstance(nested_frame.local_values["local_var"], str)
    assert "<span" in nested_frame.local_values["nested_dict"]


def test_syntax_highlighting(parser):
    try:
        x = {"complex": [1, 2, 3], "dict": {"nested": True}}
        raise Exception("Test")
    except Exception as e:
        result = parser.parse_exception(e)

    frame = result.frames[-1]
    assert "class=" in frame.code_context
    assert "span" in frame.code_context
    assert frame.local_values["x"].count("<span") > 1


def test_different_file_types(parser, tmp_path):
    py_file = tmp_path / "test.py"
    py_file.write_text(
        dedent(
            """
        def test_function():
            x = 42
            raise ValueError("Test")
    """
        )
    )

    import importlib.util

    spec = importlib.util.spec_from_file_location("test_module", py_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    try:
        module.test_function()
    except ValueError as e:
        result = parser.parse_exception(e)

    frame = result.frames[-1]
    assert frame.file_name == str(py_file)
    assert "test_function" in frame.code_context
    assert "<span" in frame.code_context


def test_get_style_defs(parser):
    styles = parser.get_style_defs()
    assert isinstance(styles, str)
    assert len(styles) > 0


def test_exception_without_traceback(parser):
    exc = ValueError("Test error")
    result = parser.parse_exception(exc)

    assert result.exc_type == "ValueError"
    assert result.exc_value == "Test error"
    assert isinstance(result.frames, list)


def test_line_numbers_accuracy(parser):
    def error_on_specific_line():
        x = 1
        y = 2
        raise ValueError("Test")

    try:
        error_on_specific_line()
    except ValueError as e:
        result = parser.parse_exception(e)

    frame = result.frames[-1]
    assert "ValueError" in frame.code_context
    assert frame.line_number > 0
