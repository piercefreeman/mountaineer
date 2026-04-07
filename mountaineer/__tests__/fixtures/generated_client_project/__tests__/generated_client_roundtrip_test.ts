// @ts-nocheck
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";

import { useServer } from "../app/home/_server/useServer";

const baseUrl = process.env.MOUNTAINEER_BASE_URL!;
const serverData = JSON.parse(process.env.MOUNTAINEER_SERVER_DATA_JSON!);
const nativeFetch = global.fetch.bind(globalThis);
const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>");

global.window = dom.window;
global.document = dom.window.document;
global.navigator = dom.window.navigator;
global.HTMLElement = dom.window.HTMLElement;
global.Node = dom.window.Node;
global.IS_REACT_ACT_ENVIRONMENT = true;

beforeAll(() => {
  global.SERVER_DATA = serverData;
  global.fetch = ((input, init) => {
    if (typeof input === "string" && input.startsWith("/")) {
      input = new URL(input, baseUrl).toString();
    }

    const headers = new Headers(init?.headers || {});
    if (!headers.has("referer")) {
      headers.set("referer", `${baseUrl}/`);
    }

    return nativeFetch(input, {
      ...init,
      headers,
    });
  }) as typeof fetch;
});

afterAll(() => {
  global.fetch = nativeFetch;
  delete global.SERVER_DATA;
});

describe("generated useServer integration", () => {
  it("round trips sideeffects and keeps callbacks stable across rerenders", async () => {
    let latestState: any;

    function Probe() {
      latestState = useServer();
      return React.createElement("div", null, latestState.current_count);
    }

    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(React.createElement(Probe));
    });

    const initialState = latestState;

    expect(initialState.current_count).toBe(0);
    expect(initialState.render_token).toBe(1);
    expect(
      initialState.linkGenerator.detailController({ item_id: "generated-link" }),
    ).toBe("/detail/generated-link");

    await act(async () => {
      const passthrough = await initialState.get_message();
      expect(passthrough.passthrough.message).toBe("count=0");
    });

    await act(async () => {
      await initialState.increment_count({
        requestBody: {
          count: 1,
        },
      });
    });

    const afterFullReload = latestState;

    expect(afterFullReload.current_count).toBe(1);
    expect(afterFullReload.render_token).toBe(2);
    expect(afterFullReload.increment_count).toBe(initialState.increment_count);
    expect(afterFullReload.increment_count_only).toBe(
      initialState.increment_count_only,
    );
    expect(afterFullReload.get_message).toBe(initialState.get_message);

    await act(async () => {
      await afterFullReload.increment_count_only({
        requestBody: {
          count: 2,
        },
      });
    });

    const afterPartialReload = latestState;

    expect(afterPartialReload.current_count).toBe(3);
    expect(afterPartialReload.render_token).toBe(2);
    expect(afterPartialReload.increment_count).toBe(initialState.increment_count);
    expect(afterPartialReload.increment_count_only).toBe(
      initialState.increment_count_only,
    );
    expect(afterPartialReload.get_message).toBe(initialState.get_message);

    await act(async () => {
      const passthrough = await afterPartialReload.get_message();
      expect(passthrough.passthrough.message).toBe("count=3");
    });

    await act(async () => {
      root.unmount();
    });
  });
});
