"""Shared strict API schema configuration."""

from pydantic import BaseModel, ConfigDict


class ApiSchema(BaseModel):
    """Reject coercions and undeclared fields at the public API boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)
