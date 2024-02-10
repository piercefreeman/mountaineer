# Plugins

Plugins currently have a few conventions:

`Dependencies` - provide a single class to manage dependencies. Anytime you need access to the plugin objects in an action or render(), you should look to the Dependencies object to grab the dependency injection functions.

`Model` - provide base models that aren't marked with `table=True`. To keep your data model definition, you need to subclass these models to add them to your project. This has the benefit of allowing you to implement other fields that extend the base model.

`Controller` - provide a fully-working controller that you can subclass to add to your project. You can alternatively subclass it to add additional actions, pass additional render data, or implement a new view that better matches your site styling.
