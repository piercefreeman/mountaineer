import React, { useState } from 'react';
import { applySideEffect } from '../../../_server/api';
import LinkGenerator from '../../../_server/links';
import { DetailRender } from './models';

export type DetailRenderOptional = Partial<DetailRender>;

declare global {
var SERVER_DATA: any;
}


export const useServer = () => {
const [ serverState, setServerState ] = useState(SERVER_DATA as DetailRender);
const setControllerState = (payload: DetailRenderOptional) => {
setServerState((state) => ({
...state,
...payload,
}));
};
return {
...serverState,
linkGenerator: LinkGenerator,
}
};