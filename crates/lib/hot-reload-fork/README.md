# Fork reload tests

The `os_level` Cargo integration target tests the public `Strategy` API using
real Python interpreters, forks, signals, and native pthreads. Its small Python
runtime fixture replaces the web server while retaining the production probe,
parent, payload loading, and worker lifecycle. A C compiler (`cc`) is required.

From the repository root, with the desired Python environment active:

```sh
python -m pip install --only-binary=:all: -r crates/lib/hot-reload-fork/tests/requirements.txt
make test-os-level
```

The interpreter is `python` on `PATH`. This target needs neither the Mountaineer
extension build nor Node, Postgres, or Docker. `cargo test --workspace` also runs
the standard-library cases; OpenCV/NumPy cases are explicitly ignored there
because they require the separate test dependencies. `make test-os-level`
includes them, and missing native dependencies fail the run.

CI runs this target on Linux, macOS ARM, and macOS Intel with Python 3.10–3.14.
The matrix is required by the aggregate `check` job. Native dependencies are
pinned for reproducibility and do not become Mountaineer runtime dependencies.

Coverage includes:

- Safe preloading, independent import probes, transitive imports, completed and
  live Python/executor/native threads, and non-daemon threads at probe shutdown.
- Import exceptions, syntax errors, missing dependencies, early process exits,
  killed probes, cancelled startup, and Python/C/subprocess output isolation.
- Repeated generations, copy-on-write state, overlapping workers, termination,
  signal-handler reset, unexpected worker exits, invalid payloads, and reaping.
- OpenCV import alone, image processing before and after fork, single-thread
  settings, subprocesses, completed Python threads, NumPy BLAS, and macOS system
  proxy lookup. Native cases run multiple generations and validate image output.
- The macOS guard for imports that start threads only when combined.

Thread policy differs by OS: macOS rejects even completed threads because its
native thread-history flag remains set; Linux rejects threads still running.
OpenCV wheel versions and native backends can initialize differently, so native
tests accept either preloading or deferral and require successful worker behavior
in both cases. Synthetic fixtures assert the exact expected probe policy.

These checks cover the fork strategy, not the full HTTP/Vite dev-server startup
or every possible native library's fork safety. The final macOS guard fails
closed when individually safe imports become unsafe together; it does not
automatically restart with a different preload set.
