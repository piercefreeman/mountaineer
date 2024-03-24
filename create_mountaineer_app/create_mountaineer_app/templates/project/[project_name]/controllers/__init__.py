{% if create_stub_files %}
from .home import HomeController as HomeController
from .detail import DetailController as DetailController
{% else %}
# Specify sub-controllers here
# Ex: from .home import HomeController
{% endif %}