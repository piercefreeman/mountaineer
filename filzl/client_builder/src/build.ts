import { build } from "esbuild";
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

const createSyntheticPage = (
  pagePath: string,
  layoutPaths: string[],
  outputDir: string,
  rootElement: string,
): string => {
  /*
   * Following the Next.js syntax, layouts wrap individual pages in a top-down order. Here we
   * create a synthetic page that wraps the actual page in the correct order.
   * The output is a valid React file that acts as the page entrypoint
   * for the `rootElement` ID in the DOM.
   */
  const pageImportPath = relative(outputDir, pagePath).replace(/\\/g, "/");
  const layoutImportPaths = layoutPaths.map((path) =>
    relative(outputDir, path).replace(/\\/g, "/"),
  );

  let content = "";
  content += "import { createRoot } from 'react-dom/client';\n";
  layoutImportPaths.forEach((layoutPath, index) => {
    content += `import Layout${index} from '../${layoutPath}';\n`;
  });
  content += `import Page from '../${pageImportPath}';\n\n`;

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
  content += "};\n\n";

  content += `const container = document.getElementById('${rootElement}');`;
  content += "const root = createRoot(container!);";
  content += `root.render(<Entrypoint />);`;

  const syntheticFilePath = join(outputDir, "synthetic.tsx");
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
  const syntheticPage = createSyntheticPage(
    pagePath,
    layoutPaths,
    outputTempPath,
    "root",
  );

  const compiledPath = join(outputTempPath, "dist", "output.js");
  const buildResult = await build({
    entryPoints: [syntheticPage],
    bundle: true,
    outfile: compiledPath,
    format: "esm",
    loader: { ".tsx": "tsx" },
  });

  if (buildResult.errors.length > 0) {
    console.error(buildResult.errors);
    throw new Error("Failed to compile page");
  }

  // Read the output file and return it
  const compiledContents = readFileSync(compiledPath, "utf-8");
  rmdirSync(outputTempPath, { recursive: true });

  return compiledContents;
};
