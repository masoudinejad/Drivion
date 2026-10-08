"""Shared validation and override behavior for configuration models."""

from typing import Self

from pydantic import BaseModel, ConfigDict


class ConfigModel(BaseModel):
    """Strict settings with validated, non-mutating programmatic overrides."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        revalidate_instances="always",
    )

    def with_overrides(self, **overrides: object) -> Self:
        """Replace supplied fields and validate the complete resulting model.

        Nested sections are replaced, not recursively merged. Use a section's
        with_overrides first when changing only some of its fields.
        """
        values = self.model_dump()
        for name, value in overrides.items():
            values[name] = value.model_dump() if isinstance(value, BaseModel) else value
        return type(self).model_validate(values)
