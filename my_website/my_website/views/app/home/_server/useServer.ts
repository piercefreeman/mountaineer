import React, { useContext } from 'react';
import { ServerContext } from '../../../_server/server';


export interface HomeRenderOptional {
  first_name?: string;
  current_count?: number;
}

export const useServer = () => {
const { serverState, setServerState } = useContext(ServerContext);
const setControllerState = (payload: HomeRenderOptional) => {
setServerState((state) => ({
...state,
HOME_CONTROLLER: {
...state.HOME_CONTROLLER,
...payload,
}
}))
};
return {
...serverState['HOME_CONTROLLER'],
}
};