import { resolve } from "path";
import { existsSync } from "fs";
import { buildPage } from "./build";
import { stdout } from "process";

interface CLIArgs {
  pagePath: string;
  viewRootPath: string;
}

const FINAL_OUTPUT_MARKER = {
  // Decorator used so client callers are able to detect the final
  // output from this script, in case other stdlog commands return JSON
  // as well.
  _output: true,
};

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
  const { compiledContents, sourceMapContents } = await buildPage(
    cliArgs.pagePath,
    cliArgs.viewRootPath,
  );

  const payload = {
    ...FINAL_OUTPUT_MARKER,
    compiledContents,
    sourceMapContents,
  };

  // Write the payload to stdout
  stdout.write(JSON.stringify(payload));
};

await main();
