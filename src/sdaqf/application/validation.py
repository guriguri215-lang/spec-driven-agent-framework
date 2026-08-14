"""Runtime validation for the repository sample-project contract."""

from __future__ import annotations

import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdaqf.application.baselines import (
    BaselineContractError,
    requirement_records_from_list,
)
from sdaqf.application.contracts import ContractError, parse_json_bytes
from sdaqf.application.schema_validation import (
    LocalSchemaValidator,
    SchemaValidationError,
)
from sdaqf.application.ui_validation import parse_manifest_ui
from sdaqf.application.workspace import is_reparse_point

_MAX_SAMPLE_BYTES = 1_000_000
_SCHEMA_BY_FILE = {
    "manifest.json": "project-manifest.schema.json",
    "requirements.json": "requirement.schema.json",
    "evidence.json": "evidence.schema.json",
    "approval.json": "approval.schema.json",
    "execution-attempt.json": "execution-attempt.schema.json",
    "handoff.json": "handoff.schema.json",
    "tool-registry.json": "tool-registry.schema.json",
    "agent-registry.json": "agent-registry.schema.json",
}


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
    """Apply the published schemas and existing semantic manifest contract."""

    _FILES = tuple(_SCHEMA_BY_FILE)

    def __init__(self, schemas_dir: Path | None = None) -> None:
        self._schemas_dir = _published_schemas_dir() if schemas_dir is None else schemas_dir

    def validate(self, project_dir: Path) -> ValidationReport:
        """Validate every required sample without following unsafe paths."""

        errors: list[str] = []
        checked: list[str] = []
        if is_reparse_point(project_dir) or not project_dir.is_dir():
            return ValidationReport(False, ("Project path must be a regular directory.",), ())
        if is_reparse_point(self._schemas_dir) or not self._schemas_dir.is_dir():
            return ValidationReport(False, ("Published schema directory is unavailable.",), ())

        validator = LocalSchemaValidator(self._schemas_dir)
        payloads: dict[str, Any] = {}
        schema_valid: set[str] = set()
        for filename in self._FILES:
            path = project_dir / filename
            if not path.is_file() or path.is_symlink() or is_reparse_point(path):
                errors.append(f"{filename}: required regular file is missing.")
                continue
            try:
                if path.stat().st_size > _MAX_SAMPLE_BYTES:
                    raise ContractError("file exceeds the size limit")
                payload = _load_strict_json(path)
            except (ContractError, OSError) as exc:
                errors.append(f"{filename}: invalid JSON ({exc}).")
                continue
            payloads[filename] = payload
            checked.append(filename)
            try:
                validator.validate(_SCHEMA_BY_FILE[filename], payload)
            except SchemaValidationError as exc:
                errors.append(f"{filename}: schema validation failed ({exc}).")
            except (AssertionError, OSError, UnicodeError, ValueError) as exc:
                errors.append(f"{filename}: published schema is unavailable ({exc}).")
            else:
                schema_valid.add(filename)

        if "manifest.json" in schema_valid:
            try:
                parse_manifest_ui(payloads["manifest.json"], legacy_syntax=True)
            except ContractError as exc:
                errors.append(f"manifest.json: semantic validation failed ({exc}).")
        if "requirements.json" in schema_valid:
            try:
                requirement_records_from_list(payloads["requirements.json"])
            except BaselineContractError as exc:
                errors.append(f"requirements.json: semantic validation failed ({exc}).")

        return ValidationReport(not errors, tuple(errors), tuple(checked))


def _load_strict_json(path: Path) -> object:
    """Decode one instance while rejecting duplicate keys and non-finite numbers."""

    return parse_json_bytes(
        path.read_bytes(),
        path.name,
        maximum_bytes=_MAX_SAMPLE_BYTES,
    )


def _published_schemas_dir() -> Path:
    """Resolve the one published schema set in checkout or installed layouts."""

    module = Path(__file__).resolve()
    checkout = module.parents[3]
    if (checkout / "pyproject.toml").is_file() and module.parent.parent.parent.name == "src":
        return checkout / "schemas"
    target_install = module.parents[2] / "share" / "sdaqf" / "schemas"
    if target_install.exists() or is_reparse_point(target_install):
        return target_install
    return Path(sysconfig.get_path("data")) / "share" / "sdaqf" / "schemas"
