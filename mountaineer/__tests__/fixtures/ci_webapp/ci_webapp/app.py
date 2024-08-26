from mountaineer import AppController, LinkAttribute, Metadata
from mountaineer.client_compiler.postcss import PostCSSBundler

from ci_webapp.config import AppConfig
from ci_webapp.controllers.complex import ComplexController
from ci_webapp.controllers.detail import DetailController
from ci_webapp.controllers.home import HomeController
from ci_webapp.controllers.root_layout import RootLayoutController
from ci_webapp.controllers.stream import StreamController

controller = AppController(
    global_metadata=Metadata(
        links=[LinkAttribute(rel="stylesheet", href="/static/app_main.css")]
    ),
    custom_builders=[
        PostCSSBundler(),
    ],
    config=AppConfig(),
)
controller.register(HomeController())
controller.register(DetailController())
controller.register(ComplexController())
controller.register(StreamController())
controller.register(RootLayoutController())
