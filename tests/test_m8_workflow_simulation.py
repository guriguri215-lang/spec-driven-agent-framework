"""Deterministic representative M8 simulation tests."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

import sdaqf.application.workflow_simulation as simulation_module
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.context_contracts import load_context_artifact
from sdaqf.application.scheduler_contracts import load_scheduler_artifact
from sdaqf.application.workflow_contracts import (
    load_workflow_artifact,
    parse_workflow_artifact_bytes,
)
from sdaqf.application.workflow_simulation import (
    SCENARIOS,
    WorkflowSimulationError,
    WorkflowSimulationEvidence,
    WorkflowSimulationResult,
    WorkflowSimulationService,
    run_all_scenarios,
)
from sdaqf.domain.context import ContextArtifactType, ContextGraph, ContextSelection
from sdaqf.domain.scheduler import SchedulerArtifactType, TaskGraph
from sdaqf.domain.workflow import (
    IntegratedPlan,
    MeasurementStatus,
    WorkflowArtifactType,
    WorkflowEvent,
    WorkflowMeasurement,
    WorkflowState,
)
from tests.m8_workflow_helpers import (
    create_plan,
    create_planner,
    create_scheduler,
    create_workspace,
)


def test_all_twelve_scenarios_are_offline_named_and_non_aggregate(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    results = run_all_scenarios(plan, root, scheduler, create_planner())
    assert tuple(item.scenario for item in results) == SCENARIOS
    assert {
        item.scenario: (item.outcome, item.blockers) for item in results
    } == {
        "non-ui-success": ("completed", ()),
        "ui-observation-unavailable": (
            "blocked",
            ("ui-evidence-unavailable",),
        ),
        "approval-required": ("blocked", ("approval-required",)),
        "approval-refused": ("blocked", ("approval-refused",)),
        "approval-expired": ("blocked", ("approval-expired",)),
        "stale-candidate": ("blocked", ("stale-candidate",)),
        "stale-context": ("blocked", ("stale-context",)),
        "lease-lost": ("blocked", ("lease-lost",)),
        "solver-inconclusive": ("blocked", ("solver-inconclusive",)),
        "ambiguous-external-effect": (
            "blocked",
            ("external-effect-ambiguous",),
        ),
        "crash-and-recovery": ("completed", ()),
        "candidate-supersession": (
            "superseded",
            ("predecessor-superseded",),
        ),
    }
    assert all(item.offline for item in results)
    assert all(not item.real_ui_observed for item in results)
    assert all(not item.hosted_runtime_used for item in results)
    assert all(len(item.measurements) == 9 for item in results)
    assert all(
        sum(len(group) for group in item.measurements.values()) == 52 for item in results
    )
    assert all("aggregate_score" not in item.to_dict() for item in results)
    assert all(
        {"planner", "runtime", "status", "outcome"} <= set(item.contract_trace) for item in results
    )
    assert all(item.native_artifact_ids for item in results)
    assert all(item.event_ids for item in results)
    assert all(item.outcome_artifact_id.startswith("M8-WORKFLOW-OUTCOME-") for item in results)
    assert all(item.terminal_state_id.startswith("M8-WORKFLOW-STATE-") for item in results)
    assert all(item.fixture_bundle_id.startswith("M8-FIXTURE-BUNDLE-") for item in results)

    plan_value = plan.value
    selection_artifact = load_context_artifact(
        root / plan_value.context_selection.reference.path,  # type: ignore[union-attr]
        expected_type=ContextArtifactType.SELECTION,
    )
    selection = selection_artifact.value
    assert isinstance(selection, ContextSelection)
    first = results[0].measurements["context"]["selected_context_bytes"]
    assert first["status"] == "observed"
    assert isinstance(first["value"], int) and first["value"] > selection.used_bytes


def test_three_fixture_bundles_causally_change_m1_m5_m6_m3_plan_state_and_outcome(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    observed: dict[str, tuple[str, ...]] = {}

    def capture(
        result: WorkflowSimulationResult,
        evidence: WorkflowSimulationEvidence,
    ) -> None:
        project = result.project_fixture
        plan_path = evidence.plan_path
        evidence_root = evidence.root
        terminal_state_path = evidence.terminal_state_path
        outcome_path = evidence.outcome_path
        plan_artifact = load_workflow_artifact(
            plan_path,
            expected_type=WorkflowArtifactType.INTEGRATED_PLAN,
        )
        fixture_plan = plan_artifact.value
        assert isinstance(fixture_plan, IntegratedPlan)
        context_artifact = load_context_artifact(
            evidence_root / fixture_plan.context_graph.reference.path,
            expected_type=ContextArtifactType.GRAPH,
        )
        context_graph = context_artifact.value
        assert isinstance(context_graph, ContextGraph)
        task_graph_artifact = load_scheduler_artifact(
            evidence_root / fixture_plan.task_graph.reference.path,
            expected_type=SchedulerArtifactType.TASK_GRAPH,
            root=evidence_root,
        )
        task_graph = task_graph_artifact.value
        assert isinstance(task_graph, TaskGraph)
        m3 = tuple(
            reference
            for node in context_graph.nodes
            for reference in node.provenance.references
            if reference.path.endswith("fixture-evidence-ledger.json")
        )
        assert len(m3) == 1
        terminal_state = load_workflow_artifact(
            terminal_state_path,
            expected_type=WorkflowArtifactType.WORKFLOW_STATE,
        )
        outcome = load_workflow_artifact(
            outcome_path,
            expected_type=WorkflowArtifactType.WORKFLOW_OUTCOME,
        )
        observed[project] = (
            fixture_plan.requirement_baseline_id,
            context_artifact.artifact_id,
            task_graph_artifact.artifact_id,
            m3[0].sha256,
            plan_artifact.artifact_id,
            terminal_state.artifact_id,
            outcome.artifact_id,
        )

    service = WorkflowSimulationService(create_planner())
    for scenario in (
        "non-ui-success",
        "ui-observation-unavailable",
        "approval-required",
    ):
        service.run(plan, root, scheduler, scenario, evidence_validator=capture)
    assert set(observed) == {"offline-config", "ui-issue-tracker", "secure-export"}
    for index in range(7):
        assert len({values[index] for values in observed.values()}) == 3


def test_simulation_is_deterministic_and_ui_pass_means_honest_block(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    service = WorkflowSimulationService(create_planner())
    one = service.run(plan, root, scheduler, "ui-observation-unavailable")
    two = service.run(plan, root, scheduler, "ui-observation-unavailable")
    assert one == two
    assert one.outcome == "blocked"
    assert one.blockers == ("ui-evidence-unavailable",)
    assert one.project_fixture == "ui-issue-tracker"


def test_security_sensitive_scenarios_use_secure_export_fixture(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    service = WorkflowSimulationService(create_planner())
    approval = service.run(plan, root, scheduler, "approval-required")
    ambiguous = service.run(plan, root, scheduler, "ambiguous-external-effect")
    assert approval.project_fixture == "secure-export"
    assert ambiguous.project_fixture == "secure-export"
    assert ambiguous.blockers == ("external-effect-ambiguous",)


def test_solver_inconclusive_uses_real_m7_request_and_m6_budget(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    result = WorkflowSimulationService(create_planner()).run(
        plan,
        root,
        scheduler,
        "solver-inconclusive",
    )
    assert result.outcome == "blocked"
    assert result.blockers == ("solver-inconclusive",)
    assert result.project_fixture == "offline-config"


def test_crash_recovery_uses_current_m6_time_and_publishes_completed_outcome(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    result = WorkflowSimulationService(create_planner()).run(
        plan,
        root,
        scheduler,
        "crash-and-recovery",
    )
    assert result.outcome == "completed"
    assert result.blockers == ()
    assert "recovery" in result.contract_trace


def test_simulation_rejects_disconnected_scheduler_and_contract_executions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    service = WorkflowSimulationService(create_planner())
    original = service._exercise_contracts

    def disconnected(*args: object) -> tuple[object, ...]:
        result = original(*args)  # type: ignore[arg-type]
        return ((plan.artifact_id,), *result[1:])

    monkeypatch.setattr(
        service,
        "_exercise_contracts",
        disconnected,
    )
    with pytest.raises(WorkflowSimulationError, match="same native execution"):
        service.run(plan, root, scheduler, "non-ui-success")


def test_simulation_validator_resolves_measurements_events_and_contract_trace(
    tmp_path: Path,
) -> None:
    from scripts.validate_m8_workflow import (
        _independently_validate_simulation_evidence,
        _validate_simulation_result,
    )

    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    result = WorkflowSimulationService(create_planner()).run(
        plan,
        root,
        scheduler,
        "non-ui-success",
        evidence_validator=_independently_validate_simulation_evidence,
    )
    measurements = {
        group: {name: dict(payload) for name, payload in values.items()}
        for group, values in result.measurements.items()
    }
    measurements["requirements"]["required_requirement_count"]["source_ids"] = [
        "M8-FAKE-SOURCE-" + "A" * 64
    ]
    with pytest.raises(WorkflowSimulationError, match="measurement source"):
        _validate_simulation_result(replace(result, measurements=measurements))
    with pytest.raises(WorkflowSimulationError, match="contract trace"):
        _validate_simulation_result(replace(result, contract_trace=("planner", "outcome")))


def test_independent_measurements_ignore_forged_workflow_projection_fields(
    tmp_path: Path,
) -> None:
    from scripts.validate_m8_workflow import _independent_measurements

    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)

    def prove_m6_authority(
        _result: WorkflowSimulationResult,
        evidence: WorkflowSimulationEvidence,
    ) -> None:
        scenario_plan = load_workflow_artifact(
            evidence.plan_path,
            expected_type=WorkflowArtifactType.INTEGRATED_PLAN,
        )
        state_artifact = load_workflow_artifact(
            evidence.terminal_state_path,
            expected_type=WorkflowArtifactType.WORKFLOW_STATE,
        )
        state = state_artifact.value
        assert isinstance(state, WorkflowState)
        events: list[WorkflowEvent] = []
        for binding in state.event_chain:
            event_artifact = load_workflow_artifact(
                evidence.root / binding.reference.path,
                expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
            )
            event = event_artifact.value
            assert isinstance(event, WorkflowEvent)
            events.append(event)
        store = SQLiteSchedulerStore(evidence.scheduler_state, evidence.root)
        authoritative = _independent_measurements(
            scenario_plan,
            state,
            tuple(events),
            store,
            evidence.root,
        )
        forged = replace(
            state,
            tasks=(),
            ambiguities=("forged-ambiguity",),
            approval_ids=("M6-APPROVAL-" + "F" * 64,),
        )
        assert (
            _independent_measurements(
                scenario_plan,
                forged,
                tuple(events),
                store,
                evidence.root,
            )
            == authoritative
        )
        task_count = authoritative["scheduling"]["task_count"]["value"]
        assert isinstance(task_count, int) and task_count > 0

    WorkflowSimulationService(create_planner()).run(
        plan,
        root,
        scheduler,
        "approval-required",
        evidence_validator=prove_m6_authority,
    )


def test_simulation_defensive_contracts_fail_closed(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    service = WorkflowSimulationService(create_planner())
    with pytest.raises(WorkflowSimulationError, match="unsupported"):
        service.run(plan, root, scheduler, "not-a-scenario")
    intent = parse_workflow_artifact_bytes(
        (root / "workflow/intent.json").read_bytes(),
        expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
    )
    with pytest.raises(WorkflowSimulationError, match="requires Integrated Plan"):
        service.run(intent, root, scheduler, "non-ui-success")
    with pytest.raises(WorkflowSimulationError, match="scheduler probe"):
        simulation_module._scheduler_scenario("approval-required")
    with pytest.raises(WorkflowSimulationError, match="did not reproduce"):
        simulation_module._require_probe(False)
    candidate = plan.value.candidate
    with pytest.raises(WorkflowSimulationError, match="Candidate observation"):
        simulation_module._ExactCandidateVerifier(candidate).observe(
            root / "missing",
            candidate,
            scheduler_state=scheduler,
        )
    collision = root / "workflow/.simulation-non-ui-success"
    collision.mkdir()
    with (
        pytest.raises(WorkflowSimulationError, match="already exists"),
        simulation_module._deterministic_private_directory(root / "workflow", "non-ui-success"),
    ):
        pass
    collision.rmdir()
    invalid = WorkflowMeasurement(
        "ungrouped",
        MeasurementStatus.NOT_AVAILABLE,
        None,
        None,
        (plan.artifact_id,),
    )
    with pytest.raises(WorkflowSimulationError, match="exact M8-D7 sequence"):
        simulation_module._measurement_payload((invalid,))


def test_fixture_bundle_is_complete_exact_byte_and_single_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_root = tmp_path / "fixtures"
    source = simulation_module._FIXTURE_ROOT / "offline-config"
    shutil.copytree(source, fixture_root / "offline-config")
    monkeypatch.setattr(simulation_module, "_FIXTURE_ROOT", fixture_root)
    bundle = simulation_module._load_fixture_bundle("offline-config")
    assert bundle.fixture_bundle_id.startswith("M8-FIXTURE-BUNDLE-")
    assert {path for path, _ in bundle.files} >= {
        "specification.md",
        "expected-normalized.json",
        "structured-run.json",
    }
    (fixture_root / "offline-config/specification.md").write_bytes(b"drift")
    with pytest.raises(WorkflowSimulationError, match="identity drifted"):
        simulation_module._load_fixture_bundle("offline-config")


def test_fixture_normalization_must_be_semantically_present_in_specification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.validate_m8_workflow import _independent_fixture_bundle

    fixture_root = tmp_path / "fixtures"
    source = simulation_module._FIXTURE_ROOT / "offline-config"
    target = fixture_root / "offline-config"
    shutil.copytree(source, target)
    normalized_path = target / "expected-normalized.json"
    normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
    normalized["requirements"][0]["statement"] = "A statement absent from the specification."
    normalized_path.write_text(
        json.dumps(normalized, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fixture_id, _ = _independent_fixture_bundle(target)
    monkeypatch.setattr(simulation_module, "_FIXTURE_ROOT", fixture_root)
    monkeypatch.setitem(simulation_module._FIXTURE_PROJECTS, "offline-config", fixture_id)
    root = create_workspace(tmp_path / "workspace-root")
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    with pytest.raises(WorkflowSimulationError, match="not present"):
        WorkflowSimulationService(create_planner()).run(
            plan,
            root,
            scheduler,
            "non-ui-success",
        )
