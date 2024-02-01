import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from filzl.client_builder.base import ClientBuilderBase


class PostCSSBundler(ClientBuilderBase):
    def handle_file(self, file_path: Path, static_output: Path):
        # If this is a CSS file we try to process it
        if file_path.suffix != ".css":
            return

        built_css = self.process_css(file_path)
        (static_output / file_path.name).write_text(built_css)

    def process_css(self, css_path: Path) -> str:
        """
        Process a CSS file using PostCSS and output the transformed contents.
        """
        is_installed, cli_path = self.postcss_is_installed()
        if not is_installed:
            raise EnvironmentError(
                "postcss-cli is not installed in the specified view_root_path. Install it with:\n"
                "$ npm install -D postcss postcss-cli"
            )

        css_file_path = self.view_root_path / css_path
        if not css_file_path.is_file():
            raise FileNotFoundError(
                f"The specified css_path does not exist: {css_path}"
            )

        with TemporaryDirectory() as temp_dir_name:
            temp_dir_path = Path(temp_dir_name)
            output_path = temp_dir_path / "output.css"

            try:
                subprocess.run(
                    [cli_path, str(css_file_path), "-o", str(output_path)],
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"PostCSS processing failed: {e}")

            return output_path.read_text()

    def postcss_is_installed(self):
        # Adjust the check to look for local installation of postcss-cli, which we currently
        # require at the CLI bridge
        expected_path = self.view_root_path / "node_modules" / ".bin" / "postcss"
        return (
            expected_path.exists() and expected_path.is_file(),
            expected_path,
        )
