"""Successor lifecycle compatibility across distinct M6 workflow authorities."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.scheduler import SchedulerService
from sdaqf.application.workflow_contracts import WorkflowContractError
from sdaqf.application.workflow_recovery import WorkflowRecoveryError
from sdaqf.domain.scheduler import WorkflowEpochPhase
from sdaqf.domain.workflow import (
    IntegratedPlan,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowOutcome,
    WorkflowState,
    WorkflowTerminalObservation,
    WorkflowTerminalObservationCause,
)
from tests.m8_workflow_helpers import (
    FixedClock,
    create_plan,
    create_recovery,
    create_runtime,
    create_scheduler,
    create_successor_workflow,
    create_workspace,
    workflow_binding,
)


def test_successor_run_status_and_resume_revalidate_predecessor_authority(
    tmp_path: Path,
) -> None:
    fixture = create_successor_workflow(tmp_path)
    runtime = create_runtime(FixedClock())
    state_path = fixture.root / "workflow/successor-lifecycle-state.json"
    first = runtime.run(
        fixture.successor_plan,
        fixture.root,
        fixture.successor_scheduler_state,
        state_path,
        fixture.root / "workflow/successor-lifecycle-event.json",
        predecessor_scheduler_state=fixture.predecessor_scheduler_state,
    )
    with pytest.raises(WorkflowContractError, match="required exactly"):
        runtime.status(
            first.state,
            fixture.successor_plan,
            fixture.root,
            fixture.successor_scheduler_state,
        )
    status = runtime.status(
        first.state,
        fixture.successor_plan,
        fixture.root,
        fixture.successor_scheduler_state,
        predecessor_scheduler_state=fixture.predecessor_scheduler_state,
    )
    assert status["valid"] is True
    assert status["side_effect_free"] is True
    resumed = runtime.resume(
        first.state,
        workflow_binding(fixture.root, state_path, first.state),
        fixture.successor_plan,
        fixture.root,
        fixture.successor_scheduler_state,
        fixture.root / "workflow/successor-resumed-state.json",
        fixture.root / "workflow/successor-resumed-event.json",
        predecessor_scheduler_state=fixture.predecessor_scheduler_state,
    )
    resumed_state = resumed.state.value
    assert isinstance(resumed_state, WorkflowState)
    assert resumed_state.transition_count == 2


def test_successor_nonterminal_state_recovery_revalidates_predecessor_authority(
    tmp_path: Path,
) -> None:
    fixture = create_successor_workflow(tmp_path)
    source_path = fixture.root / "workflow/successor-recovery-source-state.json"
    source = create_runtime(FixedClock()).run(
        fixture.successor_plan,
        fixture.root,
        fixture.successor_scheduler_state,
        source_path,
        fixture.root / "workflow/successor-recovery-source-event.json",
        predecessor_scheduler_state=fixture.predecessor_scheduler_state,
    )
    recovery = create_recovery(FixedClock())
    with pytest.raises(WorkflowRecoveryError):
        recovery.recover(
            source.state,
            workflow_binding(fixture.root, source_path, source.state),
            fixture.successor_plan,
            (),
            fixture.root,
            fixture.successor_scheduler_state,
            fixture.root / "workflow/missing-authority-recovered-state.json",
            fixture.root / "workflow/missing-authority-recovery-event.json",
        )
    recovered, event = recovery.recover(
        source.state,
        workflow_binding(fixture.root, source_path, source.state),
        fixture.successor_plan,
        (),
        fixture.root,
        fixture.successor_scheduler_state,
        fixture.root / "workflow/successor-recovered-state.json",
        fixture.root / "workflow/successor-recovery-event.json",
        predecessor_scheduler_state=fixture.predecessor_scheduler_state,
    )
    recovered_state = recovered.value
    recovered_event = event.value
    assert isinstance(recovered_state, WorkflowState)
    assert isinstance(recovered_event, WorkflowEvent)
    assert recovered_event.cause is WorkflowEventCause.RECOVERY_OBSERVED
    assert recovered_event.prior_state_id == source.state.artifact_id


def test_successor_finalize_observation_closes_terminal_epoch(
    tmp_path: Path,
) -> None:
    fixture = create_successor_workflow(tmp_path)
    store = SQLiteSchedulerStore(fixture.successor_scheduler_state, fixture.root)
    native = store.status()
    plan = fixture.successor_plan.value
    assert isinstance(plan, IntegratedPlan)
    observation = WorkflowTerminalObservation(
        WorkflowTerminalObservationCause.STALE_CONTEXT,
        native.artifact_id,
        store.current_event_head_id,
        (plan.context_snapshot.artifact_id,),
    )
    runtime = create_runtime(FixedClock())
    with pytest.raises(WorkflowContractError, match="required exactly"):
        runtime.finalize_observation(
            fixture.successor_plan,
            fixture.root,
            fixture.successor_scheduler_state,
            observation,
            fixture.root / "workflow/missing-authority-terminal-event.json",
            fixture.root / "workflow/missing-authority-terminal-state.json",
            fixture.root / "workflow/missing-authority-outcome.json",
        )
    transition = runtime.finalize_observation(
        fixture.successor_plan,
        fixture.root,
        fixture.successor_scheduler_state,
        observation,
        fixture.root / "workflow/successor-terminal-event.json",
        fixture.root / "workflow/successor-terminal-state.json",
        fixture.root / "workflow/successor-outcome.json",
        predecessor_scheduler_state=fixture.predecessor_scheduler_state,
    )
    assert isinstance(transition.state.value, WorkflowState)
    assert transition.outcome is not None
    assert isinstance(transition.outcome.value, WorkflowOutcome)
    head = store.workflow_head(fixture.successor_plan.artifact_id)
    assert head is not None
    assert head.phase is WorkflowEpochPhase.TERMINAL_CONFIRMED


def test_genesis_default_lifecycle_call_shape_remains_compatible(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    state_path = root / "workflow/genesis-compatible-state.json"
    runtime = create_runtime(FixedClock())
    first = runtime.run(
        plan,
        root,
        scheduler,
        state_path,
        root / "workflow/genesis-compatible-event.json",
    )
    assert runtime.status(first.state, plan, root, scheduler)["valid"] is True
    resumed = runtime.resume(
        first.state,
        workflow_binding(root, state_path, first.state),
        plan,
        root,
        scheduler,
        root / "workflow/genesis-compatible-resumed-state.json",
        root / "workflow/genesis-compatible-resumed-event.json",
    )
    assert isinstance(resumed.state.value, WorkflowState)
    with pytest.raises(WorkflowContractError, match="required exactly"):
        runtime.status(
            resumed.state,
            plan,
            root,
            scheduler,
            predecessor_scheduler_state=scheduler,
        )


def test_successor_lifecycle_rejects_foreign_same_alias_and_stale_authority(
    tmp_path: Path,
) -> None:
    fixture = create_successor_workflow(tmp_path)
    source = create_runtime(FixedClock()).run(
        fixture.successor_plan,
        fixture.root,
        fixture.successor_scheduler_state,
        fixture.root / "workflow/authority-source-state.json",
        fixture.root / "workflow/authority-source-event.json",
        predecessor_scheduler_state=fixture.predecessor_scheduler_state,
    )
    foreign = fixture.root / "workflow/foreign-predecessor-scheduler.sqlite3"
    SchedulerService(FixedClock()).initialize(
        fixture.root / "examples/m6-scheduler/task-graph.json",
        fixture.root,
        foreign,
        workflow_authority=True,
    )
    rejected = (
        foreign,
        fixture.successor_scheduler_state,
        fixture.stale_predecessor_scheduler_state,
    )
    runtime = create_runtime(FixedClock())
    for predecessor in rejected:
        with pytest.raises(WorkflowContractError):
            runtime.status(
                source.state,
                fixture.successor_plan,
                fixture.root,
                fixture.successor_scheduler_state,
                predecessor_scheduler_state=predecessor,
            )

    alias = fixture.root / "workflow/successor-scheduler-alias.sqlite3"
    try:
        os.link(fixture.successor_scheduler_state, alias)
    except OSError as exc:
        pytest.skip(f"hardlink alias is unavailable: {exc}")
    with pytest.raises(WorkflowContractError, match="distinct databases"):
        runtime.status(
            source.state,
            fixture.successor_plan,
            fixture.root,
            fixture.successor_scheduler_state,
            predecessor_scheduler_state=alias,
        )
