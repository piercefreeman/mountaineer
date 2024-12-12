from dataclasses import dataclass
from enum import Enum, auto
from typing import List


class TokenType(Enum):
    IMPORT = auto()
    EXPORT = auto()
    DECLARE = auto()
    RETURN = auto()
    FUNCTION = auto()
    ARROW = auto()
    TYPE_DECL = auto()  # interface, type, etc.
    OPEN_BRACE = auto()
    CLOSE_BRACE = auto()
    SEMICOLON = auto()
    OTHER = auto()


@dataclass
class Token:
    type: TokenType
    content: str
    line_number: int
    consume_next: bool = False


class FormattingContext:
    def __init__(self):
        self.in_return_statement = False
        self.in_import_statement = False
        self.in_type_declaration = False
        self.brace_stack = []
        self.current_indent = 0
        self.consumed_lines = set()


class TypeScriptFormatter:
    def __init__(self, indent_size: int = 2):
        self.indent_size = indent_size

    def tokenize_line(self, line: str, line_number: int) -> List[Token]:
        """Convert a line into a series of tokens."""
        line = line.strip()
        if not line:
            return []

        tokens = []

        # Handle complete line patterns first
        if line.startswith("import "):
            tokens.append(Token(TokenType.IMPORT, line, line_number))
            return tokens

        if line.startswith("export "):
            if "interface " in line or "type " in line:
                # Check if it's a type alias (no brace needed) or interface (needs brace)
                if "type " in line and "=" in line:
                    tokens.append(Token(TokenType.TYPE_DECL, line, line_number))
                else:
                    tokens.append(Token(TokenType.TYPE_DECL, line, line_number))
                    if not line.endswith("{"):
                        tokens.append(Token(TokenType.OPEN_BRACE, "{", line_number))
            else:
                tokens.append(Token(TokenType.EXPORT, line, line_number))
            return tokens

        if line.startswith("declare "):
            tokens.append(Token(TokenType.DECLARE, line, line_number))
            if not line.endswith("{"):
                tokens.append(Token(TokenType.OPEN_BRACE, "{", line_number))
            return tokens

        if line.startswith("return "):
            # Special handling for return statements
            content = line.strip()
            if content == "return" or content == "return {":
                tokens.append(Token(TokenType.RETURN, content, line_number))
                if not content.endswith("{"):
                    tokens.append(Token(TokenType.OPEN_BRACE, "{", line_number))
            else:
                tokens.append(Token(TokenType.RETURN, line, line_number))
            return tokens

        # Handle single braces
        if line == "{":
            tokens.append(Token(TokenType.OPEN_BRACE, "{", line_number))
            return tokens

        if line == "}" or line == "};":
            tokens.append(Token(TokenType.CLOSE_BRACE, line, line_number))
            return tokens

        # Handle other content
        tokens.append(Token(TokenType.OTHER, line, line_number))
        return tokens

    def should_add_brace_after(self, line: str) -> bool:
        """Determine if we should add a brace after this line."""
        if "export type" in line and "=" in line:
            return False
        if "=>" in line and not line.endswith("{"):
            return True
        if "interface" in line and not line.endswith("{"):
            return True
        if "declare" in line and not line.endswith("{"):
            return True
        return False

    def format(self, code: str) -> str:
        return code

        # lines = code.split('\n')
        # formatted_lines = []
        # context = FormattingContext()

        # i = 0
        # while i < len(lines):
        #     if i in context.consumed_lines:
        #         i += 1
        #         continue

        #     line = lines[i].strip()
        #     if not line:
        #         i += 1
        #         continue

        #     tokens = self.tokenize_line(line, i)

        #     for token in tokens:
        #         if token.line_number in context.consumed_lines:
        #             continue

        #         indent = " " * (self.indent_size * context.current_indent)

        #         if token.type == TokenType.IMPORT:
        #             formatted_lines.append(f"{indent}{token.content}")

        #         elif token.type == TokenType.TYPE_DECL:
        #             formatted_lines.append(f"{indent}{token.content}")
        #             if self.should_add_brace_after(token.content):
        #                 formatted_lines.append(f"{indent}{{")
        #                 context.current_indent += 1

        #         elif token.type == TokenType.DECLARE:
        #             formatted_lines.append(f"{indent}{token.content} {{")
        #             context.current_indent += 1

        #         elif token.type == TokenType.OPEN_BRACE:
        #             if not formatted_lines[-1].endswith('{'):
        #                 formatted_lines.append(f"{indent}{{")
        #             context.current_indent += 1

        #         elif token.type == TokenType.CLOSE_BRACE:
        #             context.current_indent = max(0, context.current_indent - 1)
        #             indent = " " * (self.indent_size * context.current_indent)
        #             formatted_lines.append(f"{indent}{token.content}")

        #         elif token.type == TokenType.RETURN:
        #             if token.content == 'return' or token.content == 'return {':
        #                 formatted_lines.append(f"{indent}return {{")
        #                 context.current_indent += 1
        #             else:
        #                 formatted_lines.append(f"{indent}{token.content}")

        #         elif token.type == TokenType.EXPORT:
        #             if ' => ' in token.content:
        #                 # Handle arrow function
        #                 formatted_lines.append(f"{indent}{token.content} {{")
        #                 context.current_indent += 1
        #             else:
        #                 formatted_lines.append(f"{indent}{token.content}")
        #                 if self.should_add_brace_after(token.content):
        #                     formatted_lines.append(f"{indent}{{")
        #                     context.current_indent += 1

        #         else:
        #             # Handle arrow functions in other contexts
        #             if ' => ' in token.content and not token.content.endswith('{'):
        #                 formatted_lines.append(f"{indent}{token.content} {{")
        #                 context.current_indent += 1
        #             else:
        #                 formatted_lines.append(f"{indent}{token.content}")

        #         context.consumed_lines.add(token.line_number)

        #     i += 1

        # return '\n'.join(formatted_lines)
