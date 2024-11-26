from pydantic import BaseModel


class BuildMetadata(BaseModel):
    """
    Metadata added during compile_time that should be maintained in the
    bundle for production hosting.

    """

    static_artifact_shas: dict[str, str]
