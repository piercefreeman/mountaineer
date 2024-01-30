#! /bin/bash -e

#
# Development build script for the filzl rust plugins. This will automatically
# build the plugin and install into the parent poetry environment.
#

# We might switch directories during script execution, so install a hook
# to restore the original directory on exit.
ORIGINAL_PWD="$(pwd)"
cleanup() {
    cd "$ORIGINAL_PWD"
}
trap cleanup EXIT

# Get the directory of the current script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Run maturin build using poetry
cd "$DIR"
poetry run maturin build --release --bindings pyo3

# Locate the built wheel file in the target/wheels directory.
# This assumes that there's only one wheel file present.
WHEEL_FILE=$(find "$DIR/target/wheels/" -name "*.whl")

# Get the absolute path to the wheel file
ABSOLUTE_WHEEL_FILE=$(readlink -f "$WHEEL_FILE")

# CD into ~/other_project and install the new wheel package using pip
(cd "$DIR/.." && poetry run pip install "$ABSOLUTE_WHEEL_FILE" --force-reinstall)
(cd "$DIR/../my_website" && poetry run pip install "$ABSOLUTE_WHEEL_FILE" --force-reinstall)
