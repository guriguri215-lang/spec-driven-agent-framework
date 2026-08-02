"""M6 typed mailbox adoption and rejection tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sdaqf.application.scheduler_contracts import (
    SchedulerContractError,
    artifact_from_value,
    parse_scheduler_artifact_bytes,
)
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.scheduler import (
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
)
from tests.m6_scheduler_helpers import (
    FIXED_TIME,
    ROOT,
    create_store,
    example_payload,
    first_dispatch,
    graph_artifact,
    graph_value,
    host_message,
    refresh_identity,
    strict_bytes,
)


def test_duplicate_is_idempotent_and_distinct_periodic_heartbeats_are_accepted(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    first = host_message(dispatch, MessageType.HEARTBEAT, {"progress": "one"})
    assert store.tick(ROOT, "HST-TEST", (first,), FIXED_TIME).accepted_message_ids == (
        first.artifact_id,
    )
    duplicate = store.tick(ROOT, "HST-TEST", (first,), FIXED_TIME)
    assert duplicate.accepted_message_ids == (first.artifact_id,)
    second = host_message(dispatch, MessageType.HEARTBEAT, {"progress": "two"})
    accepted = store.tick(ROOT, "HST-TEST", (second,), FIXED_TIME)
    assert accepted.accepted_message_ids == (second.artifact_id,)
    assert len(store.inspect_mailbox(direction="host_to_scheduler")) == 2
    assert len(store.export("leases")) == 3


def test_missing_causal_parent_is_rejected(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    message = host_message(
        dispatch,
        MessageType.HEARTBEAT,
        {"progress": "orphan"},
        parents=("M6-MESSAGE-" + "A" * 64,),
    )
    tick = store.tick(ROOT, "HST-TEST", (message,), FIXED_TIME)
    assert tick.rejected_message_ids == (message.artifact_id,)


def test_direction_secret_and_absolute_payload_paths_fail_contract_validation() -> None:
    payload = example_payload("mailbox-message.json")
    payload["content"]["direction"] = "host_to_scheduler"  # type: ignore[index]
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError, match="direction"):
        parse_scheduler_artifact_bytes(strict_bytes(payload))

    payload = example_payload("mailbox-message.json")
    payload["content"]["sensitivity"] = "secret-or-prohibited"  # type: ignore[index]
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError, match="prohibited"):
        parse_scheduler_artifact_bytes(strict_bytes(payload))

    payload = example_payload("mailbox-message.json")
    payload["content"]["message_type"] = "worktree_request"  # type: ignore[index]
    payload["content"]["payload"] = {"worktree": "C:/outside", "owned_paths": []}  # type: ignore[index]
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


def test_capability_observation_unblocks_matching_task(tmp_path: Path) -> None:
    graph = graph_value()
    graph = replace(
        graph,
        tasks=(replace(graph.tasks[0], required_capabilities=("sandbox",)),),
    )
    store = create_store(tmp_path, graph=graph)
    graph_id = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph).artifact_id
    message = MailboxMessage(
        message_type=MessageType.CAPABILITY_OBSERVATION,
        direction=MessageDirection.HOST_TO_SCHEDULER,
        sender="HST-TEST",
        recipient="HST-SCHEDULER",
        graph_id=graph_id,
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
    )
    artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, message)
    tick = store.tick(ROOT, "HST-TEST", (artifact,), FIXED_TIME)
    assert tick.accepted_message_ids == (artifact.artifact_id,)
    assert len(tick.outgoing) == 1


def test_mailbox_filters_are_bounded_and_validate_direction(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    first_dispatch(store)
    assert len(store.inspect_mailbox(task_id="TSK-M6-DEMO")) == 1
    assert len(store.inspect_mailbox(direction="scheduler_to_host")) == 1
    with pytest.raises(SchedulerContractError):
        store.inspect_mailbox(direction="sideways")


def test_foreign_graph_unknown_task_and_context_mismatch_are_rejected(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    base = host_message(dispatch, MessageType.HEARTBEAT, {"progress": "bounded"}).value
    assert isinstance(base, MailboxMessage)
    messages = (
        replace(base, graph_id="M6-TASK-GRAPH-" + "A" * 64),
        replace(base, task_id="TSK-UNKNOWN"),
        replace(base, context_snapshot_id="CTX-SNAPSHOT-" + "B" * 64),
    )
    for index, message in enumerate(messages):
        artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, message)
        tick = store.tick(ROOT, "HST-TEST", (artifact,), FIXED_TIME)
        assert tick.rejected_message_ids == (artifact.artifact_id,), index


def test_foreign_capability_host_and_bad_approval_recipient_are_rejected(
    tmp_path: Path,
) -> None:
    store = create_store(tmp_path)
    graph = graph_value()
    graph_id = graph_artifact().artifact_id
    capability = MailboxMessage(
        message_type=MessageType.CAPABILITY_OBSERVATION,
        direction=MessageDirection.HOST_TO_SCHEDULER,
        sender="HST-FOREIGN",
        recipient="HST-SCHEDULER",
        graph_id=graph_id,
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
        payload={"capabilities": []},
    )
    artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, capability)
    tick = store.tick(ROOT, "HST-TEST", (artifact,), FIXED_TIME)
    assert tick.rejected_message_ids == (artifact.artifact_id,)

    dispatch = tick.outgoing[0]
    dispatch_value = dispatch.value
    assert isinstance(dispatch_value, MailboxMessage)
    approval = replace(
        dispatch_value,
        message_type=MessageType.APPROVAL_DECISION,
        direction=MessageDirection.OWNER_TO_SCHEDULER,
        sender="HST-OWNER",
        recipient="HST-WRONG",
        causal_parent_message_ids=(dispatch.artifact_id,),
        payload={
            "approval_id": "APR-M6-BAD-RECIPIENT",
            "approval_type": "owner",
            "decision": "approved",
            "transition": "dispatch",
            "effect_digest": dispatch_value.payload["effect_digest"],
            "approved_at": "2026-08-01T00:00:00Z",
            "expires_at": "2026-08-01T01:00:00Z",
            "authority": "Owner",
            "supersedes_approval_id": None,
        },
    )
    approval_artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, approval)
    tick = store.tick(ROOT, "HST-TEST", (approval_artifact,), FIXED_TIME)
    assert tick.rejected_message_ids == (approval_artifact.artifact_id,)


def test_context_sensitivity_drift_is_revalidated_before_dispatch(tmp_path: Path) -> None:
    graph = graph_value()
    private_binding = replace(graph.contexts[0], sensitivity=Sensitivity.REPOSITORY_PRIVATE)
    graph = replace(graph, contexts=(private_binding,))
    store = create_store(tmp_path, graph=graph)
    with pytest.raises(SchedulerContractError, match="sensitivity"):
        first_dispatch(store)
