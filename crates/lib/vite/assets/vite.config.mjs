import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

import {
  developmentClientSource,
  entrypointInputs,
  mountaineerEntrypoints,
} from "./mountaineer-entrypoints.mjs";
import { mountaineerUseClient } from "./mountaineer-use-client.mjs";

const require = createRequire(mountaineer.toolchain_package_json);
const { defineConfig } = await import(
  pathToFileURL(require.resolve("vite")).href
);
const react = (
  await import(pathToFileURL(require.resolve("@vitejs/plugin-react")).href)
).default;

const development =
  mountaineer.mode === "development" ? mountaineer : undefined;
const clientBuild =
  mountaineer.mode === "build_client" ? mountaineer : undefined;
const ssrBuild = mountaineer.mode === "build_ssr" ? mountaineer : undefined;
const styleBuild =
  mountaineer.mode === "build_styles" ? mountaineer : undefined;
const backendSignal = development
  ? path.resolve(development.backend_signal)
  : undefined;
const entrypoints = clientBuild
  ? clientBuild.entrypoints
  : ssrBuild
    ? [ssrBuild.entrypoint]
    : [];
const styleEntries = Object.fromEntries(
  (styleBuild?.styles ?? []).map(({ name, path }) => [name, path]),
);

export default defineConfig({
  root: mountaineer.frontend_root,
  appType: "custom",
  base: "./",
  clearScreen: false,
  resolve: {
    tsconfigPaths: true,
  },
  define: ssrBuild
    ? {
        "process.env.NODE_ENV": JSON.stringify(ssrBuild.environment),
        "process.env.SSR_RENDERING": "true",
        "process.env.LIVE_RELOAD_PORT": "0",
        global: "globalThis",
      }
    : clientBuild
      ? {
          "process.env.NODE_ENV": JSON.stringify("production"),
          "process.env.SSR_RENDERING": "false",
          "process.env.LIVE_RELOAD_PORT": "0",
        }
      : undefined,
  plugins: [
    mountaineerEntrypoints(entrypoints, ssrBuild ? "ssr" : "client"),
    mountaineerUseClient(ssrBuild ? "ssr" : "client"),
    react(),
    ...(development
      ? [
          {
            name: "mountaineer:development",
            configureServer(server) {
              server.middlewares.use(
                "/@mountaineer/client",
                (request, response) => {
                  const params = new URL(
                    request.url ?? "",
                    "http://mountaineer",
                  ).searchParams;
                  const views = params
                    .getAll("view")
                    .map((view) => `/@fs/${view.replaceAll("\\", "/")}`);
                  const styles = params
                    .getAll("style")
                    .map((style) => `/@fs/${style.replaceAll("\\", "/")}`);
                  if (views.length === 0) {
                    response.statusCode = 400;
                    response.end("Missing Mountaineer view");
                    return;
                  }

                  response.setHeader("Content-Type", "text/javascript");
                  response.end(developmentClientSource(views, styles));
                },
              );

              server.watcher.add(backendSignal);
              server.watcher.on("change", (changedPath) => {
                if (path.resolve(changedPath) === backendSignal) {
                  for (const environment of Object.values(
                    server.environments,
                  )) {
                    environment.moduleGraph.invalidateAll();
                  }
                  server.ws.send({ type: "full-reload" });
                }
              });
            },
          },
        ]
      : []),
  ],
  server: development
    ? {
        host: development.host,
        port: development.port,
        strictPort: true,
        cors: true,
        origin: `http://${development.public_host}:${development.port}`,
        hmr: {
          host: development.public_host,
          port: development.port,
        },
        watch: {
          ignored: ["**/.mountaineer/**", "**/.mountaineer-vite/**"],
        },
      }
    : undefined,
  ssr: ssrBuild
    ? {
        target: "webworker",
        noExternal: true,
      }
    : undefined,
  build: clientBuild
    ? {
        outDir: clientBuild.output_dir,
        emptyOutDir: true,
        copyPublicDir: false,
        cssCodeSplit: true,
        minify: clientBuild.minify,
        sourcemap: "hidden",
        rolldownOptions: {
          input: entrypointInputs(clientBuild.entrypoints),
          output: {
            entryFileNames: "[name].js",
            chunkFileNames: "[name]-[hash].js",
            assetFileNames: "[name]-[hash][extname]",
          },
        },
      }
    : ssrBuild
      ? {
          ssr: true,
          outDir: ssrBuild.output_dir,
          emptyOutDir: ssrBuild.empty_output,
          copyPublicDir: false,
          minify: ssrBuild.minify,
          sourcemap: "hidden",
          rolldownOptions: {
            input: entrypointInputs([ssrBuild.entrypoint]),
            output: {
              format: "iife",
              name: "SSR",
              inlineDynamicImports: true,
              entryFileNames: "[name].js",
            },
          },
        }
      : styleBuild
        ? {
            outDir: styleBuild.output_dir,
            emptyOutDir: false,
            copyPublicDir: false,
            cssCodeSplit: true,
            minify: styleBuild.minify,
            rolldownOptions: {
              input: styleEntries,
              output: {
                assetFileNames: "[name][extname]",
              },
            },
          }
        : undefined,
});
