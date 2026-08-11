"""Strict canonical contracts for M8 workflow integration artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sdaqf.application.context_contracts import canonical_json_bytes
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
    path_free_text,
    safe_relative_path,
    sha256,
    string_tuple,
    string_value,
)
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.context import SENSITIVITY_RANK, Sensitivity
from sdaqf.domain.scheduler import EffectKind, SchedulerBudget, TaskOutcome, TaskState
from sdaqf.domain.workflow import (
    EXCLUDED_REASON_CODES,
    SELECTED_REASON_CODES,
    UNCERTAINTY_REASON_CODES,
    WORKFLOW_MEASUREMENT_NAMES,
    CompletionProfile,
    DevelopmentIntent,
    EffectDisposition,
    GateObservation,
    GateStatus,
    IntegratedPlan,
    IntegratedPlanTask,
    IntentRisk,
    IntentTaskLink,
    MeasurementStatus,
    NativeArtifactBinding,
    OutcomeClaimState,
    ProtectedEffect,
    WorkflowArtifactType,
    WorkflowBlocker,
    WorkflowDecision,
    WorkflowDecisionKind,
    WorkflowDisposition,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowMeasurement,
    WorkflowOutcome,
    WorkflowState,
    WorkflowTaskProjection,
    WorkflowValue,
)

SMALL_ARTIFACT_BYTES = 1 * 1024 * 1024
LARGE_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_JSON_NODES = 250_000
MAX_TASKS = 4096
MAX_REFERENCES = 4096
MAX_DECISIONS = 16384
MAX_BLOCKERS = 256
MAX_EFFECTS = 256

_PREFIX = {
    WorkflowArtifactType.DEVELOPMENT_INTENT: "M8-DEVELOPMENT-INTENT-",
    WorkflowArtifactType.INTEGRATED_PLAN: "M8-INTEGRATED-PLAN-",
    WorkflowArtifactType.WORKFLOW_STATE: "M8-WORKFLOW-STATE-",
    WorkflowArtifactType.WORKFLOW_EVENT: "M8-WORKFLOW-EVENT-",
    WorkflowArtifactType.WORKFLOW_OUTCOME: "M8-WORKFLOW-OUTCOME-",
}
_SMALL_TYPES = {
    WorkflowArtifactType.DEVELOPMENT_INTENT,
    WorkflowArtifactType.WORKFLOW_EVENT,
}
_WORKFLOW_ID = re.compile(r"^M8-[A-Z-]+-[0-9A-F]{64}$")
_NATIVE_ID = re.compile(r"^[A-Z][A-Z0-9._:@-]{1,191}$")
_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_TASK_ID = re.compile(r"^TSK-[A-Z0-9][A-Z0-9-]{0,63}$")
_REQUIREMENT_ID = re.compile(r"^[A-Z][A-Z0-9-]{0,127}$")
_BASELINE_ID = re.compile(r"^RB-[0-9A-F]{16}$")
_GATE_ID = re.compile(r"^G[1-4]$")
_CODE = re.compile(r"^[a-z][a-z0-9-]{0,95}$")
_NATIVE_TYPE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_IDEMPOTENCY = re.compile(r"^M8-IDEM-[0-9A-F]{64}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_MEASUREMENT = re.compile(
    r"^(?:requirements|context|scheduling|solver|evidence|handoff|recovery|approval|available_cost)"
    r"\.[a-z][a-z0-9_-]{0,95}$"
)


class WorkflowContractError(ContractError):
    """One M8 workflow artifact violates its strict contract."""


@dataclass(frozen=True, slots=True)
class LoadedWorkflowArtifact:
    """Validated content-addressed M8 artifact."""

    artifact_type: WorkflowArtifactType
    artifact_id: str
    value: WorkflowValue

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "artifact_type": self.artifact_type.value,
            "artifact_id": self.artifact_id,
            "content": self.value.to_dict(),
        }


def workflow_identity(artifact_type: WorkflowArtifactType, content: object) -> str:
    """Return the full M5-canonical content identity for one M8 value."""

    digest = hashlib.sha256(canonical_json_bytes(content)).hexdigest().upper()
    return f"{_PREFIX[artifact_type]}{digest}"


def workflow_id(
    value: object,
    where: str,
    *,
    expected_type: WorkflowArtifactType | None = None,
) -> str:
    """Require a full uppercase workflow identity."""

    text = string_value(value, where, maximum=160)
    if not _WORKFLOW_ID.fullmatch(text):
        raise WorkflowContractError(f"{where} must be a full M8 identity.")
    if expected_type is not None and not text.startswith(_PREFIX[expected_type]):
        raise WorkflowContractError(f"{where} has an unexpected M8 identity type.")
    return text


def artifact_from_value(
    artifact_type: WorkflowArtifactType,
    value: WorkflowValue,
) -> LoadedWorkflowArtifact:
    """Create and reparse a canonical artifact from one typed value."""

    try:
        parsed = _parse_value(artifact_type, value.to_dict())
    except WorkflowContractError:
        raise
    except (ContractError, ValueError) as exc:
        raise WorkflowContractError(str(exc)) from exc
    if parsed.to_dict() != value.to_dict():
        raise WorkflowContractError("Generated workflow artifact is not canonical.")
    return LoadedWorkflowArtifact(
        artifact_type,
        workflow_identity(artifact_type, parsed.to_dict()),
        parsed,
    )


def serialize_workflow_artifact(artifact: LoadedWorkflowArtifact) -> bytes:
    """Serialize deterministic ASCII JSON plus one newline."""

    expected = workflow_identity(artifact.artifact_type, artifact.value.to_dict())
    if artifact.artifact_id != expected:
        raise WorkflowContractError("Workflow artifact identity is stale.")
    return (
        json.dumps(artifact.to_dict(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("ascii")


def load_workflow_artifact(
    path: Path,
    *,
    expected_type: WorkflowArtifactType | None = None,
) -> LoadedWorkflowArtifact:
    """Load one bounded regular unlinked M8 JSON file."""

    if path.suffix.casefold() != ".json":
        raise WorkflowContractError("Workflow artifact must be a JSON file.")
    if path.is_symlink() or is_reparse_point(path) or not path.is_file():
        raise WorkflowContractError("Workflow artifact must be a regular unlinked file.")
    try:
        if path.stat().st_size > LARGE_ARTIFACT_BYTES:
            raise WorkflowContractError("Workflow artifact exceeds the size limit.")
        content = path.read_bytes()
    except WorkflowContractError:
        raise
    except OSError as exc:
        raise WorkflowContractError("Workflow artifact could not be read.") from exc
    return parse_workflow_artifact_bytes(content, expected_type=expected_type)


def parse_workflow_artifact_bytes(
    content: bytes,
    *,
    expected_type: WorkflowArtifactType | None = None,
) -> LoadedWorkflowArtifact:
    """Parse strict JSON and reauthenticate its full content identity."""

    if len(content) > LARGE_ARTIFACT_BYTES:
        raise WorkflowContractError("Workflow artifact exceeds the size limit.")

    def strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise WorkflowContractError("Workflow artifact contains a duplicate JSON key.")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise WorkflowContractError(f"Workflow artifact contains non-finite JSON number {value}.")

    try:
        raw: object = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=strict_object,
            parse_constant=reject_constant,
        )
    except WorkflowContractError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise WorkflowContractError("Workflow artifact could not be read.") from exc
    _validate_canonical_value(raw)
    envelope = object_value(raw, "workflow artifact")
    only_keys(
        envelope,
        {"schema_version", "artifact_type", "artifact_id", "content"},
        "workflow artifact",
    )
    if envelope.get("schema_version") != "1.0":
        raise WorkflowContractError("Workflow schema_version must be 1.0.")
    artifact_type = enum_value(WorkflowArtifactType, envelope.get("artifact_type"), "artifact_type")
    if expected_type is not None and artifact_type is not expected_type:
        raise WorkflowContractError("Workflow artifact type is unexpected.")
    maximum = SMALL_ARTIFACT_BYTES if artifact_type in _SMALL_TYPES else LARGE_ARTIFACT_BYTES
    if len(content) > maximum:
        raise WorkflowContractError("Workflow artifact exceeds its type size limit.")
    try:
        value = _parse_value(
            artifact_type,
            object_value(envelope.get("content"), "content"),
        )
    except WorkflowContractError:
        raise
    except (ContractError, ValueError) as exc:
        raise WorkflowContractError(str(exc)) from exc
    artifact_id = workflow_id(
        envelope.get("artifact_id"), "artifact_id", expected_type=artifact_type
    )
    if artifact_id != workflow_identity(artifact_type, value.to_dict()):
        raise WorkflowContractError("Workflow artifact identity does not match content.")
    return LoadedWorkflowArtifact(artifact_type, artifact_id, value)


def verify_workflow_reference(
    root: Path,
    binding: NativeArtifactBinding,
    *,
    maximum_bytes: int = LARGE_ARTIFACT_BYTES,
) -> Path:
    """Reauthenticate one bounded native artifact below an explicit root."""

    try:
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir() or root.is_symlink() or is_reparse_point(root):
            raise WorkflowContractError("Workflow root must be regular and unlinked.")
        candidate = resolved_root.joinpath(*Path(binding.reference.path).parts)
        current = resolved_root
        for part in Path(binding.reference.path).parts:
            current = current / part
            if current.is_symlink() or is_reparse_point(current):
                raise WorkflowContractError("Workflow reference contains a linked component.")
        resolved = candidate.resolve(strict=True)
        if (
            not resolved.is_relative_to(resolved_root)
            or not resolved.is_file()
            or resolved.is_symlink()
            or is_reparse_point(resolved)
            or resolved.stat().st_size > maximum_bytes
        ):
            raise WorkflowContractError("Workflow reference is outside its bounded root.")
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest().upper()
    except WorkflowContractError:
        raise
    except OSError as exc:
        raise WorkflowContractError("Workflow reference could not be observed.") from exc
    if digest != binding.reference.sha256:
        raise WorkflowContractError("Workflow reference digest drifted.")
    return resolved


def _validate_canonical_value(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > 64 or nodes > MAX_JSON_NODES:
            raise WorkflowContractError("Workflow artifact exceeds the JSON structure limit.")
        if isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str) or not key.isascii():
                    raise WorkflowContractError("Workflow artifact keys must be ASCII strings.")
                if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                    raise WorkflowContractError("Workflow artifact contains a surrogate.")
                stack.append((item, depth + 1))
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in current):
                raise WorkflowContractError("Workflow artifact contains a surrogate.")
        elif current is None or isinstance(current, (bool, int)):
            continue
        else:
            raise WorkflowContractError("Workflow artifact contains an unsupported JSON value.")


def _parse_value(
    artifact_type: WorkflowArtifactType,
    value: dict[str, object],
) -> WorkflowValue:
    if artifact_type is WorkflowArtifactType.DEVELOPMENT_INTENT:
        return _parse_intent(value)
    if artifact_type is WorkflowArtifactType.INTEGRATED_PLAN:
        return _parse_plan(value)
    if artifact_type is WorkflowArtifactType.WORKFLOW_STATE:
        return _parse_state(value)
    if artifact_type is WorkflowArtifactType.WORKFLOW_EVENT:
        return _parse_event(value)
    return _parse_outcome(value)


def _parse_intent(value: dict[str, object]) -> DevelopmentIntent:
    where = "content"
    only_keys(
        value,
        {
            "project_id",
            "candidate",
            "objective",
            "completion_profile",
            "specification",
            "requirement_baseline_id",
            "requirement_baseline",
            "allowed_paths",
            "prohibited_paths",
            "required_requirement_ids",
            "required_acceptance_ids",
            "requested_effects",
            "risk",
            "clearance",
            "sensitivity",
            "budget",
            "capabilities",
            "context_graph",
            "context_query",
            "context_selection",
            "context_snapshot",
            "task_graph",
            "solver_registry",
            "solver_requests",
            "task_links",
            "required_gate_ids",
            "observation_slots",
            "ui_required",
            "predecessor_plan_id",
            "predecessor_state_id",
            "predecessor_outcome_id",
            "predecessor_plan",
            "predecessor_state",
            "predecessor_outcome",
        },
        where,
    )
    project_id = string_value(value.get("project_id"), f"{where}.project_id", maximum=64)
    if not _PROJECT_ID.fullmatch(project_id):
        raise WorkflowContractError("content.project_id is invalid.")
    baseline_id = _baseline_id(
        value.get("requirement_baseline_id"),
        f"{where}.requirement_baseline_id",
    )
    allowed = _sorted_paths(value.get("allowed_paths"), f"{where}.allowed_paths")
    prohibited = _sorted_paths(value.get("prohibited_paths"), f"{where}.prohibited_paths")
    if set(allowed) & set(prohibited):
        raise WorkflowContractError("Intent allowed and prohibited paths overlap.")
    required_requirements = _sorted_pattern_ids(
        value.get("required_requirement_ids"), f"{where}.required_requirement_ids"
    )
    required_acceptance = _sorted_pattern_ids(
        value.get("required_acceptance_ids"), f"{where}.required_acceptance_ids"
    )
    requested_effects = _sorted_enums(
        EffectKind, value.get("requested_effects"), f"{where}.requested_effects", maximum=4
    )
    clearance = enum_value(Sensitivity, value.get("clearance"), f"{where}.clearance")
    sensitivity = enum_value(Sensitivity, value.get("sensitivity"), f"{where}.sensitivity")
    if SENSITIVITY_RANK[sensitivity] > SENSITIVITY_RANK[clearance]:
        raise WorkflowContractError("Intent sensitivity exceeds actor clearance.")
    solver_registry = _optional_binding(value.get("solver_registry"), f"{where}.solver_registry")
    solver_requests = _required_bindings(value.get("solver_requests"), f"{where}.solver_requests")
    if solver_registry is None and solver_requests:
        raise WorkflowContractError("Solver Requests require an exact Solver Registry.")
    task_links = _task_links(value.get("task_links"), f"{where}.task_links")
    gates = _gate_ids(value.get("required_gate_ids"), f"{where}.required_gate_ids")
    predecessor_plan = _optional_workflow_id(
        value.get("predecessor_plan_id"),
        f"{where}.predecessor_plan_id",
        WorkflowArtifactType.INTEGRATED_PLAN,
    )
    predecessor_outcome = _optional_workflow_id(
        value.get("predecessor_outcome_id"),
        f"{where}.predecessor_outcome_id",
        WorkflowArtifactType.WORKFLOW_OUTCOME,
    )
    predecessor_state = _optional_workflow_id(
        value.get("predecessor_state_id"),
        f"{where}.predecessor_state_id",
        WorkflowArtifactType.WORKFLOW_STATE,
    )
    predecessor_plan_binding = _optional_binding(
        value.get("predecessor_plan"), f"{where}.predecessor_plan"
    )
    predecessor_state_binding = _optional_binding(
        value.get("predecessor_state"), f"{where}.predecessor_state"
    )
    predecessor_outcome_binding = _optional_binding(
        value.get("predecessor_outcome"), f"{where}.predecessor_outcome"
    )
    predecessor_values = (
        predecessor_plan,
        predecessor_state,
        predecessor_outcome,
        predecessor_plan_binding,
        predecessor_state_binding,
        predecessor_outcome_binding,
    )
    if any(item is None for item in predecessor_values) and any(
        item is not None for item in predecessor_values
    ):
        raise WorkflowContractError(
            "Intent predecessor IDs and exact bindings must be provided together."
        )
    _validate_predecessor_bindings(
        predecessor_plan,
        predecessor_state,
        predecessor_outcome,
        predecessor_plan_binding,
        predecessor_state_binding,
        predecessor_outcome_binding,
        "Intent",
    )
    result = DevelopmentIntent(
        project_id=project_id,
        candidate=parse_candidate_identity(value.get("candidate"), f"{where}.candidate"),
        objective=path_free_text(value.get("objective"), f"{where}.objective"),
        completion_profile=enum_value(
            CompletionProfile, value.get("completion_profile"), f"{where}.completion_profile"
        ),
        specification=parse_artifact_reference(
            value.get("specification"), f"{where}.specification"
        ),
        requirement_baseline_id=baseline_id,
        requirement_baseline=parse_artifact_reference(
            value.get("requirement_baseline"), f"{where}.requirement_baseline"
        ),
        allowed_paths=allowed,
        prohibited_paths=prohibited,
        required_requirement_ids=required_requirements,
        required_acceptance_ids=required_acceptance,
        requested_effects=requested_effects,
        risk=enum_value(IntentRisk, value.get("risk"), f"{where}.risk"),
        clearance=clearance,
        sensitivity=sensitivity,
        budget=_parse_budget(value.get("budget"), f"{where}.budget"),
        capabilities=_sorted_codes(value.get("capabilities"), f"{where}.capabilities"),
        context_graph=_required_binding(value.get("context_graph"), f"{where}.context_graph"),
        context_query=_required_binding(value.get("context_query"), f"{where}.context_query"),
        context_selection=_required_binding(
            value.get("context_selection"), f"{where}.context_selection"
        ),
        context_snapshot=_required_binding(
            value.get("context_snapshot"), f"{where}.context_snapshot"
        ),
        task_graph=_required_binding(value.get("task_graph"), f"{where}.task_graph"),
        solver_registry=solver_registry,
        solver_requests=solver_requests,
        task_links=task_links,
        required_gate_ids=gates,
        observation_slots=_sorted_codes(
            value.get("observation_slots"), f"{where}.observation_slots"
        ),
        ui_required=boolean_value(value.get("ui_required"), f"{where}.ui_required"),
        predecessor_plan_id=predecessor_plan,
        predecessor_state_id=predecessor_state,
        predecessor_outcome_id=predecessor_outcome,
        predecessor_plan=predecessor_plan_binding,
        predecessor_state=predecessor_state_binding,
        predecessor_outcome=predecessor_outcome_binding,
    )
    _validate_intent_profile(result)
    _reject_unrepresentable_secret_content(result.sensitivity, result.objective)
    return result


def _parse_plan(value: dict[str, object]) -> IntegratedPlan:
    where = "content"
    only_keys(
        value,
        {
            "intent",
            "project_id",
            "candidate",
            "sensitivity",
            "completion_profile",
            "specification",
            "requirement_baseline_id",
            "requirement_baseline",
            "context_graph",
            "context_query",
            "context_selection",
            "context_snapshot",
            "task_graph",
            "solver_registry",
            "solver_requests",
            "tasks",
            "protected_effects",
            "decisions",
            "budget",
            "required_gate_ids",
            "observation_slots",
            "ui_required",
            "predecessor_plan_id",
            "predecessor_state_id",
            "predecessor_outcome_id",
            "predecessor_plan",
            "predecessor_state",
            "predecessor_outcome",
        },
        where,
    )
    project_id = string_value(value.get("project_id"), f"{where}.project_id", maximum=64)
    if not _PROJECT_ID.fullmatch(project_id):
        raise WorkflowContractError("content.project_id is invalid.")
    tasks = _plan_tasks(value.get("tasks"), f"{where}.tasks")
    effects = _protected_effects(value.get("protected_effects"), f"{where}.protected_effects")
    decisions = _decisions(value.get("decisions"), f"{where}.decisions")
    solver_registry = _optional_binding(value.get("solver_registry"), f"{where}.solver_registry")
    solver_requests = _required_bindings(value.get("solver_requests"), f"{where}.solver_requests")
    if solver_registry is None and solver_requests:
        raise WorkflowContractError("Plan Solver Requests require a Solver Registry.")
    predecessor_plan = _optional_workflow_id(
        value.get("predecessor_plan_id"),
        f"{where}.predecessor_plan_id",
        WorkflowArtifactType.INTEGRATED_PLAN,
    )
    predecessor_outcome = _optional_workflow_id(
        value.get("predecessor_outcome_id"),
        f"{where}.predecessor_outcome_id",
        WorkflowArtifactType.WORKFLOW_OUTCOME,
    )
    predecessor_state = _optional_workflow_id(
        value.get("predecessor_state_id"),
        f"{where}.predecessor_state_id",
        WorkflowArtifactType.WORKFLOW_STATE,
    )
    predecessor_plan_binding = _optional_binding(
        value.get("predecessor_plan"), f"{where}.predecessor_plan"
    )
    predecessor_state_binding = _optional_binding(
        value.get("predecessor_state"), f"{where}.predecessor_state"
    )
    predecessor_outcome_binding = _optional_binding(
        value.get("predecessor_outcome"), f"{where}.predecessor_outcome"
    )
    predecessor_values = (
        predecessor_plan,
        predecessor_state,
        predecessor_outcome,
        predecessor_plan_binding,
        predecessor_state_binding,
        predecessor_outcome_binding,
    )
    if any(item is None for item in predecessor_values) and any(
        item is not None for item in predecessor_values
    ):
        raise WorkflowContractError(
            "Plan predecessor IDs and exact bindings must be provided together."
        )
    _validate_predecessor_bindings(
        predecessor_plan,
        predecessor_state,
        predecessor_outcome,
        predecessor_plan_binding,
        predecessor_state_binding,
        predecessor_outcome_binding,
        "Plan",
    )
    task_ids = {item.task_id for item in tasks}
    if any(effect.task_id not in task_ids for effect in effects):
        raise WorkflowContractError("Protected effect references an unknown Plan task.")
    result = IntegratedPlan(
        intent=_required_binding(value.get("intent"), f"{where}.intent"),
        project_id=project_id,
        candidate=parse_candidate_identity(value.get("candidate"), f"{where}.candidate"),
        sensitivity=enum_value(Sensitivity, value.get("sensitivity"), f"{where}.sensitivity"),
        completion_profile=enum_value(
            CompletionProfile, value.get("completion_profile"), f"{where}.completion_profile"
        ),
        specification=parse_artifact_reference(
            value.get("specification"), f"{where}.specification"
        ),
        requirement_baseline_id=_baseline_id(
            value.get("requirement_baseline_id"), f"{where}.requirement_baseline_id"
        ),
        requirement_baseline=parse_artifact_reference(
            value.get("requirement_baseline"), f"{where}.requirement_baseline"
        ),
        context_graph=_required_binding(value.get("context_graph"), f"{where}.context_graph"),
        context_query=_required_binding(value.get("context_query"), f"{where}.context_query"),
        context_selection=_required_binding(
            value.get("context_selection"), f"{where}.context_selection"
        ),
        context_snapshot=_required_binding(
            value.get("context_snapshot"), f"{where}.context_snapshot"
        ),
        task_graph=_required_binding(value.get("task_graph"), f"{where}.task_graph"),
        solver_registry=solver_registry,
        solver_requests=solver_requests,
        tasks=tasks,
        protected_effects=effects,
        decisions=decisions,
        budget=_parse_budget(value.get("budget"), f"{where}.budget"),
        required_gate_ids=_gate_ids(value.get("required_gate_ids"), f"{where}.required_gate_ids"),
        observation_slots=_sorted_codes(
            value.get("observation_slots"), f"{where}.observation_slots"
        ),
        ui_required=boolean_value(value.get("ui_required"), f"{where}.ui_required"),
        predecessor_plan_id=predecessor_plan,
        predecessor_state_id=predecessor_state,
        predecessor_outcome_id=predecessor_outcome,
        predecessor_plan=predecessor_plan_binding,
        predecessor_state=predecessor_state_binding,
        predecessor_outcome=predecessor_outcome_binding,
    )
    if result.intent.artifact_type != WorkflowArtifactType.DEVELOPMENT_INTENT.value:
        raise WorkflowContractError("Plan intent binding must reference Development Intent.")
    _validate_plan_profile(result)
    if result.sensitivity is Sensitivity.SECRET_OR_PROHIBITED:
        raise WorkflowContractError(
            "Secret-or-prohibited native content cannot be embedded in an Integrated Plan."
        )
    return result


def _parse_state(value: dict[str, object]) -> WorkflowState:
    where = "content"
    only_keys(
        value,
        {
            "plan_id",
            "candidate",
            "sensitivity",
            "status",
            "scheduler_graph_id",
            "scheduler_state_id",
            "scheduler_event_sequence",
            "scheduler_event_head_sha256",
            "tasks",
            "solver_verification_ids",
            "evidence_ids",
            "review_ids",
            "approval_ids",
            "gates",
            "handoff_id",
            "handoff_status",
            "blockers",
            "ambiguities",
            "measurements",
            "observation_artifacts",
            "event_chain",
            "latest_event",
            "transition_count",
            "recorded_at",
        },
        where,
    )
    handoff_id = _optional_native_id(value.get("handoff_id"), f"{where}.handoff_id")
    handoff_status = _optional_code(value.get("handoff_status"), f"{where}.handoff_status")
    if (handoff_id is None) != (handoff_status is None):
        raise WorkflowContractError("Workflow State handoff identity and status must be paired.")
    result = WorkflowState(
        plan_id=workflow_id(
            value.get("plan_id"),
            f"{where}.plan_id",
            expected_type=WorkflowArtifactType.INTEGRATED_PLAN,
        ),
        candidate=parse_candidate_identity(value.get("candidate"), f"{where}.candidate"),
        sensitivity=enum_value(Sensitivity, value.get("sensitivity"), f"{where}.sensitivity"),
        status=enum_value(TaskState, value.get("status"), f"{where}.status"),
        scheduler_graph_id=_native_id(
            value.get("scheduler_graph_id"), f"{where}.scheduler_graph_id"
        ),
        scheduler_state_id=_native_id(
            value.get("scheduler_state_id"), f"{where}.scheduler_state_id"
        ),
        scheduler_event_sequence=integer_value(
            value.get("scheduler_event_sequence"),
            f"{where}.scheduler_event_sequence",
            minimum=0,
            maximum=2_147_483_647,
        ),
        scheduler_event_head_sha256=sha256(
            value.get("scheduler_event_head_sha256"),
            f"{where}.scheduler_event_head_sha256",
        ),
        tasks=_workflow_tasks(value.get("tasks"), f"{where}.tasks"),
        solver_verification_ids=_sorted_native_ids(
            value.get("solver_verification_ids"),
            f"{where}.solver_verification_ids",
        ),
        evidence_ids=_sorted_native_ids(value.get("evidence_ids"), f"{where}.evidence_ids"),
        review_ids=_sorted_native_ids(value.get("review_ids"), f"{where}.review_ids"),
        approval_ids=_sorted_native_ids(value.get("approval_ids"), f"{where}.approval_ids"),
        gates=_gates(value.get("gates"), f"{where}.gates"),
        handoff_id=handoff_id,
        handoff_status=handoff_status,
        blockers=_blockers(value.get("blockers"), f"{where}.blockers"),
        ambiguities=_sorted_codes(value.get("ambiguities"), f"{where}.ambiguities"),
        measurements=_measurements(value.get("measurements"), f"{where}.measurements"),
        observation_artifacts=_required_bindings(
            value.get("observation_artifacts"), f"{where}.observation_artifacts"
        ),
        event_chain=_ordered_required_bindings(
            value.get("event_chain"), f"{where}.event_chain", minimum=1
        ),
        latest_event=_required_binding(value.get("latest_event"), f"{where}.latest_event"),
        transition_count=integer_value(
            value.get("transition_count"),
            f"{where}.transition_count",
            minimum=1,
            maximum=2_147_483_647,
        ),
        recorded_at=_utc_timestamp(value.get("recorded_at"), f"{where}.recorded_at"),
    )
    if result.latest_event.artifact_type != WorkflowArtifactType.WORKFLOW_EVENT.value:
        raise WorkflowContractError("Workflow State latest_event has the wrong type.")
    workflow_id(
        result.latest_event.artifact_id,
        "content.latest_event.artifact_id",
        expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
    )
    if (
        len(result.event_chain) != result.transition_count
        or result.event_chain[-1] != result.latest_event
        or any(
            item.artifact_type != WorkflowArtifactType.WORKFLOW_EVENT.value
            for item in result.event_chain
        )
    ):
        raise WorkflowContractError("Workflow State Event chain is incomplete or inconsistent.")
    return result


def _parse_event(value: dict[str, object]) -> WorkflowEvent:
    where = "content"
    only_keys(
        value,
        {
            "sequence",
            "previous_event_id",
            "prior_state_id",
            "prior_state",
            "plan_id",
            "candidate",
            "sensitivity",
            "cause",
            "before_status",
            "after_status",
            "scheduler_event_head_before",
            "scheduler_event_head_after",
            "effect_disposition",
            "actor",
            "recorded_at",
            "idempotency_key",
            "native_input_ids",
            "native_output_ids",
            "task_id",
            "effect_id",
            "approval_id",
            "reason_codes",
        },
        where,
    )
    sequence = integer_value(
        value.get("sequence"), f"{where}.sequence", minimum=1, maximum=2_147_483_647
    )
    previous = _optional_workflow_id(
        value.get("previous_event_id"),
        f"{where}.previous_event_id",
        WorkflowArtifactType.WORKFLOW_EVENT,
    )
    prior = _optional_workflow_id(
        value.get("prior_state_id"),
        f"{where}.prior_state_id",
        WorkflowArtifactType.WORKFLOW_STATE,
    )
    prior_binding = _optional_binding(value.get("prior_state"), f"{where}.prior_state")
    if sequence == 1 and (previous is not None or prior is not None or prior_binding is not None):
        raise WorkflowContractError("First Workflow Event cannot claim prior M8 artifacts.")
    if sequence > 1 and (
        previous is None
        or prior is None
        or prior_binding is None
        or prior_binding.artifact_type != WorkflowArtifactType.WORKFLOW_STATE.value
        or prior_binding.artifact_id != prior
        or not prior_binding.required
    ):
        raise WorkflowContractError(
            "Later Workflow Event requires its exact prior Event and State binding."
        )
    key = string_value(value.get("idempotency_key"), f"{where}.idempotency_key", maximum=72)
    if not _IDEMPOTENCY.fullmatch(key):
        raise WorkflowContractError("Workflow Event idempotency key is invalid.")
    task = _optional_pattern_id(value.get("task_id"), f"{where}.task_id", _TASK_ID)
    return WorkflowEvent(
        sequence=sequence,
        previous_event_id=previous,
        prior_state_id=prior,
        plan_id=workflow_id(
            value.get("plan_id"),
            f"{where}.plan_id",
            expected_type=WorkflowArtifactType.INTEGRATED_PLAN,
        ),
        candidate=parse_candidate_identity(value.get("candidate"), f"{where}.candidate"),
        sensitivity=enum_value(Sensitivity, value.get("sensitivity"), f"{where}.sensitivity"),
        cause=enum_value(WorkflowEventCause, value.get("cause"), f"{where}.cause"),
        before_status=enum_value(TaskState, value.get("before_status"), f"{where}.before_status"),
        after_status=enum_value(TaskState, value.get("after_status"), f"{where}.after_status"),
        scheduler_event_head_before=sha256(
            value.get("scheduler_event_head_before"),
            f"{where}.scheduler_event_head_before",
        ),
        scheduler_event_head_after=sha256(
            value.get("scheduler_event_head_after"),
            f"{where}.scheduler_event_head_after",
        ),
        effect_disposition=enum_value(
            EffectDisposition,
            value.get("effect_disposition"),
            f"{where}.effect_disposition",
        ),
        actor=path_free_text(value.get("actor"), f"{where}.actor", maximum=128),
        recorded_at=_utc_timestamp(value.get("recorded_at"), f"{where}.recorded_at"),
        idempotency_key=key,
        native_input_ids=_sorted_native_ids(
            value.get("native_input_ids"), f"{where}.native_input_ids"
        ),
        native_output_ids=_sorted_native_ids(
            value.get("native_output_ids"), f"{where}.native_output_ids"
        ),
        task_id=task,
        effect_id=_optional_native_id(value.get("effect_id"), f"{where}.effect_id"),
        approval_id=_optional_native_id(value.get("approval_id"), f"{where}.approval_id"),
        reason_codes=_sorted_codes(value.get("reason_codes"), f"{where}.reason_codes"),
        prior_state=prior_binding,
    )


def _parse_outcome(value: dict[str, object]) -> WorkflowOutcome:
    where = "content"
    only_keys(
        value,
        {
            "plan_id",
            "lineage_plan_ids",
            "terminal_state_id",
            "candidate",
            "sensitivity",
            "disposition",
            "claim_state",
            "completion_profile",
            "scheduler_state_id",
            "solver_verification_ids",
            "evidence_ids",
            "review_ids",
            "gates",
            "effect_ids",
            "approval_ids",
            "ambiguities",
            "blockers",
            "measurements",
            "observation_artifacts",
            "handoff_id",
            "handoff_status",
            "next_action",
            "completed_at",
        },
        where,
    )
    plan_id = workflow_id(
        value.get("plan_id"),
        f"{where}.plan_id",
        expected_type=WorkflowArtifactType.INTEGRATED_PLAN,
    )
    lineage = _sorted_workflow_ids(
        value.get("lineage_plan_ids"),
        f"{where}.lineage_plan_ids",
        WorkflowArtifactType.INTEGRATED_PLAN,
    )
    if plan_id not in lineage:
        raise WorkflowContractError("Workflow Outcome lineage omits its Plan.")
    handoff_id = _optional_native_id(value.get("handoff_id"), f"{where}.handoff_id")
    handoff_status = _optional_code(value.get("handoff_status"), f"{where}.handoff_status")
    if (handoff_id is None) != (handoff_status is None):
        raise WorkflowContractError("Workflow Outcome handoff fields must be paired.")
    result = WorkflowOutcome(
        plan_id=plan_id,
        lineage_plan_ids=lineage,
        terminal_state_id=workflow_id(
            value.get("terminal_state_id"),
            f"{where}.terminal_state_id",
            expected_type=WorkflowArtifactType.WORKFLOW_STATE,
        ),
        candidate=parse_candidate_identity(value.get("candidate"), f"{where}.candidate"),
        sensitivity=enum_value(Sensitivity, value.get("sensitivity"), f"{where}.sensitivity"),
        disposition=enum_value(
            WorkflowDisposition, value.get("disposition"), f"{where}.disposition"
        ),
        claim_state=enum_value(OutcomeClaimState, value.get("claim_state"), f"{where}.claim_state"),
        completion_profile=enum_value(
            CompletionProfile, value.get("completion_profile"), f"{where}.completion_profile"
        ),
        scheduler_state_id=_native_id(
            value.get("scheduler_state_id"), f"{where}.scheduler_state_id"
        ),
        solver_verification_ids=_sorted_native_ids(
            value.get("solver_verification_ids"), f"{where}.solver_verification_ids"
        ),
        evidence_ids=_sorted_native_ids(value.get("evidence_ids"), f"{where}.evidence_ids"),
        review_ids=_sorted_native_ids(value.get("review_ids"), f"{where}.review_ids"),
        gates=_gates(value.get("gates"), f"{where}.gates"),
        effect_ids=_sorted_native_ids(value.get("effect_ids"), f"{where}.effect_ids"),
        approval_ids=_sorted_native_ids(value.get("approval_ids"), f"{where}.approval_ids"),
        ambiguities=_sorted_codes(value.get("ambiguities"), f"{where}.ambiguities"),
        blockers=_blockers(value.get("blockers"), f"{where}.blockers"),
        measurements=_measurements(value.get("measurements"), f"{where}.measurements"),
        observation_artifacts=_required_bindings(
            value.get("observation_artifacts"), f"{where}.observation_artifacts"
        ),
        handoff_id=handoff_id,
        handoff_status=handoff_status,
        next_action=path_free_text(value.get("next_action"), f"{where}.next_action", maximum=4000),
        completed_at=_utc_timestamp(value.get("completed_at"), f"{where}.completed_at"),
    )
    if (
        result.disposition is WorkflowDisposition.COMPLETED
        and result.claim_state is not OutcomeClaimState.VERIFIED
    ):
        raise WorkflowContractError("Completed Outcome claims must be verified.")
    if (
        result.disposition is not WorkflowDisposition.COMPLETED
        and result.claim_state is OutcomeClaimState.VERIFIED
    ):
        raise WorkflowContractError("Non-completed Outcome cannot claim verified completion.")
    return result


def _parse_binding(value: object, where: str) -> NativeArtifactBinding:
    item = object_value(value, where)
    only_keys(item, {"artifact_type", "artifact_id", "reference", "required"}, where)
    artifact_type = string_value(item.get("artifact_type"), f"{where}.artifact_type", maximum=64)
    if not _NATIVE_TYPE.fullmatch(artifact_type):
        raise WorkflowContractError(f"{where}.artifact_type is invalid.")
    return NativeArtifactBinding(
        artifact_type=artifact_type,
        artifact_id=_native_or_workflow_id(item.get("artifact_id"), f"{where}.artifact_id"),
        reference=parse_artifact_reference(item.get("reference"), f"{where}.reference"),
        required=boolean_value(item.get("required"), f"{where}.required"),
    )


def _optional_binding(value: object, where: str) -> NativeArtifactBinding | None:
    return None if value is None else _required_binding(value, where)


def _validate_predecessor_bindings(
    plan_id: str | None,
    state_id: str | None,
    outcome_id: str | None,
    plan: NativeArtifactBinding | None,
    state: NativeArtifactBinding | None,
    outcome: NativeArtifactBinding | None,
    subject: str,
) -> None:
    if plan_id is None:
        return
    assert state_id is not None
    assert outcome_id is not None
    assert plan is not None
    assert state is not None
    assert outcome is not None
    expected = (
        (plan, WorkflowArtifactType.INTEGRATED_PLAN, plan_id),
        (state, WorkflowArtifactType.WORKFLOW_STATE, state_id),
        (outcome, WorkflowArtifactType.WORKFLOW_OUTCOME, outcome_id),
    )
    if any(
        binding.artifact_type != artifact_type.value
        or binding.artifact_id != artifact_id
        or not binding.required
        for binding, artifact_type, artifact_id in expected
    ):
        raise WorkflowContractError(
            f"{subject} predecessor binding types or identities are inconsistent."
        )


def _required_binding(value: object, where: str) -> NativeArtifactBinding:
    binding = _parse_binding(value, where)
    if not binding.required:
        raise WorkflowContractError(f"{where} must be an exact required binding.")
    return binding


def _bindings(value: object, where: str) -> tuple[NativeArtifactBinding, ...]:
    items = tuple(
        _parse_binding(item, f"{where}[{index}]")
        for index, item in enumerate(array_value(value, where, maximum=MAX_REFERENCES))
    )
    if items != tuple(sorted(items, key=lambda item: item.artifact_id)):
        raise WorkflowContractError(f"{where} must use artifact identity order.")
    if len({item.artifact_id for item in items}) != len(items):
        raise WorkflowContractError(f"{where} contains duplicate identities.")
    return items


def _required_bindings(
    value: object,
    where: str,
    *,
    minimum: int = 0,
) -> tuple[NativeArtifactBinding, ...]:
    raw_items = array_value(value, where, maximum=MAX_REFERENCES)
    if len(raw_items) < minimum:
        raise WorkflowContractError(f"{where} has too few required bindings.")
    items = tuple(
        _required_binding(item, f"{where}[{index}]") for index, item in enumerate(raw_items)
    )
    if items != tuple(sorted(items, key=lambda item: item.artifact_id)):
        raise WorkflowContractError(f"{where} must use artifact identity order.")
    if len({item.artifact_id for item in items}) != len(items):
        raise WorkflowContractError(f"{where} contains duplicate artifact identities.")
    return items


def _ordered_required_bindings(
    value: object,
    where: str,
    *,
    minimum: int = 0,
) -> tuple[NativeArtifactBinding, ...]:
    raw_items = array_value(value, where, maximum=MAX_REFERENCES)
    if len(raw_items) < minimum:
        raise WorkflowContractError(f"{where} has too few required bindings.")
    items = tuple(
        _required_binding(item, f"{where}[{index}]") for index, item in enumerate(raw_items)
    )
    if len({item.artifact_id for item in items}) != len(items):
        raise WorkflowContractError(f"{where} contains duplicate artifact identities.")
    return items


def _task_links(value: object, where: str) -> tuple[IntentTaskLink, ...]:
    result: list[IntentTaskLink] = []
    for index, raw in enumerate(array_value(value, where, maximum=MAX_TASKS)):
        item_where = f"{where}[{index}]"
        item = object_value(raw, item_where)
        only_keys(
            item,
            {
                "task_id",
                "requirement_ids",
                "acceptance_ids",
                "context_node_ids",
                "solver_request_ids",
            },
            item_where,
        )
        result.append(
            IntentTaskLink(
                task_id=_task_id(item.get("task_id"), f"{item_where}.task_id"),
                requirement_ids=_sorted_pattern_ids(
                    item.get("requirement_ids"), f"{item_where}.requirement_ids"
                ),
                acceptance_ids=_sorted_pattern_ids(
                    item.get("acceptance_ids"), f"{item_where}.acceptance_ids"
                ),
                context_node_ids=_sorted_native_ids(
                    item.get("context_node_ids"), f"{item_where}.context_node_ids"
                ),
                solver_request_ids=_sorted_native_ids(
                    item.get("solver_request_ids"), f"{item_where}.solver_request_ids"
                ),
            )
        )
    items = tuple(result)
    if items != tuple(sorted(items, key=lambda item: item.task_id)):
        raise WorkflowContractError(f"{where} must use Task ID order.")
    if len({item.task_id for item in items}) != len(items):
        raise WorkflowContractError(f"{where} contains duplicate Task IDs.")
    return items


def _plan_tasks(value: object, where: str) -> tuple[IntegratedPlanTask, ...]:
    result: list[IntegratedPlanTask] = []
    for index, raw in enumerate(array_value(value, where, maximum=MAX_TASKS)):
        item_where = f"{where}[{index}]"
        item = object_value(raw, item_where)
        only_keys(
            item,
            {
                "task_id",
                "phase",
                "topological_rank",
                "wave",
                "task_kind",
                "dependencies",
                "role_id",
                "context_snapshot_id",
                "requirement_ids",
                "acceptance_ids",
                "context_node_ids",
                "solver_request_ids",
                "effect_kind",
                "approval_stops",
                "evidence_predicates",
                "terminal_predicates",
            },
            item_where,
        )
        task_kind = string_value(item.get("task_kind"), f"{item_where}.task_kind", maximum=32)
        if not _CODE.fullmatch(task_kind):
            raise WorkflowContractError(f"{item_where}.task_kind is invalid.")
        result.append(
            IntegratedPlanTask(
                task_id=_task_id(item.get("task_id"), f"{item_where}.task_id"),
                phase=integer_value(
                    item.get("phase"), f"{item_where}.phase", minimum=0, maximum=64
                ),
                topological_rank=integer_value(
                    item.get("topological_rank"),
                    f"{item_where}.topological_rank",
                    minimum=0,
                    maximum=MAX_TASKS,
                ),
                wave=integer_value(
                    item.get("wave"), f"{item_where}.wave", minimum=0, maximum=MAX_TASKS
                ),
                task_kind=task_kind,
                dependencies=_sorted_task_ids(
                    item.get("dependencies"), f"{item_where}.dependencies"
                ),
                role_id=_code(item.get("role_id"), f"{item_where}.role_id"),
                context_snapshot_id=_native_id(
                    item.get("context_snapshot_id"), f"{item_where}.context_snapshot_id"
                ),
                requirement_ids=_sorted_pattern_ids(
                    item.get("requirement_ids"), f"{item_where}.requirement_ids"
                ),
                acceptance_ids=_sorted_pattern_ids(
                    item.get("acceptance_ids"), f"{item_where}.acceptance_ids"
                ),
                context_node_ids=_sorted_native_ids(
                    item.get("context_node_ids"), f"{item_where}.context_node_ids"
                ),
                solver_request_ids=_sorted_native_ids(
                    item.get("solver_request_ids"), f"{item_where}.solver_request_ids"
                ),
                effect_kind=enum_value(
                    EffectKind, item.get("effect_kind"), f"{item_where}.effect_kind"
                ),
                approval_stops=_sorted_codes(
                    item.get("approval_stops"), f"{item_where}.approval_stops", maximum=2
                ),
                evidence_predicates=_sorted_codes(
                    item.get("evidence_predicates"), f"{item_where}.evidence_predicates"
                ),
                terminal_predicates=_sorted_codes(
                    item.get("terminal_predicates"),
                    f"{item_where}.terminal_predicates",
                    minimum=1,
                ),
            )
        )
    tasks = tuple(result)
    expected = tuple(
        sorted(
            tasks,
            key=lambda item: (
                item.phase,
                item.topological_rank,
                item.wave,
                item.task_kind,
                item.task_id,
            ),
        )
    )
    if tasks != expected:
        raise WorkflowContractError(f"{where} is not in deterministic Plan order.")
    ids = {item.task_id for item in tasks}
    if len(ids) != len(tasks) or any(not set(item.dependencies) <= ids for item in tasks):
        raise WorkflowContractError(f"{where} has duplicate or unknown Task references.")
    return tasks


def _protected_effects(value: object, where: str) -> tuple[ProtectedEffect, ...]:
    result: list[ProtectedEffect] = []
    for index, raw in enumerate(array_value(value, where, maximum=MAX_EFFECTS)):
        item_where = f"{where}[{index}]"
        item = object_value(raw, item_where)
        only_keys(
            item,
            {
                "effect_id",
                "task_id",
                "effect_kind",
                "target_paths",
                "network_destinations",
                "reversible",
                "ambiguous_on_failure",
                "approval_types",
                "idempotency_scope",
                "effect_digest",
            },
            item_where,
        )
        effect_id = _native_id(item.get("effect_id"), f"{item_where}.effect_id")
        digest = sha256(item.get("effect_digest"), f"{item_where}.effect_digest")
        if effect_id != f"M8-EFFECT-{digest}":
            raise WorkflowContractError("Protected effect ID must bind its exact digest.")
        destinations = string_tuple(
            item.get("network_destinations"),
            f"{item_where}.network_destinations",
            maximum=64,
        )
        if destinations != tuple(sorted(set(destinations))) or any(
            not destination or len(destination) > 256 or "\n" in destination
            for destination in destinations
        ):
            raise WorkflowContractError("Protected effect destinations are not canonical.")
        result.append(
            ProtectedEffect(
                effect_id=effect_id,
                task_id=_task_id(item.get("task_id"), f"{item_where}.task_id"),
                effect_kind=enum_value(
                    EffectKind, item.get("effect_kind"), f"{item_where}.effect_kind"
                ),
                target_paths=_sorted_paths(item.get("target_paths"), f"{item_where}.target_paths"),
                network_destinations=destinations,
                reversible=boolean_value(item.get("reversible"), f"{item_where}.reversible"),
                ambiguous_on_failure=boolean_value(
                    item.get("ambiguous_on_failure"),
                    f"{item_where}.ambiguous_on_failure",
                ),
                approval_types=_sorted_codes(
                    item.get("approval_types"), f"{item_where}.approval_types", maximum=2
                ),
                idempotency_scope=_code(
                    item.get("idempotency_scope"), f"{item_where}.idempotency_scope"
                ),
                effect_digest=digest,
            )
        )
    effects = tuple(result)
    if effects != tuple(sorted(effects, key=lambda item: item.effect_id)):
        raise WorkflowContractError(f"{where} must use effect identity order.")
    if len({item.effect_id for item in effects}) != len(effects):
        raise WorkflowContractError(f"{where} contains duplicate effect IDs.")
    return effects


def _decisions(value: object, where: str) -> tuple[WorkflowDecision, ...]:
    result: list[WorkflowDecision] = []
    for index, raw in enumerate(array_value(value, where, maximum=MAX_DECISIONS)):
        item_where = f"{where}[{index}]"
        item = object_value(raw, item_where)
        only_keys(
            item,
            {"subject_kind", "subject_id", "kind", "reason_code", "references", "blocking"},
            item_where,
        )
        kind = enum_value(WorkflowDecisionKind, item.get("kind"), f"{item_where}.kind")
        reason = _code(item.get("reason_code"), f"{item_where}.reason_code")
        allowed = {
            WorkflowDecisionKind.SELECTED: SELECTED_REASON_CODES,
            WorkflowDecisionKind.EXCLUDED: EXCLUDED_REASON_CODES,
            WorkflowDecisionKind.UNCERTAINTY: UNCERTAINTY_REASON_CODES,
        }[kind]
        if reason not in allowed:
            raise WorkflowContractError(f"{item_where}.reason_code is invalid for its kind.")
        blocking = boolean_value(item.get("blocking"), f"{item_where}.blocking")
        if kind is not WorkflowDecisionKind.UNCERTAINTY and blocking:
            raise WorkflowContractError("Only uncertainty decisions may block a Plan.")
        result.append(
            WorkflowDecision(
                subject_kind=_code(item.get("subject_kind"), f"{item_where}.subject_kind"),
                subject_id=_native_or_workflow_id(
                    item.get("subject_id"), f"{item_where}.subject_id"
                ),
                kind=kind,
                reason_code=reason,
                references=_sorted_native_or_workflow_ids(
                    item.get("references"), f"{item_where}.references"
                ),
                blocking=blocking,
            )
        )
    decisions = tuple(result)
    expected = tuple(
        sorted(
            decisions,
            key=lambda item: (
                item.subject_kind,
                item.subject_id,
                item.kind.value,
                item.reason_code,
                item.references,
            ),
        )
    )
    if decisions != expected:
        raise WorkflowContractError(f"{where} must use deterministic reason order.")
    if len({item.to_dict().__repr__() for item in decisions}) != len(decisions):
        raise WorkflowContractError(f"{where} contains duplicate decisions.")
    return decisions


def _workflow_tasks(value: object, where: str) -> tuple[WorkflowTaskProjection, ...]:
    result: list[WorkflowTaskProjection] = []
    for index, raw in enumerate(array_value(value, where, maximum=MAX_TASKS)):
        item_where = f"{where}[{index}]"
        item = object_value(raw, item_where)
        only_keys(
            item,
            {"task_id", "state", "outcome", "attempt", "fence", "blocker_codes"},
            item_where,
        )
        result.append(
            WorkflowTaskProjection(
                task_id=_task_id(item.get("task_id"), f"{item_where}.task_id"),
                state=enum_value(TaskState, item.get("state"), f"{item_where}.state"),
                outcome=enum_value(TaskOutcome, item.get("outcome"), f"{item_where}.outcome"),
                attempt=integer_value(
                    item.get("attempt"), f"{item_where}.attempt", minimum=0, maximum=1024
                ),
                fence=integer_value(
                    item.get("fence"), f"{item_where}.fence", minimum=0, maximum=2_147_483_647
                ),
                blocker_codes=_sorted_codes(
                    item.get("blocker_codes"), f"{item_where}.blocker_codes"
                ),
            )
        )
    tasks = tuple(result)
    if tasks != tuple(sorted(tasks, key=lambda item: item.task_id)):
        raise WorkflowContractError(f"{where} must use Task ID order.")
    if len({item.task_id for item in tasks}) != len(tasks):
        raise WorkflowContractError(f"{where} contains duplicate Task IDs.")
    return tasks


def _gates(value: object, where: str) -> tuple[GateObservation, ...]:
    result: list[GateObservation] = []
    for index, raw in enumerate(array_value(value, where, maximum=4)):
        item_where = f"{where}[{index}]"
        item = object_value(raw, item_where)
        only_keys(item, {"gate_id", "status", "evidence_ids", "blocker_codes"}, item_where)
        observation = GateObservation(
            gate_id=_gate_id(item.get("gate_id"), f"{item_where}.gate_id"),
            status=enum_value(GateStatus, item.get("status"), f"{item_where}.status"),
            evidence_ids=_sorted_native_ids(item.get("evidence_ids"), f"{item_where}.evidence_ids"),
            blocker_codes=_sorted_codes(item.get("blocker_codes"), f"{item_where}.blocker_codes"),
        )
        if observation.status is GateStatus.PASS and (
            not observation.evidence_ids or observation.blocker_codes
        ):
            raise WorkflowContractError("Passing Gate requires exact evidence and no blocker.")
        if observation.status is not GateStatus.PASS and not observation.blocker_codes:
            raise WorkflowContractError("Non-passing Gate requires a blocker code.")
        result.append(observation)
    gates = tuple(result)
    if gates != tuple(sorted(gates, key=lambda item: item.gate_id)):
        raise WorkflowContractError(f"{where} must use Gate ID order.")
    if len({item.gate_id for item in gates}) != len(gates):
        raise WorkflowContractError(f"{where} contains duplicate Gates.")
    return gates


def _blockers(value: object, where: str) -> tuple[WorkflowBlocker, ...]:
    result: list[WorkflowBlocker] = []
    for index, raw in enumerate(array_value(value, where, maximum=MAX_BLOCKERS)):
        item_where = f"{where}[{index}]"
        item = object_value(raw, item_where)
        only_keys(item, {"code", "references"}, item_where)
        result.append(
            WorkflowBlocker(
                code=_code(item.get("code"), f"{item_where}.code"),
                references=_sorted_native_or_workflow_ids(
                    item.get("references"), f"{item_where}.references"
                ),
            )
        )
    blockers = tuple(result)
    expected = tuple(sorted(blockers, key=lambda item: (item.code, item.references)))
    if blockers != expected or len({repr(item.to_dict()) for item in blockers}) != len(blockers):
        raise WorkflowContractError(f"{where} must be unique and deterministically ordered.")
    return blockers


def _measurements(value: object, where: str) -> tuple[WorkflowMeasurement, ...]:
    result: list[WorkflowMeasurement] = []
    for index, raw in enumerate(array_value(value, where, maximum=512)):
        item_where = f"{where}[{index}]"
        item = object_value(raw, item_where)
        only_keys(item, {"name", "status", "value", "unit", "source_ids"}, item_where)
        name = string_value(item.get("name"), f"{item_where}.name", maximum=128)
        if not _MEASUREMENT.fullmatch(name):
            raise WorkflowContractError(f"{item_where}.name is unsupported.")
        status = enum_value(MeasurementStatus, item.get("status"), f"{item_where}.status")
        raw_value = item.get("value")
        if raw_value is not None and (
            isinstance(raw_value, bool) or not isinstance(raw_value, (int, str))
        ):
            raise WorkflowContractError(f"{item_where}.value is unsupported.")
        measured: int | str | None
        if isinstance(raw_value, str):
            measured = path_free_text(raw_value, f"{item_where}.value", maximum=128)
        else:
            measured = raw_value
        unit = _optional_code(item.get("unit"), f"{item_where}.unit")
        if status is MeasurementStatus.NOT_AVAILABLE and (measured is not None or unit is not None):
            raise WorkflowContractError("Unavailable measurement cannot claim a value or unit.")
        if status is MeasurementStatus.OBSERVED and measured is None:
            raise WorkflowContractError("Observed measurement requires an exact value.")
        result.append(
            WorkflowMeasurement(
                name=name,
                status=status,
                value=measured,
                unit=unit,
                source_ids=_sorted_native_or_workflow_ids(
                    item.get("source_ids"), f"{item_where}.source_ids"
                ),
            )
        )
    measurements = tuple(result)
    if tuple(item.name for item in measurements) != WORKFLOW_MEASUREMENT_NAMES:
        raise WorkflowContractError(
            f"{where} must contain the exact 52 measurements in canonical group order."
        )
    return measurements


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
    agents = integer_value(item.get("max_agents"), f"{where}.max_agents", minimum=1, maximum=16)
    concurrency = integer_value(
        item.get("max_concurrency"), f"{where}.max_concurrency", minimum=1, maximum=16
    )
    if concurrency > agents:
        raise WorkflowContractError(f"{where}.max_concurrency exceeds max_agents.")
    reasoning = string_value(
        item.get("max_reasoning_effort"), f"{where}.max_reasoning_effort", maximum=6
    )
    if reasoning not in {"low", "medium", "high"}:
        raise WorkflowContractError(f"{where}.max_reasoning_effort is unsupported.")
    cost = object_value(item.get("cost"), f"{where}.cost")
    only_keys(cost, {"status", "currency", "max_microunits"}, f"{where}.cost")
    status = string_value(cost.get("status"), f"{where}.cost.status", maximum=20)
    if status not in {"available", "not_available"}:
        raise WorkflowContractError(f"{where}.cost.status is unsupported.")
    currency_raw = cost.get("currency")
    currency = (
        None
        if currency_raw is None
        else string_value(currency_raw, f"{where}.cost.currency", maximum=3)
    )
    if currency is not None and not _CURRENCY.fullmatch(currency):
        raise WorkflowContractError(f"{where}.cost.currency is invalid.")
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
        raise WorkflowContractError(f"{where}.cost available requires currency and limit.")
    if status == "not_available" and (currency is not None or amount is not None):
        raise WorkflowContractError(f"{where}.cost unavailable cannot claim values.")
    return SchedulerBudget(
        max_agents=agents,
        max_concurrency=concurrency,
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
            item.get("max_solver_steps"),
            f"{where}.max_solver_steps",
            minimum=0,
            maximum=2_147_483_647,
        ),
        cost_status=status,
        currency=currency,
        max_microunits=amount,
    )


def _validate_intent_profile(intent: DevelopmentIntent) -> None:
    expected = {
        CompletionProfile.PLAN_ONLY: ("G1",),
        CompletionProfile.IMPLEMENTATION_VERIFIED: ("G1", "G2"),
        CompletionProfile.INDEPENDENT_REVIEW_ACCEPTED: ("G1", "G2", "G3"),
        CompletionProfile.RELEASE_CANDIDATE_READY: ("G1", "G2", "G3", "G4"),
    }[intent.completion_profile]
    if intent.required_gate_ids != expected:
        raise WorkflowContractError("Intent Gate set does not match its completion profile.")
    if (
        intent.ui_required
        and intent.completion_profile is not CompletionProfile.RELEASE_CANDIDATE_READY
    ):
        raise WorkflowContractError("UI-required Intent must use release-candidate-ready profile.")


def _validate_plan_profile(plan: IntegratedPlan) -> None:
    expected = {
        CompletionProfile.PLAN_ONLY: ("G1",),
        CompletionProfile.IMPLEMENTATION_VERIFIED: ("G1", "G2"),
        CompletionProfile.INDEPENDENT_REVIEW_ACCEPTED: ("G1", "G2", "G3"),
        CompletionProfile.RELEASE_CANDIDATE_READY: ("G1", "G2", "G3", "G4"),
    }[plan.completion_profile]
    if plan.required_gate_ids != expected:
        raise WorkflowContractError("Plan Gate set does not match its completion profile.")
    if (
        plan.ui_required
        and plan.completion_profile is not CompletionProfile.RELEASE_CANDIDATE_READY
    ):
        raise WorkflowContractError("UI-required Plan must use release-candidate-ready profile.")


def _native_id(value: object, where: str) -> str:
    text = string_value(value, where, maximum=192)
    if not _NATIVE_ID.fullmatch(text):
        raise WorkflowContractError(f"{where} is not a stable native identity.")
    return text


def _native_or_workflow_id(value: object, where: str) -> str:
    text = string_value(value, where, maximum=192)
    if not (_NATIVE_ID.fullmatch(text) or _WORKFLOW_ID.fullmatch(text)):
        raise WorkflowContractError(f"{where} is not a stable identity.")
    return text


def _optional_native_id(value: object, where: str) -> str | None:
    return None if value is None else _native_id(value, where)


def _optional_workflow_id(
    value: object,
    where: str,
    artifact_type: WorkflowArtifactType,
) -> str | None:
    return None if value is None else workflow_id(value, where, expected_type=artifact_type)


def _optional_pattern_id(value: object, where: str, pattern: re.Pattern[str]) -> str | None:
    if value is None:
        return None
    text = string_value(value, where, maximum=128)
    if not pattern.fullmatch(text):
        raise WorkflowContractError(f"{where} is invalid.")
    return text


def _optional_code(value: object, where: str) -> str | None:
    return None if value is None else _code(value, where)


def _code(value: object, where: str) -> str:
    text = string_value(value, where, maximum=96)
    if not _CODE.fullmatch(text):
        raise WorkflowContractError(f"{where} must be a stable lowercase code.")
    return text


def _task_id(value: object, where: str) -> str:
    text = string_value(value, where, maximum=68)
    if not _TASK_ID.fullmatch(text):
        raise WorkflowContractError(f"{where} must be a stable Task ID.")
    return text


def _baseline_id(value: object, where: str) -> str:
    text = string_value(value, where, maximum=19)
    if not _BASELINE_ID.fullmatch(text):
        raise WorkflowContractError(f"{where} must be a stable Requirement Baseline ID.")
    return text


def _gate_id(value: object, where: str) -> str:
    text = string_value(value, where, maximum=2)
    if not _GATE_ID.fullmatch(text):
        raise WorkflowContractError(f"{where} must be one of G1 through G4.")
    return text


def _gate_ids(value: object, where: str) -> tuple[str, ...]:
    items = string_tuple(value, where, minimum=1, maximum=4)
    if items != tuple(sorted(items)) or any(not _GATE_ID.fullmatch(item) for item in items):
        raise WorkflowContractError(f"{where} must contain sorted unique G1-G4 IDs.")
    return items


def _sorted_paths(value: object, where: str) -> tuple[str, ...]:
    result = tuple(
        safe_relative_path(item, f"{where}[{index}]")
        for index, item in enumerate(array_value(value, where, maximum=MAX_REFERENCES))
    )
    portable = tuple(
        "/".join(part.casefold() for part in PurePosixPath(item).parts) for item in result
    )
    if result != tuple(sorted(set(result))) or len(set(portable)) != len(portable):
        raise WorkflowContractError(
            f"{where} must be sorted, unique, and free of portable case collisions."
        )
    return result


def _sorted_pattern_ids(value: object, where: str) -> tuple[str, ...]:
    result = string_tuple(value, where, maximum=MAX_REFERENCES)
    if result != tuple(sorted(result)) or any(
        not _REQUIREMENT_ID.fullmatch(item) for item in result
    ):
        raise WorkflowContractError(f"{where} must contain sorted stable IDs.")
    return result


def _sorted_task_ids(value: object, where: str) -> tuple[str, ...]:
    result = string_tuple(value, where, maximum=MAX_TASKS)
    if result != tuple(sorted(result)) or any(not _TASK_ID.fullmatch(item) for item in result):
        raise WorkflowContractError(f"{where} must contain sorted Task IDs.")
    return result


def _sorted_codes(
    value: object,
    where: str,
    *,
    minimum: int = 0,
    maximum: int = 256,
) -> tuple[str, ...]:
    result = string_tuple(value, where, minimum=minimum, maximum=maximum)
    if result != tuple(sorted(result)) or any(not _CODE.fullmatch(item) for item in result):
        raise WorkflowContractError(f"{where} must contain sorted stable codes.")
    return result


def _sorted_native_ids(value: object, where: str) -> tuple[str, ...]:
    result = string_tuple(value, where, maximum=MAX_REFERENCES)
    if result != tuple(sorted(result)) or any(not _NATIVE_ID.fullmatch(item) for item in result):
        raise WorkflowContractError(f"{where} must contain sorted native IDs.")
    return result


def _sorted_native_or_workflow_ids(value: object, where: str) -> tuple[str, ...]:
    result = string_tuple(value, where, maximum=MAX_REFERENCES)
    if result != tuple(sorted(result)) or any(
        not (_NATIVE_ID.fullmatch(item) or _WORKFLOW_ID.fullmatch(item)) for item in result
    ):
        raise WorkflowContractError(f"{where} must contain sorted stable IDs.")
    return result


def _sorted_workflow_ids(
    value: object,
    where: str,
    artifact_type: WorkflowArtifactType,
) -> tuple[str, ...]:
    result = string_tuple(value, where, minimum=1, maximum=MAX_REFERENCES)
    if result != tuple(sorted(result)):
        raise WorkflowContractError(f"{where} must be sorted and unique.")
    for index, item in enumerate(result):
        workflow_id(item, f"{where}[{index}]", expected_type=artifact_type)
    return result


def _sorted_enums[E: EffectKind](
    enum_type: type[E],
    value: object,
    where: str,
    *,
    maximum: int,
) -> tuple[E, ...]:
    result = tuple(
        enum_value(enum_type, item, f"{where}[{index}]")
        for index, item in enumerate(array_value(value, where, maximum=maximum))
    )
    if result != tuple(sorted(set(result), key=lambda item: item.value)):
        raise WorkflowContractError(f"{where} must be sorted and unique.")
    return result


def _utc_timestamp(value: object, where: str) -> str:
    text = string_value(value, where, maximum=32)
    if not _RFC3339_UTC.fullmatch(text):
        raise WorkflowContractError(f"{where} must be canonical UTC Z time.")
    try:
        parsed = datetime.fromisoformat(text.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise WorkflowContractError(f"{where} must be a real UTC instant.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise WorkflowContractError(f"{where} must be UTC.")
    return text


def _reject_unrepresentable_secret_content(
    sensitivity: Sensitivity,
    objective: str,
) -> None:
    if sensitivity is Sensitivity.SECRET_OR_PROHIBITED and objective != "[REDACTED]":
        raise WorkflowContractError(
            "Secret-or-prohibited Intent may retain only a non-disclosing redaction marker."
        )
