from warnings import filterwarnings

import pytest


@pytest.fixture(autouse=True)
def ignore_httpx_deprecation_warnings():
    # Ignore httpx deprecation warnings until fastapi updates its internal test constructor
    # https://github.com/encode/httpx/blame/master/httpx/_client.py#L678
    filterwarnings("ignore", category=DeprecationWarning, module="httpx.*")
