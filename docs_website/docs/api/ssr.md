# SSR

Most SSR logic is handled in our embedded Rust layer. In Rust we spin up a V8 isolate, handle logging, catch and process exceptions, etc. This page only covers the client functions that are exposed to Python.

## SSR

::: mountaineer.ssr.render_ssr

::: mountaineer.ssr.V8RuntimeError

## Source Maps

::: mountaineer.client_compiler.source_maps.SourceMapParser
