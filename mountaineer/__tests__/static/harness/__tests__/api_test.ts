import {
  __getLink,
  __request,
  applySideEffect,
  convertToUrlString,
  FetchErrorBase,
  handleOutputFormat,
  processUrlParams,
  ServerURLSearchParams,
  ServerURL,
} from "../api";

// Mock fetch globally
global.fetch = jest.fn();

describe("FetchErrorBase", () => {
  it("should create an instance with correct properties", () => {
    const error = new FetchErrorBase(404, "Not Found");
    expect(error).toBeInstanceOf(Error);
    expect(error.statusCode).toBe(404);
    expect(error.body).toBe("Not Found");
    expect(error.message).toBe("Error 404: Not Found");
  });
});

describe("convertToUrlString", () => {
  it("should convert various types to string", () => {
    const testCases = [
      { input: "test", expected: "test" },
      { input: 123, expected: "123" },
      { input: true, expected: "true" },
      { input: new Date("2024-01-01"), expected: "2024-01-01T00:00:00.000Z" },
      { input: null, expected: undefined },
      { input: undefined, expected: undefined },
    ];

    testCases.forEach(({ input, expected }) => {
      expect(convertToUrlString(input)).toBe(expected);
    });
  });
});

describe("processUrlParams", () => {
  it("should process single value parameters", () => {
    const params = {
      name: "John",
      age: 30,
      active: true,
    };

    const result = processUrlParams(params);
    expect(result.toString()).toBe("name=John&age=30&active=true");
  });

  it("should handle array parameters", () => {
    const params = {
      tags: ["javascript", "typescript"],
      ids: [1, 2, 3],
    };

    const result = processUrlParams(params);
    expect(result.toString()).toBe(
      "tags=javascript&tags=typescript&ids=1&ids=2&ids=3",
    );
  });

  it("should skip null and undefined values", () => {
    const params = {
      name: "John",
      age: null,
      city: undefined,
      active: true,
    };

    const result = processUrlParams(params);
    expect(result.toString()).toBe("name=John&active=true");
  });

  it("should handle empty objects", () => {
    const params = {};
    const result = processUrlParams(params);
    expect(result.toString()).toBe("");
  });
});

describe("handleOutputFormat", () => {
  it("should handle text format", async () => {
    const mockResponse = {
      text: jest.fn().mockResolvedValue("Hello World"),
    };

    const result = await handleOutputFormat(
      mockResponse as unknown as Response,
      "text",
    );
    expect(result).toBe("Hello World");
    expect(mockResponse.text).toHaveBeenCalled();
  });

  it("should handle raw format", async () => {
    const mockResponse = {
      text: jest.fn(),
      json: jest.fn(),
    };

    const result = await handleOutputFormat(
      mockResponse as unknown as Response,
      "raw",
    );
    expect(result).toBe(mockResponse);
    expect(mockResponse.text).not.toHaveBeenCalled();
    expect(mockResponse.json).not.toHaveBeenCalled();
  });

  it("should handle json format by default", async () => {
    const mockData = { message: "Hello" };
    const mockResponse = {
      json: jest.fn().mockResolvedValue(mockData),
    };

    const result = await handleOutputFormat(
      mockResponse as unknown as Response,
    );
    expect(result).toEqual(mockData);
    expect(mockResponse.json).toHaveBeenCalled();
  });
});

describe("__request", () => {
  beforeEach(() => {
    (global.fetch as jest.Mock).mockClear();
  });

  it("should make a successful GET request", async () => {
    const mockResponse = { data: "test" };
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      json: jest.fn().mockResolvedValueOnce(mockResponse),
    });

    const result = await __request({
      method: "GET",
      url: "https://api.example.com/data",
    });

    expect(result).toEqual(mockResponse);
    expect(global.fetch).toHaveBeenCalledWith(
      "https://api.example.com/data",
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
      }),
    );
  });

  it("should handle path parameters correctly", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      json: jest.fn().mockResolvedValueOnce({}),
    });

    await __request({
      method: "GET",
      url: "https://api.example.com/users/{userId}",
      path: { userId: "123" },
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "https://api.example.com/users/123",
      expect.anything(),
    );
  });

  it("should handle query parameters correctly", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      json: jest.fn().mockResolvedValueOnce({}),
    });

    await __request({
      method: "GET",
      url: "https://api.example.com/search",
      query: { q: "test", page: 1 },
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "https://api.example.com/search?q=test&page=1",
      expect.anything(),
    );
  });

  it("should handle JSON body correctly", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      json: jest.fn().mockResolvedValueOnce({}),
    });

    const body = { name: "John", age: 30 };
    await __request({
      method: "POST",
      url: "https://api.example.com/users",
      body,
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "https://api.example.com/users",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify(body),
      }),
    );
  });

  it("should handle form-data body correctly", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 200,
      json: jest.fn().mockResolvedValueOnce({}),
    });

    const body = { name: "John", age: 30 };
    await __request({
      method: "POST",
      url: "https://api.example.com/users",
      body,
      mediaType: "multipart/form-data",
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "https://api.example.com/users",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData),
      }),
    );

    const calledBody = (global.fetch as jest.Mock).mock.calls[0][1].body;
    expect(calledBody).toBeInstanceOf(FormData);
    expect(calledBody.get("name")).toBe("John");
    expect(calledBody.get("age")).toBe("30");
  });

  it("should handle custom error responses", async () => {
    const errorBody = { message: "Not Found" };
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 404,
      json: jest.fn().mockResolvedValueOnce(errorBody),
    });

    class CustomError extends FetchErrorBase<typeof errorBody> {}

    await expect(
      __request({
        method: "GET",
        url: "https://api.example.com/nonexistent",
        errors: {
          404: CustomError,
        },
      }),
    ).rejects.toThrow(CustomError);
  });

  it("should handle generic error responses", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      status: 500,
      json: jest
        .fn()
        .mockResolvedValueOnce({ message: "Internal Server Error" }),
    });

    await expect(
      __request({
        method: "GET",
        url: "https://api.example.com/error",
      }),
    ).rejects.toThrow(FetchErrorBase);
  });

  it("should handle network errors", async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(
      new Error("Network Error"),
    );

    await expect(
      __request({
        method: "GET",
        url: "https://api.example.com/network-error",
      }),
    ).rejects.toThrow(FetchErrorBase);
  });
});

describe("applySideEffect", () => {
  it("should apply side effect and return result", async () => {
    const mockApiFunction = jest.fn().mockResolvedValue({
      sideeffect: { count: 1 },
      passthrough: { message: "Success" },
    });

    const mockSetControllerState = jest.fn();

    const wrappedFunction = applySideEffect(
      mockApiFunction,
      mockSetControllerState,
    );
    const result = await wrappedFunction("arg1", "arg2");

    expect(mockApiFunction).toHaveBeenCalledWith("arg1", "arg2");
    expect(mockSetControllerState).toHaveBeenCalledWith({ count: 1 });
    expect(result).toEqual({
      sideeffect: { count: 1 },
      passthrough: { message: "Success" },
    });
  });
});

describe("__getLink", () => {
  it("should generate correct URL with path and query parameters", () => {
    const url = __getLink({
      rawUrl: "https://api.example.com/users/{userId}/posts/{postId}",
      pathParameters: {
        userId: "123",
        postId: "456",
      },
      queryParameters: {
        sort: "date",
        order: "desc",
      },
    });

    expect(url).toBe(
      "https://api.example.com/users/123/posts/456?sort=date&order=desc",
    );
  });

  it("should ignore undefined query parameters", () => {
    const url = __getLink({
      rawUrl: "https://api.example.com/users",
      pathParameters: {},
      queryParameters: {
        name: "John",
        age: undefined,
      },
    });

    expect(url).toBe("https://api.example.com/users?name=John");
  });
});

describe("ServerURL", () => {
  describe("path handling", () => {
    const pathTests = [
      ["simple path", "foo/bar", undefined, "/foo/bar"],
      ["absolute path", "/foo/bar", undefined, "/foo/bar"],
      ["with base", "foo/bar", "/base/", "/base/foo/bar"],
      ["with base no slash", "foo/bar", "/base", "/base/foo/bar"],
      ["absolute with base", "/foo/bar", "/base/", "/foo/bar"],
      ["with dots", "../foo/bar", "/base/path/", "/base/foo/bar"],
      ["empty path", "", undefined, "/"],
    ];

    it.each(pathTests)("%s", (_, path, base, expected) => {
      const url = new ServerURL(path, base);
      expect(url.pathname).toBe(expected);
    });
  });

  describe("search params", () => {
    it("should handle search parameters", () => {
      const url = new ServerURL("foo/bar?a=1&b=2");
      expect(url.pathname).toBe("/foo/bar");
      expect(url.search).toBe("?a=1&b=2");
    });

    it("should allow setting search", () => {
      const url = new ServerURL("foo/bar");
      url.search = "a=1&b=2";
      expect(url.search).toBe("?a=1&b=2");
    });
  });

  describe("pathname setter", () => {
    it("should normalize paths", () => {
      const url = new ServerURL("/foo/bar");
      url.pathname = "baz/qux";
      expect(url.pathname).toBe("/baz/qux");
    });
  });

  describe("toString", () => {
    it("should combine pathname and search", () => {
      const url = new ServerURL("foo/bar?a=1");
      expect(url.toString()).toBe("/foo/bar?a=1");
    });
  });
});

describe("ServerURLSearchParams", () => {
  describe("constructor", () => {
    it("should handle string input", () => {
      const params = new ServerURLSearchParams("a=1&b=2");
      expect(params.toString()).toBe("a=1&b=2");
    });

    it("should handle object input", () => {
      const params = new ServerURLSearchParams({ a: "1", b: "2" });
      expect(params.toString()).toBe("a=1&b=2");
    });

    it("should handle array values", () => {
      const params = new ServerURLSearchParams({ a: ["1", "2"], b: "3" });
      expect(params.toString()).toBe("a=1&a=2&b=3");
    });
  });

  describe("append", () => {
    it("should append values", () => {
      const params = new ServerURLSearchParams();
      params.append("a", "1");
      params.append("a", "2");
      expect(params.toString()).toBe("a=1&a=2");
    });
  });

  describe("toString", () => {
    it("should encode special characters", () => {
      const params = new ServerURLSearchParams();
      params.append("a", "hello world");
      params.append("b", "1+2=3");
      expect(params.toString()).toBe("a=hello%20world&b=1%2B2%3D3");
    });
  });
});
