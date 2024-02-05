# Error handling

Errors are a fundamental part of computer science, but nowhere is that more evident than when building websites. There are so many factors you don't have control over: client latency, malformed payloads, spiky server load, resource contention for the same user. The list goes on. Any one can bring a user experience to its knees.

All that to say - it's not a question of _if_ you'll see errors but _when_. filzl provides some handy utilities that make it a bit easier to handle the errors you may encounter in production.

## Client->Server exceptions

When client actions call server actions (either sideeffects or passthroughs), their browser needs to make an outgoing fetch request to your server. Your server can return an error to this payload for any reason: validation failures, unexpected state, or whatever.



## SSR timeouts

To render each page on the server side, we have to execute your view's Javascript in a V8 engine. This is the same Javascript interpreter that powers Chrome. As such, you have the full freedom to write any Javascript in your view declaration - loops, calculations, package calls, etc. As is the case with Turing-complete languages, with great power comes great responsibility.

These SSR requests can potentially take a long time. At the extreme, they could even clog up your server by infinite looping and never returning a value. We have a series of safeguards in place to help ensure SSR renders return quickly and keep your server able to chug through additional requests.

- Default, debug logging of the duration of each SSR page render.
- Logging if rendering takes longer than some interval so you can keep an eye on endpoints that are creeping up.
- Hard timeouts for rendering. So if something goes sideways and your server rendering, we'll terminate the server-side javascript executor for you and return an error to the client.

## SSR exceptions

Alongside timeouts, it's possible your view Javascript actually gets into an unrecoverable state and throws an exception during rendering. To help you debug this on the server side, we'll raise this error as a `filzl.ssr.V8RuntimeError` and log the stack trace that comes back from the V8 engine.

```bash
{"level": "ERROR", "name": "filzl.logging", "message": "Exception encountered in ComplexController rendering"}
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  File "/Users/piercefreeman/projects/filzl/filzl/ssr.py", line 37, in render_ssr
    render_result = filzl_rs.render_ssr(
                    ^^^^^^^^^^^^^^^^^^^^
...

 File "/Users/piercefreeman/projects/filzl/filzl/ssr.py", line 43, in render_ssr
   raise V8RuntimeError(e)
filzl.ssr.V8RuntimeError: Error calling function 'Index': Error: Example client error
Stack: Error: Example client error
   at Page (<anonymous>:12882:13)
   at renderWithHooks (<anonymous>:6333:26)
   at renderIndeterminateComponent (<anonymous>:6390:25)
   at renderElement (<anonymous>:6550:17)
   at renderNodeDestructiveImpl (<anonymous>:6655:19)
   at renderNodeDestructive (<anonymous>:6635:24)
   at renderIndeterminateComponent (<anonymous>:6430:17)
   at renderElement (<anonymous>:6550:17)
   at renderNodeDestructiveImpl (<anonymous>:6655:19)
   at renderNodeDestructive (<anonymous>:6635:24)
```
