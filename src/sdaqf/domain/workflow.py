"""Immutable M8 Integrated Vibe-Coding Framework domain contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sdaqf.domain.context import Sensitivity
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity, GitObservation
from sdaqf.domain.scheduler import (
    EffectKind,
    SchedulerBudget,
    TaskOutcome,
    TaskState,
    WorkflowReceiptSnapshot,
)


class WorkflowArtifactType(StrEnum):
    """Public M8 artifact discriminators."""

    DEVELOPMENT_INTENT = "development-intent"
    INTEGRATED_PLAN = "integrated-plan"
    WORKFLOW_STATE = "workflow-state"
    WORKFLOW_EVENT = "workflow-event"
    WORKFLOW_OUTCOME = "workflow-outcome"


class CompletionProfile(StrEnum):
    """Closed completion predicates selected by untrusted Development Intent."""

    PLAN_ONLY = "plan-only"
    IMPLEMENTATION_VERIFIED = "implementation-verified"
    INDEPENDENT_REVIEW_ACCEPTED = "independent-review-accepted"
    RELEASE_CANDIDATE_READY = "release-candidate-ready"


class IntentRisk(StrEnum):
    """Bounded risk labels that never grant authority."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkflowDecisionKind(StrEnum):
    """Auditable planner decision classes."""

    SELECTED = "selected"
    EXCLUDED = "excluded"
    UNCERTAINTY = "uncertainty"


class WorkflowEventCause(StrEnum):
    """Closed integration transition causes."""

    PLAN_ADOPTED = "plan-adopted"
    RUNTIME_STARTED = "runtime-started"
    CONTEXT_REVALIDATED = "context-revalidated"
    SCHEDULER_ADVANCED = "scheduler-advanced"
    APPROVAL_BLOCKED = "approval-blocked"
    APPROVAL_REVALIDATED = "approval-revalidated"
    SOLVER_REVALIDATED = "solver-revalidated"
    EVIDENCE_REVALIDATED = "evidence-revalidated"
    REVIEW_REVALIDATED = "review-revalidated"
    GATE_EVALUATED = "gate-evaluated"
    AMBIGUITY_RECORDED = "ambiguity-recorded"
    RECOVERY_OBSERVED = "recovery-observed"
    PLAN_SUPERSEDED = "plan-superseded"
    HANDOFF_REVALIDATED = "handoff-revalidated"
    OUTCOME_PRODUCED = "outcome-produced"


class WorkflowDisposition(StrEnum):
    """Truthful Outcome dispositions that cannot upgrade native evidence."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class WorkflowTerminalObservationCause(StrEnum):
    """Closed native causes accepted by the terminal observation finalizer."""

    COMPLETION_OBSERVED = "completion-observed"
    UI_EVIDENCE_UNAVAILABLE = "ui-evidence-unavailable"
    APPROVAL_REQUIRED = "approval-required"
    APPROVAL_REFUSED = "approval-refused"
    APPROVAL_EXPIRED = "approval-expired"
    STALE_CANDIDATE = "stale-candidate"
    STALE_CONTEXT = "stale-context"
    LEASE_LOST = "lease-lost"
    SOLVER_INCONCLUSIVE = "solver-inconclusive"
    EXTERNAL_EFFECT_AMBIGUOUS = "external-effect-ambiguous"
    RECOVERED_COMPLETION = "recovered-completion"


class OutcomeClaimState(StrEnum):
    """Truth state of the claims summarized by one Workflow Outcome."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    KNOWN_PROBLEM = "known-problem"


class EffectDisposition(StrEnum):
    """Closed effect observation carried by every Workflow Event."""

    NOT_APPLICABLE = "not-applicable"
    BLOCKED = "blocked"
    REVALIDATED = "revalidated"
    AMBIGUOUS = "ambiguous"


class MeasurementStatus(StrEnum):
    """Availability of one exact non-aggregate measurement."""

    OBSERVED = "observed"
    NOT_AVAILABLE = "not-available"


class GateStatus(StrEnum):
    """Native Gate observation states."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_VERIFIED = "NOT_VERIFIED"


WORKFLOW_MEASUREMENT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("requirements", (
        "required_requirement_count", "covered_requirement_count",
        "uncovered_requirement_ids", "scope_addition_count",
        "blocking_diagnostic_count",
    )),
    ("context", (
        "required_reference_count", "selected_required_reference_count",
        "stale_required_count", "provenance_missing_count",
        "sensitivity_violation_count", "selected_context_bytes",
        "context_budget_bytes", "unresolved_contradiction_count",
    )),
    ("scheduling", (
        "task_count", "completed_task_count", "blocked_task_count",
        "retry_used_count", "duplicate_rejection_count",
        "late_result_rejection_count", "deadlock_count",
    )),
    ("solver", (
        "solver_task_count", "status_counts", "verified_result_count",
        "adoptable_result_count", "solver_calls_used", "solver_steps_used",
    )),
    ("evidence", (
        "claim_count", "verified_claim_count", "unverified_claim_count",
        "known_problem_count", "missing_evidence_count",
    )),
    ("handoff", (
        "handoff_created_count", "handoff_resume_failure_count",
        "incomplete_item_count", "open_decision_count", "known_problem_count",
    )),
    ("recovery", (
        "resume_attempt_count", "successful_resume_count",
        "recovery_attempt_count", "successful_recovery_count",
        "ambiguous_effect_count",
    )),
    ("approval", (
        "required_approval_count", "consumed_approval_count",
        "refused_approval_count", "expired_approval_count",
        "pending_approval_count", "approval_revalidation_failure_count",
    )),
    ("available_cost", (
        "status", "currency", "budget_microunits", "used_microunits",
        "remaining_microunits",
    )),
)

WORKFLOW_MEASUREMENT_NAMES: tuple[str, ...] = tuple(
    f"{group}.{name}"
    for group, names in WORKFLOW_MEASUREMENT_GROUPS
    for name in names
)


SELECTED_REASON_CODES = (
    "required-by-intent",
    "required-by-requirement",
    "required-dependency",
    "required-context",
    "review-separation",
    "gate-prerequisite",
    "solver-justified",
    "handoff-required",
)
EXCLUDED_REASON_CODES = (
    "outside-allowed-scope",
    "inside-prohibited-scope",
    "unsupported-capability",
    "budget-exceeded",
    "approval-not-authority",
    "evidence-unavailable",
    "solver-not-justified",
    "ui-not-applicable",
    "optional-context-not-selected",
)
UNCERTAINTY_REASON_CODES = (
    "open-decision",
    "blocking-diagnostic",
    "unresolved-contradiction",
    "stale-context",
    "cost-not-available",
    "capability-not-observed",
    "external-effect-ambiguous",
)


@dataclass(frozen=True, slots=True)
class NativeArtifactBinding:
    """Exact path, digest, identity, type, and requiredness of a native artifact."""

    artifact_type: str
    artifact_id: str
    reference: ArtifactReference
    required: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "reference": self.reference.to_dict(),
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class WorkflowTerminalObservation:
    """One cause plus exact M6 identities, never a requested public result."""

    cause: WorkflowTerminalObservationCause
    scheduler_state_id: str
    scheduler_event_head_id: str
    source_artifact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntentTaskLink:
    """Untrusted task trace proposal that deterministic planning must validate."""

    task_id: str
    requirement_ids: tuple[str, ...]
    acceptance_ids: tuple[str, ...]
    context_node_ids: tuple[str, ...]
    solver_request_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "requirement_ids": list(self.requirement_ids),
            "acceptance_ids": list(self.acceptance_ids),
            "context_node_ids": list(self.context_node_ids),
            "solver_request_ids": list(self.solver_request_ids),
        }


@dataclass(frozen=True, slots=True)
class WorkflowDecision:
    """One exact planner selection, exclusion, or uncertainty."""

    subject_kind: str
    subject_id: str
    kind: WorkflowDecisionKind
    reason_code: str
    references: tuple[str, ...]
    blocking: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "kind": self.kind.value,
            "reason_code": self.reason_code,
            "references": list(self.references),
            "blocking": self.blocking,
        }


@dataclass(frozen=True, slots=True)
class ProtectedEffect:
    """Protected native effect that needs fresh M6 authority before host dispatch."""

    effect_id: str
    task_id: str
    effect_kind: EffectKind
    target_paths: tuple[str, ...]
    network_destinations: tuple[str, ...]
    reversible: bool
    ambiguous_on_failure: bool
    approval_types: tuple[str, ...]
    idempotency_scope: str
    effect_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "effect_id": self.effect_id,
            "task_id": self.task_id,
            "effect_kind": self.effect_kind.value,
            "target_paths": list(self.target_paths),
            "network_destinations": list(self.network_destinations),
            "reversible": self.reversible,
            "ambiguous_on_failure": self.ambiguous_on_failure,
            "approval_types": list(self.approval_types),
            "idempotency_scope": self.idempotency_scope,
            "effect_digest": self.effect_digest,
        }


@dataclass(frozen=True, slots=True)
class IntegratedPlanTask:
    """Validated deterministic projection of one native M6 task."""

    task_id: str
    phase: int
    topological_rank: int
    wave: int
    task_kind: str
    dependencies: tuple[str, ...]
    role_id: str
    context_snapshot_id: str
    requirement_ids: tuple[str, ...]
    acceptance_ids: tuple[str, ...]
    context_node_ids: tuple[str, ...]
    solver_request_ids: tuple[str, ...]
    effect_kind: EffectKind
    approval_stops: tuple[str, ...]
    evidence_predicates: tuple[str, ...]
    terminal_predicates: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "phase": self.phase,
            "topological_rank": self.topological_rank,
            "wave": self.wave,
            "task_kind": self.task_kind,
            "dependencies": list(self.dependencies),
            "role_id": self.role_id,
            "context_snapshot_id": self.context_snapshot_id,
            "requirement_ids": list(self.requirement_ids),
            "acceptance_ids": list(self.acceptance_ids),
            "context_node_ids": list(self.context_node_ids),
            "solver_request_ids": list(self.solver_request_ids),
            "effect_kind": self.effect_kind.value,
            "approval_stops": list(self.approval_stops),
            "evidence_predicates": list(self.evidence_predicates),
            "terminal_predicates": list(self.terminal_predicates),
        }


@dataclass(frozen=True, slots=True)
class GateObservation:
    """Recomputed observation of an existing G1-G4 authority."""

    gate_id: str
    status: GateStatus
    evidence_ids: tuple[str, ...]
    blocker_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id,
            "status": self.status.value,
            "evidence_ids": list(self.evidence_ids),
            "blocker_codes": list(self.blocker_codes),
        }


@dataclass(frozen=True, slots=True)
class WorkflowBlocker:
    """One exact blocker retained through state, recovery, and outcome."""

    code: str
    references: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "references": list(self.references)}


@dataclass(frozen=True, slots=True)
class WorkflowMeasurement:
    """One named measurement with explicit availability and native sources."""

    name: str
    status: MeasurementStatus
    value: int | str | None
    unit: str | None
    source_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "value": self.value,
            "unit": self.unit,
            "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True, slots=True)
class WorkflowPublicationObservation:
    """One pinned Git enumeration and validated M6 v2 receipt snapshot."""

    git: GitObservation
    scheduler_state_path: str
    receipts: WorkflowReceiptSnapshot
    tracked_paths: tuple[str, ...]
    untracked_non_ignored_paths: tuple[str, ...]
    receipt_excluded_paths: tuple[str, ...]
    receipt_plan_id: str | None = None


@dataclass(frozen=True, slots=True)
class DevelopmentIntent:
    """Untrusted bounded scope input; this value never grants approval."""

    project_id: str
    candidate: CandidateIdentity
    objective: str
    completion_profile: CompletionProfile
    specification: ArtifactReference
    requirement_baseline_id: str
    requirement_baseline: ArtifactReference
    allowed_paths: tuple[str, ...]
    prohibited_paths: tuple[str, ...]
    required_requirement_ids: tuple[str, ...]
    required_acceptance_ids: tuple[str, ...]
    requested_effects: tuple[EffectKind, ...]
    risk: IntentRisk
    clearance: Sensitivity
    sensitivity: Sensitivity
    budget: SchedulerBudget
    capabilities: tuple[str, ...]
    context_graph: NativeArtifactBinding
    context_query: NativeArtifactBinding
    context_selection: NativeArtifactBinding
    context_snapshot: NativeArtifactBinding
    task_graph: NativeArtifactBinding
    solver_registry: NativeArtifactBinding | None
    solver_requests: tuple[NativeArtifactBinding, ...]
    task_links: tuple[IntentTaskLink, ...]
    required_gate_ids: tuple[str, ...]
    observation_slots: tuple[str, ...]
    ui_required: bool
    predecessor_plan_id: str | None
    predecessor_outcome_id: str | None
    predecessor_state_id: str | None = None
    predecessor_plan: NativeArtifactBinding | None = None
    predecessor_state: NativeArtifactBinding | None = None
    predecessor_outcome: NativeArtifactBinding | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "candidate": self.candidate.to_dict(),
            "objective": self.objective,
            "completion_profile": self.completion_profile.value,
            "specification": self.specification.to_dict(),
            "requirement_baseline_id": self.requirement_baseline_id,
            "requirement_baseline": self.requirement_baseline.to_dict(),
            "allowed_paths": list(self.allowed_paths),
            "prohibited_paths": list(self.prohibited_paths),
            "required_requirement_ids": list(self.required_requirement_ids),
            "required_acceptance_ids": list(self.required_acceptance_ids),
            "requested_effects": [item.value for item in self.requested_effects],
            "risk": self.risk.value,
            "clearance": self.clearance.value,
            "sensitivity": self.sensitivity.value,
            "budget": self.budget.to_dict(),
            "capabilities": list(self.capabilities),
            "context_graph": self.context_graph.to_dict(),
            "context_query": self.context_query.to_dict(),
            "context_selection": self.context_selection.to_dict(),
            "context_snapshot": self.context_snapshot.to_dict(),
            "task_graph": self.task_graph.to_dict(),
            "solver_registry": (
                None if self.solver_registry is None else self.solver_registry.to_dict()
            ),
            "solver_requests": [item.to_dict() for item in self.solver_requests],
            "task_links": [item.to_dict() for item in self.task_links],
            "required_gate_ids": list(self.required_gate_ids),
            "observation_slots": list(self.observation_slots),
            "ui_required": self.ui_required,
            "predecessor_plan_id": self.predecessor_plan_id,
            "predecessor_state_id": self.predecessor_state_id,
            "predecessor_outcome_id": self.predecessor_outcome_id,
            "predecessor_plan": (
                None if self.predecessor_plan is None else self.predecessor_plan.to_dict()
            ),
            "predecessor_state": (
                None if self.predecessor_state is None else self.predecessor_state.to_dict()
            ),
            "predecessor_outcome": (
                None if self.predecessor_outcome is None else self.predecessor_outcome.to_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class IntegratedPlan:
    """Validated deterministic integration plan; never execution authority."""

    intent: NativeArtifactBinding
    project_id: str
    candidate: CandidateIdentity
    sensitivity: Sensitivity
    completion_profile: CompletionProfile
    specification: ArtifactReference
    requirement_baseline_id: str
    requirement_baseline: ArtifactReference
    context_graph: NativeArtifactBinding
    context_query: NativeArtifactBinding
    context_selection: NativeArtifactBinding
    context_snapshot: NativeArtifactBinding
    task_graph: NativeArtifactBinding
    solver_registry: NativeArtifactBinding | None
    solver_requests: tuple[NativeArtifactBinding, ...]
    tasks: tuple[IntegratedPlanTask, ...]
    protected_effects: tuple[ProtectedEffect, ...]
    decisions: tuple[WorkflowDecision, ...]
    budget: SchedulerBudget
    required_gate_ids: tuple[str, ...]
    observation_slots: tuple[str, ...]
    ui_required: bool
    predecessor_plan_id: str | None
    predecessor_outcome_id: str | None
    predecessor_state_id: str | None = None
    predecessor_plan: NativeArtifactBinding | None = None
    predecessor_state: NativeArtifactBinding | None = None
    predecessor_outcome: NativeArtifactBinding | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent.to_dict(),
            "project_id": self.project_id,
            "candidate": self.candidate.to_dict(),
            "sensitivity": self.sensitivity.value,
            "completion_profile": self.completion_profile.value,
            "specification": self.specification.to_dict(),
            "requirement_baseline_id": self.requirement_baseline_id,
            "requirement_baseline": self.requirement_baseline.to_dict(),
            "context_graph": self.context_graph.to_dict(),
            "context_query": self.context_query.to_dict(),
            "context_selection": self.context_selection.to_dict(),
            "context_snapshot": self.context_snapshot.to_dict(),
            "task_graph": self.task_graph.to_dict(),
            "solver_registry": (
                None if self.solver_registry is None else self.solver_registry.to_dict()
            ),
            "solver_requests": [item.to_dict() for item in self.solver_requests],
            "tasks": [item.to_dict() for item in self.tasks],
            "protected_effects": [item.to_dict() for item in self.protected_effects],
            "decisions": [item.to_dict() for item in self.decisions],
            "budget": self.budget.to_dict(),
            "required_gate_ids": list(self.required_gate_ids),
            "observation_slots": list(self.observation_slots),
            "ui_required": self.ui_required,
            "predecessor_plan_id": self.predecessor_plan_id,
            "predecessor_state_id": self.predecessor_state_id,
            "predecessor_outcome_id": self.predecessor_outcome_id,
            "predecessor_plan": (
                None if self.predecessor_plan is None else self.predecessor_plan.to_dict()
            ),
            "predecessor_state": (
                None if self.predecessor_state is None else self.predecessor_state.to_dict()
            ),
            "predecessor_outcome": (
                None if self.predecessor_outcome is None else self.predecessor_outcome.to_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class WorkflowTaskProjection:
    """Exact M6 task status retained in one M8 projection."""

    task_id: str
    state: TaskState
    outcome: TaskOutcome
    attempt: int
    fence: int
    blocker_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "outcome": self.outcome.value,
            "attempt": self.attempt,
            "fence": self.fence,
            "blocker_codes": list(self.blocker_codes),
        }


@dataclass(frozen=True, slots=True)
class WorkflowState:
    """Reproducible projection over native stores and immutable evidence."""

    plan_id: str
    candidate: CandidateIdentity
    sensitivity: Sensitivity
    status: TaskState
    scheduler_graph_id: str
    scheduler_state_id: str
    scheduler_event_sequence: int
    scheduler_event_head_sha256: str
    tasks: tuple[WorkflowTaskProjection, ...]
    solver_verification_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    approval_ids: tuple[str, ...]
    gates: tuple[GateObservation, ...]
    handoff_id: str | None
    handoff_status: str | None
    blockers: tuple[WorkflowBlocker, ...]
    ambiguities: tuple[str, ...]
    measurements: tuple[WorkflowMeasurement, ...]
    observation_artifacts: tuple[NativeArtifactBinding, ...]
    event_chain: tuple[NativeArtifactBinding, ...]
    latest_event: NativeArtifactBinding
    transition_count: int
    recorded_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "candidate": self.candidate.to_dict(),
            "sensitivity": self.sensitivity.value,
            "status": self.status.value,
            "scheduler_graph_id": self.scheduler_graph_id,
            "scheduler_state_id": self.scheduler_state_id,
            "scheduler_event_sequence": self.scheduler_event_sequence,
            "scheduler_event_head_sha256": self.scheduler_event_head_sha256,
            "tasks": [item.to_dict() for item in self.tasks],
            "solver_verification_ids": list(self.solver_verification_ids),
            "evidence_ids": list(self.evidence_ids),
            "review_ids": list(self.review_ids),
            "approval_ids": list(self.approval_ids),
            "gates": [item.to_dict() for item in self.gates],
            "handoff_id": self.handoff_id,
            "handoff_status": self.handoff_status,
            "blockers": [item.to_dict() for item in self.blockers],
            "ambiguities": list(self.ambiguities),
            "measurements": [item.to_dict() for item in self.measurements],
            "observation_artifacts": [item.to_dict() for item in self.observation_artifacts],
            "event_chain": [item.to_dict() for item in self.event_chain],
            "latest_event": self.latest_event.to_dict(),
            "transition_count": self.transition_count,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    """One immutable prior-state-linked integration audit event."""

    sequence: int
    previous_event_id: str | None
    prior_state_id: str | None
    plan_id: str
    candidate: CandidateIdentity
    sensitivity: Sensitivity
    cause: WorkflowEventCause
    before_status: TaskState
    after_status: TaskState
    scheduler_event_head_before: str
    scheduler_event_head_after: str
    effect_disposition: EffectDisposition
    actor: str
    recorded_at: str
    idempotency_key: str
    native_input_ids: tuple[str, ...]
    native_output_ids: tuple[str, ...]
    task_id: str | None
    effect_id: str | None
    approval_id: str | None
    reason_codes: tuple[str, ...]
    prior_state: NativeArtifactBinding | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "previous_event_id": self.previous_event_id,
            "prior_state_id": self.prior_state_id,
            "prior_state": None if self.prior_state is None else self.prior_state.to_dict(),
            "plan_id": self.plan_id,
            "candidate": self.candidate.to_dict(),
            "sensitivity": self.sensitivity.value,
            "cause": self.cause.value,
            "before_status": self.before_status.value,
            "after_status": self.after_status.value,
            "scheduler_event_head_before": self.scheduler_event_head_before,
            "scheduler_event_head_after": self.scheduler_event_head_after,
            "effect_disposition": self.effect_disposition.value,
            "actor": self.actor,
            "recorded_at": self.recorded_at,
            "idempotency_key": self.idempotency_key,
            "native_input_ids": list(self.native_input_ids),
            "native_output_ids": list(self.native_output_ids),
            "task_id": self.task_id,
            "effect_id": self.effect_id,
            "approval_id": self.approval_id,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class WorkflowOutcome:
    """Truthful terminal or blocked summary over native authorities."""

    plan_id: str
    lineage_plan_ids: tuple[str, ...]
    terminal_state_id: str
    candidate: CandidateIdentity
    sensitivity: Sensitivity
    disposition: WorkflowDisposition
    claim_state: OutcomeClaimState
    completion_profile: CompletionProfile
    scheduler_state_id: str
    solver_verification_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    gates: tuple[GateObservation, ...]
    effect_ids: tuple[str, ...]
    approval_ids: tuple[str, ...]
    ambiguities: tuple[str, ...]
    blockers: tuple[WorkflowBlocker, ...]
    measurements: tuple[WorkflowMeasurement, ...]
    observation_artifacts: tuple[NativeArtifactBinding, ...]
    handoff_id: str | None
    handoff_status: str | None
    next_action: str
    completed_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "lineage_plan_ids": list(self.lineage_plan_ids),
            "terminal_state_id": self.terminal_state_id,
            "candidate": self.candidate.to_dict(),
            "sensitivity": self.sensitivity.value,
            "disposition": self.disposition.value,
            "claim_state": self.claim_state.value,
            "completion_profile": self.completion_profile.value,
            "scheduler_state_id": self.scheduler_state_id,
            "solver_verification_ids": list(self.solver_verification_ids),
            "evidence_ids": list(self.evidence_ids),
            "review_ids": list(self.review_ids),
            "gates": [item.to_dict() for item in self.gates],
            "effect_ids": list(self.effect_ids),
            "approval_ids": list(self.approval_ids),
            "ambiguities": list(self.ambiguities),
            "blockers": [item.to_dict() for item in self.blockers],
            "measurements": [item.to_dict() for item in self.measurements],
            "observation_artifacts": [item.to_dict() for item in self.observation_artifacts],
            "handoff_id": self.handoff_id,
            "handoff_status": self.handoff_status,
            "next_action": self.next_action,
            "completed_at": self.completed_at,
        }


type WorkflowValue = (
    DevelopmentIntent | IntegratedPlan | WorkflowState | WorkflowEvent | WorkflowOutcome
)
