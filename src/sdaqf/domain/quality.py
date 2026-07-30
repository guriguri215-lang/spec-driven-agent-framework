"""Immutable M3 evidence, review, UI, release, and handoff contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    """Immutable identity of one locally observed repository candidate."""

    source_spec_sha256: str
    git_head: str
    repository_digest: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible representation."""

        return {
            "source_spec_sha256": self.source_spec_sha256,
            "git_head": self.git_head,
            "repository_digest": self.repository_digest,
        }


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """Repository-bounded artifact path and content digest."""

    path: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible representation."""

        return {"path": self.path, "sha256": self.sha256}


class EvidenceType(StrEnum):
    """Supported Claim-Evidence Ledger evidence classes."""

    TEST = "TEST"
    STATIC_ANALYSIS = "STATIC_ANALYSIS"
    TYPE_CHECK = "TYPE_CHECK"
    BENCHMARK = "BENCHMARK"
    VISUAL = "VISUAL"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    SOURCE_REVIEW = "SOURCE_REVIEW"
    UNVERIFIED = "UNVERIFIED"


class EvidenceStatus(StrEnum):
    """One explicit evidence result."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_VERIFIED = "NOT_VERIFIED"


class ClaimState(StrEnum):
    """Truthful implementation state for one bounded claim."""

    IMPLEMENTED = "implemented"
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    KNOWN_PROBLEM = "known_problem"


class ClaimCriticality(StrEnum):
    """Non-compensating claim class."""

    NORMAL = "normal"
    MUST = "must"
    SECURITY = "security"
    DATA_LOSS = "data_loss"
    DISCLOSURE = "disclosure"


class Confidence(StrEnum):
    """Bounded fact confidence."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


@dataclass(frozen=True, slots=True)
class Claim:
    """One requirement or acceptance claim in the ledger."""

    claim_id: str
    statement: str
    requirement_ids: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    state: ClaimState
    criticality: ClaimCriticality
    confidence: Confidence

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "requirement_ids": list(self.requirement_ids),
            "acceptance_criteria": list(self.acceptance_criteria),
            "state": self.state.value,
            "criticality": self.criticality.value,
            "confidence": self.confidence.value,
        }


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One bounded item of evidence."""

    evidence_id: str
    claim_ids: tuple[str, ...]
    evidence_type: EvidenceType
    status: EvidenceStatus
    command: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    commit: str
    repository_digest: str
    artifacts: tuple[ArtifactReference, ...]
    recorded_at: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "evidence_id": self.evidence_id,
            "claim_ids": list(self.claim_ids),
            "type": self.evidence_type.value,
            "status": self.status.value,
            "command": list(self.command),
            "environment": dict(self.environment),
            "commit": self.commit,
            "repository_digest": self.repository_digest,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class EvidenceLedger:
    """Validated Claim-Evidence Ledger."""

    baseline_id: str
    source_spec_sha256: str
    git_head: str
    repository_digest: str
    claims: tuple[Claim, ...]
    evidence: tuple[EvidenceRecord, ...]
    diff_review_evidence_id: str
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""

        return {
            "schema_version": self.schema_version,
            "baseline_id": self.baseline_id,
            "source_spec_sha256": self.source_spec_sha256,
            "git_head": self.git_head,
            "repository_digest": self.repository_digest,
            "claims": [item.to_dict() for item in self.claims],
            "evidence": [item.to_dict() for item in self.evidence],
            "diff_review_evidence_id": self.diff_review_evidence_id,
        }


class ReviewStatus(StrEnum):
    """Independent review completion state."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    REJECTED = "rejected"


class ReviewArea(StrEnum):
    """Required independent review areas."""

    REGRESSION = "regression"
    SECURITY = "security"
    MAINTAINABILITY = "maintainability"


class ReviewFindingSeverity(StrEnum):
    """Review finding severity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewFindingStatus(StrEnum):
    """Resolution state of one review finding."""

    OPEN = "open"
    RESOLVED = "resolved"
    ACCEPTED = "accepted"


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    """One traceable independent review finding."""

    finding_id: str
    severity: ReviewFindingSeverity
    status: ReviewFindingStatus
    statement: str
    specification_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    approval_id: str | None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "finding_id": self.finding_id,
            "severity": self.severity.value,
            "status": self.status.value,
            "statement": self.statement,
            "specification_refs": list(self.specification_refs),
            "evidence_refs": list(self.evidence_refs),
            "approval_id": self.approval_id,
        }


@dataclass(frozen=True, slots=True)
class IndependentReview:
    """Bounded, read-only independent review result."""

    review_id: str
    baseline_id: str
    candidate: CandidateIdentity
    reviewed_at: str
    reviewer_id: str
    reviewed_agent_ids: tuple[str, ...]
    status: ReviewStatus
    read_only: bool
    areas: tuple[ReviewArea, ...]
    findings: tuple[ReviewFinding, ...]
    reviewed_paths: tuple[str, ...]
    changed_paths: tuple[str, ...]
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "schema_version": self.schema_version,
            "review_id": self.review_id,
            "baseline_id": self.baseline_id,
            "candidate": self.candidate.to_dict(),
            "reviewed_at": self.reviewed_at,
            "reviewer_id": self.reviewer_id,
            "reviewed_agent_ids": list(self.reviewed_agent_ids),
            "status": self.status.value,
            "read_only": self.read_only,
            "areas": [item.value for item in self.areas],
            "findings": [item.to_dict() for item in self.findings],
            "reviewed_paths": list(self.reviewed_paths),
            "changed_paths": list(self.changed_paths),
        }


@dataclass(frozen=True, slots=True)
class FindingAcceptance:
    """Exact Owner approval to accept one critical review finding."""

    approval_id: str
    review_id: str
    finding_id: str
    finding_sha256: str
    candidate: CandidateIdentity
    rationale: str
    approved_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class DesignBrief:
    """UI users, flows, states, and target devices."""

    users: tuple[str, ...]
    primary_flows: tuple[str, ...]
    states: tuple[str, ...]
    target_devices: tuple[str, ...]
    design_research: tuple[str, ...]
    third_party_asset_policy: str
    third_party_asset_provenance: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "users": list(self.users),
            "primary_flows": list(self.primary_flows),
            "states": list(self.states),
            "target_devices": list(self.target_devices),
            "design_research": list(self.design_research),
            "third_party_asset_policy": self.third_party_asset_policy,
            "third_party_asset_provenance": list(self.third_party_asset_provenance),
        }


@dataclass(frozen=True, slots=True)
class BrowserObservation:
    """One bounded browser or target-platform validation attempt."""

    attempt: int
    observed_at: str
    observer_id: str
    provenance: str
    platform: str
    browser: str
    command: tuple[str, ...]
    flows_passed: tuple[str, ...]
    states_passed: tuple[str, ...]
    devices_passed: tuple[str, ...]
    viewports: tuple[str, ...]
    keyboard: bool
    focus_order: bool
    readability: bool
    contrast: bool
    information_structure: bool
    efficiency: bool
    offline: bool
    recovery: bool
    screenshots: tuple[ArtifactReference, ...]
    trace: ArtifactReference
    visual_regression: str
    visual_regression_reason: str | None
    status: EvidenceStatus
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "attempt": self.attempt,
            "observed_at": self.observed_at,
            "observer_id": self.observer_id,
            "provenance": self.provenance,
            "platform": self.platform,
            "browser": self.browser,
            "command": list(self.command),
            "flows_passed": list(self.flows_passed),
            "states_passed": list(self.states_passed),
            "devices_passed": list(self.devices_passed),
            "viewports": list(self.viewports),
            "keyboard": self.keyboard,
            "focus_order": self.focus_order,
            "readability": self.readability,
            "contrast": self.contrast,
            "information_structure": self.information_structure,
            "efficiency": self.efficiency,
            "offline": self.offline,
            "recovery": self.recovery,
            "screenshots": [item.to_dict() for item in self.screenshots],
            "trace": self.trace.to_dict(),
            "visual_regression": self.visual_regression,
            "visual_regression_reason": self.visual_regression_reason,
            "status": self.status.value,
            "failures": list(self.failures),
        }


@dataclass(frozen=True, slots=True)
class UiValidation:
    """UI classification and recorded host validation."""

    project_id: str
    ui_present: bool
    candidate: CandidateIdentity
    design_brief: DesignBrief | None
    observations: tuple[BrowserObservation, ...]
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "ui_present": self.ui_present,
            "candidate": self.candidate.to_dict(),
            "design_brief": (
                None if self.design_brief is None else self.design_brief.to_dict()
            ),
            "observations": [item.to_dict() for item in self.observations],
        }


@dataclass(frozen=True, slots=True)
class ProjectLicense:
    """Exact Owner-approved project-license material."""

    spdx_expression: str
    copyright_holder: str
    license_file: ArtifactReference
    notice_file: ArtifactReference

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "spdx_expression": self.spdx_expression,
            "copyright_holder": self.copyright_holder,
            "license_file": self.license_file.to_dict(),
            "notice_file": self.notice_file.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ReleaseCandidateInput:
    """Bounded local inputs for Gate G4."""

    install_evidence_id: str
    execution_module: str
    install_target: str
    rollback_guidance: str
    documentation_paths: tuple[str, ...]
    license_status: str
    license: ProjectLicense | None = None
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "install_evidence_id": self.install_evidence_id,
            "execution_module": self.execution_module,
            "install_target": self.install_target,
            "rollback_guidance": self.rollback_guidance,
            "documentation_paths": list(self.documentation_paths),
        }
        if self.schema_version == "1.0":
            result["license_status"] = self.license_status
        elif self.license is not None:
            result["license"] = self.license.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class PublicationReadinessInput:
    """Exact offline publication-readiness declaration."""

    candidate: CandidateIdentity
    branch: str
    publication_paths: tuple[str, ...]
    release_notes: ArtifactReference
    review_candidate: CandidateIdentity
    review_baseline_id: str
    review_decision: str
    gate_results: tuple[tuple[str, str], ...]
    gate_evidence: tuple[tuple[str, ArtifactReference], ...]
    unresolved_findings: tuple[tuple[str, int], ...]
    publication_performed: bool
    actual_gate_g5: str
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, object]:
        """Return the bounded fields relevant to local evaluation."""

        return {
            "schema_version": self.schema_version,
            "candidate": self.candidate.to_dict(),
            "branch": self.branch,
            "publication_paths": list(self.publication_paths),
            "release_notes": self.release_notes.to_dict(),
            "review_candidate": self.review_candidate.to_dict(),
            "review_baseline_id": self.review_baseline_id,
            "review_decision": self.review_decision,
            "gate_results": dict(self.gate_results),
            "gate_evidence": {
                gate_id: reference.to_dict()
                for gate_id, reference in self.gate_evidence
            },
            "unresolved_findings": dict(self.unresolved_findings),
            "publication_performed": self.publication_performed,
            "actual_gate_g5": self.actual_gate_g5,
        }


@dataclass(frozen=True, slots=True)
class GitObservation:
    """Read-only local Git identity and cleanliness observation."""

    root_matches: bool
    branch: str
    head: str
    clean: bool
    repository_digest: str
    changed_paths: tuple[str, ...] = ()
    publication_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "root_matches": self.root_matches,
            "branch": self.branch,
            "head": self.head,
            "clean": self.clean,
            "repository_digest": self.repository_digest,
            "changed_paths": list(self.changed_paths),
            "publication_paths": list(self.publication_paths),
        }


class HandoffStatus(StrEnum):
    """Supported task handoff states."""

    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class NextPromptContext:
    """Bounded fields used to generate, but never execute, a next prompt."""

    role: str
    references: tuple[str, ...]
    change_scope: tuple[str, ...]
    exclusions: tuple[str, ...]
    completion_criteria: tuple[str, ...]
    stop_conditions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "role": self.role,
            "references": list(self.references),
            "change_scope": list(self.change_scope),
            "exclusions": list(self.exclusions),
            "completion_criteria": list(self.completion_criteria),
            "stop_conditions": list(self.stop_conditions),
        }


@dataclass(frozen=True, slots=True)
class AutomatedHandoff:
    """Deterministic M3 session handoff."""

    milestone: str
    status: HandoffStatus
    branch: str
    head: str
    worktree: str
    baseline_id: str
    source_spec_sha256: str
    repository_digest: str
    completed: tuple[str, ...]
    incomplete: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    open_decisions: tuple[str, ...]
    known_problems: tuple[str, ...]
    recommended_next: str
    primary_folder: str
    approval_stops: tuple[str, ...]
    next_prompt_context: NextPromptContext
    next_prompt: str
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "schema_version": self.schema_version,
            "milestone": self.milestone,
            "status": self.status.value,
            "git": {
                "branch": self.branch,
                "head": self.head,
                "worktree": self.worktree,
            },
            "baseline_id": self.baseline_id,
            "source_spec_sha256": self.source_spec_sha256,
            "repository_digest": self.repository_digest,
            "completed": list(self.completed),
            "incomplete": list(self.incomplete),
            "evidence_ids": list(self.evidence_ids),
            "open_decisions": list(self.open_decisions),
            "known_problems": list(self.known_problems),
            "recommended_next": self.recommended_next,
            "primary_folder": self.primary_folder,
            "approval_stops": list(self.approval_stops),
            "next_prompt_context": self.next_prompt_context.to_dict(),
            "next_prompt": self.next_prompt,
        }
