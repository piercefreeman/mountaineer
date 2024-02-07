# Views

Your React app should be initialized in the `/views` folder of your filzl project. This is the directory where we look for package.json and tsconfig.json, and where esbuild looks for specific build-time overrides. In other words, the views folder should look much like your frontend application if you were building an SPA. It's just embedded within your larger filzl project.

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

We also support the Next.js `layout.tsx` convention, which is a special file that will be used to wrap all containing views in a common layout. This is useful for things like headers, footers, and other common elements.

The children of the page will be passed as `{children}` to the layout component. Make sure to include this in your rendered view:

```typescript title="/views/app/layout.tsx"
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

When rendering `dashboard/home/page.tsx`, the view will be wrapped in the `app/dashboard/layout.tsx` layout alongside `app/layout.tsx`. These layouts should only provide styling. Since the use of `useServer` would be ambiguous for layouts that are rendered by multiple components, they should not contain any logic or data fetching.
