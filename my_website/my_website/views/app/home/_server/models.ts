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
  metadata?: Metadata | null;
  client_ip: string;
  current_count: number;
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
  metadata?: Metadata | null;
  client_ip: string;
  current_count: number;
}

export interface LinkAttribute {
  rel: string;
  href: string;
  optional_attributes?: Record<string, string>;
}

export interface MetaAttribute {
  name?: string | null;
  content?: string | null;
  optional_attributes?: Record<string, string>;
}

export interface Metadata {
  title?: string | null;
  meta?: Array<MetaAttribute>;
  links?: Array<LinkAttribute>;
}

export interface Optional Attributes {

}

export interface ValidationError {
  loc: Array<string | number>;
  msg: string;
  type: string;
}