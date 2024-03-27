# API Exception

The `APIException` is the root exception that you should inherit for errors that are thrown within action functions. This syntax allows your frontend to pick up on the error parameters. APIExceptions are just Pydantic BaseModels with a few helpful defaults, and a metaclass that allows them to work natively with HTTPExceptions.

::: mountaineer.exceptions.APIException
    options:
      members:
        - status_code
        - detail
