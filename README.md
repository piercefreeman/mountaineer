# filzl

filzl is a batteries-included MVC web framework. It uses Python for the backend and React for the interactive frontend. If you've used either of these languages before for web development, we hope you'll be right at home.

## Design Goals

- Firstclass typehints for both the frontend and backend
- Trivially simple client<->server communication, data binding, and function calling
- Optimize for server rendering of components for better accessibility and SEO
- Avoid the need for a separate frontend gateway, server
- Static analysis of templates for strong validation of link validity

## Future Directions

- Offload more of the server logic to Rust
- AST parsing of the tsx files to determine which parts of the serverState they're actually using and mask accordingly
- Plugins for simple authentication, billing, etc.

## Typescript Generation

For easier development and static error checking for the frontend components, we automatically build the relevant client<->server bindings as typescript definitions.

1. We need to generate one for the return of the render() function
    - This model will represent the server payload returned by useServer()
2. We also need for each action endpoint, both the request and the response.
    - If the response is a full sideeffect, we will either use the same model as render()
    - If the response is a partial sideeffect, we will need to generate a subtype of the render() model
    - If the response is a passthrough, we will need to generate a new custom type

    The final payloads in general should look like:
    ```json
    {
    passthroughData,
    sideEffectData: // Either full state, or partial state. If partial state define inline.
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

### Some thoughts on useServer()

Since the useServer elements will called in both the react component and by our sideeffect API components, its clear that we will need some global state to handle this coordination. The most standard way in React these days is to wrap the whole application in a `ContextProvider`, and set the content as part of the provider state.

Since we only want to wrap one of these global context providers, we'll need to have a slot for every controller so we can return the correct sub-field. We can draw on the Next.js convention of using a layout typescript page:

```tsx /views/app/layout.tsx
import {ServerProvider} from '_server';

const Layout = ({children} : {children: React.ReactNode) => {
    return (
        <ServerProvider>
        {children}
        </ServerProvider>
    )
}
export default Layout;
```

```ts /views/_server/serverContext.ts
//
// Logic shared between views so located within the global namespace and
// not in the /app subdirectory
//

import { useContext, useState } from 'react';

interface ServerState {
    CONTROLLER_1_STATE?: Controller1State,
    CONTROLLER_2_STATE?: Controller2State,
}

export const ServerContext = React.useContext(
  {
    serverState: ServerState,
    setServerState: (state: ServerState) => void,
  }
);

export const ServerProvider = ({children}) => {
  const [serverState, setServerState] = useState<ServerState>({
      // GLOBAL_STATE will be dynamically injected by the server build process
      CONTROLLER_1_STATE: GLOBAL_STATE["CONTROLLER_1_STATE""],
      CONTROLLER_2_STATE: GLOBAL_STATE["CONTROLLER_2_STATE"],
  });

  return (
    <ServerContext.Provider serverState={serverState} setServerState={setServerState}>
      {children}
    </ServerContext.Provider>
  )
}
```

```tsx /views/app/home.tsx
import { useServer } from '_server/serverContext';
//
// This file should inherit the global context provider from layout.tsx
//

const Home = () => {
  const serverState = useServer();

  return (
    <div>
      <h1>Home</h1>
      <p>Hello {serverState.first_name}</p>
      <p>Past views: {serverState.past_views}</p>
      <button onClick={
        () => {
          serverState.incrementPastViews();
        }
      }></button>
    </div>
  )
  {}
}
export default Home;
```

```tsx /views/app/_server/useServer.ts
//
// This file just returns the controller that is used in the current page.
// The rest of the controllers are expected to be undefined based on the current state.
//
import { ServerContext } from '/_server';
import { incrementPastViews } from './actions.ts';

const useServer = () => {
  const { serverState } = useContext(ServerContext);
  return {
    ...serverState["CONTROLLER_1_STATE"],
    incrementPastViews,
  }
}
```

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
