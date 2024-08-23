from pathlib import Path
from shutil import move as shutil_move
from tempfile import mkdtemp
from time import monotonic_ns

from mountaineer.app import AppController
from mountaineer.client_compiler.base import ClientBundleMetadata
from mountaineer.client_compiler.exceptions import BuildProcessException
from mountaineer.console import CONSOLE
from mountaineer.io import gather_with_concurrency
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath


class ClientCompiler:
    """
    Main entrypoint for compiling client code into the artifacts that
    will be used in production.

    """

    def __init__(
        self,
        view_root: ManagedViewPath,
        app: AppController,
    ):
        self.view_root = view_root
        self.app = app

        self.tmp_dir = Path(mkdtemp())

    async def run_builder_plugins(
        self,
        limit_paths: list[Path] | None = None,
        max_concurrency: int = 10,
    ):
        """
        :param limit_paths: If not provided, will sniff out all the files on disk. Note that
        this is a None equality check; a blank list is provided, we won't refresh any files.

        """
        if limit_paths is None:
            limit_paths = list(self._get_static_files())
            limit_paths += [
                self.view_root.get_controller_view_path(
                    controller_definition.controller
                )
                for controller_definition in self.app.controllers
            ]

        if not limit_paths:
            LOGGER.debug("No files to compile in builder plugins, skipping...")
            return

        # For now we do this every time to make sure we pick up on
        # new controllers that might have been added since this class
        # was created
        self._init_builders()

        for path in limit_paths:
            for builder in self.app.builders:
                builder.mark_file_dirty(path)

        start = monotonic_ns()
        results = await gather_with_concurrency(
            [builder.build_wrapper() for builder in self.app.builders],
            n=max_concurrency,
            catch_exceptions=True,
        )
        LOGGER.debug(f"Plugin builders took {(monotonic_ns() - start) / 1e9}s")

        # Go through the exceptions, logging the build errors explicitly
        has_build_error = False
        final_exception: str = ""
        for result in results:
            if isinstance(result, Exception):
                has_build_error = True
                if isinstance(result, BuildProcessException):
                    CONSOLE.print(f"[bold red]Build error: {result}")
                final_exception += str(result)

        if has_build_error:
            raise BuildProcessException(final_exception)

        # Up until now builders have placed their results into a temporary
        # directory, we want to merge this with the project directory
        self._move_build_artifacts_into_project()

    def _init_builders(self):
        metadata = ClientBundleMetadata(
            live_reload_port=None,
            package_root_link=self.view_root.get_package_root_link(),
            tmp_dir=self.tmp_dir,
        )

        for builder in self.app.builders:
            builder.set_metadata(metadata)

        for builder in self.app.builders:
            for controller_definition in self.app.controllers:
                builder.register_controller(
                    controller_definition.controller,
                    self.view_root.get_controller_view_path(
                        controller_definition.controller
                    ),
                )

    def _get_static_files(self):
        ignore_directories = ["_ssr", "_static", "_server", "_metadata", "node_modules"]

        for view_root in self._get_all_root_views():
            for dir_path, _, filenames in view_root.walk():
                for filename in filenames:
                    if any(
                        [
                            directory in dir_path.parts
                            for directory in ignore_directories
                        ]
                    ):
                        continue
                    yield dir_path / filename

    def _get_all_root_views(self) -> list[ManagedViewPath]:
        """
        The self.view_root variable is the root of the current user project. We may have other
        "view roots" that store view for plugins.

        This function inspects the controller path definitions and collects all of the
        unique root view paths. The returned ManagedViewPaths are all copied and set to
        share the same package root as the user project.

        """
        # Find the view roots
        view_roots = {self.view_root.copy()}
        for controller_definition in self.app.controllers:
            view_path = controller_definition.controller.view_path
            if isinstance(view_path, ManagedViewPath):
                view_roots.add(view_path.get_root_link().copy())

        # All the view roots should have the same package root
        for view_root in view_roots:
            view_root.package_root_link = self.view_root.package_root_link

        return list(view_roots)

    def _move_build_artifacts_into_project(self):
        """
        Now that we build has completed, we can clear out the old files and replace it
        with the thus-far temporary files

        This cleans up old controllers in the case that they were deleted, and prevents
        outdated md5 content hashes from being served

        """
        # For now, just copy over the _tmp files into the main directory. Replace them
        # if they exist. This is a differential copy to support our build pipeline
        # that will only change progressively. It notably does not handle the case of
        # deleted files.
        for tmp_path, final_path in [
            (
                self.view_root.get_managed_static_dir(tmp_build=True),
                self.view_root.get_managed_static_dir(),
            ),
            # (
            #    self.view_root.get_managed_ssr_dir(tmp_build=True),
            #    self.view_root.get_managed_ssr_dir(),
            # ),
        ]:
            # Only remove the final path if the matching tmp path build exists
            # This creates a merged build where we maintain the base code created
            # on startup and the possibly incremental builds.
            # We do the deletion up-front so we don't delete our actual files mid-copy
            # in case we have multiple with the same prefix (like .js and .map)
            for tmp_file in tmp_path.glob("*"):
                # Strip any md5 hashes from the filename and delete
                # all the items matching the same name
                base_filename = tmp_file.name.rsplit("-")[0].rsplit(".")[0]
                for old_file in final_path.glob(f"{base_filename}*"):
                    old_file.unlink()

            # We've cleared old versions, now freshly copy the files
            for tmp_file in tmp_path.glob("*"):
                final_file = final_path / tmp_file.name
                shutil_move(tmp_file, final_file)
