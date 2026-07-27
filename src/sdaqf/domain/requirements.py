"""Immutable contracts for M1 requirement baselines."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RequirementType(StrEnum):
    """Supported normalized requirement record types."""

    FUNCTIONAL = "functional"
    NONFUNCTIONAL = "nonfunctional"
    CONSTRAINT = "constraint"
    NON_GOAL = "non-goal"
    ASSUMPTION = "assumption"
    OPEN_DECISION = "open-decision"


class RequirementPriority(StrEnum):
    """Normative priority used by the requirements contract."""

    MUST = "must"
    SHOULD = "should"
    COULD = "could"


class DiagnosticKind(StrEnum):
    """Kinds of requirement-quality issue detected by deterministic rules."""

    AMBIGUITY = "ambiguity"
    CONTRADICTION = "contradiction"
    DUPLICATE_IDENTIFIER = "duplicate-identifier"
    DUPLICATE_STATEMENT = "duplicate-statement"
    MISSING_ASSUMPTION = "missing-assumption"
    UNVERIFIABLE = "unverifiable"


class DiagnosticSeverity(StrEnum):
    """Severity of an open normalization diagnostic."""

    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Safe metadata for one ingested specification."""

    filename: str
    path: str
    sha256: str
    size_bytes: int
    modified_at: str
    imported_at: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "filename": self.filename,
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "imported_at": self.imported_at,
        }


@dataclass(frozen=True, slots=True)
class SourceTrace:
    """Original-source trace for a normalized requirement."""

    document: str
    section: str
    line_start: int
    line_end: int
    excerpt: str
    derivation_basis: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "document": self.document,
            "section": self.section,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "excerpt": self.excerpt,
            "derivation_basis": self.derivation_basis,
        }


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    """One traceable acceptance criterion and its verification methods."""

    criterion_id: str
    statement: str
    verification_methods: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "id": self.criterion_id,
            "statement": self.statement,
            "verification_methods": list(self.verification_methods),
        }


@dataclass(frozen=True, slots=True)
class TraceLinks:
    """Downstream trace links, empty until supported evidence is recorded."""

    design: tuple[str, ...] = ()
    code: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    releases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "design": list(self.design),
            "code": list(self.code),
            "tests": list(self.tests),
            "evidence": list(self.evidence),
            "releases": list(self.releases),
        }


@dataclass(frozen=True, slots=True)
class RequirementRecord:
    """A normalized requirement that makes no implementation claim."""

    requirement_id: str
    title: str
    requirement_type: RequirementType
    priority: RequirementPriority
    source: SourceTrace
    statement: str
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    verification_methods: tuple[str, ...]
    assumptions: tuple[str, ...]
    open_questions: tuple[str, ...]
    trace_links: TraceLinks
    identifier_source: str
    status: str = "baselined"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "id": self.requirement_id,
            "title": self.title,
            "type": self.requirement_type.value,
            "priority": self.priority.value,
            "status": self.status,
            "source": self.source.to_dict(),
            "statement": self.statement,
            "acceptance_criteria": [
                criterion.to_dict() for criterion in self.acceptance_criteria
            ],
            "verification_methods": list(self.verification_methods),
            "assumptions": list(self.assumptions),
            "open_questions": list(self.open_questions),
            "trace_links": self.trace_links.to_dict(),
            "identifier_source": self.identifier_source,
        }


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """An explicit quality issue found during normalization."""

    diagnostic_id: str
    kind: DiagnosticKind
    severity: DiagnosticSeverity
    requirement_ids: tuple[str, ...]
    message: str
    line_start: int
    line_end: int
    status: str = "open"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "id": self.diagnostic_id,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "requirement_ids": list(self.requirement_ids),
            "message": self.message,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class RequirementBaseline:
    """Versioned deterministic requirement baseline."""

    baseline_id: str
    source: SourceMetadata
    requirements: tuple[RequirementRecord, ...]
    source_acceptance_criteria: tuple[AcceptanceCriterion, ...]
    diagnostics: tuple[Diagnostic, ...]
    approval_required: tuple[str, ...] = ()
    approval_granted: tuple[str, ...] = ()
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return {
            "schema_version": self.schema_version,
            "baseline_id": self.baseline_id,
            "source": self.source.to_dict(),
            "requirements": [item.to_dict() for item in self.requirements],
            "source_acceptance_criteria": [
                item.to_dict() for item in self.source_acceptance_criteria
            ],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "approval_state": {
                "required": list(self.approval_required),
                "granted": list(self.approval_granted),
            },
        }


def generated_requirement_id(
    statement: str, requirement_type: RequirementType
) -> str:
    """Return the stable content-derived identifier for an unlabelled record."""

    prefixes = {
        RequirementType.FUNCTIONAL: "FR-AUTO",
        RequirementType.NONFUNCTIONAL: "NFR-AUTO",
        RequirementType.CONSTRAINT: "C-AUTO",
        RequirementType.NON_GOAL: "NG-AUTO",
        RequirementType.ASSUMPTION: "ASM-AUTO",
        RequirementType.OPEN_DECISION: "OD-AUTO",
    }
    normalized = re.sub(r"[^a-z0-9]+", " ", statement.casefold()).strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{prefixes[requirement_type]}-{digest[:12].upper()}"
