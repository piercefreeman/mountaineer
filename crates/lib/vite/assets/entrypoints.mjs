const ENTRY_PREFIX = "virtual:mountaineer-entry:";
const RESOLVED_ENTRY_PREFIX = `\0${ENTRY_PREFIX}`;

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
      if (source.startsWith(ENTRY_PREFIX)) {
        return `\0${source}`;
      }
    },
    load(id) {
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

export function developmentClientSource(views, styles) {
  return `
import "/@vite/client";
import RefreshRuntime from "/@react-refresh";
RefreshRuntime.injectIntoGlobalHook(window);
window.$RefreshReg$ = () => {};
window.$RefreshSig$ = () => (type) => type;
window.__vite_plugin_react_preamble_installed__ = true;
await Promise.all(${JSON.stringify(styles)}.map((source) => import(source)));
const ReactModule = await import("/@id/react");
const React = ReactModule.default ?? ReactModule;
const ReactDOMModule = await import("/@id/react-dom/client");
const { hydrateRoot } = ReactDOMModule.default ?? ReactDOMModule;
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
