from mountaineer.app import AppController
from mountaineer.render import LinkAttribute, Metadata

{% if create_stub_files %}
from {{project_name}}.controllers.detail import DetailController
from {{project_name}}.controllers.home import HomeController
{% endif %}
from {{project_name}}.config import AppConfig

controller = AppController(
    config=AppConfig(),  # type: ignore
    global_metadata=Metadata(
        links=[LinkAttribute(rel="stylesheet", href="/static/app_main.css")]
    ),
)

{% if create_stub_files %}
controller.register(HomeController())
controller.register(DetailController())
{% endif %}
