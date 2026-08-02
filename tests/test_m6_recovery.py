"""M6 evidence-preserving SQLite recovery tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import sdaqf.adapters.scheduler as scheduler_adapter
from sdaqf.adapters.scheduler import (
    SchedulerAdapterError,
    SQLiteSchedulerStore,
    recover_scheduler_database,
)
from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.scheduler_contracts import (
    EVENT_CAUSES,
    LoadedSchedulerArtifact,
    artifact_from_value,
    event_digest,
)
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.scheduler import (
    DispatchPhase,
    Lease,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerEvent,
    TaskOutcome,
    TaskState,
    WorktreeLease,
    WorktreeLeaseStatus,
)
from tests.m6_scheduler_helpers import (
    FIXED_TIME,
    ROOT,
    create_store,
    first_dispatch,
    host_message,
    result_message,
    worktree_graph,
)


def _replace_message_and_rehash_events(
    store: SQLiteSchedulerStore,
    original: LoadedSchedulerArtifact,
    replacement: LoadedSchedulerArtifact,
) -> None:
    events = store.export("events")
    replacement_value = replacement.value
    assert isinstance(replacement_value, MailboxMessage)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "UPDATE messages SET artifact_id = ?, message_type = ?, direction = ?, "
            "artifact_json = ? WHERE artifact_id = ?",
            (
                replacement.artifact_id,
                replacement_value.message_type.value,
                replacement_value.direction.value,
                canonical_json_bytes(replacement.to_dict()).decode("ascii"),
                original.artifact_id,
            ),
        )
        previous = "0" * 64
        for loaded in events:
            event = loaded.value
            assert isinstance(event, SchedulerEvent)
            rewritten = replace(
                event,
                previous_event_sha256=previous,
                message_id=(
                    replacement.artifact_id
                    if event.message_id == original.artifact_id
                    else event.message_id
                ),
                result_id=(
                    replacement.artifact_id
                    if event.result_id == original.artifact_id
                    else event.result_id
                ),
            )
            artifact = artifact_from_value(
                SchedulerArtifactType.SCHEDULER_EVENT, rewritten
            )
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
        connection.commit()
    finally:
        connection.close()


def _replace_event_and_rehash_tail(
    store: SQLiteSchedulerStore,
    replacement: SchedulerEvent,
) -> None:
    events = store.export("events")
    connection = sqlite3.connect(store.path)
    try:
        previous = "0" * 64
        for loaded in events:
            event = loaded.value
            assert isinstance(event, SchedulerEvent)
            selected = replacement if event.sequence == replacement.sequence else event
            rewritten = replace(selected, previous_event_sha256=previous)
            artifact = artifact_from_value(
                SchedulerArtifactType.SCHEDULER_EVENT, rewritten
            )
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
        connection.commit()
    finally:
        connection.close()


def _append_forged_worktree_observation(
    store: SQLiteSchedulerStore,
    request: LoadedSchedulerArtifact,
    worktree: WorktreeLease,
) -> LoadedSchedulerArtifact:
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": worktree.worktree,
            "observed_digest": worktree.observed_digest,
            "state": "created",
        },
    )
    message = observation.value
    assert isinstance(message, MailboxMessage)
    projection = next(
        event.value.task_projection
        for event in reversed(store.export("events"))
        if isinstance(event.value, SchedulerEvent)
        and event.value.task_id == message.task_id
        and event.value.task_projection is not None
    )
    assert projection is not None
    connection = sqlite3.connect(store.path)
    try:
        last_event = connection.execute(
            "SELECT sequence, event_sha256 FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        assert last_event is not None
        message_sequence = int(
            connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages").fetchone()[0]
        )
        connection.execute(
            "INSERT INTO messages(sequence, artifact_id, message_type, direction, task_id, "
            "idempotency_key, artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                message_sequence,
                observation.artifact_id,
                message.message_type.value,
                message.direction.value,
                message.task_id,
                message.idempotency_key,
                canonical_json_bytes(observation.to_dict()).decode("ascii"),
            ),
        )
        event = SchedulerEvent(
            sequence=int(last_event[0]) + 1,
            previous_event_sha256=str(last_event[1]),
            actor=message.sender,
            cause="worktree-observed",
            graph_id=message.graph_id,
            task_id=message.task_id,
            candidate=message.candidate,
            context_snapshot_id=message.context_snapshot_id,
            before_state=projection.state.value,
            after_state=projection.state.value,
            lease_id=message.lease_id,
            message_id=observation.artifact_id,
            result_id=None,
            approval_id=None,
            budget_deltas={},
            task_projection=projection,
            reason=None,
            recorded_at=message.recorded_at,
        )
        event_artifact = artifact_from_value(SchedulerArtifactType.SCHEDULER_EVENT, event)
        digest = event_digest(event_artifact)
        connection.execute(
            "INSERT INTO events(sequence, artifact_id, event_sha256, previous_sha256, "
            "artifact_json) VALUES (?, ?, ?, ?, ?)",
            (
                event.sequence,
                event_artifact.artifact_id,
                digest,
                event.previous_event_sha256,
                canonical_json_bytes(event_artifact.to_dict()).decode("ascii"),
            ),
        )
        worktree_artifact = artifact_from_value(
            SchedulerArtifactType.WORKTREE_LEASE,
            worktree,
        )
        connection.execute(
            "INSERT INTO worktree_lease_history(event_sequence, artifact_id, task_id, "
            "status, artifact_json) VALUES (?, ?, ?, ?, ?)",
            (
                event.sequence,
                worktree_artifact.artifact_id,
                worktree.task_id,
                worktree.status.value,
                canonical_json_bytes(worktree_artifact.to_dict()).decode("ascii"),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return observation


def test_recovery_preserves_state_events_and_source(tmp_path: Path) -> None:
    source = create_store(tmp_path)
    first_dispatch(source)
    before_source = source.path.read_bytes()
    before_state = source.status()
    before_events = source.export("events")
    recovered = recover_scheduler_database(source.path, tmp_path / "recovered.sqlite3", ROOT)
    assert recovered.status() == before_state
    assert recovered.export("events") == before_events
    assert source.path.read_bytes() == before_source


def test_recovery_rebuilds_logically_corrupt_mutable_projections(tmp_path: Path) -> None:
    source = create_store(tmp_path)
    first_dispatch(source)
    expected_state = source.status()
    expected_events = source.export("events")
    connection = sqlite3.connect(source.path)
    try:
        connection.execute(
            "UPDATE tasks SET state = 'blocked', blockers_json = "
            "'[{\"code\":\"projection-drift\",\"references\":[]}]'"
        )
        connection.execute(
            "UPDATE current_leases SET owner_id = 'HST-CORRUPT', expires_at = "
            "'2026-08-01T09:00:00Z'"
        )
        connection.execute(
            "UPDATE budget_totals SET reserved = 0, used = 0 WHERE resource = 'context_bytes'"
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError, match=r"projection|lease|Budget|budget"):
        source.validate()
    source.validate_evidence()
    recovered = recover_scheduler_database(
        source.path, tmp_path / "rebuilt.sqlite3", ROOT
    )
    assert recovered.status() == expected_state
    assert recovered.export("events") == expected_events


def test_recovery_detects_and_rebuilds_a_missing_current_lease(tmp_path: Path) -> None:
    source = create_store(tmp_path)
    first_dispatch(source)
    expected_state = source.status()
    expected_events = source.export("events")
    connection = sqlite3.connect(source.path)
    try:
        connection.execute("DELETE FROM current_leases")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="Current lease projection set"):
        source.validate()
    source.validate_evidence()
    recovered = recover_scheduler_database(
        source.path, tmp_path / "lease-set-rebuilt.sqlite3", ROOT
    )
    assert recovered.status() == expected_state
    assert recovered.export("events") == expected_events
    recovered.validate()


def test_recovery_detects_and_rebuilds_a_missing_current_worktree_lease(
    tmp_path: Path,
) -> None:
    graph = worktree_graph()
    graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
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
            sensitivity=Sensitivity.PUBLIC,
            provenance=(),
            causal_parent_message_ids=(),
            recorded_at="2026-08-01T00:00:00Z",
            payload={"capabilities": ["sandbox"]},
        ),
    )
    source = create_store(tmp_path, graph=graph)
    request_tick = source.tick(ROOT, "HST-TEST", (capability,), FIXED_TIME)
    request = request_tick.outgoing[0]
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "created",
        },
    )
    source.tick(ROOT, "HST-TEST", (observation,), FIXED_TIME)
    expected_state = source.status()
    expected_worktrees = source.export("worktrees")
    expected_events = source.export("events")

    connection = sqlite3.connect(source.path)
    try:
        connection.execute("DELETE FROM current_worktree_leases")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError, match="Current Worktree Lease projection set"):
        source.validate()
    source.validate_evidence()

    recovered = recover_scheduler_database(
        source.path, tmp_path / "worktree-rebuilt.sqlite3", ROOT
    )
    assert recovered.status() == expected_state
    assert recovered.export("worktrees") == expected_worktrees
    assert recovered.export("events") == expected_events
    connection = sqlite3.connect(recovered.path)
    try:
        capabilities = connection.execute(
            "SELECT value FROM metadata WHERE key = 'host_capabilities'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert capabilities == '{"HST-TEST":["sandbox"]}'
    recovered.validate()


def test_recovery_refuses_existing_output_without_overwrite(tmp_path: Path) -> None:
    source = create_store(tmp_path)
    output = tmp_path / "existing.sqlite3"
    output.write_bytes(b"preserve")
    with pytest.raises(SchedulerAdapterError, match="fresh"):
        recover_scheduler_database(source.path, output, ROOT)
    assert output.read_bytes() == b"preserve"


def test_recovery_rejects_corrupt_source_and_creates_no_output(tmp_path: Path) -> None:
    source = create_store(tmp_path)
    connection = sqlite3.connect(source.path)
    try:
        connection.execute("PRAGMA user_version = 99")
        connection.commit()
    finally:
        connection.close()
    output = tmp_path / "not-created.sqlite3"
    with pytest.raises(SchedulerAdapterError):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


def test_rehashed_forged_terminal_event_is_not_recoverable_evidence(tmp_path: Path) -> None:
    source = create_store(tmp_path)
    first_dispatch(source)
    event_artifact = source.export("events")[-1]
    event = event_artifact.value
    assert isinstance(event, SchedulerEvent)
    assert event.task_projection is not None
    forged_projection = replace(
        event.task_projection,
        state=TaskState.COMPLETED,
        dispatch_phase=DispatchPhase.ACCEPTED,
        outcome=TaskOutcome.SUCCEEDED,
    )
    forged_event = replace(
        event,
        after_state=TaskState.COMPLETED.value,
        task_projection=forged_projection,
    )
    forged_artifact = artifact_from_value(
        SchedulerArtifactType.SCHEDULER_EVENT, forged_event
    )
    forged_digest = event_digest(forged_artifact)
    encoded = canonical_json_bytes(forged_artifact.to_dict()).decode("ascii")
    connection = sqlite3.connect(source.path)
    try:
        connection.execute(
            "UPDATE events SET artifact_id = ?, event_sha256 = ?, artifact_json = ? "
            "WHERE sequence = ?",
            (forged_artifact.artifact_id, forged_digest, encoded, event.sequence),
        )
        connection.execute(
            "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ? "
            "WHERE task_id = ?",
            (
                forged_projection.state.value,
                forged_projection.dispatch_phase.value,
                forged_projection.outcome.value,
                forged_projection.task_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match=r"transition|replay"):
        source.validate()
    output = tmp_path / "forged-recovery.sqlite3"
    with pytest.raises(SchedulerAdapterError, match=r"transition|replay"):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("unknown-task", "task semantics"),
        ("context", "Context identity"),
        ("before-state", "before-state"),
        ("missing-message", "causal message is missing"),
        ("unavailable-message", "causal message is unavailable"),
        ("wrong-message-type", r"projection mutation|causal message type"),
    ],
)
def test_semantically_forged_dispatch_events_fail_closed(
    tmp_path: Path, mutation: str, error: str
) -> None:
    source = create_store(tmp_path)
    first_dispatch(source)
    event_artifact = source.export("events")[-1]
    event = event_artifact.value
    assert isinstance(event, SchedulerEvent)
    assert event.task_projection is not None
    assert event.context_snapshot_id is not None
    assert event.message_id is not None
    if mutation == "unknown-task":
        forged = replace(
            event,
            task_id="TSK-UNKNOWN",
            task_projection=replace(event.task_projection, task_id="TSK-UNKNOWN"),
        )
    elif mutation == "context":
        suffix = "0" if event.context_snapshot_id[-1] != "0" else "1"
        forged = replace(
            event,
            context_snapshot_id=event.context_snapshot_id[:-1] + suffix,
        )
    elif mutation == "before-state":
        forged = replace(event, before_state=TaskState.PLANNED.value)
    elif mutation == "missing-message":
        forged = replace(event, message_id=None)
    elif mutation == "unavailable-message":
        suffix = "0" if event.message_id[-1] != "0" else "1"
        forged = replace(event, message_id=event.message_id[:-1] + suffix)
    else:
        forged = replace(event, cause="worktree-request")
    forged_artifact = artifact_from_value(SchedulerArtifactType.SCHEDULER_EVENT, forged)
    forged_digest = event_digest(forged_artifact)
    encoded = canonical_json_bytes(forged_artifact.to_dict()).decode("ascii")
    connection = sqlite3.connect(source.path)
    try:
        connection.execute(
            "UPDATE events SET artifact_id = ?, event_sha256 = ?, artifact_json = ? "
            "WHERE sequence = ?",
            (forged_artifact.artifact_id, forged_digest, encoded, event.sequence),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError, match=error):
        source.validate_evidence()


def test_event_semantic_dispatch_is_total_and_omitted_cause_cannot_complete(
    tmp_path: Path,
) -> None:
    assert set(scheduler_adapter._EVENT_SCOPES) == set(EVENT_CAUSES)
    task_causes = {
        cause
        for cause, scope in scheduler_adapter._EVENT_SCOPES.items()
        if scope != "graph"
    }
    assert set(scheduler_adapter._EVENT_TRANSITIONS) == task_causes
    assert set(scheduler_adapter._EVENT_PROJECTION_MUTATIONS) == task_causes

    source = create_store(tmp_path)
    dispatch = first_dispatch(source)
    previous_artifact = source.export("events")[-1]
    previous = previous_artifact.value
    assert isinstance(previous, SchedulerEvent)
    assert previous.task_projection is not None
    forged_projection = replace(
        previous.task_projection,
        state=TaskState.COMPLETED,
        dispatch_phase=DispatchPhase.ACCEPTED,
        outcome=TaskOutcome.SUCCEEDED,
    )
    forged = SchedulerEvent(
        sequence=previous.sequence + 1,
        previous_event_sha256=event_digest(previous_artifact),
        actor="scheduler",
        cause="duplicate-message",
        graph_id=previous.graph_id,
        task_id=previous.task_id,
        candidate=previous.candidate,
        context_snapshot_id=previous.context_snapshot_id,
        before_state=None,
        after_state=TaskState.COMPLETED.value,
        lease_id=previous.lease_id,
        message_id=dispatch.artifact_id,
        result_id=None,
        approval_id=None,
        budget_deltas={},
        task_projection=forged_projection,
        reason="duplicate-message-retained",
        recorded_at=previous.recorded_at,
    )
    forged_artifact = artifact_from_value(SchedulerArtifactType.SCHEDULER_EVENT, forged)
    forged_digest = event_digest(forged_artifact)
    connection = sqlite3.connect(source.path)
    try:
        connection.execute(
            "INSERT INTO events(sequence, artifact_id, event_sha256, previous_sha256, "
            "artifact_json) VALUES (?, ?, ?, ?, ?)",
            (
                forged.sequence,
                forged_artifact.artifact_id,
                forged_digest,
                forged.previous_event_sha256,
                canonical_json_bytes(forged_artifact.to_dict()).decode("ascii"),
            ),
        )
        connection.execute(
            "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ? WHERE task_id = ?",
            (
                forged_projection.state.value,
                forged_projection.dispatch_phase.value,
                forged_projection.outcome.value,
                forged_projection.task_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match=r"transition|projection|audit"):
        source.validate()
    output = tmp_path / "omitted-cause-forged-recovery.sqlite3"
    with pytest.raises(SchedulerAdapterError, match=r"transition|projection|audit"):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


def test_event_replay_requires_prior_immutable_lease_authority(tmp_path: Path) -> None:
    source = create_store(tmp_path)
    dispatch = first_dispatch(source)
    acknowledgement = host_message(
        dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": True, "effect_observed": "none", "note": None},
    )
    source.tick(ROOT, "HST-TEST", (acknowledgement,), FIXED_TIME)
    connection = sqlite3.connect(source.path)
    try:
        connection.execute("DELETE FROM lease_history")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError, match="prior Lease authority"):
        source.validate_evidence()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("causal-parent", "causal parent"),
        ("sender", "Lease authority"),
        ("expiry", "Lease authority"),
    ],
)
def test_rehashed_host_events_replay_causal_and_lease_authority(
    tmp_path: Path, mutation: str, error: str
) -> None:
    source = create_store(tmp_path)
    dispatch = first_dispatch(source)
    acknowledgement = host_message(
        dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": True, "effect_observed": "none", "note": None},
    )
    source.tick(ROOT, "HST-TEST", (acknowledgement,), FIXED_TIME)
    event_artifact = source.export("events")[-1]
    event = event_artifact.value
    message = acknowledgement.value
    assert isinstance(event, SchedulerEvent)
    assert isinstance(message, MailboxMessage)
    lease = source.export("leases")[0].value
    assert isinstance(lease, Lease)
    message_artifact = acknowledgement
    if mutation == "causal-parent":
        message_artifact = artifact_from_value(
            SchedulerArtifactType.MAILBOX_MESSAGE,
            replace(message, causal_parent_message_ids=()),
        )
    elif mutation == "sender":
        message_artifact = artifact_from_value(
            SchedulerArtifactType.MAILBOX_MESSAGE,
            replace(message, sender="HST-FOREIGN"),
        )
    event_recorded_at = event.recorded_at
    if mutation == "expiry":
        event_recorded_at = lease.expires_at
    forged_event = replace(
        event,
        message_id=message_artifact.artifact_id,
        recorded_at=event_recorded_at,
    )
    forged_artifact = artifact_from_value(
        SchedulerArtifactType.SCHEDULER_EVENT, forged_event
    )
    connection = sqlite3.connect(source.path)
    try:
        if message_artifact.artifact_id != acknowledgement.artifact_id:
            connection.execute(
                "UPDATE messages SET artifact_id = ?, artifact_json = ? "
                "WHERE artifact_id = ?",
                (
                    message_artifact.artifact_id,
                    canonical_json_bytes(message_artifact.to_dict()).decode("ascii"),
                    acknowledgement.artifact_id,
                ),
            )
        connection.execute(
            "UPDATE events SET artifact_id = ?, event_sha256 = ?, artifact_json = ? "
            "WHERE sequence = ?",
            (
                forged_artifact.artifact_id,
                event_digest(forged_artifact),
                canonical_json_bytes(forged_artifact.to_dict()).decode("ascii"),
                event.sequence,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError, match=error):
        source.validate_evidence()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing-result", "evidence is incomplete"),
        ("wrong-blocked-reason", "reason is not replayable"),
    ],
)
def test_rehashed_verification_events_replay_exact_result_policy(
    tmp_path: Path, mutation: str, error: str
) -> None:
    source = create_store(tmp_path)
    dispatch = first_dispatch(source)
    source.tick(
        ROOT,
        "HST-TEST",
        (result_message(dispatch, evidence=mutation == "missing-result"),),
        FIXED_TIME,
    )
    event_artifact = source.export("events")[-1]
    event = event_artifact.value
    assert isinstance(event, SchedulerEvent)
    forged = (
        replace(event, result_id=None)
        if mutation == "missing-result"
        else replace(event, reason="forged-reason")
    )
    forged_artifact = artifact_from_value(SchedulerArtifactType.SCHEDULER_EVENT, forged)
    connection = sqlite3.connect(source.path)
    try:
        connection.execute(
            "UPDATE events SET artifact_id = ?, event_sha256 = ?, artifact_json = ? "
            "WHERE sequence = ?",
            (
                forged_artifact.artifact_id,
                event_digest(forged_artifact),
                canonical_json_bytes(forged_artifact.to_dict()).decode("ascii"),
                event.sequence,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError, match=error):
        source.validate_evidence()


@pytest.mark.parametrize(
    ("outcome", "effect"),
    [
        ("failed", "none"),
        ("unknown", "none"),
        ("succeeded", "ambiguous"),
    ],
)
def test_rehashed_non_success_result_cannot_enter_completed_verification_chain(
    tmp_path: Path,
    outcome: str,
    effect: str,
) -> None:
    source = create_store(tmp_path)
    dispatch = first_dispatch(source)
    result = result_message(dispatch)
    source.tick(ROOT, "HST-TEST", (result,), FIXED_TIME)
    message = result.value
    assert isinstance(message, MailboxMessage)
    payload = dict(message.payload)
    payload["outcome"] = outcome
    payload["effect_observed"] = effect
    replacement = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(message, payload=payload),
    )
    _replace_message_and_rehash_events(source, result, replacement)

    with pytest.raises(SchedulerAdapterError, match="successful result semantics"):
        source.validate_evidence()
    output = tmp_path / f"forged-{outcome}-{effect}.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="successful result semantics"):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "sender",
        "sensitivity",
        "provenance",
        "recorded-time",
        "extra-parent",
    ],
)
def test_rehashed_plain_scheduler_egress_requires_exact_envelope_and_no_parent(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = create_store(tmp_path)
    dispatch = first_dispatch(source)
    message = dispatch.value
    assert isinstance(message, MailboxMessage)
    if mutation == "sender":
        changed = replace(message, sender="HST-FOREIGN")
    elif mutation == "sensitivity":
        changed = replace(message, sensitivity=Sensitivity.REPOSITORY_PRIVATE)
    elif mutation == "provenance":
        changed = replace(message, provenance=())
    elif mutation == "recorded-time":
        changed = replace(message, recorded_at="2026-08-01T00:00:01Z")
    else:
        changed = replace(message, causal_parent_message_ids=(dispatch.artifact_id,))
    replacement = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, changed)
    _replace_message_and_rehash_events(source, dispatch, replacement)

    with pytest.raises(SchedulerAdapterError, match=r"egress envelope|forbidden causal parent"):
        source.validate_evidence()
    output = tmp_path / f"forged-egress-{mutation}.sqlite3"
    with pytest.raises(SchedulerAdapterError):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


def test_rehashed_cancel_egress_requires_latest_active_intent_parent(
    tmp_path: Path,
) -> None:
    source = create_store(tmp_path)
    first_dispatch(source)
    cancel = source.request_cancel(
        ROOT,
        "HST-TEST",
        "TSK-M6-DEMO",
        "Owner requested stop.",
        FIXED_TIME,
    )
    message = cancel.value
    assert isinstance(message, MailboxMessage)
    replacement = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(message, causal_parent_message_ids=()),
    )
    _replace_message_and_rehash_events(source, cancel, replacement)

    with pytest.raises(SchedulerAdapterError, match="Cancellation request"):
        source.validate_evidence()
    output = tmp_path / "forged-cancel-parent.sqlite3"
    with pytest.raises(SchedulerAdapterError):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize(
    "mutation",
    ["foreign-path", "post-dispatch-phase", "old-released-lease"],
)
def test_rehashed_worktree_observation_requires_exact_live_authority(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = create_store(tmp_path, graph=worktree_graph())
    first_request = first_dispatch(source)
    first_observation = host_message(
        first_request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": None if mutation == "foreign-path" else "D" * 64,
            "state": "ambiguous" if mutation == "foreign-path" else "created",
        },
    )
    first_tick = source.tick(ROOT, "HST-TEST", (first_observation,), FIXED_TIME)

    if mutation == "foreign-path":
        observation_event = next(
            item.value
            for item in source.export("events")
            if isinstance(item.value, SchedulerEvent)
            and item.value.cause == "worktree-observed"
        )
        assert isinstance(observation_event, SchedulerEvent)
        blocked = source.export("worktrees")[-1].value
        assert isinstance(blocked, WorktreeLease)
        message = first_observation.value
        assert isinstance(message, MailboxMessage)
        payload = dict(message.payload)
        payload["worktree"] = "worktrees/foreign"
        replacement = artifact_from_value(
            SchedulerArtifactType.MAILBOX_MESSAGE,
            replace(message, payload=payload),
        )
        _replace_message_and_rehash_events(source, first_observation, replacement)
        forged_worktree = artifact_from_value(
            SchedulerArtifactType.WORKTREE_LEASE,
            replace(blocked, worktree="worktrees/foreign"),
        )
        connection = sqlite3.connect(source.path)
        try:
            connection.execute(
                "UPDATE worktree_lease_history SET artifact_id = ?, status = ?, "
                "artifact_json = ? WHERE event_sequence = ?",
                (
                    forged_worktree.artifact_id,
                    blocked.status.value,
                    canonical_json_bytes(forged_worktree.to_dict()).decode("ascii"),
                    observation_event.sequence,
                ),
            )
            connection.commit()
        finally:
            connection.close()
    elif mutation == "post-dispatch-phase":
        assert len(first_tick.outgoing) == 1
        observed = source.export("worktrees")[-1].value
        assert isinstance(observed, WorktreeLease)
        _append_forged_worktree_observation(
            source,
            first_request,
            replace(observed, observed_digest="E" * 64),
        )
    else:
        assert len(first_tick.outgoing) == 1
        failed = result_message(first_tick.outgoing[0], outcome="failed", effect="none")
        retry_tick = source.tick(ROOT, "HST-TEST", (failed,), FIXED_TIME)
        second_request = next(
            item
            for item in retry_tick.outgoing
            if isinstance(item.value, MailboxMessage)
            and item.value.message_type is MessageType.WORKTREE_REQUEST
        )
        requested = source.export("worktrees")[-1].value
        assert isinstance(requested, WorktreeLease)
        second_request_value = second_request.value
        assert isinstance(second_request_value, MailboxMessage)
        assert requested.fence == second_request_value.fence
        forged_observed = replace(
            requested,
            observed_digest="E" * 64,
            status=WorktreeLeaseStatus.OBSERVED,
            integration_state="verified",
            recovery_guidance="Preserve the worktree and require an exact host observation.",
        )
        _append_forged_worktree_observation(source, first_request, forged_observed)

    with pytest.raises(SchedulerAdapterError, match="Worktree observation authority"):
        source.validate_evidence()
    output = tmp_path / f"forged-worktree-observation-{mutation}.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="Worktree observation authority"):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


def test_nonterminal_worktree_observation_rejects_non_live_lease_history_output(
    tmp_path: Path,
) -> None:
    source = create_store(tmp_path, graph=worktree_graph())
    request = first_dispatch(source)
    observation_time = FIXED_TIME + timedelta(seconds=30)
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "created",
        },
        clock=observation_time,
    )
    source.tick(ROOT, "HST-TEST", (observation,), observation_time)
    observation_event = next(
        item.value
        for item in source.export("events")
        if isinstance(item.value, SchedulerEvent) and item.value.cause == "worktree-observed"
    )
    current_artifact = source.export("leases")[-1]
    current = current_artifact.value
    assert isinstance(observation_event, SchedulerEvent)
    assert isinstance(current, Lease)
    heartbeat_at = observation_time.isoformat().replace("+00:00", "Z")
    expires_at = (observation_time + timedelta(seconds=current.ttl_seconds)).isoformat().replace(
        "+00:00", "Z"
    )
    forged = replace(current, heartbeat_at=heartbeat_at, expires_at=expires_at)
    forged_artifact = artifact_from_value(SchedulerArtifactType.LEASE, forged)
    connection = sqlite3.connect(source.path)
    try:
        connection.execute(
            "INSERT INTO lease_history(event_sequence, artifact_id, authority_lease_id, "
            "task_id, fence, status, artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                observation_event.sequence,
                forged_artifact.artifact_id,
                observation_event.lease_id,
                forged.task_id,
                forged.fence,
                forged.status.value,
                canonical_json_bytes(forged_artifact.to_dict()).decode("ascii"),
            ),
        )
        connection.execute(
            "UPDATE current_leases SET projection_artifact_id = ?, heartbeat_at = ?, "
            "expires_at = ?, artifact_json = ? WHERE task_id = ?",
            (
                forged_artifact.artifact_id,
                forged.heartbeat_at,
                forged.expires_at,
                canonical_json_bytes(forged_artifact.to_dict()).decode("ascii"),
                forged.task_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="unexpected Lease history"):
        source.validate_evidence()
    output = tmp_path / "forged-worktree-observation-lease-history.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="unexpected Lease history"):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["missing", "extra", "foreign", "late"])
def test_rehashed_worktree_dispatch_requires_exact_earlier_observation_parent(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = create_store(tmp_path, graph=worktree_graph())
    request = first_dispatch(source)
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "created",
        },
    )
    activated = source.tick(ROOT, "HST-TEST", (observation,), FIXED_TIME)
    dispatch = activated.outgoing[0]
    late_parent_id = observation.artifact_id
    if mutation == "late":
        late_parent = host_message(
            dispatch,
            MessageType.HEARTBEAT,
            {"progress": "later message"},
        )
        source.tick(ROOT, "HST-TEST", (late_parent,), FIXED_TIME)
        late_parent_id = late_parent.artifact_id
    message = dispatch.value
    assert isinstance(message, MailboxMessage)
    parents = {
        "missing": (),
        "extra": tuple(sorted((observation.artifact_id, request.artifact_id))),
        "foreign": (request.artifact_id,),
        "late": (late_parent_id,),
    }
    replacement = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(message, causal_parent_message_ids=parents[mutation]),
    )
    _replace_message_and_rehash_events(source, dispatch, replacement)

    with pytest.raises(SchedulerAdapterError, match="Worktree authority"):
        source.validate_evidence()
    output = tmp_path / f"forged-worktree-parent-{mutation}.sqlite3"
    with pytest.raises(SchedulerAdapterError):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["not-observed", "mismatched-owner"])
def test_rehashed_worktree_dispatch_requires_exact_prior_worktree_authority(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = create_store(tmp_path, graph=worktree_graph())
    request = first_dispatch(source)
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "created",
        },
    )
    source.tick(ROOT, "HST-TEST", (observation,), FIXED_TIME)
    history = source.export("worktrees")
    requested = history[0]
    observed = history[1]
    if mutation == "not-observed":
        replacement = requested
    else:
        value = observed.value
        assert isinstance(value, WorktreeLease)
        replacement = artifact_from_value(
            SchedulerArtifactType.WORKTREE_LEASE,
            replace(value, owner_id="HST-FOREIGN"),
        )
    replacement_value = replacement.value
    assert isinstance(replacement_value, WorktreeLease)
    connection = sqlite3.connect(source.path)
    try:
        connection.execute(
            "UPDATE worktree_lease_history SET artifact_id = ?, status = ?, "
            "artifact_json = ? WHERE event_sequence = "
            "(SELECT MAX(event_sequence) FROM worktree_lease_history)",
            (
                replacement.artifact_id,
                replacement_value.status.value,
                canonical_json_bytes(replacement.to_dict()).decode("ascii"),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="Worktree authority"):
        source.validate_evidence()
    output = tmp_path / f"forged-worktree-authority-{mutation}.sqlite3"
    with pytest.raises(SchedulerAdapterError):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["missing", "extra", "status-drift"])
def test_worktree_request_requires_one_complete_cause_derived_history_row(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = create_store(tmp_path, graph=worktree_graph())
    first_dispatch(source)
    requested_artifact = source.export("worktrees")[0]
    requested = requested_artifact.value
    assert isinstance(requested, WorktreeLease)
    request_event = next(
        item.value
        for item in source.export("events")
        if isinstance(item.value, SchedulerEvent) and item.value.cause == "worktree-request"
    )
    assert isinstance(request_event, SchedulerEvent)
    drifted = replace(
        requested,
        observed_digest="D" * 64,
        status=WorktreeLeaseStatus.OBSERVED,
        integration_state="verified",
        recovery_guidance="Preserve the worktree and require an exact host observation.",
    )
    drifted_artifact = artifact_from_value(SchedulerArtifactType.WORKTREE_LEASE, drifted)
    connection = sqlite3.connect(source.path)
    try:
        if mutation == "missing":
            connection.execute(
                "DELETE FROM worktree_lease_history WHERE event_sequence = ?",
                (request_event.sequence,),
            )
        elif mutation == "extra":
            connection.execute(
                "INSERT INTO worktree_lease_history(event_sequence, artifact_id, task_id, "
                "status, artifact_json) VALUES (?, ?, ?, ?, ?)",
                (
                    request_event.sequence,
                    drifted_artifact.artifact_id,
                    requested.task_id,
                    drifted.status.value,
                    canonical_json_bytes(drifted_artifact.to_dict()).decode("ascii"),
                ),
            )
        else:
            connection.execute(
                "UPDATE worktree_lease_history SET artifact_id = ?, status = ?, "
                "artifact_json = ? WHERE event_sequence = ?",
                (
                    drifted_artifact.artifact_id,
                    drifted.status.value,
                    canonical_json_bytes(drifted_artifact.to_dict()).decode("ascii"),
                    request_event.sequence,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="Worktree authority"):
        source.validate_evidence()
    output = tmp_path / f"forged-worktree-request-{mutation}.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="Worktree authority"):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


def test_rehashed_safe_retry_event_cannot_omit_consumed_retry_delta(
    tmp_path: Path,
) -> None:
    source = create_store(tmp_path)
    dispatch = first_dispatch(source)
    failed = result_message(dispatch, outcome="failed", effect="none")
    source.tick(ROOT, "HST-TEST", (failed,), FIXED_TIME)
    terminal = next(
        item.value
        for item in source.export("events")
        if isinstance(item.value, SchedulerEvent)
        and item.value.cause == "result-terminal"
    )
    assert isinstance(terminal, SchedulerEvent)
    assert terminal.budget_deltas["retries"] == 1
    forged_deltas = dict(terminal.budget_deltas)
    del forged_deltas["retries"]
    _replace_event_and_rehash_tail(
        source,
        replace(terminal, budget_deltas=forged_deltas),
    )

    with pytest.raises(SchedulerAdapterError, match="budget semantics"):
        source.validate_evidence()
    output = tmp_path / "forged-missing-retry-delta.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="budget semantics"):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize("accepted", [True, False])
def test_rehashed_dispatch_ack_payload_cannot_reverse_live_policy(
    tmp_path: Path,
    accepted: bool,
) -> None:
    source = create_store(tmp_path)
    dispatch = first_dispatch(source)
    acknowledgement = host_message(
        dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {
            "accepted": accepted,
            "effect_observed": "none",
            "note": None if accepted else "not started",
        },
    )
    source.tick(ROOT, "HST-TEST", (acknowledgement,), FIXED_TIME)
    value = acknowledgement.value
    assert isinstance(value, MailboxMessage)
    payload = value.to_dict()["payload"]
    assert isinstance(payload, dict)
    payload["accepted"] = not accepted
    payload["note"] = "not started" if accepted else None
    replacement = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(value, payload=payload),
    )
    _replace_message_and_rehash_events(source, acknowledgement, replacement)

    with pytest.raises(SchedulerAdapterError, match=r"exact (acceptance|rejection)"):
        source.validate_evidence()
    output = tmp_path / f"ack-policy-{accepted}-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match=r"exact (acceptance|rejection)"):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()


@pytest.mark.parametrize("kind", ["capability", "worktree"])
def test_orphan_authority_message_requires_one_primary_adoption_event(
    tmp_path: Path,
    kind: str,
) -> None:
    source = create_store(tmp_path, graph=worktree_graph() if kind == "worktree" else None)
    dispatch = first_dispatch(source)
    dispatch_value = dispatch.value
    assert isinstance(dispatch_value, MailboxMessage)
    if kind == "worktree":
        orphan = host_message(
            dispatch,
            MessageType.WORKTREE_OBSERVATION,
            {
                "worktree": "worktrees/implementation",
                "observed_digest": "D" * 64,
                "state": "created",
            },
        )
    else:
        orphan = artifact_from_value(
            SchedulerArtifactType.MAILBOX_MESSAGE,
            MailboxMessage(
                message_type=MessageType.CAPABILITY_OBSERVATION,
                direction=MessageDirection.HOST_TO_SCHEDULER,
                sender="HST-TEST",
                recipient="HST-SCHEDULER",
                graph_id=dispatch_value.graph_id,
                task_id=None,
                candidate=dispatch_value.candidate,
                context_snapshot_id=None,
                attempt=None,
                lease_id=None,
                fence=None,
                idempotency_key=None,
                sensitivity=Sensitivity.PUBLIC,
                provenance=(),
                causal_parent_message_ids=(),
                recorded_at=dispatch_value.recorded_at,
                payload={"capabilities": ["forged-capability"]},
            ),
        )
    orphan_value = orphan.value
    assert isinstance(orphan_value, MailboxMessage)
    connection = sqlite3.connect(source.path)
    try:
        next_sequence = connection.execute(
            "SELECT MAX(sequence) + 1 FROM messages"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO messages(sequence, artifact_id, message_type, direction, "
            "task_id, idempotency_key, artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                next_sequence,
                orphan.artifact_id,
                orphan_value.message_type.value,
                orphan_value.direction.value,
                orphan_value.task_id,
                orphan_value.idempotency_key,
                canonical_json_bytes(orphan.to_dict()).decode("ascii"),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SchedulerAdapterError, match="primary adoption"):
        source.validate_evidence()
    output = tmp_path / f"orphan-{kind}-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="primary adoption"):
        recover_scheduler_database(source.path, output, ROOT)
    assert not output.exists()
