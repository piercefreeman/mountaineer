export interface GetExternalDataResponse {
  passthrough: GetExternalDataResponsePassthrough;
}

export interface GetExternalDataResponsePassthrough {
  first_name: string;
}

export interface HTTPValidationError {
  detail?: Array<ValidationError>;
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
  first_name: string;
  current_count: number;
}

export interface ValidationError {
  loc: Array<string | number>;
  msg: string;
  type: string;
}