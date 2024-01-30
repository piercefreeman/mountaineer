#! /bin/bash -e

#
# Production builder
#

# Capture the original working directory and restore on exit
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
