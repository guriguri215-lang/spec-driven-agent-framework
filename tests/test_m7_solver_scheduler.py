"""M6 scheduler integration for exact M7 solver authority and budgets."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.scheduler_contracts import artifact_from_value
from sdaqf.domain.scheduler import (
    MailboxMessage,
    SchedulerArtifactType,
    SchedulerState,
    TaskGraph,
    TaskState,
)
from tests.m6_scheduler_helpers import ROOT
from tests.m7_solver_helpers import FIXED_TIME, HOST_ID, build_fixture, start_solver_lease


def test_solver_task_is_blocked_until_exact_capability_is_observed(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    store = SQLiteSchedulerStore.initialize(
        fixture.state_path,
        ROOT,
        fixture.graph,
        FIXED_TIME,
    )
    tick = store.tick(ROOT, HOST_ID, (), FIXED_TIME)
    assert tick.outgoing == ()
    state = tick.state.value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].state is TaskState.BLOCKED
    assert tuple(item.code for item in state.tasks[0].blockers) == ("missing-capability",)


def test_dispatch_reserves_only_the_contract_solve_and_verification_steps(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path, solve_steps=7, verification_steps=11)
    store, dispatch = start_solver_lease(fixture)
    value = dispatch.value
    assert isinstance(value, MailboxMessage)
    payload = value.to_dict()["payload"]
    assert isinstance(payload, dict)
    reservation = payload["budget_reservation"]
    assert isinstance(reservation, dict)
    assert reservation["context_bytes"] > 0
    assert reservation["microunits"] == 0
    assert reservation["solver_calls"] == 1
    assert reservation["solver_steps"] == 18
    assert reservation["tool_calls"] == 0
    ledger_artifacts = store.export("budget")
    assert ledger_artifacts
    ledger = ledger_artifacts[-1].value
    ledger_content = ledger.to_dict()
    reserved = ledger_content["reserved"]
    assert isinstance(reserved, dict)
    assert reserved["solver_steps"] == 18


def test_malformed_solver_token_never_receives_scheduler_authority(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    graph = fixture.graph.value
    assert isinstance(graph, TaskGraph)
    malformed = replace(
        graph,
        tasks=(
            replace(
                graph.tasks[0],
                required_capabilities=("m7-solver-v1@forged@1@1",),
            ),
        ),
    )
    malformed_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, malformed)
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "malformed.sqlite3",
        ROOT,
        malformed_artifact,
        FIXED_TIME,
    )
    tick = store.tick(ROOT, HOST_ID, (), FIXED_TIME)
    state = tick.state.value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].state is TaskState.BLOCKED
    assert {item.code for item in state.tasks[0].blockers} == {
        "missing-capability",
        "solver-contract-unavailable",
    }
