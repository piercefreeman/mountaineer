{% if create_stub_files %}
from mountaineer.database import SQLModel, Field

class DetailItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    description: str
{% endif %}