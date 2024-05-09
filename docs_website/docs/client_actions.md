# Client Actions

Conventionally, server mutations that affect a page state are a bit of a hassle. You need to keep track of modified attributes, issue an API call, then reload or merge them into the current page. All of this to mostly just update the state that the original page was initialized with in the first place.

Actions are a way to simplify this process. They allow you to define server-side mutations that can be called from the client as if they're regular Javascript functions. Their request and response payloads are typehinted so you can statically verify their behavior.

## Action Types

Anytime clients need to modify the server state, we denote these requests as "actions". Internally, they're just POST requests that are sent to the server. There's no black magic to this syntax. You can inspect them all in your browser's console as regular JSON.

Your choice of action type depends on how you want to update _client_ data after your _server_ action has been executed.

**@sideeffect:** Update the server data that initialized the client view. Sideeffects are also passthroughs, by definition, so they can pass back arbitrary data that is outside of the scope of the render() data payload. Use a sideeffect whenever the client modifies some data that lives on the server.

**@passthrough:** Expose an action to the client caller but don't update the server data once the action has been completed. Use a passthrough whenever you need to fetch additional data from the server, or the mutation on the server doesn't affect the local frontend state.

## Side Effect

Side-effects work as if you have reloaded the page. They update the server state and then push the updated state back to the client. They will call a fully fresh `render()` on the server so you can provide the latest data state to the client. However, unlike a true refresh on the client side, there's no actual browser refresh that is performed. This allows you to receive the updated data definition and keep the rest of your variables saved in local state.

`@sideeffect` can either be called with default behavior or customized via decorator arguments:

```python
# no parameters, refresh all state
@sideeffect
def increment_count(self) -> None:
    self.global_count += 1
```

```python
@sideeffect(
    # only push the updated current_count variable to the client
    reload=(CountRender.current_count,)
)
def increment_count(self) -> None:
    self.global_count += 1
```

```python
# execute a sideeffect and then return additional data from a custom data model
@sideeffect
def increment_count(self) -> CustomDataModel:
    self.global_count += 1
    ...
    return CustomDataModel(...)
```

Keyword arguments can be chained as you expect to customize the sideeffect behavior.

You call the sideeffect from the client through the serverState variable:

```typescript
const response = await serverState.increment_count({
  requestBody: {
    count: 5,
  },
});
```

You can also manually inspect the sideeffect payload by accessing `response.sideeffect`.

If the action has a passthrough, it will be supplied in `response.passthrough`. Otherwise it will be undefined.

### Experimental Render Reloader

!!! warning

    This feature is experimental and only supports relatively simple render() function implementations. If you use it for a more complicated render() function and it doesn't work as expected, report a bug to improve the test coverage.

Render functions sometimes have heavy logic overhead: they need to fetch multiple objects from the database, do some roll-up computation, etc. If you're issuing a sideeffect that only affects a small portion of the initial data, this is wasted computation.

Passing a `reload` filter to `sideeffect` prevents this redundant data from being sent to the frontend. But this feature only saves bandwidth; it doesn't actually prevent the server from doing the computation in the first place. This is where the `experimental_render_reload` comes in.

When this flag is set to `True`, Mountaineer will inspect the AST ([Abstract Syntax Tree](https://en.wikipedia.org/wiki/Abstract_syntax_tree)) of your render function. It creates a new synthetic render function that only does the computation required to calculate the `reload` parameters. If some intensive compute isn't required for your sideeffect, it will be ignored.

We compile this function into the Python runtime so it runs with the same performance as if you had implemented an alternative `render()` function yourself. Depending on your full render function complexity, this can lead to significant performance improvements.

Let's consider the following render function:

```python
def render(
    self,
    query_id: int,
) -> ExampleRenderModel:
    a = calculate_primes(10000)
    b = calculate_primes(1000000)
    return ExampleRenderModel(
        value_a=f"Hello {a}",
        value_b=f"World {b}",
    )

@sideeffect(
    reload=(ExampleRenderModel.value_a,),
    experimental_render_reload=use_experimental,
)
def call_sideeffect(self, payload: dict) -> None:
    pass
```

Benchmarked on a Macbook M1, calling this initial render will perform ~1.84s of compute. It results in:

```json
{
  "value_a": "Hello 1229",
  "value_b": "Hello 78498"
}
```

When `call_sideeffect` is called with `experimental_render_reload=True`, the compute only takes `0.010s`. It results in:

```json
{
  "value_a": "Hello 1229"
}
```

## Passthrough

Passthrough is conceptually much simpler, since it doesn't perform any server->client data syncs once it's finished. Instead, it provides a simple decorator that optionally accepts a ResponseModel:

```python
# no parameters, no response model
@passthrough
def server_action(self) -> None:
    pass
```

```python
# execute a passthrough and then return additional data from a custom data model
@passthrough
def server_action(self) -> CustomDataModel:
    pass
```

Like passthrough values in sideeffects, you can access it on the client side like:

```typescript
const response = await serverState.server_action({});
console.log(response.passthrough);
```

### Server Events

[Server-event](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events) streams are a useful paradigm in webapp design, and increasing utilized to provide realtime Server->Client data for use in user notifications, CI feedback, and model inference.

Mountaineer supports these natively on the server and client side. Simply decorate your response_model with a `typing.AsyncIterator` annotation and implement an async generator like you normally do:

```python
from typing import AsyncIterator
from mountaineer import passthrough, ControllerBase
from pydantic import BaseModel

class MyMetadata(BaseModel):
    state: int

class MyController(ControllerBase):
    ...

    @passthrough
    async def stream_metadata(self) -> AsyncIterator[MyMetadata]:
        yield MyMetadata(state=1)
        await asyncio.sleep(10)
        yield MyMetadata(state=2)
```

For the time being we only support server-events in `@passthrough` functions, not `@sideeffect`. It's ill-defined whether we should re-render() content every yield or when the iterator has finished. Yielding in passthrough makes it clear that you just want to stream the yielded value to the client.

In your frontend, you can iterate over these responses with an async generator loop. Each response object will be parsed into your typed schema for you, so you can see typehints like you would for any regular Mountaineer action.

```typescript
import React, { useState, useEffect } from "react";

const Page = () => {
  const [currentState, setCurrentState] = useState(-1);

  useEffect(() => {
      const runStream = async () => {
        const responseStream = await serverState.stream_metadata({});
        for await (const response of responseStream) {
          setCurrentState(response.passthrough.state);
        }
      };
      runStream();
    }, []);

  return <div>{currentState}</div>;
}
```

You'll see the first event state `1` for 10 seconds, then it will update to `2`.

## Action Definitions

When defining your action functions themselves in your controller, we support typehinting via:

- Query parameters
- Pydantic models for JSON payloads
- Dependency injection via `fastapi.Depends`

We also support both sync and async functions. Sync functions will be spawned into a thread pool by default - which processes them in parallel but can tax system resources with GIL locking. Where possible, use async functions with libraries that support await constructs.

A common sideeffect pattern might look like this:

```python
from mountaineer import ControllerBase, Depends
from my_website.models import User
from my_website.deps import get_current_user

class IncrementCountRequest:
    count: int

class MyController(ControllerBase):
    def __init__(self):
        super().__init__()
        self.global_count = 0

    @sideeffect
    async def increment_count(
        self,
        payload: IncrementCountRequest,
        query_param: int,
        user: User = Depends(get_current_user)
    ) -> None:
        self.global_count += payload.count
```

!!! warning

    Actions are publicly exposed to the Internet by default. It's up to you to secure them with authentication if they should only be accessible by a certain portion of your userbase.
