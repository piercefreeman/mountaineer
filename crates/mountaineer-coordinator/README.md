# Mountaineer coordinator

The wheel installs two native entrypoints. Run them from anywhere inside a
Mountaineer project; the active uv environment and project layout are inferred:

```bash
uv run mountaineer-dev
uv run mountaineer-prod
```

`mountaineer-dev` owns file watching, readiness checks, a stable TCP proxy, and
last-good-worker swaps. Unix uses a pre-imported Python template plus `fork()`.
Each candidate warm import is first tried in a disposable fork and automatically
excluded if it leaves more than one OS thread running.
Windows keeps two pre-imported Python processes idle by default and replenishes
the pool whenever one becomes an app worker.

The coordinator also launches the project's Vite 8 server. Vite's React plugin
provides state-preserving Fast Refresh and CSS HMR while Rust refreshes the
Python SSR worker behind the stable proxy.

`mountaineer-prod` validates `_static` and `_ssr`, hashes the static artifacts,
writes the versioned runtime payload, then launches `python -m
mountaineer.runtime`.

The development coordinator installs its private Vite toolchain into the user
cache on first launch. Project dependencies remain unchanged.
