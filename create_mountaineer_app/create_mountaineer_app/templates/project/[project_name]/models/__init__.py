{% if create_stub_files %}
from .detail import DetailItem # noqa: F401
{% else %}
# Specify sub-models here
# Ex: from .detail import DetailItem
{% endif %}