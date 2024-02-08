from filzl.app import AppController
from filzl.js_compiler.postcss import PostCSSBundler
from filzl.render import LinkAttribute, Metadata

from {{project_name}}.controllers.detail import DetailController
from {{project_name}}.controllers.home import HomeController
from {{project_name}}.views import get_view_path

controller = AppController(
    view_root=get_view_path(""),
    {% if use_tailwind %}
    global_metadata=Metadata(
        links=[LinkAttribute(rel="stylesheet", href="/static/app_main.css")]
    ),
    custom_builders=[
        PostCSSBundler(),
    ],
    {% endif %}
)
controller.register(HomeController())
controller.register(DetailController())
