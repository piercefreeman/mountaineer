from typing import Any, Type, cast, get_type_hints

from fastapi import HTTPException
from pydantic import BaseModel, Field, create_model


class APIExceptionInternalModelBase(BaseModel):
    status_code: int
    detail: str
    headers: dict[str, str]


class APIException(HTTPException):
    status_code: int = 500
    detail: str = "A server error occurred"
    headers: dict[str, str] = Field(default_factory=dict)

    InternalModel: Type[APIExceptionInternalModelBase]

    def __new__(cls, *args, **kwargs):
        cls._create_internal_model()
        return super().__new__(cls)

    @classmethod
    def _create_internal_model(cls):
        type_hints = get_type_hints(cls)

        fields = {
            key: (
                key_type,
                getattr(cls, key, None),
            )
            for key, key_type in type_hints.items()
        }

        cls.InternalModel = create_model(
            f"{cls.__name__}InternalModel",
            __base__=APIExceptionInternalModelBase,
            **cast(Any, fields),
        )

    def __init__(self, *args, **kwargs):
        # Initialize the internal model with provided kwargs
        self.internal_model = self.InternalModel(**kwargs)

        # Initialize HTTPException with base fields
        super().__init__(
            status_code=self.internal_model.status_code,
            detail=self.internal_model.detail,
            headers=self.internal_model.headers,
        )

        # Update instance attributes with values from internal_model
        # for direct access
        for field in self.internal_model.model_fields.keys():
            setattr(self, field, getattr(self.internal_model, field))
