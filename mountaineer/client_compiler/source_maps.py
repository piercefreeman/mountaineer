from dataclasses import dataclass
from os.path import commonpath
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

    def __init__(
        self,
        path: str | Path | None = None,
        script: str | None = None,
    ):
        self.path = Path(path) if path else None
        self.script = script

        self.source_map: SourceMapSchema | None = None
        self._common_prefix_cache: dict[frozenset[str], str | None] = {}

        # { (line, column) : MapMetadata }
        self.parsed_mappings: dict[
            tuple[int, int], mountaineer_rs.MapMetadata
        ] | None = None

    def find_common_prefix(self, paths: list[str]) -> str | None:
        """
        Find the common prefix among all non-anonymous paths.
        Caches results based on the set of input paths.
        """
        # Convert paths to a frozenset for cache key
        paths_set = frozenset(paths)

        # Check cache first
        if paths_set in self._common_prefix_cache:
            return self._common_prefix_cache[paths_set]

        # Filter out anonymous paths and empty paths
        valid_paths = [
            p for p in paths if p and not p.startswith("<") and not p.endswith(">")
        ]

        if not valid_paths:
            result = None
        else:
            try:
                common = commonpath(valid_paths)
                result = common if common != "/" else None
            except ValueError:
                result = None

        # Cache the result
        self._common_prefix_cache[paths_set] = result
        return result

    def parse(self):
        """
        Parse the source map file and build up the internal mappings.
        Common prefix calculation is deferred until needed.
        """
        # If we've already parsed this file, don't do it again
        if self.parsed_mappings is not None:
            return

        text = Path(self.path).read_text() if self.path else self.script
        if not text:
            raise ValueError("No source map found")

        start_parse = monotonic_ns()
        self.source_map = SourceMapSchema.model_validate_json(text)
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
        relevant_sources = set()

        # First pass: collect all relevant source indices
        for match in re_finditer(
            r"\(([<>A-Za-z0-9/_.()]+?):(\d+?):(\d+?)\)", exception
        ):
            original_match = self.get_original_location(
                int(match.group(2)), int(match.group(3))
            )
            if original_match and original_match.source_index is not None:
                source = self.source_map.sources[original_match.source_index]
                relevant_sources.add(source)

        # Only calculate common prefix for sources that are actually used
        common_prefix = self.find_common_prefix(list(relevant_sources))

        # Second pass: build replacements
        for match in re_finditer(
            r"\(([<>A-Za-z0-9/_.()]+?):(\d+?):(\d+?)\)", exception
        ):
            original_match = self.get_original_location(
                int(match.group(2)), int(match.group(3))
            )

            if original_match and original_match.source_index is not None:
                source = self.source_map.sources[original_match.source_index]
                text_replacements[match.span(1)] = self._convert_relative_path(
                    source, common_prefix
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

    def _convert_relative_path(self, path: str, common_prefix: str | None) -> str:
        """
        Convert a path by stripping common prefix and cleaning up.
        - Keeps anonymous paths (<anonymous>) unchanged
        - Strips common prefix from regular paths
        - Removes leading "../" sequences
        """
        # Don't modify anonymous paths
        if path.startswith("<") and path.endswith(">"):
            return path

        # Strip the common prefix if it exists
        if common_prefix and path.startswith(common_prefix):
            path = path[len(common_prefix) :].lstrip("/")

        return path


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
