import logging
from json import dumps as json_dumps
from pathlib import Path
from re import finditer as re_finditer
from typing import Any, cast

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.cache import extended_lru_cache
from mountaineer.client_compiler.source_maps import SourceMapParser
from mountaineer.logging import debug_log_artifact
from mountaineer.static import get_static_path


class V8RuntimeError(Exception):
    """
    An exception thrown by the V8 runtime in the case of a permanent failure that
    involves the content of the script.

    Enhanced with rich context including:
    - Original raw JavaScript stack trace
    - Source-mapped stack trace (when available)
    - Code context around error locations
    - Formatted error summary
    """

    def __init__(
        self,
        message: str,
        *,
        original_stack: str | None = None,
        source_mapped_stack: str | None = None,
        code_context: dict[str, str] | None = None,
        script_content: str | None = None,
    ):
        self.original_stack = original_stack or message
        self.source_mapped_stack = source_mapped_stack
        self.code_context = code_context or {}
        self.script_content = script_content

        # Create enhanced error message
        enhanced_message = self._format_enhanced_message()
        super().__init__(enhanced_message)

    def _format_enhanced_message(self) -> str:
        """Format a comprehensive error message with all available context."""
        lines = []

        # Start with the main error message
        lines.append("JavaScript Runtime Error:")
        lines.append("=" * 50)

        # Add the primary stack trace (source-mapped if available, otherwise original)
        primary_stack = self.source_mapped_stack or self.original_stack
        lines.append(primary_stack)

        # Add code context if available
        if self.code_context:
            lines.append("\nCode Context:")
            lines.append("-" * 20)
            for location, context in self.code_context.items():
                lines.append(f"\nAt {location}:")
                lines.append(context)

        # Add additional details if we have both original and mapped stacks
        if self.source_mapped_stack and self.source_mapped_stack != self.original_stack:
            lines.append("\nOriginal Stack Trace:")
            lines.append("-" * 25)
            lines.append(self.original_stack)

        return "\n".join(lines)

    def __str__(self) -> str:
        """Return the enhanced error message."""
        return super().__str__()


def extract_code_context(script: str, line_number: int, context_lines: int = 3) -> str:
    """
    Extract lines of code around a specific line number for context.

    :param script: The full script content
    :param line_number: The line number where the error occurred (1-indexed)
    :param context_lines: Number of lines to show before and after the error line
    :return: Formatted code context string
    """
    script_lines = script.split("\n")
    total_lines = len(script_lines)

    # Validate line number bounds
    if line_number < 1 or line_number > total_lines:
        raise ValueError(
            f"Line number {line_number} is out of bounds (script has {total_lines} lines)"
        )

    # Convert to 0-indexed and ensure bounds
    error_line_idx = line_number - 1
    start_idx = max(0, error_line_idx - context_lines)
    end_idx = min(total_lines, error_line_idx + context_lines + 1)

    context_lines_list = []
    for i in range(start_idx, end_idx):
        line_num = i + 1
        line_content = script_lines[i]

        # Truncate very long lines to keep output manageable
        if len(line_content) > 120:
            line_content = line_content[:117] + "..."

        # Mark the error line with an arrow
        marker = " -> " if i == error_line_idx else "    "
        context_lines_list.append(f"{marker}{line_num:4d}: {line_content}")

    # Add a header showing the location if we're deep in a large file
    if line_number > 50:
        header = (
            f"Context around line {line_number} (script has {total_lines} total lines):"
        )
        return header + "\n" + "\n".join(context_lines_list)

    return "\n".join(context_lines_list)


def extract_error_locations_from_stack(stack_trace: str) -> list[tuple[str, int, int]]:
    """
    Extract file, line, and column information from a JavaScript stack trace.

    :param stack_trace: The JavaScript stack trace string
    :return: List of tuples containing (file, line, column)
    """
    locations = []

    # Single comprehensive regex that handles both formats:
    # - "at Object.x (<anonymous>:19:19)" (with function names)
    # - "at <anonymous>:10944:8" (without function names)
    pattern = r"at (?:.+? \()?([^:)]+):(\d+):(\d+)\)?"

    for match in re_finditer(pattern, stack_trace):
        file_name = match.group(1)
        line_number = int(match.group(2))
        column_number = int(match.group(3))
        locations.append((file_name, line_number, column_number))

    return locations


def fix_exception_lines(*, exception: str, injected_script: str):
    """
    Since we create a synthetic script to run in the V8 runtime, the line numbers
    of the in-application stack trace will be offset by however long our
    injected script is. This function re-processed the stack trace to fix the
    line number.

    """
    offset_lines = injected_script.count("\n")
    logging.debug(f"Fixing exception lines with offset: {offset_lines}")

    text_replacements: dict[tuple[int, int], str] = {}

    # Handle both stack trace formats with a comprehensive regex
    # Matches: "(<anonymous>:12345:67)" or "at <anonymous>:12345:67"
    for match in re_finditer(r"(at (?:.+? \()?|\()([^:)]+):(\d+):(\d+)\)?", exception):
        line_number = int(match.group(3))
        corrected_line = line_number - offset_lines

        # Only replace the line numbers, and only if they're positive after correction
        if corrected_line > 0:
            text_replacements[match.span(3)] = str(corrected_line)
            logging.debug(f"Correcting line {line_number} -> {corrected_line}")
        else:
            logging.warning(
                f"Line number {line_number} would become {corrected_line} after correction, skipping"
            )

    sorted_replacements = sorted(
        text_replacements.items(), key=lambda x: x[0][0], reverse=True
    )

    for (start, end), replacement in sorted_replacements:
        exception = exception[:start] + replacement + exception[end:]

    logging.debug(f"Fixed exception: {exception}")
    return exception


def find_tsconfig(paths: list[list[str]]) -> str | None:
    """
    Find the tsconfig.json file in the parent directories of the provided paths.
    We look for tsconfig.json in the parent directories of each path in the list.
    If multiple tsconfig.json files are found, we use the one closest to the root.

    :param paths: List of lists of file paths to search from
    :return: Path to tsconfig.json if found, None otherwise
    """
    tsconfig_paths = set()

    # For each group of paths
    for path_group in paths:
        # For each path in the group
        for path in path_group:
            current = Path(path).parent
            # Walk up the directory tree
            while current != current.parent:
                tsconfig = current / "tsconfig.json"
                if tsconfig.exists():
                    tsconfig_paths.add(str(tsconfig))
                current = current.parent

    if not tsconfig_paths:
        logging.warning(
            f"No tsconfig.json found in any parent directory of the provided paths: {paths}"
        )
        return None

    # Return the tsconfig.json closest to the original file
    return min(tsconfig_paths, key=len)


@extended_lru_cache(maxsize=128, max_size_mb=5)
def render_ssr(
    script: str,
    render_data: dict[str, Any],
    hard_timeout: int | float | None = None,
    sourcemap: str | None = None,
) -> str:
    """
    Render the React component in the provided SSR javascript bundle. This file will
    be directly executed within the V8 runtime.

    To speed up requests for the same exact content (ie. same react and same data)
    we cache the result of the render_ssr_rust call by default for a limited amount of
    previous calls. We limit the overall size of this cache to 5MB.

    :param script: The raw code of the javascript bundle to execute. Should be pre-compiled into an
        SSR compatible package with a single entrypoint.
    :param render_data: The data to inject into the SSR javascript bundle
    :param hard_timeout: The maximum time to allow the render to take in seconds. If the render takes
        longer than this time, our thread supervisor will kick in and terminate the rust worker.

    :raises TimeoutError: If the render takes longer than the hard_timeout
    :raises V8RuntimeError: If the V8 runtime throws an exception during the render

    """
    polyfill_script = get_static_path("ssr_polyfills.js").read_text()
    data_json = json_dumps(render_data)

    injected_script = f"var SERVER_DATA = {data_json};\n{polyfill_script}\n"
    full_script = f"{injected_script}{script}"

    debug_log_artifact("ssr_script", "js", full_script)

    try:
        # Convert to milliseconds for the rust worker
        render_result = mountaineer_rs.render_ssr(
            full_script, int(hard_timeout * 1000) if hard_timeout else 0
        )
    except ConnectionAbortedError:
        raise TimeoutError("SSR render was interrupted after hard timeout")
    except ValueError as e:
        original_stack = str(e)
        js_stack = fix_exception_lines(
            exception=original_stack, injected_script=injected_script
        )

        # Prepare enhanced error context
        source_mapped_stack = None
        code_context = {}

        # Apply source map if available
        if sourcemap:
            try:
                sourcemap_parser = SourceMapParser(script=sourcemap)
                sourcemap_parser.parse()
                source_mapped_stack = sourcemap_parser.map_exception(js_stack)
            except Exception as sourcemap_error:
                # Log but don't fail on sourcemap errors
                logging.warning(f"Failed to apply sourcemap: {sourcemap_error}")

        # Extract code context from error locations
        context_extraction_attempts = []
        try:
            # Extract context using original line numbers (before fix_exception_lines)
            original_error_locations = extract_error_locations_from_stack(
                original_stack
            )
            corrected_error_locations = extract_error_locations_from_stack(js_stack)

            context_extraction_attempts.append(
                f"Found {len(original_error_locations)} error location(s) in stack trace"
            )

            # Log debug information to help diagnose issues
            if not original_error_locations:
                logging.warning(
                    f"No error locations found in original stack: {original_stack}"
                )
                context_extraction_attempts.append(
                    "Failed to parse error locations from stack trace"
                )
            if not corrected_error_locations:
                logging.warning(
                    f"No error locations found in corrected stack: {js_stack}"
                )
                context_extraction_attempts.append(
                    "Failed to parse error locations from corrected stack trace"
                )

            for (orig_file, orig_line, orig_col), (
                corr_file,
                corr_line,
                corr_col,
            ) in zip(original_error_locations, corrected_error_locations):
                # Only extract context for anonymous locations (compiled code)
                if orig_file == "<anonymous>":
                    # Use corrected line numbers for the location key (display purposes)
                    location_key = f"<anonymous>:{corr_line}:{corr_col}"
                    # But extract context using original line numbers from full script
                    try:
                        context = extract_code_context(full_script, orig_line)
                        code_context[location_key] = context
                        logging.debug(
                            f"Successfully extracted context for {location_key}"
                        )
                        context_extraction_attempts.append(
                            f"Successfully extracted context for {location_key}"
                        )
                    except Exception as ctx_err:
                        logging.warning(
                            f"Failed to extract context for line {orig_line}: {ctx_err}"
                        )
                        context_extraction_attempts.append(
                            f"Failed to extract context for line {orig_line}: {str(ctx_err)}"
                        )

                    # Limit context to prevent overwhelming output
                    if len(code_context) >= 3:
                        break
                else:
                    context_extraction_attempts.append(
                        f"Skipped context extraction for {orig_file} (not anonymous)"
                    )

            if not code_context:
                logging.warning(
                    "No code context could be extracted from error locations"
                )
                context_extraction_attempts.append(
                    "No code context could be extracted from any error location"
                )

        except Exception as context_error:
            # Log but don't fail on context extraction errors
            logging.warning(
                f"Failed to extract code context: {context_error}", exc_info=True
            )
            context_extraction_attempts.append(
                f"Context extraction failed with exception: {str(context_error)}"
            )

        # Add fallback information if no context was extracted
        if not code_context and context_extraction_attempts:
            fallback_info = {
                "Context Extraction Attempted": "\n".join(
                    [
                        "Enhanced error context extraction was attempted but failed.",
                        "Extraction attempts:",
                    ]
                    + [f"  • {attempt}" for attempt in context_extraction_attempts]
                    + [
                        "",
                        "This may happen with very large scripts, unusual stack trace formats,",
                        "or when error locations point outside the script boundaries.",
                        "The basic stack trace above should still help identify the issue.",
                    ]
                )
            }
            code_context.update(fallback_info)

        raise V8RuntimeError(
            js_stack,
            original_stack=original_stack,
            source_mapped_stack=source_mapped_stack,
            code_context=code_context,
            script_content=full_script if len(code_context) > 0 else None,
        )

    return cast(str, render_result)
