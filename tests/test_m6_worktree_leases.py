"""M6 worktree observation and portable lease tests."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from sdaqf.adapters.scheduler import recover_scheduler_database
from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.scheduler_contracts import (
    SchedulerContractError,
    artifact_from_value,
    format_utc,
    load_scheduler_artifact,
    parse_scheduler_artifact_bytes,
)
from sdaqf.domain.scheduler import (
    Lease,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerState,
)
from tests.m6_scheduler_helpers import (
    FIXED_TIME,
    ROOT,
    create_store,
    example_payload,
    first_dispatch,
    host_message,
    refresh_identity,
    result_message,
    strict_bytes,
    worktree_graph,
)


def test_public_worktree_lease_is_strict_and_portable() -> None:
    artifact = load_scheduler_artifact(
        ROOT / "examples" / "m6-scheduler" / "worktree-lease.json",
        expected_type=SchedulerArtifactType.WORKTREE_LEASE,
    )
    assert artifact.value.to_dict()["worktree"] == "worktrees/implementation"


@pytest.mark.parametrize("field", ["worktree", "owned_paths"])
def test_absolute_or_parent_worktree_paths_are_rejected(field: str) -> None:
    payload = example_payload("worktree-lease.json")
    content = payload["content"]
    if field == "worktree":
        content[field] = "C:/outside"  # type: ignore[index]
    else:
        content[field] = ["../outside"]  # type: ignore[index]
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


def test_invalid_or_uppercase_base_commit_is_rejected() -> None:
    payload = example_payload("worktree-lease.json")
    payload["content"]["base_commit"] = "A" * 40  # type: ignore[index]
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError, match="base_commit"):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


def test_unplanned_worktree_observation_is_rejected_not_adopted(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    observation = host_message(
        dispatch,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/unplanned",
            "observed_digest": None,
            "state": "created",
        },
    )
    tick = store.tick(ROOT, "HST-TEST", (observation,), FIXED_TIME)
    assert tick.rejected_message_ids == (observation.artifact_id,)
    assert store.export("worktrees") == ()


@pytest.mark.parametrize(
    ("state", "expected_status", "expected_task_state"),
    [("created", "observed", "running"), ("ambiguous", "blocked", "blocked")],
)
def test_planned_worktree_observations_are_durable_and_ambiguity_blocks(
    tmp_path: Path,
    state: str,
    expected_status: str,
    expected_task_state: str,
) -> None:
    store = create_store(tmp_path, graph=worktree_graph())
    dispatch = first_dispatch(store)
    observation = host_message(
        dispatch,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64 if state == "created" else None,
            "state": state,
        },
    )
    tick = store.tick(ROOT, "HST-TEST", (observation,), FIXED_TIME)
    assert tick.accepted_message_ids == (observation.artifact_id,)
    leases = store.export("worktrees")
    assert len(leases) == 2
    assert leases[-1].value.to_dict()["status"] == expected_status
    assert tick.state.value.to_dict()["tasks"][0]["state"] == expected_task_state  # type: ignore[index]


def test_worktree_observation_requires_exact_request_assignment(tmp_path: Path) -> None:
    store = create_store(tmp_path, graph=worktree_graph())
    request = first_dispatch(store)
    mismatched = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/different",
            "observed_digest": "D" * 64,
            "state": "created",
        },
    )
    tick = store.tick(ROOT, "HST-TEST", (mismatched,), FIXED_TIME)
    assert tick.rejected_message_ids == (mismatched.artifact_id,)
    leases = store.export("worktrees")
    assert len(leases) == 1
    assert leases[0].value.to_dict()["status"] == "requested"


def test_ambiguous_worktree_releases_authority_and_late_result_cannot_complete(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path, graph=worktree_graph())
    request = first_dispatch(store)
    ambiguous = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": None,
            "state": "ambiguous",
        },
    )
    store.tick(ROOT, "HST-TEST", (ambiguous,), FIXED_TIME)
    assert store.status().value.to_dict()["lease_ids"] == []
    late = result_message(request)
    tick = store.tick(ROOT, "HST-TEST", (late,), FIXED_TIME)
    assert tick.rejected_message_ids == (late.artifact_id,)
    task = tick.state.value.to_dict()["tasks"][0]  # type: ignore[index]
    assert task["state"] == "blocked"
    assert task["outcome"] == "unknown"


def test_released_worktree_can_be_reacquired_by_a_sequential_task(
    tmp_path: Path,
) -> None:
    graph = worktree_graph()
    first = graph.tasks[0]
    second = replace(
        first,
        task_id="TSK-WORKTREE-SECOND",
        dependencies=(first.task_id,),
        owned_paths=(),
        review_targets=(),
    )
    graph = replace(graph, tasks=(first, second))
    store = create_store(tmp_path, graph=graph)
    first_request = first_dispatch(store)
    first_observation = host_message(
        first_request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "created",
        },
    )
    activated = store.tick(ROOT, "HST-TEST", (first_observation,), FIXED_TIME)
    assert len(activated.outgoing) == 1
    first_result = result_message(activated.outgoing[0])
    next_tick = store.tick(ROOT, "HST-TEST", (first_result,), FIXED_TIME)
    assert len(next_tick.outgoing) == 1
    second_request = next_tick.outgoing[0].value
    assert isinstance(second_request, MailboxMessage)
    assert second_request.task_id == second.task_id
    assert second_request.message_type is MessageType.WORKTREE_REQUEST

    history = store.export("worktrees")
    assert [item.value.to_dict()["status"] for item in history] == [
        "requested",
        "observed",
        "released",
        "requested",
    ]
    recovered = recover_scheduler_database(
        store.path, tmp_path / "sequential-worktree-recovered.sqlite3", ROOT
    )
    recovered.validate()
    assert recovered.status() == store.status()
    assert recovered.export("worktrees") == history


def test_integrated_worktree_is_terminal_and_recovery_does_not_restore_authority(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path, graph=worktree_graph())
    request = first_dispatch(store)
    integrated = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "integrated",
        },
    )
    tick = store.tick(ROOT, "HST-TEST", (integrated,), FIXED_TIME)
    assert tick.accepted_message_ids == (integrated.artifact_id,)
    assert tick.state.value.to_dict()["worktree_lease_ids"] == []
    assert store.export("worktrees")[-1].value.to_dict()["status"] == "integrated"

    recovered = recover_scheduler_database(
        store.path, tmp_path / "integrated-worktree-recovered.sqlite3", ROOT
    )
    recovered.validate()
    assert recovered.status() == store.status()
    assert recovered.export("worktrees") == store.export("worktrees")


def test_worktree_activation_rechecks_dispatch_budget_atomically(tmp_path: Path) -> None:
    graph = worktree_graph()
    template = graph.tasks[0]
    worktree_task = replace(template, task_id="TSK-A-WORKTREE")
    regular_task = replace(
        template,
        task_id="TSK-Z-REGULAR",
        owned_paths=(),
        worktree_assignment=None,
        review_targets=(),
    )
    graph = replace(
        graph,
        tasks=(worktree_task, regular_task),
        budget=replace(
            graph.budget,
            max_agents=2,
            max_concurrency=2,
            max_dispatches=1,
        ),
    )
    store = create_store(tmp_path, graph=graph)
    initial = store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    request = next(
        item
        for item in initial.outgoing
        if isinstance(item.value, MailboxMessage)
        and item.value.message_type is MessageType.WORKTREE_REQUEST
    )
    assert any(
        isinstance(item.value, MailboxMessage)
        and item.value.message_type is MessageType.DISPATCH_INTENT
        for item in initial.outgoing
    )
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "created",
        },
    )
    tick = store.tick(ROOT, "HST-TEST", (observation,), FIXED_TIME)
    assert tick.accepted_message_ids == (observation.artifact_id,)
    assert tick.outgoing == ()
    state = tick.state.value
    assert isinstance(state, SchedulerState)
    blocked = next(item for item in state.tasks if item.task_id == "TSK-A-WORKTREE")
    assert blocked.state.value == "running"
    assert blocked.outcome.value == "none"
    assert blocked.blockers[0].code == "budget-exhausted"
    assert len(state.lease_ids) == 2
    assert len(state.worktree_lease_ids) == 1
    event_count = len(store.export("events"))
    unchanged = store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    assert unchanged.outgoing == ()
    assert len(store.export("events")) == event_count
    store.validate()


def test_delayed_worktree_budget_failure_does_not_consume_exact_approval(
    tmp_path: Path,
) -> None:
    graph = worktree_graph()
    template = graph.tasks[0]
    worktree_task = replace(
        template,
        task_id="TSK-A-WORKTREE",
        required_tools=("git",),
        approval_stops=("owner",),
    )
    regular_task = replace(
        template,
        task_id="TSK-Z-REGULAR",
        required_capabilities=("later-capability",),
        owned_paths=(),
        worktree_assignment=None,
        required_tools=("git",),
        approval_stops=(),
        review_targets=(),
    )
    graph = replace(
        graph,
        tasks=(worktree_task, regular_task),
        budget=replace(
            graph.budget,
            max_agents=2,
            max_concurrency=2,
            max_dispatches=2,
            max_tool_calls=1,
        ),
    )
    graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
    store = create_store(tmp_path, graph=graph)
    assert store.tick(ROOT, "HST-TEST", (), FIXED_TIME).outgoing == ()
    lease_artifact = next(
        item
        for item in store.export("leases")
        if isinstance(item.value, Lease) and item.value.task_id == worktree_task.task_id
    )
    lease = lease_artifact.value
    assert isinstance(lease, Lease)
    binding = next(
        item for item in graph.contexts if item.artifact_id == worktree_task.context_snapshot_id
    )
    effect_digest = hashlib.sha256(
        canonical_json_bytes(worktree_task.to_dict())
    ).hexdigest().upper()
    approval = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.APPROVAL_DECISION,
            direction=MessageDirection.OWNER_TO_SCHEDULER,
            sender="HST-OWNER",
            recipient="HST-SCHEDULER",
            graph_id=graph_artifact.artifact_id,
            task_id=worktree_task.task_id,
            candidate=graph.candidate,
            context_snapshot_id=worktree_task.context_snapshot_id,
            attempt=lease.attempt,
            lease_id=lease_artifact.artifact_id,
            fence=lease.fence,
            idempotency_key=lease.idempotency_key,
            sensitivity=binding.sensitivity,
            provenance=(binding.reference,),
            causal_parent_message_ids=(),
            recorded_at=format_utc(FIXED_TIME),
            payload={
                "approval_id": "APR-M6-DELAYED-BUDGET",
                "approval_type": "owner",
                "decision": "approved",
                "transition": "dispatch",
                "effect_digest": effect_digest,
                "approved_at": format_utc(FIXED_TIME),
                "expires_at": format_utc(FIXED_TIME + timedelta(hours=1)),
                "authority": "Owner",
                "supersedes_approval_id": None,
            },
        ),
    )
    approval_tick = store.tick(ROOT, "HST-TEST", (approval,), FIXED_TIME)
    request = next(
        item
        for item in approval_tick.outgoing
        if isinstance(item.value, MailboxMessage)
        and item.value.message_type is MessageType.WORKTREE_REQUEST
    )

    capability = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.CAPABILITY_OBSERVATION,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender="HST-TEST",
            recipient="HST-SCHEDULER",
            graph_id=graph_artifact.artifact_id,
            task_id=None,
            candidate=graph.candidate,
            context_snapshot_id=None,
            attempt=None,
            lease_id=None,
            fence=None,
            idempotency_key=None,
            sensitivity=binding.sensitivity,
            provenance=(),
            causal_parent_message_ids=(),
            recorded_at=format_utc(FIXED_TIME),
            payload={"capabilities": ["later-capability"]},
        ),
    )
    regular_dispatch = store.tick(ROOT, "HST-TEST", (capability,), FIXED_TIME).outgoing
    assert len(regular_dispatch) == 1
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "created",
        },
    )
    blocked = store.tick(ROOT, "HST-TEST", (observation,), FIXED_TIME)
    assert blocked.outgoing == ()
    blocked_state = blocked.state.value
    assert isinstance(blocked_state, SchedulerState)
    task_projection = next(
        item for item in blocked_state.tasks if item.task_id == worktree_task.task_id
    )
    assert task_projection.state.value == "running"
    assert task_projection.outcome.value == "none"
    assert task_projection.blockers[0].code == "budget-exhausted"
    request_value = request.value
    assert isinstance(request_value, MailboxMessage)
    preserved_lease_id = request_value.lease_id
    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM approval_consumptions WHERE approval_id = ?",
            ("APR-M6-DELAYED-BUDGET",),
        ).fetchone()[0] == 0
    finally:
        connection.close()

    regular_result = result_message(regular_dispatch[0], tool_calls=0)
    activated = store.tick(ROOT, "HST-TEST", (regular_result,), FIXED_TIME)
    assert len(activated.outgoing) == 1
    dispatch = activated.outgoing[0].value
    assert isinstance(dispatch, MailboxMessage)
    assert dispatch.message_type is MessageType.DISPATCH_INTENT
    assert dispatch.task_id == worktree_task.task_id
    assert dispatch.lease_id == preserved_lease_id
    assert dispatch.causal_parent_message_ids == (observation.artifact_id,)
    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM approval_consumptions WHERE approval_id = ?",
            ("APR-M6-DELAYED-BUDGET",),
        ).fetchone()[0] == 1
    finally:
        connection.close()
    store.validate()
