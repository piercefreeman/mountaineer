# Links

In a typical webapp, you'll have a lot of links. Most will be internal to your site: detail pages, settings, profiles, etc. Traditionally, developers format these links manually and hope they don't break over time as routes update.

In Mountaineer, generating links is baked into the client side routes. For every controller you define, we'll generate a link interface that defines the parameters that controller accepts. This interface will update as your route declarations do, so you're guaranteed to always generate the latest links to successfully resolve that controller.

Controllers set the parameters that they need to render their views by configuring the `render()` function with the required parameters:

```python
class DetailController:
    url = "/detail/{detail_id}"

    def render(self, detail_id: int, checking_out: bool = False) -> MyDetailData:
        ...
```

Alongside generating the appropriate API and router files, Mountaineer will detect this render signature and produce a link generator.

This particular generator will require a `detail_id` and support an optional `checking_out` boolean. The `detail_id` is required because it's a part of the controller url. `checking_out` on the other hand is optional, since it has a default keyword argument in the case that another value isn't provided.

On the client side, you can now create these dynamic links anywhere within your application. Mount the server state of the current view and use the included `linkGenerator`.

```typescript
const MyHomeRoute = () => {
  const serverState = useServer();

  return (
    <a
      href={serverState.linkGenerator.detailController({
        detail_id: "9280ca4d-e607-486a-a343-7bbaae6b5a86",
      })}
    >
      Detail Link
    </a>
  )
}
```

Not providing the `detail_id`, or providing an incorrect type for the ID, will throw a typescript error at compile time.

## Link Parameters

There are two types of dynamic URL parameters:

- Path Variables: `/product/[product_id]`
- Query Variables: `/posts?page=[page_num]`

Both path variables and query variables are exposed as interface definitions within the link generator.
