import asyncio
from os import environ
from pathlib import Path
from subprocess import PIPE
from tempfile import TemporaryDirectory

from mountaineer.controller import ControllerBase
from mountaineer.js_compiler.base import ClientBuilderBase, ClientBundleMetadata
from mountaineer.js_compiler.exceptions import BuildProcessException
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

    async def handle_file(
        self,
        file_path: ManagedViewPath,
        controller: ControllerBase | None,
        metadata: ClientBundleMetadata,
    ):
        # If this is a CSS file we try to process it
        if file_path.suffix not in {".css", ".scss"}:
            return

        root_path = file_path.get_package_root_link()
        built_css = await self.process_css(file_path)
        (
            root_path.get_managed_static_dir(tmp_build=True)
            / self.get_style_output_name(file_path)
        ).write_text(built_css)

    async def process_css(self, css_path: ManagedViewPath) -> str:
        """
        Process a CSS file using PostCSS and output the transformed contents.
        """
        is_installed, cli_path = self.postcss_is_installed(
            css_path.get_package_root_link()
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
                    "NODE_PATH": str(css_path.get_package_root_link() / "node_modules"),
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
