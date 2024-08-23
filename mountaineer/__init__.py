# Re-export some core dependencies from other packages that will
# be used across projects
from fastapi import Depends as Depends

from mountaineer.actions.passthrough_dec import passthrough as passthrough
from mountaineer.actions.sideeffect_dec import sideeffect as sideeffect
from mountaineer.app import AppController as AppController
from mountaineer.client_compiler.postcss import PostCSSBundler as PostCSSBundler
from mountaineer.config import ConfigBase as ConfigBase
from mountaineer.controller import ControllerBase as ControllerBase
from mountaineer.controller_layout import LayoutControllerBase as LayoutControllerBase
from mountaineer.dependencies import CoreDependencies as CoreDependencies
from mountaineer.exceptions import APIException as APIException
from mountaineer.paths import ManagedViewPath as ManagedViewPath
from mountaineer.render import (
    LinkAttribute as LinkAttribute,
    MetaAttribute as MetaAttribute,
    Metadata as Metadata,
    RenderBase as RenderBase,
    ScriptAttribute as ScriptAttribute,
    ThemeColorMeta as ThemeColorMeta,
    ViewportMeta as ViewportMeta,
)
