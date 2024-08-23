# PostCSS & Tailwind

## PostCSS

[PostCSS](https://postcss.org/) is a compiler for CSS. It enables buildtime transformation of CSS files to convert SCSS, LESS, or other CSS-like languages into standard CSS. It also has utilities for polyfills and browser-specific prefixes. I think of it like a swiss-army knife for CSS: it helps assure that your styling intentions are actually rendered uniformily across browsers.

PostCSS support is handled as a buildtime plugin with Mountaineer. It's disabled by default. To enable, make sure you have `postcss-cli` installed within your `views` project:

```bash
npm install postcss-cli
```

After this you can leverage the `PostCSSBundler` within your custom build pipeline:

```python
from mountaineer.client_compiler.postcss import PostCSSBundler

controller = AppController(
    custom_builders=[
        PostCSSBundler(),
    ],
)
```

Adding the PostCSSBundler will find all the `.css` that you have specified within your `views` directory and pass them through PostCSS. Let's say you have the following CSS files:

```
/views/app/home/style.css
/views/app/detail/style.css
```

The compiler will pass each through PostCSS and deposit these artifacts into:

```
/views/_static/home_style.css
/views/_static/detail_style.css
```

You can then import this CSS file in whatever <meta> tag is relevant to your project. See the [metadata documentation](./metadata.md) for more details on how to do this.

## Tailwind

Tailwind uses PostCSS to handle the tree shaking and project analysis that allows it to output the minimal amount of CSS tags to correctly render your project. If you set up the PostCSS extension like described above, you should be able to follow the typical Tailwind [setup](https://tailwindcss.com/docs/installation) steps.

```typescript title="views/app/tailwind.config.ts"
module.exports = {
  content: ["./app/**/*.{html,tsx,jsx,ts,js}"],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

```css title="views/app/main.css"
@tailwind base;
@tailwind components;
@tailwind utilities;
```

Then export the built styles into your global metadata:

```python
controller = AppController(
    config=AppConfig(),
    global_metadata=Metadata(
        links=[LinkAttribute(rel="stylesheet", href="/static/app_main.css")]
    ),
    custom_builders=[
        PostCSSBundler(),
    ],
)
```
