# Re-export some core dependencies from other packages that will
# be used across projects
from fastapi import Depends as Depends

from mountaineer.actions import passthrough as passthrough, sideeffect as sideeffect
from mountaineer.app import AppController as AppController
from mountaineer.config import ConfigBase as ConfigBase
from mountaineer.controller import ControllerBase as ControllerBase
from mountaineer.dependencies import CoreDependencies as CoreDependencies
from mountaineer.exceptions import APIException as APIException
from mountaineer.js_compiler.postcss import PostCSSBundler as PostCSSBundler
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
