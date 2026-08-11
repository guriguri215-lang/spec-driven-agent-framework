"""M8 source-preserving recovery tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

import sdaqf.application.workflow_recovery as recovery_module
from sdaqf.application.workflow_contracts import (
    artifact_from_value,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_planning import artifact_reference_for
from sdaqf.application.workflow_recovery import (
    WorkflowRecoveryError,
    WorkflowRecoveryService,
)
from sdaqf.application.workflow_runtime import WorkflowRuntimeError
from sdaqf.domain.workflow import (
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowState,
)
from tests.m8_workflow_helpers import (
    FixedClock,
    create_plan,
    create_recovery,
    create_runtime,
    create_scheduler,
    create_workspace,
    workflow_binding,
)


def test_recovery_creates_fresh_artifacts_and_preserves_sources(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    runtime = create_runtime(FixedClock())
    source_state_path = root / "workflow/source-state.json"
    source_event_path = root / "workflow/source-event.json"
    source = runtime.run(
        plan,
        root,
        scheduler,
        source_state_path,
        source_event_path,
    )
    original_state = source_state_path.read_bytes()
    original_event = source_event_path.read_bytes()
    recovered, event = create_recovery(FixedClock()).recover(
        source.state,
        workflow_binding(root, root / "workflow/source-state.json", source.state),
        plan,
        (),
        root,
        scheduler,
        root / "workflow/recovered-state.json",
        root / "workflow/recovery-event.json",
    )
    recovered_value = recovered.value
    event_value = event.value
    assert isinstance(recovered_value, WorkflowState)
    assert isinstance(event_value, WorkflowEvent)
    assert event_value.cause is WorkflowEventCause.RECOVERY_OBSERVED
    assert event_value.prior_state_id == source.state.artifact_id
    assert recovered_value.latest_event.artifact_id == event.artifact_id
    assert source_state_path.read_bytes() == original_state
    assert source_event_path.read_bytes() == original_event
    retried_state, retried_event = create_recovery(FixedClock()).recover(
        source.state,
        workflow_binding(root, root / "workflow/source-state.json", source.state),
        plan,
        (),
        root,
        scheduler,
        root / "workflow/recovered-state.json",
        root / "workflow/recovery-event.json",
    )
    assert retried_state.artifact_id == recovered.artifact_id
    assert retried_event.artifact_id == event.artifact_id

    forged_event = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_EVENT,
        replace(event_value, actor="forged recovery actor"),
    )
    forged_event_path = root / "workflow/forged-recovery-event.json"
    forged_event_path.write_bytes(serialize_workflow_artifact(forged_event))
    forged_event_binding = workflow_binding(root, forged_event_path, forged_event)
    forged_state = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_STATE,
        replace(
            recovered_value,
            event_chain=(*recovered_value.event_chain[:-1], forged_event_binding),
            latest_event=forged_event_binding,
        ),
    )
    with pytest.raises(WorkflowRuntimeError, match="recovery disposition"):
        runtime.status(forged_state, plan, root, scheduler)


def test_recovery_retains_ambiguity_instead_of_retrying(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    source = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/source-state.json",
        root / "workflow/source-event.json",
    )
    recovered, _ = create_recovery(FixedClock()).recover(
        source.state,
        workflow_binding(root, root / "workflow/source-state.json", source.state),
        plan,
        (),
        root,
        scheduler,
        root / "workflow/recovered.json",
        root / "workflow/recovery.json",
    )
    assert isinstance(recovered.value, WorkflowState)
    source_value = source.state.value
    assert isinstance(source_value, WorkflowState)
    assert recovered.value.scheduler_state_id == source_value.scheduler_state_id


def test_recovery_validates_orphan_event_chain_and_rebuilds_sequence(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    runtime = create_runtime(FixedClock())
    source = runtime.run(
        plan,
        root,
        scheduler,
        root / "workflow/orphan-source-state.json",
        root / "workflow/orphan-source-event.json",
    )
    orphan = runtime.resume(
        source.state,
        workflow_binding(root, root / "workflow/orphan-source-state.json", source.state),
        plan,
        root,
        scheduler,
        root / "workflow/orphan-unadopted-state.json",
        root / "workflow/orphan-event.json",
    ).event
    source_value = source.state.value
    assert isinstance(source_value, WorkflowState)
    supplied = WorkflowRecoveryService._validate_observed_events(
        source.state,
        plan,
        source_value,
        (orphan,),
    )
    assert supplied == (orphan,)
    orphan_binding = NativeArtifactBinding(
        WorkflowArtifactType.WORKFLOW_EVENT.value,
        orphan.artifact_id,
        artifact_reference_for(root, root / "workflow/orphan-event.json"),
        True,
    )
    with pytest.raises(WorkflowRecoveryError, match="historical recovery"):
        create_recovery(FixedClock()).recover(
            source.state,
            workflow_binding(root, root / "workflow/orphan-source-state.json", source.state),
            plan,
            (orphan,),
            root,
            scheduler,
            root / "workflow/orphan-recovered-state.json",
            root / "workflow/orphan-recovery-event.json",
            (orphan_binding,),
        )

    with pytest.raises(WorkflowRecoveryError, match="duplicates"):
        WorkflowRecoveryService._validate_observed_events(
            source.state, plan, source_value, (orphan, orphan)
        )
    orphan_value = orphan.value
    assert isinstance(orphan_value, WorkflowEvent)
    stale = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_EVENT,
        replace(orphan_value, plan_id="M8-INTEGRATED-PLAN-" + "A" * 64),
    )
    with pytest.raises(WorkflowRecoveryError, match="stale"):
        WorkflowRecoveryService._validate_observed_events(
            source.state, plan, source_value, (stale,)
        )
    broken = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_EVENT,
        replace(orphan_value, previous_event_id="M8-WORKFLOW-EVENT-" + "B" * 64),
    )
    with pytest.raises(WorkflowRecoveryError, match="does not extend"):
        WorkflowRecoveryService._validate_observed_events(
            source.state, plan, source_value, (broken,)
        )
    with pytest.raises(WorkflowRecoveryError, match="Workflow Event"):
        WorkflowRecoveryService._validate_observed_events(
            source.state, plan, source_value, (source.state,)
        )
    with pytest.raises(WorkflowRecoveryError, match="timezone"):
        recovery_module._format_utc(datetime(2026, 8, 1))


def test_recovery_rejects_semantically_invalid_orphan_before_publication(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    runtime = create_runtime(FixedClock())
    source_path = root / "workflow/semantic-source-state.json"
    source = runtime.run(
        plan,
        root,
        scheduler,
        source_path,
        root / "workflow/semantic-source-event.json",
    )
    orphan = runtime.resume(
        source.state,
        workflow_binding(root, source_path, source.state),
        plan,
        root,
        scheduler,
        root / "workflow/semantic-orphan-unadopted-state.json",
        root / "workflow/semantic-orphan-event.json",
    ).event
    orphan_value = orphan.value
    assert isinstance(orphan_value, WorkflowEvent)
    invalid = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_EVENT,
        replace(orphan_value, actor="forged recovery actor"),
    )
    invalid_path = root / "workflow/semantic-invalid-orphan.json"
    invalid_path.write_bytes(serialize_workflow_artifact(invalid))
    output_state = root / "workflow/semantic-invalid-recovered-state.json"
    output_event = root / "workflow/semantic-invalid-recovery-event.json"
    with pytest.raises(WorkflowRecoveryError, match="semantic"):
        create_recovery(FixedClock()).recover(
            source.state,
            workflow_binding(root, source_path, source.state),
            plan,
            (invalid,),
            root,
            scheduler,
            output_state,
            output_event,
            (workflow_binding(root, invalid_path, invalid),),
        )
    assert not output_state.exists()
    assert not output_event.exists()
