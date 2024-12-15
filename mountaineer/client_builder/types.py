from abc import ABC, abstractmethod, abstractproperty
from types import UnionType
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Set,
    Tuple,
    Union,
    get_args,
    get_origin,
)


def is_union_type(type_: type) -> bool:
    """Check if a type is a Union type"""
    return get_origin(type_) is Union or isinstance(type_, UnionType)


def get_union_types(type_: type) -> list[type]:
    """Get the types from a Union type"""
    if not is_union_type(type_):
        raise ValueError(f"Expected Union type, got {type_}")
    return list(get_args(type_))


def is_none_type(field_type: Any):
    return field_type is None or field_type is type(None)


class TypeDefinition(ABC):
    """Base class for all type definitions"""

    @abstractproperty
    def children(self) -> list[Any]:
        """Return a list of all types this definition wraps"""
        raise NotImplementedError

    @abstractmethod
    def update_children(self, children: list[Any]):
        """Return a new instance with updated children"""
        raise NotImplementedError

    def __repr__(self):
        return f"{self.__class__.__name__}({', '.join(repr(child) for child in self.children)})"


class Or(TypeDefinition):
    """Represents a Union type"""

    types: tuple[Any, ...]

    def __init__(self, *types):
        self.types = types

    @property
    def children(self):
        return list(self.types)

    def update_children(self, children):
        self.types = tuple(children)


class ListOf(TypeDefinition):
    """Represents a List type"""

    type: Any

    def __init__(self, type):
        self.type = type

    @property
    def children(self):
        return [self.type]

    def update_children(self, children):
        assert len(children) == 1
        self.type = children[0]


class DictOf(TypeDefinition):
    """Represents a Dict type"""

    key_type: Any
    value_type: Any

    def __init__(self, key, value):
        self.key_type = key
        self.value_type = value

    @property
    def children(self):
        return [self.key_type, self.value_type]

    def update_children(self, children):
        assert len(children) == 2
        self.key_type = children[0]
        self.value_type = children[1]


class TupleOf(TypeDefinition):
    """Represents a Tuple type"""

    types: tuple[Any, ...]

    def __init__(self, *types):
        self.types = types

    @property
    def children(self):
        return list(self.types)

    def update_children(self, children):
        self.types = tuple(children)


class SetOf(TypeDefinition):
    """Represents a Set type"""

    type: Any

    def __init__(self, type_):
        self.type = type_

    @property
    def children(self):
        return [self.type]

    def update_children(self, children):
        self.types = tuple(children)


class LiteralOf(TypeDefinition):
    """Represents a Literal type"""

    values: list[Any]

    def __init__(self, *values):
        self.values = [value if not is_none_type(value) else None for value in values]
        self._validate_primitive_values(self.values)

    @staticmethod
    def _validate_primitive_values(values: List[Any]) -> None:
        """
        Ensures all values are primitive types (str, int, float, bool, None).
        Raises TypeError for non-primitive values.

        """
        for value in values:
            if not isinstance(value, (str, int, float, bool)) and value is not None:
                raise TypeError(
                    f"Literal values must be primitive types (str, int, float, bool, None). "
                    f"Got {type(value)} for value: {value}"
                )

    @property
    def children(self):
        return []

    def update_children(self, children):
        pass


class TypeParser:
    """
    Type parser that converts Python types into TypeDefinition instances
    """

    def parse_type(self, field_type: Any):
        """
        Convert any Python type into a TypeDefinition instance

        Args:
            field_type: Any Python type

        Returns:
            TypeDefinition: Corresponding TypeDefinition instance
        """
        # Handle None type
        if is_none_type(field_type):
            return type(None)

        # Handle unions
        if is_union_type(field_type):
            union_types = get_union_types(field_type)
            return Or(*[self.parse_type(arg) for arg in union_types])

        # Handle built-in collections
        origin_type = get_origin(field_type)
        if origin_type is not None:
            return self._parse_origin_type(field_type, origin_type)

        # Handle basic types
        return self._parse_basic_type(field_type)

    def _parse_origin_type(self, field_type: Any, origin_type: Any) -> TypeDefinition:
        """Parse types with origin (e.g., List[int], Dict[str, int])"""
        args = get_args(field_type)
        args = tuple(self.parse_type(arg) for arg in args)

        if origin_type in (list, List):
            return ListOf(type=args[0])

        if origin_type in (dict, Dict):
            return DictOf(key=args[0], value=args[1])

        if origin_type in (tuple, Tuple):
            return TupleOf(*args)

        if origin_type in (set, Set):
            return SetOf(args[0])

        if origin_type is Literal:
            return LiteralOf(*args)

        # For unknown origin types, wrap in Or
        raise ValueError(f"Unsupported origin type: {origin_type}")

    def _parse_basic_type(self, field_type: Any) -> Any:
        """Parse basic types without args"""
        if isinstance(field_type, type):
            if issubclass(field_type, (list, List)):
                return ListOf(Any)
            elif issubclass(field_type, (dict, Dict)):
                return DictOf(key=Any, value=Any)
            elif issubclass(field_type, (tuple, Tuple)):  # type: ignore
                return TupleOf(Any)
            elif issubclass(field_type, (set, Set)):
                return SetOf(Any)

        return field_type
