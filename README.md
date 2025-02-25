![Mountaineer Header](https://raw.githubusercontent.com/piercefreeman/mountaineer/main/media/header.png)

<p align="center"><i>Move fast. Climb mountains. Don't break things.</i></p>

Mountaineer 🏔️ is a framework to easily build webapps in Python and React. If you've used either of these languages before for development, we think you'll be right at home.

## Main Features

Each framework has its own unique features and tradeoffs. Mountaineer focuses on developer productivity above all else, with production speed a close second.

- 📝 Typehints up and down the stack: frontend, backend, and database
- 🎙️ Trivially easy client<->server communication, data binding, and function calling
- 🌎 Optimized server rendering for better accessibility and SEO
- 🏹 Static analysis of web pages for strong validation: link validity, data access, etc.
- 🤩 Skip the API or Node.js server just to serve frontend clients

> We built Mountaineer out of a frustration that we were reinventing the webapp wheel time and time again. We love Python for backend development and the interactivity of React for frontend UX. But they don't work seamlessly together without a fair amount of glue. So: we built the glue. While we were at it, we embedded a V8 engine to provide server-side rendering, added conventions for application configuration, built native Typescript integrations, and more. Our vision is for you to import one slim dependency and you're off to the races.
>
> We're eager for you to give Mountaineer a try, and equally devoted to making you successful if you like it. File an Issue if you see anything unexpected or if there's a steeper learning curve than you expect. There's much more to do - and we're excited to do it together.
>
> ~ Pierce

## Getting Started

### New Project

To get started as quickly as possible, we bundle a project generator that sets up a simple project after a quick Q&A. Make sure you have pipx [installed](https://pipx.pypa.io/stable/installation/).

```bash
$ pipx run create-mountaineer-app

? Project name [my-project]: my_webapp
? Author [Pierce Freeman <pierce@freeman.vc>] Default
? Use poetry for dependency management? [Yes] Yes
? Create stub MVC files? [Yes] Yes
? Use Tailwind CSS? [Yes] Yes
? Add editor configuration? [vscode] vscode
```

Mountaineer projects all follow a similar structure. After running this CLI you should see a new folder called `my_webapp`, with folders like the following:

```
my_webapp
  /controllers
    /home.py
  /models
    /mymodel.py
  /views
    /app
      /home
        /page.tsx
      /layout.tsx
    /package.json
    /tsconfig.json
  /app.py
  /cli.py
pyproject.toml
poetry.lock
```

Every service file is nested under the `my_webapp` root package. Views are defined in a disk-based hierarchy (`views`) where nested routes are in nested folders. This folder acts as your React project and is where you can define requirements and build parameters in `package.json` and `tsconfig.json`. Controllers are defined nearby in a flat folder (`controllers`) where each route is a separate file. Everything else is just standard Python code for you to modify as needed.

### Development

If you're starting a new application from scratch, you'll typically want to create your new database tables. Make sure you have postgres running. We bundle a docker compose file for convenience with `create-mountaineer-app`.

```bash
docker compose up -d
poetry run createdb
```

Of course you can also use an existing database instance, simply configure it in the `.env` file in the project root.

Mountaineer relies on watching your project for changes and doing progressive compilation. We provide a few CLI commands to help with this.

While doing development work, you'll usually want to preview the frontend and automatically build dependent files. You can do this with:

```bash
$ poetry run runserver

INFO:     Started server process [93111]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:5006 (Press CTRL+C to quit)
```

Navigate to http://127.0.0.1:5006 to see your new webapp running.

Or, if you just want to watch the source tree for changes without hosting the server. Watching will allow your frontend to pick up API definitions from your backend controllers:

```bash
$ poetry run watch
```

Both of these CLI commands are specified in your project's `cli.py` file.

### Documentation

- [Mountaineer Tutorial](https://mountaineer.sh/mountaineer/guides/quickstart)
- [Concepts](https://mountaineer.sh/mountaineer/guides/views)
- [API](https://mountaineer.sh/mountaineer/api/actions)
