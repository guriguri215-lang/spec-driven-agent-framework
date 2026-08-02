"""Deterministic M6 simulator tests."""

from __future__ import annotations

import json

import pytest

from sdaqf.application.scheduler_simulation import (
    SCENARIOS,
    SchedulerSimulationService,
    run_all_scenarios,
)
from tests.m6_scheduler_helpers import ROOT, TASK_GRAPH_PATH


def test_all_ten_scenarios_match_recorded_evaluation_exactly() -> None:
    first = run_all_scenarios(TASK_GRAPH_PATH, ROOT)
    second = run_all_scenarios(TASK_GRAPH_PATH, ROOT)
    assert tuple(item.scenario for item in first) == SCENARIOS
    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    recorded = json.loads((ROOT / "evals" / "results" / "m6-scheduler-evaluation.json").read_text())
    assert [
        {
            "case_id": item.scenario,
            "deterministic_digest": item.deterministic_digest,
            "observed_outcome": item.outcome,
            "observed_wait_kind": item.wait_kind,
            "observed_blockers": list(item.blockers),
            "passed": True,
        }
        for item in first
    ] == recorded["cases"]


def test_unknown_scenario_is_rejected_without_running() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        SchedulerSimulationService().run(TASK_GRAPH_PATH, ROOT, "not-a-scenario")


def test_every_scenario_reports_the_production_wait_projection_semantically() -> None:
    results = {item.scenario: item for item in run_all_scenarios(TASK_GRAPH_PATH, ROOT)}
    assert results["success"].wait_kind == "clear"
    assert results["result-disagreement"].wait_kind == "clear"
    assert results["duplicate-and-late-result"].wait_kind == "clear"
    assert results["wait-for-deadlock"].wait_kind == "deadlock"
    assert results["missing-capability"].wait_kind == "stall"
    assert results["missing-capability"].blockers == (
        "task:TSK-M6-DEMO->capability:unassigned:unavailable-capability",
    )
    assert results["budget-exhaustion"].wait_kind == "stall"
    assert "task:TSK-SECOND->budget:scheduler" in results["budget-exhaustion"].blockers
