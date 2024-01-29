from pathlib import Path

from pkg_resources import resource_filename


def get_static_path(asset_name: str) -> Path:
    return Path(resource_filename(__name__, asset_name))
