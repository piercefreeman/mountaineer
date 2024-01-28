### useServer()

_This is a rough specification for the useServer() API component. It walks through a simple case to help guide the implementation of the code template generator._

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

export const ServerContext = useContext(
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
