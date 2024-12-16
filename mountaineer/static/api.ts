/*
 * Common Typescript API for client<->server communication, automatically copied
 * to each component project during schema generation.
 */

// Type for values that can be converted to strings for URL parameters
export type UrlParamValue = string | number | boolean | Date | null | undefined;
export type UrlParamArray = Array<string | number | boolean | Date>;
export type UrlParam = UrlParamValue | UrlParamArray;

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
  path?: Record<string, UrlParamValue>;
  query?: Record<string, UrlParam>;
  headers?: Record<string, UrlParam>;
  errors?: Record<
    number,
    new (statusCode: number, body: any) => FetchErrorBase<any>
  >;
  body?: Record<string, any>;
  mediaType?: string;
  outputFormat?: "json" | "text" | "raw";
  eventStreamResponse?: boolean;
  signal?: AbortSignal;
}

// Helper function to convert various types to string for URL parameters
export const convertToUrlString = (
  value: UrlParamValue | UrlParam,
): string | undefined => {
  if (value === null || value === undefined) {
    return undefined;
  }

  if (value instanceof Date) {
    return value.toISOString();
  }

  return String(value);
};

// Helper function to process URL parameters
export const processUrlParams = (
  params: Record<string, UrlParam>,
): URLSearchParams => {
  const searchParams = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) {
      continue;
    }

    if (Array.isArray(value)) {
      // Handle array values
      value.forEach((item) => {
        const strValue = convertToUrlString(item);
        if (strValue !== undefined) {
          searchParams.append(key, strValue);
        }
      });
    } else {
      // Handle single values
      const strValue = convertToUrlString(value);
      if (strValue !== undefined) {
        searchParams.append(key, strValue);
      }
    }
  }

  return searchParams;
};

export const handleOutputFormat = async (
  response: Response,
  format?: string,
) => {
  if (format === "text") {
    return await response.text();
  } else if (format == "raw") {
    return response;
  } else {
    // Assume JSON if not specified
    return await response.json();
  }
};

export const __request = async (params: FetchParams) => {
  let contentType: string | undefined = params.mediaType || "application/json";
  let payloadBody: string | FormData | undefined = undefined;

  if (params.body) {
    if (contentType == "application/json") {
      payloadBody = JSON.stringify(params.body);
    } else if (contentType == "multipart/form-data") {
      payloadBody = new FormData();
      for (const [key, value] of Object.entries(params.body)) {
        payloadBody.append(key, value);
      }

      // Manually specifying multipart/form-data alongside the FormData requires
      // us to also send the boundary. We'd rather let the browser handle this.
      contentType = undefined;
    }
  }

  // Process URL and path parameters
  let url = new URL(params.url);

  // Fill path parameters
  for (const [key, value] of Object.entries(params.path || {})) {
    const strValue = convertToUrlString(value);
    if (strValue === undefined) {
      throw new Error(`Missing required path parameter ${key}`);
    }
    url.pathname = decodeURIComponent(url.pathname).replace(
      `{${key}}`,
      strValue,
    );
  }

  // Process and append query parameters
  if (params.query) {
    const searchParams = processUrlParams(params.query);
    url.search = searchParams.toString();
  }

  // Fill headers
  const headers: Record<string, string> = {
    ...(contentType && { "Content-Type": contentType }),
  };

  if (params.headers) {
    for (const [key, value] of Object.entries(params.headers)) {
      const strValue = convertToUrlString(value);
      if (strValue !== undefined) {
        headers[key] = strValue;
      }
    }
  }

  try {
    const response = await fetch(url.toString(), {
      method: params.method,
      headers,
      body: payloadBody,
      signal: params.signal,
    });

    if (response.status >= 200 && response.status < 300) {
      if (params.eventStreamResponse) {
        if (!response.body) {
          throw new Error("Response body is undefined");
        }
        return handleStreamOutputFormat(response.body, params.outputFormat);
      }
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
    const errorText = e instanceof Error ? e.toString() : "Unknown error";
    const errorStack = e instanceof Error ? e.stack : undefined;

    const error = new FetchErrorBase<any>(-1, errorText);
    error.stack = errorStack;
    throw error;
  }
};

const handleStreamOutputFormat = async (
  stream: ReadableStream<Uint8Array>,
  format?: string,
) => {
  /*
   * Unlike the typical implementation of EventSource (which only supports basic
   * GET and no custom headers), we'd rather piggyback on fetch() and iteratively parse
   * the response payload. We should implement reconnection logic in the future to
   * achieve parity with EventSource.
   */
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  return (async function* () {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        // If there's any residual data in the buffer when the stream ends,
        // yield it as the last piece of data.
        if (buffer.length > 0) {
          yield format === "text" ? buffer : JSON.parse(buffer);
        }
        break;
      }

      // Decode the current chunk and add it to the buffer.
      const textChunk = decoder.decode(value, { stream: true });
      buffer += textChunk;

      // Check for new lines in the buffer, and yield each line as a separate piece of data.
      let newLineIndex: number;
      while ((newLineIndex = buffer.indexOf("\n")) !== -1) {
        // Extract the line including the new line character, and adjust the buffer.
        let line = buffer.slice(0, newLineIndex + 1);
        buffer = buffer.slice(newLineIndex + 1);

        // If the line starts with "data:", strip it and trim the line.
        if (line.startsWith("data:")) {
          line = line.replace(/^data:/, "").trim();
        }

        // Yield the line in the requested format.
        yield format === "text" ? line : JSON.parse(line);
      }
    }
  })();
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
  queryParameters: Record<string, UrlParam>;
  pathParameters: Record<string, UrlParamValue>;
}

export const __getLink = (params: GetLinkParams) => {
  // Format the URL using the standard URL API
  const url = new URL(params.rawUrl);

  // Fill path parameters
  for (const [key, value] of Object.entries(params.pathParameters)) {
    const strValue = convertToUrlString(value);
    if (strValue === undefined) {
      throw new Error(`Missing required path parameter ${key}`);
    }
    url.pathname = decodeURIComponent(url.pathname).replace(
      `{${key}}`,
      strValue,
    );
  }

  // Process query parameters
  if (params.queryParameters) {
    const searchParams = processUrlParams(params.queryParameters);
    url.search = searchParams.toString();
  }

  return decodeURIComponent(url.toString());
};
