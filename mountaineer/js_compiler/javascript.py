import multiprocessing
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from time import monotonic_ns
from typing import Any

from inflection import underscore

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.controller import ControllerBase
from mountaineer.js_compiler.base import ClientBuilderBase, ClientBundleMetadata
from mountaineer.js_compiler.exceptions import BuildProcessException
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath, generate_relative_import


@dataclass
class JSBundle:
    temp_path: Path
    client_entrypoint_path: Path
    server_entrypoint_path: Path

    # Also pass along the raw parameters that we were called with
    file_path: ManagedViewPath
    controller: ControllerBase
    metadata: ClientBundleMetadata


@dataclass
class BundleOutput:
    client_entrypoint_path: Path
    client_compiled_contents: str
    client_source_map_contents: str
    server_entrypoint_path: Path
    server_compiled_contents: str
    server_source_map_contents: str


@dataclass
class CompiledOutput:
    success: bool
    exception_type: str | None = None
    exception_message: str | None = None


class JavascriptBundler(ClientBuilderBase):
    """
    Compile the client-written tsx/jsx to raw javascript files for execution as part
    of the SSR pipeline and client hydration.
    """

    def __init__(
        self,
        root_element: str = "root",
        environment: str = "development",
        tmp_dir: Path | None = None,
    ):
        super().__init__(tmp_dir=tmp_dir)

        self.root_element = root_element
        self.environment = environment

        # Pending paths to be processed
        # (client_path, server_path)
        self.pending_files: list[JSBundle] = []

    async def init_state(self, global_state):
        self.global_state = global_state

        # Launch a thread that will handle our build queue, potentially across
        # multiple subprocesses
        build_input_queue: multiprocessing.Queue[tuple[Any]] = multiprocessing.Queue()
        build_output_queue: multiprocessing.Queue[
            CompiledOutput
        ] = multiprocessing.Queue()

        global_state["js_bundler_input"] = build_input_queue
        global_state["js_bundler_output"] = build_output_queue

        thread = Thread(
            target=self.process_pending_files,
            args=(build_input_queue, build_output_queue),
            daemon=True,
        )
        thread.start()

    def process_pending_files(
        self, input_queue: multiprocessing.Queue, output_queue: multiprocessing.Queue
    ):
        LOGGER.debug("Spawning process_pending_files")
        while True:
            try:
                payload = input_queue.get()
            except EOFError:
                LOGGER.debug("Exiting process_pending_files")
                return

            LOGGER.debug(f"Got JS build payload: {len(payload)}")
            if payload is None:
                break

            build_params = [
                mountaineer_rs.BuildContextParams(*params) for params in payload
            ]

            start = monotonic_ns()
            try:
                # TODO: Right now this raises pyo3_runtime.PanicException, which isn't caught
                # appropriately. Our try/except block should be catching this.
                mountaineer_rs.build_javascript(build_params)
            except Exception as e:
                LOGGER.error(f"Error building JS: {e}")
                output_queue.put(
                    CompiledOutput(
                        success=False,
                        exception_type=e.__class__.__name__,
                        exception_message=str(e),
                    )
                )
                continue

            LOGGER.debug(
                f"Processed payload in {(monotonic_ns() - start) / 1e9} seconds"
            )

            output_queue.put(CompiledOutput(success=True))

    async def start_build(self):
        self.pending_files = []

        # Make sure we have been initialized
        if self.global_state is None:
            await self.init_state({})

    async def handle_file(
        self,
        file_path: ManagedViewPath,
        controller: ControllerBase | None,
        metadata: ClientBundleMetadata,
    ):
        if controller is None:
            # Require a controller for our bundling
            return None
        if file_path.suffix not in [".tsx", ".jsx"]:
            # We only know how to parse tsx and jsx files
            return None

        # Now we can process the files in bulk
        payload = self.generate_js_bundle(
            file_path=file_path, controller=controller, metadata=metadata
        )
        self.pending_files.append(payload)

    async def finish_build(self):
        if not self.global_state:
            raise ValueError("JavascriptBundler has not been initialized")

        build_params = []
        for payload in self.pending_files:
            controller_base = underscore(payload.controller.__class__.__name__)

            root_path = payload.file_path.get_package_root_link()
            static_dir = root_path.get_managed_static_dir(tmp_build=True)
            ssr_dir = root_path.get_managed_ssr_dir(tmp_build=True)

            # Client entrypoint config
            # All these tuple arguments map to the input __init__ arguments
            # for mountaineer_rs.BuildContextParams
            build_params.append(
                (
                    str(payload.client_entrypoint_path),
                    str(payload.temp_path / "node_modules"),
                    self.environment,
                    payload.metadata.live_reload_port
                    if payload.metadata.live_reload_port
                    else 0,
                    False,
                    controller_base,
                    str(static_dir),
                )
            )
            # Server entrypoint config
            build_params.append(
                (
                    str(payload.server_entrypoint_path),
                    str(payload.temp_path / "node_modules"),
                    self.environment,
                    0,
                    True,
                    controller_base,
                    str(ssr_dir),
                )
            )

        # Send the build params to the queue
        self.global_state["js_bundler_input"].put(build_params)
        output_payload = self.global_state["js_bundler_output"].get()

        if not output_payload.success:
            if output_payload.exception_type == "ValueError":
                raise BuildProcessException(output_payload.exception_message)
            raise ValueError(
                f"Error building JS, unknown error: {output_payload.exception_message}"
            )

    def generate_js_bundle(
        self,
        file_path: ManagedViewPath,
        controller: ControllerBase,
        metadata: ClientBundleMetadata,
    ) -> JSBundle:
        # Before starting, make sure all the files are valid
        self.validate_page(
            page_path=file_path, view_root_path=file_path.get_root_link()
        )

        # Since this directory should persist between build lifecycles, we both use a unchanging
        # directory name and one that will be unique across different controllers
        temp_dir_path = self.tmp_dir / controller.__class__.__name__
        temp_dir_path.mkdir(exist_ok=True)

        layout_paths = self.sniff_for_layouts(
            page_path=file_path, view_root_path=file_path.get_root_link()
        )

        # The same endpoint definition is used for both SSR and the client build
        synthetic_payload = self.build_synthetic_endpoint(
            page_path=file_path,
            layout_paths=layout_paths,
            # This output path should be relative to the `synthetic_client` and `synthetic_server`
            # entrypoint files
            output_path=temp_dir_path,
        )

        client_entrypoint = self.build_synthetic_client_page(*synthetic_payload)
        ssr_entrypoint = self.build_synthetic_ssr_page(*synthetic_payload)

        client_entrypoint_path = temp_dir_path / "synthetic_client.tsx"
        server_entrypoint_path = temp_dir_path / "synthetic_server.tsx"

        self.link_project_files(
            view_root_path=file_path.get_package_root_link(),
            temp_dir_path=temp_dir_path,
        )
        client_entrypoint_path.write_text(client_entrypoint)
        server_entrypoint_path.write_text(ssr_entrypoint)

        return JSBundle(
            temp_path=temp_dir_path,
            client_entrypoint_path=client_entrypoint_path,
            server_entrypoint_path=server_entrypoint_path,
            file_path=file_path,
            controller=controller,
            metadata=metadata,
        )

    def build_synthetic_client_page(
        self,
        synthetic_imports: list[str],
        synthetic_endpoint: str,
        synthetic_endpoint_name: str,
    ):
        lines: list[str] = []

        # Assume the client page is always being called from a page that has been
        # initially rendered by SSR
        lines.append("import * as React from 'react';")
        lines.append("import { hydrateRoot } from 'react-dom/client';")
        lines += synthetic_imports

        lines.append(synthetic_endpoint)

        lines.append(
            f"const container = document.getElementById('{self.root_element}');"
        )
        lines.append(f"hydrateRoot(container, <{synthetic_endpoint_name} />);")

        return "\n".join(lines)

    def build_synthetic_ssr_page(
        self,
        synthetic_imports: list[str],
        synthetic_endpoint: str,
        synthetic_endpoint_name: str,
    ):
        lines: list[str] = []

        lines.append("import * as React from 'react';")
        lines.append("import { renderToString } from 'react-dom/server';")
        lines += synthetic_imports

        lines.append(synthetic_endpoint)

        lines.append(
            f"export const Index = () => renderToString(<{synthetic_endpoint_name} />);"
        )

        return "\n".join(lines)

    def build_synthetic_endpoint(
        self, *, page_path: ManagedViewPath, layout_paths: list[Path], output_path: Path
    ):
        """
        Following the Next.js syntax, layouts wrap individual pages in a top-down order. Here we
        create a synthetic page that wraps the actual page in the correct order.
        The output is a valid React file that acts as the page entrypoint
        for the `rootElement` ID in the DOM.

        """
        # All import paths have to be a relative path from the scratch directory
        # to the original file
        import_paths: list[str] = []

        static_api_path = (
            page_path.get_package_root_link().get_managed_code_dir() / "live_reload.ts"
        )
        import_paths.append(
            f"import mountLiveReload from '{generate_relative_import(output_path, static_api_path)}';"
        )

        import_paths.append(
            f"import Page from '{generate_relative_import(output_path, page_path)}';"
        )

        for i, layout_path in enumerate(layout_paths):
            import_paths.append(
                f"import Layout{i} from '{generate_relative_import(output_path, layout_path)}';"
            )

        # The synthetic endpoint is a function that returns a React component
        entrypoint_name = "Entrypoint"
        content_lines = [
            f"const {entrypoint_name} = () => {{",
            # This hook will only run in the browser, in dev mode
            # Otherwise it will short-circuit so it won't apply to production
            "mountLiveReload({});" "return (",
            *[f"<Layout{i}>" for i in range(len(layout_paths))],
            "<Page />",
            *[f"</Layout{i}>" for i in reversed(range(len(layout_paths)))],
            ");",
            "};",
        ]

        return import_paths, "\n".join(content_lines), entrypoint_name

    def link_project_files(self, *, view_root_path: Path, temp_dir_path: Path):
        """
        Javascript packages define a variety of build metadata in the root directory
        of the project (tsconfig.json, package.json, etc). Since we're running our esbuild pipeline
        in a temporary directory, we need to copy over the key files. We use a symbolic link
        to avoid copying the files over.
        """
        required_to_link = ["package.json", "node_modules"]
        optional_to_link = ["tsconfig.json"]

        for file_name in required_to_link + optional_to_link:
            # Only throw an error if the file is required to exist
            if not (view_root_path / file_name).exists():
                if file_name in required_to_link:
                    raise ValueError(
                        f"Error linking, expected {file_name} to exist in {view_root_path}"
                    )
                continue

            # If the file exists, we assume it's to the correct path
            LOGGER.debug(f"Linking {file_name} to {temp_dir_path}")
            (temp_dir_path / file_name).unlink(missing_ok=True)
            (temp_dir_path / file_name).symlink_to(view_root_path / file_name)

    def sniff_for_layouts(self, *, page_path: Path, view_root_path: Path):
        """
        Given a page.tsx path, find all the layouts that apply to it.
        Returns the layout paths that are found. Orders them from the top->down
        as they expect to be rendered.

        """
        # It's easier to handle absolute paths when doing direct string comparisons
        # of the file hierarchy.
        page_path = page_path.resolve().absolute()
        view_root_path = view_root_path.resolve().absolute()

        # Starting at the page path, walk up the directory tree and yield each layout
        # that is found.
        layouts: list[Path] = []
        current_path = page_path.parent

        while current_path != view_root_path:
            layout_path_tsx = current_path / "layout.tsx"
            layout_path_jsx = current_path / "layout.jsx"

            # We shouldn't have both in the same directory
            if layout_path_tsx.exists() and layout_path_jsx.exists():
                raise ValueError(
                    f"Duplicate layout definitions: {layout_path_tsx}, {layout_path_jsx}"
                )

            if layout_path_tsx.exists():
                layouts.append(layout_path_tsx)
            if layout_path_jsx.exists():
                layouts.append(layout_path_jsx)

            current_path = current_path.parent

        # Return the layouts in the order they should be rendered
        return list(reversed(layouts))

    def validate_page(self, *, page_path: Path, view_root_path: Path):
        # Validate that we're actually calling on a path file
        if page_path.name not in {"page.tsx", "page.jsx"}:
            raise ValueError(
                f"Invalid page path; view need to be specified in a `page.tsx` file: {page_path}"
            )

        # Validate that the page_path is within the view root. The following
        # logic assumes a hierarchical relationship between the two.
        if not page_path.is_relative_to(view_root_path):
            raise ValueError(
                f"Invalid page path, not relative to view root: {page_path} (root: {view_root_path})"
            )
