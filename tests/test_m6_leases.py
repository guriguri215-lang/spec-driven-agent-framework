"""M6 lease fencing, heartbeat, expiry, and late-message tests."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from sdaqf.adapters.scheduler import SchedulerAdapterError
from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.scheduler_contracts import scheduler_identity
from sdaqf.domain.scheduler import (
    BudgetLedger,
    Lease,
    MailboxMessage,
    MessageType,
    SchedulerArtifactType,
    SchedulerState,
)
from tests.m6_scheduler_helpers import (
    FIXED_TIME,
    ROOT,
    MutableClock,
    create_store,
    first_dispatch,
    graph_value,
    host_message,
    result_message,
    worktree_graph,
)


def test_expiry_retries_read_only_work_with_monotonic_fence(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    first = first_dispatch(store)
    clock = MutableClock()
    clock.advance(60)
    tick = store.tick(ROOT, "HST-TEST", (), clock.now())
    assert len(tick.outgoing) == 1
    second = tick.outgoing[0].value
    original = first.value
    assert isinstance(second, MailboxMessage)
    assert isinstance(original, MailboxMessage)
    assert second.attempt == 2
    assert second.fence == 2
    assert second.lease_id != original.lease_id


def test_heartbeat_extends_lease_and_is_recorded(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    clock = MutableClock()
    clock.advance(10)
    heartbeat = host_message(
        dispatch,
        MessageType.HEARTBEAT,
        {"progress": "Still working."},
        clock=clock.now(),
    )
    tick = store.tick(ROOT, "HST-TEST", (heartbeat,), clock.now())
    assert tick.accepted_message_ids == (heartbeat.artifact_id,)
    clock.advance(55)
    assert store.tick(ROOT, "HST-TEST", (), clock.now()).outgoing == ()
    state = store.status().value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].attempt == 1


def test_distinct_periodic_heartbeats_refresh_portable_lease_projection(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    clock = MutableClock()
    for seconds, progress in ((10, "first"), (30, "second")):
        clock.advance(seconds)
        heartbeat = host_message(
            dispatch,
            MessageType.HEARTBEAT,
            {"progress": progress},
            clock=clock.now(),
        )
        tick = store.tick(ROOT, "HST-TEST", (heartbeat,), clock.now())
        assert tick.accepted_message_ids == (heartbeat.artifact_id,)
    leases = store.export("leases")
    assert len(leases) == 3
    assert len({item.artifact_id for item in leases}) == 3
    latest = leases[-1].value
    assert isinstance(latest, Lease)
    assert latest.heartbeat_at == "2026-08-01T00:00:40Z"
    assert latest.expires_at == "2026-08-01T00:01:40Z"
    state = store.status().value
    assert isinstance(state, SchedulerState)
    dispatch_value = dispatch.value
    assert isinstance(dispatch_value, MailboxMessage)
    assert state.lease_ids == (dispatch_value.lease_id,)
    store.validate()


def test_foreign_and_late_messages_are_rejected_without_adoption(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    first = first_dispatch(store)
    foreign = host_message(
        first,
        MessageType.HEARTBEAT,
        {"progress": "Wrong owner."},
        sender="HST-FOREIGN",
    )
    rejected = store.tick(ROOT, "HST-TEST", (foreign,), FIXED_TIME)
    assert rejected.rejected_message_ids == (foreign.artifact_id,)

    clock = MutableClock()
    clock.advance(61)
    second = store.tick(ROOT, "HST-TEST", (), clock.now()).outgoing[0]
    late = host_message(
        first,
        MessageType.HEARTBEAT,
        {"progress": "Late old fence."},
        clock=clock.now(),
    )
    tick = store.tick(ROOT, "HST-TEST", (late,), clock.now())
    assert tick.rejected_message_ids == (late.artifact_id,)
    second_message = second.value
    assert isinstance(second_message, MailboxMessage)
    assert second_message.fence == 2


def test_heartbeat_arriving_after_expiry_is_rejected_before_recovery(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    clock = MutableClock()
    clock.advance(61)
    late = host_message(
        dispatch,
        MessageType.HEARTBEAT,
        {"progress": "Already expired."},
        clock=clock.now(),
    )
    tick = store.tick(ROOT, "HST-TEST", (late,), clock.now())
    assert tick.rejected_message_ids == (late.artifact_id,)
    assert len(tick.outgoing) == 1


@pytest.mark.parametrize("seconds", [60, 61])
@pytest.mark.parametrize(
    ("message_type", "payload"),
    [
        (
            MessageType.DISPATCH_ACKNOWLEDGEMENT,
            {"accepted": True, "effect_observed": "none", "note": None},
        ),
        (MessageType.HEARTBEAT, {"progress": "Expired traffic."}),
    ],
)
def test_dispatch_traffic_at_or_after_expiry_is_rejected(
    tmp_path: Path,
    seconds: int,
    message_type: MessageType,
    payload: dict[str, object],
) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    observed_at = FIXED_TIME + timedelta(seconds=seconds)
    message = host_message(dispatch, message_type, payload, clock=observed_at)
    tick = store.tick(ROOT, "HST-TEST", (message,), observed_at)
    assert tick.rejected_message_ids == (message.artifact_id,)


@pytest.mark.parametrize("seconds", [60, 61])
def test_result_at_or_after_expiry_is_rejected(tmp_path: Path, seconds: int) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    observed_at = FIXED_TIME + timedelta(seconds=seconds)
    result = result_message(dispatch, clock=observed_at)
    tick = store.tick(ROOT, "HST-TEST", (result,), observed_at)
    assert tick.rejected_message_ids == (result.artifact_id,)


@pytest.mark.parametrize("seconds", [60, 61])
def test_cancel_acknowledgement_at_or_after_expiry_is_rejected(
    tmp_path: Path, seconds: int
) -> None:
    store = create_store(tmp_path)
    first_dispatch(store)
    cancel = store.request_cancel(
        ROOT, "HST-TEST", "TSK-M6-DEMO", "Owner requested stop.", FIXED_TIME
    )
    observed_at = FIXED_TIME + timedelta(seconds=seconds)
    acknowledgement = host_message(
        cancel,
        MessageType.CANCEL_ACKNOWLEDGEMENT,
        {"cancelled": True, "effect_observed": "none"},
        clock=observed_at,
    )
    tick = store.tick(ROOT, "HST-TEST", (acknowledgement,), observed_at)
    assert tick.rejected_message_ids == (acknowledgement.artifact_id,)


@pytest.mark.parametrize("seconds", [60, 61])
def test_cancel_request_at_or_after_expiry_emits_no_stale_egress(
    tmp_path: Path, seconds: int
) -> None:
    store = create_store(tmp_path)
    first_dispatch(store)
    requested_at = FIXED_TIME + timedelta(seconds=seconds)
    with pytest.raises(SchedulerAdapterError, match="current host-owned lease"):
        store.request_cancel(
            ROOT,
            "HST-TEST",
            "TSK-M6-DEMO",
            "Owner requested stop.",
            requested_at,
        )
    cancel_messages = [
        item
        for item in store.export("messages")
        if isinstance(item.value, MailboxMessage)
        and item.value.message_type is MessageType.CANCEL_REQUEST
    ]
    assert cancel_messages == []
    state = store.status().value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].dispatch_phase.value != "cancellation_requested"


def test_cancel_request_replay_revalidates_expiry_before_returning_existing_intent(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path)
    first_dispatch(store)
    original = store.request_cancel(
        ROOT,
        "HST-TEST",
        "TSK-M6-DEMO",
        "Owner requested stop.",
        FIXED_TIME + timedelta(seconds=59),
    )
    assert (
        store.request_cancel(
            ROOT,
            "HST-TEST",
            "TSK-M6-DEMO",
            "Owner requested stop.",
            FIXED_TIME + timedelta(seconds=59),
        )
        == original
    )
    with pytest.raises(SchedulerAdapterError, match="current host-owned lease"):
        store.request_cancel(
            ROOT,
            "HST-TEST",
            "TSK-M6-DEMO",
            "Owner requested stop.",
            FIXED_TIME + timedelta(seconds=60),
        )
    cancel_messages = [
        item
        for item in store.export("messages")
        if isinstance(item.value, MailboxMessage)
        and item.value.message_type is MessageType.CANCEL_REQUEST
    ]
    assert cancel_messages == [original]
    state = store.status().value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].dispatch_phase.value != "cancellation_requested"


@pytest.mark.parametrize("seconds", [60, 61])
def test_worktree_observation_at_or_after_expiry_is_rejected(
    tmp_path: Path, seconds: int
) -> None:
    store = create_store(tmp_path, graph=worktree_graph())
    request = first_dispatch(store)
    observed_at = FIXED_TIME + timedelta(seconds=seconds)
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "created",
        },
        clock=observed_at,
    )
    tick = store.tick(ROOT, "HST-TEST", (observation,), observed_at)
    assert tick.rejected_message_ids == (observation.artifact_id,)


def test_expired_approval_proposal_rotates_without_consuming_an_attempt_or_budget(
    tmp_path: Path,
) -> None:
    graph = graph_value()
    task = replace(graph.tasks[0], approval_stops=("owner",), max_attempts=1)
    store = create_store(tmp_path, graph=replace(graph, tasks=(task,)))
    first = store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    assert first.outgoing == ()
    first_proposal = store.export("leases")[-1]

    clock = MutableClock()
    clock.advance(61)
    second = store.tick(ROOT, "HST-TEST", (), clock.now())
    assert second.outgoing == ()
    leases = store.export("leases")
    latest = leases[-1].value
    assert isinstance(latest, Lease)
    assert latest.status.value == "current"
    assert leases[-1].artifact_id != first_proposal.artifact_id
    state = store.status().value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].attempt == 1
    assert state.tasks[0].blockers[0].code == "approval-required"
    ledger = store.export("budget")[-1].value
    assert isinstance(ledger, BudgetLedger)
    assert ledger.reserved["concurrency"] == 0
    assert ledger.used["dispatches"] == 0
    store.validate()


def test_authoritative_store_rejects_rehashed_cross_field_lease_drift(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path)
    first_dispatch(store)
    connection = sqlite3.connect(store.path)
    try:
        row = connection.execute(
            "SELECT artifact_json FROM current_leases"
        ).fetchone()
        payload = json.loads(row[0])
        payload["content"]["heartbeat_interval_seconds"] = 31
        artifact_id = scheduler_identity(
            SchedulerArtifactType.LEASE, payload["content"]
        )
        payload["artifact_id"] = artifact_id
        artifact_json = canonical_json_bytes(payload).decode("ascii")
        connection.execute(
            "UPDATE current_leases SET projection_artifact_id = ?, artifact_json = ?",
            (artifact_id, artifact_json),
        )
        connection.execute(
            "UPDATE lease_history SET artifact_id = ?, artifact_json = ? "
            "WHERE status = 'current'",
            (artifact_id, artifact_json),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError, match="Authoritative Lease"):
        store.validate()


def test_rehashed_heartbeat_history_must_equal_event_time_plus_original_ttl(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    clock = MutableClock()
    clock.advance(10)
    heartbeat = host_message(
        dispatch,
        MessageType.HEARTBEAT,
        {"progress": "exact heartbeat"},
        clock=clock.now(),
    )
    store.tick(ROOT, "HST-TEST", (heartbeat,), clock.now())

    connection = sqlite3.connect(store.path)
    try:
        row = connection.execute(
            "SELECT artifact_json FROM lease_history ORDER BY event_sequence DESC LIMIT 1"
        ).fetchone()
        payload = json.loads(row[0])
        payload["content"]["heartbeat_at"] = "2026-08-01T00:00:11Z"
        payload["content"]["expires_at"] = "2026-08-01T00:01:11Z"
        artifact_id = scheduler_identity(
            SchedulerArtifactType.LEASE, payload["content"]
        )
        payload["artifact_id"] = artifact_id
        artifact_json = canonical_json_bytes(payload).decode("ascii")
        connection.execute(
            "UPDATE lease_history SET artifact_id = ?, artifact_json = ? "
            "WHERE event_sequence = (SELECT MAX(event_sequence) FROM lease_history)",
            (artifact_id, artifact_json),
        )
        connection.execute(
            "UPDATE current_leases SET projection_artifact_id = ?, heartbeat_at = ?, "
            "expires_at = ?, artifact_json = ?",
            (
                artifact_id,
                payload["content"]["heartbeat_at"],
                payload["content"]["expires_at"],
                artifact_json,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="Lease history semantics"):
        store.validate_evidence()
