# Client Actions

Conventionally, server mutations that affect a page state are a bit of a hassle. You need to keep track of modified attributes, issue an API call, then reload or merge them into the current page. All of this to mostly just update the state that the original page was initialized with in the first place.

Actions are a way to simplify this process. They allow you to define server-side mutations that can be called from the client as if they're regular Javascript functions. Their request and response payloads are typehinted so you can statically verify their behavior.

## Action Types

Anytime clients need to modify the server state, we denote these requests as "actions". Internally, they're just POST requests that are sent to the server. There's no black magic to this syntax. You can inspect them all in your browser's console as regular JSON.

Your choice of action type depends on how you want to update _client_ data after your _server_ action has been executed.

**@sideeffect:** Update the server data that initialized the client view. Sideeffects are also passthroughs, by definition, so they can pass back arbitrary data that is outside of the scope of the render() data payload.

**@passthrough:** Expose an action to the client caller but don't update the server data once the action has been completed.

## Side Effect

Side-effects work as if you have reloaded the page. They update the server state and then push the updated state back to the client. They will call a fully fresh `render()` on the server so you can provide the latest data state to the client. However, unlike a true refresh on the client side, there's no actual browser refresh that is performed. This allows you to receive the updated data definition and keep the rest of your variables saved in local state.

`@sideeffect` can either be called with default behavior or customized via decorator arguments:

```python
# no parameters, refresh all state
@sideeffect
def increment_count(self):
    self.global_count += 1
```

```python
@sideeffect(
    # only refresh the current_count variable
    reload=(CountRender.current_count,)
)
def increment_count(self):
    self.global_count += 1
```

```python
@sideeffect(
    # execute a sideeffect and then return additional data from a custom data model
    response_model=CustomDataModel
)
def increment_count(self):
    self.global_count += 1
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

## Passthrough

Passthrough is conceptually much simpler, since it doesn't perform any server->client data syncs once it's finished. Instead, it provides a simple decorator that optionally accepts a ResponseModel:

```python
# no parameters, no response model
@passthrough
def server_action(self):
    pass
```

```python
@passthrough(
    # execute a passthrough and then return additional data from a custom data model
    response_model=CustomDataModel
)
def server_action(self):
    pass
```

Like passthrough values in sideeffects, you can access it on the client side like:

```typescript
const response = await serverState.server_action({});
console.log(response.passthrough);
```

## Action Definitions

When defining your action functions themselves in your controller, we support typehinting via:

- Query parameters
- Pydantic models for JSON payloads
- Dependency injection via `fastapi.Depends`

We also support both sync and async functions. A common sideeffect pattern might look like this:

```python
from fastapi import Depends
from my_website.models import User

class IncrementCountRequest:
    count: int

@sideeffect
async def increment_count(
    self,
    payload: IncrementCountRequest,
    query_param: int,
    user: User = Depends(get_current_user)
):
    self.global_count += payload.count
```

> [!CAUTION]
> Actions are publicly exposed to the Internet by default. It's up to you to secure them with authentication if they should only be accessible by a certain portion of your userbase.
