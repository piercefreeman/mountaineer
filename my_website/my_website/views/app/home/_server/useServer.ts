import React, { useState } from 'react';
import { applySideEffect } from '../../../_server/api';
import LinkGenerator from '../../../_server/links';
import { HomeRender } from './models';import { get_external_data, increment_count, increment_count_only } from './actions';

export type HomeRenderOptional = Partial<HomeRender>;

declare global {
var SERVER_DATA: HomeRender;
}


export const useServer = () => {
const [ serverState, setServerState ] = useState(SERVER_DATA);
const setControllerState = (payload: HomeRenderOptional) => {
setServerState((state) => ({
...state,
...payload,
}));
};
return {
...serverState,
linkGenerator: LinkGenerator,
get_external_data: get_external_data,
increment_count: applySideEffect(increment_count, setControllerState),
increment_count_only: applySideEffect(increment_count_only, setControllerState)}
};