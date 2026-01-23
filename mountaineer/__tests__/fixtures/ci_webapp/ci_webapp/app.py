from mountaineer import Mountaineer, LinkAttribute, Metadata
from mountaineer.client_compiler.postcss import PostCSSBundler

from ci_webapp.config import AppConfig
from ci_webapp.controllers.complex import ComplexController
from ci_webapp.controllers.detail import DetailController
from ci_webapp.controllers.home import HomeController
from ci_webapp.controllers.root_layout import RootLayoutController
from ci_webapp.controllers.stream import StreamController

mountaineer = Mountaineer(
    global_metadata=Metadata(
        links=[LinkAttribute(rel="stylesheet", href="/static/app_main.css")]
    ),
    custom_builders=[
        PostCSSBundler(),
    ],
    config=AppConfig(),
)
mountaineer.register(HomeController())
mountaineer.register(DetailController())
mountaineer.register(ComplexController())
mountaineer.register(StreamController())
mountaineer.register(RootLayoutController())
