import { __getLink } from '../../../_server/api';
export const getLink = ({
detail_id,
delay_loops
} : {
detail_id: string,
delay_loops: number
}) => {

const url = `/complex/{detail_id}/`;

const queryParameters : Record<string, any> = {
delay_loops
};
const pathParameters : Record<string, any> = {
detail_id
};

return __getLink({rawUrl: url, queryParameters, pathParameters});

};