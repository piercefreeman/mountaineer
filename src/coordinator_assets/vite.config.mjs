import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(process.env.MOUNTAINEER_TOOLCHAIN_PACKAGE_JSON);
const { defineConfig } = await import(
  pathToFileURL(require.resolve("vite")).href
);
const react = (
  await import(pathToFileURL(require.resolve("@vitejs/plugin-react")).href)
).default;
const host = process.env.MOUNTAINEER_VITE_HOST;
const publicHost = process.env.MOUNTAINEER_VITE_PUBLIC_HOST;
const port = Number(process.env.MOUNTAINEER_VITE_PORT);
const backendSignal = path.resolve(process.env.MOUNTAINEER_BACKEND_SIGNAL);

export default defineConfig({
  root: process.env.MOUNTAINEER_FRONTEND_ROOT,
  appType: "custom",
  clearScreen: false,
  plugins: [
    react(),
    {
      name: "mountaineer:backend-reload",
      configureServer(server) {
        server.watcher.add(backendSignal);
        server.watcher.on("change", (changedPath) => {
          if (path.resolve(changedPath) === backendSignal) {
            for (const environment of Object.values(server.environments)) {
              environment.moduleGraph.invalidateAll();
            }
            server.ws.send({ type: "full-reload" });
          }
        });
      },
    },
  ],
  server: {
    host,
    port,
    strictPort: true,
    cors: true,
    origin: `http://${publicHost}:${port}`,
    hmr: { host: publicHost, port },
    watch: {
      ignored: [
        "**/.mountaineer-vite/**",
        "**/_metadata/**",
        "**/_server/**",
        "**/_ssr/**",
        "**/_static/**",
      ],
    },
  },
});
