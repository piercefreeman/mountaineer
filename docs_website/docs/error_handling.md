# Error Handling

Errors are a fundamental part of computer science, but nowhere is that more evident than when building websites. There are so many factors you don't have control over: client latency, malformed payloads, spiky server load, resource contention for the same user. The list goes on. Any one can bring a user experience to its knees.

All that to say - it's not a question of _if_ you'll see errors but _when_. Mountaineer provides some handy utilities that make it a bit easier to handle the errors you may encounter in production.

## Client->Server exceptions

When client actions call server actions (either sideeffects or passthroughs), their browser needs to make an outgoing fetch request to your server. Your server can throw an error in response to this payload for any reason: validation failures, unexpected state, or just because some internal logic failed.

When your server returns an error, your async action will raise the relevant error. Let's say you have the following component that issues an invalid call to a server action:

```typescript
<button
  onClick={async () => {
    await serverState.increment_count({
      requestBody: {
        // @ts-ignore
        count: "invalid payload",
      },
    });
  }}
>
  Invalid Increment
</button>
```

When this button is clicked, it will send an `increment_count` action to the server. The server will validate the incoming payload with Pydantic, which will throw a [ValidationError](https://docs.pydantic.dev/latest/errors/validation_errors/) since it expects `count` to be an integer, not a string. The server will then respond with a 422 validation error, which will be passed back to the client and raised in the async function. You can catch this error with a try/catch block:

```typescript
import { HTTPValidationErrorException } from "./_server/actions";

...

<button
  className="rounded-md bg-blue-500 p-2 text-white"
  onClick={async () => {
    try {
      await serverState.increment_count({
        requestBody: {
          // @ts-ignore
          count: "invalid payload",
        },
      });
    } catch (error) {
      if (error instanceof HTTPValidationErrorException) {
        console.log(
          "Validation Error",
          error.body.detail?.[0].loc,
          error.body.detail?.[0].msg,
        );
      } else {
        throw error;
      }
    }
  }}
>
  Invalid Increment
</button>
```

Mountaineer will convert the error into a custom error class and expose it in `_server/actions` for you to import. This class helps you switch logic depending on the type of error that was raised. Using a class here also has the benefit of typeguarding your error handling, so you'll see IDE recommendations specific to that ValidationError.

You can find the error payload itself within `error.body`, which will be typehinted with all the metadata (if any) that the server is expected to return as part of this error code. In the above example, that looks like this:

```
Validation Error (2) ['body', 'count'] Input should be a valid integer, unable to parse string as an integer
```

Internally, we generate `HTTPValidationErrorException` as a subclass of FetchErrorBase. This provided the common error handling, while typehinting it for your specific API errors.

```typescript title="_server/actions.ts"
class HTTPValidationErrorException extends FetchErrorBase<HTTPValidationError> {}
```

!!! tip

    For more information on error typehinting and custom handling, see the FastAPI [documentation](https://fastapi.tiangolo.com/tutorial/handling-errors/).

## Custom Errors

A 422 ValidationError is a special error that is included in every action, because your function signature is verified every time a client sends a new payload to your server. To implement a custom error that is specific to your application, you can subclass `APIException`:

```python
from mountaineer.exceptions import APIException

class LoginInvalid(APIException):
    status_code = 401
    invalid_reason: str

class LoginController(ControllerBase):
    ...

    @passthrough(exception_models=[LoginInvalid])
    def login(self, login_payload: LoginRequest):
        raise LoginInvalid(invalid_reason="Login not implemented")
```

Provide all the exceptions that your function may throw to `@passthrough(exception_models=[])`. The `@sideeffect` decorator accepts the same argument.

When specified like this, Mountaineer turns your exception into a client-side exception just like `HTTPValidationErrorException`. You can now use it in the same way.

## SSR timeouts

To render each page on the server side, we have to execute your view's Javascript in a V8 engine. This is the same Javascript interpreter that powers Chrome. As such, you have the full freedom to write any Javascript in your view that will help you render your page - loops, calculations, package calls, etc.

As is the case with Turing-complete languages, with great power comes great responsibility.

These SSR requests can potentially take a long time. At the extreme, they could even clog up your server by infinite looping and never returning a value. We have a series of safeguards in place to help ensure SSR renders return quickly and keep your server able to chug through additional requests.

- Debug logging of the duration of each SSR page render, for use in development.
- Warning logs if rendering takes longer than some interval so you can keep an eye on endpoints that might need some optimization.
- Hard timeouts for rendering. If something goes sideways and your server rendering takes longer a maximum threshold, we'll terminate the server-side Javascript executor for you and return an error to the client.

## SSR exceptions

Alongside timeouts, it's possible your view's Javascript actually gets into an unrecoverable state and throws an exception during rendering. To help you debug this on the server side, we'll raise this error as a `mountaineer.ssr.V8RuntimeError` and log the stack trace that comes back from the V8 engine.

The paths reported in the stack trace are found from the sourcemap that's created alongside the compiled SSR files. These should point to the files in your view directory that have produced that exception.

```bash
{"level": "ERROR", "name": "mountaineer.logging", "message": "Exception encountered in ComplexController rendering"}
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  File "/Users/piercefreeman/projects/mountaineer/mountaineer/ssr.py", line 37, in render_ssr
    render_result = mountaineer_rs.render_ssr(
                    ^^^^^^^^^^^^^^^^^^^^
...

 File "/Users/piercefreeman/projects/mountaineer/mountaineer/ssr.py", line 43, in render_ssr
   raise V8RuntimeError(e)
mountaineer.ssr.V8RuntimeError: Error calling function 'Index': Error: Example client error
Stack: Error: Example client error
    at Page (./my_website/views/app/complex/page.tsx:41:10)
    at renderWithHooks (./my_website/views/node_modules/react-dom/cjs/react-dom-server-legacy.browser.development.js:5660:15)
    at renderIndeterminateComponent (./my_website/views/node_modules/react-dom/cjs/react-dom-server-legacy.browser.development.js:5733:14)
    at renderElement (<anonymous>:6537:17)
    at renderNodeDestructiveImpl (<anonymous>:6642:19)
    at renderNodeDestructive (./my_website/views/node_modules/react-dom/cjs/react-dom-server-legacy.browser.development.js:6078:13)
    at renderIndeterminateComponent (<anonymous>:6417:17)
    at renderElement (<anonymous>:6537:17)
    at renderNodeDestructiveImpl (<anonymous>:6642:19)
    at renderNodeDestructive (./my_website/views/node_modules/react-dom/cjs/react-dom-server-legacy.browser.development.js:6078:13)
```
