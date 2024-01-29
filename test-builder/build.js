const esbuild = require("esbuild");
const { glob } = require("glob");
const path = require("path");
const fs = require("fs");
const { promisify } = require("util");

const writeFileAsync = promisify(fs.writeFile);

// Function to find layout hierarchy
function findLayouts(file, baseDir) {
  console.log("FINDING LAYOUTS", file, baseDir);
  let layouts = [];
  let currentDir = path.resolve(path.dirname(file));
  baseDir = path.resolve(baseDir);

  while (true) {
    const potentialLayout = path.join(currentDir, "layout.tsx");
    console.log("CANDIDATE", potentialLayout);
    if (fs.existsSync(potentialLayout)) {
      layouts.push(potentialLayout);
    }
    console.log("CURRENT", currentDir, baseDir);
    if (baseDir === currentDir) {
      // Break the loop if we reach the root directory to avoid infinite loop
      break;
    }
    // Go to the parent path
    currentDir = path.dirname(currentDir);
  }

  return layouts.reverse();
}

// Function to create a synthetic page
async function createSyntheticPage(file, layouts) {
  const pageImportPath = path.relative(__dirname, file).replace(/\\/g, "/");
  const layoutImportPaths = layouts.map((l) =>
    path.relative(__dirname, l).replace(/\\/g, "/"),
  );

  // TODO: Calculate actual offset path to the react files
  // Right now we assume we're in a /synthetic directory and therefore
  // need to step up once to get to the root app directory
  let content = "";
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

  content +=
    "ReactDOM.render(<Entrypoint />, document.getElementById('root'));";

  const syntheticFilePath = path.join(
    __dirname,
    "synthetic",
    path.basename(file),
  );
  await writeFileAsync(syntheticFilePath, content);

  return syntheticFilePath;
}

// Function to build a page with its layouts
async function buildPage(file) {
  const layouts = findLayouts(file, path.resolve("app"));
  console.log("LAYOUTS", layouts);
  const syntheticPage = await createSyntheticPage(file, layouts);

  await esbuild.build({
    entryPoints: [syntheticPage],
    bundle: true,
    outfile: `dist/${path.basename(file, ".tsx")}.js`,
    format: "esm",
    loader: { ".tsx": "tsx" },
  });
}

// Main function to find and build all pages
async function main() {
  console.log("Finding pages");
  const files = await glob("app/**/page.tsx");

  console.log("Starting build");
  for (const file of files) {
    await buildPage(file);
  }
  console.log("BUILT");
}

await main();
