import { __request, FetchErrorBase } from '../../../_server/api';
import type { GetExternalDataResponse, IncrementCountOnlyResponse, IncrementCountRequest, IncrementCountResponse, HTTPValidationError } from './models';

export const get_external_data = (): Promise<GetExternalDataResponse> => {
return __request(
{
'method': 'POST',
'url': '/internal/api/home_controller/get_external_data',
'query': {

}
}
);
}

export const increment_count = ({
requestBody
}: {
requestBody: IncrementCountRequest
}): Promise<IncrementCountResponse> => {
return __request(
{
'method': 'POST',
'url': '/internal/api/home_controller/increment_count',
'query': {

},
'errors': {
422: HTTPValidationErrorException
},
'body': requestBody,
'mediaType': 'application/json'
}
);
}

export const increment_count_only = ({
url_param,
requestBody
}: {
url_param: number,
requestBody: IncrementCountRequest
}): Promise<IncrementCountOnlyResponse> => {
return __request(
{
'method': 'POST',
'url': '/internal/api/home_controller/increment_count_only',
'query': {
url_param
},
'errors': {
422: HTTPValidationErrorException
},
'body': requestBody,
'mediaType': 'application/json'
}
);
}

class HTTPValidationErrorException extends FetchErrorBase<HTTPValidationError> {}