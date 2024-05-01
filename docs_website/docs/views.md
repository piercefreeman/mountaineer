# Frontend Views & Layouts

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
/views
  /app
    /dashboard
      /layout.tsx
      /home
        /page.tsx
      /settings
        /page.tsx
    /layout.tsx
```

When rendering `dashboard/home/page.tsx`, the view will be wrapped in the `app/dashboard/layout.tsx` layout alongside `app/layout.tsx`. These layout files will be automatically found by Mountaineer during the build process. They don't require any explicit declaration in your Python backend if you're just using them for styling.

If you need more server side power and want to define them in Python, you can add a LayoutController that backs the layout.

## Layout Controllers

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

In general you can implement layout controllers just like you do for pages. But since they're shared across multiple pages there are a few important differences to keep in mind:

- Layout controllers will be rendered in an isolated scope. Sideeffects in one layout controller won't affect the others.
- Dependency injections are similarly isolated. They are run in an isolated, synthetic context and not with the same dependency injection parameters that the page uses.
- Layout controllers don't modify the page signature. Query params on layouts won't be extracted, for instance.

As long as you write your layout controllers without directly referencing the page that they might be wrapping, which is the case for most layouts, you should be good to go.

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
