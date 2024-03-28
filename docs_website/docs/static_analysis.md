# Static Analysis

A core design consideration in Mountaineer is allowing for full _static analysis_ of your webapps. This term just means that we can verify your code from its text alone without having to run it all. As your webapp grows in scope this becomes increasingly valuable, as it allows you to catch errors early before they become runtime issues. And the more complicated your logic becomes, the more switch conditions and edge cases you're necessarily going to have. Manually testing all that is... not going to be fun.

Since static analysis is a personal choice, we don't yet bundle a type checker within Mountaineer. This page covers some basic suggestions for adding it to your project.

!!! tip

    Adding a type checker to your project might seem like overkill while the scope is still small. But we find that adding it to CI early helps prevent future headaches by taking small steps to correctly annotate your function signatures, resolve ambiguities, and catch bugs while you still have the context of implementation.

## Python

`mypy` and `pyright` are the most popular type checkers for Python. They both effectively do the same thing. `mypy` is a bit more mature and has a larger community, but `pyright` is often preferred by IDEs so you help ensure your dev workflow is the same as your CI verification. We typically use both in our projects to be extra safe.

```bash
poetry add mypy --group dev
poetry add pyright --group dev
```

Then modify your `pyproject.toml` to make as strict as you would like. Here's a good starting point for mypy:

```toml
[tool.mypy]
warn_return_any = true
warn_unused_configs = true
check_untyped_defs = true
plugins = ["pydantic.mypy"]
```

Pyright is already a bit stricter by default, but you can really boost the verbosity by specifying:

```toml
[tool.pyright]
typeCheckingMode = "strict"
```

Then, to run against your project:

```bash
poetry run mypy
poetry run pyright
```

## Typescript

Typescript's main goal as a language extension to Javascript is to provide typechecking and static analysis. These features are built into the default compiler `tsc`. As such, most frontend issues in your Mountaineer project are typically caught when we compile your typescript code with `poetry run build` or progressively with `runserver` or `watch`. However there are some cases where you don't want to perform a full build, like in CI where you just want to validate the current state of your project.

```bash
npm install typescript --save-dev
```

The `tsconfig.json` specifies the level of strictness you want to enforce. These options set to the strictest level will catch the most errors:

```json title="views/tsconfig.json"
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "strictFunctionTypes": true,
    "strictBindCallApply": true,
    "strictPropertyInitialization": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true
  }
}
```

| Parameter                    | Description                                                                                                                               |
|------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| strict                       | Enables all strict type-checking options. Setting this to true is the easiest way to ensure you're using TypeScript's strictest settings. |
| noImplicitAny                | Raises error on expressions and declarations with an implied any type.                                                                    |
| strictNullChecks             | When enabled, null and undefined are not in the domain of every type.                                                                     |
| strictFunctionTypes          | Ensures functions' parameters are correctly typed.                                                                                        |
| strictBindCallApply          | Enforce stricter checking of the bind, call, and apply methods on functions.                                                              |
| strictPropertyInitialization | Ensures class properties are initialized in the constructor.                                                                              |
| noImplicitReturns            | Report error when not all code paths in function return a value.                                                                          |
| noFallthroughCasesInSwitch   | Prevent fall-through cases in switch statements.                                                                                          |

Then, to run against your project:

```json title="views/package.json"
{
  "scripts": {
    "typecheck": "tsc --noEmit"
  }
}
```

```bash
npm run typecheck
```
