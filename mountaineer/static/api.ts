/*
 * Common Typescript API for client<->server communication, automatically copied
 * to each component project during schema generation.
 */

export class FetchErrorBase<T> extends Error {
  statusCode: number;
  body: T;

  constructor(statusCode: number, body: T) {
    super(`Error ${statusCode}: ${body}`);

    this.statusCode = statusCode;
    this.body = body;
  }
}

interface FetchParams {
  method: string;
  url: string;
  path?: Record<string, string | number>;
  query?: Record<string, string | number>;
  errors?: Record<
    number,
    new (statusCode: number, body: any) => FetchErrorBase<any>
  >;
  body?: Record<string, any>;
  mediaType?: string;
  outputFormat?: "json" | "text";
}

const handleOutputFormat = async (response: Response, format?: string) => {
  if (format === "text") {
    return await response.text();
  } else {
    // Assume JSON if not specified
    return await response.json();
  }
};

export const __request = async (params: FetchParams) => {
  const payloadBody = params.body ? JSON.stringify(params.body) : undefined;
  let filledUrl = params.url;

  // Fill path parameters
  for (const [key, value] of Object.entries(params.path || {})) {
    filledUrl = filledUrl.replace(`{${key}}`, value.toString());
  }

  // Fill query parameters
  Object.entries(params.query || {}).forEach(([key, value], i) => {
    filledUrl = `${filledUrl}${i === 0 ? "?" : "&"}${key}=${value}`;
  });

  try {
    const response = await fetch(filledUrl, {
      method: params.method,
      headers: {
        "Content-Type": params.mediaType || "application/json",
      },
      body: payloadBody,
    });

    if (response.status >= 200 && response.status < 300) {
      return await handleOutputFormat(response, params.outputFormat);
    } else {
      // Try to handle according to our error map
      if (params.errors && params.errors[response.status]) {
        const errorClass = params.errors[response.status];
        throw new errorClass(
          response.status,
          await handleOutputFormat(response, params.outputFormat),
        );
      }

      // It's rare that we don't have typehinted context to a more specific exception, but it
      // can happen. Handle with a generic error.
      throw new FetchErrorBase<any>(
        response.status,
        await handleOutputFormat(response, params.outputFormat),
      );
    }
  } catch (e) {
    // If we've caught the FetchErrorBase, rethrow it
    if (e instanceof FetchErrorBase) {
      throw e;
    }

    // Otherwise we have an unhandled error, rethrow as a generic error
    const error = new FetchErrorBase<any>(-1, e.toString());
    error.stack = e.stack;
    throw error;
  }
};

type ApiFunctionReturnType<S, P> = {
  sideeffect: S;
  passthrough?: P;
};

export function applySideEffect<
  ARG extends any[],
  S,
  P,
  RE extends ApiFunctionReturnType<S, P>,
>(
  apiFunction: (...args: ARG) => Promise<RE>,
  setControllerState: (payload: S) => void,
): (...args: ARG) => Promise<RE> {
  /*
   * Executes an API server function, triggering any appropriate exceptions.
   * If the fetch succeeds, the sideeffect is applied to the controller state.
   */
  return async (...args: ARG) => {
    const result = await apiFunction(...args);
    setControllerState(result.sideeffect);
    return result;
  };
}

interface GetLinkParams {
  rawUrl: string;
  queryParameters: Record<string, string>;
  pathParameters: Record<string, string>;
}

export const __getLink = (params: GetLinkParams) => {
  // Format the query parameters in raw JS, since our SSR environment doesn't  have
  // access to the URLSearchParams API.
  const parsedParams = Object.entries(params.queryParameters).reduce(
    (acc, [key, value]) => {
      if (value !== undefined) {
        acc.push(`${key}=${value}`);
      }
      return acc;
    },
    [] as string[],
  );
  const paramString = parsedParams.join("&");

  // Now fill in the path parameters
  let url = params.rawUrl;
  for (const [key, value] of Object.entries(params.pathParameters)) {
    if (value === undefined) {
      throw new Error(`Missing required path parameter ${key}`);
    }
    url = url.replace(`{${key}}`, value);
  }
  if (paramString) {
    url = `${url}?${paramString}`;
  }
  return url;
};
