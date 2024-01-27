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


class MyRouteController(RouteController):
    # Unlike in next.js the post won't actually do anything, it's just to align conventions
    # OR maybe this should actually determine URL paths? Easier to layout templates in terms
    # of arbitrary paths than for them to be embedded in python itself.


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
        )

    @sideeffect
    def my_action_with_sideeffect(self, payload: MyInputPayload):
        pass

    def my_action_without_sideeffect(self):
        pass

    def other_action(self):
        # Maybe also provide the ability for side-effects to provide arbitrary data back that isn't
        # inscope of the render route itself?
        # What would this be? Credit card confirmation from Stripe, for instance?
        # Maybe @passthrough to indicate it's not actually resetting the server state (unlike side-effect)
        pass

if __name__ == "__main__":
    from pydantic import BaseModel
    from typing import Generic, TypeVar, Tuple, Type

    class MySpec(ReturnModel):
        testing: str
        testing2: int
        testing3: float  # Assuming you have a third field for demonstration

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
