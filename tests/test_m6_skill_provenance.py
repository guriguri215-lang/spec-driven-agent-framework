"""Exact M2 Skill provenance across accepted M6 results and M8 bindings."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

import sdaqf.application.scheduler_contracts as scheduler_contracts_module
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    SchedulerContractError,
    load_scheduler_artifact,
    load_task_agent_result,
    serialize_scheduler_artifact,
    validate_task_graph_inputs,
    validate_task_result_reference,
)
from sdaqf.application.scheduler_contracts import (
    artifact_from_value as scheduler_artifact_from_value,
)
from sdaqf.application.skills import (
    resolve_skill_capabilities,
    skill_capability_token,
    validate_skills,
)
from sdaqf.application.workflow_contracts import (
    LoadedWorkflowArtifact,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_contracts import (
    artifact_from_value as workflow_artifact_from_value,
)
from sdaqf.application.workflow_planning import artifact_reference_for
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.scheduler import (
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerState,
    TaskGraph,
    TaskState,
)
from sdaqf.domain.workflow import (
    CompletionProfile,
    DevelopmentIntent,
    IntegratedPlan,
    WorkflowArtifactType,
    WorkflowState,
)
from tests.m8_workflow_helpers import (
    ACCEPTANCE_ID,
    FIXED_TIME,
    REQUIREMENT_ID,
    FixedClock,
    create_intent,
    create_planner,
    create_runtime,
    create_scheduler,
    create_workspace,
)

ROOT = Path(__file__).resolve().parents[1]
HOST_ID = "HST-SKILL-TEST"


@dataclass(frozen=True, slots=True)
class SkillCase:
    root: Path
    graph_artifact: LoadedSchedulerArtifact
    graph: TaskGraph
    token: str
    skill_path: Path
    skill_reference: ArtifactReference


def test_task_graph_preflight_reserves_one_provenance_slot_for_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    graph = load_scheduler_artifact(
        root / "examples/m6-scheduler/task-graph.json",
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )

    monkeypatch.setattr(
        scheduler_contracts_module,
        "resolve_skill_capabilities",
        lambda _root, _capabilities: tuple(object() for _ in range(63)),
    )
    validate_task_graph_inputs(graph, root)

    monkeypatch.setattr(
        scheduler_contracts_module,
        "resolve_skill_capabilities",
        lambda _root, _capabilities: tuple(object() for _ in range(64)),
    )
    with pytest.raises(SchedulerContractError, match="at most 63 exact Skills"):
        validate_task_graph_inputs(graph, root)


def test_skill_result_with_exact_context_and_skill_provenance_is_accepted(
    tmp_path: Path,
) -> None:
    case = _create_skill_case(tmp_path)
    store, dispatch = _start_skill_task(case)
    provenance = (case.graph.contexts[0].reference, case.skill_reference)
    dispatch_message = dispatch.value
    assert isinstance(dispatch_message, MailboxMessage)
    assert dispatch_message.provenance == provenance
    result = _task_result(case.root, dispatch, provenance)

    tick = store.tick(case.root, HOST_ID, (result,), FIXED_TIME)

    state = tick.state.value
    assert isinstance(state, SchedulerState)
    assert tick.accepted_message_ids == (result.artifact_id,)
    assert state.tasks[0].state is TaskState.COMPLETED


def test_skill_result_rejects_missing_provenance_and_skill_digest_drift(
    tmp_path: Path,
) -> None:
    case = _create_skill_case(tmp_path)
    store, dispatch = _start_skill_task(case)
    context_only = (case.graph.contexts[0].reference,)

    with pytest.raises(SchedulerContractError, match="provenance"):
        store.tick(
            case.root,
            HOST_ID,
            (_task_result(case.root, dispatch, context_only),),
            FIXED_TIME,
        )
    state = store.status().value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].state is TaskState.RUNNING

    case.skill_path.write_text(
        case.skill_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    exact_old_provenance = (case.graph.contexts[0].reference, case.skill_reference)
    with pytest.raises(SchedulerContractError, match="Skill capability"):
        store.tick(
            case.root,
            HOST_ID,
            (_task_result(case.root, dispatch, exact_old_provenance),),
            FIXED_TIME,
        )
    with pytest.raises(SchedulerContractError, match="Skill capability"):
        store.status()


def test_stale_skill_is_rejected_before_scheduler_dispatch(tmp_path: Path) -> None:
    case = _create_skill_case(tmp_path)
    case.skill_path.write_text(
        case.skill_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SchedulerContractError, match="Task Skill capability"):
        create_scheduler(case.root)


def test_non_skill_result_preserves_existing_context_only_contract(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    graph_artifact = load_scheduler_artifact(
        root / "examples/m6-scheduler/task-graph.json",
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    scheduler = create_scheduler(root)
    store = SQLiteSchedulerStore(scheduler, root)
    tick = store.tick(root, HOST_ID, (), FIXED_TIME)
    assert len(tick.outgoing) == 1
    dispatch = tick.outgoing[0]
    message = dispatch.value
    assert isinstance(message, MailboxMessage)
    assert len(message.provenance) == 1

    result = _task_result(root, dispatch, message.provenance)
    completed = store.tick(root, HOST_ID, (result,), FIXED_TIME)

    graph = graph_artifact.value
    state = completed.state.value
    assert isinstance(graph, TaskGraph)
    assert isinstance(state, SchedulerState)
    assert graph.tasks[0].required_capabilities == ()
    assert completed.accepted_message_ids == (result.artifact_id,)
    assert state.tasks[0].state is TaskState.COMPLETED


def test_task_agent_result_loader_fails_closed_on_every_exact_binding(
    tmp_path: Path,
) -> None:
    case = _create_skill_case(tmp_path)
    _store, dispatch = _start_skill_task(case)
    provenance = (case.graph.contexts[0].reference, case.skill_reference)
    result_artifact = _task_result(case.root, dispatch, provenance)
    result_message = result_artifact.value
    dispatch_message = dispatch.value
    assert isinstance(result_message, MailboxMessage)
    assert isinstance(dispatch_message, MailboxMessage)

    result, reference = load_task_agent_result(
        case.root,
        case.graph,
        result_message,
    )
    assert result.role_id == case.graph.tasks[0].role_id
    assert reference == _agent_result_reference(case.root)
    assert validate_task_result_reference(case.root, case.graph, dispatch_message) is None

    with pytest.raises(SchedulerContractError, match="not a Task Result"):
        load_task_agent_result(case.root, case.graph, dispatch_message)
    with pytest.raises(SchedulerContractError, match="current Task Graph"):
        load_task_agent_result(
            case.root,
            case.graph,
            replace(result_message, graph_id="M6-TASK-GRAPH-" + "0" * 64),
        )
    with pytest.raises(SchedulerContractError, match="unknown task"):
        load_task_agent_result(
            case.root,
            case.graph,
            replace(result_message, task_id="TSK-UNKNOWN"),
        )

    invalid_reference = replace(_agent_result_reference(case.root), sha256="0" * 64)
    with pytest.raises(SchedulerContractError, match="identity is invalid"):
        load_task_agent_result(
            case.root,
            case.graph,
            _replace_agent_result_reference(result_message, invalid_reference),
        )

    malformed_path = case.root / "workflow/malformed-agent-result.json"
    malformed_content = b"{}\n"
    malformed_path.write_bytes(malformed_content)
    malformed_reference = ArtifactReference(
        malformed_path.relative_to(case.root).as_posix(),
        hashlib.sha256(malformed_content).hexdigest().upper(),
    )
    with pytest.raises(SchedulerContractError, match="Agent Result is invalid"):
        load_task_agent_result(
            case.root,
            case.graph,
            _replace_agent_result_reference(result_message, malformed_reference),
        )

    result_path = case.root / "examples/m2-orchestration/implementer-result.json"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["role_id"] = "test-implementer"
    result_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SchedulerContractError, match="role does not match"):
        load_task_agent_result(
            case.root,
            case.graph,
            _replace_agent_result_reference(
                result_message,
                _agent_result_reference(case.root),
            ),
        )

    payload["role_id"] = "implementer"
    payload["status"] = "blocked"
    result_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SchedulerContractError, match="status contradicts"):
        load_task_agent_result(
            case.root,
            case.graph,
            _replace_agent_result_reference(
                result_message,
                _agent_result_reference(case.root),
            ),
        )


def test_m8_state_retains_accepted_agent_result_and_skill_bindings(
    tmp_path: Path,
) -> None:
    case = _create_skill_case(tmp_path)
    plan_artifact, scheduler = _create_implementation_plan(case.root, case.token)
    plan = plan_artifact.value
    assert isinstance(plan, IntegratedPlan)
    store, dispatch = _start_skill_task(case)
    ledger_reference = _write_candidate_ledger(case.root, plan)
    agent_reference = _agent_result_reference(case.root)
    provenance = (case.graph.contexts[0].reference, case.skill_reference)
    result = _task_result(
        case.root,
        dispatch,
        provenance,
        evidence=(ledger_reference,),
    )
    completed = store.tick(case.root, HOST_ID, (result,), FIXED_TIME)
    assert completed.accepted_message_ids == (result.artifact_id,)

    transition = create_runtime(FixedClock()).run(
        plan_artifact,
        case.root,
        scheduler,
        case.root / "workflow/skill-state.json",
        case.root / "workflow/skill-event.json",
    )

    state = transition.state.value
    assert isinstance(state, WorkflowState)
    agent_binding = next(
        item for item in state.observation_artifacts if item.artifact_type == "agent-result"
    )
    skill_binding = next(
        item for item in state.observation_artifacts if item.artifact_type == "skill"
    )
    assert agent_binding.reference == agent_reference
    assert skill_binding.reference == case.skill_reference
    assert agent_binding.artifact_id == f"M2-AGENT-RESULT-{agent_reference.sha256}"
    assert skill_binding.artifact_id == f"M2-SKILL-{case.skill_reference.sha256}"


def _create_skill_case(tmp_path: Path) -> SkillCase:
    root = create_workspace(tmp_path)
    skill_source = ROOT / ".agents/skills/independent-review/SKILL.md"
    skill_path = root / ".agents/skills/independent-review/SKILL.md"
    skill_path.parent.mkdir(parents=True)
    shutil.copy2(skill_source, skill_path)
    lifecycle = validate_skills(root / ".agents/skills")[0]
    token = skill_capability_token(lifecycle)
    resolved = resolve_skill_capabilities(root, (token,))[0]

    graph_path = root / "examples/m6-scheduler/task-graph.json"
    original = load_scheduler_artifact(
        graph_path,
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    graph = original.value
    assert isinstance(graph, TaskGraph)
    graph = replace(
        graph,
        tasks=(replace(graph.tasks[0], required_capabilities=(token,)),),
    )
    graph_artifact = scheduler_artifact_from_value(
        SchedulerArtifactType.TASK_GRAPH,
        graph,
    )
    graph_path.write_bytes(serialize_scheduler_artifact(graph_artifact))
    return SkillCase(
        root=root,
        graph_artifact=graph_artifact,
        graph=graph,
        token=token,
        skill_path=skill_path,
        skill_reference=resolved.reference,
    )


def _start_skill_task(
    case: SkillCase,
) -> tuple[SQLiteSchedulerStore, LoadedSchedulerArtifact]:
    scheduler = create_scheduler(case.root)
    store = SQLiteSchedulerStore(scheduler, case.root)
    observation = scheduler_artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.CAPABILITY_OBSERVATION,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender=HOST_ID,
            recipient="HST-SCHEDULER",
            graph_id=case.graph_artifact.artifact_id,
            task_id=None,
            candidate=case.graph.candidate,
            context_snapshot_id=None,
            attempt=None,
            lease_id=None,
            fence=None,
            idempotency_key=None,
            sensitivity=Sensitivity.PUBLIC,
            provenance=(),
            causal_parent_message_ids=(),
            recorded_at=FIXED_TIME.isoformat(timespec="seconds").replace("+00:00", "Z"),
            payload={"capabilities": [case.token]},
        ),
    )
    tick = store.tick(case.root, HOST_ID, (observation,), FIXED_TIME)
    assert tick.accepted_message_ids == (observation.artifact_id,)
    assert len(tick.outgoing) == 1
    return store, tick.outgoing[0]


def _task_result(
    root: Path,
    dispatch_artifact: LoadedSchedulerArtifact,
    provenance: tuple[ArtifactReference, ...],
    *,
    evidence: tuple[ArtifactReference, ...] | None = None,
) -> LoadedSchedulerArtifact:
    dispatch = dispatch_artifact.value
    assert isinstance(dispatch, MailboxMessage)
    agent_reference = _agent_result_reference(root)
    evidence_references = (agent_reference,) if evidence is None else evidence
    return scheduler_artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(
            dispatch,
            message_type=MessageType.TASK_RESULT,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender=HOST_ID,
            recipient="HST-SCHEDULER",
            provenance=provenance,
            causal_parent_message_ids=(dispatch_artifact.artifact_id,),
            payload={
                "agent_result": agent_reference.to_dict(),
                "outcome": "succeeded",
                "effect_observed": "none",
                "evidence_refs": [item.to_dict() for item in evidence_references],
                "budget_usage": {
                    "microunits": 0,
                    "solver_calls": 0,
                    "solver_steps": 0,
                    "tool_calls": 0,
                },
            },
        ),
    )


def _agent_result_reference(root: Path) -> ArtifactReference:
    relative = Path("examples/m2-orchestration/implementer-result.json")
    return ArtifactReference(
        relative.as_posix(),
        hashlib.sha256((root / relative).read_bytes()).hexdigest().upper(),
    )


def _replace_agent_result_reference(
    message: MailboxMessage,
    reference: ArtifactReference,
) -> MailboxMessage:
    return replace(
        message,
        payload={**message.payload, "agent_result": reference.to_dict()},
    )


def _create_implementation_plan(
    root: Path,
    skill_token: str,
) -> tuple[LoadedWorkflowArtifact, Path]:
    intent_artifact, intent_path = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    implementation_intent = workflow_artifact_from_value(
        WorkflowArtifactType.DEVELOPMENT_INTENT,
        replace(
            intent,
            completion_profile=CompletionProfile.IMPLEMENTATION_VERIFIED,
            required_gate_ids=("G1", "G2"),
            capabilities=(skill_token,),
        ),
    )
    intent_path.write_bytes(serialize_workflow_artifact(implementation_intent))
    scheduler = create_scheduler(root)
    plan = create_planner().publish_plan(
        implementation_intent,
        artifact_reference_for(root, intent_path),
        root,
        scheduler,
        root / "workflow/skill-plan.json",
        recorded_at=FIXED_TIME,
    )
    return plan, scheduler


def _write_candidate_ledger(root: Path, plan: IntegratedPlan) -> ArtifactReference:
    payload = json.loads(
        (ROOT / "examples/m3-quality/claim-evidence-ledger.json").read_text(
            encoding="utf-8"
        )
    )
    payload["baseline_id"] = plan.requirement_baseline_id
    payload["source_spec_sha256"] = plan.candidate.source_spec_sha256
    payload["git_head"] = plan.candidate.git_head
    payload["repository_digest"] = plan.candidate.repository_digest
    payload["claims"][0]["requirement_ids"] = [REQUIREMENT_ID]
    payload["claims"][0]["acceptance_criteria"] = [ACCEPTANCE_ID]
    for evidence in payload["evidence"]:
        evidence["commit"] = plan.candidate.git_head
        evidence["repository_digest"] = plan.candidate.repository_digest
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    relative = Path("workflow/skill-evidence-ledger.json")
    (root / relative).write_bytes(content)
    return ArtifactReference(
        relative.as_posix(),
        hashlib.sha256(content).hexdigest().upper(),
    )
