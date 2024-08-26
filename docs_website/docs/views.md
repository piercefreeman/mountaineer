# Views & Layouts

Your React app should be initialized in the `/views` folder of your Mountaineer project. This is the directory where we look for package.json and tsconfig.json, and where esbuild looks for specific build-time overrides. In other words, the views folder should look just like your frontend application if you were building a Single-Page-App (SPA). It's just embedded within your larger Mountaineer project and rendered separately.

We expect that all controller views will be labeled as a `page.tsx`, so they'll typically sit in a folder with themselves and other tightly connected React components. These views should have one default export, which is your page constructor:

```typescript title="/views/app/home/page.tsx"
import React from "react";

const Home = () => {
  return (
    <div>
      <h1>Home</h1>
      <p>Welcome to the home page!</p>
    </div>
  );
}

export default Home;
```

We don't support async functions for these page renders, instead expecting that your backend will provide all data required to serialize the view.

If you want actions performed on the client-side after the view has been hydrated with Javascript, you can use a `useEffect` hook with an empty dependency list:

```typescript title="/views/app/home/page.tsx"
import React, { useEffect } from "react";

const Home = () => {
  useEffect(() => {
    console.log("The page has been hydrated with Javascript!");
  }, []);

  return (
    <div>
      <h1>Home</h1>
      <p>Welcome to the home page!</p>
    </div>
  );
}

export default Home;
```

## Controllers

A controller backs a view in a 1:1 relationship. It provides the backend plumbing to render the view, and can also provide sideeffects and passthroughs actions. The main entrypoint into this is the `render` function, which is called on your initial view to serialize all the data that your frontend will need when displaying the initial state of the page. All your data heavy lifting (database queries, manipulation, etc) should go here.

```python title="/controllers/home.py"

from mountaineer import sideeffect, ControllerBase, RenderBase
from mountaineer.database import DatabaseDependencies
from mountaineer.database.session import AsyncSession

from sqlmodel import select

from myapp.models import TodoItem

class HomeRender(RenderBase):
    todos: list[TodoItem]

class HomeController(ControllerBase):
    url = "/"
    view_path = "/app/home/page.tsx"

    async def render(
        self,
        session: AsyncSession = Depends(DatabaseDependencies.get_db_session)
    ) -> HomeRender:
        todos = (await session.execute(select(TodoItem))).all()

        return HomeRender(
            todos=todos
        )
```

### Path Parameters

The `render` function signature is inspected to provide the full URL that can be called. To provide a URL parameter that extracts a given ID identifier and matches the following:

```
/details/a687566b-db3e-42e3-9053-4f679abe8277
/details/4a4c26bc-554a-40dd-aecd-916abd3bc475
```

You can do:

```python
class DetailController(ControllerBase):
    url = "/details/{item_id}"
    view_path = "/app/details/page.tsx"

    async def render(
        self,
        item_id: UUID,
    ) -> HomeRender:
        ...
```

### Query Parameters

Query parameters are also supported. We support both simple types (str, float, UUID, etc) alongside lists of simple types. To provide a query parameter that matches the following:

```
/search?name=Apple&cost=30&cost=50
/search?name=Banana
```

You can do:

```python
from typing import Annotated
from fastapi import Query

class SearchController(ControllerBase):
    url = "/search"
    view_path = "/app/search/page.tsx"

    async def render(
        self,
        name: str,
        cost: Annotated[list[int] | None, Query()] = None,
    ) -> HomeRender:
        ...
```

!!! tip

    Both path and query parameters are validated by FastAPI, so you can use the same validation techniques. For more details, see the FastAPI [guide](https://fastapi.tiangolo.com/tutorial/query-params-str-validations/).

## Layouts

We also support the Next.js `layout.tsx` convention, which is a special file that will be used to wrap all containing views in a common layout. This is useful for things like headers, footers, and other common elements.

The children of the page will be passed as `{children}` to the layout component. Make sure to include this in your rendered view:

```typescript title="/views/app/layout.tsx"
import React from "react";

const Layout = ({ children } : { children: React.ReactNode }) => {
  return (
    <div>
      <header>
        <h1>My Website</h1>
      </header>
      <main>
        {children}
      </main>
      <footer>
        <p>© My Website</p>
      </footer>
    </div>
  );
}

export default Layout;
```

This allows you to chain layouts before rendering the final, most specific page:

```
views/
└── app/
    ├── dashboard/
    │   ├── layout.tsx
    │   ├── home/
    │   │   └── page.tsx
    │   └── settings/
    │       └── page.tsx
    └── layout.tsx
```

When rendering `dashboard/home/page.tsx`, the view will be wrapped in the `app/dashboard/layout.tsx` layout alongside `app/layout.tsx`. These layout files will be automatically found by Mountaineer during the build process. They don't require any explicit declaration in your Python backend if you're just using them for styling.

If you need more server side power and want to define them in Python, you can add a LayoutController that backs the layout.

### Layout Controllers

Layouts support most of the same controller logic that regular pages do. They can specify their own actions, both sideeffects and passthroughs, which will re-render the layout as required.

```python title="/controllers/root_layout.py"
from mountaineer import LayoutControllerBase, RenderBase
from mountaineer.actions import sideeffect

class RootLayoutRender(RenderBase):
    layout_value: int

class RootLayoutController(LayoutControllerBase):
    view_path = "/app/layout.tsx"

    def __init__(self):
        super().__init__()
        self.layout_value = 0

    def render(self) -> RootLayoutRender:
        return RootLayoutRender(
            layout_value=self.layout_value,
        )

    @sideeffect
    async def increment_layout_value(self) -> None:
        self.layout_value += 1
```

All these functions are now exposed to the frontend layout, including the link generator, state, and any actions specified.

```typescript title="/views/app/layout.tsx"
import React, { ReactNode } from "react";
import { useServer } from "./_server";

const Layout = ({ children }: { children: ReactNode }) => {
  const serverState = useServer();

  return (
    <div className="p-6">
      <h1>Layout State: {serverState.layout_value}</h1>
      <div>{children}</div>
      <div>
        <button
          className="rounded-md bg-indigo-500 p-2 text-white"
          onClick={async () => {
            await serverState.increment_layout_value();
          }}
        >
          Increase Ticker
        </button>
      </div>
    </div>
  );
};

export default Layout;
```

Once your controller is declared, you'll need to mount your layout into the AppController like you do for regular pages.

```python title="/app.py"
app_controller = AppController(...)
app_controller.register(RootLayoutController())
```

In general you can implement layout controllers just like you do for pages. But since they're shared across multiple child controllers, make sure the keyword arguments you use in your `render` signature don't have any conflicts. Mountaineer will merge these signatures at runtime and check for duplicate keyword names across the layout's child pages. Arguments are allowed to share the same name _and_ type, in which case they will be resolved to the same value. Arguments with conflicting types will raise a `TypeError`.

It's also worth noting that layout controllers will resolve their dependencies in the same scope as the page controllers. So if you need database access within your layout, you'll receive the same underlying transaction as the page controller. This makes dependency injection a powerful way to save on resources, but be careful to not treat them as isolated objects.

## Typescript Configuration

If you want to customize how Mountaineer builds your view files into raw client-side javascript, add a `tsconfig.json` file. The Typescript website includes a [full list](https://www.typescriptlang.org/tsconfig) of the available options here. A good place to start is:

```json
{
  "compilerOptions": {
    "target": "es2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
  },
  "exclude": ["node_modules"]
}
```

A common convention is importing all your view paths with absolute paths (like `@/components/myfile`) instead of having to do relative imports (`../../components/myfile`). This can be easily achieved by adding a `paths` key to your `tsconfig.json`. Your import becomes relative to all paths in the root directory.

```json
{
  "compilerOptions": {
    "target": "es2017",
    ...
    "paths": {
      "@/*": ["./*"]
    }
  },
  "exclude": ["node_modules"]
}
```
