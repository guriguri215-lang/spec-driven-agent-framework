"""Immutable M2 agent-orchestration contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ProblemType(StrEnum):
    """Supported orchestration problem classes."""

    DISCOVERY = "discovery"
    IMPLEMENTATION = "implementation"
    TEST_DESIGN = "test_design"
    LOG_ANALYSIS = "log_analysis"
    REVIEW = "review"


class WorkScale(StrEnum):
    """Bounded problem scale."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class RiskLevel(StrEnum):
    """Ordered orchestration risk."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PROHIBITED = "prohibited"

    @property
    def rank(self) -> int:
        """Return a stable comparison rank."""

        return tuple(RiskLevel).index(self)


class ParallelismMode(StrEnum):
    """Supported parallel-execution shapes."""

    SEQUENTIAL = "sequential"
    READ_PARALLEL = "read_parallel"
    WRITE_PARALLEL = "write_parallel"


class ReasoningEffort(StrEnum):
    """Bounded reasoning budget."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        """Return a stable comparison rank."""

        return tuple(ReasoningEffort).index(self)


class AgentExecutionMode(StrEnum):
    """How a selected role is executed."""

    NATIVE_SUBAGENT = "native_subagent"
    INDEPENDENT_SESSION = "independent_session"
    SEQUENTIAL = "sequential"


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """One validated Agent Registry entry."""

    role_id: str
    display_name: str
    responsibilities: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    tools: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    problem_types: tuple[ProblemType, ...]
    scales: tuple[WorkScale, ...]
    max_risk: RiskLevel
    parallelism: tuple[ParallelismMode, ...]
    can_write: bool
    independent_reviewer: bool


@dataclass(frozen=True, slots=True)
class AgentRegistry:
    """Validated, versioned Agent Registry."""

    agents: tuple[AgentDefinition, ...]
    schema_version: str = "2.0"

    def by_role(self, role_id: str) -> AgentDefinition | None:
        """Return the named role when present."""

        return next((agent for agent in self.agents if agent.role_id == role_id), None)


@dataclass(frozen=True, slots=True)
class AgentBudget:
    """Agent-count, concurrency, and reasoning limits."""

    max_agents: int
    max_concurrency: int
    max_reasoning_effort: ReasoningEffort


@dataclass(frozen=True, slots=True)
class OrchestrationRequest:
    """Validated selection inputs."""

    request_id: str
    problem_type: ProblemType
    scale: WorkScale
    risk: RiskLevel
    parallelism: ParallelismMode
    requested_roles: tuple[str, ...]
    native_subagents_available: bool
    independent_session_available: bool
    budget: AgentBudget


@dataclass(frozen=True, slots=True)
class WorktreeAssignment:
    """One isolated writer's exact ownership."""

    role_id: str
    worktree: str
    owned_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorktreePlan:
    """Validated parallel-write isolation plan."""

    base_commit: str
    integrator_role: str
    assignments: tuple[WorktreeAssignment, ...]


@dataclass(frozen=True, slots=True)
class AgentAssignment:
    """One justified role selection."""

    role_id: str
    reason: str
    execution_mode: AgentExecutionMode
    reasoning_effort: ReasoningEffort
    wave: int
    dispatch_prompt: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "role_id": self.role_id,
            "reason": self.reason,
            "execution_mode": self.execution_mode.value,
            "reasoning_effort": self.reasoning_effort.value,
            "wave": self.wave,
            "dispatch_prompt": self.dispatch_prompt,
        }


@dataclass(frozen=True, slots=True)
class OrchestrationPlan:
    """Deterministic fail-closed role-selection result."""

    request_id: str
    assignments: tuple[AgentAssignment, ...]
    effective_concurrency: int
    warnings: tuple[str, ...]
    worktree_plan: WorktreePlan | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        worktree: dict[str, object] | None = None
        if self.worktree_plan is not None:
            worktree = {
                "base_commit": self.worktree_plan.base_commit,
                "integrator_role": self.worktree_plan.integrator_role,
                "assignments": [
                    {
                        "role_id": item.role_id,
                        "worktree": item.worktree,
                        "owned_paths": list(item.owned_paths),
                    }
                    for item in self.worktree_plan.assignments
                ],
            }
        return {
            "schema_version": "1.0",
            "request_id": self.request_id,
            "assignments": [item.to_dict() for item in self.assignments],
            "effective_concurrency": self.effective_concurrency,
            "warnings": list(self.warnings),
            "worktree_plan": worktree,
        }


class AgentResultStatus(StrEnum):
    """Structured agent completion state."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    REJECTED = "rejected"


class FindingSeverity(StrEnum):
    """Review finding severity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Return a stable comparison rank."""

        return tuple(FindingSeverity).index(self)


class EvidenceStrength(StrEnum):
    """Bounded evidence quality used for disagreements."""

    UNVERIFIED = "unverified"
    INDIRECT = "indirect"
    DIRECT = "direct"
    COUNTEREXAMPLE = "counterexample"

    @property
    def rank(self) -> int:
        """Return a stable comparison rank."""

        return tuple(EvidenceStrength).index(self)


@dataclass(frozen=True, slots=True)
class AgentFinding:
    """One bounded, traceable structured finding."""

    finding_id: str
    severity: FindingSeverity
    statement: str
    specification_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    evidence_strength: EvidenceStrength
    counterexample: str | None


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Validated summary returned by one agent."""

    agent_id: str
    role_id: str
    status: AgentResultStatus
    summary: str
    findings: tuple[AgentFinding, ...]
    changed_paths: tuple[str, ...]
    reviewed_agent_ids: tuple[str, ...]
    self_approved: bool


@dataclass(frozen=True, slots=True)
class DisagreementResolution:
    """Evidence-based resolution that never treats a vote as proof."""

    finding_id: str
    selected_agent_id: str
    rationale: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-compatible representation."""

        return {
            "finding_id": self.finding_id,
            "selected_agent_id": self.selected_agent_id,
            "rationale": self.rationale,
        }
