/*
 * Utilities to sniff the user filesystem for desired files.
 */
import { resolve, dirname, join } from "path";
import { existsSync } from "fs";

export const findLayouts = (
  pagePath: string,
  projectBasePath: string,
): string[] => {
  /*
   * Given a page.tsx path, find all the layouts that apply to it.
   * Returns the layout paths that are found. Orders them from the top->down
   * as they expect to be rendered.
   */
  // It's easier to handle absolute paths when doing direct string comparisons
  // of the file hierarchy.
  pagePath = resolve(pagePath);
  projectBasePath = resolve(projectBasePath);

  // Ensure that users are calling this function on the page path
  if (!pagePath.endsWith("page.tsx")) {
    throw new Error(
      `findLayouts must be called on a page.tsx file. Received ${pagePath}`,
    );
  }

  // Ensure that pagePath is a child of projectBasePath
  if (!pagePath.startsWith(projectBasePath)) {
    throw new Error(
      `findLayouts must be called on a page.tsx file that is a child of the project base path. Received ${pagePath} and ${projectBasePath}`,
    );
  }

  let currentDir = dirname(pagePath);
  let layoutPaths: string[] = [];

  while (true) {
    const layoutPath = directoryHasLayout(currentDir);
    if (layoutPath) layoutPaths.push(layoutPath);

    // No layout files are allowed to exist above the app project directory
    // Once we've explored this directory, we can stop
    if (isRootDirectory(currentDir, projectBasePath)) break;

    // Move up a directory to explore the parent
    currentDir = dirname(currentDir);
  }

  return layoutPaths.reverse();
};

const directoryHasLayout = (directory: string): string | null => {
  const layoutFile = join(directory, "layout.tsx");
  if (existsSync(layoutFile)) return layoutFile;
  return null;
};

const isRootDirectory = (currentDir: string, baseDir: string): boolean => {
  return currentDir === baseDir;
};
