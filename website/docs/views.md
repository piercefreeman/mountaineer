# Frontend Views

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

When rendering `dashboard/home/page.tsx`, the view will be wrapped in the `app/dashboard/layout.tsx` layout alongside `app/layout.tsx`. These layouts should only provide styling. Since the use of `useServer` would be ambiguous for layouts that are rendered by multiple components, they should not contain any logic or data fetching.

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
