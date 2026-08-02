"""Immutable M6 scheduler domain contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from sdaqf.domain.context import Sensitivity
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity


class SchedulerArtifactType(StrEnum):
    """Portable M6 artifact types."""

    TASK_GRAPH = "task-graph"
    SCHEDULER_STATE = "scheduler-state"
    LEASE = "lease"
    MAILBOX_MESSAGE = "mailbox-message"
    SCHEDULER_EVENT = "scheduler-event"
    BUDGET_LEDGER = "budget-ledger"
    WORKTREE_LEASE = "worktree-lease"


class TaskKind(StrEnum):
    """Supported scheduler task kinds."""

    DISCOVERY = "discovery"
    IMPLEMENTATION = "implementation"
    TEST = "test"
    TOOL = "tool"
    REVIEW = "review"
    INTEGRATION = "integration"
    SOLVER = "solver"
    HANDOFF = "handoff"


class TaskState(StrEnum):
    """Normative FR-EXE task states."""

    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class DispatchPhase(StrEnum):
    """Host-dispatch phase orthogonal to task state."""

    NOT_DISPATCHED = "not_dispatched"
    INTENT_PENDING = "intent_pending"
    ACCEPTED = "accepted"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLATION_ACKNOWLEDGED = "cancellation_acknowledged"


class TaskOutcome(StrEnum):
    """Terminal or ambiguous task outcome."""

    NONE = "none"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class EffectKind(StrEnum):
    """Effect class used for conservative retry policy."""

    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"
    EXTERNAL = "external"
    DESTRUCTIVE = "destructive"


class MessageType(StrEnum):
    """Exact M6 mailbox variants."""

    DISPATCH_INTENT = "dispatch_intent"
    DISPATCH_ACKNOWLEDGEMENT = "dispatch_acknowledgement"
    HEARTBEAT = "heartbeat"
    TASK_RESULT = "task_result"
    CANCEL_REQUEST = "cancel_request"
    CANCEL_ACKNOWLEDGEMENT = "cancel_acknowledgement"
    WORKTREE_REQUEST = "worktree_request"
    WORKTREE_OBSERVATION = "worktree_observation"
    APPROVAL_DECISION = "approval_decision"
    CAPABILITY_OBSERVATION = "capability_observation"


class MessageDirection(StrEnum):
    """Allowed mailbox directions."""

    SCHEDULER_TO_HOST = "scheduler_to_host"
    HOST_TO_SCHEDULER = "host_to_scheduler"
    OWNER_TO_SCHEDULER = "owner_to_scheduler"


class LeaseStatus(StrEnum):
    """Lease lifecycle states."""

    CURRENT = "current"
    RELEASED = "released"
    EXPIRED = "expired"
    REJECTED = "rejected"


class WorktreeLeaseStatus(StrEnum):
    """Host-observed worktree lease lifecycle."""

    REQUESTED = "requested"
    OBSERVED = "observed"
    INTEGRATED = "integrated"
    RELEASED = "released"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ContextBinding:
    """Exact reference to one validated M5 Context Snapshot."""

    artifact_id: str
    reference: ArtifactReference
    sensitivity: Sensitivity
    candidate: CandidateIdentity

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "path": self.reference.path,
            "sha256": self.reference.sha256,
            "sensitivity": self.sensitivity.value,
            "candidate": self.candidate.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SchedulerBudget:
    """Hard integer scheduler resource limits."""

    max_agents: int
    max_concurrency: int
    max_reasoning_effort: str
    max_dispatches: int
    max_retries: int
    max_wall_time_seconds: int
    max_tool_calls: int
    max_context_bytes_per_dispatch: int
    max_context_bytes_total: int
    max_solver_calls: int
    max_solver_steps: int
    cost_status: str
    currency: str | None
    max_microunits: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "max_agents": self.max_agents,
            "max_concurrency": self.max_concurrency,
            "max_reasoning_effort": self.max_reasoning_effort,
            "max_dispatches": self.max_dispatches,
            "max_retries": self.max_retries,
            "max_wall_time_seconds": self.max_wall_time_seconds,
            "max_tool_calls": self.max_tool_calls,
            "max_context_bytes_per_dispatch": self.max_context_bytes_per_dispatch,
            "max_context_bytes_total": self.max_context_bytes_total,
            "max_solver_calls": self.max_solver_calls,
            "max_solver_steps": self.max_solver_steps,
            "cost": {
                "status": self.cost_status,
                "currency": self.currency,
                "max_microunits": self.max_microunits,
            },
        }


@dataclass(frozen=True, slots=True)
class SchedulerTask:
    """One immutable Task Graph node."""

    task_id: str
    kind: TaskKind
    dependencies: tuple[str, ...]
    role_id: str
    context_snapshot_id: str
    required_tools: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    owned_paths: tuple[str, ...]
    worktree_assignment: str | None
    effect_kind: EffectKind
    approval_stops: tuple[str, ...]
    evidence_predicate: tuple[str, ...]
    review_targets: tuple[str, ...]
    terminal_predicate: tuple[str, ...]
    wave: int
    max_attempts: int

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "kind": self.kind.value,
            "dependencies": list(self.dependencies),
            "role_id": self.role_id,
            "context_snapshot_id": self.context_snapshot_id,
            "required_tools": list(self.required_tools),
            "required_capabilities": list(self.required_capabilities),
            "owned_paths": list(self.owned_paths),
            "worktree_assignment": self.worktree_assignment,
            "effect_kind": self.effect_kind.value,
            "approval_stops": list(self.approval_stops),
            "evidence_predicate": list(self.evidence_predicate),
            "review_targets": list(self.review_targets),
            "terminal_predicate": list(self.terminal_predicate),
            "wave": self.wave,
            "max_attempts": self.max_attempts,
        }


@dataclass(frozen=True, slots=True)
class TaskGraph:
    """Validated immutable task DAG and all exact input references."""

    candidate: CandidateIdentity
    agent_registry: ArtifactReference
    tool_registry: ArtifactReference
    orchestration_request: ArtifactReference
    worktree_plan: ArtifactReference | None
    contexts: tuple[ContextBinding, ...]
    budget: SchedulerBudget
    tasks: tuple[SchedulerTask, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.to_dict(),
            "agent_registry": self.agent_registry.to_dict(),
            "tool_registry": self.tool_registry.to_dict(),
            "orchestration_request": self.orchestration_request.to_dict(),
            "worktree_plan": (None if self.worktree_plan is None else self.worktree_plan.to_dict()),
            "contexts": [item.to_dict() for item in self.contexts],
            "budget": self.budget.to_dict(),
            "tasks": [item.to_dict() for item in self.tasks],
        }


@dataclass(frozen=True, slots=True)
class Blocker:
    """One deterministic task blocker."""

    code: str
    references: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "references": list(self.references)}


@dataclass(frozen=True, slots=True)
class TaskProjection:
    """Current durable projection for one task."""

    task_id: str
    state: TaskState
    dispatch_phase: DispatchPhase
    outcome: TaskOutcome
    attempt: int
    fence: int
    blockers: tuple[Blocker, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "dispatch_phase": self.dispatch_phase.value,
            "outcome": self.outcome.value,
            "attempt": self.attempt,
            "fence": self.fence,
            "blockers": [item.to_dict() for item in self.blockers],
        }


@dataclass(frozen=True, slots=True)
class SchedulerState:
    """Deterministic bounded public projection of one scheduler database."""

    graph_id: str
    candidate: CandidateIdentity
    tasks: tuple[TaskProjection, ...]
    ready_order: tuple[str, ...]
    lease_ids: tuple[str, ...]
    message_ids: tuple[str, ...]
    budget_ledger_id: str
    worktree_lease_ids: tuple[str, ...]
    event_sequence: int
    event_head_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "graph_id": self.graph_id,
            "candidate": self.candidate.to_dict(),
            "tasks": [item.to_dict() for item in self.tasks],
            "ready_order": list(self.ready_order),
            "lease_ids": list(self.lease_ids),
            "message_ids": list(self.message_ids),
            "budget_ledger_id": self.budget_ledger_id,
            "worktree_lease_ids": list(self.worktree_lease_ids),
            "event_sequence": self.event_sequence,
            "event_head_sha256": self.event_head_sha256,
        }


@dataclass(frozen=True, slots=True)
class Lease:
    """Fenced single-owner task lease."""

    graph_id: str
    task_id: str
    candidate: CandidateIdentity
    context_snapshot_id: str
    attempt: int
    owner_id: str
    fence: int
    idempotency_key: str
    acquired_at: str
    heartbeat_at: str
    expires_at: str
    ttl_seconds: int
    heartbeat_interval_seconds: int
    status: LeaseStatus
    release_outcome: TaskOutcome

    def to_dict(self) -> dict[str, object]:
        return {
            "graph_id": self.graph_id,
            "task_id": self.task_id,
            "candidate": self.candidate.to_dict(),
            "context_snapshot_id": self.context_snapshot_id,
            "attempt": self.attempt,
            "owner_id": self.owner_id,
            "fence": self.fence,
            "idempotency_key": self.idempotency_key,
            "acquired_at": self.acquired_at,
            "heartbeat_at": self.heartbeat_at,
            "expires_at": self.expires_at,
            "ttl_seconds": self.ttl_seconds,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "status": self.status.value,
            "release_outcome": self.release_outcome.value,
        }


@dataclass(frozen=True, slots=True)
class MailboxMessage:
    """One immutable typed scheduler mailbox message."""

    message_type: MessageType
    direction: MessageDirection
    sender: str
    recipient: str
    graph_id: str
    task_id: str | None
    candidate: CandidateIdentity
    context_snapshot_id: str | None
    attempt: int | None
    lease_id: str | None
    fence: int | None
    idempotency_key: str | None
    sensitivity: Sensitivity
    provenance: tuple[ArtifactReference, ...]
    causal_parent_message_ids: tuple[str, ...]
    recorded_at: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))

    def to_dict(self) -> dict[str, object]:
        return {
            "message_type": self.message_type.value,
            "direction": self.direction.value,
            "sender": self.sender,
            "recipient": self.recipient,
            "graph_id": self.graph_id,
            "task_id": self.task_id,
            "candidate": self.candidate.to_dict(),
            "context_snapshot_id": self.context_snapshot_id,
            "attempt": self.attempt,
            "lease_id": self.lease_id,
            "fence": self.fence,
            "idempotency_key": self.idempotency_key,
            "sensitivity": self.sensitivity.value,
            "provenance": [item.to_dict() for item in self.provenance],
            "causal_parent_message_ids": list(self.causal_parent_message_ids),
            "recorded_at": self.recorded_at,
            "payload": _thaw_mapping(self.payload),
        }


@dataclass(frozen=True, slots=True)
class SchedulerEvent:
    """One append-only hash-chained scheduler transition."""

    sequence: int
    previous_event_sha256: str
    actor: str
    cause: str
    graph_id: str
    task_id: str | None
    candidate: CandidateIdentity
    context_snapshot_id: str | None
    before_state: str | None
    after_state: str | None
    lease_id: str | None
    message_id: str | None
    result_id: str | None
    approval_id: str | None
    budget_deltas: Mapping[str, int]
    task_projection: TaskProjection | None
    reason: str | None
    recorded_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_deltas", _freeze_integer_mapping(self.budget_deltas))

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "previous_event_sha256": self.previous_event_sha256,
            "actor": self.actor,
            "cause": self.cause,
            "graph_id": self.graph_id,
            "task_id": self.task_id,
            "candidate": self.candidate.to_dict(),
            "context_snapshot_id": self.context_snapshot_id,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "lease_id": self.lease_id,
            "message_id": self.message_id,
            "result_id": self.result_id,
            "approval_id": self.approval_id,
            "budget_deltas": dict(self.budget_deltas),
            "task_projection": (
                None if self.task_projection is None else self.task_projection.to_dict()
            ),
            "reason": self.reason,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class BudgetLedger:
    """Transactional reservation and usage projection."""

    graph_id: str
    limits: SchedulerBudget
    reserved: Mapping[str, int]
    used: Mapping[str, int]
    availability: Mapping[str, str]
    blocker_codes: tuple[str, ...]
    event_sequence: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "reserved", _freeze_integer_mapping(self.reserved))
        object.__setattr__(self, "used", _freeze_integer_mapping(self.used))
        object.__setattr__(self, "availability", _freeze_string_mapping(self.availability))

    def to_dict(self) -> dict[str, object]:
        return {
            "graph_id": self.graph_id,
            "limits": self.limits.to_dict(),
            "reserved": dict(self.reserved),
            "used": dict(self.used),
            "availability": dict(self.availability),
            "blocker_codes": list(self.blocker_codes),
            "event_sequence": self.event_sequence,
        }


@dataclass(frozen=True, slots=True)
class WorktreeLease:
    """Durable host-observed worktree authority record."""

    graph_id: str
    task_id: str
    worktree_plan: ArtifactReference
    base_commit: str
    worktree: str
    owner_id: str
    owned_paths: tuple[str, ...]
    fence: int
    observed_digest: str | None
    status: WorktreeLeaseStatus
    integration_state: str
    ambiguous: bool
    recovery_guidance: str

    def to_dict(self) -> dict[str, object]:
        return {
            "graph_id": self.graph_id,
            "task_id": self.task_id,
            "worktree_plan": self.worktree_plan.to_dict(),
            "base_commit": self.base_commit,
            "worktree": self.worktree,
            "owner_id": self.owner_id,
            "owned_paths": list(self.owned_paths),
            "fence": self.fence,
            "observed_digest": self.observed_digest,
            "status": self.status.value,
            "integration_state": self.integration_state,
            "ambiguous": self.ambiguous,
            "recovery_guidance": self.recovery_guidance,
        }


type SchedulerValue = (
    TaskGraph
    | SchedulerState
    | Lease
    | MailboxMessage
    | SchedulerEvent
    | BudgetLedger
    | WorktreeLease
)


def scheduler_value_dict(value: SchedulerValue) -> dict[str, Any]:
    """Return a JSON object without widening the stable package exports."""

    return value.to_dict()


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in sorted(value.items())}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    frozen = _freeze_json(value)
    assert isinstance(frozen, Mapping)
    return frozen


def _thaw_mapping(value: Mapping[str, object]) -> dict[str, object]:
    thawed = _thaw_json(value)
    assert isinstance(thawed, dict)
    return thawed


def _freeze_integer_mapping(value: Mapping[str, int]) -> Mapping[str, int]:
    return MappingProxyType(dict(sorted(value.items())))


def _freeze_string_mapping(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(sorted(value.items())))
