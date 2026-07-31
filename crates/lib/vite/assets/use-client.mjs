import { readFile } from "node:fs/promises";
import path from "node:path";

const WRAPPER_PREFIX = "\0mountaineer-client-wrapper:";
const ACTUAL_PREFIX = "\0mountaineer-client-actual:";
const EXPORT_DEFAULT = /^\s*export\s+default\b/m;
const EXPORT_ALL = /^\s*export\s+\*\s+from\b/m;
const NAMED_EXPORTS = [
  /^\s*export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\b/gm,
  /^\s*export\s+class\s+([A-Za-z_$][\w$]*)\b/gm,
  /^\s*export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)\b/gm,
  /^\s*export\s+\*\s+as\s+([A-Za-z_$][\w$]*)\s+from\b/gm,
];
const EXPORT_BLOCK =
  /^\s*export\s*\{([^}]*)\}\s*(?:from\s*["'][^"']+["'])?\s*;?/gm;

export function mountaineerUseClient(target) {
  const boundaryCache = new Map();
  const exportCache = new Map();

  return {
    name: "mountaineer:use-client",
    enforce: "pre",
    async resolveId(source, importer) {
      if (source.startsWith(WRAPPER_PREFIX) || source.startsWith(ACTUAL_PREFIX)) {
        return source;
      }

      const actualImporter = importer?.startsWith(ACTUAL_PREFIX)
        ? importer.slice(ACTUAL_PREFIX.length)
        : importer;
      const resolved = await this.resolve(source, actualImporter, {
        skipSelf: true,
      });
      if (!resolved || resolved.external) {
        return;
      }

      if (await isClientBoundary(resolved.id, boundaryCache)) {
        return importer?.startsWith(ACTUAL_PREFIX)
          ? `${ACTUAL_PREFIX}${cleanId(resolved.id)}`
          : `${WRAPPER_PREFIX}${cleanId(resolved.id)}`;
      }
      return importer?.startsWith(ACTUAL_PREFIX) ? resolved : undefined;
    },
    async load(id) {
      if (id.startsWith(ACTUAL_PREFIX)) {
        return readFile(id.slice(ACTUAL_PREFIX.length), "utf8");
      }
      if (!id.startsWith(WRAPPER_PREFIX)) {
        return;
      }

      const filename = id.slice(WRAPPER_PREFIX.length);
      const surface = await exportSurface(filename, exportCache);
      return target === "ssr"
        ? ssrBoundarySource(surface)
        : clientBoundarySource(filename, surface);
    },
  };
}

async function isClientBoundary(id, cache) {
  const filename = cleanId(id);
  if (
    !path.isAbsolute(filename) ||
    filename.split(path.sep).includes("node_modules") ||
    ![".js", ".jsx", ".ts", ".tsx"].includes(path.extname(filename))
  ) {
    return false;
  }
  if (!cache.has(filename)) {
    cache.set(filename, hasUseClientDirective(await readFile(filename, "utf8")));
  }
  return cache.get(filename);
}

function cleanId(id) {
  return id.split("?", 1)[0];
}

function hasUseClientDirective(source) {
  let remaining = source.replace(/^\uFEFF/, "").trimStart();
  while (remaining.startsWith("//") || remaining.startsWith("/*")) {
    if (remaining.startsWith("//")) {
      const end = remaining.indexOf("\n");
      remaining = end === -1 ? "" : remaining.slice(end + 1).trimStart();
    } else {
      const end = remaining.indexOf("*/", 2);
      remaining = end === -1 ? "" : remaining.slice(end + 2).trimStart();
    }
  }
  return /^(["'])use client\1(?:;|\s|$)/.test(remaining);
}

async function exportSurface(filename, cache) {
  if (cache.has(filename)) {
    return cache.get(filename);
  }
  const source = stripComments(await readFile(filename, "utf8"));
  if (EXPORT_ALL.test(source)) {
    throw new Error(
      "Modules marked 'use client' cannot use `export * from ...`. Re-export explicit component names instead.",
    );
  }

  let hasDefault = EXPORT_DEFAULT.test(source);
  const named = new Set();
  for (const pattern of NAMED_EXPORTS) {
    pattern.lastIndex = 0;
    for (const match of source.matchAll(pattern)) {
      named.add(match[1]);
    }
  }
  EXPORT_BLOCK.lastIndex = 0;
  for (const match of source.matchAll(EXPORT_BLOCK)) {
    for (const specifier of match[1].split(",")) {
      const parts = specifier.trim().split(/\s+as\s+/);
      const exported = parts.at(-1)?.trim();
      if (!exported || exported.startsWith("type ")) {
        continue;
      }
      if (exported === "default") {
        hasDefault = true;
      } else if (/^[A-Za-z_$][\w$]*$/.test(exported)) {
        named.add(exported);
      } else {
        throw new Error(
          `Unsupported export ${JSON.stringify(exported)} in a module marked 'use client'.`,
        );
      }
    }
  }

  const surface = { hasDefault, named: [...named].sort() };
  cache.set(filename, surface);
  return surface;
}

function ssrBoundarySource({ hasDefault, named }) {
  const exports = named
    .map(
      (name) =>
        `export const ${name} = createClientBoundary(${JSON.stringify(name)});`,
    )
    .join("\n");
  return `
const createClientBoundary = (exportName) => {
  const Boundary = (props) => props?.children ?? null;
  Boundary.displayName = \`ClientBoundary(\${exportName})\`;
  return Boundary;
};
${hasDefault ? 'export default createClientBoundary("default");' : ""}
${exports}
`;
}

function clientBoundarySource(filename, { hasDefault, named }) {
  const actualId = `${ACTUAL_PREFIX}${filename}`;
  const exports = named
    .map(
      (name) =>
        `export const ${name} = createClientBoundary(actual.${name}, ${JSON.stringify(name)});`,
    )
    .join("\n");
  return `
import React, { useEffect, useState } from "react";
import * as actual from ${JSON.stringify(actualId)};
const createClientBoundary = (Actual, exportName) => {
  const Boundary = (props) => {
    const [isMounted, setIsMounted] = useState(false);
    useEffect(() => setIsMounted(true), []);
    if (!isMounted) return props?.children ?? null;
    return React.createElement(Actual, props ?? {});
  };
  Boundary.displayName = \`ClientBoundary(\${exportName})\`;
  return Boundary;
};
${hasDefault ? 'export default createClientBoundary(actual.default, "default");' : ""}
${exports}
`;
}

function stripComments(source) {
  let output = "";
  let quote;
  let lineComment = false;
  let blockComment = false;

  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    const next = source[index + 1];
    if (lineComment) {
      if (character === "\n") {
        lineComment = false;
        output += character;
      }
    } else if (blockComment) {
      if (character === "*" && next === "/") {
        blockComment = false;
        index += 1;
      } else if (character === "\n") {
        output += character;
      }
    } else if (quote) {
      output += character;
      if (character === quote && source[index - 1] !== "\\") {
        quote = undefined;
      }
    } else if (character === '"' || character === "'" || character === "`") {
      quote = character;
      output += character;
    } else if (character === "/" && next === "/") {
      lineComment = true;
      index += 1;
    } else if (character === "/" && next === "*") {
      blockComment = true;
      index += 1;
    } else {
      output += character;
    }
  }
  return output;
}
