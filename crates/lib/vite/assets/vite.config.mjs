import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(mountaineer.toolchain_package_json);
const { defineConfig } = await import(
  pathToFileURL(require.resolve("vite")).href
);
const react = (
  await import(pathToFileURL(require.resolve("@vitejs/plugin-react")).href)
).default;
const development =
  mountaineer.mode === "development" ? mountaineer : undefined;
const styleBuild =
  mountaineer.mode === "build_styles" ? mountaineer : undefined;
const backendSignal = development
  ? path.resolve(development.backend_signal)
  : undefined;
const styleEntries = Object.fromEntries(
  (styleBuild?.styles ?? []).map(({ name, path }) => [name, path]),
);

export default defineConfig({
  root: mountaineer.frontend_root,
  appType: "custom",
  clearScreen: false,
  plugins: [
    react(),
    ...(development
      ? [
          {
            name: "mountaineer:backend-reload",
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
                  response.end(`
import "/@vite/client";
import RefreshRuntime from "/@react-refresh";
RefreshRuntime.injectIntoGlobalHook(window);
window.$RefreshReg$ = () => {};
window.$RefreshSig$ = () => (type) => type;
window.__vite_plugin_react_preamble_installed__ = true;
await Promise.all(${JSON.stringify(styles)}.map((path) => import(path)));
const ReactModule = await import("/@id/react");
const React = ReactModule.default ?? ReactModule;
const ReactDOMModule = await import("/@id/react-dom/client");
const { hydrateRoot } = ReactDOMModule.default ?? ReactDOMModule;
const components = await Promise.all(
  ${JSON.stringify(views)}.map((path) => import(path)),
);
let element = null;
for (const module of components.reverse()) {
  element = React.createElement(module.default, null, element);
}
const root = document.getElementById("root");
if (!root) throw new Error("Mountaineer root element is missing");
hydrateRoot(root, element);
`);
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
  build: styleBuild
    ? {
        outDir: styleBuild.output_dir,
        emptyOutDir: false,
        copyPublicDir: false,
        cssCodeSplit: true,
        minify: styleBuild.minify,
        rollupOptions: {
          input: styleEntries,
          output: {
            assetFileNames: "[name][extname]",
          },
        },
      }
    : undefined,
});
