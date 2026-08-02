"""M6 scheduler transition and wait-report tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import sdaqf.adapters.scheduler as scheduler_adapter
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.scheduler import (
    deterministic_wait_report,
    scheduler_state_wait_report,
)
from sdaqf.application.scheduler_contracts import SchedulerContractError
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.scheduler import (
    EffectKind,
    MailboxMessage,
    MessageType,
    SchedulerState,
    TaskProjection,
)
from tests.m6_scheduler_helpers import (
    FIXED_TIME,
    ROOT,
    create_store,
    first_dispatch,
    graph_value,
    host_message,
    result_message,
    worktree_graph,
)


def _projection(store: SQLiteSchedulerStore) -> TaskProjection:
    state = store.status().value
    assert isinstance(state, SchedulerState)
    return state.tasks[0]


def test_dispatch_acknowledgement_and_result_complete_after_verification(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    acknowledgement = host_message(
        dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": True, "effect_observed": "none", "note": None},
    )
    tick = store.tick(ROOT, "HST-TEST", (acknowledgement,), FIXED_TIME)
    assert tick.accepted_message_ids == (acknowledgement.artifact_id,)
    assert _projection(store).dispatch_phase.value == "accepted"

    result = result_message(dispatch)
    tick = store.tick(ROOT, "HST-TEST", (result,), FIXED_TIME)
    assert tick.accepted_message_ids == (result.artifact_id,)
    projection = _projection(store)
    assert projection.state.value == "completed"
    assert projection.outcome.value == "succeeded"


def test_result_rejects_fabricated_evidence_and_status_contradiction(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    result_path = ROOT / "examples" / "m2-orchestration" / "implementer-result.json"
    valid = ArtifactReference(
        result_path.relative_to(ROOT).as_posix(),
        hashlib.sha256(result_path.read_bytes()).hexdigest().upper(),
    ).to_dict()
    fabricated = host_message(
        dispatch,
        MessageType.TASK_RESULT,
        {
            "agent_result": valid,
            "outcome": "succeeded",
            "effect_observed": "none",
            "evidence_refs": [
                {"path": "examples/m2-orchestration/missing-evidence.json", "sha256": "A" * 64}
            ],
            "budget_usage": {
                "microunits": 0,
                "solver_calls": 0,
                "solver_steps": 0,
                "tool_calls": 0,
            },
        },
    )
    with pytest.raises(SchedulerContractError, match="identity"):
        store.tick(ROOT, "HST-TEST", (fabricated,), FIXED_TIME)
    assert _projection(store).state.value == "running"

    blocked_value = json.loads(result_path.read_text(encoding="utf-8"))
    blocked_value["status"] = "blocked"
    blocked_value["changed_paths"] = []
    blocked_path = tmp_path / "blocked-agent-result.json"
    blocked_path.write_text(
        json.dumps(blocked_value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    blocked_reference = ArtifactReference(
        blocked_path.relative_to(ROOT).as_posix(),
        hashlib.sha256(blocked_path.read_bytes()).hexdigest().upper(),
    ).to_dict()
    contradictory = host_message(
        dispatch,
        MessageType.TASK_RESULT,
        {
            "agent_result": blocked_reference,
            "outcome": "succeeded",
            "effect_observed": "none",
            "evidence_refs": [valid],
            "budget_usage": {
                "microunits": 0,
                "solver_calls": 0,
                "solver_steps": 0,
                "tool_calls": 0,
            },
        },
    )
    with pytest.raises(SchedulerContractError, match="contradicts"):
        store.tick(ROOT, "HST-TEST", (contradictory,), FIXED_TIME)
    assert _projection(store).state.value == "running"


def test_missing_required_evidence_blocks_verification(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    store.tick(ROOT, "HST-TEST", (result_message(dispatch, evidence=False),), FIXED_TIME)
    projection = _projection(store)
    assert projection.state.value == "blocked"
    assert projection.outcome.value == "unknown"
    assert projection.blockers[0].code == "evidence-predicate-unsatisfied"


def test_incomplete_review_targets_block_successful_result_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = graph_value()
    target = graph.tasks[0]
    reviewer = replace(
        target,
        task_id="TSK-REVIEW",
        dependencies=(),
        owned_paths=(),
        review_targets=(target.task_id,),
    )
    graph = replace(
        graph,
        tasks=(target, reviewer),
        budget=replace(graph.budget, max_agents=2, max_concurrency=2),
    )
    monkeypatch.setattr(
        scheduler_adapter,
        "validate_task_graph_inputs",
        lambda _artifact, _root: None,
    )
    store = create_store(tmp_path, graph=graph)
    tick = store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    dispatch = next(
        item
        for item in tick.outgoing
        if isinstance(item.value, MailboxMessage) and item.value.task_id == reviewer.task_id
    )
    store.tick(ROOT, "HST-TEST", (result_message(dispatch),), FIXED_TIME)
    state = store.status().value
    assert isinstance(state, SchedulerState)
    projection = next(item for item in state.tasks if item.task_id == reviewer.task_id)
    assert projection.state.value == "blocked"
    assert projection.outcome.value == "unknown"
    assert projection.blockers[0].code == "review-targets-unsatisfied"
    assert projection.blockers[0].references == (target.task_id,)
    assert store.wait_for_projection()[f"task:{reviewer.task_id}"] == (
        f"task:{target.task_id}",
    )
    fallback = scheduler_state_wait_report(graph, state)
    assert fallback.kind == "stall"
    assert f"task:{reviewer.task_id}->task:{target.task_id}" in fallback.blockers
    store.validate()


def test_failed_read_only_result_retries_with_new_fence(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    tick = store.tick(
        ROOT,
        "HST-TEST",
        (result_message(dispatch, outcome="failed", effect="none"),),
        FIXED_TIME,
    )
    assert len(tick.outgoing) == 1
    retried = tick.outgoing[0].value
    original = dispatch.value
    assert isinstance(retried, MailboxMessage)
    assert isinstance(original, MailboxMessage)
    assert retried.attempt == 2
    assert retried.fence == 2
    assert retried.idempotency_key != original.idempotency_key


def test_ambiguous_external_result_blocks_unknown_without_retry(tmp_path: Path) -> None:
    graph = graph_value()
    graph = replace(
        graph,
        tasks=(replace(graph.tasks[0], effect_kind=EffectKind.EXTERNAL),),
    )
    store = create_store(tmp_path, graph=graph)
    dispatch = first_dispatch(store)
    tick = store.tick(
        ROOT,
        "HST-TEST",
        (result_message(dispatch, outcome="failed", effect="ambiguous"),),
        FIXED_TIME,
    )
    assert tick.outgoing == ()
    projection = _projection(store)
    assert projection.state.value == "blocked"
    assert projection.outcome.value == "unknown"


def test_dispatch_rejection_retries_only_when_unambiguous(tmp_path: Path) -> None:
    safe_path = tmp_path / "safe"
    safe_path.mkdir()
    safe_store = create_store(safe_path)
    safe_dispatch = first_dispatch(safe_store)
    safe_ack = host_message(
        safe_dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": False, "effect_observed": "none", "note": "not started"},
    )
    safe_tick = safe_store.tick(ROOT, "HST-TEST", (safe_ack,), FIXED_TIME)
    assert len(safe_tick.outgoing) == 1

    graph = graph_value()
    graph = replace(graph, tasks=(replace(graph.tasks[0], effect_kind=EffectKind.EXTERNAL),))
    unsafe_path = tmp_path / "unsafe"
    unsafe_path.mkdir()
    unsafe_store = create_store(unsafe_path, graph=graph)
    unsafe_dispatch = first_dispatch(unsafe_store)
    unsafe_ack = host_message(
        unsafe_dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": False, "effect_observed": "possible", "note": None},
    )
    unsafe_tick = unsafe_store.tick(ROOT, "HST-TEST", (unsafe_ack,), FIXED_TIME)
    assert unsafe_tick.outgoing == ()
    assert _projection(unsafe_store).outcome.value == "unknown"


def test_unambiguous_terminal_failure_and_both_cancellation_outcomes(tmp_path: Path) -> None:
    graph = graph_value()
    no_retry = replace(graph, tasks=(replace(graph.tasks[0], max_attempts=1),))
    failed_path = tmp_path / "failed"
    failed_path.mkdir()
    failed_store = create_store(failed_path, graph=no_retry)
    failed_dispatch = first_dispatch(failed_store)
    failed_store.tick(
        ROOT,
        "HST-TEST",
        (result_message(failed_dispatch, outcome="failed", effect="none"),),
        FIXED_TIME,
    )
    assert _projection(failed_store).state.value == "rejected"

    cancelled_path = tmp_path / "cancelled"
    cancelled_path.mkdir()
    cancelled_store = create_store(cancelled_path)
    first_dispatch(cancelled_store)
    cancel_request = cancelled_store.request_cancel(
        ROOT, "HST-TEST", "TSK-M6-DEMO", "Owner requested stop.", FIXED_TIME
    )
    cancelled = host_message(
        cancel_request,
        MessageType.CANCEL_ACKNOWLEDGEMENT,
        {"cancelled": True, "effect_observed": "none"},
    )
    cancelled_store.tick(ROOT, "HST-TEST", (cancelled,), FIXED_TIME)
    projection = _projection(cancelled_store)
    assert projection.state.value == "superseded"
    assert projection.outcome.value == "cancelled"

    unknown_path = tmp_path / "unknown"
    unknown_path.mkdir()
    unknown_store = create_store(unknown_path)
    first_dispatch(unknown_store)
    unknown_request = unknown_store.request_cancel(
        ROOT, "HST-TEST", "TSK-M6-DEMO", "Owner requested stop.", FIXED_TIME
    )
    unknown = host_message(
        unknown_request,
        MessageType.CANCEL_ACKNOWLEDGEMENT,
        {"cancelled": False, "effect_observed": "ambiguous"},
    )
    unknown_store.tick(ROOT, "HST-TEST", (unknown,), FIXED_TIME)
    projection = _projection(unknown_store)
    assert projection.state.value == "blocked"
    assert projection.dispatch_phase.value == "cancellation_requested"


def test_cancel_ack_without_scheduler_request_is_rejected(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    unsolicited = host_message(
        dispatch,
        MessageType.CANCEL_ACKNOWLEDGEMENT,
        {"cancelled": True, "effect_observed": "none"},
    )
    tick = store.tick(ROOT, "HST-TEST", (unsolicited,), FIXED_TIME)
    assert tick.rejected_message_ids == (unsolicited.artifact_id,)
    assert _projection(store).state.value == "running"


def test_wait_reports_are_canonical_and_never_speculative() -> None:
    deadlock = deterministic_wait_report(
        {"TSK-B": ("TSK-A",), "TSK-A": ("TSK-B",), "TSK-C": ("TSK-A",)}
    )
    assert deadlock.kind == "deadlock"
    assert deadlock.cycle == ("TSK-A", "TSK-B")
    stall = deterministic_wait_report({"TSK-A": ("external-owner",)})
    assert stall.kind == "stall"
    assert stall.blockers == ("TSK-A->external-owner",)
    assert deterministic_wait_report({}).kind == "clear"


def test_scheduler_state_wait_report_tracks_incomplete_dependencies(tmp_path: Path) -> None:
    graph = graph_value()
    first = graph.tasks[0]
    second = replace(
        first,
        task_id="TSK-SECOND",
        dependencies=(first.task_id,),
        owned_paths=(),
        review_targets=(),
    )
    graph = replace(graph, tasks=(first, second))
    store = create_store(tmp_path, graph=graph)
    store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    state = store.status().value
    assert isinstance(state, SchedulerState)
    report = scheduler_state_wait_report(graph, state)
    assert report.kind == "stall"
    assert report.blockers == ("task:TSK-SECOND->task:TSK-M6-DEMO",)


def test_durable_wait_projection_exposes_typed_worktree_authority_edges(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path, graph=worktree_graph())
    request = first_dispatch(store)
    request_value = request.value
    assert isinstance(request_value, MailboxMessage)
    projection = store.wait_for_projection()
    task_node = "task:TSK-M6-DEMO"
    worktree_node = "worktree:worktrees/implementation"
    assert projection[task_node] == (
        "worktree-observation:worktrees/implementation",
    )
    assert projection[worktree_node] == (task_node,)
    report = deterministic_wait_report(projection)
    assert report.kind == "stall"
    assert report.blockers == (
        "task:TSK-M6-DEMO->worktree-observation:worktrees/implementation",
        "worktree:worktrees/implementation->task:TSK-M6-DEMO",
    )


def test_durable_wait_projection_covers_dependency_lease_approval_capability_and_budget(
    tmp_path: Path,
) -> None:
    base = graph_value()
    first = base.tasks[0]

    dependency_root = tmp_path / "dependency"
    dependency_root.mkdir()
    dependent = replace(
        first,
        task_id="TSK-SECOND",
        dependencies=(first.task_id,),
        owned_paths=(),
        review_targets=(),
    )
    dependency_store = create_store(
        dependency_root, graph=replace(base, tasks=(first, dependent))
    )
    dependency_dispatch = first_dispatch(dependency_store).value
    assert isinstance(dependency_dispatch, MailboxMessage)
    dependency_projection = dependency_store.wait_for_projection()
    assert dependency_projection["task:TSK-SECOND"] == ("task:TSK-M6-DEMO",)
    assert dependency_projection["task:TSK-M6-DEMO"] == (
        f"lease:{dependency_dispatch.lease_id}:dispatch-ack",
    )

    approval_root = tmp_path / "approval"
    approval_root.mkdir()
    approval_task = replace(first, approval_stops=("owner",))
    approval_store = create_store(
        approval_root, graph=replace(base, tasks=(approval_task,))
    )
    approval_store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    assert approval_store.wait_for_projection()["task:TSK-M6-DEMO"] == (
        "approval:owner:TSK-M6-DEMO",
    )

    capability_root = tmp_path / "capability"
    capability_root.mkdir()
    capability_task = replace(first, required_capabilities=("sandbox",))
    capability_store = create_store(
        capability_root, graph=replace(base, tasks=(capability_task,))
    )
    capability_store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    assert capability_store.wait_for_projection()["task:TSK-M6-DEMO"] == (
        "capability:unassigned:sandbox",
    )

    budget_root = tmp_path / "budget"
    budget_root.mkdir()
    budget_first = replace(first, dependencies=(), required_capabilities=())
    budget_second = replace(
        budget_first,
        task_id="TSK-SECOND",
        owned_paths=(),
        review_targets=(),
    )
    budget_graph = replace(
        base,
        tasks=(budget_first, budget_second),
        budget=replace(
            base.budget,
            max_agents=2,
            max_concurrency=2,
            max_dispatches=1,
        ),
    )
    budget_store = create_store(budget_root, graph=budget_graph)
    budget_store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    assert budget_store.wait_for_projection()["task:TSK-SECOND"] == (
        "budget:scheduler",
    )


def test_durable_wait_projection_covers_remaining_phase_and_blocker_edges(
    tmp_path: Path,
) -> None:
    base = graph_value()
    first = base.tasks[0]

    accepted_root = tmp_path / "accepted"
    accepted_root.mkdir()
    accepted_store = create_store(accepted_root)
    accepted_dispatch = first_dispatch(accepted_store)
    acknowledgement = host_message(
        accepted_dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": True, "effect_observed": "none", "note": None},
    )
    accepted_store.tick(ROOT, "HST-TEST", (acknowledgement,), FIXED_TIME)
    accepted_value = accepted_dispatch.value
    assert isinstance(accepted_value, MailboxMessage)
    assert accepted_store.wait_for_projection()["task:TSK-M6-DEMO"] == (
        f"lease:{accepted_value.lease_id}:result",
    )

    cancel_root = tmp_path / "cancel"
    cancel_root.mkdir()
    cancel_store = create_store(cancel_root)
    cancel_dispatch = first_dispatch(cancel_store).value
    assert isinstance(cancel_dispatch, MailboxMessage)
    cancel_store.request_cancel(
        ROOT, "HST-TEST", "TSK-M6-DEMO", "Owner requested stop.", FIXED_TIME
    )
    assert cancel_store.wait_for_projection()["task:TSK-M6-DEMO"] == (
        f"lease:{cancel_dispatch.lease_id}:cancel-ack",
    )

    unavailable_root = tmp_path / "unavailable"
    unavailable_root.mkdir()
    worktree_base = worktree_graph()
    worktree_first = worktree_base.tasks[0]
    second = replace(
        worktree_first,
        task_id="TSK-SECOND",
        dependencies=(),
        owned_paths=(),
        review_targets=(),
    )
    unavailable_graph = replace(
        worktree_base,
        tasks=(worktree_first, second),
        budget=replace(worktree_base.budget, max_agents=2, max_concurrency=2),
    )
    unavailable_store = create_store(unavailable_root, graph=unavailable_graph)
    unavailable_store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    unavailable_projection = unavailable_store.wait_for_projection()
    assert unavailable_projection["task:TSK-SECOND"] == (
        "worktree:worktrees/implementation",
    )
    assert unavailable_projection["worktree:worktrees/implementation"] == (
        "task:TSK-M6-DEMO",
    )

    unknown_root = tmp_path / "unknown"
    unknown_root.mkdir()
    external = replace(first, effect_kind=EffectKind.EXTERNAL)
    unknown_store = create_store(unknown_root, graph=replace(base, tasks=(external,)))
    first_dispatch(unknown_store)
    unknown_store.tick(
        ROOT, "HST-TEST", (), FIXED_TIME + timedelta(seconds=61)
    )
    assert unknown_store.wait_for_projection()["task:TSK-M6-DEMO"] == (
        "blocker:lease-expired-ambiguous:TSK-M6-DEMO",
    )

    terminal_root = tmp_path / "terminal"
    terminal_root.mkdir()
    terminal_store = create_store(terminal_root)
    terminal_dispatch = first_dispatch(terminal_store)
    terminal_store.tick(
        ROOT, "HST-TEST", (result_message(terminal_dispatch),), FIXED_TIME
    )
    assert terminal_store.wait_for_projection() == {}
    terminal_state = terminal_store.status().value
    assert isinstance(terminal_state, SchedulerState)
    assert scheduler_state_wait_report(base, terminal_state).kind == "clear"
