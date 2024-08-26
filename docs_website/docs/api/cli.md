# CLI Plugins

CLI Plugins provide default handling for the most common lifecycle events during Mountaineer development. Import these if convenient, otherwise you can follow our implementation approaches to implement your own.

## Webapp CLI

::: mountaineer.cli.handle_runserver

::: mountaineer.cli.handle_watch

::: mountaineer.cli.handle_build

Building your app will compile your TypeScript into the client-side bundle that will be downloaded
by the browser. It also ahead-of-time generates the server code that will be run as part of [SSR](./ssr.md).
You'll want to do it before deploying your application into production - but since a full build can take up
to 10s, `handle_runserver` provides a better workflow for daily development.

## Database CLI

::: mountaineer.database.cli.handle_createdb
