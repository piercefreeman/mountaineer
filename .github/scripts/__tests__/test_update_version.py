import pytest

from scripts.update_version import format_cargo_version, format_python_version


@pytest.mark.parametrize(
    "input_version,expected",
    [
        ("1.2.3", "1.2.3"),
        ("1.2", "1.2.0"),
        ("1.2.3-alpha.1", "1.2.3-a1"),
        ("1.2.3-beta.2", "1.2.3-b2"),
        ("1.2.3.post1", "1.2.3-post1"),
        ("1.2.3.dev4", "1.2.3-dev4"),
        ("1.2.3-alpha.1.post2.dev3", "1.2.3-a1-post2-dev3"),
    ],
)
def test_format_cargo_version(input_version, expected):
    assert format_cargo_version(input_version) == expected


@pytest.mark.parametrize(
    "input_version,expected",
    [
        ("1.2.3", "1.2.3"),
        ("1.2.3a1", "1.2.3b1"),
        ("1.2.3b2", "1.2.3b2"),
        ("1.2.3rc3", "1.2.3b3"),
        ("1.2.3.post1", "1.2.3.post1"),
        ("1.2.3.dev4", "1.2.3.dev4"),
        ("1.2.3a1.post2.dev3", "1.2.3b1.post2.dev3"),
    ],
)
def test_format_python_version(input_version, expected):
    assert format_python_version(input_version) == expected
