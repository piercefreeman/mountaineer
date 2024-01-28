import React, { useContext, useState, ReactNode } from 'react';
import type * as ControllerTypes from './models';

interface ServerState {
  HOME_CONTROLLER?: ControllerTypes.HOME_CONTROLLERHomeRender
}

export const ServerContext = useContext<{
  serverState: ServerState
  setServerState: (state: ServerState) => void
}>(undefined as any)

export const ServerProvider = ({ children }: { children: ReactNode }) => {
const [serverState, setServerState] = useState<ServerState>({
  HOME_CONTROLLER: GLOBAL_STATE[HOME_CONTROLLER]
});
return <ServerContext.Provider
serverState={serverState}
setServerState={setServerState}>
{children}</ServerContext.Provider>
};