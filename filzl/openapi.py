from typing import TYPE_CHECKING

from fastapi.openapi.utils import get_openapi

if TYPE_CHECKING:
    from filzl.app import AppController


def openapi_with_exceptions(app: AppController):
    """
    Bundle custom user exceptions in the OpenAPI schema. By default
    endpoints just include the 422 Validation Error, but this allows
    for custom derived user methods.

    """
    get_openapi(title=app.name, version=app.version, routes=app.app.routes)
