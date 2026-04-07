import asyncio
import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Thread

import httpx
import pytest
import uvicorn
from pydantic import BaseModel

from mountaineer.actions.passthrough_dec import passthrough
from mountaineer.actions.sideeffect_dec import sideeffect
from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.controller import ControllerBase
from mountaineer.render import Metadata, RenderBase


class IncrementCountRequest(BaseModel):
    count: int


class GetMessageResponse(BaseModel):
    message: str


class HomeRender(RenderBase):
    current_count: int
    render_token: int


class DetailRender(RenderBase):
    item_id: str


class HomeController(ControllerBase):
    url = "/"
    view_path = "/app/home/page.tsx"

    def __init__(self):
        super().__init__()
        self.current_count = 0
        self.render_count = 0

    def render(self) -> HomeRender:
        self.render_count += 1
        return HomeRender(
            current_count=self.current_count,
            render_token=self.render_count,
            metadata=Metadata(title="Home"),
        )

    @sideeffect
    def increment_count(self, payload: IncrementCountRequest) -> None:
        self.current_count += payload.count

    @sideeffect(reload=(HomeRender.current_count,))
    def increment_count_only(self, payload: IncrementCountRequest) -> None:
        self.current_count += payload.count

    @passthrough
    def get_message(self) -> GetMessageResponse:
        return GetMessageResponse(message=f"count={self.current_count}")


class DetailController(ControllerBase):
    url = "/detail/{item_id}/"
    view_path = "/app/detail/page.tsx"

    def render(self, item_id: str) -> DetailRender:
        return DetailRender(
            item_id=item_id,
            metadata=Metadata(title=f"Detail: {item_id}"),
        )


@pytest.mark.integration_tests
def test_generated_use_server_roundtrip(tmp_path: Path):
    view_root = tmp_path / "views"
    _write_test_project(view_root)

    app = AppController(view_root=view_root)
    home_controller = HomeController()
    app.register(home_controller)
    app.register(DetailController())
    app.app.get("/_healthz")(lambda: {"ok": True})

    asyncio.run(APIBuilder(app).build_use_server())

    _run_command(
        ["npm", "install", "--no-fund", "--no-audit"],
        cwd=view_root,
        env=dict(os.environ, CI="1"),
    )

    initial_server_data = {
        home_controller.__class__.__name__: home_controller.render().model_dump(
            mode="json"
        )
    }

    with _run_uvicorn_server(app.app) as base_url:
        _run_command(
            [
                "npm",
                "run",
                "test",
                "--",
                "--runInBand",
                "__tests__/generated_client_roundtrip_test.ts",
            ],
            cwd=view_root,
            env=dict(
                os.environ,
                CI="1",
                MOUNTAINEER_BASE_URL=base_url,
                MOUNTAINEER_SERVER_DATA_JSON=json.dumps(initial_server_data),
            ),
        )


def _write_test_project(view_root: Path):
    (view_root / "app" / "home").mkdir(parents=True)
    (view_root / "app" / "detail").mkdir(parents=True)
    (view_root / "__tests__").mkdir(parents=True)

    (view_root / "package.json").write_text(
        json.dumps(
            {
                "name": "mountaineer-generated-client-test",
                "private": True,
                "scripts": {
                    "test": "jest",
                },
                "dependencies": {
                    "react": "^19.0.0",
                    "react-dom": "^19.0.0",
                },
                "devDependencies": {
                    "@types/jest": "^29.5.13",
                    "@types/react": "^19.0.10",
                    "@types/react-dom": "^19.0.4",
                    "jest": "^29.7.0",
                    "jest-environment-jsdom": "^29.7.0",
                    "ts-jest": "^29.2.5",
                    "typescript": "^5.7.3",
                },
            },
            indent=2,
        )
        + "\n"
    )

    (view_root / "tsconfig.json").write_text(
        """{
  "compilerOptions": {
    "target": "es2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": false,
    "noImplicitAny": false,
    "forceConsistentCasingInFileNames": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "react-jsx",
    "incremental": true
  },
  "include": ["./**/*"],
  "exclude": ["node_modules", "**/*.map.js"]
}
"""
    )

    (view_root / "jest.config.js").write_text(
        """module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  transform: {
    "^.+\\\\.tsx?$": [
      "ts-jest",
      {
        tsconfig: "./tsconfig.json"
      }
    ]
  }
};
"""
    )

    (view_root / "app" / "home" / "page.tsx").write_text(
        "export default function Page() {\n  return null;\n}\n"
    )
    (view_root / "app" / "detail" / "page.tsx").write_text(
        "export default function DetailPage() {\n  return null;\n}\n"
    )

    (view_root / "__tests__" / "generated_client_roundtrip_test.ts").write_text(
        """// @ts-nocheck
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
"""
    )


def _run_command(command: list[str], *, cwd: Path, env: dict[str, str]):
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _run_uvicorn_server(app):
    port = _find_free_port()

    class TestServer(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            return None

    server = TestServer(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )

    thread = Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/_healthz", timeout=0.5)
            if response.status_code == 200:
                break
        except httpx.RequestError as exc:
            last_error = exc

        time.sleep(0.1)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise AssertionError(f"Timed out waiting for uvicorn to start: {last_error}")

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            raise AssertionError("Uvicorn test server did not shut down cleanly")
