
Mountaineer projects all follow a similar structure. This structure is provided by default through `create-mountaineer-app` but you can also construct it yourself.

For a project called `my_webapp`, you should have something like the following:

```
my_webapp/
├── README.md
├── docker compose.yml
├── my_webapp
│   ├── __init__.py
│   ├── app.py
│   ├── cli.py
│   ├── config.py
│   ├── controllers
│   │   ├── __init__.py
│   │   ├── detail.py
│   │   └── home.py
│   ├── main.py
│   ├── models
│   │   ├── __init__.py
│   │   └── detail.py
│   └── views
│       ├── app
│       ├── node_modules
│       ├── package-lock.json
│       ├── package.json
│       ├── postcss.config.js
│       └── tailwind.config.js
├── poetry.lock
└── pyproject.toml
```

Every service file is nested under the `my_webapp` root package. This is just a regular python project - you add new code files wherever you like and import them as you're used to.

### Mandatory Conventions

`views` - this disk based directory includes a nested npm project. Within it you write all your frontend logics and components, which are regular typescript/tsx files.

Nested routes are in nested folders. This folder acts as your React project and is where you can define requirements and build parameters in `package.json` and `tsconfig.json`.

### Suggested Conventions

`controllers` - A controller is the python logic that backs your frontend view. You can define controllers however you like: a flat folder, nesting folders, or via no folders at all mixed in with other code. For simplicity we recommend starting with a single flat controllers folder and refactoring into sub-folders as distinct ownership areas of your code emerge.

`app.py` - Instantiate your controllers and add them to an `AppController` to register them for client access.

`config.py` - Specify the parameters that your application needs to run, to easily customize them: database host settings, secret keys, etc. Configurations can easily read from env variables and are globally accessible throughout your webapp.

`main.py` - Expose your application to [uvicorn](https://www.uvicorn.org/) or another async compatible webserver that follows the ASGI specification (Asynchronous Server Gateway Interface).
