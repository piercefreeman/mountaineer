from enum import StrEnum

class OpenAPISchemaType(StrEnum):
    OBJECT = "object"
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ARRAY = "array"
    # Typically used to indicate an optional type within an anyOf statement
    NULL = "null"
