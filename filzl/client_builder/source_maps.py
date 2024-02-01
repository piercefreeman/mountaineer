from re import sub


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
