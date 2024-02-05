from dataclasses import dataclass
from pathlib import Path
from re import finditer as re_finditer
from re import sub

from pydantic import BaseModel


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


class MapMetadata(BaseModel):
    line_number: int
    column_number: int
    source_index: int | None = None
    source_line: int | None = None
    source_column: int | None = None
    # Symbol index is only included if it's present in the source map, which in turn
    # is only there is the symbols got stripped in processing
    symbol_index: int | None = None


class SourceMapParser:
    """
    Parse sourcemaps according to the official specification:
    https://sourcemaps.info/spec.html

    """

    def __init__(self, path: str | Path, relative_to_path: str | Path | None = None):
        """
        :param relative_to: If specified, will output source paths relative
        to this path.

        """
        self.path = Path(path)
        self.relative_to_path = Path(relative_to_path) if relative_to_path else None

        self.vlq_decoder = VLQDecoder()
        self.source_map: SourceMapSchema | None = None

        # { (line, column) : MapMetadata }
        self.parsed_mappings: dict[tuple[int, int], MapMetadata] | None = None

    def parse(self):
        # If we've already parsed this file, don't do it again
        if self.parsed_mappings is not None:
            return

        self.source_map = SourceMapSchema.model_validate_json(
            Path(self.path).read_text()
        )

        self.parsed_mappings = {}

        # This stub object will be used to keep track of all non-None values
        metadata_state: MapMetadata = MapMetadata(line_number=-1, column_number=-1)

        # Empty lines will have semi-colons next to one another
        for line, encoded_metadata in enumerate(self.source_map.mappings.split(";")):
            for component in encoded_metadata.split(","):
                if not component.strip():
                    continue

                # 1-index line numbers to match Javascript exception formatting
                metadata = self.vlq_to_source_metadata(line, component)

                metadata = self.merge_relative_metadatas(
                    current_metadata=metadata,
                    metadata_state=metadata_state,
                )

                self.parsed_mappings[
                    # 1-indexed to align with Javascript exception formatting
                    (metadata.line_number + 1, metadata.column_number + 1)
                ] = metadata

    def get_original_location(self, line: int, column: int):
        if self.parsed_mappings is None:
            raise ValueError("SourceMapParser has not been parsed yet")

        return self.parsed_mappings.get((line, column))

    def map_exception(self, exception: str):
        """
        Given a JS stack exception, try to map it to the original files and line numbers
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

    def convert_relative_path(self, path: str):
        if not self.relative_to_path:
            return path

        source_path = Path(path)

        # Get the absolute relative path, if we can
        if source_path.is_relative_to(self.relative_to_path):
            return str(source_path.relative_to(self.relative_to_path))

        return path

    def merge_relative_metadatas(
        self,
        *,
        current_metadata: MapMetadata,
        metadata_state: MapMetadata,
    ):
        """
        The SourceMapParser spec defines all VLQ values as relative to the previous value. Some are
        line dependent.

        Performs the merge in-place in the current_metadata and metadata_state objects, but returns
        a reference to current_metadata for convenience.

        Note that the `metadata_state` isn't actually the previous instance of metadata, it should
        be the rolling state of all non-None fields.

        """

        def merge_attribute(attribute: str):
            current_value = getattr(current_metadata, attribute)
            state_value = getattr(metadata_state, attribute)

            if current_value is not None and state_value is not None:
                setattr(current_metadata, attribute, current_value + state_value)

        def update_state_attribute(attribute: str):
            current_value = getattr(current_metadata, attribute)
            if current_value is not None:
                setattr(metadata_state, attribute, current_value)

        # Only column number is relative within the current line
        if metadata_state.line_number == current_metadata.line_number:
            current_metadata.column_number += metadata_state.column_number

        # The rest of the fields are always dependent on the previous value
        merge_attribute("source_index")
        merge_attribute("source_line")
        merge_attribute("source_column")
        merge_attribute("symbol_index")

        # Now we can update the metadata with all the non-None values
        # of the current state
        update_state_attribute("line_number")
        update_state_attribute("column_number")
        update_state_attribute("source_index")
        update_state_attribute("source_line")
        update_state_attribute("source_column")
        update_state_attribute("symbol_index")

        return current_metadata

    def vlq_to_source_metadata(self, line: int, component: str):
        vlq_value = self.vlq_decoder.parse_vlq(component)
        if len(vlq_value) not in {1, 4, 5}:
            raise ValueError(
                f"VLQ value should have 1, 4 or 5 components. Got {len(vlq_value)} instead: {vlq_value} for {component}."
            )

        return MapMetadata(
            line_number=line,
            column_number=vlq_value[0],
            source_index=vlq_value[1] if len(vlq_value) > 1 else 0,
            source_line=vlq_value[2] if len(vlq_value) > 1 else 0,
            source_column=vlq_value[3] if len(vlq_value) > 1 else 0,
            symbol_index=vlq_value[4] if len(vlq_value) == 5 else None,
        )


class VLQDecoder:
    """
    Source maps encode the destination->original line information in the VLQ Format. This helper class
    decodes the VLQ format into the original integer list.

    """

    def __init__(self):
        self.alphabet = self.generate_base64_alphabet()

        self.sign_bit_mask = 0b1
        self.continuation_bit_mask = 0b1 << 5

        self.continuation_value_mask = ValueMask(mask=0b011111, right_padding=0)
        self.original_value_mask = ValueMask(mask=0b011110, right_padding=1)

    def parse_vlq(self, vlq_value: str):
        """
        The layout of a single vlq sextet is as follows:
            - [continuation bit for next sequence]
            - [di+4] [di+3] [di+2] [di+1]
            - [sign bit] if sextet starts a new sequence
              [di] if sextet is a continuation

        Where d0 is the least significant bit.

        """
        sextets = [self.alphabet[char] for char in vlq_value]

        final_values: list[int] = []
        current_value = 0
        current_bit_offset = 0
        current_sign_value = 1

        # When we start reading we by definition are creating a new value
        is_continuation = False

        for sextet in sextets:
            value_mask: ValueMask
            if not is_continuation:
                current_sign_value = -1 if (sextet & self.sign_bit_mask) else 1
                value_mask = self.original_value_mask
            else:
                value_mask = self.continuation_value_mask

            # We can find the continuation status for the next bit
            # at the end. Any non-zero value should be a continuation.
            current_value += (
                (sextet & value_mask.mask) >> value_mask.right_padding
            ) << current_bit_offset
            current_bit_offset += 5 if is_continuation else 4
            is_continuation = bool(sextet & self.continuation_bit_mask)

            # We should add to our final list of value
            if not is_continuation:
                final_values.append(current_sign_value * current_value)
                current_value = 0
                current_bit_offset = 0
                current_sign_value = 1

        return final_values

    def generate_base64_alphabet(self):
        """
        Non-standard base64 alphabet for the VLQ format: A-Z a-z 0-9 + /

        """
        alpha_ranges = [("A", "Z"), ("a", "z"), ("0", "9")]

        alphabet = []
        for start, end in alpha_ranges:
            for char in range(ord(start), ord(end) + 1):
                alphabet.append(chr(char))

        alphabet += ["+", "/"]

        return {char: index for index, char in enumerate(alphabet)}


def get_cleaned_js_contents(contents: str):
    """
    Strip all single or multiline comments, since these can be dynamically generated
    metadata and can change without the underlying logic changing.
    """
    # Regular expression to match single line and multiline comments
    # This regex handles single-line comments (// ...), multi-line comments (/* ... */),
    # and avoids capturing URLs like http://...
    # It also considers edge cases where comment-like patterns are inside strings
    pattern = r"(\/\*[\s\S]*?\*\/|([^:]|^)\/\/[^\r\n]*)"

    # Using re.sub to replace the matched comments with an empty string
    return sub(pattern, "", contents).strip()


def update_source_map_path(contents: str, new_path: str):
    """
    Updates the source map path to the new path, since the path is dynamic.
    """
    return sub(r"sourceMappingURL=(.*?).map", f"sourceMappingURL={new_path}", contents)


def make_source_map_paths_absolute(contents: str, original_script_path: Path):
    """
    Takes a source map, along with the original pre-compiled entrypoint path,
    and transforms the relative paths sources into absolute paths. Since often
    our precompiled endpoints are in tmp directories, this is helpful to encode the
    persistent path to the source files.

    """
    payload = SourceMapSchema.model_validate_json(contents)

    new_sources: list[str] = []
    for source in payload.sources:
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = original_script_path.parent / source_path
            new_sources.append(str(source_path.resolve()))

    payload.sources = new_sources
    return payload.model_dump_json()
