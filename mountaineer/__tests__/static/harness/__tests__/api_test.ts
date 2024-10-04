import { FetchErrorBase, __getLink, __request, applySideEffect } from "../api";

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

  /*it("should handle array query parameters", () => {
    const url = __getLink({
      rawUrl: "https://api.example.com/search",
      pathParameters: {},
      queryParameters: {
        tags: ["javascript", "typescript"],
      },
    });

    expect(url).toBe(
      "https://api.example.com/search?tags=javascript&tags=typescript",
    );
  });*/

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
