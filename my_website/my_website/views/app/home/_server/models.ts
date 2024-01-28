export interface GetExternalDataResponse {
  passthrough: GetExternalDataResponsePassthrough;
}

export interface GetExternalDataResponsePassthrough {
  first_name: string;
}

export interface HomeRender {
  first_name: string;
  current_count: number;
}

export interface IncrementCountOnlyResponse {
  sideeffect: IncrementCountOnlyResponseSideEffect;
}

export interface IncrementCountOnlyResponseSideEffect {
  current_count: number;
}

export interface IncrementCountResponse {
  sideeffect: IncrementCountResponseSideEffect;
}

export interface IncrementCountResponseSideEffect {
  first_name: string;
  current_count: number;
}