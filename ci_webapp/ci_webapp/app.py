from mountaineer.app import AppController
from mountaineer.js_compiler.postcss import PostCSSBundler
from mountaineer.render import LinkAttribute, Metadata

from ci_webapp.controllers.complex import ComplexController
from ci_webapp.controllers.detail import DetailController
from ci_webapp.controllers.home import HomeController
from ci_webapp.views import get_view_path

controller = AppController(
    view_root=get_view_path(""),
    global_metadata=Metadata(
        links=[LinkAttribute(rel="stylesheet", href="/static/app_main.css")]
    ),
    custom_builders=[
        PostCSSBundler(),
    ],
)
controller.register(HomeController())
controller.register(DetailController())
controller.register(ComplexController())
