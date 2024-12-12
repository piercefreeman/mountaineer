class CodeBlock:
    """
    Semantic grouping of a particular section of code, typically separated
    from other ones with two blank lines.

    """

    def __init__(self, lines: list[str]):
        self.lines = lines

    @staticmethod
    def indent(line: str):
        """
        Use the first line of the code block to determine the indentation level
        for the other lines that are implicitly imbedded in this line. This most
        acutely covers cases where string templating includes newlines so we can
        preserve the overall layout.

        ie. CodeBlock.indent(f"  my_var = {my_var}\n")

        """
        pass
