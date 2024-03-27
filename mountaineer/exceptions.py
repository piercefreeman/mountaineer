from typing import Any, Type, cast, get_type_hints

from fastapi import HTTPException
from pydantic import BaseModel, Field, create_model

# Keys that are used to initialize the HTTPException model
HTTPExceptionKeys = ["status_code", "detail", "headers"]


class APIExceptionInternalModelBase(BaseModel):
    """
    Superclass used for our synthetic internal errors. This class sets
    the required parameters and default model configuration for use in
    validating user inputs to APIException(**kwargs)

    """

    status_code: int
    detail: str
    headers: dict[str, str]

    model_config = {"extra": "forbid"}


class InternalModelMeta(type):
    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        cls._create_internal_model()
        return cls

    def _create_internal_model(cls):
        type_hints = get_type_hints(cls)

        fields = {
            key: (
                key_type,
                getattr(cls, key, Field(default_factory=lambda: None)),
            )
            for key, key_type in type_hints.items()
            if key not in ["InternalModel", "internal_model"]
        }
        cls.InternalModel = create_model(
            # Mirror the class name so our OpenAPI objects are as the user specifies
            # for their exception class
            cls.__name__,
            __base__=APIExceptionInternalModelBase,
            **cast(Any, fields),
        )
        cls.InternalModel.__module__ = cls.__module__

    def __call__(cls, *args, **kwargs):
        # Override the __call__ method to instantiate models like Pydantic does
        # Use the internal model for validation and instantiation
        internal_model = cls.InternalModel(**kwargs)
        instance = super().__call__(
            **{
                key: value
                for key, value in internal_model.model_dump().items()
                if key in HTTPExceptionKeys
            }
        )
        setattr(instance, "internal_model", internal_model)
        return instance


class APIException(HTTPException, metaclass=InternalModelMeta):
    """
    Base class for user defined APIExceptions that can be thrown
    in server actions and should provide some metadata back to
    the client caller.

    ```python
    class PostNotFound(APIException):
        status_code: int = 404
        detail: str = "The post was not found"
        post_id: int
        is_deleted: bool

    class MyController(ControllerBase):
        @passthrough
        def get_post(self, post_id: int) -> Post:
            post = self.post_service.get_post(post_id)
            if not post:
                raise PostNotFound(post_id=post_id, is_deleted=True)
            return post
    ```

    """

    status_code: int = 500
    detail: str = "A server error occurred"
    headers: dict[str, str] = Field(default_factory=dict)

    InternalModel: Type[APIExceptionInternalModelBase]
    internal_model: APIExceptionInternalModelBase

    # We can't synthetically create an API contract with the instance variables
    # (pydantic uses a plugin to get their IDE typehints)
    # Any issues with the input constructor will raise a runtime error
    # versus being statically checked
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
