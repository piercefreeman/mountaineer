You can deploy your Mountaineer project using whatever container technology you'd like, on whatever hosting provider you'd like. Most hosts at this point mandate or highly encourage containerization of your dependencies with Docker - so we start there.

This page contains a reasonable default configuration to get you started. We make heavy use of multi-stage builds to cache dependencies and minimize the size of your final image that your webservers will have to pull down.

## Docker

First, add the following to your `.dockerignore` file. This will prevent Docker from trying to copy over heavy artifacts that aren't needed for the build.

```title=".dockerignore"
**/node_modules
**/_server
**/_ssr
**/_static
**/_metadata
```

### Image 1: Frontend Dependencies

Our first stage uses `npm` to fetch your frontend dependencies. This is an isolated context since it's the only place we need node / npm in the build pipeline.

```docker
FROM node:20-slim as node-dependencies

WORKDIR /usr/src/app

# We only require the dependency definitions
COPY {my_webapp}/views/package.json {my_webapp}/views/package-lock.json ./
RUN npm install
```

### Image 2: Python Dependencies Base

Our build pipeline requires Poetry and a basic Python configuration in multiple stages. This initial stage sets up the Poetry CLI and a Python 3.11 environment. By default we make use of Docker's `buildx` to compile for linux/amd64 (Intel) since this is what most servers run on. It also lets us leverage our prebuild Mountaineer wheels.

```docker
FROM --platform=linux/amd64 python:3.11-slim as poetry-base

WORKDIR /usr/src/app

# You only need `nodejs` here if you are using the postcss plugin
RUN apt-get update \
    && apt-get install -y --no-install-recommends pipx nodejs

ENV PATH="/root/.local/bin:${PATH}"

RUN pipx install poetry
```

### Image 3: Python Dependencies

Fetch Python dependencies and package them into a virtualenv.

```docker
FROM poetry-base as venv-dependencies

RUN pipx inject poetry poetry-plugin-bundle

# Only copy package requirements to cache them in docker layer
# We don't copy poetry.lock since this is tied to the specific architecture
# of our dev machines
COPY pyproject.toml ./

# Poetry requires a README.md to be present in the project
COPY README.md ./

# Copy the application code
COPY {my_webapp} ./{my_webapp}

# Gather dependencies and place into a new virtualenv
RUN poetry -vvv bundle venv --python=/usr/local/bin/python --only=main /venv
```

### Image 4: Build Frontend to Javascript

Static frontend plugins, provided by Mountaineer.

```docker
FROM poetry-base as server-hooks-builder

COPY pyproject.toml ./
COPY README.md ./

COPY {my_webapp} ./{my_webapp}
COPY --from=node-dependencies /usr/src/app/node_modules ./{my_webapp}/views/node_modules

# Mount the application CLI handlers and build the artifacts
RUN poetry install
RUN poetry run build
```

### Image 5: Final Layer

Combines the raw python files, python dependencies, and the built frontend.

```docker
FROM --platform=linux/amd64 python:3.11-slim as final

# Create and switch to a new user
RUN useradd --create-home appuser
USER appuser

ENV PATH="/venv/bin:$PATH"

WORKDIR /usr/src/app

COPY --from=venv-dependencies /venv /venv
COPY --from=server-hooks-builder /usr/src/app/{my_webapp}/views /venv/lib/python3.11/site-packages/{my_webapp}/views

# Run the application
CMD ["/venv/bin/uvicorn", "{my_webapp}.main:app", "--host", "0.0.0.0", "--port", "3000"]
```

## Local Testing

Once your Docker image is built, the best way to test it is to run it locally with `docker run`.
However you can also simulate what the production service is doing by running:

```bash
poetry run build
ENVIRONMENT=PRODUCTION poetry run uvicorn {my_webapp}.main:app --host localhost --port 5006
```

This runs with production-minified assets and the same configuration as the production server.

## Common Errors

If you see "required file not found" when you try to run this docker image, double check that your venv is pointing to the correct version of Python within the container:

```bash
$ ls -ls /venv/bin

4 -rw-r--r-- 1 root root 2209 Mar 29 00:26 activate
4 -rw-r--r-- 1 root root 1476 Mar 29 00:26 activate.csh
4 -rw-r--r-- 1 root root 3039 Mar 29 00:26 activate.fish
4 -rw-r--r-- 1 root root 2724 Mar 29 00:26 activate.nu
4 -rw-r--r-- 1 root root 1650 Mar 29 00:26 activate.ps1
4 -rw-r--r-- 1 root root 1337 Mar 29 00:26 activate_this.py
4 -rwxr-xr-x 1 root root  212 Mar 29 00:27 dotenv
4 -rwxr-xr-x 1 root root  204 Mar 29 00:27 httpx
0 lrwxrwxrwx 1 root root   25 Mar 29 00:26 python -> /usr/local/bin/python3.11
0 lrwxrwxrwx 1 root root    6 Mar 29 00:26 python3 -> python
0 lrwxrwxrwx 1 root root    6 Mar 29 00:26 python3.11 -> python
4 -rwxr-xr-x 1 root root  207 Mar 29 00:27 tqdm
4 -rwxr-xr-x 1 root root  211 Mar 29 00:27 uvicorn
4 -rwxr-xr-x 1 root root  211 Mar 29 00:27 watchfiles
4 -rwxr-xr-x 1 root root  217 Mar 29 00:27 watchmedo
```

The path `python -> /usr/local/bin/python3.11` should be executable and run the interpreter:

```bash
$ /venv/bin/python --version

Python 3.11.8
```
