"""Additive M8 CLI namespace tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import sdaqf.cli as cli_module
from sdaqf.application.scheduler import SchedulerService
from sdaqf.application.workflow_contracts import artifact_from_value, serialize_workflow_artifact
from sdaqf.cli import main
from sdaqf.domain.workflow import DevelopmentIntent, WorkflowArtifactType
from tests.m8_workflow_helpers import (
    FixedClock,
    create_intent,
    create_plan,
    create_planner,
    create_runtime,
    create_scheduler,
    create_workspace,
)


def test_successor_predecessor_scheduler_flag_reaches_all_lifecycle_services(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    plan, plan_path = create_plan(root)
    scheduler = create_scheduler(root)
    state_path = root / "workflow/cli-propagation-state.json"
    state = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        state_path,
        root / "workflow/cli-propagation-event.json",
    ).state
    predecessor = root / "workflow/predecessor.sqlite3"
    observed: list[tuple[str, Path | None]] = []

    class _Payload:
        def to_dict(self) -> dict[str, object]:
            return {"valid": True}

    class _Explainer:
        def __init__(self, _planner: object) -> None:
            pass

        def explain(
            self,
            _plan: object,
            _root: Path,
            _scheduler: Path,
            *,
            predecessor_scheduler_state: Path | None = None,
        ) -> dict[str, object]:
            observed.append(("explain", predecessor_scheduler_state))
            return {"plan_id": plan.artifact_id}

    class _Simulation:
        def __init__(self, _planner: object) -> None:
            pass

        def run(
            self,
            _plan: object,
            _root: Path,
            _scheduler: Path,
            _scenario: str,
            *,
            predecessor_scheduler_state: Path | None = None,
        ) -> _Payload:
            observed.append(("simulate", predecessor_scheduler_state))
            return _Payload()

    class _Runtime:
        def __init__(self, *, planner: object) -> None:
            del planner

        def run(
            self,
            _plan: object,
            _root: Path,
            _scheduler: Path,
            _state: Path,
            _event: Path,
            *,
            predecessor_scheduler_state: Path | None = None,
        ) -> _Payload:
            observed.append(("run", predecessor_scheduler_state))
            return _Payload()

        def resume(
            self,
            _state: object,
            _binding: object,
            _plan: object,
            _root: Path,
            _scheduler: Path,
            _output_state: Path,
            _output_event: Path,
            *,
            predecessor_scheduler_state: Path | None = None,
        ) -> _Payload:
            observed.append(("resume", predecessor_scheduler_state))
            return _Payload()

        def status(
            self,
            _state: object,
            _plan: object,
            _root: Path,
            _scheduler: Path,
            *,
            predecessor_scheduler_state: Path | None = None,
        ) -> dict[str, object]:
            observed.append(("status", predecessor_scheduler_state))
            return {"valid": True}

    class _Recovery:
        def __init__(self, *, planner: object) -> None:
            del planner

        def recover(
            self,
            _state: object,
            _binding: object,
            _plan: object,
            _events: object,
            _root: Path,
            _scheduler: Path,
            _output_state: Path,
            _output_event: Path,
            _event_bindings: object,
            *,
            predecessor_scheduler_state: Path | None = None,
        ) -> tuple[_Payload, _Payload]:
            observed.append(("recover", predecessor_scheduler_state))
            return _Payload(), _Payload()

    monkeypatch.setattr(cli_module, "_workflow_planner_factory", create_planner)
    monkeypatch.setattr(cli_module, "WorkflowExplainer", _Explainer)
    monkeypatch.setattr(cli_module, "WorkflowSimulationService", _Simulation)
    monkeypatch.setattr(cli_module, "WorkflowRuntimeService", _Runtime)
    monkeypatch.setattr(cli_module, "WorkflowRecoveryService", _Recovery)
    common = [
        "--root",
        str(root),
        "--scheduler-state",
        str(scheduler),
        "--predecessor-scheduler-state",
        str(predecessor),
    ]
    assert main(["workflow", "explain", str(plan_path), *common, "--json"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "workflow",
                "simulate",
                str(plan_path),
                *common,
                "--scenario",
                "non-ui-success",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "workflow",
                "run",
                str(plan_path),
                *common,
                "--output-state",
                str(root / "workflow/cli-successor-state.json"),
                "--output-event",
                str(root / "workflow/cli-successor-event.json"),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "workflow",
                "resume",
                str(state_path),
                "--plan",
                str(plan_path),
                *common,
                "--output-state",
                str(root / "workflow/cli-successor-resumed-state.json"),
                "--output-event",
                str(root / "workflow/cli-successor-resumed-event.json"),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "workflow",
                "status",
                str(state_path),
                "--plan",
                str(plan_path),
                *common,
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "workflow",
                "recover",
                str(state_path),
                "--plan",
                str(plan_path),
                *common,
                "--output-state",
                str(root / "workflow/cli-successor-recovered-state.json"),
                "--output-event",
                str(root / "workflow/cli-successor-recovery-event.json"),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert state.artifact_id
    assert observed == [
        ("explain", predecessor),
        ("simulate", predecessor),
        ("run", predecessor),
        ("resume", predecessor),
        ("status", predecessor),
        ("recover", predecessor),
    ]


def test_workflow_cli_v1_store_fails_as_migration_required_without_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "_workflow_planner_factory", create_planner)
    root = create_workspace(tmp_path)
    _, intent_path = create_intent(root)
    scheduler = root / "workflow/v1-scheduler.sqlite3"
    SchedulerService(FixedClock()).initialize(
        root / "examples/m6-scheduler/task-graph.json",
        root,
        scheduler,
    )
    output = root / "workflow/v1-plan.json"
    assert (
        main(
            [
                "workflow",
                "plan",
                str(intent_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output",
                str(output),
                "--json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out) == {
        "error": "migration-required",
        "operation": "plan",
    }
    assert not output.exists()


def test_workflow_validate_and_plan_explain_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "_workflow_planner_factory", create_planner)
    root = create_workspace(tmp_path)
    _, intent_path = create_intent(root)
    scheduler = create_scheduler(root)
    plan_path = root / "workflow/cli-plan.json"
    assert main(["workflow", "validate", str(intent_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert (
        main(
            [
                "workflow",
                "plan",
                str(intent_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output",
                str(plan_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["side_effect_free_derivation"] is True
    assert payload["workflow_epoch_opened"] is True
    assert (
        main(
            [
                "workflow",
                "explain",
                str(plan_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["deterministic"] is True


def test_workflow_run_status_and_outcome_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "_workflow_planner_factory", create_planner)
    root = create_workspace(tmp_path)
    _, intent_path = create_intent(root)
    scheduler = create_scheduler(root)
    plan_path = root / "workflow/plan.json"
    assert (
        main(
            [
                "workflow",
                "plan",
                str(intent_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output",
                str(plan_path),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "workflow",
                "simulate",
                str(plan_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--scenario",
                "ui-observation-unavailable",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["blockers"] == ["ui-evidence-unavailable"]
    state = root / "workflow/state.json"
    event = root / "workflow/event.json"
    assert (
        main(
            [
                "workflow",
                "run",
                str(plan_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output-state",
                str(state),
                "--output-event",
                str(event),
                "--json",
            ]
        )
        == 0
    )
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload["host_dispatch_performed"] is False
    resumed_state = root / "workflow/resumed-state.json"
    assert (
        main(
            [
                "workflow",
                "resume",
                str(state),
                "--plan",
                str(plan_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output-state",
                str(resumed_state),
                "--output-event",
                str(root / "workflow/resumed-event.json"),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["state"]["artifact_type"] == "workflow-state"
    recovered_state = root / "workflow/recovered-state.json"
    assert (
        main(
            [
                "workflow",
                "recover",
                str(resumed_state),
                "--plan",
                str(plan_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output-state",
                str(recovered_state),
                "--output-event",
                str(root / "workflow/recovery-event.json"),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["source_preserved"] is True
    assert (
        main(
            [
                "workflow",
                "status",
                str(recovered_state),
                "--plan",
                str(plan_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["side_effect_free"] is True
    assert (
        main(
            [
                "workflow",
                "outcome",
                str(recovered_state),
                "--plan",
                str(plan_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output",
                str(root / "workflow/outcome.json"),
                "--output-event",
                str(root / "workflow/outcome-event.json"),
                "--output-state",
                str(root / "workflow/outcome-state.json"),
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["outcome"]["artifact_type"] == "workflow-outcome"


def test_workflow_supersede_cli_closes_only_the_old_candidate_epoch(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "_workflow_planner_factory", create_planner)
    root = create_workspace(tmp_path)
    intent, intent_path = create_intent(root)
    intent_value = intent.value
    assert isinstance(intent_value, DevelopmentIntent)
    scheduler = create_scheduler(root)
    plan_path = root / "workflow/supersede-plan.json"
    assert (
        main(
            [
                "workflow",
                "plan",
                str(intent_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output",
                str(plan_path),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    source_state = root / "workflow/supersede-source-state.json"
    assert (
        main(
            [
                "workflow",
                "run",
                str(plan_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output-state",
                str(source_state),
                "--output-event",
                str(root / "workflow/supersede-source-event.json"),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    successor_candidate = replace(intent_value.candidate, repository_digest="D" * 64)
    successor = artifact_from_value(
        WorkflowArtifactType.DEVELOPMENT_INTENT,
        replace(intent_value, candidate=successor_candidate),
    )
    successor_path = root / "workflow/successor-intent.json"
    successor_path.write_bytes(serialize_workflow_artifact(successor))
    (root / "workflow/candidate.json").write_text(
        json.dumps(successor_candidate.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "workflow",
                "supersede",
                str(source_state),
                "--plan",
                str(plan_path),
                "--successor-intent",
                str(successor_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output-state",
                str(root / "workflow/superseded-state.json"),
                "--output-event",
                str(root / "workflow/superseded-event.json"),
                "--output-outcome",
                str(root / "workflow/superseded-outcome.json"),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["event"]["content"]["cause"] == "plan-superseded"
    assert payload["state"]["content"]["status"] == "superseded"
    assert payload["outcome"]["content"]["disposition"] == "superseded"
    assert payload["host_dispatch_performed"] is False


def test_invalid_workflow_cli_is_stable_and_does_not_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}\n", encoding="utf-8")
    assert main(["workflow", "validate", str(invalid), "--json"]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "error": "m8-workflow-invalid",
        "operation": "validate",
    }


def test_plan_cli_emits_exact_deterministic_rejection_decision(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "_workflow_planner_factory", create_planner)
    root = create_workspace(tmp_path)
    _, intent_path = create_intent(root)
    scheduler = create_scheduler(root)
    (root / "workflow/candidate.json").write_text("{}\n", encoding="utf-8")
    output = root / "workflow/rejected-plan.json"
    assert (
        main(
            [
                "workflow",
                "plan",
                str(intent_path),
                "--root",
                str(root),
                "--scheduler-state",
                str(scheduler),
                "--output",
                str(output),
                "--json",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "m8-workflow-proposal-rejected"
    assert payload["decision"] == {
        "kind": "excluded",
        "subject_kind": "candidate",
        "subject_id": "CANDIDATE-" + "C" * 64,
        "reason_code": "stale-context",
        "references": [],
        "blocking": True,
    }
    assert not output.exists()
