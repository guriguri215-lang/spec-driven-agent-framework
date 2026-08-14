"""M6 SQLite scheduler store invariants."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from sdaqf.adapters.scheduler import (
    APPLICATION_ID,
    TABLE_NAMES,
    USER_VERSION,
    WORKFLOW_TABLE_NAMES,
    WORKFLOW_USER_VERSION,
    SchedulerAdapterError,
    SQLiteSchedulerStore,
    _reduce_workflow_event,
    _validate_workflow_epoch_evidence,
    recover_scheduler_database,
)
from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.scheduler import _existing_under_root
from sdaqf.application.scheduler_contracts import (
    MAX_TASKS,
    SchedulerContractError,
    artifact_from_value,
    load_scheduler_artifact,
)
from sdaqf.domain.scheduler import (
    BudgetLedger,
    Lease,
    MailboxMessage,
    MessageType,
    SchedulerArtifactType,
    SchedulerEvent,
    SchedulerState,
    WorkflowEpochEvent,
    WorkflowEpochPhase,
    WorktreeLease,
)
from tests.m6_scheduler_helpers import (
    FIXED_TIME,
    ROOT,
    create_store,
    first_dispatch,
    graph_artifact,
    host_message,
    result_message,
    worktree_graph,
)


def test_initial_database_has_exact_identity_shape_and_projection(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    store.validate()
    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert connection.execute("PRAGMA user_version").fetchone()[0] == USER_VERSION
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        connection.close()
    assert tables == TABLE_NAMES
    state = store.status().value
    assert isinstance(state, SchedulerState)
    assert state.event_sequence == 1
    assert state.ready_order == ("TSK-M6-DEMO",)
    assert store.graph_artifact() == graph_artifact()


def test_historical_status_requires_one_exact_existing_event_prefix(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    current = store.status()
    state = current.value
    assert isinstance(state, SchedulerState)
    assert store.historical_status(state.event_sequence) == current
    with pytest.raises(SchedulerAdapterError, match="prefix is unavailable"):
        store.historical_status(state.event_sequence + 1)
    with pytest.raises(SchedulerAdapterError, match="sequence is invalid"):
        store.historical_status(0)


def test_evidence_history_is_not_truncated_to_a_portable_export_page(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    heartbeats = tuple(
        host_message(
            dispatch,
            MessageType.HEARTBEAT,
            {"progress": f"bounded-history-{index:04d}"},
        )
        for index in range(3)
    )
    tick = store.tick(ROOT, "HST-TEST", heartbeats, FIXED_TIME)
    assert len(tick.accepted_message_ids) == 3
    state = tick.state.value
    assert isinstance(state, SchedulerState)
    portable_page = store.export("events", limit=2)
    complete = store.evidence_history(
        "events",
        through_event_sequence=state.event_sequence,
    )
    assert len(portable_page) == 2
    assert len(complete) == state.event_sequence
    assert len(complete) > len(portable_page)
    assert complete[-1].artifact_id == store.current_event_head_id


def test_evidence_history_covers_every_kind_and_rejects_invalid_bounds(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path)
    first_dispatch(store)
    state = store.status().value
    assert isinstance(state, SchedulerState)

    expected_types = {
        "leases": Lease,
        "messages": MailboxMessage,
        "events": SchedulerEvent,
        "budget": BudgetLedger,
    }
    for kind, expected_type in expected_types.items():
        history = store.evidence_history(
            kind,
            through_event_sequence=state.event_sequence,
        )
        assert history
        assert all(isinstance(item.value, expected_type) for item in history)
    assert (
        store.evidence_history(
            "messages",
            through_event_sequence=1,
        )
        == ()
    )
    assert (
        store.evidence_history(
            "worktrees",
            through_event_sequence=state.event_sequence,
        )
        == ()
    )

    worktree_root = tmp_path / "worktree-case"
    worktree_root.mkdir()
    worktree_store = create_store(worktree_root, graph=worktree_graph())
    first_dispatch(worktree_store)
    worktree_state = worktree_store.status().value
    assert isinstance(worktree_state, SchedulerState)
    worktrees = worktree_store.evidence_history(
        "worktrees",
        through_event_sequence=worktree_state.event_sequence,
    )
    assert worktrees
    assert all(isinstance(item.value, WorktreeLease) for item in worktrees)

    with pytest.raises(SchedulerAdapterError, match="kind is unsupported"):
        store.evidence_history("unknown", through_event_sequence=0)
    with pytest.raises(SchedulerAdapterError, match="bound is invalid"):
        store.evidence_history("events", through_event_sequence=-1)
    with pytest.raises(SchedulerAdapterError, match="beyond the current event head"):
        store.evidence_history(
            "events",
            through_event_sequence=state.event_sequence + 1,
        )


@pytest.mark.parametrize("corruption", ["missing", "wrong-type", "over-bound"])
def test_completed_result_history_fails_closed_on_corrupt_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    result = result_message(dispatch)
    store.tick(ROOT, "HST-TEST", (result,), FIXED_TIME)
    completed = store.completed_task_result_messages()
    assert tuple(item.artifact_id for item in completed) == (result.artifact_id,)
    verification = next(
        item
        for item in store.export("events")
        if isinstance(item.value, SchedulerEvent)
        and item.value.cause == "verification-completed"
    )

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE events(sequence INTEGER, artifact_json TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE messages(artifact_id TEXT, artifact_json TEXT NOT NULL)"
    )
    event_count = MAX_TASKS + 1 if corruption == "over-bound" else 1
    connection.executemany(
        "INSERT INTO events(sequence, artifact_json) VALUES (?, ?)",
        (
            (sequence, canonical_json_bytes(verification.to_dict()).decode("ascii"))
            for sequence in range(1, event_count + 1)
        ),
    )
    if corruption == "wrong-type":
        connection.execute(
            "INSERT INTO messages(artifact_id, artifact_json) VALUES (?, ?)",
            (
                result.artifact_id,
                canonical_json_bytes(dispatch.to_dict()).decode("ascii"),
            ),
        )

    @contextmanager
    def corrupted_read_connection() -> Iterator[sqlite3.Connection]:
        yield connection

    monkeypatch.setattr(store, "_read_connection", corrupted_read_connection)
    expected = {
        "missing": "evidence is missing",
        "wrong-type": "not a Task Result",
        "over-bound": "exceed the graph bound",
    }[corruption]
    try:
        with pytest.raises(SchedulerAdapterError, match=expected):
            store.completed_task_result_messages()
    finally:
        connection.close()


def test_v2_workflow_epoch_terminal_reserve_confirm_and_replay(tmp_path: Path) -> None:
    store = create_store(tmp_path, workflow_authority=True)
    assert store.store_version == WORKFLOW_USER_VERSION
    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == WORKFLOW_USER_VERSION
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        connection.close()
    assert tables == WORKFLOW_TABLE_NAMES
    graph = graph_artifact()
    state = store.status()
    state_value = state.value
    assert isinstance(state_value, SchedulerState)
    plan_id = "M8-INTEGRATED-PLAN-" + "A" * 64
    plan_path = "workflow/plan.json"
    head = store.open_workflow_epoch(
        plan_id=plan_id,
        candidate=graph.value.candidate,  # type: ignore[union-attr]
        graph_id=graph.artifact_id,
        scheduler_state_id=state.artifact_id,
        scheduler_event_sequence=state_value.event_sequence,
        scheduler_event_head_id=store.current_event_head_id,
        idempotency_key="M8-IDEM-" + "1" * 64,
        producer="workflow-plan",
        artifact_id=plan_id,
        artifact_type="integrated-plan",
        path=plan_path,
        recorded_at=FIXED_TIME,
    )
    assert head.phase is WorkflowEpochPhase.OPEN
    assert (
        store.open_workflow_epoch(
            plan_id=plan_id,
            candidate=graph.value.candidate,  # type: ignore[union-attr]
            graph_id=graph.artifact_id,
            scheduler_state_id=state.artifact_id,
            scheduler_event_sequence=state_value.event_sequence,
            scheduler_event_head_id=store.current_event_head_id,
            idempotency_key="M8-IDEM-" + "1" * 64,
            producer="workflow-plan",
            artifact_id=plan_id,
            artifact_type="integrated-plan",
            path=plan_path,
            recorded_at=FIXED_TIME,
        )
        == head
    )
    with pytest.raises(SchedulerAdapterError, match="different authority"):
        store.open_workflow_epoch(
            plan_id=plan_id,
            candidate=graph.value.candidate,  # type: ignore[union-attr]
            graph_id=graph.artifact_id,
            scheduler_state_id=state.artifact_id,
            scheduler_event_sequence=state_value.event_sequence,
            scheduler_event_head_id=store.current_event_head_id,
            idempotency_key="M8-IDEM-" + "1" * 64,
            producer="workflow-plan",
            artifact_id=plan_id,
            artifact_type="integrated-plan",
            path=plan_path,
            recorded_at=FIXED_TIME,
            predecessor_plan_id="M8-INTEGRATED-PLAN-" + "B" * 64,
            predecessor_terminal_event_head_id="M6-WORKFLOW-EPOCH-EVENT-" + "C" * 64,
            predecessor_state_id="M8-WORKFLOW-STATE-" + "D" * 64,
            predecessor_outcome_id="M8-WORKFLOW-OUTCOME-" + "E" * 64,
        )
    head = store.confirm_workflow_artifact(
        plan_id=plan_id,
        expected_head_id=head.current_event_head_id,
        artifact_id=plan_id,
        artifact_type="integrated-plan",
        path=plan_path,
        idempotency_key="M8-IDEM-" + "1" * 64,
        producer="workflow-plan",
        recorded_at=FIXED_TIME,
    )
    assert head.phase is WorkflowEpochPhase.ACTIVE
    head = store.reserve_workflow_transition(
        plan_id=plan_id,
        expected_head_id=head.current_event_head_id,
        scheduler_state_id=state.artifact_id,
        scheduler_event_sequence=state_value.event_sequence,
        scheduler_event_head_id=store.current_event_head_id,
        source_state_id=None,
        workflow_event_id="M8-WORKFLOW-EVENT-" + "F" * 64,
        workflow_state_id="M8-WORKFLOW-STATE-" + "B" * 64,
        idempotency_key="M8-IDEM-" + "3" * 64,
        producer="workflow-run",
        event_path="workflow/run-event.json",
        state_path="workflow/run-state.json",
        recorded_at=FIXED_TIME,
    )
    for artifact_type, artifact_id, path in (
        ("workflow-event", "M8-WORKFLOW-EVENT-" + "F" * 64, "workflow/run-event.json"),
        ("workflow-state", "M8-WORKFLOW-STATE-" + "B" * 64, "workflow/run-state.json"),
    ):
        head = store.confirm_workflow_artifact(
            plan_id=plan_id,
            expected_head_id=head.current_event_head_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            path=path,
            idempotency_key="M8-IDEM-" + "3" * 64,
            producer="workflow-run",
            recorded_at=FIXED_TIME,
        )
    assert head.phase is WorkflowEpochPhase.ACTIVE
    head = store.reserve_workflow_terminal(
        plan_id=plan_id,
        expected_head_id=head.current_event_head_id,
        scheduler_state_id=state.artifact_id,
        scheduler_event_sequence=state_value.event_sequence,
        scheduler_event_head_id=store.current_event_head_id,
        source_state_id="M8-WORKFLOW-STATE-" + "B" * 64,
        workflow_event_id="M8-WORKFLOW-EVENT-" + "C" * 64,
        workflow_state_id="M8-WORKFLOW-STATE-" + "D" * 64,
        outcome_id="M8-WORKFLOW-OUTCOME-" + "E" * 64,
        idempotency_key="M8-IDEM-" + "2" * 64,
        producer="workflow-outcome",
        event_path="workflow/event.json",
        state_path="workflow/state.json",
        outcome_path="workflow/outcome.json",
        recorded_at=FIXED_TIME,
    )
    assert head.phase is WorkflowEpochPhase.TERMINAL_RESERVED
    for artifact_type, artifact_id, path in (
        ("workflow-event", "M8-WORKFLOW-EVENT-" + "C" * 64, "workflow/event.json"),
        ("workflow-outcome", "M8-WORKFLOW-OUTCOME-" + "E" * 64, "workflow/outcome.json"),
        ("workflow-state", "M8-WORKFLOW-STATE-" + "D" * 64, "workflow/state.json"),
    ):
        head = store.confirm_workflow_artifact(
            plan_id=plan_id,
            expected_head_id=head.current_event_head_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            path=path,
            idempotency_key="M8-IDEM-" + "2" * 64,
            producer="workflow-outcome",
            recorded_at=FIXED_TIME,
        )
        assert head.phase is WorkflowEpochPhase.TERMINAL_RESERVED
    head = store.confirm_workflow_terminal(
        plan_id=plan_id,
        expected_head_id=head.current_event_head_id,
        idempotency_key="M8-IDEM-" + "2" * 64,
        producer="workflow-outcome",
        recorded_at=FIXED_TIME,
    )
    assert head.phase is WorkflowEpochPhase.TERMINAL_CONFIRMED
    assert store.workflow_head(plan_id) == head
    assert len(store.export("workflow-epochs")) == 10
    recovered = recover_scheduler_database(
        store.path,
        tmp_path / "recovered-v2.sqlite3",
        ROOT,
    )
    assert recovered.store_version == WORKFLOW_USER_VERSION
    assert recovered.workflow_head(plan_id) == head


def test_pending_terminal_blocks_mutators_and_allows_only_exact_finalization(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path, workflow_authority=True)
    graph = graph_artifact()
    state = store.status()
    state_value = state.value
    assert isinstance(state_value, SchedulerState)
    plan_id = "M8-INTEGRATED-PLAN-" + "A" * 64
    head = store.open_workflow_epoch(
        plan_id=plan_id,
        candidate=graph.value.candidate,  # type: ignore[union-attr]
        graph_id=graph.artifact_id,
        scheduler_state_id=state.artifact_id,
        scheduler_event_sequence=state_value.event_sequence,
        scheduler_event_head_id=store.current_event_head_id,
        idempotency_key="M8-IDEM-" + "1" * 64,
        producer="workflow-plan",
        artifact_id=plan_id,
        artifact_type="integrated-plan",
        path="workflow/plan.json",
        recorded_at=FIXED_TIME,
    )
    head = store.confirm_workflow_artifact(
        plan_id=plan_id,
        expected_head_id=head.current_event_head_id,
        artifact_id=plan_id,
        artifact_type="integrated-plan",
        path="workflow/plan.json",
        idempotency_key="M8-IDEM-" + "1" * 64,
        producer="workflow-plan",
        recorded_at=FIXED_TIME,
    )
    source_state_id = "M8-WORKFLOW-STATE-" + "B" * 64
    transition_event_id = "M8-WORKFLOW-EVENT-" + "F" * 64
    head = store.reserve_workflow_transition(
        plan_id=plan_id,
        expected_head_id=head.current_event_head_id,
        scheduler_state_id=state.artifact_id,
        scheduler_event_sequence=state_value.event_sequence,
        scheduler_event_head_id=store.current_event_head_id,
        source_state_id=None,
        workflow_event_id=transition_event_id,
        workflow_state_id=source_state_id,
        idempotency_key="M8-IDEM-" + "3" * 64,
        producer="workflow-run",
        event_path="workflow/run-event.json",
        state_path="workflow/run-state.json",
        recorded_at=FIXED_TIME,
    )
    for artifact_type, artifact_id, path in (
        ("workflow-event", transition_event_id, "workflow/run-event.json"),
        ("workflow-state", source_state_id, "workflow/run-state.json"),
    ):
        head = store.confirm_workflow_artifact(
            plan_id=plan_id,
            expected_head_id=head.current_event_head_id,
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            path=path,
            idempotency_key="M8-IDEM-" + "3" * 64,
            producer="workflow-run",
            recorded_at=FIXED_TIME,
        )
    event_id = "M8-WORKFLOW-EVENT-" + "C" * 64
    state_id = "M8-WORKFLOW-STATE-" + "D" * 64
    outcome_id = "M8-WORKFLOW-OUTCOME-" + "E" * 64
    head = store.reserve_workflow_terminal(
        plan_id=plan_id,
        expected_head_id=head.current_event_head_id,
        scheduler_state_id=state.artifact_id,
        scheduler_event_sequence=state_value.event_sequence,
        scheduler_event_head_id=store.current_event_head_id,
        source_state_id=source_state_id,
        workflow_event_id=event_id,
        workflow_state_id=state_id,
        outcome_id=outcome_id,
        idempotency_key="M8-IDEM-" + "2" * 64,
        producer="workflow-outcome",
        event_path="workflow/event.json",
        state_path="workflow/state.json",
        outcome_path="workflow/outcome.json",
        recorded_at=FIXED_TIME,
    )
    assert head.phase is WorkflowEpochPhase.TERMINAL_RESERVED
    with pytest.raises(SchedulerAdapterError, match="Pending terminal"):
        store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    with pytest.raises(SchedulerAdapterError, match="Workflow epoch phase"):
        store.reserve_workflow_terminal(
            plan_id=plan_id,
            expected_head_id=head.current_event_head_id,
            scheduler_state_id="M6-SCHEDULER-STATE-" + "0" * 64,
            scheduler_event_sequence=state_value.event_sequence,
            scheduler_event_head_id=store.current_event_head_id,
            source_state_id=source_state_id,
            workflow_event_id=event_id,
            workflow_state_id=state_id,
            outcome_id=outcome_id,
            idempotency_key="M8-IDEM-" + "2" * 64,
            producer="workflow-outcome",
            event_path="workflow/event.json",
            state_path="workflow/state.json",
            outcome_path="workflow/outcome.json",
            recorded_at=FIXED_TIME,
        )
    retry = store.reserve_workflow_terminal(
        plan_id=plan_id,
        expected_head_id=head.current_event_head_id,
        scheduler_state_id=state.artifact_id,
        scheduler_event_sequence=state_value.event_sequence,
        scheduler_event_head_id=store.current_event_head_id,
        source_state_id=source_state_id,
        workflow_event_id=event_id,
        workflow_state_id=state_id,
        outcome_id=outcome_id,
        idempotency_key="M8-IDEM-" + "2" * 64,
        producer="workflow-outcome",
        event_path="workflow/event.json",
        state_path="workflow/state.json",
        outcome_path="workflow/outcome.json",
        recorded_at=FIXED_TIME,
    )
    assert retry == head
    with pytest.raises(SchedulerAdapterError, match="phase rejects"):
        store.reserve_workflow_terminal(
            plan_id=plan_id,
            expected_head_id=head.current_event_head_id,
            scheduler_state_id=state.artifact_id,
            scheduler_event_sequence=state_value.event_sequence,
            scheduler_event_head_id=store.current_event_head_id,
            source_state_id=source_state_id,
            workflow_event_id=event_id,
            workflow_state_id=state_id,
            outcome_id=outcome_id,
            idempotency_key="M8-IDEM-" + "2" * 64,
            producer="workflow-outcome",
            event_path="workflow/event.json",
            state_path="workflow/state.json",
            outcome_path="workflow/outcome.json",
            recorded_at="2026-08-01T00:00:01Z",
        )
    for artifact_type, artifact_id, path in (
        ("workflow-event", event_id, "workflow/event.json"),
        ("workflow-state", state_id, "workflow/state.json"),
        ("workflow-outcome", outcome_id, "workflow/outcome.json"),
    ):
        head = store.confirm_workflow_artifact(
            plan_id=plan_id,
            expected_head_id=head.current_event_head_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            path=path,
            idempotency_key="M8-IDEM-" + "2" * 64,
            producer="workflow-outcome",
            recorded_at=FIXED_TIME,
        )
    with pytest.raises(SchedulerAdapterError, match="not admissible"):
        store.confirm_workflow_terminal(
            plan_id=plan_id,
            expected_head_id=head.current_event_head_id,
            idempotency_key="M8-IDEM-" + "2" * 64,
            producer="workflow-outcome",
            recorded_at="2026-08-01T00:00:01Z",
        )
    head = store.confirm_workflow_terminal(
        plan_id=plan_id,
        expected_head_id=head.current_event_head_id,
        idempotency_key="M8-IDEM-" + "2" * 64,
        producer="workflow-outcome",
        recorded_at=FIXED_TIME,
    )
    assert head.phase is WorkflowEpochPhase.TERMINAL_CONFIRMED
    with pytest.raises(SchedulerAdapterError, match="retry differs"):
        store.confirm_workflow_terminal(
            plan_id=plan_id,
            expected_head_id=head.current_event_head_id,
            idempotency_key="M8-IDEM-" + "2" * 64,
            producer="workflow-outcome",
            recorded_at="2026-08-01T00:00:01Z",
        )
    epoch_events = store.export("workflow-epochs")
    replayed = None
    for epoch_event in epoch_events[:-1]:
        replayed = _reduce_workflow_event(replayed, epoch_event)
    confirmed_value = epoch_events[-1].value
    assert isinstance(confirmed_value, WorkflowEpochEvent)
    forged_confirmation = artifact_from_value(
        SchedulerArtifactType.WORKFLOW_EPOCH_EVENT,
        replace(confirmed_value, recorded_at="2026-08-01T00:00:01Z"),
    )
    with pytest.raises(SchedulerAdapterError, match="terminal confirmation"):
        _reduce_workflow_event(replayed, forged_confirmation)
    assert store.tick(ROOT, "HST-TEST", (), FIXED_TIME).state.value is not None


def test_workflow_epoch_rejects_mixed_historical_scheduler_triple(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path, workflow_authority=True)
    graph = graph_artifact()
    historical = store.status()
    historical_value = historical.value
    assert isinstance(historical_value, SchedulerState)
    plan_id = "M8-INTEGRATED-PLAN-" + "9" * 64
    store.open_workflow_epoch(
        plan_id=plan_id,
        candidate=graph.value.candidate,  # type: ignore[union-attr]
        graph_id=graph.artifact_id,
        scheduler_state_id=historical.artifact_id,
        scheduler_event_sequence=historical_value.event_sequence,
        scheduler_event_head_id=store.current_event_head_id,
        idempotency_key="M8-IDEM-" + "9" * 64,
        producer="workflow-plan",
        artifact_id=plan_id,
        artifact_type="integrated-plan",
        path="workflow/mixed-plan.json",
        recorded_at=FIXED_TIME,
    )
    original = store.export("workflow-epochs")[0]
    original_value = original.value
    assert isinstance(original_value, WorkflowEpochEvent)
    forged = artifact_from_value(
        SchedulerArtifactType.WORKFLOW_EPOCH_EVENT,
        replace(
            original_value,
            scheduler_state_id="M6-SCHEDULER-STATE-" + "0" * 64,
        ),
    )
    connection = sqlite3.connect(store.path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            "UPDATE workflow_epoch_events SET artifact_id = ?, artifact_json = ? "
            "WHERE artifact_id = ?",
            (
                forged.artifact_id,
                canonical_json_bytes(forged.to_dict()).decode("ascii"),
                original.artifact_id,
            ),
        )
        connection.commit()
        with pytest.raises(SchedulerAdapterError, match="immutable historical evidence"):
            _validate_workflow_epoch_evidence(connection, graph)
    finally:
        connection.close()


def test_initialization_is_exclusive_and_paths_are_confined(tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite3"
    SQLiteSchedulerStore.initialize(state, ROOT, graph_artifact(), FIXED_TIME)
    with pytest.raises(SchedulerAdapterError, match=r"fresh|exists"):
        SQLiteSchedulerStore.initialize(state, ROOT, graph_artifact(), FIXED_TIME)
    with pytest.raises(SchedulerAdapterError):
        SQLiteSchedulerStore.initialize(tmp_path / "bad.db", ROOT, graph_artifact(), FIXED_TIME)
    lease = load_scheduler_artifact(
        ROOT / "examples" / "m6-scheduler" / "lease.json",
        expected_type=SchedulerArtifactType.LEASE,
    )
    with pytest.raises(SchedulerAdapterError, match="Task Graph"):
        SQLiteSchedulerStore.initialize(tmp_path / "wrong.sqlite3", ROOT, lease, FIXED_TIME)


def test_store_rejects_wrong_database_identity_and_event_tampering(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute("PRAGMA application_id = 0")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError):
        store.validate()

    other = SQLiteSchedulerStore.initialize(
        tmp_path / "tampered.sqlite3", ROOT, graph_artifact(), FIXED_TIME
    )
    connection = sqlite3.connect(other.path)
    try:
        connection.execute("UPDATE events SET event_sha256 = ? WHERE sequence = 1", ("F" * 64,))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError, match=r"event|chain|immutable"):
        other.validate()


def test_export_mailbox_and_tick_bounds_fail_closed(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    for kind in ("state", "leases", "messages", "events", "budget", "worktrees"):
        assert isinstance(store.export(kind), tuple)
    with pytest.raises(SchedulerAdapterError):
        store.export("unknown")
    with pytest.raises(SchedulerAdapterError):
        store.export("events", limit=0)
    with pytest.raises(SchedulerAdapterError):
        store.export("events", after_sequence=-1)
    with pytest.raises(SchedulerAdapterError):
        store.inspect_mailbox(limit=1001)
    with pytest.raises(SchedulerAdapterError):
        store.tick(ROOT, "not-a-host", (), FIXED_TIME)
    with pytest.raises(SchedulerAdapterError):
        store.tick(ROOT, "HST-TEST", (), FIXED_TIME, lease_ttl_seconds=29)
    with pytest.raises(SchedulerAdapterError):
        store.tick(
            ROOT,
            "HST-TEST",
            (),
            FIXED_TIME,
            lease_ttl_seconds=60,
            heartbeat_interval_seconds=31,
        )


def test_lease_policy_is_selected_at_initialization_and_immutable_per_store(
    tmp_path: Path,
) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "custom-policy.sqlite3",
        ROOT,
        graph_artifact(),
        FIXED_TIME,
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
    )
    with pytest.raises(SchedulerAdapterError, match="immutable initialization policy"):
        store.tick(ROOT, "HST-TEST", (), FIXED_TIME)

    tick = store.tick(
        ROOT,
        "HST-TEST",
        (),
        FIXED_TIME,
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
    )
    message = tick.outgoing[0].value
    lease = store.export("leases")[0].value
    assert isinstance(message, MailboxMessage)
    assert isinstance(lease, Lease)
    assert message.payload["lease_ttl_seconds"] == lease.ttl_seconds == 120
    assert message.payload["heartbeat_interval_seconds"] == lease.heartbeat_interval_seconds == 30
    store.validate()


def test_only_one_tick_can_claim_the_single_ready_task(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    first = store.tick(ROOT, "HST-FIRST", (), FIXED_TIME)
    second = store.tick(ROOT, "HST-SECOND", (), FIXED_TIME)
    assert len(first.outgoing) == 1
    assert second.outgoing == ()
    leases = store.export("leases")
    assert len(leases) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM metadata WHERE key = 'schema_version'",
        "UPDATE metadata SET value = '0.0' WHERE key = 'schema_version'",
        "UPDATE metadata SET value = '{' WHERE key = 'host_capabilities'",
        "UPDATE metadata SET value = '[]' WHERE key = 'host_capabilities'",
        "UPDATE metadata SET value = "
        "'M6-GRAPH-0000000000000000000000000000000000000000000000000000000000000000' "
        "WHERE key = 'graph_id'",
        "DELETE FROM task_graph",
        "CREATE TABLE unexpected(value TEXT)",
        "ALTER TABLE tasks ADD COLUMN drift TEXT",
        "UPDATE tasks SET attempt = 3 WHERE task_id = 'TSK-M6-DEMO'",
        "UPDATE tasks SET state = 'blocked' WHERE task_id = 'TSK-M6-DEMO'",
        "UPDATE budget_totals SET used = 1 WHERE resource = 'tool_calls'",
    ],
)
def test_database_shape_metadata_and_projection_drift_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    store = create_store(tmp_path)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(mutation)
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError):
        store.validate()


def test_constructor_rejects_missing_wrong_suffix_and_outside_root(tmp_path: Path) -> None:
    with pytest.raises(SchedulerAdapterError):
        SQLiteSchedulerStore(tmp_path / "missing.sqlite3", ROOT)
    wrong = tmp_path / "state.db"
    wrong.write_bytes(b"not sqlite")
    with pytest.raises(SchedulerAdapterError):
        SQLiteSchedulerStore(wrong, ROOT)


@pytest.mark.parametrize("link_kind", ["symlink", "junction"])
def test_linked_ancestor_is_rejected_before_resolution(
    tmp_path: Path, link_kind: str
) -> None:
    if not tmp_path.is_relative_to(ROOT):
        pytest.skip("pytest temporary root is outside the repository")
    real = tmp_path / "real"
    linked = tmp_path / "linked"
    real.mkdir()
    if link_kind == "symlink":
        try:
            linked.symlink_to(real, target_is_directory=True)
        except OSError:
            pytest.skip("directory symlinks are unavailable")
    else:
        if os.name != "nt":
            pytest.skip("directory junctions are Windows-only")
        junction = subprocess.run(
            ("cmd.exe", "/d", "/c", "mklink", "/J", str(linked), str(real)),
            check=False,
            capture_output=True,
        )
        if junction.returncode != 0:
            pytest.skip("directory junctions are unavailable")

    with pytest.raises(SchedulerAdapterError, match=r"linked|irregular"):
        SQLiteSchedulerStore.initialize(
            linked / "state.sqlite3", ROOT, graph_artifact(), FIXED_TIME
        )

    artifact = real / "task-graph.json"
    artifact.write_bytes(
        (ROOT / "examples" / "m6-scheduler" / "task-graph.json").read_bytes()
    )
    with pytest.raises(SchedulerContractError, match=r"linked|regular"):
        _existing_under_root(ROOT, linked / "task-graph.json", ".json")
