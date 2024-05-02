import sys

import pytest

from mountaineer.compat import StrEnum


class GoodStrEnum(StrEnum):
    one = "1"
    two = "2"
    three = bytes("3", "ascii").decode("ascii")
    four = bytes("4", "latin1").decode("latin1")


def test_first_failed_str_enum():
    with pytest.raises(TypeError, match="1 is not a string"):

        class FirstFailedStrEnum(StrEnum):
            one = 1  # type: ignore
            two = "2"


def test_second_failed_str_enum():
    with pytest.raises(TypeError, match="2 is not a string"):

        class SecondFailedStrEnum(StrEnum):
            one = "1"
            two = (2,)  # type: ignore
            three = "3"


def test_third_failed_str_enum():
    with pytest.raises(TypeError, match="2 is not a string"):

        class ThirdFailedStrEnum(StrEnum):
            one = "1"
            two = 2  # type: ignore


def test_third_failed_str_enum_encoding_issue():
    with pytest.raises(
        TypeError, match="encoding must be a string, not %r" % (sys.getdefaultencoding,)
    ):

        class FourthFailedStrEnum(StrEnum):
            one = "1"
            two = b"2", sys.getdefaultencoding  # type: ignore


def test_third_failed_str_enum_errors_issue():
    with pytest.raises(TypeError, match="errors must be a string, not 9"):

        class FifthFailedStrEnum(StrEnum):
            one = "1"
            two = b"2", "ascii", 9  # type: ignore


class DumbMixin:
    def __str__(self):  # type: ignore
        # Overrides the necessary __str__ method in the class handler
        # to prevent the StrEnum from returning the value of the enum
        return "don't do this"


class DumbStrEnum(DumbMixin, StrEnum):  # type: ignore
    five = "5"
    six = "6"
    seven = "7"


def test_dumb_str_enum():
    assert DumbStrEnum.seven == "7"
    assert str(DumbStrEnum.seven) == "don't do this"


class EnumMixin:
    def hello(self):
        pass


class HelloEnum(EnumMixin, StrEnum):
    eight = "8"


def test_hello_enum():
    assert HelloEnum.eight == "8"
    assert HelloEnum.eight == str(HelloEnum.eight)


class GoodbyeMixin:
    def goodbye(self):
        pass


class GoodbyeEnum(GoodbyeMixin, EnumMixin, StrEnum):
    nine = "9"


def test_goodbye_enum():
    assert GoodbyeEnum.nine == "9"
    assert GoodbyeEnum.nine == str(GoodbyeEnum.nine)
