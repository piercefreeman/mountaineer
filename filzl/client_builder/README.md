# client-builder

This is the client builder for filzl. It is responsible for building the client-side javascript/react bundle. In some ways it's a complete project by itself but is bundled with the main filzl python package to allow for easier embedding in the large build pipeline.

## Running standalone

We recommend running with bun, since it bundles typescript execution and aligns with how we run during at buildtime.

```bash
$ bun src/cli.ts --page-path {view_root}/page.tsx --view-root-path {view_root}
```
