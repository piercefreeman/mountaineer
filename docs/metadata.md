# Page Metadata

Pages will have metadata associated with them: page title, description, tags, stylesheets, etc. Mountaineer specifies this metadata in the Python layer, during the initial render.

Each `RenderBase` schema implements a `metadata` attribute. This metadata lets you customize the different fields that are injected in your html <head> tag:

```python
class Metadata(BaseModel):
    title: str | None = None
    metas: list[MetaAttribute] = []
    links: list[LinkAttribute] = []
```

## Title

Setting a page title is pretty straightforward. You just return a custom Metadata instance within your `render()` function. Because the metadata logic is located in-scope of your other business logic, you can access the full suit of calculated values. This is helpful to conditionally generate a dynamic title - like injecting a user's account name, number of new messages, etc.

```python
class MyRender(RenderBase):
    pass

def render() -> MyRender:
    return MyRender(
        metadata=Metadata(
            title="My Title"
        )
    )
```

## Meta and Links

We provide a pretty vanilla syntax within `Metadata` so you can specify any <meta> and <link> elements you'd liek. We do this with the recognition that only some meta tag values have been standardized, and others are left to the browser implementations or web crawlers to parse them appropriately.

You'll typically instantiate a <meta> tag like this:

```python
class MyRender(RenderBase):
    pass

def render() -> MyRender:
    return MyRender(
        metadata=Metadata(
            metas=MetaAttribute(
                "og:meta",
                content="Some meta content",
            )
        )
    )
```

We have a limited number of helper <meta> constructors, particularly in cases where there are standard definitions of complex meta values:

**ThemeColorMeta:** Customizes the default color that is attached to the page.

```python
ThemeColorMeta(
    color="white",
    media="light",
)
```

**ViewportMeta:** Defines the bounds on the current page and how much users are able to zoom.

```python
ViewportMeta(
    initial_scale=1.0,
    maximum_scale=2.0,
    user_scalable=True,
)
```

## Global Metadata

For metadata that you know should appear on every page (like stylesheets or global scripts), you can add a metadata tag to your app controller:

```python
controller = AppController(
    view_root=get_view_path(""),
    global_metadata=Metadata(
        links=[LinkAttribute(rel="stylesheet", href="/static/main.css")]
    ),
)
```
