"""Deterministic repository Skill and template lifecycle validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import cast

from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.tooling import TemplateDefinition

_MAX_SKILL_BYTES = 64 * 1024
_MAX_TEMPLATE_BYTES = 1_000_000
_MAX_ITEMS = 64
_SLUG = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$")
_REQUIRED_HEADINGS = (
    "## Trigger",
    "## Do not use",
    "## Procedure",
    "## Output",
    "## Verification",
    "## Risks",
)
_PLACEHOLDERS = {"pending", "todo", "unknown", "tbd"}
_WINDOWS_RESERVED = {
    "aux",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}


class SkillContractError(ValueError):
    """One bounded Skill or template contract failure."""


class LifecycleState(StrEnum):
    """Deterministic lifecycle state."""

    DISCOVERED = "discovered"
    VALIDATED = "validated"
    COMPATIBLE = "compatible"
    BLOCKED = "blocked"
    SELECTED = "selected"


@dataclass(frozen=True, slots=True)
class SkillLifecycle:
    """Validated Skill state transitions."""

    name: str
    digest: str
    transitions: tuple[LifecycleState, ...]

    @property
    def state(self) -> LifecycleState:
        """Return the terminal lifecycle state."""

        return self.transitions[-1]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "name": self.name,
            "digest": self.digest,
            "transitions": [item.value for item in self.transitions],
            "state": self.state.value,
        }


@dataclass(frozen=True, slots=True)
class TemplateLifecycle:
    """Evaluated template compatibility and selection state."""

    template_id: str
    transitions: tuple[LifecycleState, ...]
    blockers: tuple[str, ...]

    @property
    def state(self) -> LifecycleState:
        """Return the terminal lifecycle state."""

        return self.transitions[-1]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "template_id": self.template_id,
            "transitions": [item.value for item in self.transitions],
            "state": self.state.value,
            "blockers": list(self.blockers),
        }


def validate_skills(
    root: Path,
    *,
    selected: tuple[str, ...] = (),
) -> tuple[SkillLifecycle, ...]:
    """Discover and validate repository Skills in deterministic order."""

    if root.is_symlink() or is_reparse_point(root) or not root.is_dir():
        raise SkillContractError("Skill root must be a regular, unlinked directory.")
    if len(selected) != len(set(selected)):
        raise SkillContractError("Selected Skill names must be unique.")
    skill_paths = tuple(sorted(root.glob("*/SKILL.md"), key=lambda item: item.as_posix()))
    if not skill_paths:
        raise SkillContractError("Skill root contains no Skills.")
    records: list[SkillLifecycle] = []
    for path in skill_paths:
        if path.parent.parent != root:
            raise SkillContractError("Skill paths must be one directory below the root.")
        directory_name = path.parent.name
        if (
            not _SLUG.fullmatch(directory_name)
            or directory_name.casefold() in _WINDOWS_RESERVED
        ):
            raise SkillContractError("Skill directory name must be a safe slug.")
        if (
            path.is_symlink()
            or is_reparse_point(path)
            or is_reparse_point(path.parent)
            or not path.is_file()
        ):
            raise SkillContractError("Skill files and directories must be unlinked.")
        try:
            if path.stat().st_size > _MAX_SKILL_BYTES:
                raise SkillContractError("Skill file exceeds the size limit.")
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="strict")
            text = text.replace("\r\n", "\n")
            if "\r" in text:
                raise SkillContractError(
                    "Skill file contains unsupported line endings."
                )
        except (OSError, UnicodeError) as exc:
            raise SkillContractError("Skill file could not be read.") from exc
        frontmatter = _frontmatter(text)
        if set(frontmatter) != {"name", "description"}:
            raise SkillContractError(
                "Skill front matter must contain only name and description."
            )
        if frontmatter["name"] != directory_name:
            raise SkillContractError("Skill name must match its directory.")
        if not frontmatter["description"].strip():
            raise SkillContractError("Skill description must not be empty.")
        for heading in _REQUIRED_HEADINGS:
            marker = f"{heading}\n"
            if marker not in text:
                raise SkillContractError(f"Skill is missing required heading: {heading}")
            body = text.split(marker, maxsplit=1)[1].split("\n## ", maxsplit=1)[0]
            if not body.strip():
                raise SkillContractError(f"Skill section must not be empty: {heading}")
        transitions = [
            LifecycleState.DISCOVERED,
            LifecycleState.VALIDATED,
            LifecycleState.COMPATIBLE,
        ]
        if directory_name in selected:
            transitions.append(LifecycleState.SELECTED)
        import hashlib

        records.append(
            SkillLifecycle(
                name=directory_name,
                digest=hashlib.sha256(raw).hexdigest().upper(),
                transitions=tuple(transitions),
            )
        )
    names = {record.name for record in records}
    missing_selected = set(selected) - names
    if missing_selected:
        raise SkillContractError(
            "Selected Skill is unavailable: " + ", ".join(sorted(missing_selected))
        )
    return tuple(records)


def load_template_registry(path: Path) -> tuple[TemplateDefinition, ...]:
    """Load strict template metadata without selecting a license."""

    root = _load_object(path, "template registry")
    _only_keys(root, {"schema_version", "templates"}, "template registry")
    if _string(root.get("schema_version"), "schema_version") != "1.0":
        raise SkillContractError("Template Registry schema_version must be 1.0.")
    raw_templates = _array(root.get("templates"), "templates")
    templates = tuple(
        _parse_template(item, f"templates[{index}]")
        for index, item in enumerate(raw_templates)
    )
    if not templates:
        raise SkillContractError("templates must not be empty.")
    identifiers = [item.template_id.casefold() for item in templates]
    if len(identifiers) != len(set(identifiers)):
        raise SkillContractError("Template identifiers must be unique.")
    return tuple(sorted(templates, key=lambda item: item.template_id))


def evaluate_templates(
    templates: tuple[TemplateDefinition, ...],
    *,
    framework_version: str,
    available_dependencies: tuple[str, ...],
    active_conditions: tuple[str, ...] = (),
    selected: tuple[str, ...] = (),
) -> tuple[TemplateLifecycle, ...]:
    """Evaluate compatibility and selection without mutating templates."""

    if not _VERSION.fullmatch(framework_version):
        raise SkillContractError("framework_version must be numeric.")
    records: list[TemplateLifecycle] = []
    available = set(available_dependencies)
    active = set(active_conditions)
    selected_set = set(selected)
    known = {item.template_id for item in templates}
    if selected_set - known:
        raise SkillContractError("Selected template is unavailable.")
    for template in templates:
        blockers: list[str] = []
        if template.compatible_version != framework_version:
            blockers.append("incompatible framework version")
        missing = set(template.dependencies) - available
        if missing:
            blockers.append("missing dependencies: " + ", ".join(sorted(missing)))
        prohibited = set(template.prohibited_conditions) & active
        if prohibited:
            blockers.append(
                "prohibited conditions: " + ", ".join(sorted(prohibited))
            )
        transitions = [LifecycleState.DISCOVERED, LifecycleState.VALIDATED]
        if blockers:
            transitions.append(LifecycleState.BLOCKED)
            if template.template_id in selected_set:
                raise SkillContractError("A blocked template cannot be selected.")
        else:
            transitions.append(LifecycleState.COMPATIBLE)
            if template.template_id in selected_set:
                transitions.append(LifecycleState.SELECTED)
        records.append(
            TemplateLifecycle(
                template_id=template.template_id,
                transitions=tuple(transitions),
                blockers=tuple(blockers),
            )
        )
    return tuple(records)


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise SkillContractError("Skill must start with front matter.")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise SkillContractError("Skill front matter is not closed.") from exc
    values: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if separator != ":" or not key or not value.strip():
            raise SkillContractError("Skill front matter contains an invalid line.")
        if key in values:
            raise SkillContractError("Skill front matter keys must be unique.")
        values[key] = value.strip()
    return values


def _parse_template(value: object, where: str) -> TemplateDefinition:
    record = _object(value, where)
    _only_keys(
        record,
        {
            "template_id",
            "target",
            "compatible_version",
            "dependencies",
            "provenance",
            "license_status",
            "prohibited_conditions",
            "validated_on",
        },
        where,
    )
    template_id = _string(record.get("template_id"), f"{where}.template_id")
    if not _SLUG.fullmatch(template_id):
        raise SkillContractError(f"{where}.template_id is invalid.")
    compatible = _string(
        record.get("compatible_version"),
        f"{where}.compatible_version",
    )
    if not _VERSION.fullmatch(compatible):
        raise SkillContractError(f"{where}.compatible_version is invalid.")
    provenance = _string(record.get("provenance"), f"{where}.provenance")
    license_status = _string(
        record.get("license_status"),
        f"{where}.license_status",
    )
    if license_status not in {"internal", "not-selected", "external-approved"}:
        raise SkillContractError(f"{where}.license_status is unsupported.")
    if provenance.casefold() in _PLACEHOLDERS:
        raise SkillContractError(f"{where}.provenance must be resolved.")
    validated_on = _string(record.get("validated_on"), f"{where}.validated_on")
    try:
        date.fromisoformat(validated_on)
    except ValueError as exc:
        raise SkillContractError(f"{where}.validated_on is invalid.") from exc
    return TemplateDefinition(
        template_id=template_id,
        target=_safe_relative_path(
            _string(record.get("target"), f"{where}.target"),
            f"{where}.target",
        ),
        compatible_version=compatible,
        dependencies=_string_tuple(
            record.get("dependencies"),
            f"{where}.dependencies",
            allow_empty=True,
        ),
        provenance=provenance,
        license_status=license_status,
        prohibited_conditions=_string_tuple(
            record.get("prohibited_conditions"),
            f"{where}.prohibited_conditions",
            allow_empty=True,
        ),
        validated_on=validated_on,
    )


def _safe_relative_path(value: str, where: str) -> str:
    if (
        len(value) > 240
        or "\\" in value
        or ":" in value
        or value.startswith(("/", "~"))
    ):
        raise SkillContractError(f"{where} must be a safe relative path.")
    parts = PurePosixPath(value).parts
    if not parts or any(
        part in {"", ".", ".."}
        or part.endswith((" ", "."))
        or part.casefold().split(".", maxsplit=1)[0] in _WINDOWS_RESERVED
        for part in parts
    ):
        raise SkillContractError(f"{where} must be a safe relative path.")
    return "/".join(parts)


def _load_object(path: Path, label: str) -> dict[str, object]:
    if path.suffix.casefold() != ".json":
        raise SkillContractError(f"{label} must be a JSON file.")
    if path.is_symlink() or is_reparse_point(path) or not path.is_file():
        raise SkillContractError(f"{label} must be a regular, unlinked file.")
    try:
        if path.stat().st_size > _MAX_TEMPLATE_BYTES:
            raise SkillContractError(f"{label} exceeds the size limit.")
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise SkillContractError(f"{label} could not be read.") from exc
    try:
        decoded: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SkillContractError(f"{label} is not valid JSON.") from exc
    return _object(decoded, label)


def _object(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SkillContractError(f"{where} must be an object.")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise SkillContractError(f"{where} keys must be strings.")
    return {cast(str, key): item for key, item in raw.items()}


def _array(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise SkillContractError(f"{where} must be an array.")
    if len(value) > _MAX_ITEMS:
        raise SkillContractError(f"{where} exceeds the item limit.")
    return cast(list[object], value)


def _only_keys(
    value: dict[str, object],
    allowed: set[str],
    where: str,
) -> None:
    missing = allowed - set(value)
    extra = set(value) - allowed
    if missing:
        raise SkillContractError(
            f"{where} is missing fields: {', '.join(sorted(missing))}."
        )
    if extra:
        raise SkillContractError(
            f"{where} contains unknown fields: {', '.join(sorted(extra))}."
        )


def _string(value: object, where: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 500
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise SkillContractError(
            f"{where} must be a bounded non-empty single-line string."
        )
    return value


def _string_tuple(
    value: object,
    where: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    items = _array(value, where)
    parsed = tuple(_string(item, where) for item in items)
    if not allow_empty and not parsed:
        raise SkillContractError(f"{where} must not be empty.")
    if len(parsed) != len(set(item.casefold() for item in parsed)):
        raise SkillContractError(f"{where} values must be unique.")
    return parsed
