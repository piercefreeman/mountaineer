const ENTRY_PREFIX = "virtual:mountaineer-entry:";
const RESOLVED_ENTRY_PREFIX = `\0${ENTRY_PREFIX}`;
// Dev hydration cannot `import("@id/react")` directly: react is aliased to an
// absolute file, so bare-id URL requests bypass the dep optimizer and answer
// 504 Outdated Optimize Dep. Routing the imports through a virtual module lets
// import-analysis rewrite them to the optimized deps with the current hash.
const DEV_RUNTIME_ID = "virtual:mountaineer-dev-runtime";
const RESOLVED_DEV_RUNTIME_ID = `\0${DEV_RUNTIME_ID}`;

export function entrypointInputs(entrypoints) {
  return Object.fromEntries(
    entrypoints.map((entrypoint, index) => [
      entrypoint.name,
      `${ENTRY_PREFIX}${index}`,
    ]),
  );
}

export function mountaineerEntrypoints(entrypoints, target) {
  return {
    name: "mountaineer:entrypoints",
    enforce: "pre",
    resolveId(source) {
      if (source.startsWith(ENTRY_PREFIX) || source === DEV_RUNTIME_ID) {
        return `\0${source}`;
      }
    },
    load(id) {
      if (id === RESOLVED_DEV_RUNTIME_ID) {
        return devRuntimeSource();
      }
      if (!id.startsWith(RESOLVED_ENTRY_PREFIX)) {
        return;
      }
      const index = Number(id.slice(RESOLVED_ENTRY_PREFIX.length));
      const entrypoint = entrypoints[index];
      if (!entrypoint) {
        throw new Error(`Unknown Mountaineer entrypoint ${id}`);
      }
      return target === "ssr"
        ? ssrSource(entrypoint.views)
        : clientSource(entrypoint.views);
    },
  };
}

export function developmentClientSource(views, styles, base) {
  return `
import "${base}@vite/client";
import RefreshRuntime from "${base}@react-refresh";
RefreshRuntime.injectIntoGlobalHook(window);
window.$RefreshReg$ = () => {};
window.$RefreshSig$ = () => (type) => type;
window.__vite_plugin_react_preamble_installed__ = true;
await Promise.all(${JSON.stringify(styles)}.map((source) => import(source)));
const { React, hydrateRoot } = await import("${base}@id/${DEV_RUNTIME_ID}");
const components = await Promise.all(
  ${JSON.stringify(views)}.map((source) => import(source)),
);
let element = null;
for (const module of components.reverse()) {
  element = React.createElement(module.default, null, element);
}
const root = document.getElementById("root");
if (!root) throw new Error("Mountaineer root element is missing");
hydrateRoot(root, element);
`;
}

function devRuntimeSource() {
  return `
import * as ReactModule from "react";
import * as ReactDOMClient from "react-dom/client";
export const React = ReactModule.default ?? ReactModule;
export const hydrateRoot =
  ReactDOMClient.hydrateRoot ??
  (ReactDOMClient.default ?? ReactDOMClient).hydrateRoot;
`;
}

function clientSource(views) {
  const imports = views
    .map(
      (view, index) =>
        `import Component${index} from ${JSON.stringify(view)};`,
    )
    .join("\n");
  const components = views.map((_, index) => `Component${index}`).join(", ");
  return `
import React from "react";
import { hydrateRoot } from "react-dom/client";
${imports}
const components = [${components}];
let element = null;
for (const Component of components.reverse()) {
  element = React.createElement(Component, null, element);
}
const root = document.getElementById("root");
if (!root) throw new Error("Mountaineer root element is missing");
hydrateRoot(root, element);
`;
}

function ssrSource(views) {
  const imports = views
    .map(
      (view, index) =>
        `import Component${index} from ${JSON.stringify(view)};`,
    )
    .join("\n");
  const components = views.map((_, index) => `Component${index}`).join(", ");
  return `
import React from "react";
import { renderToString } from "react-dom/server.edge";
${imports}
const components = [${components}];
const Entrypoint = () => {
  let element = null;
  for (const Component of [...components].reverse()) {
    element = React.createElement(Component, null, element);
  }
  return element;
};
export const Index = () => renderToString(React.createElement(Entrypoint));
`;
}
