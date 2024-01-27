from pydantic import BaseModel
from typing import Any

def get_value_by_alias(model: BaseModel | dict[str, Any], alias: str):
    """
    Get the value of a pydantic model by its original JSON key. This will look for both the cast
    name and the original name.

    If there's a tie, the cast name will win.

    """
    if isinstance(model, dict):
        # Dictionaries can't have aliases
        return model[alias]

    try:
        return getattr(model, alias)
    except AttributeError:
        # Only run the following if we're not able to find the cast name since in involves
        # an O(n) operation
        for field_name, field in model.model_fields.items():
            if field.alias == alias:
                return getattr(model, field_name)
    raise AttributeError(f"No key `{alias}` found in model, either alias or cast value.")
