import React, { useContext } from 'react';
import { ServerContext } from '../../../_server/server';
import { applySideEffect } from '../../../_server/api';
import { HomeRender } from './models';import { get_external_data, increment_count, increment_count_only } from './actions';

export type HomeRenderOptional = Partial<HomeRender>;

export const useServer = () => {
const { serverState, setServerState } = useContext(ServerContext);
const setControllerState = (payload: HomeRenderOptional) => {
setServerState((state) => ({
...state,
HOME_CONTROLLER: state.HOME_CONTROLLER ? {
...state.HOME_CONTROLLER,
...payload,
} : undefined
}))
};
return {
...serverState['HOME_CONTROLLER'],
get_external_data: get_external_data,
increment_count: applySideEffect(increment_count, setControllerState),
increment_count_only: applySideEffect(increment_count_only, setControllerState)}
};