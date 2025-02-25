# React 19 Support in Mountaineer

This document outlines how Mountaineer supports React 19 and what changes were made to ensure compatibility.

## Overview

Mountaineer now fully supports React 19, which includes several new features and improvements over React 18:

- New React DOM Static APIs for static site generation
- Improved hydration for better handling of third-party scripts
- Better support for Custom Elements
- Server Components and Server Actions

## Changes Made to Support React 19

### Package Dependencies

All template and test package.json files have been updated to use React 19:

```json
{
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0"
  }
}
```

### Server-Side Rendering (SSR)

Mountaineer now supports both React 18's `renderToString` and React 19's new `prerender` API:

1. The code generator now creates SSR code that attempts to use the new `prerender` API from `react-dom/static` if available, with a fallback to `renderToString` from `react-dom/server`.

2. The SSR runtime has been updated to handle both synchronous (React 18) and asynchronous (React 19) rendering functions.

3. Additional polyfills have been added to support React 19's SSR requirements:
   - `AbortController`
   - `ReadableStream`
   - Proper handling of `document.all`

### Client-Side Hydration

The client-side hydration code continues to use `hydrateRoot` from `react-dom/client`, which is compatible with both React 18 and 19.

## Using React 19 Features

### Static Site Generation

React 19 introduces new APIs for static site generation that can improve performance by waiting for data to load. Mountaineer automatically uses these APIs when available.

### Custom Elements

React 19 adds better support for custom elements. When using custom elements in your Mountaineer app with React 19, props will be handled correctly during both SSR and client-side rendering.

## Compatibility Notes

- Existing Mountaineer apps using React 18 should continue to work without changes.
- New apps created with Mountaineer will use React 19 by default.
- If you encounter any issues when upgrading to React 19, please report them on the Mountaineer GitHub repository. 