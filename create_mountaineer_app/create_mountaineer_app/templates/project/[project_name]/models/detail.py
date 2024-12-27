{% if create_stub_files %}
from iceaxe import TableBase, Field

class DetailItem(TableBase):
    id: int | None = Field(default=None, primary_key=True)
    description: str
{% endif %}