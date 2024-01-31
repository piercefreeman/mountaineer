export interface GetExternalDataResponse {
  passthrough: GetExternalDataResponsePassthrough;
}

export interface GetExternalDataResponsePassthrough {
  first_name: string;
}

export interface HTTPValidationError {
  detail?: Array<ValidationError>;
}

export interface HomeRender {
  client_ip: string;
  current_count: number;
  random_uuid: string;
}

export interface IncrementCountOnlyResponse {
  sideeffect: IncrementCountOnlyResponseSideEffect;
}

export interface IncrementCountOnlyResponseSideEffect {
  current_count: number;
}

export interface IncrementCountRequest {
  count: number;
}

export interface IncrementCountResponse {
  sideeffect: IncrementCountResponseSideEffect;
}

export interface IncrementCountResponseSideEffect {
  client_ip: string;
  current_count: number;
  random_uuid: string;
}

export interface ValidationError {
  loc: Array<number | string>;
  msg: string;
  type: string;
}