# filzl

filzl is a batteries-included web framework. It uses Python for the backend and React for the interactive frontend. If you've used either of these languages before for web development, we think you'll be right at home.

## Main Features

Each web framework has its own unique features and tradeoffs. Filzl focuses on developer productivity above all else.

- 📝 First-class typehints for both the frontend and backend
- 🎙️ Trivially simple client<->server communication, data binding, and function calling
- 🌎 Optimized for server rendering of components for better accessibility and SEO
- 🤩 Avoids the need for a separate gateway API or Node.js server just to serve frontend clients
- 🏹 Static analysis of templates for strong validation: link validity, data access, etc.

## Getting Started

By convention, filzl projects look like this:

```
my_website
  /controllers
    /home.py
  /views
    /app
      /home
        /page.tsx
      /layout.tsx
    /package.json
    /tsconfig.json
    /__init__.py
pyproject.toml
poetry.lock
```

Every file goes within your Python project. Views are defined in a disk-based hierarchy, where nested routes are in nested folders. Controllers are setup in a flat folder, where each controller is an separate file.

Let's get started with your controller, since this will define which data you can push and pull to your frontend.

```python title="my_website/controllers/home.py"
from filzl.actions import sideeffect
from filzl.controller import ControllerBase
from filzl.render import RenderBase
from fastapi import Request

from my_website.views import get_view_path

class HomeRender(RenderBase):
    client_ip: str
    current_count: int

class HomeController(ControllerBase):
    url = "/"
    view_path = get_view_path("/app/home/page.tsx")

    def __init__(self):
        super().__init__()
        self.global_count = 0

    def render(self, request: Request) -> HomeRender:
        return HomeRender(
            client_ip=(
                request.client.host
                if request.client
                else "unknown"
            ),
            current_count=self.global_count,
        )
```

This controller manages an internal state that we expect to persist across page views. We start with a very simple data model: sending the current count. The `render()` method is called when the page is loaded, and the data returned is sent to the frontend. This render() function accepts all parameters that FastAPI endpoints do: paths, query parameters, and dependency injected functions. Right now we're just grabbing the `Request` object to get the client IP.

Let's move over to the frontend.

```tsx title="my_website/views/home/page.tsx"

import React from "react";
import { useServer } from "./_server/useServer";

const Home = () => {
  const serverState = useServer();

  return (
    <div>
      <p>
        Hello {serverState.client_ip}, current count is
        {" "}{serverState.current_count}
      </p>
    </div>
  );
};

export default Home;
```

We define a simple view to show the data coming from the backend. We use our automatically generated `useServer()` hook to do this. This hook response will provide all the `HomeRender` fields as properties of serverState.

If you access this in your browser at `localhost:5006/` we can see the counter, but we can't really _do_ anything with it yet. Let's add some interactivity to increase the current count.

```python title="my_website/controllers/home.py"
from pydantic import BaseModel

class IncrementCountRequest(BaseModel):
    count: int

class HomeController(ControllerBase):
    ...

    @sideeffect
    def increment_count(self, payload: IncrementCountRequest):
        self.global_count += payload.count
```

We define a function that accepts a pydantic model, which defines one counter int. When clients provide this number we'll use this to update the global state.

The important part is the `@sideeffect`. This decorator indicates that we want the frontend to refresh its data, since after we update the global count on the server the client state will be newly outdated.

Filzl detects the presence of this sideeffect function and analyzes its signature. It then exposes this to the frontend as a normal async function.

```tsx title="my_website/views/home/page.tsx"

import React from "react";
import { useServer } from "./_server/useServer";

const Home = () => {
  const serverState = useServer();

  return (
    <div>
      <p>
        Hello {serverState.client_ip}, current count is
        {" "}{serverState.current_count}
      </p>
      <button
        onClick={async () => {
          await serverState.increment_count({
            requestBody: {
              count: 1,
            },
          });
        }}
      >
        Increment
      </button>
    </div>
  );
};

export default Home;
```

We run this async handler when the button is clicked and specify our desired increment count. Notice that we don't have to read or parse the output value of this function. Since the function is marked as a sideeffect, the frontend will automatically refresh its data after the function is called.

Go ahead and load it in your browser. If you open up your web tools, you can increment the ticker and see POST requests sending data to the backend and receiving the current server state. The actual data updates and merging happens internally by filzl.

And that's it. We've just built a fully interactive web application. You specify the data model and actions on the server and the appropriate frontend hooks are generated and updated automatically. These few simple functions provide a powerful way to build web applications.

### Installation

When doing local development work, use poetry to manage dependencies and maturin to create a build of the combined python/rust project:

```bash
$ poetry shell
poetry install
poetry run maturin develop
```

You'll also need a system-wide installation of esbuild. If you don't have one when you run the build pipline it will install one for you within `~/.cache/filzl/esbuild`.

## Future Directions

- Offload more of the server logic to Rust
- AST parsing of the tsx files to determine which parts of the serverState they're actually using and mask accordingly
- Plugins for simple authentication, daemons, billing, etc.

## V0 TODOs

- Global methods for getting the link to another page (should validate these links are actually valid at build-time)
- How to use a preprocessor like tailwind for the bundling?
- We should clearly support both async and sync rendering functions / actions.
