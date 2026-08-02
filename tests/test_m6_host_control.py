"""M6 host-control boundary tests."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from sdaqf.adapters.scheduler import (
    ExclusiveSchedulerArtifactStore,
    SchedulerAdapterError,
    SQLiteSchedulerStore,
    SystemSchedulerClock,
    UnsupportedAgentHost,
    UnsupportedWorktreeHost,
    recover_scheduler_database,
)
from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    SchedulerContractError,
    artifact_from_value,
    derive_idempotency_key,
    event_digest,
    format_utc,
)
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.scheduler import (
    BudgetLedger,
    Lease,
    LeaseStatus,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerEvent,
    SchedulerState,
    SchedulerTask,
    TaskGraph,
    TaskOutcome,
    TaskState,
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


def _capability_observation(
    graph_artifact: LoadedSchedulerArtifact,
    graph: TaskGraph,
    host_id: str,
    capabilities: tuple[str, ...],
    *,
    recorded_at: str = "2026-08-01T00:00:00Z",
) -> LoadedSchedulerArtifact:
    return artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.CAPABILITY_OBSERVATION,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender=host_id,
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
            recorded_at=recorded_at,
            payload={"capabilities": list(capabilities)},
        ),
    )


def _owner_approval(
    graph_artifact: LoadedSchedulerArtifact,
    graph: TaskGraph,
    task: SchedulerTask,
    lease_artifact: LoadedSchedulerArtifact,
    lease: Lease,
    *,
    approval_id: str,
    approved_at: str,
    expires_at: str,
) -> LoadedSchedulerArtifact:
    effect_digest = hashlib.sha256(canonical_json_bytes(task.to_dict())).hexdigest().upper()
    binding = graph.contexts[0]
    return artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.APPROVAL_DECISION,
            direction=MessageDirection.OWNER_TO_SCHEDULER,
            sender="HST-OWNER",
            recipient="HST-SCHEDULER",
            graph_id=graph_artifact.artifact_id,
            task_id=task.task_id,
            candidate=graph.candidate,
            context_snapshot_id=task.context_snapshot_id,
            attempt=lease.attempt,
            lease_id=lease_artifact.artifact_id,
            fence=lease.fence,
            idempotency_key=lease.idempotency_key,
            sensitivity=binding.sensitivity,
            provenance=(binding.reference,),
            causal_parent_message_ids=(),
            recorded_at=approved_at,
            payload={
                "approval_id": approval_id,
                "approval_type": "owner",
                "decision": "approved",
                "transition": "dispatch",
                "effect_digest": effect_digest,
                "approved_at": approved_at,
                "expires_at": expires_at,
                "authority": "Owner",
                "supersedes_approval_id": None,
            },
        ),
    )


def _replace_adopted_message_and_rehash(
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
            )
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
        connection.commit()
    finally:
        connection.close()


def _replace_lease_history_and_rehash_events(
    store: SQLiteSchedulerStore,
    original: LoadedSchedulerArtifact,
    replacement: LoadedSchedulerArtifact,
) -> None:
    replacement_value = replacement.value
    assert isinstance(replacement_value, Lease)
    events = store.export("events")
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "UPDATE lease_history SET artifact_id = ?, authority_lease_id = ?, "
            "fence = ?, status = ?, artifact_json = ? WHERE artifact_id = ?",
            (
                replacement.artifact_id,
                replacement.artifact_id,
                replacement_value.fence,
                replacement_value.status.value,
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
                lease_id=(
                    replacement.artifact_id
                    if event.lease_id == original.artifact_id
                    else event.lease_id
                ),
            )
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
        connection.commit()
    finally:
        connection.close()


def test_default_host_adapters_refuse_external_effects(tmp_path: Path) -> None:
    dispatch = first_dispatch(create_store(tmp_path)).value
    assert isinstance(dispatch, MailboxMessage)
    with pytest.raises(SchedulerAdapterError, match="unsupported"):
        UnsupportedAgentHost().dispatch(dispatch)
    with pytest.raises(SchedulerAdapterError, match="unsupported"):
        UnsupportedAgentHost().cancel(dispatch)
    with pytest.raises(SchedulerAdapterError, match="unsupported"):
        UnsupportedWorktreeHost().request(dispatch)


def test_system_clock_is_utc_aware() -> None:
    observed = SystemSchedulerClock().now()
    offset = observed.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


def test_artifact_store_publishes_exclusively(tmp_path: Path) -> None:
    store = ExclusiveSchedulerArtifactStore(tmp_path)
    output = tmp_path / "export.json"
    store.publish(output, b"{}\n")
    assert output.read_bytes() == b"{}\n"
    with pytest.raises(SchedulerAdapterError):
        store.publish(output, b"changed\n")
    assert output.read_bytes() == b"{}\n"


def test_approval_bound_dispatch_reuses_persisted_identity_across_ticks(
    tmp_path: Path,
) -> None:
    graph = graph_value()
    task = replace(graph.tasks[0], approval_stops=("owner",))
    graph = replace(graph, tasks=(task,))
    graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
    store = create_store(tmp_path, graph=graph)

    waiting = store.tick(ROOT, "HST-ORIGINAL", (), FIXED_TIME)
    assert waiting.outgoing == ()
    proposal_artifact = store.export("leases")[-1]
    proposal = proposal_artifact.value
    assert isinstance(proposal, Lease)
    assert proposal.owner_id == "HST-ORIGINAL"

    later = FIXED_TIME + timedelta(seconds=10)
    effect_digest = hashlib.sha256(canonical_json_bytes(task.to_dict())).hexdigest().upper()
    binding = graph.contexts[0]
    approval = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.APPROVAL_DECISION,
            direction=MessageDirection.OWNER_TO_SCHEDULER,
            sender="HST-OWNER",
            recipient="HST-SCHEDULER",
            graph_id=graph_artifact.artifact_id,
            task_id=task.task_id,
            candidate=graph.candidate,
            context_snapshot_id=task.context_snapshot_id,
            attempt=proposal.attempt,
            lease_id=proposal_artifact.artifact_id,
            fence=proposal.fence,
            idempotency_key=proposal.idempotency_key,
            sensitivity=binding.sensitivity,
            provenance=(binding.reference,),
            causal_parent_message_ids=(),
            recorded_at=format_utc(later),
            payload={
                "approval_id": "APR-M6-STABLE-IDENTITY",
                "approval_type": "owner",
                "decision": "approved",
                "transition": "dispatch",
                "effect_digest": effect_digest,
                "approved_at": format_utc(later),
                "expires_at": format_utc(later + timedelta(hours=1)),
                "authority": "Owner",
                "supersedes_approval_id": None,
            },
        ),
    )
    approval_value = approval.value
    assert isinstance(approval_value, MailboxMessage)
    invalid_payload = approval_value.to_dict()["payload"]
    assert isinstance(invalid_payload, dict)
    invalid_payload["expires_at"] = invalid_payload["approved_at"]
    invalid = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(approval_value, payload=invalid_payload),
    )
    rejected = store.tick(ROOT, "HST-LATER", (invalid,), later)
    assert rejected.rejected_message_ids == (invalid.artifact_id,)
    assert rejected.outgoing == ()
    tick = store.tick(ROOT, "HST-LATER", (approval,), later)
    assert tick.accepted_message_ids == (approval.artifact_id,)
    assert len(tick.outgoing) == 1
    dispatch = tick.outgoing[0].value
    assert isinstance(dispatch, MailboxMessage)
    assert dispatch.recipient == proposal.owner_id
    assert dispatch.lease_id == proposal_artifact.artifact_id
    assert dispatch.attempt == proposal.attempt
    assert dispatch.fence == proposal.fence
    assert dispatch.idempotency_key == proposal.idempotency_key
    store.validate()


def test_exact_owner_approval_is_consumed_once_for_one_dispatch(tmp_path: Path) -> None:
    graph = graph_value()
    task = replace(graph.tasks[0], approval_stops=("owner",))
    graph = replace(graph, tasks=(task,))
    graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
    effect_digest = hashlib.sha256(canonical_json_bytes(task.to_dict())).hexdigest().upper()
    idempotency_key = derive_idempotency_key(
        graph_artifact.artifact_id,
        task.task_id,
        1,
        1,
        graph.candidate.to_dict(),
        task.context_snapshot_id,
        effect_digest,
    )
    lease = Lease(
        graph_id=graph_artifact.artifact_id,
        task_id=task.task_id,
        candidate=graph.candidate,
        context_snapshot_id=task.context_snapshot_id,
        attempt=1,
        owner_id="HST-TEST",
        fence=1,
        idempotency_key=idempotency_key,
        acquired_at=format_utc(FIXED_TIME),
        heartbeat_at=format_utc(FIXED_TIME),
        expires_at=format_utc(FIXED_TIME + timedelta(seconds=60)),
        ttl_seconds=60,
        heartbeat_interval_seconds=15,
        status=LeaseStatus.CURRENT,
        release_outcome=TaskOutcome.NONE,
    )
    lease_id = artifact_from_value(SchedulerArtifactType.LEASE, lease).artifact_id
    binding = graph.contexts[0]
    approval = MailboxMessage(
        message_type=MessageType.APPROVAL_DECISION,
        direction=MessageDirection.OWNER_TO_SCHEDULER,
        sender="HST-OWNER",
        recipient="HST-SCHEDULER",
        graph_id=graph_artifact.artifact_id,
        task_id=task.task_id,
        candidate=graph.candidate,
        context_snapshot_id=task.context_snapshot_id,
        attempt=1,
        lease_id=lease_id,
        fence=1,
        idempotency_key=idempotency_key,
        sensitivity=binding.sensitivity,
        provenance=(binding.reference,),
        causal_parent_message_ids=(),
        recorded_at=format_utc(FIXED_TIME),
        payload={
            "approval_id": "APR-M6-OWNER-DISPATCH",
            "approval_type": "owner",
            "decision": "approved",
            "transition": "dispatch",
            "effect_digest": effect_digest,
            "approved_at": format_utc(FIXED_TIME),
            "expires_at": format_utc(FIXED_TIME + timedelta(hours=1)),
            "authority": "Owner",
            "supersedes_approval_id": None,
        },
    )
    approval_artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, approval)
    store = create_store(tmp_path, graph=graph)
    waiting = store.tick(ROOT, "HST-TEST", (), FIXED_TIME)
    assert waiting.outgoing == ()
    assert store.export("leases")[-1].artifact_id == lease_id
    tick = store.tick(ROOT, "HST-TEST", (approval_artifact,), FIXED_TIME)
    assert tick.accepted_message_ids == (approval_artifact.artifact_id,)
    assert len(tick.outgoing) == 1

    failed = result_message(tick.outgoing[0], outcome="failed", effect="none")
    retry = store.tick(ROOT, "HST-TEST", (failed,), FIXED_TIME)
    assert retry.outgoing == ()
    state = retry.state.value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].blockers[0].code == "approval-required"


def test_rehashed_approval_cannot_forge_its_effect_authority(tmp_path: Path) -> None:
    graph = graph_value()
    task = replace(graph.tasks[0], approval_stops=("owner",))
    graph = replace(graph, tasks=(task,))
    graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
    store = create_store(tmp_path, graph=graph)
    assert store.tick(ROOT, "HST-TEST", (), FIXED_TIME).outgoing == ()
    lease_artifact = store.export("leases")[-1]
    lease = lease_artifact.value
    assert isinstance(lease, Lease)
    approval = _owner_approval(
        graph_artifact,
        graph,
        task,
        lease_artifact,
        lease,
        approval_id="APR-M6-OWNER-FORGED-AUTHORITY",
        approved_at=format_utc(FIXED_TIME),
        expires_at=format_utc(FIXED_TIME + timedelta(hours=1)),
    )
    assert len(store.tick(ROOT, "HST-TEST", (approval,), FIXED_TIME).outgoing) == 1
    value = approval.value
    assert isinstance(value, MailboxMessage)
    payload = value.to_dict()["payload"]
    assert isinstance(payload, dict)
    payload["effect_digest"] = "E" * 64
    replacement = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(value, payload=payload),
    )
    _replace_adopted_message_and_rehash(store, approval, replacement)

    with pytest.raises(SchedulerAdapterError, match="Approval authority semantics"):
        store.validate_evidence()
    output = tmp_path / "forged-approval-effect-recovered.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="Approval authority semantics"):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()


def test_dual_approvals_accept_only_exact_external_authorities(tmp_path: Path) -> None:
    graph = graph_value()
    task = replace(graph.tasks[0], approval_stops=("owner", "technical_sandbox"))
    graph = replace(graph, tasks=(task,))
    graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
    effect_digest = hashlib.sha256(canonical_json_bytes(task.to_dict())).hexdigest().upper()
    idempotency_key = derive_idempotency_key(
        graph_artifact.artifact_id,
        task.task_id,
        1,
        1,
        graph.candidate.to_dict(),
        task.context_snapshot_id,
        effect_digest,
    )
    lease = Lease(
        graph_id=graph_artifact.artifact_id,
        task_id=task.task_id,
        candidate=graph.candidate,
        context_snapshot_id=task.context_snapshot_id,
        attempt=1,
        owner_id="HST-TEST",
        fence=1,
        idempotency_key=idempotency_key,
        acquired_at=format_utc(FIXED_TIME),
        heartbeat_at=format_utc(FIXED_TIME),
        expires_at=format_utc(FIXED_TIME + timedelta(seconds=60)),
        ttl_seconds=60,
        heartbeat_interval_seconds=15,
        status=LeaseStatus.CURRENT,
        release_outcome=TaskOutcome.NONE,
    )
    lease_id = artifact_from_value(SchedulerArtifactType.LEASE, lease).artifact_id
    binding = graph.contexts[0]

    def approval(approval_type: str, sender: str, authority: str) -> LoadedSchedulerArtifact:
        value = MailboxMessage(
            message_type=MessageType.APPROVAL_DECISION,
            direction=MessageDirection.OWNER_TO_SCHEDULER,
            sender=sender,
            recipient="HST-SCHEDULER",
            graph_id=graph_artifact.artifact_id,
            task_id=task.task_id,
            candidate=graph.candidate,
            context_snapshot_id=task.context_snapshot_id,
            attempt=1,
            lease_id=lease_id,
            fence=1,
            idempotency_key=idempotency_key,
            sensitivity=binding.sensitivity,
            provenance=(binding.reference,),
            causal_parent_message_ids=(),
            recorded_at=format_utc(FIXED_TIME),
            payload={
                "approval_id": f"APR-M6-{approval_type.upper().replace('_', '-')}",
                "approval_type": approval_type,
                "decision": "approved",
                "transition": "dispatch",
                "effect_digest": effect_digest,
                "approved_at": format_utc(FIXED_TIME),
                "expires_at": format_utc(FIXED_TIME + timedelta(hours=1)),
                "authority": authority,
                "supersedes_approval_id": None,
            },
        )
        return artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, value)

    owner = approval("owner", "HST-OWNER", "Owner")
    technical = approval(
        "technical_sandbox",
        "HST-TECHNICAL-SANDBOX",
        "Technical sandbox reviewer",
    )
    store = create_store(tmp_path, graph=graph)
    assert store.tick(ROOT, "HST-TEST", (), FIXED_TIME).outgoing == ()
    waiting = store.tick(ROOT, "HST-TEST", (owner,), FIXED_TIME)
    assert waiting.accepted_message_ids == (owner.artifact_id,)
    assert waiting.outgoing == ()
    tick = store.tick(ROOT, "HST-TEST", (technical,), FIXED_TIME)
    assert tick.accepted_message_ids == (technical.artifact_id,)
    assert len(tick.outgoing) == 1
    store.validate()

    with pytest.raises(SchedulerContractError, match="Approval sender"):
        approval("owner", "WRK-ATTACKER", "Owner")


@pytest.mark.parametrize(
    ("message_type", "payload"),
    [
        (
            MessageType.DISPATCH_ACKNOWLEDGEMENT,
            {"accepted": True, "effect_observed": "none", "note": None},
        ),
        (MessageType.HEARTBEAT, {"progress": "No dispatch exists."}),
        (
            MessageType.TASK_RESULT,
            {
                "agent_result": {
                    "path": "examples/m2-orchestration/implementer-result.json",
                    "sha256": hashlib.sha256(
                        (ROOT / "examples/m2-orchestration/implementer-result.json").read_bytes()
                    )
                    .hexdigest()
                    .upper(),
                },
                "outcome": "succeeded",
                "effect_observed": "none",
                "evidence_refs": [
                    {
                        "path": "examples/m2-orchestration/implementer-result.json",
                        "sha256": hashlib.sha256(
                            (
                                ROOT / "examples/m2-orchestration/implementer-result.json"
                            ).read_bytes()
                        )
                        .hexdigest()
                        .upper(),
                    }
                ],
                "budget_usage": {
                    "microunits": 0,
                    "solver_calls": 0,
                    "solver_steps": 0,
                    "tool_calls": 0,
                },
            },
        ),
    ],
)
def test_provisional_approval_lease_rejects_traffic_without_dispatch_cause(
    tmp_path: Path,
    message_type: MessageType,
    payload: dict[str, object],
) -> None:
    graph = graph_value()
    task = replace(graph.tasks[0], approval_stops=("owner",))
    graph = replace(graph, tasks=(task,))
    store = create_store(tmp_path, graph=graph)
    assert store.tick(ROOT, "HST-TEST", (), FIXED_TIME).outgoing == ()
    lease_artifact = store.export("leases")[-1]
    lease = lease_artifact.value
    assert isinstance(lease, Lease)
    binding = graph.contexts[0]
    message = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=message_type,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender="HST-TEST",
            recipient="HST-SCHEDULER",
            graph_id=lease.graph_id,
            task_id=task.task_id,
            candidate=graph.candidate,
            context_snapshot_id=task.context_snapshot_id,
            attempt=lease.attempt,
            lease_id=lease_artifact.artifact_id,
            fence=lease.fence,
            idempotency_key=lease.idempotency_key,
            sensitivity=binding.sensitivity,
            provenance=(binding.reference,),
            causal_parent_message_ids=(),
            recorded_at=format_utc(FIXED_TIME),
            payload=payload,
        ),
    )
    tick = store.tick(ROOT, "HST-TEST", (message,), FIXED_TIME)
    assert tick.rejected_message_ids == (message.artifact_id,)
    state = tick.state.value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].dispatch_phase.value == "not_dispatched"


def test_worktree_dispatch_revalidates_approval_at_activation(tmp_path: Path) -> None:
    graph = worktree_graph()
    task = replace(graph.tasks[0], approval_stops=("owner",))
    graph = replace(graph, tasks=(task,))
    graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
    store = create_store(tmp_path, graph=graph)
    assert store.tick(ROOT, "HST-TEST", (), FIXED_TIME).outgoing == ()
    lease_artifact = store.export("leases")[-1]
    lease = lease_artifact.value
    assert isinstance(lease, Lease)
    approval = _owner_approval(
        graph_artifact,
        graph,
        task,
        lease_artifact,
        lease,
        approval_id="APR-M6-WORKTREE-FIRST",
        approved_at=format_utc(FIXED_TIME),
        expires_at=format_utc(FIXED_TIME + timedelta(seconds=10)),
    )
    requested = store.tick(ROOT, "HST-TEST", (approval,), FIXED_TIME)
    assert len(requested.outgoing) == 1
    request = requested.outgoing[0]

    later = FIXED_TIME + timedelta(seconds=20)
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "created",
        },
        clock=later,
    )
    blocked = store.tick(ROOT, "HST-TEST", (observation,), later)
    assert blocked.accepted_message_ids == (observation.artifact_id,)
    assert blocked.outgoing == ()
    blocked_state = blocked.state.value
    assert isinstance(blocked_state, SchedulerState)
    assert blocked_state.tasks[0].blockers[0].code == "approval-required"

    replacement = _owner_approval(
        graph_artifact,
        graph,
        task,
        lease_artifact,
        lease,
        approval_id="APR-M6-WORKTREE-REPLACEMENT",
        approved_at=format_utc(later),
        expires_at=format_utc(later + timedelta(hours=1)),
    )
    activated = store.tick(ROOT, "HST-TEST", (replacement,), later)
    assert activated.accepted_message_ids == (replacement.artifact_id,)
    assert len(activated.outgoing) == 1
    dispatch = activated.outgoing[0].value
    assert isinstance(dispatch, MailboxMessage)
    assert dispatch.message_type is MessageType.DISPATCH_INTENT
    assert dispatch.causal_parent_message_ids == (observation.artifact_id,)
    store.validate()


def test_capabilities_are_scoped_to_the_current_lease_owner(tmp_path: Path) -> None:
    graph = graph_value()
    task = replace(
        graph.tasks[0],
        approval_stops=("owner",),
        required_capabilities=("sandbox",),
    )
    graph = replace(graph, tasks=(task,))
    graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
    store = create_store(tmp_path, graph=graph)
    observed_a = _capability_observation(graph_artifact, graph, "HST-A", ("sandbox",))
    store.tick(ROOT, "HST-A", (observed_a,), FIXED_TIME)
    lease = store.export("leases")[-1].value
    assert isinstance(lease, Lease)
    assert lease.owner_id == "HST-A"

    removed_a = _capability_observation(graph_artifact, graph, "HST-A", ())
    store.tick(ROOT, "HST-A", (removed_a,), FIXED_TIME)
    observed_b = _capability_observation(graph_artifact, graph, "HST-B", ("sandbox",))
    tick = store.tick(ROOT, "HST-B", (observed_b,), FIXED_TIME)
    state = tick.state.value
    assert isinstance(state, SchedulerState)
    assert state.tasks[0].state.value == "blocked"
    assert state.tasks[0].blockers[0].code == "missing-capability"
    assert store.export("leases")[-1].value.owner_id == "HST-A"  # type: ignore[union-attr]


def test_cancel_reason_is_strict_at_the_generated_boundary(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    first_dispatch(store)
    with pytest.raises(SchedulerAdapterError, match="arguments"):
        store.request_cancel(ROOT, "HST-TEST", "TSK-M6-DEMO", "bad\nreason", FIXED_TIME)


@pytest.mark.parametrize(
    "mutation",
    ["owner", "idempotency-key", "ttl", "heartbeat-interval", "release-outcome"],
)
def test_provisional_lease_replay_requires_every_live_cause_field(
    tmp_path: Path,
    mutation: str,
) -> None:
    graph = graph_value()
    task = replace(graph.tasks[0], approval_stops=("owner",))
    store = create_store(tmp_path, graph=replace(graph, tasks=(task,)))
    assert store.tick(ROOT, "HST-TEST", (), FIXED_TIME).outgoing == ()
    original = store.export("leases")[-1]
    lease = original.value
    assert isinstance(lease, Lease)
    if mutation == "owner":
        changed = replace(lease, owner_id="HST-FORGED")
    elif mutation == "idempotency-key":
        changed = replace(lease, idempotency_key="IDEM-" + "A" * 64)
    elif mutation == "ttl":
        changed = replace(
            lease,
            ttl_seconds=61,
            expires_at=format_utc(FIXED_TIME + timedelta(seconds=61)),
        )
    elif mutation == "heartbeat-interval":
        changed = replace(lease, heartbeat_interval_seconds=14)
    else:
        changed = replace(lease, release_outcome=TaskOutcome.UNKNOWN)
    replacement = artifact_from_value(SchedulerArtifactType.LEASE, changed)
    _replace_lease_history_and_rehash_events(store, original, replacement)

    with pytest.raises(SchedulerAdapterError, match="Authoritative Lease"):
        store.validate_evidence()
    output = tmp_path / f"forged-provisional-{mutation}.sqlite3"
    with pytest.raises(SchedulerAdapterError, match="Authoritative Lease"):
        recover_scheduler_database(store.path, output, ROOT)
    assert not output.exists()


def test_cancel_rejects_old_attempt_when_current_lease_is_only_provisional(
    tmp_path: Path,
) -> None:
    graph = graph_value()
    task = replace(graph.tasks[0], approval_stops=("owner",))
    graph = replace(graph, tasks=(task,))
    graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
    store = create_store(tmp_path, graph=graph)
    assert store.tick(ROOT, "HST-TEST", (), FIXED_TIME).outgoing == ()
    first_lease_artifact = store.export("leases")[-1]
    first_lease = first_lease_artifact.value
    assert isinstance(first_lease, Lease)
    approval = _owner_approval(
        graph_artifact,
        graph,
        task,
        first_lease_artifact,
        first_lease,
        approval_id="APR-M6-CANCEL-FIRST",
        approved_at=format_utc(FIXED_TIME),
        expires_at=format_utc(FIXED_TIME + timedelta(hours=1)),
    )
    dispatched = store.tick(ROOT, "HST-TEST", (approval,), FIXED_TIME)
    dispatch = dispatched.outgoing[0]
    failed = result_message(dispatch, outcome="failed", effect="none")
    retry = store.tick(ROOT, "HST-TEST", (failed,), FIXED_TIME)
    retry_state = retry.state.value
    assert isinstance(retry_state, SchedulerState)
    assert retry_state.tasks[0].state is TaskState.BLOCKED
    provisional = store.export("leases")[-1].value
    assert isinstance(provisional, Lease)
    assert provisional.attempt == 2
    before_messages = store.export("messages")

    with pytest.raises(SchedulerAdapterError, match="no active host intent"):
        store.request_cancel(
            ROOT,
            "HST-TEST",
            task.task_id,
            "Do not reuse the older dispatch.",
            FIXED_TIME,
        )

    assert store.export("messages") == before_messages
    store.validate()


def test_cancellation_observes_wall_time_before_emitting_egress(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    dispatch = first_dispatch(store)
    later = FIXED_TIME + timedelta(seconds=5)
    cancel = store.request_cancel(
        ROOT,
        "HST-TEST",
        "TSK-M6-DEMO",
        "Owner requested stop.",
        later,
    )
    events = [item.value for item in store.export("events")]
    wall_index = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, SchedulerEvent)
        and event.cause == "wall-time-observed"
        and event.recorded_at == format_utc(later)
    )
    cancel_index = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, SchedulerEvent) and event.cause == "cancel-request"
    )
    assert wall_index < cancel_index
    message = cancel.value
    assert isinstance(message, MailboxMessage)
    assert message.causal_parent_message_ids == (dispatch.artifact_id,)
    ledger = store.export("budget")[-1].value
    assert isinstance(ledger, BudgetLedger)
    assert ledger.used["wall_time_seconds"] == 5
    store.validate()
