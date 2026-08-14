"""Production-path tests for the transient read-only M8 final report."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import sdaqf.application.baselines as baselines_module
import sdaqf.application.workflow_explanation as explanation_module
import sdaqf.application.workflow_outcome as outcome_module
import sdaqf.application.workflow_runtime as runtime_module
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.workflow_contracts import artifact_from_value
from sdaqf.application.workflow_explanation import (
    EpistemicClassification,
    WorkflowFinalReportError,
    WorkflowFinalReportService,
    WorkflowReportSourceKind,
)
from sdaqf.domain.scheduler import SchedulerState as NativeSchedulerState
from sdaqf.domain.scheduler import (
    WorkflowEpochPhase,
    WorkflowReceiptStatus,
)
from sdaqf.domain.workflow import (
    IntegratedPlan,
    WorkflowArtifactType,
    WorkflowOutcome,
    WorkflowState,
)
from tests.m8_workflow_helpers import (
    FixedClock,
    create_outcome,
    create_plan,
    create_planner,
    create_runtime,
    create_scheduler,
    create_workspace,
    workflow_binding,
)
from tests.test_m6_skill_provenance import (
    HOST_ID,
    _create_implementation_plan,
    _create_skill_case,
    _start_skill_task,
    _task_result,
    _write_candidate_ledger,
)


def test_terminal_report_reauthenticates_receipts_and_is_side_effect_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    _add_requirement_assumption(root)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    source_path = root / "workflow/report-source-state.json"
    source = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        source_path,
        root / "workflow/report-source-event.json",
    )
    outcome, _event, closure = create_outcome(FixedClock()).publish(
        source.state,
        workflow_binding(root, source_path, source.state),
        plan,
        root,
        scheduler,
        root / "workflow/report-outcome.json",
        root / "workflow/report-terminal-event.json",
        root / "workflow/report-terminal-state.json",
    )
    terminal = _terminal_state_value(closure)
    advanced = SQLiteSchedulerStore(scheduler, root).tick(
        root,
        "HST-HISTORICAL-REPORT",
        (),
        FixedClock().now() + timedelta(seconds=1),
    ).state.value
    assert isinstance(advanced, NativeSchedulerState)
    assert advanced.event_sequence > terminal.scheduler_event_sequence
    before = _tree_digests(root)

    report = WorkflowFinalReportService(create_planner()).report(
        outcome,
        closure,
        plan,
        root,
        scheduler,
    )

    assert report.outcome_id == outcome.artifact_id
    assert report.terminal_state_id == closure.artifact_id
    assumption = next(
        item
        for item in report.claims
        if item.classification is EpistemicClassification.ASSUMPTION
    )
    assert assumption.unresolved_sources[0].source_kind is WorkflowReportSourceKind.USER
    assert report.human_review_required
    assert report.to_dict()["side_effect_free"] is True
    assert _tree_digests(root) == before

    store = SQLiteSchedulerStore(scheduler, root)
    snapshot = store.workflow_receipt_snapshot(plan.artifact_id)
    assert len(snapshot.heads) == 1
    head = snapshot.heads[0]
    valid_runtime_status = {
        "valid": True,
        "side_effect_free": True,
        "authoritative_state_id": closure.artifact_id,
        "authoritative_outcome_id": outcome.artifact_id,
        "epoch_phase": WorkflowEpochPhase.TERMINAL_CONFIRMED.value,
    }

    def assert_snapshot_rejected(snapshot_value: object, match: str) -> None:
        with monkeypatch.context() as patch:
            patch.setattr(
                runtime_module.WorkflowRuntimeService,
                "status",
                lambda *_args, **_kwargs: valid_runtime_status,
            )
            patch.setattr(
                SQLiteSchedulerStore,
                "workflow_receipt_snapshot",
                lambda *_args, **_kwargs: snapshot_value,
            )
            with pytest.raises(WorkflowFinalReportError, match=match):
                WorkflowFinalReportService(create_planner()).report(
                    outcome,
                    closure,
                    plan,
                    root,
                    scheduler,
                )

    assert_snapshot_rejected(
        replace(
            snapshot,
            candidate=replace(snapshot.candidate, git_head="F" * 40),
        ),
        "receipt snapshot",
    )
    assert_snapshot_rejected(replace(snapshot, heads=()), "receipt snapshot")
    assert_snapshot_rejected(
        replace(
            snapshot,
            heads=(replace(head, scheduler_state_id="M6-SCHEDULER-STATE-" + "F" * 64),),
        ),
        "terminal head",
    )
    assert_snapshot_rejected(
        replace(
            snapshot,
            heads=(
                replace(
                    head,
                    receipts=(
                        replace(head.receipts[0], status=WorkflowReceiptStatus.RESERVED),
                        *head.receipts[1:],
                    ),
                ),
            ),
        ),
        "unconfirmed",
    )
    assert_snapshot_rejected(
        replace(
            snapshot,
            heads=(
                replace(
                    head,
                    receipts=tuple(
                        receipt
                        for receipt in head.receipts
                        if receipt.artifact_id != outcome.artifact_id
                    ),
                ),
            ),
        ),
        "lacks one exact",
    )
    assert_snapshot_rejected(
        replace(
            snapshot,
            heads=(replace(head, workflow_event_path="workflow/wrong-event.json"),),
        ),
        "paths disagree",
    )

    with monkeypatch.context() as patch:
        patch.setattr(
            runtime_module.WorkflowRuntimeService,
            "status",
            lambda *_args, **_kwargs: valid_runtime_status,
        )
        patch.setattr(
            explanation_module,
            "load_workflow_artifact",
            lambda *_args, **_kwargs: closure,
        )
        with pytest.raises(WorkflowFinalReportError, match="differs from its M6 receipt"):
            WorkflowFinalReportService(create_planner()).report(
                outcome,
                closure,
                plan,
                root,
                scheduler,
            )

    graph_artifact = store.graph_artifact()
    native_value = store.status().value
    plan_value = plan.value
    assert isinstance(plan_value, IntegratedPlan)

    with monkeypatch.context() as patch:
        patch.setattr(
            runtime_module.WorkflowRuntimeService,
            "status",
            lambda *_args, **_kwargs: valid_runtime_status,
        )
        patch.setattr(
            outcome_module.WorkflowOutcomeService,
            "derive",
            lambda *_args, **_kwargs: outcome,
        )
        patch.setattr(
            SQLiteSchedulerStore,
            "graph_artifact",
            lambda *_args, **_kwargs: replace(
                graph_artifact,
                artifact_id="M6-TASK-GRAPH-" + "F" * 64,
            ),
        )
        with pytest.raises(WorkflowFinalReportError, match="Task Graph"):
            WorkflowFinalReportService(create_planner()).report(
                outcome,
                closure,
                plan,
                root,
                scheduler,
            )

    with monkeypatch.context() as patch:
        patch.setattr(
            runtime_module.WorkflowRuntimeService,
            "status",
            lambda *_args, **_kwargs: valid_runtime_status,
        )
        patch.setattr(
            outcome_module.WorkflowOutcomeService,
            "derive",
            lambda *_args, **_kwargs: outcome,
        )
        patch.setattr(
            SQLiteSchedulerStore,
            "graph_artifact",
            lambda *_args, **_kwargs: replace(graph_artifact, value=native_value),
        )
        with pytest.raises(WorkflowFinalReportError, match="value is unavailable"):
            WorkflowFinalReportService(create_planner()).report(
                outcome,
                closure,
                plan,
                root,
                scheduler,
            )

    with monkeypatch.context() as patch:
        patch.setattr(
            runtime_module.WorkflowRuntimeService,
            "status",
            lambda *_args, **_kwargs: valid_runtime_status,
        )
        patch.setattr(
            outcome_module.WorkflowOutcomeService,
            "derive",
            lambda *_args, **_kwargs: outcome,
        )
        patch.setattr(
            SQLiteSchedulerStore,
            "completed_task_result_messages",
            lambda *_args, **_kwargs: (graph_artifact,),
        )
        with pytest.raises(WorkflowFinalReportError, match="not a Task Result"):
            WorkflowFinalReportService(create_planner()).report(
                outcome,
                closure,
                plan,
                root,
                scheduler,
            )

    baseline = baselines_module.load_baseline(
        root / plan_value.requirement_baseline.path
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            runtime_module.WorkflowRuntimeService,
            "status",
            lambda *_args, **_kwargs: valid_runtime_status,
        )
        patch.setattr(
            outcome_module.WorkflowOutcomeService,
            "derive",
            lambda *_args, **_kwargs: outcome,
        )
        patch.setattr(
            baselines_module,
            "load_baseline",
            lambda *_args, **_kwargs: replace(baseline, baseline_id="RB-" + "F" * 16),
        )
        with pytest.raises(WorkflowFinalReportError, match="Baseline"):
            WorkflowFinalReportService(create_planner()).report(
                outcome,
                closure,
                plan,
                root,
                scheduler,
            )

    outcome_value = outcome.value
    assert isinstance(outcome_value, WorkflowOutcome)
    forged_outcome = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_OUTCOME,
        replace(outcome_value, next_action="Trust a non-reproduced summary."),
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            runtime_module.WorkflowRuntimeService,
            "status",
            lambda *_args, **_kwargs: valid_runtime_status,
        )
        patch.setattr(
            outcome_module.WorkflowOutcomeService,
            "derive",
            lambda *_args, **_kwargs: forged_outcome,
        )
        with pytest.raises(WorkflowFinalReportError, match="does not reproduce"):
            WorkflowFinalReportService(create_planner()).report(
                outcome,
                closure,
                plan,
                root,
                scheduler,
            )

    with monkeypatch.context() as patch:
        patch.setattr(
            runtime_module.WorkflowRuntimeService,
            "status",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("injected")),
        )
        with pytest.raises(WorkflowFinalReportError, match="failed exact read-only"):
            WorkflowFinalReportService(create_planner()).report(
                outcome,
                closure,
                plan,
                root,
                scheduler,
            )


def test_report_rejects_unpublished_nonterminal_authority(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    transition = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/nonterminal-state.json",
        root / "workflow/nonterminal-event.json",
    )
    outcome, _event, _closure = create_outcome(FixedClock()).publish(
        transition.state,
        workflow_binding(
            root,
            root / "workflow/nonterminal-state.json",
            transition.state,
        ),
        plan,
        root,
        scheduler,
        root / "workflow/nonterminal-outcome.json",
        root / "workflow/nonterminal-terminal-event.json",
        root / "workflow/nonterminal-terminal-state.json",
    )

    with pytest.raises(WorkflowFinalReportError, match="lineage"):
        WorkflowFinalReportService(create_planner()).report(
            outcome,
            transition.state,
            plan,
            root,
            scheduler,
        )


def test_report_rejects_tampered_outcome_and_observation_binding(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    source_path = root / "workflow/tamper-source-state.json"
    source = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        source_path,
        root / "workflow/tamper-source-event.json",
    )
    outcome, _event, closure = create_outcome(FixedClock()).publish(
        source.state,
        workflow_binding(root, source_path, source.state),
        plan,
        root,
        scheduler,
        root / "workflow/tamper-outcome.json",
        root / "workflow/tamper-terminal-event.json",
        root / "workflow/tamper-terminal-state.json",
    )
    value = outcome.value
    assert isinstance(value, WorkflowOutcome)
    forged_outcome = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_OUTCOME,
        replace(value, next_action="Trust an unreceipted summary."),
    )

    with pytest.raises(WorkflowFinalReportError):
        WorkflowFinalReportService(create_planner()).report(
            forged_outcome,
            closure,
            plan,
            root,
            scheduler,
        )

    forged_binding_outcome = artifact_from_value(
        WorkflowArtifactType.WORKFLOW_OUTCOME,
        replace(
            value,
            observation_artifacts=(
                _terminal_state_value(closure).latest_event,
            ),
        ),
    )
    with pytest.raises(WorkflowFinalReportError, match="lineage"):
        WorkflowFinalReportService(create_planner()).report(
            forged_binding_outcome,
            closure,
            plan,
            root,
            scheduler,
        )


def test_report_classifies_only_accepted_agent_skill_and_user_assumptions(
    tmp_path: Path,
) -> None:
    case = _create_skill_case(tmp_path)
    _add_requirement_assumption(case.root)
    plan, scheduler = _create_implementation_plan(case.root, case.token)
    plan_value = plan.value
    assert isinstance(plan_value, IntegratedPlan)
    store, dispatch = _start_skill_task(case)
    ledger_reference = _write_candidate_ledger(case.root, plan_value)
    result = _task_result(
        case.root,
        dispatch,
        (case.graph.contexts[0].reference, case.skill_reference),
        evidence=(ledger_reference,),
    )
    completed = store.tick(case.root, HOST_ID, (result,), FixedClock().now())
    assert completed.accepted_message_ids == (result.artifact_id,)

    stray_payload = json.loads(
        (
            case.root / "examples/m2-orchestration/implementer-result.json"
        ).read_text(encoding="utf-8")
    )
    stray_payload["agent_id"] = "AGT-STRAY-1"
    stray_payload["findings"][0]["finding_id"] = "FND-STRAY-1"
    stray_payload["findings"][0]["statement"] = "This result was never accepted by M6."
    (case.root / "workflow/stray-agent-result.json").write_text(
        json.dumps(stray_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    source_path = case.root / "workflow/report-skill-source-state.json"
    source = create_runtime(FixedClock()).run(
        plan,
        case.root,
        scheduler,
        source_path,
        case.root / "workflow/report-skill-source-event.json",
    )
    outcome, _event, closure = create_outcome(FixedClock()).publish(
        source.state,
        workflow_binding(case.root, source_path, source.state),
        plan,
        case.root,
        scheduler,
        case.root / "workflow/report-skill-outcome.json",
        case.root / "workflow/report-skill-terminal-event.json",
        case.root / "workflow/report-skill-terminal-state.json",
    )
    before = _tree_digests(case.root)

    report = WorkflowFinalReportService(create_planner()).report(
        outcome,
        closure,
        plan,
        case.root,
        scheduler,
    )

    agent_claim = next(
        claim
        for claim in report.claims
        if any(
            source.source_kind is WorkflowReportSourceKind.AGENT
            for source in claim.supporting_sources
        )
    )
    assert agent_claim.classification is EpistemicClassification.INFERENCE
    skill_claim = next(
        claim
        for claim in report.claims
        if any(
            source.source_kind is WorkflowReportSourceKind.SKILL
            for source in claim.supporting_sources
        )
    )
    assert skill_claim.classification is EpistemicClassification.INFERENCE
    assumption = next(
        claim
        for claim in report.claims
        if claim.classification is EpistemicClassification.ASSUMPTION
    )
    assert assumption.human_review_required
    sources = tuple(
        source
        for claim in report.claims
        for source in (
            *claim.supporting_sources,
            *claim.refuting_sources,
            *claim.unresolved_sources,
        )
    )
    assert all("AGT-STRAY-1" not in source.source_id for source in sources)
    assert _tree_digests(case.root) == before


def _add_requirement_assumption(root: Path) -> None:
    path = root / "requirements/baseline.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["requirements"][0]["assumptions"] = [
        "The user-provided offline constraint remains applicable."
    ]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _terminal_state_value(artifact: object) -> WorkflowState:
    value = getattr(artifact, "value", None)
    assert isinstance(value, WorkflowState)
    return value


def _tree_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
