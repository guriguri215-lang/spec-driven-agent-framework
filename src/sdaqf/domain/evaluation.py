"""Immutable M4 comparative-evaluation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Workflow(StrEnum):
    """Compared development workflow."""

    STRUCTURED = "structured_sdaqf"
    UNSTRUCTURED = "ordinary_unstructured_codex"


class CriticalCategory(StrEnum):
    """Non-compensating critical failure classes."""

    MUST = "must"
    SECURITY = "security"
    DATA_LOSS = "data_loss"
    DISCLOSURE = "disclosure"


class HandoffStatus(StrEnum):
    """Observed handoff result."""

    PASSED = "PASSED"
    FAILED = "FAILED"


class CostStatus(StrEnum):
    """Availability of comparable execution-cost evidence."""

    AVAILABLE = "AVAILABLE"
    NOT_VERIFIED = "NOT_VERIFIED"


class CauseLayer(StrEnum):
    """Supported remediation layers for repeated failures."""

    INSTRUCTIONS = "instructions"
    SKILL = "skill"
    SCHEMA = "schema"
    TESTS = "tests"
    IMPLEMENTATION = "implementation"


class EvidenceStatus(StrEnum):
    """Observed status of one comparison evidence artifact."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_VERIFIED = "NOT_VERIFIED"


class EvidenceType(StrEnum):
    """Supported comparative-evaluation evidence classes."""

    TEST = "TEST"
    SOURCE_REVIEW = "SOURCE_REVIEW"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    HANDOFF = "HANDOFF"


@dataclass(frozen=True, slots=True)
class EvaluationInputIdentity:
    """Inputs that must be equal across a paired comparison."""

    project_id: str
    specification_sha256: str
    task_sha256: str
    starting_repository_digest: str
    model_id: str
    client_surface: str
    platform: str
    python_version: str
    budget_units: int
    trial_id: str

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""

        return {
            "project_id": self.project_id,
            "specification_sha256": self.specification_sha256,
            "task_sha256": self.task_sha256,
            "starting_repository_digest": self.starting_repository_digest,
            "model_id": self.model_id,
            "client_surface": self.client_surface,
            "platform": self.platform,
            "python_version": self.python_version,
            "budget_units": self.budget_units,
            "trial_id": self.trial_id,
        }


@dataclass(frozen=True, slots=True)
class CriticalDefect:
    """One critical failure that cannot be averaged away."""

    defect_id: str
    category: CriticalCategory
    requirement_ids: tuple[str, ...]
    description: str
    resolved: bool


@dataclass(frozen=True, slots=True)
class ReworkEvent:
    """One repeated or corrective work event."""

    event_id: str
    failure_signature: str
    description: str


@dataclass(frozen=True, slots=True)
class HandoffObservation:
    """One measured handoff outcome."""

    handoff_id: str
    status: HandoffStatus


@dataclass(frozen=True, slots=True)
class CauseAnalysis:
    """Required remediation decision for a repeated failure signature."""

    failure_signature: str
    layers: tuple[CauseLayer, ...]
    owner: str
    action: str
    status: str
    verification_evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CostObservation:
    """Comparable cost evidence or an explicit unverified state."""

    status: CostStatus
    elapsed_seconds: int | None
    tool_calls: int | None
    input_tokens: int | None
    output_tokens: int | None
    reason: str | None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible cost record."""

        return {
            "status": self.status.value,
            "elapsed_seconds": self.elapsed_seconds,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    """One content-bound artifact used to support a run observation."""

    evidence_id: str
    evidence_type: EvidenceType
    status: EvidenceStatus
    path: str
    sha256: str
    observed_at: str
    command: str


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """One strict structured or ordinary-unstructured workflow observation."""

    run_id: str
    workflow: Workflow
    input_identity: EvaluationInputIdentity
    intervention: str
    intervention_sha256: str
    requirements_implemented: tuple[str, ...]
    scope_additions: tuple[str, ...]
    critical_defects: tuple[CriticalDefect, ...]
    rework_events: tuple[ReworkEvent, ...]
    approvals: tuple[str, ...]
    handoffs: tuple[HandoffObservation, ...]
    trace: tuple[str, ...]
    decisions: tuple[str, ...]
    evidence: tuple[EvaluationEvidence, ...]
    cause_analyses: tuple[CauseAnalysis, ...]
    cost: CostObservation
    limitations: tuple[str, ...]
    schema_version: str = "1.0"


@dataclass(frozen=True, slots=True)
class ExpectedRequirement:
    """Stable semantic projection of one normalized requirement."""

    requirement_id: str
    requirement_type: str
    priority: str
    statement: str
    acceptance_ids: tuple[str, ...]
    verification_methods: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible expectation."""

        return {
            "requirement_id": self.requirement_id,
            "type": self.requirement_type,
            "priority": self.priority,
            "statement": self.statement,
            "acceptance_ids": list(self.acceptance_ids),
            "verification_methods": list(self.verification_methods),
        }


@dataclass(frozen=True, slots=True)
class NormalizationExpectation:
    """Expected normalized projection for one sample specification."""

    project_id: str
    source_sha256: str
    baseline_id: str
    requirements: tuple[ExpectedRequirement, ...]
    diagnostic_kinds: tuple[str, ...]
    schema_version: str = "1.0"


@dataclass(frozen=True, slots=True)
class EvaluationProject:
    """References for one paired sample-project evaluation."""

    project_id: str
    specification: str
    task: str
    structured_instructions: str
    unstructured_instructions: str
    expectation: str
    structured_run: str
    unstructured_run: str


@dataclass(frozen=True, slots=True)
class ChangeEvaluation:
    """Before/after evidence for a Skill, template, or prompt change."""

    change_id: str
    artifact_type: str
    artifact_id: str
    before_run_id: str
    after_run_id: str


@dataclass(frozen=True, slots=True)
class EvaluationSuite:
    """One bounded reproducible set of paired evaluations."""

    suite_id: str
    projects: tuple[EvaluationProject, ...]
    changes: tuple[ChangeEvaluation, ...]
    limitations: tuple[str, ...]
    schema_version: str = "1.0"


@dataclass(frozen=True, slots=True)
class RunMetrics:
    """Deterministic metrics derived from one run."""

    missed_requirements: int
    scope_additions: int
    critical_defects: int
    rework: int
    approval_count: int
    failed_handoffs: int
    trace_steps: int
    decisions: int
    evidence_items: int
    cost: CostObservation
    hard_blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible metric record."""

        return {
            "missed_requirements": self.missed_requirements,
            "scope_additions": self.scope_additions,
            "critical_defects": self.critical_defects,
            "rework": self.rework,
            "approval_count": self.approval_count,
            "failed_handoffs": self.failed_handoffs,
            "trace_steps": self.trace_steps,
            "decisions": self.decisions,
            "evidence_items": self.evidence_items,
            "cost": self.cost.to_dict(),
            "hard_blockers": list(self.hard_blockers),
        }


@dataclass(frozen=True, slots=True)
class EvaluationComparison:
    """Metrics for one parity-validated workflow pair."""

    project_id: str
    structured_run_id: str
    unstructured_run_id: str
    structured: RunMetrics
    unstructured: RunMetrics

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible project comparison."""

        return {
            "project_id": self.project_id,
            "structured_run_id": self.structured_run_id,
            "unstructured_run_id": self.unstructured_run_id,
            "structured": self.structured.to_dict(),
            "unstructured": self.unstructured.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Reproducible suite result without an aggregate quality score."""

    suite_id: str
    comparisons: tuple[EvaluationComparison, ...]
    limitations: tuple[str, ...]
    hard_blockers: tuple[str, ...]
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON-compatible output."""

        return {
            "schema_version": self.schema_version,
            "suite_id": self.suite_id,
            "comparisons": [item.to_dict() for item in self.comparisons],
            "hard_blockers": list(self.hard_blockers),
            "limitations": list(self.limitations),
            "aggregate_score": None,
        }
