from os import PathLike
from pydantic import BaseModel, Field, ValidationError, field_validator
from filzl.client_builder import get_client_builder_path
from subprocess import Popen
from pathlib import Path
from subprocess import PIPE
from typing import Annotated
from re import sub
from hashlib import md5

def assert_output_true(v: bool) -> bool:
    assert v is True
    return v

class BundleOutput(BaseModel):
    """
    Our expected output from the bundler

    """
    output: Annotated[bool, assert_output_true] = Field(alias="_output")
    compiled_contents: str = Field(alias="compiledContents")
    source_map_contents: str = Field(alias="sourceMapContents")


def bundle_javascript(page_path: str | Path, view_path: str | Path):
    # Make these strings absolute, since we're working in a different pwd
    # in the command
    page_path_absolute = Path(page_path).resolve().absolute()
    view_path_absolute = Path(view_path).resolve().absolute()

    # Run the bun command and get the full output
    process = Popen(
        ["bun", "src/cli.ts", "--page-path", str(page_path_absolute), "--view-root-path", str(view_path_absolute)],
        cwd=get_client_builder_path(""),
        stdout=PIPE, stderr=PIPE, text=True
    )
    stdout, stderr = process.communicate()

    if process.returncode != 0:
        raise Exception(f"Bundler failed: {stderr}")

    # Check every line and make sure it has our expected output signature
    for line in stdout.splitlines():
        try:
            output = BundleOutput.parse_raw(line)
        except ValidationError as e:
            # This line is probably another kind of logging
            continue

        return output.compiled_contents, output.source_map_contents

    raise Exception("Bundler failed: no output found in stdout")

def get_cleaned_js_contents(contents: str):
    """
    Strip all single or multiline comments, since these can be dynamically generated
    metadata and can change without the underlying logic changing.
    """
    # Regular expression to match single line and multiline comments
    # This regex handles single-line comments (// ...), multi-line comments (/* ... */),
    # and avoids capturing URLs like http://...
    # It also considers edge cases where comment-like patterns are inside strings
    pattern = r'(\/\*[\s\S]*?\*\/|([^:]|^)\/\/[^\r\n]*)'

    # Using re.sub to replace the matched comments with an empty string
    return sub(pattern, '', contents).strip()

def update_source_map_path(contents: str, new_path: str):
    """
    Updates the source map path to the new path, since the path is dynamic.
    """
    return sub(r'sourceMappingURL=(.*?).map', f'sourceMappingURL={new_path}', contents)
