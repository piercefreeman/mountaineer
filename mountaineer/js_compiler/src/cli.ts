import { stdout } from "process";
import * as esbuild from "esbuild";

interface CLIArgs {
  pagePath: string;
  viewRootPath: string;
}

export const parseCLIArgs = (): CLIArgs => {
  const args = process.argv.slice(2);

  // Parse CLI arguments
  let pagePath: string | undefined;
  let viewRootPath: string | undefined;

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--page-path":
        pagePath = args[++i];
        break;
      case "--view-root-path":
        viewRootPath = args[++i];
        break;
    }
  }

  if (!pagePath || !viewRootPath) {
    throw new Error(
      "Missing required arguments: --page-path and --view-root-path are required.",
    );
  }

  const cliArgs: CLIArgs = {
    pagePath: resolve(pagePath),
    viewRootPath: resolve(viewRootPath),
  };

  // Make sure both of these paths exist
  const validatePaths = [cliArgs.pagePath, cliArgs.viewRootPath];
  for (const path of validatePaths) {
    if (!existsSync(path)) {
      throw new Error(`Path does not exist: ${path}`);
    }
  }

  return cliArgs;
};

const main = async () => {
  const cliArgs = parseCLIArgs();

  await esbuild.build({
    entryPoints: ["app.js"],
    bundle: true,
    outfile: "out.js",
    plugins: [envPlugin],
  });
};

await main();
