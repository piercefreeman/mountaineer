# filzl

filzl is a batteries-included MVC web framework. It uses Python for the backend and React for the interactive frontend. If you've used either of these languages before for web development, we think you'll be right at home.

## Design Goals

- Firstclass typehints for both the frontend and backend
- Trivially simple client<->server communication, data binding, and function calling
- Optimize for server rendering of components for better accessibility and SEO
- Avoid the need for a separate gateway API or Node.js server just to serve frontend clients
- Static analysis of templates for strong validation: link validity, data access, etc.

## Future Directions

- Offload more of the server logic to Rust
- AST parsing of the tsx files to determine which parts of the serverState they're actually using and mask accordingly
- Plugins for simple authentication, daemons, billing, etc.

## Typescript Generation

For easier development and static error checking for the frontend components, we automatically build the relevant client<->server bindings as typescript definitions.

1. We need to generate one for the return of the render() function
    - This model will represent the server payload returned by useServer()
2. We also need for each action endpoint, both the request and the response.
    - If the response is a full sideeffect, we will either use the same model as render()
    - If the response is a partial sideeffect, we will need to generate a subtype of the render() model
    - If the response is a passthrough, we will need to generate a new custom type

    The final payloads in general should look like:
    ```typescript
    {
      passthroughData,
      // Either full state, or partial state. If partial state, we can define inline.
      sideEffectData
    }
    ```
3. There should be a common _request() class that will be used for all of these sideeffect fetches internally. The implementations themselves will look more like:

    ```tsx
    public static createUserPost({
        requestBody,
    }: {
        requestBody: RegisterSchema;
    }): CancelablePromise<User> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/user/',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    ```

## Design TODOs:

- Global methods for getting the link to another page (should validate these links are actually valid at build-time)
- Conventions for naming controllers to automatically generate interface type names / global context state name that doens't conflict
    - No matter what encoding strategy we'll have to enforce no controller name conflicts on build.
- How to use a preprocessor like tailwind for the bundling?
- Values will passthrough EITHER if @passthrough is specified, or if an explicit fastapi.Response is provided. In this case the user is likely setting a cookie or other advanced metadata that we should include as-is.
- For V1, we probably want to specify the routes in the controller using FastAPI's syntax. In the future we could also automatically derive the mapping from the view's hierarchy on disk. We just have to make sure that the controller->view mapping is unique. We should probably validate this anywhere when we do the initial build.
- We should clearly support both async and sync rendering functions / actions.
- We can't assume that any functions located in a controller could be called by the client, since there might be helper functions, auth functions, or the like. Instead we can either:
    - Assume the user only wants to expose @sideeffect and @passthrough functions, leveraging @passthrough even for cases where no data gets returned.
    - Explicitly analyze the template at runtime to determine which functions are actually used, and only expose those. For IDE support we'd have to initially build all of the metafiles for all of the functions so they'd get typehinting support.
    -> We go with the first option since it's more explicit and avoids having to generate meaningfully different type definition files for IDE completion during development vs. production.

NOTE:
- We can also validate that all pages will be reachable by just loading the render function at runtime. This might have some unintended data mutation-side effects however so we should be careful / not do automatically.
    - What's the safest way to retrieve the render function template then? Perhaps at the controller instance variable level instead? That wouldn't let us switch the view template depending on the request though... But do we really want to do that? That might invalidate our assumption that we can just update the render() by client-side reloading the state payload.
    -> Decision: Force controller<->view mapping to be 1:1. We can enforce this right at the component level.
