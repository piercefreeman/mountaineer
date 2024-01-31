import React, { useState } from 'react';
import { applySideEffect } from '../../../_server/api';
import LinkGenerator from '../../../_server/links';
import { ComplexRender } from './models';

export type ComplexRenderOptional = Partial<ComplexRender>;

declare global {
var SERVER_DATA: ComplexRender;
}


export const useServer = () => {
const [ serverState, setServerState ] = useState(SERVER_DATA);
const setControllerState = (payload: ComplexRenderOptional) => {
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