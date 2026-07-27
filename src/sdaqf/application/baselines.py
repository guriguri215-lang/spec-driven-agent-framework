"""Validation and loading for the M1 requirement-baseline contract."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.requirements import (
    AcceptanceCriterion,
    Diagnostic,
    DiagnosticKind,
    DiagnosticSeverity,
    RequirementBaseline,
    RequirementPriority,
    RequirementRecord,
    RequirementType,
    SourceMetadata,
    SourceTrace,
    TraceLinks,
    generated_requirement_id,
)

_ID = re.compile(r"^[A-Z][A-Z0-9-]*$")
_BASELINE_ID = re.compile(r"^RB-[0-9A-F]{16}$")
_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_DRIVE_PATH = re.compile(r"^[A-Za-z]:[/\\]")
_MAX_BASELINE_BYTES = 8 * 1024 * 1024


class BaselineContractError(ValueError):
    """A bounded requirement-baseline contract failure."""


def load_baseline(path: Path) -> RequirementBaseline:
    """Load one regular JSON file and validate its complete M1 contract."""

    if path.suffix.lower() != ".json":
        raise BaselineContractError("Requirement baseline must be a JSON file.")
    if path.is_symlink() or is_reparse_point(path) or not path.is_file():
        raise BaselineContractError("Requirement baseline must be a regular, unlinked file.")
    try:
        if path.stat().st_size > _MAX_BASELINE_BYTES:
            raise BaselineContractError("Requirement baseline exceeds the size limit.")
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise BaselineContractError("Requirement baseline could not be read.") from exc
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BaselineContractError("Requirement baseline is not valid JSON.") from exc
    return baseline_from_dict(payload)


def baseline_from_dict(payload: object) -> RequirementBaseline:
    """Validate a decoded JSON value and build immutable domain records."""

    root = _object(payload, "baseline")
    _only_keys(
        root,
        {
            "schema_version",
            "baseline_id",
            "source",
            "requirements",
            "source_acceptance_criteria",
            "diagnostics",
            "approval_state",
        },
        "baseline",
    )
    schema_version = _string(root.get("schema_version"), "schema_version")
    if schema_version != "1.0":
        raise BaselineContractError("schema_version must be 1.0.")
    baseline_id = _string(root.get("baseline_id"), "baseline_id")
    if not _BASELINE_ID.fullmatch(baseline_id):
        raise BaselineContractError("baseline_id must be a stable RB identifier.")
    source = _parse_source(root.get("source"))
    if baseline_id != f"RB-{source.sha256[:16]}":
        raise BaselineContractError("baseline_id must match the source digest.")
    requirements_raw = _array(root.get("requirements"), "requirements")
    requirements = tuple(
        _parse_requirement(item, index) for index, item in enumerate(requirements_raw)
    )
    if not requirements:
        raise BaselineContractError("requirements must not be empty.")
    requirement_ids = [item.requirement_id for item in requirements]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise BaselineContractError("requirement identifiers must be unique.")
    criteria_raw = _array(
        root.get("source_acceptance_criteria"), "source_acceptance_criteria"
    )
    source_criteria = tuple(
        _parse_criterion(item, f"source_acceptance_criteria[{index}]")
        for index, item in enumerate(criteria_raw)
    )
    source_criterion_ids = [item.criterion_id for item in source_criteria]
    if len(source_criterion_ids) != len(set(source_criterion_ids)):
        raise BaselineContractError(
            "source acceptance criterion identifiers must be unique."
        )
    if any(
        not any(
            criterion.criterion_id.startswith(f"AC-{requirement_id}-")
            for requirement_id in requirement_ids
        )
        and not re.fullmatch(r"AC-M[0-9]+-[0-9]+", criterion.criterion_id)
        for criterion in source_criteria
    ):
        raise BaselineContractError(
            "source acceptance criteria must link a requirement or milestone."
        )
    diagnostics_raw = _array(root.get("diagnostics"), "diagnostics")
    diagnostics = tuple(
        _parse_diagnostic(item, index) for index, item in enumerate(diagnostics_raw)
    )
    diagnostic_ids = [item.diagnostic_id for item in diagnostics]
    if len(diagnostic_ids) != len(set(diagnostic_ids)):
        raise BaselineContractError("diagnostic identifiers must be unique.")
    known_ids = set(requirement_ids)
    if any(
        not set(diagnostic.requirement_ids) <= known_ids
        for diagnostic in diagnostics
    ):
        raise BaselineContractError("diagnostics must reference known requirements.")
    approval = _object(root.get("approval_state"), "approval_state")
    _only_keys(approval, {"required", "granted"}, "approval_state")
    required = _string_tuple(approval.get("required"), "approval_state.required")
    granted = _string_tuple(approval.get("granted"), "approval_state.granted")
    if len(required) != len(set(required)) or len(granted) != len(set(granted)):
        raise BaselineContractError("approval identifiers must be unique.")
    if granted:
        raise BaselineContractError(
            "embedded approval grants are not trusted; use an Owner approval record."
        )
    return RequirementBaseline(
        baseline_id=baseline_id,
        source=source,
        requirements=requirements,
        source_acceptance_criteria=source_criteria,
        diagnostics=diagnostics,
        approval_required=required,
        approval_granted=granted,
        schema_version=schema_version,
    )


def _parse_source(value: object) -> SourceMetadata:
    source = _object(value, "source")
    _only_keys(
        source,
        {"filename", "path", "sha256", "size_bytes", "modified_at", "imported_at"},
        "source",
    )
    filename = _string(source.get("filename"), "source.filename")
    if not _is_safe_filename(filename):
        raise BaselineContractError("source.filename must be a safe filename.")
    display_path = _string(source.get("path"), "source.path")
    if (
        display_path.startswith(("/", "\\"))
        or _DRIVE_PATH.match(display_path)
        or ".." in Path(display_path).parts
    ):
        raise BaselineContractError("source.path must be a safe relative display path.")
    digest = _string(source.get("sha256"), "source.sha256")
    if not _SHA256.fullmatch(digest):
        raise BaselineContractError("source.sha256 must be a SHA-256 digest.")
    size_bytes = _integer(source.get("size_bytes"), "source.size_bytes")
    if size_bytes < 0:
        raise BaselineContractError("source.size_bytes must not be negative.")
    return SourceMetadata(
        filename=filename,
        path=display_path,
        sha256=digest.upper(),
        size_bytes=size_bytes,
        modified_at=_timestamp(source.get("modified_at"), "source.modified_at"),
        imported_at=_timestamp(source.get("imported_at"), "source.imported_at"),
    )


def _parse_requirement(value: object, index: int) -> RequirementRecord:
    name = f"requirements[{index}]"
    item = _object(value, name)
    _only_keys(
        item,
        {
            "id",
            "title",
            "type",
            "priority",
            "status",
            "source",
            "statement",
            "acceptance_criteria",
            "verification_methods",
            "assumptions",
            "open_questions",
            "trace_links",
            "identifier_source",
        },
        name,
    )
    identifier = _string(item.get("id"), f"{name}.id")
    if not _ID.fullmatch(identifier):
        raise BaselineContractError(f"{name}.id must be an uppercase stable identifier.")
    status = _string(item.get("status"), f"{name}.status")
    if status not in {"draft", "baselined", "implemented", "verified", "rejected"}:
        raise BaselineContractError(f"{name}.status is invalid.")
    source = _parse_trace(item.get("source"), f"{name}.source")
    criteria_raw = _array(item.get("acceptance_criteria"), f"{name}.acceptance_criteria")
    criteria = tuple(
        _parse_criterion(entry, f"{name}.acceptance_criteria[{criterion_index}]")
        for criterion_index, entry in enumerate(criteria_raw)
    )
    criterion_ids = [criterion.criterion_id for criterion in criteria]
    if len(criterion_ids) != len(set(criterion_ids)):
        raise BaselineContractError(f"{name}.acceptance_criteria IDs must be unique.")
    if any(
        not criterion.criterion_id.startswith(f"AC-{identifier}-")
        for criterion in criteria
    ):
        raise BaselineContractError(
            f"{name}.acceptance_criteria must link to {identifier}."
        )
    methods = _string_tuple(item.get("verification_methods"), f"{name}.verification_methods")
    if not criteria or not methods:
        raise BaselineContractError(f"{name} must include acceptance and verification.")
    links = _parse_links(item.get("trace_links"), f"{name}.trace_links")
    identifier_source = _string(item.get("identifier_source"), f"{name}.identifier_source")
    if identifier_source not in {"explicit", "generated"}:
        raise BaselineContractError(f"{name}.identifier_source is invalid.")
    requirement_type = _enum_value(
        RequirementType, item.get("type"), f"{name}.type"
    )
    statement = _string(item.get("statement"), f"{name}.statement")
    if (
        identifier_source == "generated"
        and identifier != generated_requirement_id(statement, requirement_type)
    ):
        raise BaselineContractError(
            f"{name}.id does not match its generated identifier contract."
        )
    return RequirementRecord(
        requirement_id=identifier,
        title=_string(item.get("title"), f"{name}.title"),
        requirement_type=requirement_type,
        priority=_enum_value(
            RequirementPriority, item.get("priority"), f"{name}.priority"
        ),
        status=status,
        source=source,
        statement=statement,
        acceptance_criteria=criteria,
        verification_methods=methods,
        assumptions=_string_tuple(item.get("assumptions"), f"{name}.assumptions"),
        open_questions=_string_tuple(
            item.get("open_questions"), f"{name}.open_questions"
        ),
        trace_links=links,
        identifier_source=identifier_source,
    )


def _parse_trace(value: object, name: str) -> SourceTrace:
    source = _object(value, name)
    _only_keys(
        source,
        {
            "document",
            "section",
            "line_start",
            "line_end",
            "excerpt",
            "derivation_basis",
        },
        name,
    )
    line_start = _integer(source.get("line_start"), f"{name}.line_start")
    line_end = _integer(source.get("line_end"), f"{name}.line_end")
    if line_start < 1 or line_end < line_start:
        raise BaselineContractError(f"{name} has an invalid line range.")
    document = _string(source.get("document"), f"{name}.document")
    if not _is_safe_filename(document):
        raise BaselineContractError(f"{name}.document must be a safe filename.")
    return SourceTrace(
        document=document,
        section=_string(source.get("section"), f"{name}.section"),
        line_start=line_start,
        line_end=line_end,
        excerpt=_string(source.get("excerpt"), f"{name}.excerpt"),
        derivation_basis=_string(
            source.get("derivation_basis"), f"{name}.derivation_basis"
        ),
    )


def _parse_criterion(value: object, name: str) -> AcceptanceCriterion:
    item = _object(value, name)
    _only_keys(item, {"id", "statement", "verification_methods"}, name)
    identifier = _string(item.get("id"), f"{name}.id")
    if not _ID.fullmatch(identifier):
        raise BaselineContractError(f"{name}.id must be a stable identifier.")
    methods = _string_tuple(item.get("verification_methods"), f"{name}.verification_methods")
    if not methods:
        raise BaselineContractError(f"{name}.verification_methods must not be empty.")
    return AcceptanceCriterion(
        criterion_id=identifier,
        statement=_string(item.get("statement"), f"{name}.statement"),
        verification_methods=methods,
    )


def _parse_links(value: object, name: str) -> TraceLinks:
    item = _object(value, name)
    _only_keys(item, {"design", "code", "tests", "evidence", "releases"}, name)
    return TraceLinks(
        design=_string_tuple(item.get("design"), f"{name}.design"),
        code=_string_tuple(item.get("code"), f"{name}.code"),
        tests=_string_tuple(item.get("tests"), f"{name}.tests"),
        evidence=_string_tuple(item.get("evidence"), f"{name}.evidence"),
        releases=_string_tuple(item.get("releases"), f"{name}.releases"),
    )


def _parse_diagnostic(value: object, index: int) -> Diagnostic:
    name = f"diagnostics[{index}]"
    item = _object(value, name)
    _only_keys(
        item,
        {
            "id",
            "kind",
            "severity",
            "requirement_ids",
            "message",
            "line_start",
            "line_end",
            "status",
        },
        name,
    )
    identifier = _string(item.get("id"), f"{name}.id")
    if not re.fullmatch(r"DIAG-[0-9A-F]{12}", identifier):
        raise BaselineContractError(f"{name}.id must be a stable diagnostic identifier.")
    status = _string(item.get("status"), f"{name}.status")
    if status not in {"open", "resolved", "accepted"}:
        raise BaselineContractError(f"{name}.status is invalid.")
    line_start = _integer(item.get("line_start"), f"{name}.line_start")
    line_end = _integer(item.get("line_end"), f"{name}.line_end")
    if line_start < 1 or line_end < line_start:
        raise BaselineContractError(f"{name} has an invalid line range.")
    return Diagnostic(
        diagnostic_id=identifier,
        kind=_enum_value(DiagnosticKind, item.get("kind"), f"{name}.kind"),
        severity=_enum_value(
            DiagnosticSeverity, item.get("severity"), f"{name}.severity"
        ),
        requirement_ids=_string_tuple(
            item.get("requirement_ids"), f"{name}.requirement_ids"
        ),
        message=_string(item.get("message"), f"{name}.message"),
        line_start=line_start,
        line_end=line_end,
        status=status,
    )


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise BaselineContractError(f"{name} must be an object.")
    return value


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise BaselineContractError(f"{name} must be an array.")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BaselineContractError(f"{name} must be a non-empty string.")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise BaselineContractError(f"{name} must be an integer.")
    return value


def _is_safe_filename(value: str) -> bool:
    return (
        Path(value).name == value
        and value not in {".", ".."}
        and "\n" not in value
        and "\r" not in value
        and "\0" not in value
        and ":" not in value
        and "/" not in value
        and "\\" not in value
    )


def _timestamp(value: object, name: str) -> str:
    text = _string(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BaselineContractError(f"{name} must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise BaselineContractError(f"{name} must include a timezone.")
    return text


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    raw = _array(value, name)
    result: list[str] = []
    for index, item in enumerate(raw):
        result.append(_string(item, f"{name}[{index}]"))
    return tuple(result)


def _enum_value[
    EnumType: (RequirementType, RequirementPriority, DiagnosticKind, DiagnosticSeverity)
](
    enum_type: type[EnumType], value: object, name: str
) -> EnumType:
    text = _string(value, name)
    try:
        return enum_type(text)
    except ValueError as exc:
        raise BaselineContractError(f"{name} has an unsupported value.") from exc


def _only_keys(item: dict[str, object], expected: set[str], name: str) -> None:
    missing = expected - item.keys()
    extra = item.keys() - expected
    if missing:
        raise BaselineContractError(f"{name} is missing {sorted(missing)[0]}.")
    if extra:
        raise BaselineContractError(f"{name} contains unsupported field {sorted(extra)[0]}.")
