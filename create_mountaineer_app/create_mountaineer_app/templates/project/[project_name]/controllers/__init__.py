{% if create_stub_files %}
from .home import HomeController # noqa: F401
from .detail import DetailController # noqa: F401
{% else %}
# Specify sub-controllers here
# Ex: from .home import HomeController
{% endif %}