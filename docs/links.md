## Links

Most pages in a webapp end up being dynamic - specifying a ID in the URL path, a query param to change pages, etc. Usually you'll format these manually and hope they don't break over time as routes update.

While Filzl allows you to do this, it also provides a way to generate links in a type-safe way. This is done by defining a `linkGenerator` that is used to generate links to all visible views.
