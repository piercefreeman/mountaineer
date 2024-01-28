interface GetExternalDataResponse {
  passthrough: GetExternalDataResponsePassthrough;
}

interface GetExternalDataResponsePassthrough {
  first_name: string;
}

interface HomeRender {
  first_name: string;
  current_count: number;
}

interface IncrementCountOnlyResponse {
  sideeffect: IncrementCountOnlyResponseSideEffect;
}

interface IncrementCountOnlyResponseSideEffect {
  current_count: number;
}

interface IncrementCountResponse {
  sideeffect: IncrementCountResponseSideEffect;
}

interface IncrementCountResponseSideEffect {
  first_name: string;
  current_count: number;
}