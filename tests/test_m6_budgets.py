"""M6 transactional budget tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from sdaqf.adapters.scheduler import (
    SchedulerAdapterError,
    SQLiteSchedulerStore,
    recover_scheduler_database,
)
from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    artifact_from_value,
    event_digest,
)
from sdaqf.application.scheduler_simulation import SchedulerSimulationService
from sdaqf.domain.scheduler import (
    Blocker,
    BudgetLedger,
    DispatchPhase,
    MailboxMessage,
    MessageType,
    SchedulerArtifactType,
    SchedulerEvent,
    SchedulerState,
    TaskOutcome,
    TaskProjection,
    TaskState,
)
from tests.m6_scheduler_helpers import (
    FIXED_TIME,
    ROOT,
    TASK_GRAPH_PATH,
    first_dispatch,
    graph_value,
    host_message,
    result_message,
)


def _replace_budget_entry(
    store: SQLiteSchedulerStore,
    original: LoadedSchedulerArtifact,
    replacement: BudgetLedger,
) -> None:
    original_value = original.value
    assert isinstance(original_value, BudgetLedger)
    artifact = artifact_from_value(SchedulerArtifactType.BUDGET_LEDGER, replacement)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "UPDATE budget_entries SET artifact_id = ?, artifact_json = ? WHERE event_sequence = ?",
            (
                artifact.artifact_id,
                canonical_json_bytes(artifact.to_dict()).decode("ascii"),
                original_value.event_sequence,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _rehash_event_chain(
    connection: sqlite3.Connection,
    events: tuple[LoadedSchedulerArtifact, ...],
    replacements: dict[int, SchedulerEvent],
) -> None:
    previous = "0" * 64
    for loaded in events:
        event = loaded.value
        assert isinstance(event, SchedulerEvent)
        selected = replacements.get(event.sequence, event)
        rewritten = replace(selected, previous_event_sha256=previous)
        artifact = artifact_from_value(SchedulerArtifactType.SCHEDULER_EVENT, rewritten)
        digest = event_digest(artifact)
        connection.execute(
            "UPDATE events SET artifact_id = ?, event_sha256 = ?, previous_sha256 = ?, "
            "artifact_json = ? WHERE sequence = ?",
            (
                artifact.artifact_id,
                digest,
                previous,
                canonical_json_bytes(artifact.to_dict()).decode("ascii"),
                rewritten.sequence,
            ),
        )
        previous = digest


def test_initial_ledger_has_exact_availability_and_zero_usage(tmp_path: Path) -> None:
    graph = graph_value()
    artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
    store = SQLiteSchedulerStore.initialize(tmp_path / "budget.sqlite3", ROOT, artifact, FIXED_TIME)
    ledgers = store.export("budget")
    assert len(ledgers) == 1
    value = ledgers[0].value
    assert isinstance(value, BudgetLedger)
    assert set(value.reserved) == set(value.used) == set(value.availability)
    assert all(count == 0 for count in value.reserved.values())
    assert value.availability["microunits"] == "not_available"


def test_dispatch_reserves_resources_atomically(tmp_path: Path) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "budget.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph_value()),
        FIXED_TIME,
    )
    tick = store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    assert len(tick.outgoing) == 1
    value = store.export("budget")[-1].value
    assert isinstance(value, BudgetLedger)
    assert value.reserved["concurrency"] == 1
    assert value.used["dispatches"] == 1
    assert value.reserved["context_bytes"] > 0
    assert value.reserved["tool_calls"] == 1
    assert value.used["context_bytes"] == 0


def test_dispatch_limit_blocks_second_ready_task() -> None:
    result = SchedulerSimulationService().run(TASK_GRAPH_PATH, ROOT, "budget-exhaustion")
    assert result.outcome == "one-running-one-budget-blocked"
    assert result.wait_kind == "stall"
    assert "task:TSK-SECOND->budget:scheduler" in result.blockers


def test_context_per_dispatch_limit_blocks_without_consuming_dispatch(tmp_path: Path) -> None:
    graph = graph_value()
    graph = replace(
        graph,
        budget=replace(graph.budget, max_context_bytes_per_dispatch=1024),
    )
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "small.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph),
        FIXED_TIME,
    )
    tick = store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    assert tick.outgoing == ()
    state = tick.state.value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].state.value == "blocked"
    ledger = store.export("budget")[-1].value
    assert isinstance(ledger, BudgetLedger)
    assert ledger.used["dispatches"] == 0


def test_rehashed_budget_blocker_must_replay_an_actual_admission_failure(
    tmp_path: Path,
) -> None:
    graph = graph_value()
    graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "forged-budget-blocker.sqlite3", ROOT, graph_artifact, FIXED_TIME
    )
    initial = store.export("events")[0]
    initial_event = initial.value
    assert isinstance(initial_event, SchedulerEvent)
    task = graph.tasks[0]
    projection = TaskProjection(
        task_id=task.task_id,
        state=TaskState.BLOCKED,
        dispatch_phase=DispatchPhase.NOT_DISPATCHED,
        outcome=TaskOutcome.NONE,
        attempt=0,
        fence=0,
        blockers=(Blocker("budget-exhausted", ()),),
    )
    forged = SchedulerEvent(
        sequence=2,
        previous_event_sha256=event_digest(initial),
        actor="scheduler",
        cause="dispatch-budget-blocked",
        graph_id=graph_artifact.artifact_id,
        task_id=task.task_id,
        candidate=graph.candidate,
        context_snapshot_id=task.context_snapshot_id,
        before_state=TaskState.READY.value,
        after_state=TaskState.BLOCKED.value,
        lease_id=None,
        message_id=None,
        result_id=None,
        approval_id=None,
        budget_deltas={},
        task_projection=projection,
        reason="budget-exhausted",
        recorded_at="2026-08-01T00:00:00Z",
    )
    forged_artifact = artifact_from_value(SchedulerArtifactType.SCHEDULER_EVENT, forged)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "INSERT INTO events(sequence, artifact_id, event_sha256, previous_sha256, "
            "artifact_json) VALUES (?, ?, ?, ?, ?)",
            (
                forged.sequence,
                forged_artifact.artifact_id,
                event_digest(forged_artifact),
                forged.previous_event_sha256,
                canonical_json_bytes(forged_artifact.to_dict()).decode("ascii"),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="no replayable admission failure"):
        store.validate_evidence()
    output = tmp_path / "forged-budget-blocker-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="no replayable admission failure"):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()


def test_dispatch_ack_and_result_transactionally_settle_reservations(tmp_path: Path) -> None:
    graph = replace(
        graph_value(),
        budget=replace(
            graph_value().budget,
            cost_status="available",
            currency="USD",
            max_microunits=100,
        ),
    )
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "settle.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph),
        FIXED_TIME,
    )
    dispatch = first_dispatch(store)
    acknowledgement = host_message(
        dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": True, "effect_observed": "none", "note": None},
    )
    store.tick(ROOT, "HST-TEST", (acknowledgement,), FIXED_TIME)
    acknowledged = store.export("budget")[-1].value
    assert isinstance(acknowledged, BudgetLedger)
    assert acknowledged.reserved["context_bytes"] == 0
    assert acknowledged.used["context_bytes"] > 0
    assert acknowledged.reserved["tool_calls"] == 1
    assert acknowledged.reserved["microunits"] == 100

    completed = result_message(dispatch, tool_calls=1, microunits=25)
    store.tick(ROOT, "HST-TEST", (completed,), FIXED_TIME)
    settled = store.export("budget")[-1].value
    assert isinstance(settled, BudgetLedger)
    assert settled.reserved["tool_calls"] == 0
    assert settled.reserved["microunits"] == 0
    assert settled.used["tool_calls"] == 1
    assert settled.used["microunits"] == 25


def test_attempt_scoped_settlement_preserves_another_tasks_reservation(
    tmp_path: Path,
) -> None:
    graph = graph_value()
    first = graph.tasks[0]
    second = replace(
        first,
        task_id="TSK-SECOND",
        dependencies=(),
        owned_paths=(),
        review_targets=(),
    )
    graph = replace(
        graph,
        tasks=(first, second),
        budget=replace(graph.budget, max_agents=2, max_concurrency=2),
    )
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "attempt-scoped.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph),
        FIXED_TIME,
    )
    tick = store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    assert len(tick.outgoing) == 2
    dispatches = {
        item.value.task_id: item  # type: ignore[union-attr]
        for item in tick.outgoing
    }
    first_dispatch_artifact = dispatches[first.task_id]
    first_dispatch_value = first_dispatch_artifact.value
    payload = first_dispatch_value.to_dict()["payload"]
    assert isinstance(payload, dict)
    reservation = payload["budget_reservation"]
    assert isinstance(reservation, dict)
    context_per_attempt = int(reservation["context_bytes"])

    acknowledgement = host_message(
        first_dispatch_artifact,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": True, "effect_observed": "none", "note": None},
    )
    store.tick(ROOT, "HST-TEST", (acknowledgement,), FIXED_TIME)
    acknowledged = store.export("budget")[-1].value
    assert isinstance(acknowledged, BudgetLedger)
    assert acknowledged.reserved["context_bytes"] == context_per_attempt
    assert acknowledged.used["context_bytes"] == context_per_attempt

    result = result_message(first_dispatch_artifact, tool_calls=1)
    store.tick(ROOT, "HST-TEST", (result,), FIXED_TIME)
    settled = store.export("budget")[-1].value
    assert isinstance(settled, BudgetLedger)
    assert settled.reserved["context_bytes"] == context_per_attempt
    assert settled.used["context_bytes"] == context_per_attempt
    assert settled.reserved["tool_calls"] == 1
    assert settled.used["tool_calls"] == 1
    state = store.status().value
    assert isinstance(state, SchedulerState)
    second_state = next(item for item in state.tasks if item.task_id == second.task_id)
    assert second_state.state.value == "running"
    store.validate()


def test_result_cannot_exceed_tool_or_unavailable_cost_budget(tmp_path: Path) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "overuse.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph_value()),
        FIXED_TIME,
    )
    dispatch = first_dispatch(store)
    overuse = result_message(dispatch, tool_calls=2, microunits=1)
    with pytest.raises(SchedulerAdapterError, match="budget reservation"):
        store.tick(ROOT, "HST-TEST", (overuse,), FIXED_TIME)
    state = store.status().value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].state.value == "running"


def test_wall_time_and_tool_call_limits_block_before_dispatch(tmp_path: Path) -> None:
    graph = graph_value()
    wall_graph = replace(
        graph,
        budget=replace(graph.budget, max_wall_time_seconds=30),
    )
    wall_store = SQLiteSchedulerStore.initialize(
        tmp_path / "wall.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, wall_graph),
        FIXED_TIME,
    )
    tick = wall_store.tick(ROOT, "HST-TEST", (), FIXED_TIME + timedelta(seconds=31))
    assert tick.outgoing == ()
    ledger = wall_store.export("budget")[-1].value
    assert isinstance(ledger, BudgetLedger)
    assert ledger.used["wall_time_seconds"] == 31
    assert "budget-exhausted" in {
        blocker.code
        for blocker in tick.state.value.tasks[0].blockers  # type: ignore[union-attr]
    }

    tool_graph = replace(
        graph,
        budget=replace(graph.budget, max_tool_calls=0),
    )
    tool_store = SQLiteSchedulerStore.initialize(
        tmp_path / "tools.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, tool_graph),
        FIXED_TIME,
    )
    assert tool_store.tick(ROOT, "HST-TEST", (), FIXED_TIME).outgoing == ()


@pytest.mark.parametrize("mutation", ["lower-used", "release-reservation"])
def test_rehashed_latest_ledger_and_matching_totals_cannot_rewrite_budget_history(
    tmp_path: Path,
    mutation: str,
) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "rewritten-latest.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph_value()),
        FIXED_TIME,
    )
    first_dispatch(store)
    original = store.export("budget")[-1]
    ledger = original.value
    assert isinstance(ledger, BudgetLedger)
    used = dict(ledger.used)
    reserved = dict(ledger.reserved)
    if mutation == "lower-used":
        resource = "dispatches"
        used[resource] = 0
    else:
        resource = "tool_calls"
        reserved[resource] = 0
    replacement = replace(ledger, used=used, reserved=reserved)
    _replace_budget_entry(store, original, replacement)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "UPDATE budget_totals SET reserved = ?, used = ? WHERE resource = ?",
            (reserved[resource], used[resource], resource),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="semantic replay"):
        store.validate_evidence()
    output = tmp_path / f"rewritten-latest-{mutation}-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="semantic replay"):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["availability", "limits"])
def test_rehashed_initial_ledger_cannot_rewrite_configured_budget_authority(
    tmp_path: Path,
    mutation: str,
) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "rewritten-initial.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph_value()),
        FIXED_TIME,
    )
    original = store.export("budget")[0]
    ledger = original.value
    assert isinstance(ledger, BudgetLedger)
    if mutation == "availability":
        availability = dict(ledger.availability)
        availability["microunits"] = "available"
        replacement = replace(ledger, availability=availability)
    else:
        replacement = replace(
            ledger,
            limits=replace(
                ledger.limits,
                max_dispatches=ledger.limits.max_dispatches + 1,
            ),
        )
    _replace_budget_entry(store, original, replacement)

    with pytest.raises(SchedulerAdapterError, match="semantic replay"):
        store.validate_evidence()
    output = tmp_path / f"rewritten-initial-{mutation}-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="semantic replay"):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()


def test_rehashed_intermediate_ledger_must_equal_event_by_event_reducer(
    tmp_path: Path,
) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "rewritten-intermediate.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph_value()),
        FIXED_TIME,
    )
    dispatch = first_dispatch(store)
    acknowledgement = host_message(
        dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": True, "effect_observed": "none", "note": None},
    )
    store.tick(ROOT, "HST-TEST", (acknowledgement,), FIXED_TIME)
    original = store.export("budget")[1]
    ledger = original.value
    assert isinstance(ledger, BudgetLedger)
    used = dict(ledger.used)
    used["dispatches"] = 0
    _replace_budget_entry(store, original, replace(ledger, used=used))

    with pytest.raises(SchedulerAdapterError, match="semantic replay"):
        store.validate_evidence()
    output = tmp_path / "rewritten-intermediate-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="semantic replay"):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["missing", "extra", "moved"])
def test_budget_snapshot_sequence_is_every_and_only_budget_changing_event(
    tmp_path: Path,
    mutation: str,
) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "snapshot-sequence.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph_value()),
        FIXED_TIME,
    )
    dispatch = first_dispatch(store)
    original = store.export("budget")[-1]
    ledger = original.value
    assert isinstance(ledger, BudgetLedger)
    heartbeat = host_message(
        dispatch,
        MessageType.HEARTBEAT,
        {"progress": "durable but budget-neutral"},
    )
    store.tick(ROOT, "HST-TEST", (heartbeat,), FIXED_TIME)
    heartbeat_event = store.export("events")[-1].value
    assert isinstance(heartbeat_event, SchedulerEvent)
    assert heartbeat_event.cause == "heartbeat"
    connection = sqlite3.connect(store.path)
    try:
        if mutation in {"missing", "moved"}:
            connection.execute(
                "DELETE FROM budget_entries WHERE event_sequence = ?",
                (ledger.event_sequence,),
            )
        if mutation in {"extra", "moved"}:
            replacement = replace(
                ledger,
                event_sequence=heartbeat_event.sequence,
            )
            artifact = artifact_from_value(SchedulerArtifactType.BUDGET_LEDGER, replacement)
            connection.execute(
                "INSERT INTO budget_entries(event_sequence, artifact_id, artifact_json) "
                "VALUES (?, ?, ?)",
                (
                    replacement.event_sequence,
                    artifact.artifact_id,
                    canonical_json_bytes(artifact.to_dict()).decode("ascii"),
                ),
            )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="snapshot sequence"):
        store.validate_evidence()
    output = tmp_path / f"snapshot-sequence-{mutation}-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="snapshot sequence"):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()


def test_rehashed_dispatch_and_ledgers_cannot_lower_rederived_reservation(
    tmp_path: Path,
) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "forged-reservation.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph_value()),
        FIXED_TIME,
    )
    dispatch_artifact = first_dispatch(store)
    dispatch = dispatch_artifact.value
    assert isinstance(dispatch, MailboxMessage)
    payload = dispatch.to_dict()["payload"]
    assert isinstance(payload, dict)
    reservation = dict(payload["budget_reservation"])
    assert reservation["tool_calls"] == 1
    reservation["tool_calls"] = 0
    payload["budget_reservation"] = reservation
    replacement_message = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(dispatch, payload=payload),
    )
    events = store.export("events")
    dispatch_event = next(
        item.value
        for item in events
        if isinstance(item.value, SchedulerEvent) and item.value.cause == "dispatch-intent"
    )
    assert isinstance(dispatch_event, SchedulerEvent)
    deltas = dict(dispatch_event.budget_deltas)
    deltas["tool_calls"] = 0
    replacement_event = replace(
        dispatch_event,
        message_id=replacement_message.artifact_id,
        budget_deltas=deltas,
    )
    latest = store.export("budget")[-1].value
    assert isinstance(latest, BudgetLedger)
    forged_reserved = dict(latest.reserved)
    forged_reserved["tool_calls"] = 0
    replacement_ledger = artifact_from_value(
        SchedulerArtifactType.BUDGET_LEDGER,
        replace(latest, reserved=forged_reserved),
    )

    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "UPDATE messages SET artifact_id = ?, artifact_json = ? WHERE artifact_id = ?",
            (
                replacement_message.artifact_id,
                canonical_json_bytes(replacement_message.to_dict()).decode("ascii"),
                dispatch_artifact.artifact_id,
            ),
        )
        _rehash_event_chain(
            connection,
            events,
            {dispatch_event.sequence: replacement_event},
        )
        connection.execute(
            "UPDATE budget_entries SET artifact_id = ?, artifact_json = ? WHERE event_sequence = ?",
            (
                replacement_ledger.artifact_id,
                canonical_json_bytes(replacement_ledger.to_dict()).decode("ascii"),
                latest.event_sequence,
            ),
        )
        connection.execute("UPDATE budget_totals SET reserved = 0 WHERE resource = 'tool_calls'")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="reservation is not deterministically"):
        store.validate_evidence()
    output = tmp_path / "forged-reservation-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="reservation is not deterministically"):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()


def test_rehashed_result_and_ledgers_cannot_exceed_original_reservation(
    tmp_path: Path,
) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "forged-result-usage.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph_value()),
        FIXED_TIME,
    )
    dispatch = first_dispatch(store)
    result_artifact = result_message(dispatch)
    store.tick(ROOT, "HST-TEST", (result_artifact,), FIXED_TIME)
    result = result_artifact.value
    assert isinstance(result, MailboxMessage)
    payload = result.to_dict()["payload"]
    assert isinstance(payload, dict)
    usage = dict(payload["budget_usage"])
    usage["tool_calls"] = 2
    payload["budget_usage"] = usage
    replacement_message = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(result, payload=payload),
    )
    events = store.export("events")
    replacements: dict[int, SchedulerEvent] = {}
    result_sequence = 0
    for loaded in events:
        event = loaded.value
        assert isinstance(event, SchedulerEvent)
        if event.message_id == result_artifact.artifact_id:
            deltas = dict(event.budget_deltas)
            deltas["tool_calls"] = 2
            replacements[event.sequence] = replace(
                event,
                message_id=replacement_message.artifact_id,
                result_id=replacement_message.artifact_id,
                budget_deltas=deltas,
            )
            result_sequence = event.sequence
        elif event.result_id == result_artifact.artifact_id:
            replacements[event.sequence] = replace(event, result_id=replacement_message.artifact_id)
    assert result_sequence > 0
    ledgers = store.export("budget")

    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "UPDATE messages SET artifact_id = ?, artifact_json = ? WHERE artifact_id = ?",
            (
                replacement_message.artifact_id,
                canonical_json_bytes(replacement_message.to_dict()).decode("ascii"),
                result_artifact.artifact_id,
            ),
        )
        _rehash_event_chain(connection, events, replacements)
        for loaded in ledgers:
            ledger = loaded.value
            assert isinstance(ledger, BudgetLedger)
            if ledger.event_sequence < result_sequence:
                continue
            forged_used = dict(ledger.used)
            forged_used["tool_calls"] = 2
            replacement = artifact_from_value(
                SchedulerArtifactType.BUDGET_LEDGER,
                replace(ledger, used=forged_used),
            )
            connection.execute(
                "UPDATE budget_entries SET artifact_id = ?, artifact_json = ? "
                "WHERE event_sequence = ?",
                (
                    replacement.artifact_id,
                    canonical_json_bytes(replacement.to_dict()).decode("ascii"),
                    ledger.event_sequence,
                ),
            )
        connection.execute("UPDATE budget_totals SET used = 2 WHERE resource = 'tool_calls'")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="exceeds its rederived"):
        store.validate_evidence()
    output = tmp_path / "forged-result-usage-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="exceeds its rederived"):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize("forged_elapsed", [30, 32])
def test_rehashed_wall_time_and_all_later_ledgers_must_equal_elapsed_time(
    tmp_path: Path,
    forged_elapsed: int,
) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "forged-wall-time.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph_value()),
        FIXED_TIME,
    )
    later = FIXED_TIME + timedelta(seconds=31)
    store.tick(ROOT, "HST-TEST", (), later)
    events = store.export("events")
    wall_event = next(
        item.value
        for item in events
        if isinstance(item.value, SchedulerEvent) and item.value.cause == "wall-time-observed"
    )
    assert isinstance(wall_event, SchedulerEvent)
    replacement_event = replace(
        wall_event,
        budget_deltas={"wall_time_seconds": forged_elapsed},
    )
    ledgers = store.export("budget")

    connection = sqlite3.connect(store.path)
    try:
        _rehash_event_chain(
            connection,
            events,
            {wall_event.sequence: replacement_event},
        )
        for loaded in ledgers:
            ledger = loaded.value
            assert isinstance(ledger, BudgetLedger)
            if ledger.event_sequence < wall_event.sequence:
                continue
            forged_used = dict(ledger.used)
            forged_used["wall_time_seconds"] = forged_elapsed
            replacement = artifact_from_value(
                SchedulerArtifactType.BUDGET_LEDGER,
                replace(ledger, used=forged_used),
            )
            connection.execute(
                "UPDATE budget_entries SET artifact_id = ?, artifact_json = ? "
                "WHERE event_sequence = ?",
                (
                    replacement.artifact_id,
                    canonical_json_bytes(replacement.to_dict()).decode("ascii"),
                    ledger.event_sequence,
                ),
            )
        connection.execute(
            "UPDATE budget_totals SET used = ? WHERE resource = 'wall_time_seconds'",
            (forged_elapsed,),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="budget semantics"):
        store.validate_evidence()
    output = tmp_path / f"forged-wall-time-{forged_elapsed}-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="budget semantics"):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["creation-drift", "missing", "extra", "moved"])
def test_wall_time_chain_rejects_unanchored_omitted_extra_or_moved_observation(
    tmp_path: Path,
    mutation: str,
) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / f"wall-chain-{mutation}.sqlite3",
        ROOT,
        artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph_value()),
        FIXED_TIME,
    )
    later = FIXED_TIME + timedelta(seconds=31)
    store.tick(ROOT, "HST-TEST", (), later)
    events = store.export("events")
    initialize = events[0]
    wall = next(
        item
        for item in events
        if isinstance(item.value, SchedulerEvent) and item.value.cause == "wall-time-observed"
    )
    wall_event = wall.value
    assert isinstance(wall_event, SchedulerEvent)
    connection = sqlite3.connect(store.path)
    try:
        if mutation == "creation-drift":
            connection.execute(
                "UPDATE metadata SET value = ? WHERE key = 'created_at'",
                ((FIXED_TIME - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),),
            )
        elif mutation == "missing":
            later_event_artifact = events[-1]
            later_event = later_event_artifact.value
            assert isinstance(later_event, SchedulerEvent)
            assert later_event.sequence == wall_event.sequence + 1
            previous = event_digest(initialize)
            rewritten = replace(
                later_event,
                sequence=wall_event.sequence,
                previous_event_sha256=previous,
            )
            rewritten_artifact = artifact_from_value(
                SchedulerArtifactType.SCHEDULER_EVENT,
                rewritten,
            )
            connection.execute(
                "DELETE FROM events WHERE sequence = ?",
                (wall_event.sequence,),
            )
            connection.execute(
                "UPDATE events SET sequence = ?, artifact_id = ?, event_sha256 = ?, "
                "previous_sha256 = ?, artifact_json = ? WHERE sequence = ?",
                (
                    rewritten.sequence,
                    rewritten_artifact.artifact_id,
                    event_digest(rewritten_artifact),
                    previous,
                    canonical_json_bytes(rewritten_artifact.to_dict()).decode("ascii"),
                    later_event.sequence,
                ),
            )
        elif mutation == "extra":
            final = events[-1]
            final_event = final.value
            assert isinstance(final_event, SchedulerEvent)
            extra_event = replace(
                wall_event,
                sequence=final_event.sequence + 1,
                previous_event_sha256=event_digest(final),
                budget_deltas={"wall_time_seconds": 1},
            )
            extra_artifact = artifact_from_value(
                SchedulerArtifactType.SCHEDULER_EVENT,
                extra_event,
            )
            connection.execute(
                "INSERT INTO events(sequence, artifact_id, event_sha256, previous_sha256, "
                "artifact_json) VALUES (?, ?, ?, ?, ?)",
                (
                    extra_event.sequence,
                    extra_artifact.artifact_id,
                    event_digest(extra_artifact),
                    extra_event.previous_event_sha256,
                    canonical_json_bytes(extra_artifact.to_dict()).decode("ascii"),
                ),
            )
        else:
            moved = replace(
                wall_event,
                recorded_at=(later + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            )
            _rehash_event_chain(connection, events, {wall_event.sequence: moved})
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        SchedulerAdapterError,
        match=r"(?i)wall-time|creation time|time moved backwards",
    ):
        store.validate_evidence()
    output = tmp_path / f"wall-chain-{mutation}-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()
