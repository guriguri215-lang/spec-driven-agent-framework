"""M8 one-tick runtime and immutable Event/State publication tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import sdaqf.adapters.scheduler as scheduler_module
import sdaqf.application.workflow_runtime as runtime_module
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.workflow_contracts import (
    WorkflowContractError,
    artifact_from_value,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_planning import artifact_reference_for
from sdaqf.application.workflow_runtime import WorkflowRuntimeError
from sdaqf.domain.scheduler import (
    Blocker,
    MailboxMessage,
    SchedulerState,
    TaskOutcome,
    TaskState,
    WorkflowEpochPhase,
)
from sdaqf.domain.workflow import (
    CompletionProfile,
    EffectDisposition,
    GateObservation,
    GateStatus,
    IntegratedPlan,
    MeasurementStatus,
    WorkflowArtifactType,
    WorkflowBlocker,
    WorkflowDecision,
    WorkflowDecisionKind,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowOutcome,
    WorkflowState,
    WorkflowTaskProjection,
    WorkflowTerminalObservation,
    WorkflowTerminalObservationCause,
)
from tests.m8_workflow_helpers import (
    FixedClock,
    create_plan,
    create_runtime,
    create_scheduler,
    create_workspace,
    workflow_binding,
)


def test_runtime_publishes_event_before_state_and_never_dispatches(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    state_path = root / "workflow/state-1.json"
    event_path = root / "workflow/event-1.json"
    transition = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        state_path,
        event_path,
    )
    assert event_path.is_file() and state_path.is_file()
    assert transition.host_dispatch_performed is False
    assert len(transition.outgoing_intent_ids) == 1
    event = transition.event.value
    state = transition.state.value
    assert isinstance(event, WorkflowEvent)
    assert isinstance(state, WorkflowState)
    assert event.sequence == 1
    assert event.prior_state_id is None
    assert state.latest_event.artifact_id == transition.event.artifact_id
    assert state.status is TaskState.COMPLETED


def test_runtime_offers_exact_dispatch_only_to_explicit_agent_host(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)

    class RecordingHost:
        def __init__(self) -> None:
            self.dispatched: list[MailboxMessage] = []
            self.cancelled: list[MailboxMessage] = []

        def dispatch(self, message: MailboxMessage) -> None:
            self.dispatched.append(message)

        def cancel(self, message: MailboxMessage) -> None:
            self.cancelled.append(message)

    host = RecordingHost()
    transition = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/host-state.json",
        root / "workflow/host-event.json",
        agent_host=host,
    )

    assert transition.host_dispatch_performed is True
    assert len(host.dispatched) == 1
    assert host.cancelled == []
    assert transition.outgoing_intent_ids == (
        next(
            artifact.artifact_id
            for artifact in SQLiteSchedulerStore(scheduler, root).export("messages")
            if artifact.value == host.dispatched[0]
        ),
    )


def test_host_failure_returns_committed_transition_and_resume_reoffers_exact_intent(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)

    class FailingOnceHost:
        def __init__(self) -> None:
            self.attempted: list[MailboxMessage] = []

        def dispatch(self, message: MailboxMessage) -> None:
            self.attempted.append(message)
            if len(self.attempted) == 1:
                raise RuntimeError("injected post-publication host failure")

        def cancel(self, message: MailboxMessage) -> None:
            raise AssertionError(f"unexpected cancellation: {message}")

    runtime = create_runtime(FixedClock())
    host = FailingOnceHost()
    first_state_path = root / "workflow/host-retry-state-1.json"
    first_event_path = root / "workflow/host-retry-event-1.json"
    first = runtime.run(
        plan,
        root,
        scheduler,
        first_state_path,
        first_event_path,
        agent_host=host,
    )

    assert first.host_dispatch_performed is False
    assert first_state_path.is_file() and first_event_path.is_file()
    head = SQLiteSchedulerStore(scheduler, root).workflow_head(plan.artifact_id)
    assert head is not None
    assert head.workflow_state_id == first.state.artifact_id

    second = runtime.resume(
        first.state,
        workflow_binding(root, first_state_path, first.state),
        plan,
        root,
        scheduler,
        root / "workflow/host-retry-state-2.json",
        root / "workflow/host-retry-event-2.json",
        agent_host=host,
    )

    assert second.host_dispatch_performed is True
    assert second.outgoing_intent_ids == ()
    assert len(host.attempted) == 2
    assert host.attempted[0] == host.attempted[1]
    persisted_id = next(
        artifact.artifact_id
        for artifact in SQLiteSchedulerStore(scheduler, root).export("messages")
        if artifact.value == host.attempted[1]
    )
    assert first.outgoing_intent_ids == (persisted_id,)


def test_runtime_finalizes_authenticated_native_observation_with_exact_blocker(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    store = SQLiteSchedulerStore(scheduler, root)
    native = store.status()
    plan_value = plan.value
    assert isinstance(plan_value, IntegratedPlan)
    runtime = create_runtime(FixedClock())
    observation = WorkflowTerminalObservation(
        WorkflowTerminalObservationCause.STALE_CONTEXT,
        native.artifact_id,
        store.current_event_head_id,
        (plan_value.context_snapshot.artifact_id,),
    )
    event_path = root / "workflow/observed-terminal-event.json"
    state_path = root / "workflow/observed-terminal-state.json"
    outcome_path = root / "workflow/observed-outcome.json"
    transition = runtime.finalize_observation(
        plan,
        root,
        scheduler,
        observation,
        event_path,
        state_path,
        outcome_path,
    )
    assert transition.outcome is not None
    state = transition.state.value
    outcome = transition.outcome.value
    assert isinstance(state, WorkflowState)
    assert isinstance(outcome, WorkflowOutcome)
    assert tuple(item.code for item in state.blockers) == ("stale-context",)
    assert tuple(item.code for item in outcome.blockers) == ("stale-context",)
    measurements = {item.name: item for item in state.measurements}
    assert (
        measurements["requirements.blocking_diagnostic_count"].status
        is MeasurementStatus.OBSERVED
    )
    assert measurements["context.stale_required_count"].status is MeasurementStatus.OBSERVED
    head = store.workflow_head(plan.artifact_id)
    assert head is not None
    assert head.phase is WorkflowEpochPhase.TERMINAL_CONFIRMED
    assert head.workflow_state_id == transition.state.artifact_id
    assert head.outcome_id == transition.outcome.artifact_id
    retried = runtime.finalize_observation(
        plan,
        root,
        scheduler,
        observation,
        event_path,
        state_path,
        outcome_path,
    )
    assert retried.event.artifact_id == transition.event.artifact_id
    assert retried.state.artifact_id == transition.state.artifact_id
    assert retried.outcome is not None
    assert retried.outcome.artifact_id == transition.outcome.artifact_id

    advanced = store.tick(
        root,
        "HST-HISTORICAL-OBSERVATION",
        (),
        FixedClock().now() + timedelta(seconds=1),
    ).state.value
    assert isinstance(advanced, SchedulerState)
    assert advanced.event_sequence > state.scheduler_event_sequence
    status = runtime.status(transition.state, plan, root, scheduler)
    assert status["valid"] is True
    assert status["scheduler_advanced"] is True
    assert status["authoritative_state_id"] == transition.state.artifact_id

    validated_plan, _, publication_observation = runtime._validate_inputs(
        plan,
        transition.state,
        root,
        scheduler,
    )
    current_artifact = store.status()
    current = current_artifact.value
    assert isinstance(current, SchedulerState)
    future_state = replace(
        state,
        scheduler_event_sequence=current.event_sequence + 1,
    )
    future_artifact = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_STATE,
        future_state,
    )
    with pytest.raises(WorkflowRuntimeError, match="extends beyond"):
        runtime._require_exact_state(
            plan.artifact_id,
            validated_plan,
            future_artifact,
            future_state,
            current,
            store,
            root,
            publication_observation,
        )

    replay_mismatch = replace(
        state,
        scheduler_state_id="M6-SCHEDULER-STATE-" + "A" * 64,
    )
    replay_mismatch_artifact = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_STATE,
        replay_mismatch,
    )
    with pytest.raises(WorkflowRuntimeError, match="does not match M6 event replay"):
        runtime._require_exact_state(
            plan.artifact_id,
            validated_plan,
            replay_mismatch_artifact,
            replay_mismatch,
            current,
            store,
            root,
            publication_observation,
        )

    projection_mismatch = replace(state, status=TaskState.REJECTED)
    projection_mismatch_artifact = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_STATE,
        projection_mismatch,
    )
    with pytest.raises(WorkflowRuntimeError, match="exact native-derived projection"):
        runtime._require_exact_state(
            plan.artifact_id,
            validated_plan,
            projection_mismatch_artifact,
            projection_mismatch,
            current,
            store,
            root,
            publication_observation,
        )


def test_every_rehashed_event_field_is_rederived_from_native_chain(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    runtime = create_runtime(FixedClock())
    first_state_path = root / "workflow/semantic-state-1.json"
    first = runtime.run(
        plan,
        root,
        scheduler,
        first_state_path,
        root / "workflow/semantic-event-1.json",
    )
    second = runtime.resume(
        first.state,
        workflow_binding(root, first_state_path, first.state),
        plan,
        root,
        scheduler,
        root / "workflow/semantic-state-2.json",
        root / "workflow/semantic-event-2.json",
    )
    runtime.status(second.state, plan, root, scheduler)
    event = second.event.value
    state = second.state.value
    assert isinstance(event, WorkflowEvent)
    assert isinstance(state, WorkflowState)
    assert event.prior_state is not None
    forged_prior_id = "M8-WORKFLOW-STATE-" + "A" * 64
    mutations: tuple[dict[str, object], ...] = (
        {
            "prior_state_id": forged_prior_id,
            "prior_state": replace(event.prior_state, artifact_id=forged_prior_id),
        },
        {"before_status": TaskState.PLANNED},
        {"after_status": TaskState.REJECTED},
        {"scheduler_event_head_before": "A" * 64},
        {"scheduler_event_head_after": "A" * 64},
        {"cause": WorkflowEventCause.GATE_EVALUATED},
        {"native_input_ids": (*event.native_input_ids, "FORGED-INPUT")},
        {"native_output_ids": (*event.native_output_ids, "FORGED-OUTPUT")},
        {"effect_disposition": EffectDisposition.AMBIGUOUS},
        {"approval_id": "APR-FORGED"},
        {"idempotency_key": "M8-IDEM-" + "A" * 64},
        {"recorded_at": "2025-08-01T00:00:00Z"},
        {"actor": "forged workflow actor"},
        {"reason_codes": (*event.reason_codes, "forged-reason")},
        {"task_id": "TSK-FORGED"},
    )
    for index, fields in enumerate(mutations):
        with pytest.raises((WorkflowContractError, WorkflowRuntimeError)):
            forged_event = artifact_from_value(
                WorkflowArtifactType.WORKFLOW_EVENT,
                replace(event, **fields),  # type: ignore[arg-type]
            )
            event_path = root / f"workflow/semantic-forged-event-{index}.json"
            event_path.write_bytes(serialize_workflow_artifact(forged_event))
            binding = replace(
                state.latest_event,
                artifact_id=forged_event.artifact_id,
                reference=artifact_reference_for(root, event_path),
            )
            state_fields: dict[str, object] = {
                "event_chain": (*state.event_chain[:-1], binding),
                "latest_event": binding,
            }
            if "after_status" in fields:
                state_fields["status"] = fields["after_status"]
            if "scheduler_event_head_after" in fields:
                state_fields["scheduler_event_head_sha256"] = fields["scheduler_event_head_after"]
            if "recorded_at" in fields:
                state_fields["recorded_at"] = fields["recorded_at"]
            forged_state = artifact_from_value(
                WorkflowArtifactType.WORKFLOW_STATE,
                replace(state, **state_fields),  # type: ignore[arg-type]
            )
            runtime.status(forged_state, plan, root, scheduler)


def test_resume_reloads_prior_event_and_extends_m8_chain(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    runtime = create_runtime(FixedClock())
    first = runtime.run(
        plan,
        root,
        scheduler,
        root / "workflow/state-1.json",
        root / "workflow/event-1.json",
    )
    second = runtime.resume(
        first.state,
        workflow_binding(root, root / "workflow/state-1.json", first.state),
        plan,
        root,
        scheduler,
        root / "workflow/state-2.json",
        root / "workflow/event-2.json",
    )
    first_state = first.state.value
    second_event = second.event.value
    second_state = second.state.value
    assert isinstance(first_state, WorkflowState)
    assert isinstance(second_event, WorkflowEvent)
    assert isinstance(second_state, WorkflowState)
    assert second_event.previous_event_id == first.event.artifact_id
    assert second_event.prior_state_id == first.state.artifact_id
    assert second_state.transition_count == 2
    assert second.host_dispatch_performed is False


def test_status_is_read_only_and_reports_native_scheduler_advance(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    runtime = create_runtime(FixedClock())
    transition = runtime.run(
        plan,
        root,
        scheduler,
        root / "workflow/state.json",
        root / "workflow/event.json",
    )
    before = scheduler.read_bytes()
    status = runtime.status(transition.state, plan, root, scheduler)
    assert status["valid"] is True
    assert status["side_effect_free"] is True
    assert scheduler.read_bytes() == before


def test_runtime_helpers_cover_status_gate_blocker_and_cost_branches(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan_artifact, _ = create_plan(root)
    scheduler = create_scheduler(root)
    transition = create_runtime(FixedClock()).run(
        plan_artifact,
        root,
        scheduler,
        root / "workflow/helper-state.json",
        root / "workflow/helper-event.json",
    )
    plan = plan_artifact.value
    state = transition.state.value
    assert isinstance(plan, IntegratedPlan)
    assert isinstance(state, WorkflowState)
    task = state.tasks[0]
    implementation = replace(
        plan,
        completion_profile=CompletionProfile.IMPLEMENTATION_VERIFIED,
        required_gate_ids=("G1", "G2", "G3"),
    )
    complete_task = replace(
        task,
        state=TaskState.COMPLETED,
        outcome=TaskOutcome.SUCCEEDED,
    )
    blocking_decision = WorkflowDecision(
        "gate",
        "G1",
        WorkflowDecisionKind.UNCERTAINTY,
        "blocking-diagnostic",
        (plan.task_graph.artifact_id,),
        True,
    )
    blocking_plan = replace(
        implementation,
        decisions=tuple(
            sorted(
                (*implementation.decisions, blocking_decision),
                key=lambda item: (
                    item.subject_kind,
                    item.subject_id,
                    item.kind.value,
                    item.reason_code,
                    item.references,
                ),
            )
        ),
    )
    gates = runtime_module._derive_gates(
        blocking_plan,
        (complete_task,),
        (),
        (),
        None,
        (),
        False,
    )
    assert gates[0].status is GateStatus.FAIL
    assert gates[1].blocker_codes == ("evidence-unavailable", "handoff-unavailable")
    assert gates[2].blocker_codes == ("g3-not-verified",)
    reachable = runtime_module._derive_gates(
        replace(
            implementation,
            completion_profile=CompletionProfile.RELEASE_CANDIDATE_READY,
            required_gate_ids=("G1", "G2", "G3", "G4"),
        ),
        (complete_task,),
        ("EVD-M8-VERIFIED",),
        ("REV-M8-ACCEPTED",),
        "completed",
        ("M3-GATE-G4-" + "A" * 64,),
        True,
    )
    assert all(item.status is GateStatus.PASS for item in reachable)
    blockers = runtime_module._derive_blockers(
        replace(blocking_plan, ui_required=True),
        (replace(complete_task, blocker_codes=("task-blocked",)),),
        gates,
        ("external-effect-ambiguous",),
    )
    assert {
        "blocking-diagnostic",
        "task-blocked",
        "external-effect-ambiguous",
        "ui-evidence-unavailable",
    } <= {item.code for item in blockers}

    statuses = {
        runtime_module._derive_status(plan, (task,), (), ()),
        runtime_module._derive_status(
            implementation, (replace(task, state=TaskState.REJECTED),), (), ()
        ),
        runtime_module._derive_status(
            implementation, (replace(task, state=TaskState.SUPERSEDED),), (), ()
        ),
        runtime_module._derive_status(
            implementation, (replace(task, state=TaskState.BLOCKED),), (), ()
        ),
        runtime_module._derive_status(
            implementation,
            (complete_task,),
            (WorkflowBlocker("blocked", ("G2",)),),
            (),
        ),
        runtime_module._derive_status(implementation, (complete_task,), (), ()),
        runtime_module._derive_status(
            implementation, (replace(task, state=TaskState.RUNNING),), (), ()
        ),
        runtime_module._derive_status(
            implementation, (replace(task, state=TaskState.VERIFICATION),), (), ()
        ),
        runtime_module._derive_status(
            implementation, (replace(task, state=TaskState.READY),), (), ()
        ),
        runtime_module._derive_status(
            implementation, (replace(task, state=TaskState.PLANNED),), (), ()
        ),
    }
    assert statuses == set(TaskState)

    native_artifact = SQLiteSchedulerStore(scheduler, root).status()
    native = native_artifact.value
    assert isinstance(native, SchedulerState)
    available_plan = replace(
        plan,
        budget=replace(
            plan.budget,
            cost_status="available",
            currency="USD",
            max_microunits=25,
        ),
    )
    measurements = runtime_module._derive_measurements(
        plan_artifact.artifact_id,
        available_plan,
        native,
        state.tasks,
        ("APR-M8-ONE",),
        ("external-effect-ambiguous",),
    )
    cost = next(
        item for item in measurements if item.name == "available_cost.budget_microunits"
    )
    assert cost.value == 25


def test_runtime_cause_lineage_and_pure_helper_failures(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan_artifact, _ = create_plan(root)
    scheduler = create_scheduler(root)
    runtime = create_runtime(FixedClock())
    transition = runtime.run(
        plan_artifact,
        root,
        scheduler,
        root / "workflow/cause-state.json",
        root / "workflow/cause-event.json",
    )
    plan = plan_artifact.value
    prior = transition.state.value
    assert isinstance(plan, IntegratedPlan)
    assert isinstance(prior, WorkflowState)
    store = SQLiteSchedulerStore(scheduler, root)
    native = store.status().value
    assert isinstance(native, SchedulerState)
    approval_task = replace(
        native.tasks[0],
        blockers=(Blocker("approval-required", ("APR-M8",)),),
    )
    ambiguity_cause = runtime._event_cause(
        plan, prior, native, (), (), ("external-effect-ambiguous",)
    )
    approval_blocked_cause = runtime._event_cause(
        plan, prior, replace(native, tasks=(approval_task,)), (), (), ()
    )
    approval_revalidated_cause = runtime._event_cause(
        plan, prior, native, ("M8-EFFECT-X",), ("APR-M8",), ()
    )
    assert ambiguity_cause is WorkflowEventCause.AMBIGUITY_RECORDED
    assert approval_blocked_cause is WorkflowEventCause.APPROVAL_BLOCKED
    assert approval_revalidated_cause is WorkflowEventCause.APPROVAL_REVALIDATED
    assert (
        runtime._event_cause(plan, None, native, (), (), ()) is WorkflowEventCause.RUNTIME_STARTED
    )
    assert (
        runtime._event_cause(plan, prior, native, (), (), ())
        is WorkflowEventCause.SCHEDULER_ADVANCED
    )

    reasons = runtime_module._transition_reason_codes(
        WorkflowEventCause.APPROVAL_REVALIDATED,
        ("M8-EFFECT-X",),
        ("APR-M8",),
        ("external-effect-ambiguous",),
    )
    assert "protected-effect-revalidated" in reasons
    assert "approval-revalidated" in reasons
    assert "external-effect-ambiguous" in reasons
    assert runtime_module._idempotency_key(
        plan_artifact.artifact_id, 1, None, native.event_head_sha256
    ).startswith("M8-IDEM-")
    with pytest.raises(WorkflowRuntimeError, match="escapes"):
        runtime_module._output_reference(root, root.parent / "outside.json", b"{}\n")
    with pytest.raises(WorkflowRuntimeError, match="timezone"):
        runtime_module._format_utc(datetime(2026, 8, 1))
    with pytest.raises(WorkflowRuntimeError, match="Integrated Plan"):
        runtime._validate_inputs(transition.event, None, root, scheduler)
    with pytest.raises(WorkflowRuntimeError, match="Workflow State"):
        runtime._validate_inputs(plan_artifact, transition.event, root, scheduler)
    with pytest.raises(WorkflowRuntimeError, match="stale"):
        runtime._validate_scheduler_lineage(
            plan,
            None,
            store,
            replace(native, graph_id="M6-TASK-GRAPH-STALE"),
        )
    with pytest.raises(WorkflowRuntimeError, match="moved behind"):
        runtime._validate_scheduler_lineage(
            plan,
            prior,
            store,
            replace(native, event_sequence=prior.scheduler_event_sequence - 1),
        )
    with pytest.raises(WorkflowRuntimeError, match="drifted"):
        runtime._validate_scheduler_lineage(
            plan,
            prior,
            store,
            replace(native, event_head_sha256="A" * 64),
        )


def test_ui_required_with_native_g4_pass_has_no_synthetic_ui_blocker(
    tmp_path: Path,
) -> None:
    """G4 native PASS, rather than the ui_required flag, controls readiness."""

    root = create_workspace(tmp_path)
    plan_artifact, _ = create_plan(root)
    plan = plan_artifact.value
    assert isinstance(plan, IntegratedPlan)
    release_plan = replace(
        plan,
        completion_profile=CompletionProfile.RELEASE_CANDIDATE_READY,
        required_gate_ids=("G1", "G2", "G3", "G4"),
        ui_required=True,
    )
    tasks = (
        WorkflowTaskProjection(
            "TSK-M8-UI-PASS",
            TaskState.COMPLETED,
            TaskOutcome.SUCCEEDED,
            1,
            1,
            (),
        ),
    )
    gates = tuple(
        GateObservation(gate_id, GateStatus.PASS, (f"EVIDENCE-{gate_id}",), ())
        for gate_id in release_plan.required_gate_ids
    )

    blockers = runtime_module._derive_blockers(release_plan, tasks, gates, ())
    assert "ui-evidence-unavailable" not in {item.code for item in blockers}


def test_runtime_rejects_publication_candidate_output_paths(tmp_path: Path) -> None:
    """Mutable Workflow artifacts and the Scheduler DB stay runtime-private."""

    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    publication = root / "publication"
    publication.mkdir()
    with pytest.raises(WorkflowRuntimeError, match="runtime-private"):
        create_runtime(FixedClock()).run(
            plan,
            root,
            scheduler,
            publication / "state.json",
            publication / "event.json",
        )


def test_unobservable_attempt_measurements_are_not_fabricated(tmp_path: Path) -> None:
    """Calls that leave no durable Event cannot be reported as observed attempts."""

    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    transition = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/measurement-state.json",
        root / "workflow/measurement-event.json",
    )
    state = transition.state.value
    assert isinstance(state, WorkflowState)
    measurements = {item.name: item for item in state.measurements}
    assert measurements["recovery.resume_attempt_count"].status.value == "not-available"
    assert measurements["recovery.recovery_attempt_count"].status.value == "not-available"
    for name in (
        "evidence.claim_count",
        "evidence.verified_claim_count",
        "evidence.unverified_claim_count",
        "evidence.known_problem_count",
        "evidence.missing_evidence_count",
        "handoff.handoff_created_count",
        "handoff.handoff_resume_failure_count",
        "handoff.incomplete_item_count",
        "handoff.open_decision_count",
        "handoff.known_problem_count",
    ):
        measurement = measurements[name]
        assert measurement.status.value == "not-available"
        assert measurement.value is None
        assert measurement.unit is None


def test_historical_native_replay_uses_adapter_authority_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/replay-state.json",
        root / "workflow/replay-event.json",
    )
    store = SQLiteSchedulerStore(scheduler, root)
    current = store.status()
    native = current.value
    assert isinstance(native, SchedulerState)
    assert runtime_module._replay_scheduler_state(store, native.event_sequence) == current

    def _fail_rebuild(*_args: object) -> None:
        raise scheduler_module.SchedulerAdapterError("injected rebuild failure")

    monkeypatch.setattr(store, "historical_status", _fail_rebuild)
    with pytest.raises(WorkflowRuntimeError, match="replay failed closed"):
        runtime_module._replay_scheduler_state(store, native.event_sequence)


def test_runtime_terminal_semantics_and_private_paths_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    transition = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/semantic-state.json",
        root / "workflow/semantic-event.json",
    )
    event = transition.event.value
    state = transition.state.value
    assert isinstance(event, WorkflowEvent)
    assert isinstance(state, WorkflowState)

    with pytest.raises(WorkflowRuntimeError, match="reason code is invalid"):
        runtime_module._terminal_observation_cause(
            replace(event, reason_codes=("native-observation-closed",)),
        )
    with pytest.raises(WorkflowRuntimeError, match="cause is not closed"):
        runtime_module._terminal_observation_cause(
            replace(event, reason_codes=("native-observation-closed", "unknown-cause")),
        )
    for cause in (
        WorkflowEventCause.RECOVERY_OBSERVED,
        WorkflowEventCause.PLAN_SUPERSEDED,
        WorkflowEventCause.OUTCOME_PRODUCED,
    ):
        with pytest.raises(WorkflowRuntimeError, match="semantic"):
            runtime_module._semantic_event_cause(
                replace(event, cause=cause),
                None,
                state,
                (),
                (),
            )

    with pytest.raises(WorkflowRuntimeError, match="output escapes"):
        runtime_module._output_reference(root, root / ".." / "outside.json", b"{}\n")
    with pytest.raises(WorkflowRuntimeError, match="path escapes"):
        runtime_module._require_runtime_private_path(
            root,
            root / ".." / "outside.json",
            existing=False,
        )
    with pytest.raises(WorkflowRuntimeError, match="not a regular file"):
        runtime_module._require_runtime_private_path(
            root,
            root / "workflow/missing.json",
            existing=True,
        )

    workflow = root / "workflow"
    monkeypatch.setattr(
        runtime_module,
        "is_reparse_point",
        lambda path: Path(path) == workflow,
    )
    with pytest.raises(WorkflowRuntimeError, match="parent is invalid"):
        runtime_module._require_runtime_private_path(
            root,
            workflow / "new.json",
            existing=False,
        )
    linked = workflow / "linked"
    parent = linked / "regular"
    parent.mkdir(parents=True)
    monkeypatch.setattr(
        runtime_module,
        "is_reparse_point",
        lambda path: Path(path) == linked,
    )
    with pytest.raises(WorkflowRuntimeError, match="contains a link"):
        runtime_module._require_runtime_private_path(
            root,
            parent / "new.json",
            existing=False,
        )
    with pytest.raises(WorkflowRuntimeError, match="timestamp is invalid"):
        runtime_module._parse_utc("not-a-time")
    with pytest.raises(WorkflowRuntimeError, match="timestamp is not UTC"):
        runtime_module._parse_utc("2026-08-01T00:00:00")
