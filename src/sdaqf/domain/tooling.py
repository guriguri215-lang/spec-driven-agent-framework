"""Immutable M2 Skill, tool, approval, and checkpoint contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from sdaqf.domain.orchestration import RiskLevel


class ApprovalRequirement(StrEnum):
    """Approval required by one operation."""

    NOT_REQUIRED = "not_required"
    MAY_BE_REQUIRED = "may_be_required"
    REQUIRED = "required"
    PROHIBITED = "prohibited"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """One validated Tool Registry entry."""

    name: str
    capability: str
    version_command: tuple[str, ...]
    version_pattern: str
    minimum_version: tuple[int, ...] | None
    platforms: tuple[str, ...]
    normal_scope: tuple[str, ...]
    protected_paths: tuple[str, ...]
    network_required: bool
    network_destinations: tuple[str, ...]
    optional: bool
    risk: RiskLevel
    technical_approval: ApprovalRequirement
    owner_approval: ApprovalRequirement
    max_attempts: int


@dataclass(frozen=True, slots=True)
class ToolRegistry:
    """Validated, versioned Tool Registry."""

    tools: tuple[ToolDefinition, ...]
    schema_version: str = "2.0"

    def by_name(self, name: str) -> ToolDefinition | None:
        """Return the named tool when present."""

        return next((tool for tool in self.tools if tool.name == name), None)


@dataclass(frozen=True, slots=True, init=False)
class ExecutionApproval:
    """Strict-loader-issued approval for one exact tool operation."""

    schema_version: str
    approval_id: str
    approval_type: str
    action: str
    tool_name: str
    command: tuple[str, ...]
    network_destinations: tuple[str, ...]
    normal_scope: tuple[str, ...]
    protected_paths: tuple[str, ...]
    risk: RiskLevel
    status: str
    rationale: str
    reversible: bool
    approved_by: str
    approved_at: datetime
    expires_at: datetime
    lifetime: str
    max_executions: int

    def __init__(self) -> None:
        """Reject caller-asserted approvals; use the strict application loader."""

        raise TypeError("ExecutionApproval must be created by its strict loader.")

    @classmethod
    def _from_validated_record(
        cls,
        *,
        schema_version: str,
        approval_id: str,
        approval_type: str,
        action: str,
        tool_name: str,
        command: tuple[str, ...],
        network_destinations: tuple[str, ...],
        normal_scope: tuple[str, ...],
        protected_paths: tuple[str, ...],
        risk: RiskLevel,
        status: str,
        rationale: str,
        reversible: bool,
        approved_by: str,
        approved_at: datetime,
        expires_at: datetime,
        lifetime: str,
        max_executions: int,
    ) -> Self:
        """Create a record only after application-layer contract validation."""

        value = object.__new__(cls)
        fields = {
            "schema_version": schema_version,
            "approval_id": approval_id,
            "approval_type": approval_type,
            "action": action,
            "tool_name": tool_name,
            "command": command,
            "network_destinations": network_destinations,
            "normal_scope": normal_scope,
            "protected_paths": protected_paths,
            "risk": risk,
            "status": status,
            "rationale": rationale,
            "reversible": reversible,
            "approved_by": approved_by,
            "approved_at": approved_at,
            "expires_at": expires_at,
            "lifetime": lifetime,
            "max_executions": max_executions,
        }
        for name, item in fields.items():
            object.__setattr__(value, name, item)
        return value


class ToolObservationStatus(StrEnum):
    """Distinct tool presence, policy, and execution outcomes."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_CHECKED = "NOT_CHECKED"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    TIMEOUT = "TIMEOUT"
    NON_ZERO_EXIT = "NON_ZERO_EXIT"
    BLOCKED = "BLOCKED"


class FailureClass(StrEnum):
    """Normalized failure classification for checkpoints."""

    NONE = "NONE"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    UNSUPPORTED_VERSION = "UNSUPPORTED_VERSION"
    PROCESS_TIMEOUT = "PROCESS_TIMEOUT"
    NON_ZERO_EXIT = "NON_ZERO_EXIT"
    PERMISSION_DENIAL = "PERMISSION_DENIAL"
    SANDBOX_DENIAL = "SANDBOX_DENIAL"
    NETWORK_DENIAL = "NETWORK_DENIAL"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    AUTHORIZATION_FAILURE = "AUTHORIZATION_FAILURE"
    TEST_FAILURE = "TEST_FAILURE"
    WORKFLOW_FAILURE = "WORKFLOW_FAILURE"
    EXTERNAL_SERVICE_FAILURE = "EXTERNAL_SERVICE_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


@dataclass(frozen=True, slots=True)
class ToolObservation:
    """Bounded result of one safe version probe."""

    tool_name: str
    status: ToolObservationStatus
    failure_class: FailureClass
    detail: str
    version: str | None
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int | None = None
    execution_mode: str = "not_executed"
    approval_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return {
            "tool_name": self.tool_name,
            "status": self.status.value,
            "failure_class": self.failure_class.value,
            "detail": self.detail,
            "version": self.version,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "duration_ms": self.duration_ms,
            "execution_mode": self.execution_mode,
            "approval_ids": list(self.approval_ids),
        }


class CheckpointState(StrEnum):
    """M2 execution checkpoint states."""

    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    VERIFICATION = "verification"
    COMPLETED = "completed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Resume-sensitive repository and plan identity."""

    plan_version: str
    specification_digest: str
    git_head: str
    worktree_digest: str


@dataclass(frozen=True, slots=True)
class ExecutionCheckpoint:
    """Bounded retry and execution state."""

    checkpoint_id: str
    tool_name: str
    command_digest: str
    context: ExecutionContext
    state: CheckpointState
    attempts: int
    last_failure: FailureClass
    state_change_token: str | None
    observation: ToolObservation | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return {
            "schema_version": "1.0",
            "checkpoint_id": self.checkpoint_id,
            "tool_name": self.tool_name,
            "command_digest": self.command_digest,
            "context": {
                "plan_version": self.context.plan_version,
                "specification_digest": self.context.specification_digest,
                "git_head": self.context.git_head,
                "worktree_digest": self.context.worktree_digest,
            },
            "state": self.state.value,
            "attempts": self.attempts,
            "last_failure": self.last_failure.value,
            "state_change_token": self.state_change_token,
            "observation": (
                self.observation.to_dict()
                if self.observation is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    """Versioned reusable template metadata."""

    template_id: str
    target: str
    compatible_version: str
    dependencies: tuple[str, ...]
    provenance: str
    license_status: str
    prohibited_conditions: tuple[str, ...]
    validated_on: str
