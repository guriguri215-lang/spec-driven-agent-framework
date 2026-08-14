"""One production-path closeout flow across M2, M3, M6, M7, and M8."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

import sdaqf.adapters.scheduler as scheduler_adapter_module
import sdaqf.application.quality_gates as quality_gates_module
import sdaqf.application.scheduler_contracts as scheduler_contracts_module
import sdaqf.cli as cli_module
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.evidence import load_evidence_ledger
from sdaqf.application.handoffs import HandoffService
from sdaqf.application.scheduler import SchedulerService
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    load_scheduler_artifact,
    serialize_scheduler_artifact,
)
from sdaqf.application.scheduler_contracts import (
    artifact_from_value as scheduler_artifact_from_value,
)
from sdaqf.application.skills import (
    resolve_skill_capabilities,
    skill_capability_token,
    validate_skills,
)
from sdaqf.application.solver import SolverService
from sdaqf.application.solver_contracts import (
    REFERENCE_ADAPTER_ID,
    operational_contract_id,
    serialize_solver_artifact,
    solver_capability_token,
)
from sdaqf.application.solver_contracts import (
    artifact_from_value as solver_artifact_from_value,
)
from sdaqf.application.solver_verification import SolverVerificationService
from sdaqf.application.workflow_contracts import (
    LoadedWorkflowArtifact,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_contracts import (
    artifact_from_value as workflow_artifact_from_value,
)
from sdaqf.application.workflow_explanation import (
    ClaimConclusion,
    EpistemicClassification,
    WorkflowFinalReportError,
    WorkflowFinalReportService,
    WorkflowReportSourceKind,
)
from sdaqf.application.workflow_planning import artifact_reference_for
from sdaqf.cli import main
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.quality import ArtifactReference, EvidenceLedger, GitObservation
from sdaqf.domain.scheduler import (
    EffectKind,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    TaskGraph,
    TaskKind,
    TaskState,
)
from sdaqf.domain.scheduler import (
    SchedulerState as NativeSchedulerState,
)
from sdaqf.domain.solver import (
    LoadedSolverArtifact,
    SolverArtifactType,
    SolverRequest,
    SolverRequiredClaim,
    SolverResourcePolicy,
    SolverResult,
    SolverVerification,
    SolverVerificationOutcome,
)
from sdaqf.domain.workflow import (
    CompletionProfile,
    DevelopmentIntent,
    IntegratedPlan,
    IntentTaskLink,
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowState,
)
from tests.m6_scheduler_helpers import host_message
from tests.m7_solver_helpers import (
    FIXED_TIME as CLOSEOUT_TIME,
)
from tests.m7_solver_helpers import reference_registry, scheduling_problem
from tests.m8_workflow_helpers import (
    ACCEPTANCE_ID,
    REQUIREMENT_ID,
    ROOT,
    FixedClock,
    create_intent,
    create_outcome,
    create_planner,
    create_runtime,
    create_workspace,
    workflow_binding,
)
from tests.test_m6_skill_provenance import _write_candidate_ledger

HOST_ID = "HST-CLOSEOUT-E2E"
IMPLEMENTER_TASK = "TSK-CLOSEOUT-01-IMPLEMENTER"
SOLVER_TASK = "TSK-CLOSEOUT-02-SOLVER"
REVIEWER_TASK = "TSK-CLOSEOUT-03-REVIEWER"
HANDOFF_TASK = "TSK-CLOSEOUT-04-HANDOFF"
IMPLEMENTER_AGENT = "AGT-CLOSEOUT-IMPLEMENTER"
SOLVER_AGENT = "AGT-CLOSEOUT-SOLVER"
REVIEWER_AGENT = "AGT-CLOSEOUT-REVIEWER"
HANDOFF_AGENT = "AGT-CLOSEOUT-HANDOFF"
DISAGREEMENT_ID = "FND-CLOSEOUT-DISAGREEMENT"


@dataclass(frozen=True, slots=True)
class CloseoutCase:
    """Exact paths and artifacts needed by the one closeout execution."""

    root: Path
    graph_path: Path
    scheduler_path: Path
    plan: LoadedWorkflowArtifact
    plan_path: Path
    registry_path: Path
    request_path: Path
    review_skill_reference: ArtifactReference
    review_skill_token: str
    handoff_skill_reference: ArtifactReference
    handoff_skill_token: str
    solver_token: str


def test_closeout_e2e_preserves_authority_and_epistemic_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = _create_case(tmp_path)
    plan = case.plan.value
    assert isinstance(plan, IntegratedPlan)
    store = SQLiteSchedulerStore(case.scheduler_path, case.root)
    ledger_reference = _write_candidate_ledger(case.root, plan)
    ledger = load_evidence_ledger(case.root / ledger_reference.path)

    tick = store.tick(
        case.root,
        HOST_ID,
        (_capability_observation(case),),
        CLOSEOUT_TIME + timedelta(seconds=1),
    )
    implementer_dispatch = _only_dispatch(tick.outgoing, IMPLEMENTER_TASK)
    _assert_context_only_provenance(implementer_dispatch)
    implementer_result = _write_agent_result(
        case.root,
        "implementer-result.json",
        agent_id=IMPLEMENTER_AGENT,
        role_id="implementer",
        finding_id=DISAGREEMENT_ID,
        statement="The bounded implementation evidence is sufficient.",
        evidence_refs=(ledger_reference.path,),
    )
    stale_implementer_result = _write_agent_result(
        case.root,
        "stale-implementer-result.json",
        agent_id=IMPLEMENTER_AGENT,
        role_id="implementer",
        finding_id="FND-CLOSEOUT-STALE",
        statement="This same-agent result was not accepted by M6.",
        evidence_refs=(ledger_reference.path,),
    )
    tick = store.tick(
        case.root,
        HOST_ID,
        (
            _task_result(
                implementer_dispatch,
                implementer_result,
                (ledger_reference,),
                clock_offset=2,
            ),
        ),
        CLOSEOUT_TIME + timedelta(seconds=2),
    )

    solver_dispatch = _only_dispatch(tick.outgoing, SOLVER_TASK)
    _assert_context_only_provenance(solver_dispatch)
    solver_message = cast(MailboxMessage, solver_dispatch.value)
    assert solver_message.lease_id is not None
    acknowledgement = host_message(
        solver_dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": True, "effect_observed": "none", "note": None},
        clock=CLOSEOUT_TIME + timedelta(seconds=3),
        sender=HOST_ID,
    )
    acknowledged = store.tick(
        case.root,
        HOST_ID,
        (acknowledgement,),
        CLOSEOUT_TIME + timedelta(seconds=3),
    )
    assert acknowledged.accepted_message_ids == (acknowledgement.artifact_id,)
    result_path = case.root / "workflow/closeout-solver-result.json"
    verification_path = case.root / "workflow/closeout-solver-verification.json"
    solver_result = SolverService().run(
        case.request_path,
        case.registry_path,
        case.graph_path,
        case.scheduler_path,
        case.root,
        HOST_ID,
        solver_message.lease_id,
        result_path,
    )
    solver_verification = SolverVerificationService().verify(
        result_path,
        case.request_path,
        case.registry_path,
        case.graph_path,
        case.scheduler_path,
        case.root,
        HOST_ID,
        solver_message.lease_id,
        verification_path,
    )
    verification_value = solver_verification.value
    assert isinstance(verification_value, SolverVerification)
    assert verification_value.outcome is SolverVerificationOutcome.VERIFIED
    assert verification_value.adoption_allowed
    solver_agent_result = _write_agent_result(
        case.root,
        "solver-agent-result.json",
        agent_id=SOLVER_AGENT,
        role_id="implementer",
        finding_id="FND-CLOSEOUT-SOLVER",
        statement="The exact finite-domain result was independently verified.",
        evidence_refs=(
            result_path.relative_to(case.root).as_posix(),
            verification_path.relative_to(case.root).as_posix(),
        ),
    )
    tick = store.tick(
        case.root,
        HOST_ID,
        (
            _solver_task_result(
                solver_dispatch,
                solver_agent_result,
                solver_result,
                solver_verification,
                case.root,
                result_path,
                verification_path,
            ),
        ),
        CLOSEOUT_TIME + timedelta(seconds=4),
    )

    reviewer_dispatch = _only_dispatch(tick.outgoing, REVIEWER_TASK)
    _assert_exact_skill_provenance(
        reviewer_dispatch,
        case.review_skill_reference,
    )
    review_path = _write_independent_review(case.root, plan)
    reviewer_result = _write_agent_result(
        case.root,
        "reviewer-result.json",
        agent_id=REVIEWER_AGENT,
        role_id="independent-reviewer",
        finding_id=DISAGREEMENT_ID,
        statement="The bounded implementation evidence remains insufficient.",
        evidence_refs=(review_path.relative_to(case.root).as_posix(),),
        reviewed_agent_ids=(IMPLEMENTER_AGENT,),
    )
    tick = store.tick(
        case.root,
        HOST_ID,
        (
            _task_result(
                reviewer_dispatch,
                reviewer_result,
                tuple(
                    sorted(
                        (_reference(case.root, review_path), implementer_result),
                        key=lambda item: (item.path, item.sha256),
                    )
                ),
                clock_offset=5,
            ),
        ),
        CLOSEOUT_TIME + timedelta(seconds=5),
    )

    handoff_dispatch = _only_dispatch(tick.outgoing, HANDOFF_TASK)
    _assert_exact_skill_provenance(
        handoff_dispatch,
        case.handoff_skill_reference,
    )
    handoff_path = _write_handoff(case.root, plan, ledger)
    handoff_result = _write_agent_result(
        case.root,
        "handoff-agent-result.json",
        agent_id=HANDOFF_AGENT,
        role_id="implementer",
        finding_id="FND-CLOSEOUT-HANDOFF",
        statement="The exact handoff contains no unfinished item.",
        evidence_refs=(handoff_path.relative_to(case.root).as_posix(),),
    )
    finished = store.tick(
        case.root,
        HOST_ID,
        (
            _task_result(
                handoff_dispatch,
                handoff_result,
                (_reference(case.root, handoff_path),),
                clock_offset=6,
            ),
        ),
        CLOSEOUT_TIME + timedelta(seconds=6),
    )
    assert finished.outgoing == ()
    native = store.status().value
    assert isinstance(native, NativeSchedulerState)
    assert all(task.state is TaskState.COMPLETED for task in native.tasks)
    assert len(store.completed_task_result_messages()) == 4

    runtime = create_runtime(FixedClock(CLOSEOUT_TIME + timedelta(seconds=7)))
    source_path = case.root / "workflow/closeout-source-state.json"
    transition = runtime.run(
        case.plan,
        case.root,
        case.scheduler_path,
        source_path,
        case.root / "workflow/closeout-source-event.json",
    )
    source_state = transition.state.value
    assert isinstance(source_state, WorkflowState)
    assert source_state.status is TaskState.COMPLETED
    assert source_state.review_ids == ("REV-CLOSEOUT-1",)
    assert source_state.handoff_status == "completed"
    assert source_state.solver_verification_ids == (
        solver_verification.artifact_id,
    )
    outcome, _terminal_event, closure = create_outcome(
        FixedClock(CLOSEOUT_TIME + timedelta(seconds=8))
    ).publish(
        transition.state,
        workflow_binding(case.root, source_path, transition.state),
        case.plan,
        case.root,
        case.scheduler_path,
        case.root / "workflow/closeout-outcome.json",
        case.root / "workflow/closeout-terminal-event.json",
        case.root / "workflow/closeout-terminal-state.json",
    )
    before_report = _tree_digests(case.root)
    report = WorkflowFinalReportService(create_planner()).report(
        outcome,
        closure,
        case.plan,
        case.root,
        case.scheduler_path,
    )

    disagreement = next(
        claim for claim in report.claims if claim.claim_id == DISAGREEMENT_ID
    )
    assert disagreement.classification is EpistemicClassification.UNKNOWN
    assert disagreement.conclusion is ClaimConclusion.UNRESOLVED
    assert {source.source_id for source in disagreement.unresolved_sources} == {
        f"{IMPLEMENTER_AGENT}:{DISAGREEMENT_ID}",
        f"{REVIEWER_AGENT}:{DISAGREEMENT_ID}",
    }
    solver_fact = next(
        claim
        for claim in report.claims
        if claim.rationale == "verified-solver-result-on-exact-lineage"
    )
    assert solver_fact.classification is EpistemicClassification.FACT
    assert solver_fact.supporting_sources[0].source_kind is (
        WorkflowReportSourceKind.PROGRAM
    )
    ledger_inference = next(
        claim
        for claim in report.claims
        if claim.rationale == "machine-evidence-recorded-but-not-independently-replayed"
    )
    assert ledger_inference.classification is EpistemicClassification.INFERENCE
    assert ledger_inference.human_review_required
    assert any(
        source.source_kind is WorkflowReportSourceKind.SKILL
        for claim in report.claims
        for source in claim.supporting_sources
    )
    assert any(
        claim.classification is EpistemicClassification.INFERENCE
        and any(
            source.source_kind is WorkflowReportSourceKind.AGENT
            for source in claim.supporting_sources
        )
        for claim in report.claims
    )
    assert report.human_review_required

    monkeypatch.setattr(cli_module, "_workflow_planner_factory", create_planner)
    assert (
        main(
            [
                "workflow",
                "report",
                str(case.root / "workflow/closeout-outcome.json"),
                "--state",
                str(case.root / "workflow/closeout-terminal-state.json"),
                "--plan",
                str(case.plan_path),
                "--root",
                str(case.root),
                "--scheduler-state",
                str(case.scheduler_path),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == report.to_dict()
    assert _tree_digests(case.root) == before_report

    accepted_messages = store.completed_task_result_messages()

    def rebound_messages(
        references: tuple[ArtifactReference, ...],
    ) -> tuple[LoadedSchedulerArtifact, ...]:
        serialized = [
            item.to_dict()
            for item in sorted(references, key=lambda item: (item.path, item.sha256))
        ]
        return tuple(
            replace(
                artifact,
                value=replace(
                    message,
                    payload={**message.payload, "evidence_refs": serialized},
                ),
            )
            if isinstance((message := artifact.value), MailboxMessage)
            and message.task_id == REVIEWER_TASK
            else artifact
            for artifact in accepted_messages
        )

    def report_store_with(
        altered: tuple[LoadedSchedulerArtifact, ...],
    ) -> type[SQLiteSchedulerStore]:
        class ReboundReportStore(SQLiteSchedulerStore):
            def completed_task_result_messages(self) -> tuple[LoadedSchedulerArtifact, ...]:
                return altered

        return ReboundReportStore

    for invalid_references in (
        (_reference(case.root, review_path),),
        (_reference(case.root, review_path), stale_implementer_result),
    ):
        altered_messages = rebound_messages(invalid_references)
        with monkeypatch.context() as patch:
            patch.setattr(
                scheduler_adapter_module,
                "SQLiteSchedulerStore",
                report_store_with(altered_messages),
            )
            with pytest.raises(
                WorkflowFinalReportError,
                match="exact target Agent Result lineage",
            ):
                WorkflowFinalReportService(create_planner()).report(
                    outcome,
                    closure,
                    case.plan,
                    case.root,
                    case.scheduler_path,
                )

    accepted_review = quality_gates_module.load_independent_review(review_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            quality_gates_module,
            "load_independent_review",
            lambda _path: replace(
                accepted_review,
                candidate=replace(plan.candidate, repository_digest="F" * 64),
            ),
        )
        with pytest.raises(
            WorkflowFinalReportError,
            match="binding or reviewed Agent Results are stale",
        ):
            WorkflowFinalReportService(create_planner()).report(
                outcome,
                closure,
                case.plan,
                case.root,
                case.scheduler_path,
            )

    def fail_reviewed_agent_identity(*_args: object, **_kwargs: object) -> None:
        raise ValueError("injected reviewed Agent identity mismatch")

    with monkeypatch.context() as patch:
        patch.setattr(
            scheduler_contracts_module,
            "validate_reviewed_agent_identities",
            fail_reviewed_agent_identity,
        )
        with pytest.raises(
            WorkflowFinalReportError,
            match="binding or reviewed Agent Results are stale",
        ):
            WorkflowFinalReportService(create_planner()).report(
                outcome,
                closure,
                case.plan,
                case.root,
                case.scheduler_path,
            )


def _create_case(tmp_path: Path) -> CloseoutCase:
    root = create_workspace(tmp_path)
    for relative in (
        "LICENSE",
        "pyproject.toml",
        "docs/evidence/M2-verification.md",
        "examples/m3-quality/evidence/install-trace.json",
    ):
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    for name in ("handoff", "independent-review"):
        skill_source = ROOT / ".agents" / "skills" / name / "SKILL.md"
        skill_path = root / ".agents" / "skills" / name / "SKILL.md"
        skill_path.parent.mkdir(parents=True)
        shutil.copy2(skill_source, skill_path)
    lifecycles = {
        item.name: item for item in validate_skills(root / ".agents/skills")
    }
    review_skill_token = skill_capability_token(lifecycles["independent-review"])
    handoff_skill_token = skill_capability_token(lifecycles["handoff"])
    review_skill_reference = resolve_skill_capabilities(
        root,
        (review_skill_token,),
    )[0].reference
    handoff_skill_reference = resolve_skill_capabilities(
        root,
        (handoff_skill_token,),
    )[0].reference

    request_reference = _write_orchestration_request(root)
    base_artifact = load_scheduler_artifact(
        root / "examples/m6-scheduler/task-graph.json",
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    base = base_artifact.value
    assert isinstance(base, TaskGraph)
    registry_path = root / "workflow/closeout-solver-registry.json"
    registry_artifact = solver_artifact_from_value(
        SolverArtifactType.REGISTRY,
        reference_registry(root=root),
    )
    registry_path.write_bytes(serialize_solver_artifact(registry_artifact))
    registry_reference = _reference(root, registry_path)
    context = base.contexts[0]
    placeholder = ArtifactReference("placeholder.json", "0" * 64)
    request_value = SolverRequest(
        sensitivity=context.sensitivity,
        registry=registry_reference,
        registry_id=registry_artifact.artifact_id,
        adapter_id=REFERENCE_ADAPTER_ID,
        contract_id="M7-SOLVER-CONTRACT-" + "0" * 64,
        task_graph=placeholder,
        graph_id="M6-TASK-GRAPH-" + "0" * 64,
        task_id=SOLVER_TASK,
        candidate=base.candidate,
        context_snapshot=context.reference,
        context_snapshot_id=context.artifact_id,
        problem=scheduling_problem(),
        required_claim=SolverRequiredClaim.OPTIMAL,
        resource_policy=SolverResourcePolicy(16, 16, None, 1_048_576),
    )
    request_value = replace(
        request_value,
        contract_id=operational_contract_id(request_value.operational_content()),
    )
    solver_token = solver_capability_token(request_value)
    budget = replace(
        base.budget,
        max_agents=4,
        max_concurrency=1,
        max_solver_calls=1,
        max_solver_steps=32,
    )
    base_task = base.tasks[0]
    tasks = (
        replace(
            base_task,
            task_id=IMPLEMENTER_TASK,
            dependencies=(),
            required_capabilities=(),
            review_targets=(),
            wave=0,
        ),
        replace(
            base_task,
            task_id=SOLVER_TASK,
            kind=TaskKind.SOLVER,
            dependencies=(IMPLEMENTER_TASK,),
            required_tools=(),
            required_capabilities=(solver_token,),
            owned_paths=(),
            worktree_assignment=None,
            effect_kind=EffectKind.READ_ONLY,
            review_targets=(),
            wave=1,
        ),
        replace(
            base_task,
            task_id=REVIEWER_TASK,
            kind=TaskKind.REVIEW,
            dependencies=tuple(sorted((IMPLEMENTER_TASK, SOLVER_TASK))),
            role_id="independent-reviewer",
            required_capabilities=(review_skill_token,),
            review_targets=(IMPLEMENTER_TASK,),
            wave=2,
        ),
        replace(
            base_task,
            task_id=HANDOFF_TASK,
            kind=TaskKind.HANDOFF,
            dependencies=tuple(sorted((IMPLEMENTER_TASK, SOLVER_TASK, REVIEWER_TASK))),
            required_capabilities=(handoff_skill_token,),
            review_targets=(),
            wave=3,
        ),
    )
    graph = replace(
        base,
        orchestration_request=request_reference,
        budget=budget,
        tasks=tasks,
    )
    graph_artifact = scheduler_artifact_from_value(
        SchedulerArtifactType.TASK_GRAPH,
        graph,
    )
    graph_path = root / "workflow/closeout-task-graph.json"
    graph_path.write_bytes(serialize_scheduler_artifact(graph_artifact))
    request_value = replace(
        request_value,
        task_graph=_reference(root, graph_path),
        graph_id=graph_artifact.artifact_id,
    )
    assert request_value.contract_id == operational_contract_id(
        request_value.operational_content()
    )
    request_artifact = solver_artifact_from_value(
        SolverArtifactType.REQUEST,
        request_value,
    )
    request_path = root / "workflow/closeout-solver-request.json"
    request_path.write_bytes(serialize_solver_artifact(request_artifact))
    SolverService().validate_request(request_path, registry_path, graph_path, root)

    scheduler_path = root / "workflow/closeout-scheduler.sqlite3"
    SchedulerService(FixedClock(CLOSEOUT_TIME)).initialize(
        graph_path,
        root,
        scheduler_path,
        workflow_authority=True,
    )
    intent_artifact, intent_path = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    links = tuple(
        IntentTaskLink(
            task_id=task.task_id,
            requirement_ids=(REQUIREMENT_ID,),
            acceptance_ids=(ACCEPTANCE_ID,),
            context_node_ids=intent.task_links[0].context_node_ids,
            solver_request_ids=(
                (request_artifact.artifact_id,)
                if task.task_id == SOLVER_TASK
                else ()
            ),
        )
        for task in graph.tasks
    )
    closeout_intent = workflow_artifact_from_value(
        WorkflowArtifactType.DEVELOPMENT_INTENT,
        replace(
            intent,
            completion_profile=CompletionProfile.IMPLEMENTATION_VERIFIED,
            budget=budget,
            capabilities=tuple(sorted((review_skill_token, handoff_skill_token))),
            task_graph=NativeArtifactBinding(
                SchedulerArtifactType.TASK_GRAPH.value,
                graph_artifact.artifact_id,
                _reference(root, graph_path),
                True,
            ),
            solver_registry=NativeArtifactBinding(
                SolverArtifactType.REGISTRY.value,
                registry_artifact.artifact_id,
                registry_reference,
                True,
            ),
            solver_requests=(
                NativeArtifactBinding(
                    SolverArtifactType.REQUEST.value,
                    request_artifact.artifact_id,
                    _reference(root, request_path),
                    True,
                ),
            ),
            task_links=links,
            required_gate_ids=("G1", "G2"),
        ),
    )
    intent_path.write_bytes(serialize_workflow_artifact(closeout_intent))
    plan_path = root / "workflow/closeout-plan.json"
    plan = create_planner().publish_plan(
        closeout_intent,
        artifact_reference_for(root, intent_path),
        root,
        scheduler_path,
        plan_path,
        recorded_at=CLOSEOUT_TIME,
    )
    return CloseoutCase(
        root,
        graph_path,
        scheduler_path,
        plan,
        plan_path,
        registry_path,
        request_path,
        review_skill_reference,
        review_skill_token,
        handoff_skill_reference,
        handoff_skill_token,
        solver_token,
    )


def _write_orchestration_request(root: Path) -> ArtifactReference:
    payload = json.loads(
        (root / "examples/m2-orchestration/orchestration-request.json").read_text(
            encoding="utf-8"
        )
    )
    payload["requested_roles"] = sorted(("implementer", "independent-reviewer"))
    payload["budget"]["max_agents"] = 4
    payload["budget"]["max_concurrency"] = 1
    path = root / "workflow/closeout-orchestration-request.json"
    _write_json(path, payload)
    return _reference(root, path)


def _capability_observation(case: CloseoutCase) -> LoadedSchedulerArtifact:
    graph_artifact = load_scheduler_artifact(
        case.graph_path,
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=case.root,
    )
    graph = graph_artifact.value
    assert isinstance(graph, TaskGraph)
    return scheduler_artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.CAPABILITY_OBSERVATION,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender=HOST_ID,
            recipient="HST-SCHEDULER",
            graph_id=graph_artifact.artifact_id,
            task_id=None,
            candidate=graph.candidate,
            context_snapshot_id=None,
            attempt=None,
            lease_id=None,
            fence=None,
            idempotency_key=None,
            sensitivity=Sensitivity.PUBLIC,
            provenance=(),
            causal_parent_message_ids=(),
            recorded_at=_timestamp(CLOSEOUT_TIME + timedelta(seconds=1)),
            payload={
                "capabilities": sorted(
                    (
                        case.review_skill_token,
                        case.handoff_skill_token,
                        case.solver_token,
                    )
                )
            },
        ),
    )


def _task_result(
    dispatch: LoadedSchedulerArtifact,
    agent_result: ArtifactReference,
    evidence: tuple[ArtifactReference, ...],
    *,
    clock_offset: int,
) -> LoadedSchedulerArtifact:
    return host_message(
        dispatch,
        MessageType.TASK_RESULT,
        {
            "agent_result": agent_result.to_dict(),
            "outcome": "succeeded",
            "effect_observed": "none",
            "evidence_refs": [item.to_dict() for item in evidence],
            "budget_usage": {
                "microunits": 0,
                "solver_calls": 0,
                "solver_steps": 0,
                "tool_calls": 0,
            },
        },
        clock=CLOSEOUT_TIME + timedelta(seconds=clock_offset),
        sender=HOST_ID,
    )


def _solver_task_result(
    dispatch: LoadedSchedulerArtifact,
    agent_result: ArtifactReference,
    result_artifact: LoadedSolverArtifact,
    verification_artifact: LoadedSolverArtifact,
    root: Path,
    result_path: Path,
    verification_path: Path,
) -> LoadedSchedulerArtifact:
    result = getattr(result_artifact, "value", None)
    verification = getattr(verification_artifact, "value", None)
    assert isinstance(result, SolverResult)
    assert isinstance(verification, SolverVerification)
    evidence = tuple(
        sorted(
            (_reference(root, result_path), _reference(root, verification_path)),
            key=lambda item: item.path,
        )
    )
    return host_message(
        dispatch,
        MessageType.TASK_RESULT,
        {
            "agent_result": agent_result.to_dict(),
            "outcome": "succeeded",
            "effect_observed": "none",
            "evidence_refs": [item.to_dict() for item in evidence],
            "budget_usage": {
                "microunits": 0,
                "solver_calls": result.resources.solver_calls,
                "solver_steps": (
                    result.resources.solver_steps + verification.verification_steps
                ),
                "tool_calls": 0,
            },
        },
        clock=CLOSEOUT_TIME + timedelta(seconds=4),
        sender=HOST_ID,
    )


def _write_agent_result(
    root: Path,
    name: str,
    *,
    agent_id: str,
    role_id: str,
    finding_id: str,
    statement: str,
    evidence_refs: tuple[str, ...],
    reviewed_agent_ids: tuple[str, ...] = (),
) -> ArtifactReference:
    path = root / "workflow/agents" / name
    _write_json(
        path,
        {
            "schema_version": "1.0",
            "agent_id": agent_id,
            "role_id": role_id,
            "status": "completed",
            "summary": statement,
            "findings": [
                {
                    "finding_id": finding_id,
                    "severity": "low",
                    "statement": statement,
                    "specification_refs": [REQUIREMENT_ID],
                    "evidence_refs": list(evidence_refs),
                    "evidence_strength": "direct",
                    "counterexample": None,
                }
            ],
            "changed_paths": [],
            "reviewed_agent_ids": list(reviewed_agent_ids),
            "self_approved": False,
        },
    )
    return _reference(root, path)


def _write_independent_review(root: Path, plan: IntegratedPlan) -> Path:
    path = root / "workflow/closeout-independent-review.json"
    _write_json(
        path,
        {
            "schema_version": "1.0",
            "review_id": "REV-CLOSEOUT-1",
            "baseline_id": plan.requirement_baseline_id,
            "candidate": plan.candidate.to_dict(),
            "reviewed_at": _timestamp(CLOSEOUT_TIME + timedelta(seconds=5)),
            "reviewer_id": REVIEWER_AGENT,
            "reviewed_agent_ids": [IMPLEMENTER_AGENT],
            "status": "completed",
            "read_only": True,
            "areas": ["regression", "security", "maintainability"],
            "findings": [],
            "reviewed_paths": ["src/sdaqf/application/workflow_explanation.py"],
            "changed_paths": [],
        },
    )
    return path


def _write_handoff(root: Path, plan: IntegratedPlan, ledger: EvidenceLedger) -> Path:
    evidence_ids = sorted(item.evidence_id for item in ledger.evidence)
    input_path = root / "workflow/closeout-handoff-input.json"
    _write_json(
        input_path,
        {
            "schema_version": "1.0",
            "milestone": "M8",
            "status": "completed",
            "completed": ["Closeout evidence and exact solver verification"],
            "incomplete": [],
            "evidence_ids": evidence_ids,
            "open_decisions": [],
            "known_problems": [],
            "recommended_next": "Freeze feature development after human review.",
            "primary_folder": "repo/",
            "approval_stops": ["Human review remains required before the final decision."],
            "next_prompt_context": {
                "role": "Closeout reviewer",
                "references": ["workflow/closeout-outcome.json"],
                "change_scope": ["Review the exact closeout report."],
                "exclusions": ["Do not publish or add features."],
                "completion_criteria": ["Confirm unresolved disagreements."],
                "stop_conditions": ["Stop if exact provenance cannot be reproduced."],
            },
        },
    )
    handoff = HandoffService().create(
        input_path,
        baseline_id=plan.requirement_baseline_id,
        candidate=plan.candidate,
        git=GitObservation(
            True,
            "fixture",
            plan.candidate.git_head,
            True,
            plan.candidate.repository_digest,
        ),
        ledger=ledger,
    )
    path = root / "workflow/closeout-automated-handoff.json"
    _write_json(path, handoff.to_dict())
    return path


def _only_dispatch(
    outgoing: tuple[LoadedSchedulerArtifact, ...],
    task_id: str,
) -> LoadedSchedulerArtifact:
    assert len(outgoing) == 1
    dispatch = outgoing[0]
    message = dispatch.value
    assert isinstance(message, MailboxMessage)
    assert message.message_type is MessageType.DISPATCH_INTENT
    assert message.task_id == task_id
    return dispatch


def _assert_exact_skill_provenance(
    dispatch: LoadedSchedulerArtifact,
    skill_reference: ArtifactReference,
) -> None:
    message = dispatch.value
    assert isinstance(message, MailboxMessage)
    assert len(message.provenance) == 2
    assert message.provenance[1] == skill_reference


def _assert_context_only_provenance(dispatch: LoadedSchedulerArtifact) -> None:
    message = dispatch.value
    assert isinstance(message, MailboxMessage)
    assert len(message.provenance) == 1


def _reference(root: Path, path: Path) -> ArtifactReference:
    relative = path.resolve(strict=True).relative_to(root.resolve(strict=True)).as_posix()
    return ArtifactReference(
        relative,
        hashlib.sha256(path.read_bytes()).hexdigest().upper(),
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _tree_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
