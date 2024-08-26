import asyncio
from os import environ
from pathlib import Path
from subprocess import PIPE
from tempfile import TemporaryDirectory
from time import monotonic_ns

from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn

from mountaineer.client_compiler.base import ClientBuilderBase
from mountaineer.client_compiler.exceptions import BuildProcessException
from mountaineer.console import CONSOLE
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath


class PostCSSBundler(ClientBuilderBase):
    """
    Support PostCSS processing for CSS files.

    - Assumes postcss-cli is installed in the primary project's package root (ie.
      the ci_webapp/views/node_modules directory)
    - Assumes that the css file under consideration has a root postcss.config.js file
      within its own view path

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We want to keep track of known css files, so we'll specifically
        # rebuild them every change
        self.known_css_files: set[Path] = set()

    def mark_file_dirty(self, file_path: Path):
        # We expect that our runtime will call us at least once with the style
        if file_path.suffix in {".css", ".scss"}:
            self.known_css_files.add(file_path)
            super().mark_file_dirty(file_path)
        elif file_path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            # Stylesheets should reload if any frontend file or stylesheet changes,
            # not just the stylesheet itself since plugins like tailwind analyze the frontend
            # files for style declarations
            super().mark_file_dirty(file_path)

    async def build(self):
        if not self.metadata:
            raise ValueError("No metadata provided to build")

        if not self.dirty_files:
            return

        known_css_files = self.managed_views_from_paths(list(self.known_css_files))

        # Figure out which roots the actually modified files belong to. We only
        # need to update the stylesheets that are in scope of the given root packages.
        dirty_managed = self.managed_views_from_paths(list(self.dirty_files))
        dirty_roots = {path.get_root_link() for path in dirty_managed}

        dirty_stylesheets = {
            stylesheet
            for stylesheet in known_css_files
            if stylesheet.get_root_link() in dirty_roots
        }
        LOGGER.debug(
            f"Potentially dirty stylesheets detected {dirty_stylesheets} of {known_css_files}"
        )

        # We only need to process the known css files
        start = monotonic_ns()
        with Progress(
            SpinnerColumn(),
            *Progress.get_default_columns(),
            TimeElapsedColumn(),
            console=CONSOLE,
            transient=True,
        ) as progress:
            build_task = progress.add_task(
                "[cyan]Building CSS...", total=len(dirty_stylesheets)
            )

            for file_path in dirty_stylesheets:
                root_path = self.metadata.package_root_link
                built_css = await self.process_css(file_path)
                (
                    root_path.get_managed_static_dir(tmp_build=True)
                    / self.get_style_output_name(file_path)
                ).write_text(built_css)
                progress.update(build_task, advance=1)

        CONSOLE.print(
            f"[bold green]🎨 Compiled {len(dirty_stylesheets)} stylesheet{'s' if len(dirty_stylesheets) > 1 else ''} in {(monotonic_ns() - start) / 1e9:.2f}s"
        )

    async def process_css(self, css_path: ManagedViewPath) -> str:
        """
        Process a CSS file using PostCSS and output the transformed contents.
        """
        if not self.metadata:
            raise ValueError("No metadata provided to build")

        is_installed, cli_path = self.postcss_is_installed(
            self.metadata.package_root_link
        )
        if not is_installed:
            raise EnvironmentError(
                "postcss-cli is not installed in the specified view_root_path. Install it with:\n"
                "$ npm install -D postcss postcss-cli"
            )

        with TemporaryDirectory() as temp_dir_name:
            temp_dir_path = Path(temp_dir_name)
            output_path = temp_dir_path / "output.css"

            command = [str(cli_path), str(css_path), "-o", str(output_path)]
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=PIPE,
                stderr=PIPE,
                # postcss won't find the config file if we don't set the cwd
                # we assume this is in each view's root directory
                cwd=css_path.get_root_link(),
                env={
                    **environ,
                    # We expect the main package root will be the one with node modules installed
                    "NODE_PATH": str(self.metadata.package_root_link / "node_modules"),
                },
            )

            stdout, stderr = await process.communicate()

            if stdout.strip():
                LOGGER.info(stdout.decode())
            if stderr.strip():
                LOGGER.warning(stderr.decode())

            if process.returncode != 0:
                raise BuildProcessException(f"postcss error: {stderr.decode()}")

            return output_path.read_text()

    def get_style_output_name(self, original_stylesheet_path: ManagedViewPath) -> str:
        """
        Given a path to an original stylesheet, return the name of the compiled css file

        original_stylesheet_path: "path/to/styles.scss"
        output: "path_to_styles.css"
        """
        root_path = original_stylesheet_path.get_root_link()
        relative_path = original_stylesheet_path.relative_to(root_path)

        # Convert the parent portions of the path to make sure our final output
        # filename is unique
        unique_path = "_".join(
            [*relative_path.parent.parts, original_stylesheet_path.name]
        )
        return str(Path(unique_path).with_suffix(".css"))

    def postcss_is_installed(self, view_root_path: Path):
        # Adjust the check to look for local installation of postcss-cli, which we currently
        # require at the CLI bridge
        expected_path = view_root_path / "node_modules" / ".bin" / "postcss"
        return (
            expected_path.exists() and expected_path.is_file(),
            expected_path,
        )
