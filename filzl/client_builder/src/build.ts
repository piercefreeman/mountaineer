import { BuildOptions, build } from "esbuild";
import { join, relative } from "path";
import {
  writeFileSync,
  readFileSync,
  rmdirSync,
  mkdtempSync,
  existsSync,
  symlinkSync,
} from "fs";
import { findLayouts } from "./sniff";
import { tmpdir } from "os";

const createSyntheticEntrypoint = ({
  pagePath,
  layoutPaths,
  outputDir,
}: {
  pagePath: string;
  layoutPaths: string[];
  outputDir: string;
}) => {
  const pageImportPath = relative(outputDir, pagePath).replace(/\\/g, "/");
  const layoutImportPaths = layoutPaths.map((path) =>
    relative(outputDir, path).replace(/\\/g, "/"),
  );

  let content = "";
  const imports = new Array<string>();

  layoutImportPaths.forEach((layoutPath, index) => {
    imports.push(`import Layout${index} from '../${layoutPath}';`);
  });
  imports.push(`import Page from '../${pageImportPath}';`);

  content += "const Entrypoint = () => {\n";
  content += "return (\n";

  content += layoutImportPaths.map((_, index) => `<Layout${index}>`).join("");
  content += "<Page />";

  // Reverse the layout import paths to close the tags in the correct order
  // (innermost to outermost)
  layoutImportPaths.forEach((_, index) => {
    content += `</Layout${layoutImportPaths.length - 1 - index}>`;
  });
  content += "\n);\n";
  content += "};";

  return {
    entrypoint: content,
    imports,
  };
};

const createSyntheticClientPage = ({
  pagePath,
  layoutPaths,
  outputDir,
  rootElement,
}: {
  pagePath: string;
  layoutPaths: string[];
  outputDir: string;
  rootElement: string;
}): string => {
  /*
   * Following the Next.js syntax, layouts wrap individual pages in a top-down order. Here we
   * create a synthetic page that wraps the actual page in the correct order.
   * The output is a valid React file that acts as the page entrypoint
   * for the `rootElement` ID in the DOM.
   */
  const { entrypoint, imports } = createSyntheticEntrypoint({
    pagePath,
    layoutPaths,
    outputDir,
  });

  let content = "";
  content += "import * as React from 'react';\n";
  content += "import { hydrateRoot } from 'react-dom/client';\n";
  content += [...imports].join("\n") + "\n";

  content += entrypoint + "\n";

  content += `const container = document.getElementById('${rootElement}');`;
  content += `hydrateRoot(container, <Entrypoint />);`;

  const syntheticFilePath = join(outputDir, "synthetic_client.tsx");
  writeFileSync(syntheticFilePath, content);

  return syntheticFilePath;
};

const createSyntheticSSRPage = ({
  pagePath,
  layoutPaths,
  outputDir,
}: {
  pagePath: string;
  layoutPaths: string[];
  outputDir: string;
}) => {
  /*
   * Create a synthetic page that generates the HTML for the synthetic page.
   * This output is intended for execution in a Javascript/V8 runtime engine
   * to evaluate the final output.
   */
  const { entrypoint, imports } = createSyntheticEntrypoint({
    pagePath,
    layoutPaths,
    outputDir,
  });

  let content = "";
  content += "import * as React from 'react';\n";
  content += "import { renderToString } from 'react-dom/server';";
  content += [...imports].join("\n") + "\n";

  content += entrypoint + "\n";

  content += "export const Index = () => renderToString(<Entrypoint />);";

  const syntheticFilePath = join(outputDir, "synthetic_server.tsx");
  writeFileSync(syntheticFilePath, content);

  return syntheticFilePath;
};

const linkProjectFiles = (rootPath: string, tempPath: string) => {
  /*
   * Javascript packages define a variety of build metadata in the root directory
   * of the project (tsconfig.json, package.json, etc). Since we're running our esbuild pipeline
   * in a temporary directory, we need to copy over the key files. We use a symbolic link
   * to avoid copying the files over.
   */
  const toLink = ["package.json", "tsconfig.json", "node_modules"];

  toLink.forEach((fileOrDir) => {
    const target = join(rootPath, fileOrDir);
    const link = join(tempPath, fileOrDir);

    if (existsSync(target)) {
      symlinkSync(target, link, "junction"); // 'junction' is used for directory symlinks on Windows
    } else {
      console.warn(`Warning: ${fileOrDir} does not exist at ${rootPath}`);
    }
  });
};

export const buildPage = async (pagePath: string, rootPath: string) => {
  /*
   * Build the final javascript bundle for this given page. Constructs the
   * final page by merging the layouts and the page into a synethic file and
   * compiling that.
   */
  // Scratch working directory, since esbuild needs to provided with file paths
  const tempDirPrefix = join(tmpdir(), "filzl-build");
  const outputTempPath = mkdtempSync(tempDirPrefix);

  // Mirror the project configuration files
  linkProjectFiles(rootPath, outputTempPath);

  const layoutPaths = findLayouts(pagePath, rootPath);
  const clientSyntheticPath = createSyntheticClientPage({
    pagePath,
    layoutPaths,
    outputDir: outputTempPath,
    rootElement: "root",
  });
  const serverSyntheticPath = createSyntheticSSRPage({
    pagePath,
    layoutPaths,
    outputDir: outputTempPath,
  });

  const clientCompiledPath = join(outputTempPath, "dist", "output.client.js");
  const serverCompiledPath = join(outputTempPath, "dist", "output.server.js");

  const commonBuildParams: BuildOptions = {
    bundle: true,
    loader: { ".tsx": "tsx" },
    sourcemap: true,
  };

  const clientBuildResult = await build({
    entryPoints: [clientSyntheticPath],
    outfile: clientCompiledPath,
    format: "esm",
    ...commonBuildParams,
  });
  const serverBuildResult = await build({
    entryPoints: [serverSyntheticPath],
    outfile: serverCompiledPath,
    format: "iife",
    globalName: "SSR",
    define: {
      global: "window",
    },
    external: [],
    ...commonBuildParams,
  });

  if (clientBuildResult.errors.length > 0) {
    console.error(clientBuildResult.errors);
    throw new Error("Failed to compile client page");
  }
  if (serverBuildResult.errors.length > 0) {
    console.error(serverBuildResult.errors);
    throw new Error("Failed to compile server page");
  }

  // Read the output file and return it
  const clientCompiledContents = readFileSync(clientCompiledPath, "utf-8");
  const clientSourceMapContents = readFileSync(
    `${clientCompiledPath}.map`,
    "utf-8",
  );
  const serverCompiledContents = readFileSync(serverCompiledPath, "utf-8");
  const serverSourceMapContents = readFileSync(
    `${serverCompiledPath}.map`,
    "utf-8",
  );

  rmdirSync(outputTempPath, { recursive: true });

  return {
    clientCompiledContents,
    clientSourceMapContents,
    serverCompiledContents,
    serverSourceMapContents,
  };
};
