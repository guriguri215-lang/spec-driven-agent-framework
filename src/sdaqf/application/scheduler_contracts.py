"""Strict content-addressed contracts for the M6 scheduler."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sdaqf.application.context_contracts import (
    ContextContractError,
    canonical_json_bytes,
    load_context_artifact,
)
from sdaqf.application.contracts import (
    ContractError,
    array_value,
    boolean_value,
    enum_value,
    integer_value,
    object_value,
    only_keys,
    parse_artifact_reference,
    parse_candidate_identity,
    parse_json_object_bytes,
    path_free_text,
    path_free_tuple,
    safe_relative_path,
    sha256,
    string_tuple,
    string_value,
    verify_artifact,
)
from sdaqf.application.orchestration import (
    AgentOrchestrator,
    OrchestrationContractError,
    load_agent_registry,
    load_agent_result,
    load_orchestration_request,
    load_worktree_plan,
    validate_agent_tool_references,
)
from sdaqf.application.tooling import ToolContractError, load_tool_registry
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.context import ContextArtifactType, ContextSnapshot, Sensitivity
from sdaqf.domain.orchestration import AgentResult, AgentResultStatus, ReasoningEffort
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.scheduler import (
    Blocker,
    BudgetLedger,
    ContextBinding,
    DispatchPhase,
    EffectKind,
    Lease,
    LeaseStatus,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerBudget,
    SchedulerEvent,
    SchedulerState,
    SchedulerTask,
    SchedulerValue,
    TaskGraph,
    TaskKind,
    TaskOutcome,
    TaskProjection,
    TaskState,
    WorktreeLease,
    WorktreeLeaseStatus,
)

MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_MESSAGE_BYTES = 64 * 1024
MAX_TASKS = 4096
MAX_REFERENCES = 64
ZERO_SHA256 = "0" * 64

EVENT_CAUSES = frozenset(
    {
        "approval-consumed",
        "approval-proposal-expired",
        "approval-received",
        "cancel-acknowledgement",
        "cancel-request",
        "capability-observed",
        "dispatch-accepted",
        "dispatch-approval-blocked",
        "dispatch-budget-blocked",
        "dispatch-intent",
        "dispatch-rejected",
        "duplicate-message",
        "heartbeat",
        "initialize",
        "lease-expired",
        "message-rejected",
        "readiness-refreshed",
        "result-received",
        "result-terminal",
        "verification-blocked",
        "verification-completed",
        "wall-time-observed",
        "worktree-observed",
        "worktree-request",
    }
)

_PREFIX: dict[SchedulerArtifactType, str] = {
    SchedulerArtifactType.TASK_GRAPH: "M6-TASK-GRAPH-",
    SchedulerArtifactType.SCHEDULER_STATE: "M6-SCHEDULER-STATE-",
    SchedulerArtifactType.LEASE: "M6-LEASE-",
    SchedulerArtifactType.MAILBOX_MESSAGE: "M6-MESSAGE-",
    SchedulerArtifactType.SCHEDULER_EVENT: "M6-EVENT-",
    SchedulerArtifactType.BUDGET_LEDGER: "M6-BUDGET-LEDGER-",
    SchedulerArtifactType.WORKTREE_LEASE: "M6-WORKTREE-LEASE-",
}
_TASK_ID = re.compile(r"^TSK-[A-Z0-9][A-Z0-9-]{0,63}$")
_HOST_ID = re.compile(r"^HST-[A-Z0-9][A-Z0-9-]{0,63}$")
_WORKER_ID = re.compile(r"^WRK-[A-Z0-9][A-Z0-9-]{0,63}$")
_IDEMPOTENCY = re.compile(r"^IDEM-[0-9A-F]{64}$")
_M6_ID = re.compile(r"^M6-[A-Z-]+-[0-9A-F]{64}$")
_CONTEXT_ID = re.compile(r"^CTX-SNAPSHOT-[0-9A-F]{64}$")
_ROLE_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_APPROVAL_ID = re.compile(r"^APR-[A-Z0-9][A-Z0-9-]{0,95}$")
_RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_APPROVAL_ACTORS = {
    "owner": ("HST-OWNER", "Owner"),
    "technical_sandbox": (
        "HST-TECHNICAL-SANDBOX",
        "Technical sandbox reviewer",
    ),
}


class SchedulerContractError(ContractError):
    """One M6 scheduler artifact violates its strict contract."""


@dataclass(frozen=True, slots=True)
class LoadedSchedulerArtifact:
    """A validated content-addressed M6 artifact."""

    artifact_type: SchedulerArtifactType
    artifact_id: str
    value: SchedulerValue

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "artifact_type": self.artifact_type.value,
            "artifact_id": self.artifact_id,
            "content": self.value.to_dict(),
        }


def scheduler_identity(artifact_type: SchedulerArtifactType, content: object) -> str:
    """Return the full uppercase content identity for one M6 value."""

    digest = hashlib.sha256(canonical_json_bytes(content)).hexdigest().upper()
    return f"{_PREFIX[artifact_type]}{digest}"


def artifact_from_value(
    artifact_type: SchedulerArtifactType,
    value: SchedulerValue,
) -> LoadedSchedulerArtifact:
    """Create a canonical artifact from an already validated domain value."""

    content = value.to_dict()
    parsed = _parse_value(artifact_type, content)
    if parsed.to_dict() != content:
        raise SchedulerContractError("Generated scheduler artifact is not canonical.")
    return LoadedSchedulerArtifact(
        artifact_type=artifact_type,
        artifact_id=scheduler_identity(artifact_type, parsed.to_dict()),
        value=parsed,
    )


def serialize_scheduler_artifact(artifact: LoadedSchedulerArtifact) -> bytes:
    """Serialize one artifact as deterministic UTF-8 JSON plus newline."""

    expected = scheduler_identity(artifact.artifact_type, artifact.value.to_dict())
    if artifact.artifact_id != expected:
        raise SchedulerContractError("Scheduler artifact identity is stale.")
    import json

    return (
        json.dumps(artifact.to_dict(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("ascii")


def load_scheduler_artifact(
    path: Path,
    *,
    expected_type: SchedulerArtifactType | None = None,
    root: Path | None = None,
) -> LoadedSchedulerArtifact:
    """Load one bounded regular file and validate its exact artifact contract."""

    if path.suffix.casefold() != ".json":
        raise SchedulerContractError("Scheduler artifact must be a JSON file.")
    if path.is_symlink() or is_reparse_point(path) or not path.is_file():
        raise SchedulerContractError("Scheduler artifact must be a regular, unlinked file.")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise SchedulerContractError("Scheduler artifact could not be read.") from exc
    return parse_scheduler_artifact_bytes(
        content,
        expected_type=expected_type,
        root=root,
    )


def parse_scheduler_artifact_bytes(
    content: bytes,
    *,
    expected_type: SchedulerArtifactType | None = None,
    root: Path | None = None,
) -> LoadedSchedulerArtifact:
    """Parse strict JSON, reject unknown fields, and verify content identity."""

    maximum = (
        MAX_MESSAGE_BYTES
        if expected_type is SchedulerArtifactType.MAILBOX_MESSAGE
        else MAX_ARTIFACT_BYTES
    )
    try:
        envelope = parse_json_object_bytes(content, "M6 scheduler artifact", maximum_bytes=maximum)
        only_keys(
            envelope,
            {"schema_version", "artifact_type", "artifact_id", "content"},
            "M6 scheduler artifact",
        )
        if envelope.get("schema_version") != "1.0":
            raise SchedulerContractError("Scheduler schema version is unsupported.")
        artifact_type = enum_value(
            SchedulerArtifactType,
            envelope.get("artifact_type"),
            "artifact_type",
        )
        if expected_type is not None and artifact_type is not expected_type:
            raise SchedulerContractError("Scheduler artifact type is unexpected.")
        if (
            artifact_type is SchedulerArtifactType.MAILBOX_MESSAGE
            and len(content) > MAX_MESSAGE_BYTES
        ):
            raise SchedulerContractError("Mailbox message exceeds 64 KiB.")
        raw_content = object_value(envelope.get("content"), "content")
        value = _parse_value(artifact_type, raw_content)
        expected_id = scheduler_identity(artifact_type, value.to_dict())
        artifact_id = scheduler_id(
            envelope.get("artifact_id"),
            "artifact_id",
            prefix=_PREFIX[artifact_type],
        )
        if artifact_id != expected_id:
            raise SchedulerContractError("Scheduler artifact identity does not match content.")
        result = LoadedSchedulerArtifact(artifact_type, artifact_id, value)
        if artifact_type is SchedulerArtifactType.TASK_GRAPH and root is not None:
            validate_task_graph_inputs(result, root)
        return result
    except SchedulerContractError:
        raise
    except (ContextContractError, ContractError, ValueError) as exc:
        raise SchedulerContractError(str(exc)) from exc


def validate_task_graph_inputs(artifact: LoadedSchedulerArtifact, root: Path) -> None:
    """Revalidate every exact M2/M5 input and cross-contract invariant."""

    if artifact.artifact_type is not SchedulerArtifactType.TASK_GRAPH:
        raise SchedulerContractError("Task Graph validation requires a Task Graph artifact.")
    graph = artifact.value
    assert isinstance(graph, TaskGraph)
    resolved_root = _validated_root(root)
    try:
        registry_path = _verified_path(resolved_root, graph.agent_registry)
        tools_path = _verified_path(resolved_root, graph.tool_registry)
        request_path = _verified_path(resolved_root, graph.orchestration_request)
        registry = load_agent_registry(registry_path)
        tools = load_tool_registry(tools_path)
        validate_agent_tool_references(registry, tools)
        request = load_orchestration_request(request_path)
        worktree = None
        if graph.worktree_plan is not None:
            worktree = load_worktree_plan(_verified_path(resolved_root, graph.worktree_plan))
        AgentOrchestrator().plan(registry, request, worktree_plan=worktree)
    except (OrchestrationContractError, ToolContractError, OSError) as exc:
        raise SchedulerContractError("Task Graph M2 input validation failed.") from exc

    if graph.budget.max_agents > request.budget.max_agents:
        raise SchedulerContractError("Task Graph max_agents exceeds the M2 budget.")
    if graph.budget.max_concurrency > request.budget.max_concurrency:
        raise SchedulerContractError("Task Graph max_concurrency exceeds the M2 budget.")
    if (
        ReasoningEffort(graph.budget.max_reasoning_effort).rank
        > request.budget.max_reasoning_effort.rank
    ):
        raise SchedulerContractError("Task Graph reasoning effort exceeds the M2 budget.")

    contexts: dict[str, ContextBinding] = {}
    for binding in graph.contexts:
        snapshot_path = _verified_path(resolved_root, binding.reference)
        try:
            loaded = load_context_artifact(
                snapshot_path, expected_type=ContextArtifactType.SNAPSHOT
            )
        except (ContextContractError, OSError) as exc:
            raise SchedulerContractError("Task Graph Context Snapshot is invalid.") from exc
        if loaded.artifact_id != binding.artifact_id:
            raise SchedulerContractError("Task Graph Context Snapshot identity drifted.")
        snapshot = loaded.value
        assert isinstance(snapshot, ContextSnapshot)
        if snapshot.candidate != binding.candidate or snapshot.candidate != graph.candidate:
            raise SchedulerContractError("Task Graph Context candidate does not match.")
        if snapshot.sensitivity is not binding.sensitivity:
            raise SchedulerContractError("Task Graph Context sensitivity does not match.")
        contexts[binding.artifact_id] = binding

    requested = set(request.requested_roles)
    roles = {item.role_id: item for item in registry.agents}
    worktree_assignments = (
        {} if worktree is None else {item.role_id: item for item in worktree.assignments}
    )
    tasks = {item.task_id: item for item in graph.tasks}
    for task in graph.tasks:
        role = roles.get(task.role_id)
        if role is None or task.role_id not in requested:
            raise SchedulerContractError("Task role is not authorized by the M2 request.")
        if task.context_snapshot_id not in contexts:
            raise SchedulerContractError("Task references an unknown Context Snapshot.")
        if not set(task.required_tools).issubset(role.tools):
            raise SchedulerContractError("Task requires a tool not granted to its role.")
        if task.kind is TaskKind.REVIEW and not role.independent_reviewer:
            raise SchedulerContractError("Review task requires an independent reviewer role.")
        if task.kind is TaskKind.INTEGRATION and (
            worktree is None or task.role_id != worktree.integrator_role
        ):
            raise SchedulerContractError("Integration task requires the exact integrator role.")
        if task.owned_paths and not role.can_write:
            raise SchedulerContractError("A read-only role cannot own write paths.")
        if task.worktree_assignment is not None:
            assignment = worktree_assignments.get(task.role_id)
            if assignment is None or assignment.worktree != task.worktree_assignment:
                raise SchedulerContractError("Task worktree assignment does not match its plan.")
            if not _paths_within(task.owned_paths, assignment.owned_paths):
                raise SchedulerContractError("Task paths exceed its worktree assignment.")
        for target in task.review_targets:
            target_task = tasks[target]
            if target_task.role_id == task.role_id:
                raise SchedulerContractError("A task cannot review its own role.")


def validate_task_result_reference(
    root: Path,
    graph: TaskGraph,
    message: MailboxMessage,
) -> AgentResult | None:
    """Verify an exact Agent Result wrapper against the Task Graph registry."""

    if message.message_type is not MessageType.TASK_RESULT:
        return None
    payload = message.to_dict()["payload"]
    assert isinstance(payload, dict)
    result_reference = parse_artifact_reference(
        payload.get("agent_result"),
        "payload.agent_result",
    )
    resolved_root = _validated_root(root)
    try:
        registry = load_agent_registry(_verified_path(resolved_root, graph.agent_registry))
        result = load_agent_result(_verified_path(resolved_root, result_reference), registry)
    except (OrchestrationContractError, OSError) as exc:
        raise SchedulerContractError("Wrapped Agent Result is invalid.") from exc
    task = next(item for item in graph.tasks if item.task_id == message.task_id)
    if result.role_id != task.role_id:
        raise SchedulerContractError("Wrapped Agent Result role does not match the task.")
    if payload.get("outcome") == "succeeded" and result.status is not AgentResultStatus.COMPLETED:
        raise SchedulerContractError("Wrapped Agent Result status contradicts the task outcome.")
    evidence = tuple(
        parse_artifact_reference(item, f"payload.evidence_refs[{index}]")
        for index, item in enumerate(
            array_value(
                payload.get("evidence_refs"),
                "payload.evidence_refs",
                maximum=MAX_REFERENCES,
            )
        )
    )
    for reference in evidence:
        _verified_path(resolved_root, reference)
    return result


def verified_reference_size(root: Path, reference: ArtifactReference) -> int:
    """Revalidate one exact referenced artifact and return its current byte size."""

    resolved = _verified_path(_validated_root(root), reference)
    try:
        return resolved.stat().st_size
    except OSError as exc:
        raise SchedulerContractError("Referenced artifact size could not be observed.") from exc


def scheduler_id(value: object, where: str, *, prefix: str | None = None) -> str:
    text = string_value(value, where, maximum=160)
    if not _M6_ID.fullmatch(text) or (prefix is not None and not text.startswith(prefix)):
        raise SchedulerContractError(f"{where} must be a full M6 artifact identity.")
    return text


def task_id(value: object, where: str) -> str:
    text = string_value(value, where, maximum=68)
    if not _TASK_ID.fullmatch(text):
        raise SchedulerContractError(f"{where} must be a valid task identifier.")
    return text


def host_or_worker_id(value: object, where: str) -> str:
    text = string_value(value, where, maximum=68)
    if not (_HOST_ID.fullmatch(text) or _WORKER_ID.fullmatch(text)):
        raise SchedulerContractError(f"{where} must be a host or worker identifier.")
    return text


def strict_host_id(value: object, where: str) -> str:
    """Require one canonical host identity, never a worker or prefix lookalike."""

    try:
        text = string_value(value, where, maximum=68)
    except ContractError as exc:
        raise SchedulerContractError(f"{where} must be a host identifier.") from exc
    if not _HOST_ID.fullmatch(text):
        raise SchedulerContractError(f"{where} must be a host identifier.")
    return text


def strict_reason(value: object, where: str, *, maximum: int = 4000) -> str:
    """Require one canonical path-free, single-line, secret-free reason."""

    try:
        return path_free_text(value, where, maximum=maximum)
    except ContractError as exc:
        raise SchedulerContractError(f"{where} must be canonical reason text.") from exc


def utc_timestamp(value: object, where: str) -> str:
    text = string_value(value, where, maximum=40)
    if not _RFC3339_UTC.fullmatch(text):
        raise SchedulerContractError(f"{where} must be RFC 3339 UTC.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchedulerContractError(f"{where} is invalid.") from exc
    if parsed.utcoffset() != timedelta(0):
        raise SchedulerContractError(f"{where} must be UTC.")
    return text


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise SchedulerContractError("Scheduler clock must be timezone-aware UTC.")
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def derive_idempotency_key(
    graph_id: str,
    task_id_value: str,
    attempt: int,
    fence: int,
    candidate: object,
    context_snapshot_id: str,
    effect_digest: str,
) -> str:
    """Derive a stable full idempotency key from the exact attempt identity."""

    content = {
        "graph_id": graph_id,
        "task_id": task_id_value,
        "attempt": attempt,
        "fence": fence,
        "candidate": candidate,
        "context_snapshot_id": context_snapshot_id,
        "effect_digest": effect_digest,
    }
    return "IDEM-" + hashlib.sha256(canonical_json_bytes(content)).hexdigest().upper()


def event_digest(artifact: LoadedSchedulerArtifact) -> str:
    """Return the event envelope digest used by the next chain link."""

    if artifact.artifact_type is not SchedulerArtifactType.SCHEDULER_EVENT:
        raise SchedulerContractError("Event digest requires a Scheduler Event.")
    return hashlib.sha256(canonical_json_bytes(artifact.to_dict())).hexdigest().upper()


def _parse_value(
    artifact_type: SchedulerArtifactType,
    value: dict[str, object],
) -> SchedulerValue:
    if artifact_type is SchedulerArtifactType.TASK_GRAPH:
        return _parse_task_graph(value)
    if artifact_type is SchedulerArtifactType.SCHEDULER_STATE:
        return _parse_scheduler_state(value)
    if artifact_type is SchedulerArtifactType.LEASE:
        return _parse_lease(value)
    if artifact_type is SchedulerArtifactType.MAILBOX_MESSAGE:
        return _parse_message(value)
    if artifact_type is SchedulerArtifactType.SCHEDULER_EVENT:
        return _parse_event(value)
    if artifact_type is SchedulerArtifactType.BUDGET_LEDGER:
        return _parse_budget_ledger(value)
    return _parse_worktree_lease(value)


def _parse_task_graph(value: dict[str, object]) -> TaskGraph:
    where = "Task Graph content"
    only_keys(
        value,
        {
            "candidate",
            "agent_registry",
            "tool_registry",
            "orchestration_request",
            "worktree_plan",
            "contexts",
            "budget",
            "tasks",
        },
        where,
    )
    candidate = parse_candidate_identity(value.get("candidate"), "candidate")
    worktree_raw = value.get("worktree_plan")
    worktree = (
        None if worktree_raw is None else parse_artifact_reference(worktree_raw, "worktree_plan")
    )
    contexts = tuple(
        _parse_context_binding(item, f"contexts[{index}]")
        for index, item in enumerate(array_value(value.get("contexts"), "contexts", maximum=64))
    )
    if not contexts or contexts != tuple(sorted(contexts, key=lambda item: item.artifact_id)):
        raise SchedulerContractError("contexts must be non-empty and sorted by artifact_id.")
    if len({item.artifact_id for item in contexts}) != len(contexts):
        raise SchedulerContractError("contexts must contain unique Snapshot identities.")
    tasks = tuple(
        _parse_task(item, f"tasks[{index}]")
        for index, item in enumerate(array_value(value.get("tasks"), "tasks", maximum=MAX_TASKS))
    )
    if not tasks or tasks != tuple(sorted(tasks, key=lambda item: item.task_id)):
        raise SchedulerContractError("tasks must be non-empty and sorted by task_id.")
    _validate_dag(tasks)
    _validate_path_ownership(tasks)
    return TaskGraph(
        candidate=candidate,
        agent_registry=parse_artifact_reference(value.get("agent_registry"), "agent_registry"),
        tool_registry=parse_artifact_reference(value.get("tool_registry"), "tool_registry"),
        orchestration_request=parse_artifact_reference(
            value.get("orchestration_request"), "orchestration_request"
        ),
        worktree_plan=worktree,
        contexts=contexts,
        budget=_parse_budget(value.get("budget"), "budget"),
        tasks=tasks,
    )


def _parse_context_binding(value: object, where: str) -> ContextBinding:
    item = object_value(value, where)
    only_keys(item, {"artifact_id", "path", "sha256", "sensitivity", "candidate"}, where)
    artifact_id = string_value(item.get("artifact_id"), f"{where}.artifact_id", maximum=128)
    if not _CONTEXT_ID.fullmatch(artifact_id):
        raise SchedulerContractError(f"{where}.artifact_id is not a Snapshot identity.")
    sensitivity = enum_value(Sensitivity, item.get("sensitivity"), f"{where}.sensitivity")
    if sensitivity is Sensitivity.SECRET_OR_PROHIBITED:
        raise SchedulerContractError(f"{where} cannot adopt prohibited sensitivity.")
    return ContextBinding(
        artifact_id=artifact_id,
        reference=ArtifactReference(
            safe_relative_path(item.get("path"), f"{where}.path"),
            sha256(item.get("sha256"), f"{where}.sha256"),
        ),
        sensitivity=sensitivity,
        candidate=parse_candidate_identity(item.get("candidate"), f"{where}.candidate"),
    )


def _parse_budget(value: object, where: str) -> SchedulerBudget:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "max_agents",
            "max_concurrency",
            "max_reasoning_effort",
            "max_dispatches",
            "max_retries",
            "max_wall_time_seconds",
            "max_tool_calls",
            "max_context_bytes_per_dispatch",
            "max_context_bytes_total",
            "max_solver_calls",
            "max_solver_steps",
            "cost",
        },
        where,
    )
    max_agents = integer_value(item.get("max_agents"), f"{where}.max_agents", minimum=1, maximum=16)
    max_concurrency = integer_value(
        item.get("max_concurrency"), f"{where}.max_concurrency", minimum=1, maximum=16
    )
    if max_concurrency > max_agents:
        raise SchedulerContractError(f"{where}.max_concurrency exceeds max_agents.")
    reasoning = string_value(
        item.get("max_reasoning_effort"), f"{where}.max_reasoning_effort", maximum=6
    )
    if reasoning not in {"low", "medium", "high"}:
        raise SchedulerContractError(f"{where}.max_reasoning_effort is unsupported.")
    cost = object_value(item.get("cost"), f"{where}.cost")
    only_keys(cost, {"status", "currency", "max_microunits"}, f"{where}.cost")
    status = string_value(cost.get("status"), f"{where}.cost.status", maximum=20)
    if status not in {"available", "not_available"}:
        raise SchedulerContractError(f"{where}.cost.status is unsupported.")
    currency_raw = cost.get("currency")
    currency = (
        None
        if currency_raw is None
        else string_value(currency_raw, f"{where}.cost.currency", maximum=3)
    )
    if currency is not None and not _CURRENCY.fullmatch(currency):
        raise SchedulerContractError(f"{where}.cost.currency must be uppercase ISO-style text.")
    amount_raw = cost.get("max_microunits")
    amount = (
        None
        if amount_raw is None
        else integer_value(
            amount_raw,
            f"{where}.cost.max_microunits",
            minimum=0,
            maximum=1_000_000_000_000_000,
        )
    )
    if status == "available" and (currency is None or amount is None):
        raise SchedulerContractError(f"{where}.cost available requires currency and limit.")
    if status == "not_available" and (currency is not None or amount is not None):
        raise SchedulerContractError(f"{where}.cost unavailable must not claim values.")
    return SchedulerBudget(
        max_agents=max_agents,
        max_concurrency=max_concurrency,
        max_reasoning_effort=reasoning,
        max_dispatches=integer_value(
            item.get("max_dispatches"), f"{where}.max_dispatches", minimum=1, maximum=4096
        ),
        max_retries=integer_value(
            item.get("max_retries"), f"{where}.max_retries", minimum=0, maximum=1024
        ),
        max_wall_time_seconds=integer_value(
            item.get("max_wall_time_seconds"),
            f"{where}.max_wall_time_seconds",
            minimum=1,
            maximum=604800,
        ),
        max_tool_calls=integer_value(
            item.get("max_tool_calls"), f"{where}.max_tool_calls", minimum=0, maximum=100000
        ),
        max_context_bytes_per_dispatch=integer_value(
            item.get("max_context_bytes_per_dispatch"),
            f"{where}.max_context_bytes_per_dispatch",
            minimum=1024,
            maximum=8388608,
        ),
        max_context_bytes_total=integer_value(
            item.get("max_context_bytes_total"),
            f"{where}.max_context_bytes_total",
            minimum=1024,
            maximum=34359738368,
        ),
        max_solver_calls=integer_value(
            item.get("max_solver_calls"), f"{where}.max_solver_calls", minimum=0, maximum=1024
        ),
        max_solver_steps=integer_value(
            item.get("max_solver_steps"), f"{where}.max_solver_steps", minimum=0, maximum=2147483647
        ),
        cost_status=status,
        currency=currency,
        max_microunits=amount,
    )


def _parse_task(value: object, where: str) -> SchedulerTask:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "task_id",
            "kind",
            "dependencies",
            "role_id",
            "context_snapshot_id",
            "required_tools",
            "required_capabilities",
            "owned_paths",
            "worktree_assignment",
            "effect_kind",
            "approval_stops",
            "evidence_predicate",
            "review_targets",
            "terminal_predicate",
            "wave",
            "max_attempts",
        },
        where,
    )
    role = string_value(item.get("role_id"), f"{where}.role_id", maximum=64)
    if not _ROLE_ID.fullmatch(role):
        raise SchedulerContractError(f"{where}.role_id is invalid.")
    context_id = string_value(
        item.get("context_snapshot_id"), f"{where}.context_snapshot_id", maximum=128
    )
    if not _CONTEXT_ID.fullmatch(context_id):
        raise SchedulerContractError(f"{where}.context_snapshot_id is invalid.")
    dependencies = _sorted_task_ids(item.get("dependencies"), f"{where}.dependencies")
    review_targets = _sorted_task_ids(item.get("review_targets"), f"{where}.review_targets")
    approval_stops = string_tuple(item.get("approval_stops"), f"{where}.approval_stops", maximum=2)
    if approval_stops != tuple(sorted(approval_stops)) or not set(approval_stops).issubset(
        {"owner", "technical_sandbox"}
    ):
        raise SchedulerContractError(f"{where}.approval_stops must be sorted supported values.")
    worktree_raw = item.get("worktree_assignment")
    worktree = (
        None
        if worktree_raw is None
        else safe_relative_path(worktree_raw, f"{where}.worktree_assignment")
    )
    evidence_predicate = _sorted_path_free_text(
        item.get("evidence_predicate"), f"{where}.evidence_predicate"
    )
    if evidence_predicate not in {(), ("evidence-reference-present",)}:
        raise SchedulerContractError(f"{where}.evidence_predicate is unsupported.")
    terminal_predicate = _sorted_path_free_text(
        item.get("terminal_predicate"), f"{where}.terminal_predicate", minimum=1
    )
    if terminal_predicate != ("agent-result-valid",):
        raise SchedulerContractError(f"{where}.terminal_predicate is unsupported.")
    return SchedulerTask(
        task_id=task_id(item.get("task_id"), f"{where}.task_id"),
        kind=enum_value(TaskKind, item.get("kind"), f"{where}.kind"),
        dependencies=dependencies,
        role_id=role,
        context_snapshot_id=context_id,
        required_tools=_sorted_strings(item.get("required_tools"), f"{where}.required_tools"),
        required_capabilities=_sorted_strings(
            item.get("required_capabilities"), f"{where}.required_capabilities"
        ),
        owned_paths=_sorted_paths(item.get("owned_paths"), f"{where}.owned_paths"),
        worktree_assignment=worktree,
        effect_kind=enum_value(EffectKind, item.get("effect_kind"), f"{where}.effect_kind"),
        approval_stops=approval_stops,
        evidence_predicate=evidence_predicate,
        review_targets=review_targets,
        terminal_predicate=terminal_predicate,
        wave=integer_value(item.get("wave"), f"{where}.wave", minimum=0, maximum=4096),
        max_attempts=integer_value(
            item.get("max_attempts"), f"{where}.max_attempts", minimum=1, maximum=3
        ),
    )


def _validate_dag(tasks: tuple[SchedulerTask, ...]) -> None:
    by_id = {item.task_id: item for item in tasks}
    if len(by_id) != len(tasks):
        raise SchedulerContractError("Task IDs must be unique.")
    for item in tasks:
        if item.task_id in item.dependencies or item.task_id in item.review_targets:
            raise SchedulerContractError("A task cannot depend on or review itself.")
        if not set(item.dependencies).issubset(by_id) or not set(item.review_targets).issubset(
            by_id
        ):
            raise SchedulerContractError("Task references an unknown task.")
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in temporary:
            raise SchedulerContractError("Task Graph contains a dependency cycle.")
        if identifier in permanent:
            return
        temporary.add(identifier)
        for dependency in by_id[identifier].dependencies:
            visit(dependency)
        temporary.remove(identifier)
        permanent.add(identifier)

    for identifier in sorted(by_id):
        visit(identifier)


def topological_ranks(graph: TaskGraph) -> dict[str, int]:
    """Return deterministic longest-dependency ranks for ready ordering."""

    tasks = {item.task_id: item for item in graph.tasks}
    result: dict[str, int] = {}

    def rank(identifier: str) -> int:
        existing = result.get(identifier)
        if existing is not None:
            return existing
        dependencies = tasks[identifier].dependencies
        value = 0 if not dependencies else 1 + max(rank(item) for item in dependencies)
        result[identifier] = value
        return value

    for identifier in sorted(tasks):
        rank(identifier)
    return result


def _validate_path_ownership(tasks: tuple[SchedulerTask, ...]) -> None:
    owners: list[tuple[str, str]] = []
    for task in tasks:
        for path in task.owned_paths:
            for existing_path, existing_task in owners:
                if task.task_id != existing_task and _paths_overlap(path, existing_path):
                    raise SchedulerContractError("Task owned paths overlap.")
            owners.append((path, task.task_id))


def _parse_scheduler_state(value: dict[str, object]) -> SchedulerState:
    where = "Scheduler State content"
    only_keys(
        value,
        {
            "graph_id",
            "candidate",
            "tasks",
            "ready_order",
            "lease_ids",
            "message_ids",
            "budget_ledger_id",
            "worktree_lease_ids",
            "event_sequence",
            "event_head_sha256",
        },
        where,
    )
    tasks = tuple(
        _parse_projection(item, f"tasks[{index}]")
        for index, item in enumerate(array_value(value.get("tasks"), "tasks", maximum=MAX_TASKS))
    )
    if tasks != tuple(sorted(tasks, key=lambda item: item.task_id)) or len(
        {item.task_id for item in tasks}
    ) != len(tasks):
        raise SchedulerContractError("Scheduler State tasks must be sorted and unique.")
    ready = _sorted_task_ids(value.get("ready_order"), "ready_order")
    if not set(ready).issubset({item.task_id for item in tasks}):
        raise SchedulerContractError("ready_order references an unknown task.")
    sequence = integer_value(
        value.get("event_sequence"), "event_sequence", minimum=1, maximum=2_147_483_647
    )
    return SchedulerState(
        graph_id=scheduler_id(
            value.get("graph_id"), "graph_id", prefix=_PREFIX[SchedulerArtifactType.TASK_GRAPH]
        ),
        candidate=parse_candidate_identity(value.get("candidate"), "candidate"),
        tasks=tasks,
        ready_order=ready,
        lease_ids=_sorted_scheduler_ids(
            value.get("lease_ids"), "lease_ids", _PREFIX[SchedulerArtifactType.LEASE]
        ),
        message_ids=_sorted_scheduler_ids(
            value.get("message_ids"), "message_ids", _PREFIX[SchedulerArtifactType.MAILBOX_MESSAGE]
        ),
        budget_ledger_id=scheduler_id(
            value.get("budget_ledger_id"),
            "budget_ledger_id",
            prefix=_PREFIX[SchedulerArtifactType.BUDGET_LEDGER],
        ),
        worktree_lease_ids=_sorted_scheduler_ids(
            value.get("worktree_lease_ids"),
            "worktree_lease_ids",
            _PREFIX[SchedulerArtifactType.WORKTREE_LEASE],
        ),
        event_sequence=sequence,
        event_head_sha256=sha256(value.get("event_head_sha256"), "event_head_sha256"),
    )


def _parse_projection(value: object, where: str) -> TaskProjection:
    item = object_value(value, where)
    only_keys(
        item,
        {"task_id", "state", "dispatch_phase", "outcome", "attempt", "fence", "blockers"},
        where,
    )
    blockers = tuple(
        _parse_blocker(blocker, f"{where}.blockers[{index}]")
        for index, blocker in enumerate(
            array_value(item.get("blockers"), f"{where}.blockers", maximum=64)
        )
    )
    if blockers != tuple(sorted(blockers, key=lambda blocker: (blocker.code, blocker.references))):
        raise SchedulerContractError(f"{where}.blockers must be sorted.")
    return TaskProjection(
        task_id=task_id(item.get("task_id"), f"{where}.task_id"),
        state=enum_value(TaskState, item.get("state"), f"{where}.state"),
        dispatch_phase=enum_value(
            DispatchPhase, item.get("dispatch_phase"), f"{where}.dispatch_phase"
        ),
        outcome=enum_value(TaskOutcome, item.get("outcome"), f"{where}.outcome"),
        attempt=integer_value(item.get("attempt"), f"{where}.attempt", minimum=0, maximum=3),
        fence=integer_value(item.get("fence"), f"{where}.fence", minimum=0, maximum=2_147_483_647),
        blockers=blockers,
    )


def _parse_blocker(value: object, where: str) -> Blocker:
    item = object_value(value, where)
    only_keys(item, {"code", "references"}, where)
    return Blocker(
        code=string_value(item.get("code"), f"{where}.code", maximum=100),
        references=_sorted_path_free_text(item.get("references"), f"{where}.references"),
    )


def _parse_lease(value: dict[str, object]) -> Lease:
    where = "Lease content"
    only_keys(
        value,
        {
            "graph_id",
            "task_id",
            "candidate",
            "context_snapshot_id",
            "attempt",
            "owner_id",
            "fence",
            "idempotency_key",
            "acquired_at",
            "heartbeat_at",
            "expires_at",
            "ttl_seconds",
            "heartbeat_interval_seconds",
            "status",
            "release_outcome",
        },
        where,
    )
    ttl = integer_value(value.get("ttl_seconds"), "ttl_seconds", minimum=30, maximum=3600)
    heartbeat_interval = integer_value(
        value.get("heartbeat_interval_seconds"),
        "heartbeat_interval_seconds",
        minimum=5,
        maximum=300,
    )
    acquired = utc_timestamp(value.get("acquired_at"), "acquired_at")
    heartbeat = utc_timestamp(value.get("heartbeat_at"), "heartbeat_at")
    expires = utc_timestamp(value.get("expires_at"), "expires_at")
    idem = string_value(value.get("idempotency_key"), "idempotency_key", maximum=69)
    if not _IDEMPOTENCY.fullmatch(idem):
        raise SchedulerContractError("Lease idempotency key is invalid.")
    return Lease(
        graph_id=scheduler_id(
            value.get("graph_id"), "graph_id", prefix=_PREFIX[SchedulerArtifactType.TASK_GRAPH]
        ),
        task_id=task_id(value.get("task_id"), "task_id"),
        candidate=parse_candidate_identity(value.get("candidate"), "candidate"),
        context_snapshot_id=_snapshot_id(value.get("context_snapshot_id"), "context_snapshot_id"),
        attempt=integer_value(value.get("attempt"), "attempt", minimum=1, maximum=3),
        owner_id=host_or_worker_id(value.get("owner_id"), "owner_id"),
        fence=integer_value(value.get("fence"), "fence", minimum=1, maximum=2_147_483_647),
        idempotency_key=idem,
        acquired_at=acquired,
        heartbeat_at=heartbeat,
        expires_at=expires,
        ttl_seconds=ttl,
        heartbeat_interval_seconds=heartbeat_interval,
        status=enum_value(LeaseStatus, value.get("status"), "status"),
        release_outcome=enum_value(TaskOutcome, value.get("release_outcome"), "release_outcome"),
    )


def _parse_message(value: dict[str, object]) -> MailboxMessage:
    where = "Mailbox Message content"
    only_keys(
        value,
        {
            "message_type",
            "direction",
            "sender",
            "recipient",
            "graph_id",
            "task_id",
            "candidate",
            "context_snapshot_id",
            "attempt",
            "lease_id",
            "fence",
            "idempotency_key",
            "sensitivity",
            "provenance",
            "causal_parent_message_ids",
            "recorded_at",
            "payload",
        },
        where,
    )
    message_type = enum_value(MessageType, value.get("message_type"), "message_type")
    direction = enum_value(MessageDirection, value.get("direction"), "direction")
    _validate_direction(message_type, direction)
    sensitivity = enum_value(Sensitivity, value.get("sensitivity"), "sensitivity")
    if sensitivity is Sensitivity.SECRET_OR_PROHIBITED:
        raise SchedulerContractError("Mailbox message cannot adopt prohibited sensitivity.")
    parsed_task = None if value.get("task_id") is None else task_id(value.get("task_id"), "task_id")
    context = (
        None
        if value.get("context_snapshot_id") is None
        else _snapshot_id(value.get("context_snapshot_id"), "context_snapshot_id")
    )
    attempt = (
        None
        if value.get("attempt") is None
        else integer_value(value.get("attempt"), "attempt", minimum=1, maximum=3)
    )
    lease = (
        None
        if value.get("lease_id") is None
        else scheduler_id(
            value.get("lease_id"), "lease_id", prefix=_PREFIX[SchedulerArtifactType.LEASE]
        )
    )
    fence = (
        None
        if value.get("fence") is None
        else integer_value(value.get("fence"), "fence", minimum=1, maximum=2_147_483_647)
    )
    idem_raw = value.get("idempotency_key")
    idem = None if idem_raw is None else string_value(idem_raw, "idempotency_key", maximum=69)
    if idem is not None and not _IDEMPOTENCY.fullmatch(idem):
        raise SchedulerContractError("Message idempotency key is invalid.")
    if message_type is not MessageType.CAPABILITY_OBSERVATION and None in {
        parsed_task,
        context,
        attempt,
        lease,
        fence,
        idem,
    }:
        raise SchedulerContractError("Task-bound message identity is incomplete.")
    if message_type is MessageType.CAPABILITY_OBSERVATION and any(
        item is not None
        for item in (parsed_task, context, attempt, lease, fence, idem)
    ):
        raise SchedulerContractError(
            "Capability observation task identity fields must all be null."
        )
    provenance = tuple(
        parse_artifact_reference(item, f"provenance[{index}]")
        for index, item in enumerate(
            array_value(value.get("provenance"), "provenance", maximum=MAX_REFERENCES)
        )
    )
    parents = _sorted_scheduler_ids(
        value.get("causal_parent_message_ids"),
        "causal_parent_message_ids",
        _PREFIX[SchedulerArtifactType.MAILBOX_MESSAGE],
    )
    payload = _parse_message_payload(message_type, value.get("payload"))
    sender = host_or_worker_id(value.get("sender"), "sender")
    recipient = host_or_worker_id(value.get("recipient"), "recipient")
    if message_type is MessageType.APPROVAL_DECISION:
        approval_type = payload["approval_type"]
        assert isinstance(approval_type, str)
        expected_sender, expected_authority = _APPROVAL_ACTORS[approval_type]
        if sender != expected_sender or payload.get("authority") != expected_authority:
            raise SchedulerContractError(
                "Approval sender and authority do not match the approval type."
            )
    return MailboxMessage(
        message_type=message_type,
        direction=direction,
        sender=sender,
        recipient=recipient,
        graph_id=scheduler_id(
            value.get("graph_id"), "graph_id", prefix=_PREFIX[SchedulerArtifactType.TASK_GRAPH]
        ),
        task_id=parsed_task,
        candidate=parse_candidate_identity(value.get("candidate"), "candidate"),
        context_snapshot_id=context,
        attempt=attempt,
        lease_id=lease,
        fence=fence,
        idempotency_key=idem,
        sensitivity=sensitivity,
        provenance=provenance,
        causal_parent_message_ids=parents,
        recorded_at=utc_timestamp(value.get("recorded_at"), "recorded_at"),
        payload=payload,
    )


def _parse_message_payload(message_type: MessageType, value: object) -> dict[str, object]:
    item = object_value(value, "payload")
    if message_type is MessageType.DISPATCH_INTENT:
        only_keys(
            item,
            {
                "effect_digest",
                "lease_ttl_seconds",
                "heartbeat_interval_seconds",
                "required_capabilities",
                "required_tools",
                "context_bytes",
                "budget_reservation",
            },
            "payload",
        )
        ttl = integer_value(
            item.get("lease_ttl_seconds"), "payload.lease_ttl_seconds", minimum=30, maximum=3600
        )
        heartbeat = integer_value(
            item.get("heartbeat_interval_seconds"),
            "payload.heartbeat_interval_seconds",
            minimum=5,
            maximum=300,
        )
        return {
            "effect_digest": sha256(item.get("effect_digest"), "payload.effect_digest"),
            "lease_ttl_seconds": ttl,
            "heartbeat_interval_seconds": heartbeat,
            "required_capabilities": list(
                _sorted_strings(item.get("required_capabilities"), "payload.required_capabilities")
            ),
            "required_tools": list(
                _sorted_strings(item.get("required_tools"), "payload.required_tools")
            ),
            "context_bytes": integer_value(
                item.get("context_bytes"),
                "payload.context_bytes",
                minimum=0,
                maximum=MAX_ARTIFACT_BYTES,
            ),
            "budget_reservation": _exact_resource_counts(
                item.get("budget_reservation"),
                "payload.budget_reservation",
                {"context_bytes", "microunits", "solver_calls", "solver_steps", "tool_calls"},
            ),
        }
    if message_type is MessageType.DISPATCH_ACKNOWLEDGEMENT:
        only_keys(item, {"accepted", "effect_observed", "note"}, "payload")
        return {
            "accepted": boolean_value(item.get("accepted"), "payload.accepted"),
            "effect_observed": _choice(
                item.get("effect_observed"),
                "payload.effect_observed",
                {"none", "possible", "confirmed"},
            ),
            "note": _optional_path_free(item.get("note"), "payload.note"),
        }
    if message_type is MessageType.HEARTBEAT:
        only_keys(item, {"progress"}, "payload")
        return {"progress": path_free_text(item.get("progress"), "payload.progress", maximum=4000)}
    if message_type is MessageType.TASK_RESULT:
        only_keys(
            item,
            {"agent_result", "outcome", "effect_observed", "evidence_refs", "budget_usage"},
            "payload",
        )
        outcome = _choice(
            item.get("outcome"), "payload.outcome", {"succeeded", "failed", "unknown"}
        )
        return {
            "agent_result": parse_artifact_reference(
                item.get("agent_result"), "payload.agent_result"
            ).to_dict(),
            "outcome": outcome,
            "effect_observed": _choice(
                item.get("effect_observed"),
                "payload.effect_observed",
                {"none", "confirmed", "ambiguous"},
            ),
            "evidence_refs": [
                reference.to_dict()
                for reference in _artifact_references(
                    item.get("evidence_refs"), "payload.evidence_refs"
                )
            ],
            "budget_usage": _exact_resource_counts(
                item.get("budget_usage"),
                "payload.budget_usage",
                {"microunits", "solver_calls", "solver_steps", "tool_calls"},
            ),
        }
    if message_type is MessageType.CANCEL_REQUEST:
        only_keys(item, {"reason"}, "payload")
        return {"reason": path_free_text(item.get("reason"), "payload.reason", maximum=4000)}
    if message_type is MessageType.CANCEL_ACKNOWLEDGEMENT:
        only_keys(item, {"cancelled", "effect_observed"}, "payload")
        return {
            "cancelled": boolean_value(item.get("cancelled"), "payload.cancelled"),
            "effect_observed": _choice(
                item.get("effect_observed"),
                "payload.effect_observed",
                {"none", "confirmed", "ambiguous"},
            ),
        }
    if message_type is MessageType.WORKTREE_REQUEST:
        only_keys(item, {"worktree", "owned_paths"}, "payload")
        return {
            "worktree": safe_relative_path(item.get("worktree"), "payload.worktree"),
            "owned_paths": list(_sorted_paths(item.get("owned_paths"), "payload.owned_paths")),
        }
    if message_type is MessageType.WORKTREE_OBSERVATION:
        only_keys(item, {"worktree", "observed_digest", "state"}, "payload")
        digest = (
            None
            if item.get("observed_digest") is None
            else sha256(item.get("observed_digest"), "payload.observed_digest")
        )
        return {
            "worktree": safe_relative_path(item.get("worktree"), "payload.worktree"),
            "observed_digest": digest,
            "state": _choice(
                item.get("state"),
                "payload.state",
                {"created", "unchanged", "integrated", "ambiguous"},
            ),
        }
    if message_type is MessageType.APPROVAL_DECISION:
        only_keys(
            item,
            {
                "approval_id",
                "approval_type",
                "decision",
                "transition",
                "effect_digest",
                "approved_at",
                "expires_at",
                "authority",
                "supersedes_approval_id",
            },
            "payload",
        )
        approval_id = string_value(item.get("approval_id"), "payload.approval_id", maximum=100)
        if not _APPROVAL_ID.fullmatch(approval_id):
            raise SchedulerContractError("payload.approval_id is invalid.")
        supersedes_raw = item.get("supersedes_approval_id")
        supersedes = (
            None
            if supersedes_raw is None
            else string_value(supersedes_raw, "payload.supersedes_approval_id", maximum=100)
        )
        if supersedes is not None and not _APPROVAL_ID.fullmatch(supersedes):
            raise SchedulerContractError("payload.supersedes_approval_id is invalid.")
        approved = utc_timestamp(item.get("approved_at"), "payload.approved_at")
        expires = utc_timestamp(item.get("expires_at"), "payload.expires_at")
        return {
            "approval_id": approval_id,
            "approval_type": _choice(
                item.get("approval_type"), "payload.approval_type", {"owner", "technical_sandbox"}
            ),
            "decision": _choice(item.get("decision"), "payload.decision", {"approved", "rejected"}),
            "transition": path_free_text(
                item.get("transition"), "payload.transition", maximum=100
            ),
            "effect_digest": sha256(item.get("effect_digest"), "payload.effect_digest"),
            "approved_at": approved,
            "expires_at": expires,
            "authority": path_free_text(item.get("authority"), "payload.authority", maximum=200),
            "supersedes_approval_id": supersedes,
        }
    only_keys(item, {"capabilities"}, "payload")
    return {"capabilities": list(_sorted_strings(item.get("capabilities"), "payload.capabilities"))}


def _validate_direction(message_type: MessageType, direction: MessageDirection) -> None:
    expected = {
        MessageType.DISPATCH_INTENT: MessageDirection.SCHEDULER_TO_HOST,
        MessageType.CANCEL_REQUEST: MessageDirection.SCHEDULER_TO_HOST,
        MessageType.WORKTREE_REQUEST: MessageDirection.SCHEDULER_TO_HOST,
        MessageType.APPROVAL_DECISION: MessageDirection.OWNER_TO_SCHEDULER,
    }
    required = expected.get(message_type, MessageDirection.HOST_TO_SCHEDULER)
    if direction is not required:
        raise SchedulerContractError("Mailbox message direction does not match its type.")


def _parse_event(value: dict[str, object]) -> SchedulerEvent:
    where = "Scheduler Event content"
    only_keys(
        value,
        {
            "sequence",
            "previous_event_sha256",
            "actor",
            "cause",
            "graph_id",
            "task_id",
            "candidate",
            "context_snapshot_id",
            "before_state",
            "after_state",
            "lease_id",
            "message_id",
            "result_id",
            "approval_id",
            "budget_deltas",
            "task_projection",
            "reason",
            "recorded_at",
        },
        where,
    )
    sequence = integer_value(value.get("sequence"), "sequence", minimum=1, maximum=2_147_483_647)
    previous = sha256(value.get("previous_event_sha256"), "previous_event_sha256")
    if sequence == 1 and previous != ZERO_SHA256:
        raise SchedulerContractError("First Scheduler Event must use the zero chain root.")
    deltas_raw = object_value(value.get("budget_deltas"), "budget_deltas")
    allowed_deltas = {
        "concurrency",
        "dispatches",
        "retries",
        "context_bytes",
        "tool_calls",
        "solver_calls",
        "solver_steps",
        "microunits",
        "wall_time_seconds",
    }
    if not set(deltas_raw).issubset(allowed_deltas):
        raise SchedulerContractError("budget_deltas contains an unsupported key.")
    deltas = {
        key: _signed_integer(item, f"budget_deltas.{key}")
        for key, item in sorted(deltas_raw.items())
    }
    parsed_task_id = (
        None if value.get("task_id") is None else task_id(value.get("task_id"), "task_id")
    )
    projection = (
        None
        if value.get("task_projection") is None
        else _parse_projection(value.get("task_projection"), "task_projection")
    )
    after_state = _optional_choice(
        value.get("after_state"), "after_state", {item.value for item in TaskState}
    )
    if projection is not None and (
        parsed_task_id != projection.task_id or after_state != projection.state.value
    ):
        raise SchedulerContractError("Scheduler Event task projection does not match its state.")
    if parsed_task_id is not None and projection is None:
        raise SchedulerContractError("Task-bound Scheduler Event requires a task projection.")
    if parsed_task_id is None and (projection is not None or after_state is not None):
        raise SchedulerContractError(
            "Graph-wide Scheduler Event cannot contain a task state projection."
        )
    return SchedulerEvent(
        sequence=sequence,
        previous_event_sha256=previous,
        actor=path_free_text(value.get("actor"), "actor", maximum=100),
        cause=_choice(value.get("cause"), "cause", set(EVENT_CAUSES)),
        graph_id=scheduler_id(
            value.get("graph_id"), "graph_id", prefix=_PREFIX[SchedulerArtifactType.TASK_GRAPH]
        ),
        task_id=parsed_task_id,
        candidate=parse_candidate_identity(value.get("candidate"), "candidate"),
        context_snapshot_id=None
        if value.get("context_snapshot_id") is None
        else _snapshot_id(value.get("context_snapshot_id"), "context_snapshot_id"),
        before_state=_optional_choice(
            value.get("before_state"), "before_state", {item.value for item in TaskState}
        ),
        after_state=after_state,
        lease_id=_optional_scheduler_id(
            value.get("lease_id"), "lease_id", _PREFIX[SchedulerArtifactType.LEASE]
        ),
        message_id=_optional_scheduler_id(
            value.get("message_id"), "message_id", _PREFIX[SchedulerArtifactType.MAILBOX_MESSAGE]
        ),
        result_id=_optional_scheduler_id(
            value.get("result_id"), "result_id", _PREFIX[SchedulerArtifactType.MAILBOX_MESSAGE]
        ),
        approval_id=_optional_approval_id(value.get("approval_id"), "approval_id"),
        budget_deltas=deltas,
        task_projection=projection,
        reason=_optional_path_free(value.get("reason"), "reason"),
        recorded_at=utc_timestamp(value.get("recorded_at"), "recorded_at"),
    )


def _parse_budget_ledger(value: dict[str, object]) -> BudgetLedger:
    where = "Budget Ledger content"
    only_keys(
        value,
        {
            "graph_id",
            "limits",
            "reserved",
            "used",
            "availability",
            "blocker_codes",
            "event_sequence",
        },
        where,
    )
    allowed = {
        "concurrency",
        "dispatches",
        "retries",
        "context_bytes",
        "tool_calls",
        "solver_calls",
        "solver_steps",
        "microunits",
        "wall_time_seconds",
    }
    reserved = _exact_resource_counts(value.get("reserved"), "reserved", allowed)
    used = _exact_resource_counts(value.get("used"), "used", allowed)
    availability_raw = object_value(value.get("availability"), "availability")
    if not set(availability_raw).issubset(allowed):
        raise SchedulerContractError("availability contains an unsupported key.")
    if set(availability_raw) != allowed:
        raise SchedulerContractError("availability must contain every required resource.")
    availability = {
        key: _choice(item, f"availability.{key}", {"available", "not_available"})
        for key, item in sorted(availability_raw.items())
    }
    return BudgetLedger(
        graph_id=scheduler_id(
            value.get("graph_id"), "graph_id", prefix=_PREFIX[SchedulerArtifactType.TASK_GRAPH]
        ),
        limits=_parse_budget(value.get("limits"), "limits"),
        reserved=reserved,
        used=used,
        availability=availability,
        blocker_codes=_sorted_path_free_text(value.get("blocker_codes"), "blocker_codes"),
        event_sequence=integer_value(
            value.get("event_sequence"), "event_sequence", minimum=1, maximum=2_147_483_647
        ),
    )


def _parse_worktree_lease(value: dict[str, object]) -> WorktreeLease:
    where = "Worktree Lease content"
    only_keys(
        value,
        {
            "graph_id",
            "task_id",
            "worktree_plan",
            "base_commit",
            "worktree",
            "owner_id",
            "owned_paths",
            "fence",
            "observed_digest",
            "status",
            "integration_state",
            "ambiguous",
            "recovery_guidance",
        },
        where,
    )
    base_commit = string_value(value.get("base_commit"), "base_commit", maximum=40)
    if not re.fullmatch(r"[0-9a-f]{40}", base_commit):
        raise SchedulerContractError("base_commit must be a lowercase full commit.")
    digest = (
        None
        if value.get("observed_digest") is None
        else sha256(value.get("observed_digest"), "observed_digest")
    )
    return WorktreeLease(
        graph_id=scheduler_id(
            value.get("graph_id"), "graph_id", prefix=_PREFIX[SchedulerArtifactType.TASK_GRAPH]
        ),
        task_id=task_id(value.get("task_id"), "task_id"),
        worktree_plan=parse_artifact_reference(value.get("worktree_plan"), "worktree_plan"),
        base_commit=base_commit,
        worktree=safe_relative_path(value.get("worktree"), "worktree"),
        owner_id=host_or_worker_id(value.get("owner_id"), "owner_id"),
        owned_paths=_sorted_paths(value.get("owned_paths"), "owned_paths"),
        fence=integer_value(value.get("fence"), "fence", minimum=1, maximum=2_147_483_647),
        observed_digest=digest,
        status=enum_value(WorktreeLeaseStatus, value.get("status"), "status"),
        integration_state=_choice(
            value.get("integration_state"),
            "integration_state",
            {"not_started", "requested", "verified", "ambiguous"},
        ),
        ambiguous=boolean_value(value.get("ambiguous"), "ambiguous"),
        recovery_guidance=path_free_text(
            value.get("recovery_guidance"), "recovery_guidance", maximum=4000
        ),
    )


def _validated_root(root: Path) -> Path:
    try:
        if root.is_symlink() or is_reparse_point(root):
            raise SchedulerContractError("Scheduler root must be an unlinked directory.")
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise SchedulerContractError("Scheduler root is unavailable.") from exc
    if not resolved.is_dir():
        raise SchedulerContractError("Scheduler root must be a directory.")
    return resolved


def _verified_path(root: Path, reference: ArtifactReference) -> Path:
    if not verify_artifact(root, reference, maximum_bytes=MAX_ARTIFACT_BYTES):
        raise SchedulerContractError("Referenced artifact identity is invalid.")
    return root.joinpath(*reference.path.split("/"))


def _paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _paths_within(paths: tuple[str, ...], roots: tuple[str, ...]) -> bool:
    return all(any(path == root or path.startswith(root + "/") for root in roots) for path in paths)


def _sorted_task_ids(value: object, where: str) -> tuple[str, ...]:
    result = tuple(
        task_id(item, f"{where}[{index}]")
        for index, item in enumerate(array_value(value, where, maximum=MAX_TASKS))
    )
    return _require_sorted_unique(result, where)


def _sorted_scheduler_ids(value: object, where: str, prefix: str) -> tuple[str, ...]:
    result = tuple(
        scheduler_id(item, f"{where}[{index}]", prefix=prefix)
        for index, item in enumerate(array_value(value, where, maximum=1000))
    )
    return _require_sorted_unique(result, where)


def _sorted_strings(value: object, where: str) -> tuple[str, ...]:
    result = string_tuple(value, where, maximum=64)
    return _require_sorted_unique(result, where)


def _sorted_paths(value: object, where: str) -> tuple[str, ...]:
    result = tuple(
        safe_relative_path(item, f"{where}[{index}]")
        for index, item in enumerate(array_value(value, where, maximum=64))
    )
    result = _require_sorted_unique(result, where)
    for index, path in enumerate(result):
        for other in result[index + 1 :]:
            if _paths_overlap(path, other):
                raise SchedulerContractError(f"{where} contains overlapping paths.")
    return result


def _sorted_path_free_text(value: object, where: str, *, minimum: int = 0) -> tuple[str, ...]:
    result = path_free_tuple(value, where, minimum=minimum, maximum=64)
    return _require_sorted_unique(result, where)


def _artifact_references(value: object, where: str) -> tuple[ArtifactReference, ...]:
    refs = tuple(
        parse_artifact_reference(item, f"{where}[{index}]")
        for index, item in enumerate(array_value(value, where, maximum=MAX_REFERENCES))
    )
    if refs != tuple(sorted(refs, key=lambda item: (item.path, item.sha256))):
        raise SchedulerContractError(f"{where} must be sorted.")
    if len({(item.path, item.sha256) for item in refs}) != len(refs):
        raise SchedulerContractError(f"{where} must be unique.")
    return refs


def _require_sorted_unique(value: tuple[str, ...], where: str) -> tuple[str, ...]:
    if value != tuple(sorted(value)) or len(value) != len(set(value)):
        raise SchedulerContractError(f"{where} must be sorted and unique.")
    return value


def _snapshot_id(value: object, where: str) -> str:
    text = string_value(value, where, maximum=128)
    if not _CONTEXT_ID.fullmatch(text):
        raise SchedulerContractError(f"{where} must be a Context Snapshot identity.")
    return text


def _choice(value: object, where: str, allowed: set[str]) -> str:
    text = string_value(value, where, maximum=100)
    if text not in allowed:
        raise SchedulerContractError(f"{where} is unsupported.")
    return text


def _optional_choice(value: object, where: str, allowed: set[str]) -> str | None:
    return None if value is None else _choice(value, where, allowed)


def _optional_path_free(value: object, where: str) -> str | None:
    return None if value is None else path_free_text(value, where, maximum=4000)


def _optional_scheduler_id(value: object, where: str, prefix: str) -> str | None:
    return None if value is None else scheduler_id(value, where, prefix=prefix)


def _optional_approval_id(value: object, where: str) -> str | None:
    if value is None:
        return None
    text = string_value(value, where, maximum=100)
    if not _APPROVAL_ID.fullmatch(text):
        raise SchedulerContractError(f"{where} is invalid.")
    return text


def _signed_integer(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 1_000_000_000_000_000:
        raise SchedulerContractError(f"{where} must be a bounded integer.")
    return value


def _resource_counts(value: object, where: str, allowed: set[str]) -> dict[str, int]:
    item = object_value(value, where)
    if not set(item).issubset(allowed):
        raise SchedulerContractError(f"{where} contains an unsupported key.")
    return {
        key: integer_value(raw, f"{where}.{key}", minimum=0, maximum=1_000_000_000_000_000)
        for key, raw in sorted(item.items())
    }


def _exact_resource_counts(value: object, where: str, required: set[str]) -> dict[str, int]:
    result = _resource_counts(value, where, required)
    if set(result) != required:
        raise SchedulerContractError(f"{where} must contain every required resource.")
    return result
