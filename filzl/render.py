from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass
from pydantic.fields import FieldInfo, Field
from typing import Any, TYPE_CHECKING
from typing_extensions import dataclass_transform
from dataclasses import dataclass


# TODO: Fix unsafe_hash / remove it
@dataclass(unsafe_hash=True)
class FieldClassDefinition:
    key: str
    field_definition: FieldInfo


@dataclass_transform(kw_only_default=True, field_specifiers=(Field,))
class ReturnModelMetaclass(ModelMetaclass):
    if not TYPE_CHECKING:  # pragma: no branch
        # Following the lead of the pydantic superclass, we wrap with a non-TYPE_CHECKING
        # block: "otherwise mypy allows arbitrary attribute access""
        def __getattr__(self, key: str) -> Any:
            try:
                return super().__getattr__(key)
            except AttributeError:
                # Determine if this field is defined within the spec
                # If so, return it
                if key in self.model_fields:
                    return FieldClassDefinition(key, self.model_fields[key])
                raise


class RenderBase(BaseModel, metaclass=ReturnModelMetaclass):
    pass
