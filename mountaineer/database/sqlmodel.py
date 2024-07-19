from typing import (
    AbstractSet,
    Any,
    Dict,
    Mapping,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
    cast,
)

from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass
from pydantic_core import (
    PydanticUndefined as Undefined,
    PydanticUndefinedType as UndefinedType,
)
from sqlalchemy import Column
from sqlmodel._compat import (
    finish_init,
    post_init_field_info,
    sqlmodel_init,
)
from sqlmodel.main import (
    FieldInfo,
    NoArgAnyCallable,
    SQLModel as SQLModelBase,
    SQLModelMetaclass as SQLModelMetaclassBase,
)
from typing_extensions import dataclass_transform


def Field(
    default: Any = Undefined,
    *,
    default_factory: Optional[NoArgAnyCallable] = None,
    alias: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    exclude: Union[
        AbstractSet[Union[int, str]], Mapping[Union[int, str], Any], Any
    ] = None,
    include: Union[
        AbstractSet[Union[int, str]], Mapping[Union[int, str], Any], Any
    ] = None,
    const: Optional[bool] = None,
    gt: Optional[float] = None,
    ge: Optional[float] = None,
    lt: Optional[float] = None,
    le: Optional[float] = None,
    multiple_of: Optional[float] = None,
    max_digits: Optional[int] = None,
    decimal_places: Optional[int] = None,
    min_items: Optional[int] = None,
    max_items: Optional[int] = None,
    unique_items: Optional[bool] = None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    allow_mutation: bool = True,
    regex: Optional[str] = None,
    discriminator: Optional[str] = None,
    repr: bool = True,
    primary_key: Union[bool, UndefinedType] = Undefined,
    foreign_key: Any = Undefined,
    unique: Union[bool, UndefinedType] = Undefined,
    nullable: Union[bool, UndefinedType] = Undefined,
    index: Union[bool, UndefinedType] = Undefined,
    sa_type: Union[Type[Any], Any, UndefinedType] = Undefined,
    sa_column: Union[Column, UndefinedType] = Undefined,  # type: ignore
    sa_column_args: Union[Sequence[Any], UndefinedType] = Undefined,
    sa_column_kwargs: Union[Mapping[str, Any], UndefinedType] = Undefined,
    schema_extra: Optional[dict[str, Any]] = None,
) -> Any:
    """
    Allow instantiated `sa_type` to be used. This permits DateTime(timezone=True) instead
    of just passing a vanilla DateTime. Since these are passed through directly to the column
    syntax this is the same as a regular column declaration:

    https://github.com/tiangolo/sqlmodel/blob/6b562358fc1e857dd1ce4b8b23a9f68c0337430d/sqlmodel/main.py#L561

    Original: https://github.com/tiangolo/sqlmodel/blob/6b562358fc1e857dd1ce4b8b23a9f68c0337430d/sqlmodel/main.py

    """
    current_schema_extra = schema_extra or {}
    field_info = FieldInfo(
        default,
        default_factory=default_factory,
        alias=alias,
        title=title,
        description=description,
        exclude=exclude,
        include=include,
        const=const,
        gt=gt,
        ge=ge,
        lt=lt,
        le=le,
        multiple_of=multiple_of,
        max_digits=max_digits,
        decimal_places=decimal_places,
        min_items=min_items,
        max_items=max_items,
        unique_items=unique_items,
        min_length=min_length,
        max_length=max_length,
        allow_mutation=allow_mutation,
        regex=regex,
        discriminator=discriminator,
        repr=repr,
        primary_key=primary_key,
        foreign_key=foreign_key,
        unique=unique,
        nullable=nullable,
        index=index,
        sa_type=sa_type,
        sa_column=sa_column,
        sa_column_args=sa_column_args,
        sa_column_kwargs=sa_column_kwargs,
        **current_schema_extra,
    )
    post_init_field_info(field_info)
    return field_info


@dataclass_transform(kw_only_default=True, field_specifiers=(Field, FieldInfo))
class GenericSQLModelMetaclass(SQLModelMetaclassBase):
    def __new__(
        cls,
        name: str,
        bases: tuple[Type[Any], ...],
        class_dict: Dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        """
        Unlike the base SQLModel metaclass, we first fully instantiate the pydantic
        model before transfering the fields to SQLAlchemy. Pydantic V2 has helpful hooks
        within metadata construction that fullfill generic definitions that will be missed
        if we try to naively inspect the type annotations.

        """
        # SQLModel by default won't inherit FieldInfo definitions from parent classes, which is
        # unideal since we want to set it once in a parent class and pass through these values
        # into the children
        # Traverse the base classes to find their Field definitions. We can't grab these
        # directly from the pydantic model, since we want the raw SQLModel attributes
        # instead of the regular pydantic Fields
        parent_field_infos: dict[str, FieldInfo] = {}
        for base in reversed(bases):  # Reverse to ensure correct order of precedence
            if hasattr(base, "_explicit_fieldinfo"):
                parent_field_infos = {**parent_field_infos, **base._explicit_fieldinfo}

        self_field_infos = {
            key: value for key, value in class_dict.items() if not key.startswith("__")
        }

        class_dict = {
            **parent_field_infos,
            **class_dict,
        }

        pydantic_model = cls._validate_pydantic_model(name, bases, class_dict, **kwargs)
        pydantic_annotations = {
            key: field.annotation for key, field in pydantic_model.model_fields.items()
        }

        # Override with the parsed annotations that are extracted from Pydantic
        # This helps typehint the SQLModel class with the correct, resolved types
        class_dict["__annotations__"] = {
            **class_dict.get("__annotations__", {}),
            **pydantic_annotations,
        }

        cls = super().__new__(cls, name, bases, class_dict, **kwargs)

        cls._original_model = pydantic_model
        cls._explicit_fieldinfo = {
            **parent_field_infos,
            **self_field_infos,
        }

        return cls

    @classmethod
    def _validate_pydantic_model(
        cls,
        name: str,
        bases: tuple[Type[Any], ...],
        class_dict: dict[str, Any],
        **kwargs,
    ):
        """
        Given this class declaration, build up a Pydantic model with the type annotation hierarchy
        from base classes. This will resolve the TypeVars and other generic types that are not
        otherwise handled by SQLModel.

        """
        pydantic_bases = [
            base._original_model for base in bases if hasattr(base, "_original_model")
        ]
        parent_resolved_fields = {
            key: value.annotation
            for model in pydantic_bases
            for key, value in model.model_fields.items()
            # Don't pass through TypeVars, we only want to pass concrete types
            if not isinstance(value, TypeVar)
        }
        pydantic_class_dict = {
            **class_dict,
            "__annotations__": {
                **parent_resolved_fields,
                # Allow overrides for this subclass
                **class_dict.get("__annotations__", {}),
            },
        }

        return cast(
            BaseModel,
            ModelMetaclass.__new__(
                ModelMetaclass,
                name,
                (tuple(pydantic_bases) or (BaseModel,)),
                pydantic_class_dict,
                **{key: value for key, value in kwargs.items() if key not in {"table"}},
            ),
        )


class SQLModel(SQLModelBase, metaclass=GenericSQLModelMetaclass):
    def __init__(self, **data: Any):
        if hasattr(self, "_original_model"):
            self._original_model(**data)  # type: ignore
        if finish_init.get():
            sqlmodel_init(self=self, data=data)
