import asyncio
from json import dumps as json_dumps
from logging import warning
from os import PathLike, environ
from pathlib import Path
from platform import machine as platform_machine
from platform import system as platform_system
from shutil import move as shutil_move
from subprocess import PIPE
from subprocess import run as subprocess_run
from tarfile import open as tarfile_open
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from packaging import version
from tqdm import tqdm

from mountaineer.js_compiler.exceptions import BuildProcessException
from mountaineer.logging import LOGGER

ESBUILD_VERSION = "0.19.11"
URL_PATTERN = "https://registry.npmjs.org/@esbuild/{platform}/-/{filename}"
CACHE_PATH = Path("~/.cache/mountaineer/esbuild").expanduser()


class ESBuildWrapper:
    """
    Python shim for esbuild, only supports a subset of the spec.

    https://esbuild.github.io/api/#build

    """

    def __init__(self, allow_auto_download: bool = True):
        self.allow_auto_download = allow_auto_download

    async def bundle(
        self,
        *,
        entry_points: list[PathLike],
        outfile: PathLike,
        bundle: bool | None = None,
        loaders: dict[str, str] | None = None,
        output_format: str | None = None,
        global_name: str | None = None,
        sourcemap: bool | None = None,
        define: dict[str, str] | None = None,
        node_paths: list[str | Path] | None = None,
    ):
        # Make sure the output file path exists
        Path(outfile).parent.mkdir(parents=True, exist_ok=True)

        # Assemble and run a async subprocess with the above params
        command = [str(self.get_esbuild_path())]

        # We always expect to have entry points and outputs
        for entry_point in entry_points:
            command.append(str(entry_point))
        command.append(f"--outfile={outfile}")

        if bundle:
            command.append("--bundle")

        for ext, loader in (loaders or {}).items():
            command.append(f"--loader:{ext}={loader}")

        if output_format:
            command.append(f"--format={output_format}")

        if global_name:
            command.append(f"--global-name={global_name}")

        if sourcemap:
            command.append("--sourcemap")

        for key, value in (define or {}).items():
            command.append(f"--define:{key}={json_dumps(value)}")

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=PIPE,
            stderr=PIPE,
            env={
                **environ,
                "NODE_PATH": ":".join([str(path) for path in (node_paths or [])]),
            },
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise BuildProcessException(f"esbuild error: {stderr.decode()}")

        return stdout.decode()

    def get_esbuild_path(self):
        """
        If esbuild isn't already available in the path, we download it based
        on the current platform.

        This follows the logic in their official install script:
        https://esbuild.github.io/dl/v0.19.11
        """

        # Determine if we already have esbuild installed
        installed_path = self.get_installed_path()
        if installed_path:
            return installed_path

        if not self.allow_auto_download:
            raise Exception(
                "esbuild is not installed and auto-download is disabled, bundle can't continue."
            )

        # Identify the platform
        system: str = platform_system()
        machine: str = platform_machine()

        # Map the system and machine to the esbuild platform
        if system == "Darwin":
            esbuild_platform = "darwin-arm64" if machine == "arm64" else "darwin-x64"
        elif system == "Linux":
            esbuild_platform = (
                "linux-arm64" if machine in ["arm64", "aarch64"] else "linux-x64"
            )
        elif system == "NetBSD":
            esbuild_platform = "netbsd-x64"
        elif system == "OpenBSD":
            esbuild_platform = "openbsd-x64"
        else:
            raise Exception(f"Unsupported platform: {system} {machine}")

        filename = f"{esbuild_platform}-{ESBUILD_VERSION}.tgz"
        url = URL_PATTERN.format(platform=esbuild_platform, filename=filename)

        with TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            tgz_path = temp_dir_path / filename
            LOGGER.info(f"Downloading current version of esbuild from {url}")
            self.download_with_progress(url, tgz_path)

            # Extract the binary executable
            with tarfile_open(tgz_path, "r:gz") as tar:
                tar.extractall(path=temp_dir)

            # Make sure the cache path exists
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil_move(temp_dir_path / "package" / "bin" / "esbuild", CACHE_PATH)

        return CACHE_PATH

    def download_with_progress(self, url, filename):
        """
        Download a file with a progress bar.
        """
        with urlopen(url) as response, open(filename, "wb") as out_file:
            file_size = int(response.info().get("Content-Length"))
            chunk_size = 1024

            with tqdm(total=file_size, unit="B", unit_scale=True) as bar:
                for data in iter(lambda: response.read(chunk_size), b""):
                    out_file.write(data)
                    bar.update(len(data))

    def get_installed_path(self):
        """
        Check the local version of esbuild and issue a warning if it's outdated.i

        """
        # If they already have the cache path, we can assume they have the right version
        if Path(CACHE_PATH).exists():
            return CACHE_PATH

        result = subprocess_run(
            "esbuild --version", capture_output=True, text=True, shell=True
        )
        if result.returncode == 0 and version.parse(
            result.stdout.strip()
        ) != version.parse(ESBUILD_VERSION):
            warning(
                f"The locally found esbuild version is older than {ESBUILD_VERSION}, continuing anyway...",
                UserWarning,
            )

        # Get the path to this executable
        result = subprocess_run(
            "which esbuild", capture_output=True, text=True, shell=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return False
