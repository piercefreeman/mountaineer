# postcss

[PostCSS](https://postcss.org/) is a compiler for CSS. It enables buildtime transformation of CSS files to convert SCSS, LESS, or other CSS-like languages into standard CSS. It also has utilities for polyfills and browser-specific prefixes. I think of it like a swiss-army knife for CSS: it helps assure that your styling intentions are actually rendered uniformily across browsers.

PostCSS support is handled as a buildtime plugin with mountaineer. It's disabled by default. To enable, make sure you have `postcss-cli` installed within your `views/project.json` file. You'll also need to properly `npm install` the dependencies before running.

```python
from mountaineer.js_compiler.postcss import PostCSSBundler

controller = AppController(
    view_root=get_view_path(""),
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
