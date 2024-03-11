# Re-export some core dependencies from other packages that will
# be used across projects
from fastapi import Depends as Depends

from mountaineer.actions import passthrough as passthrough
from mountaineer.actions import sideeffect as sideeffect
from mountaineer.app import AppController as AppController
from mountaineer.config import ConfigBase as ConfigBase
from mountaineer.controller import ControllerBase as ControllerBase
from mountaineer.dependencies import CoreDependencies as CoreDependencies
from mountaineer.exceptions import APIException as APIException
from mountaineer.js_compiler.postcss import PostCSSBundler as PostCSSBundler
from mountaineer.paths import ManagedViewPath as ManagedViewPath
from mountaineer.render import (
    LinkAttribute as LinkAttribute,
)
from mountaineer.render import (
    MetaAttribute as MetaAttribute,
)
from mountaineer.render import (
    Metadata as Metadata,
)
from mountaineer.render import (
    RenderBase as RenderBase,
)
from mountaineer.render import (
    ScriptAttribute as ScriptAttribute,
)
from mountaineer.render import (
    ThemeColorMeta as ThemeColorMeta,
)
from mountaineer.render import (
    ViewportMeta as ViewportMeta,
)
