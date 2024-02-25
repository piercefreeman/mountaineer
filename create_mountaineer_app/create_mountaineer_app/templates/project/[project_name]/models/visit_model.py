from mountaineer.database import SQLModel, Field

class VisitModel(SQLModel, table=True):
    id: int = Field(primary_key=True)
    ip_address: str
