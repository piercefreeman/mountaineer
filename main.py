"""
Define the initial spec for what we want our API to look like.

We assume that everything serialized is a pydantic model, since other things like ORM
objects can easily be converted with standard APIs.

"""
from pydantic import BaseModel

class APIRouter:
    def get(self, path: str):
        def wrapper(func):
            return func
        return wrapper

router = APIRouter()

class ReturnModel(BaseModel):
    template_path: str

class OtherObject(BaseModel):
    object_variable: str

class MyResponse(ReturnModel):
    static_variable: str
    obj: OtherObject

@router.get("/myroute")
def route():
    return MyResponse(
        # How to get access to the request?
        static_variable="hello",
        obj=OtherObject(
            object_variable="world",
        ),
        template_path="mytemplate.html",
    )


# OR:

class MyRouteController(RouteController):
    def render(self):
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
        return sideeffect(
            # This will throw by default in Pydantic, but maybe we allow it in our subclasses
            reload=[MyResponse.static_variable, ...],
        )

    def my_action_without_sideeffect(self):
        # Logic, return None

    def other_value(self):
        # Maybe also provide the ability for side-effects to provide arbitrary data back that isn't
        # inscope of the render route itself?
        # What would this be? Credit card confirmation from Stripe, for instance?
        pass
