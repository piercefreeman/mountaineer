"""
Define the initial spec for what we want our API to look like.

We assume that everything serialized is a pydantic model, since other things like ORM
objects can easily be converted with standard APIs.

"""
from pydantic import BaseModel
from pydantic._internal._model_construction import ModelMetaclass
from pydantic.fields import FieldInfo, Field
from typing import Callable, Any, Tuple, Union, TYPE_CHECKING
from typing_extensions import dataclass_transform
from dataclasses import dataclass
from functools import wraps

class APIRouter:
    def get(self, path: str):
        def wrapper(func):
            return func
        return wrapper

router = APIRouter()

# TODO: Fix unsafe_hash / remove it
@dataclass(unsafe_hash=True)
class FieldClassDefinition:
    key: str
    field_definition: FieldInfo


@dataclass_transform(kw_only_default=True, field_specifiers=(Field,))
class ReturnModelMetaclass(ModelMetaclass):
    # def __new__(
    #     mcs,
    #     cls_name: str,
    #     bases: tuple[type[Any], ...],
    #     namespace: dict[str, Any],
    #     __pydantic_generic_metadata__: PydanticGenericMetadata | None = None,
    #     __pydantic_reset_parent_namespace__: bool = True,
    #     _create_model_module: str | None = None,
    #     **kwargs: Any,
    # ) -> type:
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

class ReturnModel(BaseModel, metaclass=ReturnModelMetaclass):
    template_path: str

class OtherObject(BaseModel):
    object_variable: str

class MyResponse(ReturnModel):
    static_variable: str
    obj: OtherObject

class MyInputPayload(BaseModel):
    input_variable: str

#@router.get("/myroute")
#def route():
#    return MyResponse(
#        # How to get access to the request?
#        static_variable="hello",
#        obj=OtherObject(
#            object_variable="world",
#        ),
#        template_path="mytemplate.html",
#    )

# OR:

class RouteController:
    pass

class MyRouteController(RouteController):
    def render(
        self
        # Can inject dependencies here, like the request
        # It's just a normal FastAPI route
    ):
        return MyResponse(
            # TODO: Some way to flag these as only being calculated when the user requests a change
            # to this specific variable
            static_variable="hello",
            obj=OtherObject(
                object_variable="world",
            ),
            # Unlike in next.js the post won't actually do anything, it's just to align conventions
            # OR maybe this should actually determine URL paths? Easier to layout templates in terms
            # of arbitrary paths than for them to be embedded in python itself.
            template_path="/testing/[post_id]/mytemplate.tsx",
        )

    def my_action_with_sideeffect(self, payload: MyInputPayload):
        #return sideeffect(
        #   # This will throw by default in Pydantic, but maybe we allow it in our subclasses
        #    reload=[MyResponse.static_variable, ...],
        #)
        return None

    def my_action_without_sideeffect(self):
        # Logic, return None
        return None

    def other_value(self):
        # Maybe also provide the ability for side-effects to provide arbitrary data back that isn't
        # inscope of the render route itself?
        # What would this be? Credit card confirmation from Stripe, for instance?
        pass

if __name__ == "__main__":
    from pydantic import BaseModel
    from typing import Generic, TypeVar, Tuple, Type

    # Define the types for WrapperElement
    T = TypeVar('T')

    class MySpec(ReturnModel):
        testing: str
        testing2: int
        testing3: float  # Assuming you have a third field for demonstration

    # Define a generic WrapperElement class
    class WrapperElement(Generic[T]):
        def __init__(self, *elements: T):
            self.elements = elements

        def __repr__(self):
            return f"WrapperElement(elements={self.elements})"

    def sideeffect(*args, **kwargs):
        """
        :param: If provided, will ONLY reload these fields. By default will reload all fields. Otherwise, why
            specify a sideeffect at all?
        """
        def decorator_with_args(reload: Tuple[FieldClassDefinition, ...]):
            print("SPECIFIC RELOAD", reload)
            def wrapper(func: Callable):
                @wraps(func)
                def inner(*func_args, **func_kwargs):
                    return func(*func_args, **func_kwargs)
                return inner
            return wrapper

        if args and callable(args[0]):
            # It's used as @sideeffect without arguments
            func = args[0]
            return decorator_with_args(())(func)
        else:
            # It's used as @sideeffect(xyz=2) with arguments
            return decorator_with_args(*args, **kwargs)


    # Example usage
    #wrapper1 = WrapperElement(MySpec.testing, MySpec.testing2)
    #wrapper2 = WrapperElement(MySpec.testing, MySpec.testing2, MySpec.testing3)
    #wrapper3 = WrapperElement(MySpec.testing)
    print(MySpec)
    print(MySpec.model_fields)

    @sideeffect(reload=[MySpec.testing, MySpec.testing2])
    def testing():
        print("WHEE")

    @sideeffect
    def testing2():
        print("WHEE2")
    #def testing() -> WrapperElement[Union[MySpec.testing, MySpec.testing2]]:
    #    print("WHEE")

    print(testing())
    print(testing2())
    print(testing.__annotations__)
    print("VALUE", MySpec.testing)

    # Our framework will take care of this part
    controller = MyRouteController()
    controller.render()
