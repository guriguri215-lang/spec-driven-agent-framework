"""M8 Outcome publication and no-status-upgrade tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

import sdaqf.application.workflow_outcome as outcome_module
from sdaqf.adapters.context import CanonicalUTF8ByteEstimator, LocalContextSourceReader
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.adapters.workflow import ExclusiveWorkflowArtifactStore, WorkflowAdapterError
from sdaqf.application.workflow_contracts import (
    artifact_from_value,
    load_workflow_artifact,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_planning import (
    IntegratedPlanner,
    WorkflowPlanningError,
    artifact_reference_for,
)
from sdaqf.application.workflow_recovery import WorkflowRecoveryError
from sdaqf.application.workflow_runtime import WorkflowRuntimeError, WorkflowRuntimeService
from sdaqf.domain.scheduler import TaskOutcome, TaskState, WorkflowEpochPhase
from sdaqf.domain.workflow import (
    CompletionProfile,
    DevelopmentIntent,
    EffectDisposition,
    GateObservation,
    GateStatus,
    IntegratedPlan,
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowBlocker,
    WorkflowDisposition,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowOutcome,
    WorkflowState,
)
from tests.m8_workflow_helpers import (
    FixedClock,
    FixtureCandidateVerifier,
    create_outcome,
    create_plan,
    create_planner,
    create_recovery,
    create_runtime,
    create_scheduler,
    create_workspace,
    workflow_binding,
)


def test_plan_only_outcome_completes_with_g1_and_no_plan_blocker(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    state = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/state.json",
        root / "workflow/event.json",
    )
    outcome, event, closure = create_outcome(FixedClock()).publish(
        state.state,
        workflow_binding(root, root / "workflow/state.json", state.state),
        plan,
        root,
        scheduler,
        root / "workflow/outcome.json",
        root / "workflow/outcome-event.json",
        root / "workflow/outcome-state.json",
    )
    assert isinstance(outcome.value, WorkflowOutcome)
    assert isinstance(event.value, WorkflowEvent)
    assert outcome.value.disposition is WorkflowDisposition.COMPLETED
    closure_value = closure.value
    assert isinstance(closure_value, WorkflowState)
    assert outcome.value.terminal_state_id == closure.artifact_id
    assert event.value.native_output_ids == ()
    assert closure_value.latest_event.artifact_id == event.artifact_id


def test_terminal_confirmed_exact_retry_reuses_public_artifacts_and_receipts(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    source_path = root / "workflow/retry-source-state.json"
    source = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        source_path,
        root / "workflow/retry-source-event.json",
    )
    arguments = (
        source.state,
        workflow_binding(root, source_path, source.state),
        plan,
        root,
        scheduler,
        root / "workflow/retry-outcome.json",
        root / "workflow/retry-terminal-event.json",
        root / "workflow/retry-terminal-state.json",
    )
    first = create_outcome(FixedClock()).publish(*arguments)
    second = create_outcome(FixedClock()).publish(*arguments)
    assert second == first
    head = SQLiteSchedulerStore(scheduler, root).workflow_head(plan.artifact_id)
    assert head is not None and head.phase is WorkflowEpochPhase.TERMINAL_CONFIRMED


def test_terminal_foreign_collision_remains_reserved_and_is_never_repaired(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    source_path = root / "workflow/collision-source-state.json"
    source = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        source_path,
        root / "workflow/collision-source-event.json",
    )
    terminal_event = root / "workflow/collision-terminal-event.json"
    terminal_state = root / "workflow/collision-terminal-state.json"
    outcome_path = root / "workflow/collision-outcome.json"

    class CollisionStore(ExclusiveWorkflowArtifactStore):
        def publish_idempotent(
            self,
            output: Path,
            content: bytes,
            *,
            artifact_type: str,
            artifact_id: str,
        ) -> None:
            if Path(output).name == terminal_event.name and not terminal_event.exists():
                terminal_event.write_bytes(b"{}\n")
                raise WorkflowAdapterError("synthetic foreign collision")
            super().publish_idempotent(
                output,
                content,
                artifact_type=artifact_type,
                artifact_id=artifact_id,
            )

    service = outcome_module.WorkflowOutcomeService(
        FixedClock(),
        CollisionStore(root),
        planner=create_planner(),
    )
    with pytest.raises(WorkflowAdapterError, match="foreign collision"):
        service.publish(
            source.state,
            workflow_binding(root, source_path, source.state),
            plan,
            root,
            scheduler,
            outcome_path,
            terminal_event,
            terminal_state,
        )
    store = SQLiteSchedulerStore(scheduler, root)
    head = store.workflow_head(plan.artifact_id)
    assert head is not None and head.phase is WorkflowEpochPhase.TERMINAL_RESERVED
    foreign = terminal_event.read_bytes()
    with pytest.raises(WorkflowAdapterError):
        create_outcome(FixedClock()).publish(
            source.state,
            workflow_binding(root, source_path, source.state),
            plan,
            root,
            scheduler,
            outcome_path,
            terminal_event,
            terminal_state,
        )
    assert terminal_event.read_bytes() == foreign
    replay_head = store.workflow_head(plan.artifact_id)
    assert replay_head is not None
    assert replay_head.phase is WorkflowEpochPhase.TERMINAL_RESERVED


def test_outcome_revalidates_pinned_candidate_immediately_before_terminal_reserve(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    source_path = root / "workflow/race-source-state.json"
    source = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        source_path,
        root / "workflow/race-source-event.json",
    )

    class RaceVerifier(FixtureCandidateVerifier):
        def revalidate(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("synthetic reserve-edge Candidate drift")

    service = outcome_module.WorkflowOutcomeService(
        FixedClock(),
        planner=IntegratedPlanner(
            RaceVerifier(),
            LocalContextSourceReader(),
            CanonicalUTF8ByteEstimator(),
        ),
    )
    targets = tuple(
        root / "workflow" / name
        for name in ("race-terminal-event.json", "race-terminal-state.json", "race-outcome.json")
    )
    with pytest.raises(
        outcome_module.WorkflowOutcomeError,
        match="changed before reserve",
    ):
        service.publish(
            source.state,
            workflow_binding(root, source_path, source.state),
            plan,
            root,
            scheduler,
            targets[2],
            targets[0],
            targets[1],
        )
    head = SQLiteSchedulerStore(scheduler, root).workflow_head(plan.artifact_id)
    assert head is not None and head.phase is WorkflowEpochPhase.ACTIVE
    assert not any(path.exists() for path in targets)


def test_supersede_revalidates_successor_candidate_before_terminal_reserve(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    plan_value = plan.value
    assert isinstance(plan_value, IntegratedPlan)
    scheduler = create_scheduler(root)
    source_path = root / "workflow/supersede-race-source-state.json"
    source = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        source_path,
        root / "workflow/supersede-race-source-event.json",
    )
    old_intent = load_workflow_artifact(
        root / plan_value.intent.reference.path,
        expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
    ).value
    assert isinstance(old_intent, DevelopmentIntent)
    successor_candidate = replace(plan_value.candidate, repository_digest="D" * 64)
    successor = artifact_from_value(
        WorkflowArtifactType.DEVELOPMENT_INTENT,
        replace(old_intent, candidate=successor_candidate),
    )
    successor_path = root / "workflow/supersede-race-intent.json"
    successor_path.write_bytes(serialize_workflow_artifact(successor))
    (root / "workflow/candidate.json").write_text(
        json.dumps(successor_candidate.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    class RaceVerifier(FixtureCandidateVerifier):
        def revalidate(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("synthetic reserve-edge successor drift")

    runtime = WorkflowRuntimeService(
        FixedClock(),
        planner=IntegratedPlanner(
            RaceVerifier(),
            LocalContextSourceReader(),
            CanonicalUTF8ByteEstimator(),
        ),
    )
    targets = tuple(
        root / "workflow" / name
        for name in (
            "supersede-race-state.json",
            "supersede-race-event.json",
            "supersede-race-outcome.json",
        )
    )
    with pytest.raises(WorkflowRuntimeError, match="changed before reserve"):
        runtime.supersede(
            source.state,
            workflow_binding(root, source_path, source.state),
            plan,
            successor,
            workflow_binding(root, successor_path, successor),
            root,
            scheduler,
            targets[0],
            targets[1],
            targets[2],
        )
    head = SQLiteSchedulerStore(scheduler, root).workflow_head(plan.artifact_id)
    assert head is not None and head.phase is WorkflowEpochPhase.ACTIVE
    assert not any(path.exists() for path in targets)


def test_superseded_epoch_produces_exact_predecessor_outcome_without_erasing_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    plan, plan_path = create_plan(root)
    plan_value = plan.value
    assert isinstance(plan_value, IntegratedPlan)
    scheduler = create_scheduler(root)
    source_path = root / "workflow/source-state.json"
    source = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        source_path,
        root / "workflow/source-event.json",
    )
    old_intent = load_workflow_artifact(
        root / plan_value.intent.reference.path,
        expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
    ).value
    assert isinstance(old_intent, DevelopmentIntent)
    successor_candidate = replace(plan_value.candidate, repository_digest="D" * 64)
    proposal = artifact_from_value(
        WorkflowArtifactType.DEVELOPMENT_INTENT,
        replace(old_intent, candidate=successor_candidate),
    )
    proposal_path = root / "workflow/successor-proposal.json"
    proposal_path.write_bytes(serialize_workflow_artifact(proposal))
    (root / "workflow/candidate.json").write_text(
        json.dumps(successor_candidate.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    superseded_path = root / "workflow/superseded-state.json"
    outcome_path = root / "workflow/superseded-outcome.json"
    superseded = create_runtime(FixedClock()).supersede(
        source.state,
        workflow_binding(root, source_path, source.state),
        plan,
        proposal,
        workflow_binding(root, proposal_path, proposal),
        root,
        scheduler,
        superseded_path,
        root / "workflow/superseded-event.json",
        outcome_path,
    )
    outcome = superseded.outcome
    assert outcome is not None
    closure = superseded.state
    outcome_value = outcome.value
    assert isinstance(outcome_value, WorkflowOutcome)
    assert outcome_value.disposition is WorkflowDisposition.SUPERSEDED
    assert isinstance(closure.value, WorkflowState)

    successor = replace(
        old_intent,
        candidate=successor_candidate,
        predecessor_plan_id=plan.artifact_id,
        predecessor_state_id=superseded.state.artifact_id,
        predecessor_outcome_id=outcome.artifact_id,
        predecessor_plan=workflow_binding(root, plan_path, plan),
        predecessor_state=workflow_binding(root, superseded_path, superseded.state),
        predecessor_outcome=workflow_binding(root, outcome_path, outcome),
    )
    planner = create_planner()
    assert planner._validate_predecessor(successor, root, scheduler) == outcome_value
    assert successor.predecessor_plan is not None

    with pytest.raises(WorkflowPlanningError, match="binding is not exact"):
        planner._validate_predecessor(
            replace(
                successor,
                predecessor_plan=replace(successor.predecessor_plan, required=False),
            ),
            root,
            scheduler,
        )
    with pytest.raises(WorkflowPlanningError, match="must change"):
        planner._validate_predecessor(
            replace(successor, candidate=plan_value.candidate),
            root,
            scheduler,
        )
    missing_plan = replace(
        successor.predecessor_plan,
        reference=replace(successor.predecessor_plan.reference, path="workflow/missing-plan.json"),
    )
    with pytest.raises(WorkflowPlanningError, match="failed validation"):
        planner._validate_predecessor(
            replace(successor, predecessor_plan=missing_plan),
            root,
            scheduler,
        )

    superseded_value = superseded.state.value
    assert isinstance(superseded_value, WorkflowState)
    linked_plan_value = replace(
        plan_value,
        candidate=successor_candidate,
        predecessor_plan_id=plan.artifact_id,
        predecessor_state_id=superseded.state.artifact_id,
        predecessor_outcome_id=outcome.artifact_id,
        predecessor_plan=workflow_binding(root, plan_path, plan),
        predecessor_state=workflow_binding(root, superseded_path, superseded.state),
        predecessor_outcome=workflow_binding(root, outcome_path, outcome),
    )
    linked_plan = artifact_from_value(
        WorkflowArtifactType.INTEGRATED_PLAN,
        linked_plan_value,
    )
    with monkeypatch.context() as lineage_patch:
        lineage_patch.setattr(
            outcome_module.WorkflowOutcomeService,
            "_validated_values",
                lambda _self, _state, candidate_plan, *_args: (
                    candidate_plan.value,
                    superseded_value,
                    None,
                ),
        )
        derived = create_outcome(FixedClock()).derive(
            superseded.state,
            linked_plan,
            root,
            scheduler,
        )
        derived_value = derived.value
        assert isinstance(derived_value, WorkflowOutcome)
        assert derived_value.lineage_plan_ids == tuple(
            sorted((plan.artifact_id, linked_plan.artifact_id))
        )
        assert linked_plan_value.predecessor_outcome is not None
        drift_plan = artifact_from_value(
            WorkflowArtifactType.INTEGRATED_PLAN,
            replace(
                linked_plan_value,
                predecessor_outcome_id="M8-WORKFLOW-OUTCOME-" + "A" * 64,
                predecessor_outcome=replace(
                    linked_plan_value.predecessor_outcome,
                    artifact_id="M8-WORKFLOW-OUTCOME-" + "A" * 64,
                ),
            ),
        )
        with pytest.raises(outcome_module.WorkflowOutcomeError, match="binding drifted"):
            create_outcome(FixedClock()).derive(
                superseded.state,
                drift_plan,
                root,
                scheduler,
            )

    wrong_status = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_STATE,
        replace(superseded_value, status=TaskState.COMPLETED),
    )
    wrong_status_path = root / "workflow/wrong-predecessor-status.json"
    wrong_status_path.write_bytes(serialize_workflow_artifact(wrong_status))
    with pytest.raises(WorkflowPlanningError, match="old superseded epoch"):
        planner._validate_predecessor(
            replace(
                successor,
                predecessor_state_id=wrong_status.artifact_id,
                predecessor_state=workflow_binding(root, wrong_status_path, wrong_status),
            ),
            root,
            scheduler,
        )

    supersession_event = load_workflow_artifact(
        root / "workflow/superseded-event.json",
        expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
    )
    supersession_event_value = supersession_event.value
    assert isinstance(supersession_event_value, WorkflowEvent)
    wrong_event = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_EVENT,
        replace(supersession_event_value, actor="forged supersession actor"),
    )
    wrong_event_path = root / "workflow/wrong-supersession-event.json"
    wrong_event_path.write_bytes(serialize_workflow_artifact(wrong_event))
    wrong_event_binding = workflow_binding(root, wrong_event_path, wrong_event)
    wrong_event_state = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_STATE,
        replace(
            superseded_value,
            event_chain=(*superseded_value.event_chain[:-1], wrong_event_binding),
            latest_event=wrong_event_binding,
        ),
    )
    wrong_event_state_path = root / "workflow/wrong-supersession-state.json"
    wrong_event_state_path.write_bytes(serialize_workflow_artifact(wrong_event_state))
    with pytest.raises(WorkflowPlanningError, match="supersession Event"):
        planner._validate_predecessor(
            replace(
                successor,
                predecessor_state_id=wrong_event_state.artifact_id,
                predecessor_state=workflow_binding(root, wrong_event_state_path, wrong_event_state),
            ),
            root,
            scheduler,
        )
    with pytest.raises(WorkflowRuntimeError, match="supersession disposition"):
        create_runtime(FixedClock()).status(
            wrong_event_state,
            plan,
            root,
            scheduler,
            publication_observation=planner._verify_candidate(
                root,
                successor,
                scheduler,
                require_scheduler_candidate=False,
            ),
        )

    mutations = (
        replace(outcome_value, evidence_ids=("EVD-FORGED",)),
        replace(outcome_value, approval_ids=("APR-FORGED",)),
        replace(outcome_value, ambiguities=("external-effect-ambiguous",)),
    )
    for index, mutation in enumerate(mutations):
        forged = artifact_from_value(WorkflowArtifactType.WORKFLOW_OUTCOME, mutation)
        forged_path = root / f"workflow/forged-predecessor-{index}.json"
        forged_path.write_bytes(serialize_workflow_artifact(forged))
        forged_successor = replace(
            successor,
            predecessor_outcome_id=forged.artifact_id,
            predecessor_outcome=workflow_binding(root, forged_path, forged),
        )
        with pytest.raises(WorkflowPlanningError, match=r"terminal head|rederive|erased|changed"):
            planner._validate_predecessor(forged_successor, root, scheduler)

    scheduler.unlink()
    with pytest.raises(WorkflowPlanningError, match="native history"):
        planner._validate_predecessor(successor, root, scheduler)


def test_outcome_never_executes_protected_or_external_action(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    state = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/state.json",
        root / "workflow/event.json",
    )
    service = create_outcome(FixedClock())
    published, _event, closure = service.publish(
        state.state,
        workflow_binding(root, root / "workflow/state.json", state.state),
        plan,
        root,
        scheduler,
        root / "workflow/no-action-outcome.json",
        root / "workflow/no-action-terminal-event.json",
        root / "workflow/no-action-terminal-state.json",
    )
    before = scheduler.read_bytes()
    derived = service.derive(closure, plan, root, scheduler)
    assert derived.artifact_id == published.artifact_id
    assert scheduler.read_bytes() == before


def test_outcome_rejects_content_addressed_but_forged_workflow_state(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    transition = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/genuine-state.json",
        root / "workflow/genuine-event.json",
    )
    state = transition.state.value
    assert isinstance(state, WorkflowState)
    forged = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_STATE,
        replace(
            state,
            evidence_ids=("EVD-FORGED-COMPLETION",),
            tasks=tuple(
                replace(
                    item,
                    state=TaskState.COMPLETED,
                    outcome=TaskOutcome.SUCCEEDED,
                )
                for item in state.tasks
            ),
        ),
    )
    with pytest.raises(WorkflowRuntimeError, match=r"receipt|native-derived projection"):
        create_outcome(FixedClock()).derive(forged, plan, root, scheduler)


def test_outcome_rejects_rehashed_semantically_forged_event_chain(
    tmp_path: Path,
) -> None:
    """Content addressing cannot make an invented Event transition authoritative."""

    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    transition = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/genuine-chain-state.json",
        root / "workflow/genuine-chain-event.json",
    )
    event = transition.event.value
    state = transition.state.value
    assert isinstance(event, WorkflowEvent)
    assert isinstance(state, WorkflowState)
    forged_event = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_EVENT,
        replace(event, cause=WorkflowEventCause.GATE_EVALUATED),
    )
    forged_event_path = root / "workflow/forged-chain-event.json"
    forged_event_path.write_bytes(serialize_workflow_artifact(forged_event))
    forged_binding = NativeArtifactBinding(
        WorkflowArtifactType.WORKFLOW_EVENT.value,
        forged_event.artifact_id,
        artifact_reference_for(root, forged_event_path),
        True,
    )
    forged_state = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_STATE,
        replace(
            state,
            event_chain=(forged_binding,),
            latest_event=forged_binding,
        ),
    )
    with pytest.raises(WorkflowRuntimeError, match=r"Event.*semantic"):
        create_outcome(FixedClock()).derive(forged_state, plan, root, scheduler)


def test_outcome_rejects_forged_prior_state_adopted_by_content_addressed_closure(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    transition = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/native-source-state.json",
        root / "workflow/native-source-event.json",
    )
    state = transition.state.value
    assert isinstance(state, WorkflowState)
    forged_prior = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_STATE,
        replace(state, evidence_ids=("EV-FORGED-PRIOR",)),
    )
    forged_prior_path = root / "workflow/forged-prior-state.json"
    forged_prior_path.write_bytes(serialize_workflow_artifact(forged_prior))
    forged_prior_binding = workflow_binding(root, forged_prior_path, forged_prior)
    plan_value = plan.value
    assert isinstance(plan_value, IntegratedPlan)
    closure_event = WorkflowEvent(
        sequence=state.transition_count + 1,
        previous_event_id=state.latest_event.artifact_id,
        prior_state_id=forged_prior.artifact_id,
        plan_id=plan.artifact_id,
        candidate=plan_value.candidate,
        sensitivity=plan_value.sensitivity,
        cause=WorkflowEventCause.OUTCOME_PRODUCED,
        before_status=state.status,
        after_status=state.status,
        scheduler_event_head_before=state.scheduler_event_head_sha256,
        scheduler_event_head_after=state.scheduler_event_head_sha256,
        effect_disposition=EffectDisposition.NOT_APPLICABLE,
        actor="M8 workflow outcome service",
        recorded_at=state.recorded_at,
        idempotency_key=outcome_module._outcome_idempotency(
            plan.artifact_id,
            forged_prior.artifact_id,
        ),
        native_input_ids=tuple(
            sorted(
                {
                    plan.artifact_id,
                    forged_prior.artifact_id,
                    state.latest_event.artifact_id,
                    state.scheduler_state_id,
                }
            )
        ),
        native_output_ids=(),
        task_id=None,
        effect_id=None,
        approval_id=None,
        reason_codes=("outcome-produced",),
        prior_state=forged_prior_binding,
    )
    closure_event_artifact = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_EVENT,
        closure_event,
    )
    closure_event_path = root / "workflow/forged-closure-event.json"
    closure_event_path.write_bytes(serialize_workflow_artifact(closure_event_artifact))
    closure_binding = workflow_binding(root, closure_event_path, closure_event_artifact)
    forged_closure = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_STATE,
        replace(
            state,
            evidence_ids=("EV-FORGED-PRIOR",),
            event_chain=(*state.event_chain, closure_binding),
            latest_event=closure_binding,
            transition_count=state.transition_count + 1,
        ),
    )
    with pytest.raises(WorkflowRuntimeError, match=r"receipt|native-derived"):
        create_outcome(FixedClock()).derive(forged_closure, plan, root, scheduler)


def test_outcome_event_is_adopted_by_a_published_closure_state(tmp_path: Path) -> None:
    """A successful outcome-produced Event is never left orphaned."""

    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    transition = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/outcome-source-state.json",
        root / "workflow/outcome-source-event.json",
    )
    outcome, event, closure = create_outcome(FixedClock()).publish(
        transition.state,
        workflow_binding(
            root,
            root / "workflow/outcome-source-state.json",
            transition.state,
        ),
        plan,
        root,
        scheduler,
        root / "workflow/adopted-outcome.json",
        root / "workflow/adopted-outcome-event.json",
        root / "workflow/adopted-outcome-state.json",
    )
    closure_state = closure.value
    assert isinstance(closure_state, WorkflowState)
    assert closure_state.latest_event.artifact_id == event.artifact_id
    assert closure_state.event_chain[-1].artifact_id == event.artifact_id
    outcome_value = outcome.value
    assert isinstance(outcome_value, WorkflowOutcome)
    assert outcome_value.terminal_state_id == closure.artifact_id


def test_terminal_closure_rejects_resume_recovery_supersession_and_republication(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    plan_value = plan.value
    assert isinstance(plan_value, IntegratedPlan)
    scheduler = create_scheduler(root)
    source_path = root / "workflow/terminal-source-state.json"
    source = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        source_path,
        root / "workflow/terminal-source-event.json",
    )
    _, _, closure = create_outcome(FixedClock()).publish(
        source.state,
        workflow_binding(root, source_path, source.state),
        plan,
        root,
        scheduler,
        root / "workflow/terminal-outcome.json",
        root / "workflow/terminal-outcome-event.json",
        root / "workflow/terminal-closure-state.json",
    )
    closure_binding = workflow_binding(
        root,
        root / "workflow/terminal-closure-state.json",
        closure,
    )
    runtime = create_runtime(FixedClock())
    with pytest.raises(WorkflowRuntimeError, match="terminal"):
        runtime.resume(
            closure,
            closure_binding,
            plan,
            root,
            scheduler,
            root / "workflow/resumed-after-terminal.json",
            root / "workflow/resumed-after-terminal-event.json",
        )
    with pytest.raises(WorkflowRecoveryError, match="terminal"):
        create_recovery(FixedClock()).recover(
            closure,
            closure_binding,
            plan,
            (),
            root,
            scheduler,
            root / "workflow/recovered-after-terminal.json",
            root / "workflow/recovered-after-terminal-event.json",
        )
    old_intent = load_workflow_artifact(
        root / plan_value.intent.reference.path,
        expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
    ).value
    assert isinstance(old_intent, DevelopmentIntent)
    successor_candidate = replace(plan_value.candidate, repository_digest="D" * 64)
    successor = artifact_from_value(
        WorkflowArtifactType.DEVELOPMENT_INTENT,
        replace(old_intent, candidate=successor_candidate),
    )
    successor_path = root / "workflow/terminal-successor.json"
    successor_path.write_bytes(serialize_workflow_artifact(successor))
    (root / "workflow/candidate.json").write_text(
        json.dumps(successor_candidate.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkflowRuntimeError, match="terminal"):
        runtime.supersede(
            closure,
            closure_binding,
            plan,
            successor,
            workflow_binding(root, successor_path, successor),
            root,
            scheduler,
            root / "workflow/superseded-after-terminal.json",
            root / "workflow/superseded-after-terminal-event.json",
        )
    with pytest.raises(outcome_module.WorkflowOutcomeError, match="terminal"):
        create_outcome(FixedClock()).publish(
            closure,
            closure_binding,
            plan,
            root,
            scheduler,
            root / "workflow/republished-outcome.json",
            root / "workflow/republished-outcome-event.json",
            root / "workflow/republished-outcome-state.json",
        )


def test_all_outcome_dispositions_and_completion_profiles_are_fail_closed(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan_artifact, _ = create_plan(root)
    scheduler = create_scheduler(root)
    transition = create_runtime(FixedClock()).run(
        plan_artifact,
        root,
        scheduler,
        root / "workflow/profile-state.json",
        root / "workflow/profile-event.json",
    )
    plan = plan_artifact.value
    state = transition.state.value
    assert isinstance(plan, IntegratedPlan)
    assert isinstance(state, WorkflowState)
    rejected = replace(state, status=TaskState.REJECTED)
    superseded = replace(state, status=TaskState.SUPERSEDED)
    assert outcome_module.completion_disposition(plan, rejected)[0] is WorkflowDisposition.REJECTED
    assert (
        outcome_module.completion_disposition(plan, superseded)[0] is WorkflowDisposition.SUPERSEDED
    )

    tasks = tuple(
        replace(item, state=TaskState.COMPLETED, outcome=TaskOutcome.SUCCEEDED)
        for item in state.tasks
    )
    review_plan = replace(
        plan,
        completion_profile=CompletionProfile.INDEPENDENT_REVIEW_ACCEPTED,
        required_gate_ids=("G1", "G2", "G3"),
    )
    review_state = replace(
        state,
        status=TaskState.COMPLETED,
        tasks=tasks,
        gates=tuple(
            GateObservation(gate, GateStatus.PASS, (), ()) for gate in review_plan.required_gate_ids
        ),
        handoff_id="HANDOFF-M8-COMPLETE",
        handoff_status="completed",
        review_ids=(),
        blockers=(),
    )
    disposition, blockers = outcome_module.completion_disposition(review_plan, review_state)
    assert disposition is WorkflowDisposition.BLOCKED
    assert "review-evidence-unavailable" in {item[0] for item in blockers}

    release_plan = replace(
        plan,
        completion_profile=CompletionProfile.RELEASE_CANDIDATE_READY,
        required_gate_ids=("G1", "G2", "G3", "G4"),
        ui_required=True,
    )
    release_state = replace(
        review_state,
        gates=(
            GateObservation("G1", GateStatus.PASS, (), ()),
            GateObservation("G2", GateStatus.PASS, (), ()),
            GateObservation("G3", GateStatus.PASS, (), ()),
            GateObservation("G4", GateStatus.NOT_VERIFIED, (), ("ui-missing",)),
        ),
        review_ids=("REVIEW-M8-ONE",),
        ambiguities=("external-effect-ambiguous",),
        blockers=(WorkflowBlocker("native-blocker", ("G4",)),),
    )
    disposition, blockers = outcome_module.completion_disposition(release_plan, release_state)
    assert disposition is WorkflowDisposition.BLOCKED
    assert blockers == (("native-blocker", ("G4",)),)

    unshortcircuited = replace(
        release_state,
        status=TaskState.RUNNING,
        solver_verification_ids=(),
        handoff_id=None,
        handoff_status=None,
        blockers=(),
    )
    release_plan_with_solver = replace(
        release_plan,
        solver_requests=(release_plan.task_graph,),
    )
    disposition, blockers = outcome_module.completion_disposition(
        release_plan_with_solver,
        unshortcircuited,
    )
    assert disposition is WorkflowDisposition.BLOCKED
    codes = {item[0] for item in blockers}
    assert {
        "solver-evidence-unavailable",
        "handoff-not-completed",
        "ui-evidence-unavailable",
        "external-effect-ambiguous",
        "workflow-state-not-completed",
    } <= codes

    with pytest.raises(outcome_module.WorkflowOutcomeError, match="terminal Event"):
        outcome_module._terminal_event_time(state, root, None)
    with pytest.raises(outcome_module.WorkflowOutcomeError, match="binding drifted"):
        outcome_module._terminal_event_time(
            replace(
                state,
                latest_event=replace(
                    state.latest_event,
                    artifact_id="M8-WORKFLOW-EVENT-" + "F" * 64,
                ),
            ),
            root,
            None,
        )
    assert "rejected proposal" in outcome_module._next_action(
        WorkflowDisposition.REJECTED,
        (),
    )

    with pytest.raises(outcome_module.WorkflowOutcomeError, match="Workflow State"):
        create_outcome(FixedClock())._validated_values(
            plan_artifact, plan_artifact, root, scheduler
        )
    with pytest.raises(outcome_module.WorkflowOutcomeError, match="Integrated Plan"):
        create_outcome(FixedClock())._validated_values(
            transition.state, transition.state, root, scheduler
        )
    with pytest.raises(outcome_module.WorkflowOutcomeError, match="timezone"):
        outcome_module._format_utc(datetime(2026, 8, 1))
    assert transition.state.artifact_type is WorkflowArtifactType.WORKFLOW_STATE
