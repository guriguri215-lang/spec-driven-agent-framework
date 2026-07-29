"""Dependency-free validator for the JSON Schema subset published by this repo."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class SchemaValidationError(ValueError):
    """A sample does not satisfy its published schema."""


class LocalSchemaValidator:
    """Validate every assertion keyword used by the repository schemas."""

    def __init__(self, schemas_dir: Path) -> None:
        self._schemas_dir = schemas_dir
        self._documents: dict[str, dict[str, Any]] = {}

    def validate(self, schema_name: str, instance: object) -> None:
        schema = self._load(schema_name)
        self._validate(schema, instance, schema, schema_name, "$")

    def _load(self, name: str) -> dict[str, Any]:
        cached = self._documents.get(name)
        if cached is not None:
            return cached
        decoded: object = json.loads(
            (self._schemas_dir / name).read_text(encoding="utf-8")
        )
        if not isinstance(decoded, dict):
            raise AssertionError(f"{name} schema root must be an object")
        self._documents[name] = decoded
        return decoded

    def _validate(
        self,
        schema: dict[str, Any],
        instance: object,
        document: dict[str, Any],
        document_name: str,
        where: str,
    ) -> None:
        supported = {
            "$schema",
            "$id",
            "$ref",
            "$defs",
            "title",
            "description",
            "type",
            "const",
            "enum",
            "required",
            "properties",
            "additionalProperties",
            "propertyNames",
            "minProperties",
            "maxProperties",
            "items",
            "minItems",
            "maxItems",
            "uniqueItems",
            "minLength",
            "maxLength",
            "pattern",
            "minimum",
            "maximum",
            "format",
            "oneOf",
            "allOf",
            "if",
            "then",
            "not",
            "contains",
        }
        unknown = set(schema) - supported
        if unknown:
            raise AssertionError(
                f"unsupported schema keyword {sorted(unknown)[0]} at {where}"
            )
        reference = schema.get("$ref")
        if reference is not None:
            target, target_document, target_name = self._resolve(
                str(reference),
                document,
                document_name,
            )
            self._validate(target, instance, target_document, target_name, where)
        if "const" in schema and instance != schema["const"]:
            self._fail(where, "const")
        negated = schema.get("not")
        if isinstance(negated, dict) and self._is_valid(
            negated,
            instance,
            document,
            document_name,
            where,
        ):
            self._fail(where, "not")
        if "enum" in schema and instance not in schema["enum"]:
            self._fail(where, "enum")
        if "type" in schema and not self._matches_type(instance, schema["type"]):
            self._fail(where, "type")
        if isinstance(instance, dict):
            self._validate_object(schema, instance, document, document_name, where)
        if isinstance(instance, list):
            self._validate_array(schema, instance, document, document_name, where)
        if isinstance(instance, str):
            self._validate_string(schema, instance, where)
        if isinstance(instance, int) and not isinstance(instance, bool):
            if "minimum" in schema and instance < int(schema["minimum"]):
                self._fail(where, "minimum")
            if "maximum" in schema and instance > int(schema["maximum"]):
                self._fail(where, "maximum")
        one_of = schema.get("oneOf")
        if isinstance(one_of, list):
            matches = sum(
                self._is_valid(option, instance, document, document_name, where)
                for option in one_of
            )
            if matches != 1:
                self._fail(where, "oneOf")
        all_of = schema.get("allOf")
        if isinstance(all_of, list):
            for option in all_of:
                self._validate(option, instance, document, document_name, where)
        condition = schema.get("if")
        consequence = schema.get("then")
        if (
            isinstance(condition, dict)
            and isinstance(consequence, dict)
            and self._is_valid(condition, instance, document, document_name, where)
        ):
            self._validate(consequence, instance, document, document_name, where)

    def _validate_object(
        self,
        schema: dict[str, Any],
        instance: dict[object, object],
        document: dict[str, Any],
        document_name: str,
        where: str,
    ) -> None:
        if not all(isinstance(key, str) for key in instance):
            self._fail(where, "string property names")
        required = schema.get("required", [])
        if any(key not in instance for key in required):
            self._fail(where, "required")
        if "minProperties" in schema and len(instance) < int(schema["minProperties"]):
            self._fail(where, "minProperties")
        if "maxProperties" in schema and len(instance) > int(schema["maxProperties"]):
            self._fail(where, "maxProperties")
        names = schema.get("propertyNames")
        if isinstance(names, dict):
            for key in instance:
                self._validate(names, key, document, document_name, f"{where}.{key}")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                self._fail(where, "additionalProperties")
        additional = schema.get("additionalProperties")
        for key, value in instance.items():
            child = properties.get(key)
            if isinstance(child, dict):
                self._validate(
                    child,
                    value,
                    document,
                    document_name,
                    f"{where}.{key}",
                )
            elif isinstance(additional, dict):
                self._validate(
                    additional,
                    value,
                    document,
                    document_name,
                    f"{where}.{key}",
                )

    def _validate_array(
        self,
        schema: dict[str, Any],
        instance: list[object],
        document: dict[str, Any],
        document_name: str,
        where: str,
    ) -> None:
        if "minItems" in schema and len(instance) < int(schema["minItems"]):
            self._fail(where, "minItems")
        if "maxItems" in schema and len(instance) > int(schema["maxItems"]):
            self._fail(where, "maxItems")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True) for item in instance]
            if len(encoded) != len(set(encoded)):
                self._fail(where, "uniqueItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                self._validate(
                    item_schema,
                    item,
                    document,
                    document_name,
                    f"{where}[{index}]",
                )
        contains = schema.get("contains")
        if isinstance(contains, dict) and not any(
            self._is_valid(
                contains,
                item,
                document,
                document_name,
                f"{where}[{index}]",
            )
            for index, item in enumerate(instance)
        ):
            self._fail(where, "contains")

    def _validate_string(
        self,
        schema: dict[str, Any],
        instance: str,
        where: str,
    ) -> None:
        if "minLength" in schema and len(instance) < int(schema["minLength"]):
            self._fail(where, "minLength")
        if "maxLength" in schema and len(instance) > int(schema["maxLength"]):
            self._fail(where, "maxLength")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, instance) is None:
            self._fail(where, "pattern")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(instance.replace("Z", "+00:00"))
            except ValueError as exc:
                raise SchemaValidationError(f"{where}: format") from exc
            if parsed.tzinfo is None:
                self._fail(where, "format")

    def _resolve(
        self,
        reference: str,
        document: dict[str, Any],
        document_name: str,
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        name, separator, fragment = reference.partition("#")
        target_document = document if not name else self._load(name)
        target_name = name if name else document_name
        target: object = target_document
        if separator and fragment:
            for raw in fragment.lstrip("/").split("/"):
                key = raw.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or key not in target:
                    raise AssertionError(f"unresolved schema reference {reference}")
                target = target[key]
        if not isinstance(target, dict):
            raise AssertionError(f"schema reference is not an object: {reference}")
        return target, target_document, target_name

    def _is_valid(
        self,
        schema: object,
        instance: object,
        document: dict[str, Any],
        document_name: str,
        where: str,
    ) -> bool:
        if not isinstance(schema, dict):
            raise AssertionError(f"schema branch at {where} must be an object")
        try:
            self._validate(schema, instance, document, document_name, where)
        except SchemaValidationError:
            return False
        return True

    @staticmethod
    def _matches_type(instance: object, expected: object) -> bool:
        values = [expected] if isinstance(expected, str) else expected
        if not isinstance(values, list):
            return False
        checks = {
            "object": lambda value: isinstance(value, dict),
            "array": lambda value: isinstance(value, list),
            "string": lambda value: isinstance(value, str),
            "boolean": lambda value: isinstance(value, bool),
            "integer": lambda value: isinstance(value, int)
            and not isinstance(value, bool),
            "null": lambda value: value is None,
        }
        return any(
            isinstance(kind, str)
            and kind in checks
            and checks[kind](instance)
            for kind in values
        )

    @staticmethod
    def _fail(where: str, keyword: str) -> None:
        raise SchemaValidationError(f"{where}: {keyword}")
