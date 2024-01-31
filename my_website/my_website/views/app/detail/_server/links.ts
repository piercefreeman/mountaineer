import { __getLink } from '../../../_server/api';
export const getLink = ({
detail_id
} : {
detail_id: string
}) => {

const url = `/detail/{detail_id}/`;

const queryParameters : Record<string, any> = {

};
const pathParameters : Record<string, any> = {
detail_id
};

return __getLink({rawUrl: url, queryParameters, pathParameters});

};