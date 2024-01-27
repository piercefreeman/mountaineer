# filzl

## Design TODOs:

- Global methods for getting the link to another page (should validate these links are actually valid at build-time)
- Conventions for naming controllers to automatically generate interface type names / global context state name that doens't conflict
    - Use camel case? Either way we'll have to enforce no controller name conflicts on build.
- How to use a preprocessor like tailwind for the bundling?
- Values will passthrough EITHER if @passthrough is specified, or if an explicit fastapi.Response is provided. In this case the user is likely setting a cookie or other advanced metadata that we should include as-is.
- For V1, we probably want to specify the routes in the controller using FastAPI's syntax. In the future we could also automatically derive the mapping from the view's hierarchy on disk. We just have to make sure that the controller->view mapping is unique. We should probably validate this anywhere when we do the initial build.

NOTE:
- We can also validate that all pages will be reachable by just loading the render function at runtime. This might have some unintended data mutation-side effects however so we should be careful / not do automatically.
    - What's the safest way to retrieve the render function template then? Perhaps at the controller instance variable level instead? That wouldn't let us switch the view template depending on the request though... But do we really want to do that? That might invalidate our assumption that we can just update the render() by client-side reloading the state payload.
    -> Decision: Force controller<->view mapping to be 1:1. We can enforce this right at the component level.
