"""Small deterministic validators for the repository sample contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdaqf.application.workspace import is_reparse_point

_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9-]*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Validation result for a sample project."""

    valid: bool
    errors: tuple[str, ...]
    files_checked: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "files_checked": list(self.files_checked),
        }


class ProjectValidator:
    """Validate the project manifest and supporting sample shapes."""

    _FILES = (
        "manifest.json",
        "requirements.json",
        "evidence.json",
        "approval.json",
        "execution-attempt.json",
        "handoff.json",
        "tool-registry.json",
        "agent-registry.json",
    )

    def validate(self, project_dir: Path) -> ValidationReport:
        """Validate every required sample without following unsafe paths."""

        errors: list[str] = []
        checked: list[str] = []
        if is_reparse_point(project_dir) or not project_dir.is_dir():
            return ValidationReport(False, ("Project path must be a regular directory.",), ())

        payloads: dict[str, Any] = {}
        for filename in self._FILES:
            path = project_dir / filename
            if not path.is_file() or is_reparse_point(path):
                errors.append(f"{filename}: required regular file is missing.")
                continue
            try:
                payloads[filename] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"{filename}: invalid JSON ({type(exc).__name__}).")
                continue
            checked.append(filename)

        if "manifest.json" in payloads:
            errors.extend(self._validate_manifest(payloads["manifest.json"]))
        if "requirements.json" in payloads:
            errors.extend(self._validate_requirements(payloads["requirements.json"]))
        for filename in self._FILES[2:]:
            if filename in payloads and not isinstance(payloads[filename], dict):
                errors.append(f"{filename}: top-level value must be an object.")

        return ValidationReport(not errors, tuple(errors), tuple(checked))

    @staticmethod
    def _validate_manifest(payload: Any) -> list[str]:
        if not isinstance(payload, dict):
            return ["manifest.json: top-level value must be an object."]
        errors: list[str] = []
        for key in ("schema_version", "project_id", "title", "source_spec"):
            if key not in payload:
                errors.append(f"manifest.json: missing {key}.")
        project_id = payload.get("project_id")
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-z0-9-]+", project_id):
            errors.append("manifest.json: project_id must use lowercase ASCII words.")
        source_spec = payload.get("source_spec")
        if not isinstance(source_spec, dict):
            errors.append("manifest.json: source_spec must be an object.")
        elif not isinstance(source_spec.get("sha256"), str) or not _SHA256_PATTERN.fullmatch(
            source_spec["sha256"]
        ):
            errors.append("manifest.json: source_spec.sha256 must be a SHA-256 digest.")
        return errors

    @staticmethod
    def _validate_requirements(payload: Any) -> list[str]:
        if not isinstance(payload, list):
            return ["requirements.json: top-level value must be an array."]
        errors: list[str] = []
        identifiers: list[str] = []
        for index, requirement in enumerate(payload):
            prefix = f"requirements.json[{index}]"
            if not isinstance(requirement, dict):
                errors.append(f"{prefix}: item must be an object.")
                continue
            identifier = requirement.get("id")
            if not isinstance(identifier, str) or not _ID_PATTERN.fullmatch(identifier):
                errors.append(f"{prefix}: id must be an uppercase stable identifier.")
            else:
                identifiers.append(identifier)
            if not isinstance(requirement.get("statement"), str) or not requirement[
                "statement"
            ].strip():
                errors.append(f"{prefix}: statement must not be empty.")
            criteria = requirement.get("acceptance_criteria")
            if not isinstance(criteria, list) or not criteria:
                errors.append(f"{prefix}: acceptance_criteria must not be empty.")
        if len(set(identifiers)) != len(identifiers):
            errors.append("requirements.json: requirement identifiers must be unique.")
        return errors
