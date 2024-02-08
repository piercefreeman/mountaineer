# Core Library

Miscellaneous notes on development and testing the core library.

## Development

1. Python Testing

    ```bash
    $ make test
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
    $ docker build -t filzl .
    $ docker run -it filzl
    $ make install-deps
    $ make test-integrations
    ```
