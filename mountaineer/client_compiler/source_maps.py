from dataclasses import dataclass
from pathlib import Path
from re import finditer as re_finditer, sub
from time import monotonic_ns

from pydantic import BaseModel

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.logging import LOGGER


@dataclass
class ValueMask:
    mask: int
    right_padding: int


class SourceMapSchema(BaseModel):
    version: int
    sources: list[str]
    names: list[str]
    mappings: str
    sourcesContent: list[str] | None = None
    sourceRoot: str | None = None
    file: str | None = None


class SourceMapParser:
    """
    Parse sourcemaps according to the official specification:
    https://sourcemaps.info/spec.html

    """

    def __init__(self, path: str | Path):
        """
        :param relative_to: If specified, will output source paths relative
        to this path.

        """
        self.path = Path(path)

        self.source_map: SourceMapSchema | None = None

        # { (line, column) : MapMetadata }
        self.parsed_mappings: dict[
            tuple[int, int], mountaineer_rs.MapMetadata
        ] | None = None

    def parse(self):
        """
        Parse the source map file and build up the internal mappings. This is
        deterministic with respect to the initialized source map path, so this
        will be a no-op if it's already been run.

        """
        # If we've already parsed this file, don't do it again
        if self.parsed_mappings is not None:
            return

        start_parse = monotonic_ns()
        self.source_map = SourceMapSchema.model_validate_json(
            Path(self.path).read_text()
        )
        LOGGER.debug(f"Parsed source map in {(monotonic_ns() - start_parse)/1e9:.2f}s")

        start_parse = monotonic_ns()
        self.parsed_mappings = mountaineer_rs.parse_source_map_mappings(
            self.source_map.mappings
        )
        LOGGER.debug(f"Parsed mappings in {(monotonic_ns() - start_parse)/1e9:.2f}s")

    def get_original_location(self, line: int, column: int):
        """
        For a compiled line and column, return the original line and column where they appeared
        in the pre-built file.

        :param line: The line number in the compiled file
        :param column: The column number in the compiled file

        """
        if self.parsed_mappings is None:
            raise ValueError("SourceMapParser has not been parsed yet")

        return self.parsed_mappings.get((line, column))

    def map_exception(self, exception: str) -> str:
        """
        Given a JS stack exception, try to map it to the original files and line numbers

        :param exception: The exception string to map

        :return: The exception string with the original file and line numbers. Note that some
            exception stack traces may not be mappable, and will be left as-is.

        """
        if self.source_map is None or self.parsed_mappings is None:
            raise ValueError("SourceMapParser has not been parsed yet")

        # Build up the replacements all at once, since the matched indexes will be tied
        # to the original string
        text_replacements: dict[tuple[int, int], str] = {}
        for match in re_finditer(r"\(([<>A-Za-z0-9]+?):(\d+?):(\d+?)\)", exception):
            original_match = self.get_original_location(
                int(match.group(2)), int(match.group(3))
            )

            if original_match and original_match.source_index is not None:
                text_replacements[match.span(1)] = self.convert_relative_path(
                    self.source_map.sources[original_match.source_index]
                )
                text_replacements[match.span(2)] = str(original_match.source_line)
                text_replacements[match.span(3)] = str(original_match.source_column)

        # Sort in reverse order based on their start index to ensure that modifying parts of the string
        # doesn't affect the positions of parts that haven't been modified yet
        sorted_replacements = sorted(
            text_replacements.items(), key=lambda x: x[0][0], reverse=True
        )

        for (start, end), replacement in sorted_replacements:
            exception = exception[:start] + replacement + exception[end:]

        return exception

    def convert_relative_path(self, absolute_path: str):
        """
        Absolute paths are convenient for internal use since they fully qualify
        a given file. However, for display they often get long and repetitive across
        multiple lines. This function will convert an absolute path to a relative path
        if it's within the same directory as the current working directory.

        :param absolute_path: The absolute path to convert

        :return: The relative path if it's within the current working directory, otherwise
            the unmodified absolute path.

        """
        source_path = Path(absolute_path)

        if source_path.is_relative_to(Path.cwd()):
            return "./" + str(source_path.relative_to(Path.cwd()))

        return absolute_path


def get_cleaned_js_contents(contents: str):
    """
    Strip all single or multiline comments, since these can be dynamically generated
    metadata and can change without the underlying logic changing.
    """
    return mountaineer_rs.strip_js_comments(contents).strip()


def update_source_map_path(contents: str, new_path: str):
    """
    Updates the source map path to the new path, since the path is dynamic.
    """
    return sub(r"sourceMappingURL=(.*?).map", f"sourceMappingURL={new_path}", contents)
