# Core Library

Miscellaneous notes on development and testing the core library.

## Installation

When doing local development work, use poetry to manage dependencies and maturin to create a build of the combined python/rust project:

```bash
make install-deps
```

This effectively expands to:

```bash
poetry install
poetry run maturin develop --release
```

You can also run maturin just with `poetry run maturin develop`, which will be much faster to compile, but rust execution will be notably slower.

You'll also need a system-wide installation of esbuild. If you don't have one when you run the build pipline it will install one for you within `~/.cache/mountaineer/esbuild`.

## External Application

If you want to test your mountaineer changes against a real webapp, you can build a wheel and then add it
to your project's virtual environment:

```bash
$ poetry run maturin build --release

   Finished `release` profile [optimized] target(s) in 51.28s
📦 Built wheel for CPython 3.12 to /Users/piercefreeman/projects/mountaineer/target/wheels/mountaineer-0.1.0-cp312-cp312-macosx_11_0_arm64.whl
```

Then, in your other project. If you've already installed a previous local mountaineer wheel, you'll have to run with `--force-reinstall` to prompt pip
to actually swap out the wheels versus ignoring the same version number.

```bash
poetry run pip install [--force-reinstall] /Users/piercefreeman/projects/mountaineer/target/wheels/mountaineer-0.1.0-cp312-cp312-macosx_11_0_arm64.whl
```

## Logging

It's sometimes helpful to run Mountaineer with verbose logging, whether you're developing new functionality
or trying to diagnose a problem. You can set the `MOUNTAINEER_LOG_LEVEL` environment variable to `DEBUG` to
enable verbose logging:

```bash
$ MOUNTAINEER_LOG_LEVEL=DEBUG poetry run runserver
```

## Development Utilities

1. Python Testing

    ```bash
    $ make test
    ```

    During testing we also support providing additional test-args that are passed to pytest. This helps you narrow down the scope of tests, add more verbosity, etc.:

    ```bash
    $ make test test-args="-k test_extracts_iterable"
    ```

1. Python Linting

    ```bash
    $ make lint
    ```

1. Rust Benchmarking

    ```bash
    $ cargo bench
    ```

1. Diagnose errors in CI

    At the moment, our main CI testing flows run on Linux/x86-64 architectures. We've observed some behavior there that isn't reproducable locally. To test locally on OS X you'll need build a representative docker image and then test within it:

    ```bash
    $ docker build -t mountaineer .
    $ docker run -it mountaineer
    $ make install-deps
    $ make test-integrations
