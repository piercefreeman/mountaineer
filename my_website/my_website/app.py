from filzl.app import AppController
from filzl.client_builder.postcss import PostCSSBundler
from filzl.render import LinkAttribute, Metadata

from my_website.controllers.complex import ComplexController
from my_website.controllers.detail import DetailController
from my_website.controllers.home import HomeController
from my_website.views import get_view_path

controller = AppController(
    view_root=get_view_path(""),
    global_metadata=Metadata(
        links=[LinkAttribute(rel="stylesheet", href="/static/main.css")]
    ),
    custom_builders=[
        PostCSSBundler(),
    ],
)
controller.register(HomeController())
controller.register(DetailController())
controller.register(ComplexController())
