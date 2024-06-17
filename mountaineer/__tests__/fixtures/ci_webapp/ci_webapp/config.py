from mountaineer.config import ConfigBase


class AppConfig(ConfigBase):
    PACKAGE: str | None = "ci_webapp"
