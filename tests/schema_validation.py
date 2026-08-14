"""Compatibility import for the production JSON Schema authority."""

from sdaqf.application.schema_validation import (
    LocalSchemaValidator,
    SchemaValidationError,
)

__all__ = ["LocalSchemaValidator", "SchemaValidationError"]
