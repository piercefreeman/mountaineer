from textwrap import dedent

import pytest

from mountaineer.client_builder.file_generators.base import CodeBlock


class TestCodeBlock:
    def test_initialization(self):
        simple_code_block = CodeBlock("line1", "line2")
        assert simple_code_block.lines == ("line1", "line2")

    @pytest.mark.parametrize(
        "input_str, expected",
        [
            # Empty string cases
            ("", ""),
            # Single line cases
            ("hello", "hello"),
            ("    hello", "    hello"),
            ("\thello", "\thello"),
            # Basic multi-line cases - adding to subsequent indentation
            (
                "    first\n        second\n            third",
                "    first\n            second\n                third",
            ),
            (
                "\tfirst\n\t\tsecond\n\t\t\tthird",
                "\tfirst\n\t\t\tsecond\n\t\t\t\tthird",
            ),
            # Cases with trailing newlines
            ("    first\n        second\n", "    first\n            second\n"),
            # Cases with empty lines
            ("    first\n\n        third", "    first\n\n            third"),
            ("    first\n  \n        third", "    first\n  \n            third"),
            # Cases with mixed indentation - adding first line indent
            (
                "    first\n  second\n      third",
                "    first\n      second\n          third",
            ),
            # Cases with tabs and spaces
            ("\tfirst\n    second\n\t\tthird", "\tfirst\n\t    second\n\t\t\tthird"),
            # Complex multi-line string cases
            (
                dedent(
                    """
            def example():
                x = '''
                multi
                line
                string'''
            """
                ).strip(),
                "def example():\n    x = '''\n    multi\n    line\n    string'''",
            ),
        ],
    )
    def test_indent_variations(self, input_str, expected):
        result = CodeBlock.indent(input_str)
        assert result == expected

    def test_real_world_template_strings(self):
        # Test with f-strings and template variables
        var = "hello\n    world"  # Note: intentional indentation in var
        input_str = f"    print({var})"
        expected = "    print(hello\n        world)"
        assert CodeBlock.indent(input_str) == expected

        # Test with triple-quoted strings
        var = """first
            second
                third"""
        input_str = f"    function({var})"
        expected = (
            "    function(first\n                second\n                    third)"
        )
        assert CodeBlock.indent(input_str) == expected

    def test_whitespace_preservation(self):
        # Test that trailing whitespace is preserved
        input_str = "    x = 1  # trailing spaces  \n        y = 2"
        expected = "    x = 1  # trailing spaces  \n            y = 2"
        assert CodeBlock.indent(input_str) == expected

        # Test with tabs and spaces mixed
        input_str = "\t    x = 1\n\t\t    y = 2"
        expected = "\t    x = 1\n\t    \t\t    y = 2"
        assert CodeBlock.indent(input_str) == expected

    def test_multiple_newlines(self):
        # Test handling of multiple consecutive newlines
        input_str = "    first\n\n\n        second"
        expected = "    first\n\n\n            second"
        assert CodeBlock.indent(input_str) == expected

    def test_unicode_handling(self):
        # Test with unicode characters
        input_str = "    🐍 = 'python'\n        © = 'copyright'"
        expected = "    🐍 = 'python'\n            © = 'copyright'"
        assert CodeBlock.indent(input_str) == expected
