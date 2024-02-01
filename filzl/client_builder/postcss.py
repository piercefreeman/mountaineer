import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from filzl.client_builder.base import ClientBuilderBase
from filzl.client_interface.paths import ManagedViewPath
from filzl.controller import ControllerBase


class PostCSSBundler(ClientBuilderBase):
    def handle_file(
        self, current_path: ManagedViewPath, controller: ControllerBase | None
    ):
        # If this is a CSS file we try to process it
        if current_path.suffix != ".css":
            return

        root_path = current_path.get_root_link()
        built_css = self.process_css(current_path)
        (root_path.get_managed_static_dir() / current_path.name).write_text(built_css)

    def process_css(self, css_path: ManagedViewPath) -> str:
        """
        Process a CSS file using PostCSS and output the transformed contents.
        """
        is_installed, cli_path = self.postcss_is_installed(css_path.get_root_link())
        if not is_installed:
            raise EnvironmentError(
                "postcss-cli is not installed in the specified view_root_path. Install it with:\n"
                "$ npm install -D postcss postcss-cli"
            )

        with TemporaryDirectory() as temp_dir_name:
            temp_dir_path = Path(temp_dir_name)
            output_path = temp_dir_path / "output.css"

            try:
                subprocess.run(
                    [cli_path, str(css_path), "-o", str(output_path)],
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"PostCSS processing failed: {e}")

            return output_path.read_text()

    def postcss_is_installed(self, view_root_path: Path):
        # Adjust the check to look for local installation of postcss-cli, which we currently
        # require at the CLI bridge
        expected_path = view_root_path / "node_modules" / ".bin" / "postcss"
        return (
            expected_path.exists() and expected_path.is_file(),
            expected_path,
        )
