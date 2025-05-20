from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath
from mountaineer.ssr import find_tsconfig
from mountaineer.static import get_static_path

if TYPE_CHECKING:
    from mountaineer.graph.app_graph import ControllerDefinition


@dataclass(kw_only=True)
class DevCacheConfig:
    node_modules_path: ManagedViewPath
    live_reload_port: int


@dataclass(kw_only=True)
class ProdCacheConfig:
    pass


@dataclass(kw_only=True)
class ControllerCacheBase:
    cached_server_script: str
    cached_server_sourcemap: str | None = None


@dataclass(kw_only=True)
class ControllerDevCache(ControllerCacheBase):
    """
    Cache of the controller definition for the given controller.
    """

    cached_client_script: str
    cached_client_sourcemap: str | None = None

    @classmethod
    def resolve_dev_cache(
        cls,
        definition: "ControllerDefinition",
        config: DevCacheConfig,
    ) -> "ControllerDevCache":
        # Find tsconfig.json in the parent directories of the view paths
        view_paths = definition.get_hierarchy_view_paths()
        tsconfig_path = find_tsconfig(view_paths)

        LOGGER.debug(
            f"Compiling server-side bundle for {definition.controller.__class__.__name__}: {view_paths}"
        )
        (
            script_payloads,
            sourcemap_payloads,
        ) = mountaineer_rs.compile_independent_bundles(
            view_paths,
            str(config.node_modules_path.resolve().absolute()),
            "development",
            config.live_reload_port,
            str(get_static_path("live_reload.ts").resolve().absolute()),
            True,
            tsconfig_path,
        )
        cached_server_script = cast(str, script_payloads[0])
        cached_server_sourcemap = cast(str | None, sourcemap_payloads[0])

        LOGGER.debug(
            f"Compiling client-side bundle for {definition.controller.__class__.__name__}: {view_paths}"
        )
        script_payloads, _ = mountaineer_rs.compile_independent_bundles(
            view_paths,
            str(config.node_modules_path.resolve().absolute()),
            "development",
            config.live_reload_port,
            str(get_static_path("live_reload.ts").resolve().absolute()),
            False,
            tsconfig_path,
        )
        cached_client_script = cast(str, script_payloads[0])
        cached_client_sourcemap = cast(str | None, sourcemap_payloads[0])

        return ControllerDevCache(
            cached_server_script=cached_server_script,
            cached_server_sourcemap=cached_server_sourcemap,
            cached_client_script=cached_client_script,
            cached_client_sourcemap=cached_client_sourcemap,
        )


@dataclass(kw_only=True)
class ControllerProdCache(ControllerCacheBase):
    @classmethod
    def resolve_prod_cache(
        cls, definition: "ControllerDefinition", config: ProdCacheConfig
    ) -> "ControllerProdCache":
        if not definition.controller._ssr_path:
            raise ValueError(
                f"Controller {definition.controller} was not able to find its server-side script on disk. Make sure to run your `build` CLI before starting your webapp."
            )

        if not definition.controller._ssr_path.exists():
            raise ValueError(
                f"Controller {definition.controller} was not able to find its server-side script on disk. Make sure to run your `build` CLI before starting your webapp."
            )

        if not definition.controller._bundled_scripts:
            raise ValueError(
                f"Controller {definition.controller} was not able to find its scripts on disk. Make sure to run your `build` CLI before starting your webapp."
            )

        return ControllerProdCache(
            cached_server_script=definition.controller._ssr_path.read_text()
        )
