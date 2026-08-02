"""Run the named offline M6-SCHEDULER-SAFETY validator."""

# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from tests.m6_scheduler_helpers import host_message, worktree_graph
from tests.schema_validation import LocalSchemaValidator

import sdaqf
from sdaqf.adapters.scheduler import (
    APPLICATION_ID,
    TABLE_NAMES,
    USER_VERSION,
    SchedulerAdapterError,
    SQLiteSchedulerStore,
    recover_scheduler_database,
)
from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    SchedulerContractError,
    artifact_from_value,
    event_digest,
    load_scheduler_artifact,
    parse_scheduler_artifact_bytes,
    scheduler_identity,
    serialize_scheduler_artifact,
)
from sdaqf.application.scheduler_simulation import (
    FIXED_START,
    HOST_ID,
    SCENARIOS,
    run_all_scenarios,
)
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.scheduler import (
    BudgetLedger,
    Lease,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerEvent,
    TaskGraph,
    WorktreeLease,
    WorktreeLeaseStatus,
)

_FILES = {
    SchedulerArtifactType.TASK_GRAPH: "task-graph.json",
    SchedulerArtifactType.SCHEDULER_STATE: "scheduler-state.json",
    SchedulerArtifactType.LEASE: "lease.json",
    SchedulerArtifactType.MAILBOX_MESSAGE: "mailbox-message.json",
    SchedulerArtifactType.SCHEDULER_EVENT: "scheduler-event.json",
    SchedulerArtifactType.BUDGET_LEDGER: "budget-ledger.json",
    SchedulerArtifactType.WORKTREE_LEASE: "worktree-lease.json",
}


def main() -> int:
    """Validate contracts, SQLite safety, recovery, and all named scenarios."""

    root = Path.cwd().resolve(strict=True)
    if root != _REPOSITORY_ROOT.resolve(strict=True):
        raise RuntimeError("M6-SCHEDULER-SAFETY must run from the repository root.")
    examples = root / "examples" / "m6-scheduler"
    validator = LocalSchemaValidator(root / "schemas")
    for artifact_type, filename in _FILES.items():
        artifact = load_scheduler_artifact(
            examples / filename,
            expected_type=artifact_type,
            root=root if artifact_type is SchedulerArtifactType.TASK_GRAPH else None,
        )
        validator.validate(filename.replace(".json", ".schema.json"), artifact.to_dict())
        reparsed = parse_scheduler_artifact_bytes(
            serialize_scheduler_artifact(artifact),
            expected_type=artifact_type,
            root=root if artifact_type is SchedulerArtifactType.TASK_GRAPH else None,
        )
        if reparsed != artifact:
            raise RuntimeError("M6 artifact round trip is not deterministic.")
    _validate_negative_contract_parity(root, validator)
    _validate_positive_contract_parity(root, validator)

    graph_artifact = load_scheduler_artifact(
        examples / "task-graph.json",
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    with tempfile.TemporaryDirectory(prefix=".sdaqf-m6-validator-", dir=root) as directory:
        temporary = Path(directory)
        state = temporary / "state.sqlite3"
        store = SQLiteSchedulerStore.initialize(
            state,
            root,
            graph_artifact,
            FIXED_START,
        )
        store.validate()
        expected_state = store.tick(root, HOST_ID, (), FIXED_START).state
        expected_events = store.export("events")
        connection = sqlite3.connect(state)
        try:
            if int(connection.execute("PRAGMA application_id").fetchone()[0]) != APPLICATION_ID:
                raise RuntimeError("SQLite application_id is invalid.")
            if int(connection.execute("PRAGMA user_version").fetchone()[0]) != USER_VERSION:
                raise RuntimeError("SQLite user_version is invalid.")
            observed_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if observed_tables != TABLE_NAMES:
                raise RuntimeError("SQLite table shape is invalid.")
        finally:
            connection.close()
        connection = sqlite3.connect(state)
        try:
            connection.execute(
                "UPDATE tasks SET state = 'blocked', blockers_json = "
                "'[{\"code\":\"corrupt-projection\",\"references\":[]}]'"
            )
            connection.commit()
        finally:
            connection.close()
        try:
            store.validate()
        except SchedulerAdapterError:
            pass
        else:
            raise RuntimeError("Logical task projection corruption was not detected.")
        recovered = temporary / "recovered.sqlite3"
        recovered_store = recover_scheduler_database(state, recovered, root)
        if (
            recovered_store.export("events") != expected_events
            or recovered_store.status() != expected_state
        ):
            raise RuntimeError("Recovery did not rebuild the exact projection from evidence.")

        concurrent = temporary / "concurrent.sqlite3"
        SQLiteSchedulerStore.initialize(
            concurrent,
            root,
            graph_artifact,
            FIXED_START,
        )
        barrier = Barrier(2)

        def claim() -> int:
            barrier.wait()
            try:
                tick = SQLiteSchedulerStore(concurrent, root).tick(root, HOST_ID, (), FIXED_START)
            except SchedulerAdapterError:
                return 0
            return len(tick.outgoing)

        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = tuple(executor.map(lambda _index: claim(), range(2)))
        if sum(claims) != 1:
            raise RuntimeError("Concurrent lease claims did not produce one owner.")
        SQLiteSchedulerStore(concurrent, root).validate()

        temporal_state = temporary / "temporal-lease.sqlite3"
        temporal_store = SQLiteSchedulerStore.initialize(
            temporal_state,
            root,
            graph_artifact,
            FIXED_START,
        )
        temporal_store.tick(root, HOST_ID, (), FIXED_START)
        connection = sqlite3.connect(temporal_state)
        try:
            lease_json = connection.execute(
                "SELECT artifact_json FROM current_leases"
            ).fetchone()[0]
            lease_artifact = json.loads(lease_json)
            lease_artifact["content"]["heartbeat_interval_seconds"] = 31
            _refresh_identity(lease_artifact)
            encoded = json.dumps(
                lease_artifact, sort_keys=True, ensure_ascii=True, separators=(",", ":")
            )
            connection.execute(
                "UPDATE current_leases SET projection_artifact_id = ?, artifact_json = ?",
                (lease_artifact["artifact_id"], encoded),
            )
            connection.execute(
                "UPDATE lease_history SET artifact_id = ?, artifact_json = ? "
                "WHERE status = 'current'",
                (lease_artifact["artifact_id"], encoded),
            )
            connection.commit()
        finally:
            connection.close()
        try:
            temporal_store.validate()
        except SchedulerAdapterError:
            pass
        else:
            raise RuntimeError("Authoritative Lease timing drift was not detected.")

        _validate_semantic_corruption_recovery(
            root,
            graph_artifact,
            temporary,
        )
        _validate_seventh_remediation_boundaries(
            root,
            graph_artifact,
            temporary,
        )
        _validate_eighth_remediation_boundary(
            root,
            temporary,
        )
        _validate_ninth_remediation_boundary(
            root,
            temporary,
        )

    first = run_all_scenarios(examples / "task-graph.json", root)
    second = run_all_scenarios(examples / "task-graph.json", root)
    if first != second or tuple(item.scenario for item in first) != SCENARIOS:
        raise RuntimeError("M6 simulator is not deterministic or complete.")

    suite = _load(root / "evals" / "m6-scheduler-suite.json")
    recorded = _load(root / "evals" / "results" / "m6-scheduler-evaluation.json")
    if suite.get("suite_id") != recorded.get("suite_id"):
        raise RuntimeError("M6 evaluation suite identity drifted.")
    expected = {
        item["case_id"]: item["expected_outcome"] for item in _object_array(suite.get("cases"))
    }
    expected_waits = {
        item["case_id"]: (item["expected_wait_kind"], item["expected_blockers"])
        for item in _object_array(suite.get("cases"))
    }
    observed = {item.scenario: item.outcome for item in first}
    observed_waits = {
        item.scenario: (item.wait_kind, list(item.blockers)) for item in first
    }
    recorded_outcomes = {
        item["case_id"]: item["observed_outcome"]
        for item in _object_array(recorded.get("cases"))
        if item.get("passed") is True
    }
    recorded_digests = {
        item["case_id"]: item["deterministic_digest"]
        for item in _object_array(recorded.get("cases"))
    }
    recorded_waits = {
        item["case_id"]: (item["observed_wait_kind"], item["observed_blockers"])
        for item in _object_array(recorded.get("cases"))
        if item.get("passed") is True
    }
    actual_digests = {item.scenario: item.deterministic_digest for item in first}
    if (
        expected != observed
        or expected_waits != observed_waits
        or recorded_outcomes != observed
        or recorded_waits != observed_waits
        or recorded_digests != actual_digests
        or len(expected) != 10
    ):
        raise RuntimeError("M6 evaluation evidence does not reproduce.")
    graph_reference = recorded.get("task_graph")
    if not isinstance(graph_reference, dict):
        raise RuntimeError("M6 evaluation Task Graph reference is invalid.")
    graph_digest = hashlib.sha256((examples / "task-graph.json").read_bytes()).hexdigest().upper()
    if graph_reference.get("sha256") != graph_digest:
        raise RuntimeError("M6 evaluation Task Graph digest drifted.")
    if _contains_aggregate(suite) or _contains_aggregate(recorded):
        raise RuntimeError("M6 evidence must not publish an aggregate score.")
    if sdaqf.__all__ != ["GateCheck", "GateResult", "ToolCapability", "ToolStatus"]:
        raise RuntimeError("M6 changed the stable top-level export surface.")

    print(
        "PASS: M6-SCHEDULER-SAFETY validated 7 artifacts, SQLite schema 1, "
        "structural contract parity, authoritative time safety, one-owner concurrency, "
        "result/egress/non-result/adoption/budget-cause semantic corruption recovery, "
        "immutable Lease policy, exact Worktree observation authority and Lease-history "
        "cardinality, causal cancellation, wall-chain safety, and 10 deterministic scenarios."
    )
    return 0


def _validate_semantic_corruption_recovery(
    root: Path,
    graph_artifact: LoadedSchedulerArtifact,
    temporary: Path,
) -> None:
    egress_store = SQLiteSchedulerStore.initialize(
        temporary / "semantic-egress.sqlite3",
        root,
        graph_artifact,
        FIXED_START,
    )
    egress = egress_store.tick(root, HOST_ID, (), FIXED_START).outgoing[0]
    egress_message = egress.value
    assert isinstance(egress_message, MailboxMessage)
    forged_egress = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(egress_message, sender="HST-FOREIGN"),
    )
    _replace_message_and_rehash_events(egress_store, egress, forged_egress)
    _assert_semantic_corruption_rejected(
        egress_store,
        temporary / "semantic-egress-recovered.sqlite3",
        root,
    )

    acknowledgement_store = SQLiteSchedulerStore.initialize(
        temporary / "semantic-acknowledgement.sqlite3",
        root,
        graph_artifact,
        FIXED_START,
    )
    acknowledgement_dispatch = acknowledgement_store.tick(
        root, HOST_ID, (), FIXED_START
    ).outgoing[0]
    acknowledgement_intent = acknowledgement_dispatch.value
    assert isinstance(acknowledgement_intent, MailboxMessage)
    acknowledgement = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.DISPATCH_ACKNOWLEDGEMENT,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender=HOST_ID,
            recipient="HST-SCHEDULER",
            graph_id=acknowledgement_intent.graph_id,
            task_id=acknowledgement_intent.task_id,
            candidate=acknowledgement_intent.candidate,
            context_snapshot_id=acknowledgement_intent.context_snapshot_id,
            attempt=acknowledgement_intent.attempt,
            lease_id=acknowledgement_intent.lease_id,
            fence=acknowledgement_intent.fence,
            idempotency_key=acknowledgement_intent.idempotency_key,
            sensitivity=acknowledgement_intent.sensitivity,
            provenance=acknowledgement_intent.provenance,
            causal_parent_message_ids=(acknowledgement_dispatch.artifact_id,),
            recorded_at=acknowledgement_intent.recorded_at,
            payload={"accepted": True, "effect_observed": "none", "note": None},
        ),
    )
    acknowledgement_store.tick(root, HOST_ID, (acknowledgement,), FIXED_START)
    acknowledgement_value = acknowledgement.value
    assert isinstance(acknowledgement_value, MailboxMessage)
    forged_acknowledgement = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(
            acknowledgement_value,
            payload={
                "accepted": False,
                "effect_observed": "none",
                "note": "not started",
            },
        ),
    )
    _replace_message_and_rehash_events(
        acknowledgement_store,
        acknowledgement,
        forged_acknowledgement,
    )
    _assert_semantic_corruption_rejected(
        acknowledgement_store,
        temporary / "semantic-acknowledgement-recovered.sqlite3",
        root,
    )

    orphan_store = SQLiteSchedulerStore.initialize(
        temporary / "semantic-orphan.sqlite3",
        root,
        graph_artifact,
        FIXED_START,
    )
    orphan_dispatch = orphan_store.tick(root, HOST_ID, (), FIXED_START).outgoing[0]
    orphan_intent = orphan_dispatch.value
    assert isinstance(orphan_intent, MailboxMessage)
    orphan = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.CAPABILITY_OBSERVATION,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender=HOST_ID,
            recipient="HST-SCHEDULER",
            graph_id=orphan_intent.graph_id,
            task_id=None,
            candidate=orphan_intent.candidate,
            context_snapshot_id=None,
            attempt=None,
            lease_id=None,
            fence=None,
            idempotency_key=None,
            sensitivity=Sensitivity.PUBLIC,
            provenance=(),
            causal_parent_message_ids=(),
            recorded_at=orphan_intent.recorded_at,
            payload={"capabilities": ["forged-capability"]},
        ),
    )
    orphan_message = orphan.value
    assert isinstance(orphan_message, MailboxMessage)
    connection = sqlite3.connect(orphan_store.path)
    try:
        sequence = connection.execute(
            "SELECT MAX(sequence) + 1 FROM messages"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO messages(sequence, artifact_id, message_type, direction, "
            "task_id, idempotency_key, artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sequence,
                orphan.artifact_id,
                orphan_message.message_type.value,
                orphan_message.direction.value,
                orphan_message.task_id,
                orphan_message.idempotency_key,
                canonical_json_bytes(orphan.to_dict()).decode("ascii"),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    _assert_semantic_corruption_rejected(
        orphan_store,
        temporary / "semantic-orphan-recovered.sqlite3",
        root,
    )

    result_store = SQLiteSchedulerStore.initialize(
        temporary / "semantic-result.sqlite3",
        root,
        graph_artifact,
        FIXED_START,
    )
    dispatch = result_store.tick(root, HOST_ID, (), FIXED_START).outgoing[0]
    dispatch_message = dispatch.value
    assert isinstance(dispatch_message, MailboxMessage)
    result_path = Path("examples/m2-orchestration/implementer-result.json")
    reference = {
        "path": result_path.as_posix(),
        "sha256": hashlib.sha256((root / result_path).read_bytes()).hexdigest().upper(),
    }
    result = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.TASK_RESULT,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender=HOST_ID,
            recipient="HST-SCHEDULER",
            graph_id=dispatch_message.graph_id,
            task_id=dispatch_message.task_id,
            candidate=dispatch_message.candidate,
            context_snapshot_id=dispatch_message.context_snapshot_id,
            attempt=dispatch_message.attempt,
            lease_id=dispatch_message.lease_id,
            fence=dispatch_message.fence,
            idempotency_key=dispatch_message.idempotency_key,
            sensitivity=dispatch_message.sensitivity,
            provenance=dispatch_message.provenance,
            causal_parent_message_ids=(dispatch.artifact_id,),
            recorded_at=dispatch_message.recorded_at,
            payload={
                "agent_result": reference,
                "outcome": "succeeded",
                "effect_observed": "none",
                "evidence_refs": [reference],
                "budget_usage": {
                    "microunits": 0,
                    "solver_calls": 0,
                    "solver_steps": 0,
                    "tool_calls": 0,
                },
            },
        ),
    )
    result_store.tick(root, HOST_ID, (result,), FIXED_START)
    result_message = result.value
    assert isinstance(result_message, MailboxMessage)
    failed_payload = dict(result_message.payload)
    failed_payload["outcome"] = "failed"
    forged_result = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(result_message, payload=failed_payload),
    )
    _replace_message_and_rehash_events(result_store, result, forged_result)
    _assert_semantic_corruption_rejected(
        result_store,
        temporary / "semantic-result-recovered.sqlite3",
        root,
    )

    budget_store = SQLiteSchedulerStore.initialize(
        temporary / "semantic-budget.sqlite3",
        root,
        graph_artifact,
        FIXED_START,
    )
    budget_dispatch = budget_store.tick(root, HOST_ID, (), FIXED_START).outgoing[0]
    budget_message = budget_dispatch.value
    assert isinstance(budget_message, MailboxMessage)
    budget_payload = budget_message.to_dict()["payload"]
    if not isinstance(budget_payload, dict):
        raise RuntimeError("Dispatch budget payload is not an object.")
    budget_reservation = budget_payload["budget_reservation"]
    if not isinstance(budget_reservation, dict) or budget_reservation["tool_calls"] != 1:
        raise RuntimeError("Dispatch budget reservation fixture drifted.")
    forged_reservation = dict(budget_reservation)
    forged_reservation["tool_calls"] = 0
    budget_payload["budget_reservation"] = forged_reservation
    forged_budget_message = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(budget_message, payload=budget_payload),
    )
    budget_events = budget_store.export("events")
    dispatch_event = next(
        item.value
        for item in budget_events
        if isinstance(item.value, SchedulerEvent)
        and item.value.cause == "dispatch-intent"
    )
    assert isinstance(dispatch_event, SchedulerEvent)
    forged_deltas = dict(dispatch_event.budget_deltas)
    forged_deltas["tool_calls"] = 0
    budget_artifact = budget_store.export("budget")[-1]
    budget = budget_artifact.value
    assert isinstance(budget, BudgetLedger)
    reserved = dict(budget.reserved)
    reserved["tool_calls"] = 0
    forged_budget = artifact_from_value(
        SchedulerArtifactType.BUDGET_LEDGER,
        replace(budget, reserved=reserved),
    )
    connection = sqlite3.connect(budget_store.path)
    try:
        connection.execute(
            "UPDATE messages SET artifact_id = ?, artifact_json = ? WHERE artifact_id = ?",
            (
                forged_budget_message.artifact_id,
                canonical_json_bytes(forged_budget_message.to_dict()).decode("ascii"),
                budget_dispatch.artifact_id,
            ),
        )
        previous = "0" * 64
        for loaded in budget_events:
            event = loaded.value
            assert isinstance(event, SchedulerEvent)
            if event.sequence == dispatch_event.sequence:
                event = replace(
                    event,
                    message_id=forged_budget_message.artifact_id,
                    budget_deltas=forged_deltas,
                )
            rewritten = replace(event, previous_event_sha256=previous)
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
        connection.execute(
            "UPDATE budget_entries SET artifact_id = ?, artifact_json = ? "
            "WHERE event_sequence = ?",
            (
                forged_budget.artifact_id,
                canonical_json_bytes(forged_budget.to_dict()).decode("ascii"),
                budget.event_sequence,
            ),
        )
        connection.execute(
            "UPDATE budget_totals SET reserved = 0 WHERE resource = 'tool_calls'"
        )
        connection.commit()
    finally:
        connection.close()
    _assert_semantic_corruption_rejected(
        budget_store,
        temporary / "semantic-budget-recovered.sqlite3",
        root,
    )


def _validate_seventh_remediation_boundaries(
    root: Path,
    graph_artifact: LoadedSchedulerArtifact,
    temporary: Path,
) -> None:
    policy_store = SQLiteSchedulerStore.initialize(
        temporary / "immutable-policy.sqlite3",
        root,
        graph_artifact,
        FIXED_START,
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
    )
    try:
        policy_store.tick(root, HOST_ID, (), FIXED_START)
    except SchedulerAdapterError:
        pass
    else:
        raise RuntimeError("A tick changed the immutable initialization Lease policy.")
    policy_tick = policy_store.tick(
        root,
        HOST_ID,
        (),
        FIXED_START,
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
    )
    policy_message = policy_tick.outgoing[0].value
    policy_lease = policy_store.export("leases")[0].value
    assert isinstance(policy_message, MailboxMessage)
    assert isinstance(policy_lease, Lease)
    if (
        policy_lease.ttl_seconds,
        policy_lease.heartbeat_interval_seconds,
        policy_message.payload["lease_ttl_seconds"],
        policy_message.payload["heartbeat_interval_seconds"],
    ) != (120, 30, 120, 30):
        raise RuntimeError("Immutable initialization Lease policy was not propagated exactly.")

    graph = graph_artifact.value
    assert isinstance(graph, TaskGraph)
    approval_task = replace(graph.tasks[0], approval_stops=("owner",))
    approval_graph = replace(graph, tasks=(approval_task,))
    approval_graph_artifact = artifact_from_value(
        SchedulerArtifactType.TASK_GRAPH,
        approval_graph,
    )
    provisional_store = SQLiteSchedulerStore.initialize(
        temporary / "provisional-policy.sqlite3",
        root,
        approval_graph_artifact,
        FIXED_START,
    )
    if provisional_store.tick(root, HOST_ID, (), FIXED_START).outgoing:
        raise RuntimeError("Approval-bound Lease unexpectedly dispatched.")
    provisional_artifact = provisional_store.export("leases")[0]
    provisional = provisional_artifact.value
    assert isinstance(provisional, Lease)
    forged_provisional = artifact_from_value(
        SchedulerArtifactType.LEASE,
        replace(
            provisional,
            ttl_seconds=61,
            expires_at=(FIXED_START + timedelta(seconds=61)).isoformat().replace("+00:00", "Z"),
        ),
    )
    _replace_lease_and_rehash_events(
        provisional_store,
        provisional_artifact,
        forged_provisional,
    )
    _assert_semantic_corruption_rejected(
        provisional_store,
        temporary / "provisional-policy-recovered.sqlite3",
        root,
    )

    worktree_artifact = artifact_from_value(
        SchedulerArtifactType.TASK_GRAPH,
        worktree_graph(),
    )
    worktree_store = SQLiteSchedulerStore.initialize(
        temporary / "worktree-cardinality.sqlite3",
        root,
        worktree_artifact,
        FIXED_START,
    )
    worktree_store.tick(root, HOST_ID, (), FIXED_START)
    requested_artifact = worktree_store.export("worktrees")[0]
    requested = requested_artifact.value
    assert isinstance(requested, WorktreeLease)
    forged_worktree = artifact_from_value(
        SchedulerArtifactType.WORKTREE_LEASE,
        replace(
            requested,
            observed_digest="D" * 64,
            status=WorktreeLeaseStatus.OBSERVED,
            integration_state="verified",
            recovery_guidance="Preserve the worktree and require an exact host observation.",
        ),
    )
    request_event = next(
        item.value
        for item in worktree_store.export("events")
        if isinstance(item.value, SchedulerEvent) and item.value.cause == "worktree-request"
    )
    assert isinstance(request_event, SchedulerEvent)
    connection = sqlite3.connect(worktree_store.path)
    try:
        connection.execute(
            "INSERT INTO worktree_lease_history(event_sequence, artifact_id, task_id, status, "
            "artifact_json) VALUES (?, ?, ?, ?, ?)",
            (
                request_event.sequence,
                forged_worktree.artifact_id,
                requested.task_id,
                WorktreeLeaseStatus.OBSERVED.value,
                canonical_json_bytes(forged_worktree.to_dict()).decode("ascii"),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    _assert_semantic_corruption_rejected(
        worktree_store,
        temporary / "worktree-cardinality-recovered.sqlite3",
        root,
    )

    cancel_store = SQLiteSchedulerStore.initialize(
        temporary / "causal-cancel.sqlite3",
        root,
        graph_artifact,
        FIXED_START,
    )
    dispatch = cancel_store.tick(root, HOST_ID, (), FIXED_START).outgoing[0]
    dispatch_message = dispatch.value
    assert isinstance(dispatch_message, MailboxMessage)
    assert dispatch_message.task_id is not None
    cancel_time = FIXED_START + timedelta(seconds=5)
    cancel = cancel_store.request_cancel(
        root,
        HOST_ID,
        dispatch_message.task_id,
        "Validator requested cancellation.",
        cancel_time,
    )
    cancel_message = cancel.value
    assert isinstance(cancel_message, MailboxMessage)
    events = tuple(item.value for item in cancel_store.export("events"))
    wall_sequence = next(
        event.sequence
        for event in events
        if isinstance(event, SchedulerEvent)
        and event.cause == "wall-time-observed"
        and event.recorded_at == cancel_message.recorded_at
    )
    cancel_sequence = next(
        event.sequence
        for event in events
        if isinstance(event, SchedulerEvent) and event.cause == "cancel-request"
    )
    if (
        cancel_message.causal_parent_message_ids != (dispatch.artifact_id,)
        or wall_sequence >= cancel_sequence
    ):
        raise RuntimeError("Cancellation did not use exact same-Lease causal wall authority.")

    wall_store = SQLiteSchedulerStore.initialize(
        temporary / "wall-anchor.sqlite3",
        root,
        graph_artifact,
        FIXED_START,
    )
    wall_store.tick(root, HOST_ID, (), FIXED_START + timedelta(seconds=31))
    connection = sqlite3.connect(wall_store.path)
    try:
        connection.execute(
            "UPDATE metadata SET value = ? WHERE key = 'created_at'",
            ((FIXED_START - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),),
        )
        connection.commit()
    finally:
        connection.close()
    _assert_semantic_corruption_rejected(
        wall_store,
        temporary / "wall-anchor-recovered.sqlite3",
        root,
    )


def _validate_eighth_remediation_boundary(
    root: Path,
    temporary: Path,
) -> None:
    graph_artifact = artifact_from_value(
        SchedulerArtifactType.TASK_GRAPH,
        worktree_graph(),
    )
    store = SQLiteSchedulerStore.initialize(
        temporary / "worktree-observation-authority.sqlite3",
        root,
        graph_artifact,
        FIXED_START,
    )
    request = store.tick(root, HOST_ID, (), FIXED_START).outgoing[0]
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": None,
            "state": "ambiguous",
        },
        sender=HOST_ID,
    )
    store.tick(root, HOST_ID, (observation,), FIXED_START)
    observation_event = next(
        item.value
        for item in store.export("events")
        if isinstance(item.value, SchedulerEvent) and item.value.cause == "worktree-observed"
    )
    blocked = store.export("worktrees")[-1].value
    message = observation.value
    assert isinstance(observation_event, SchedulerEvent)
    assert isinstance(blocked, WorktreeLease)
    assert isinstance(message, MailboxMessage)
    forged_payload = dict(message.payload)
    forged_payload["worktree"] = "worktrees/foreign"
    forged_message = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(message, payload=forged_payload),
    )
    _replace_message_and_rehash_events(store, observation, forged_message)
    forged_worktree = artifact_from_value(
        SchedulerArtifactType.WORKTREE_LEASE,
        replace(blocked, worktree="worktrees/foreign"),
    )
    connection = sqlite3.connect(store.path)
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
    _assert_semantic_corruption_rejected(
        store,
        temporary / "worktree-observation-authority-recovered.sqlite3",
        root,
    )


def _validate_ninth_remediation_boundary(
    root: Path,
    temporary: Path,
) -> None:
    graph_artifact = artifact_from_value(
        SchedulerArtifactType.TASK_GRAPH,
        worktree_graph(),
    )
    store = SQLiteSchedulerStore.initialize(
        temporary / "worktree-observation-lease-cardinality.sqlite3",
        root,
        graph_artifact,
        FIXED_START,
    )
    request = store.tick(root, HOST_ID, (), FIXED_START).outgoing[0]
    observation_time = FIXED_START + timedelta(seconds=30)
    observation = host_message(
        request,
        MessageType.WORKTREE_OBSERVATION,
        {
            "worktree": "worktrees/implementation",
            "observed_digest": "D" * 64,
            "state": "created",
        },
        clock=observation_time,
        sender=HOST_ID,
    )
    store.tick(root, HOST_ID, (observation,), observation_time)
    observation_event = next(
        item.value
        for item in store.export("events")
        if isinstance(item.value, SchedulerEvent) and item.value.cause == "worktree-observed"
    )
    current = store.export("leases")[-1].value
    assert isinstance(observation_event, SchedulerEvent)
    assert isinstance(current, Lease)
    forged = replace(
        current,
        heartbeat_at=observation_time.isoformat().replace("+00:00", "Z"),
        expires_at=(observation_time + timedelta(seconds=current.ttl_seconds))
        .isoformat()
        .replace("+00:00", "Z"),
    )
    forged_artifact = artifact_from_value(SchedulerArtifactType.LEASE, forged)
    artifact_json = canonical_json_bytes(forged_artifact.to_dict()).decode("ascii")
    connection = sqlite3.connect(store.path)
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
                artifact_json,
            ),
        )
        connection.execute(
            "UPDATE current_leases SET projection_artifact_id = ?, heartbeat_at = ?, "
            "expires_at = ?, artifact_json = ? WHERE task_id = ?",
            (
                forged_artifact.artifact_id,
                forged.heartbeat_at,
                forged.expires_at,
                artifact_json,
                forged.task_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    _assert_semantic_corruption_rejected(
        store,
        temporary / "worktree-observation-lease-cardinality-recovered.sqlite3",
        root,
    )


def _replace_lease_and_rehash_events(
    store: SQLiteSchedulerStore,
    original: LoadedSchedulerArtifact,
    replacement: LoadedSchedulerArtifact,
) -> None:
    replacement_lease = replacement.value
    assert isinstance(replacement_lease, Lease)
    events = store.export("events")
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "UPDATE lease_history SET artifact_id = ?, authority_lease_id = ?, fence = ?, "
            "status = ?, artifact_json = ? WHERE artifact_id = ?",
            (
                replacement.artifact_id,
                replacement.artifact_id,
                replacement_lease.fence,
                replacement_lease.status.value,
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
            artifact = artifact_from_value(
                SchedulerArtifactType.SCHEDULER_EVENT,
                rewritten,
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


def _replace_message_and_rehash_events(
    store: SQLiteSchedulerStore,
    original: LoadedSchedulerArtifact,
    replacement: LoadedSchedulerArtifact,
) -> None:
    replacement_message = replacement.value
    assert isinstance(replacement_message, MailboxMessage)
    events = store.export("events")
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            "UPDATE messages SET artifact_id = ?, message_type = ?, direction = ?, "
            "artifact_json = ? WHERE artifact_id = ?",
            (
                replacement.artifact_id,
                replacement_message.message_type.value,
                replacement_message.direction.value,
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
                SchedulerArtifactType.SCHEDULER_EVENT,
                rewritten,
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


def _assert_semantic_corruption_rejected(
    store: SQLiteSchedulerStore,
    output: Path,
    root: Path,
) -> None:
    try:
        store.validate_evidence()
    except SchedulerAdapterError:
        pass
    else:
        raise RuntimeError("Semantic scheduler corruption was not rejected.")
    try:
        recover_scheduler_database(store.path, output, root)
    except SchedulerAdapterError:
        pass
    else:
        raise RuntimeError("Semantic scheduler corruption was recovered.")
    if output.exists():
        raise RuntimeError("Rejected semantic corruption published a recovery output.")


def _validate_negative_contract_parity(
    root: Path, validator: LocalSchemaValidator
) -> None:
    examples = root / "examples" / "m6-scheduler"
    cases: list[tuple[str, dict[str, object]]] = []

    unknown = _load(examples / "lease.json")
    unknown["unexpected"] = True
    cases.append(("lease.schema.json", unknown))

    sensitivity = _load(examples / "task-graph.json")
    sensitivity["content"]["contexts"][0]["sensitivity"] = "internal"  # type: ignore[index]
    _refresh_identity(sensitivity)
    cases.append(("task-graph.schema.json", sensitivity))

    unsafe_path = _load(examples / "task-graph.json")
    unsafe_path["content"]["agent_registry"]["path"] = "../escape.json"  # type: ignore[index]
    _refresh_identity(unsafe_path)
    cases.append(("task-graph.schema.json", unsafe_path))

    for path_value in ("CON", "dir/trailing."):
        nonportable_path = _load(examples / "task-graph.json")
        nonportable_path["content"]["agent_registry"]["path"] = path_value  # type: ignore[index]
        _refresh_identity(nonportable_path)
        cases.append(("task-graph.schema.json", nonportable_path))

    for string_value in ("line-one\nline-two", "ghp_" + "A" * 20):
        unsafe_string = _load(examples / "task-graph.json")
        unsafe_string["content"]["tasks"][0]["required_capabilities"] = [  # type: ignore[index]
            string_value
        ]
        _refresh_identity(unsafe_string)
        cases.append(("task-graph.schema.json", unsafe_string))

    impossible_concurrency = _load(examples / "task-graph.json")
    impossible_concurrency["content"]["budget"]["max_agents"] = 1  # type: ignore[index]
    impossible_concurrency["content"]["budget"]["max_concurrency"] = 16  # type: ignore[index]
    _refresh_identity(impossible_concurrency)
    cases.append(("task-graph.schema.json", impossible_concurrency))

    missing_projection = _load(examples / "scheduler-event.json")
    missing_projection["content"]["task_projection"] = None  # type: ignore[index]
    _refresh_identity(missing_projection)
    cases.append(("scheduler-event.schema.json", missing_projection))

    mismatched_projection = _load(examples / "scheduler-event.json")
    mismatched_projection["content"]["after_state"] = "completed"  # type: ignore[index]
    _refresh_identity(mismatched_projection)
    cases.append(("scheduler-event.schema.json", mismatched_projection))

    unknown_cause = _load(examples / "scheduler-event.json")
    unknown_cause["content"]["cause"] = "arbitrary-transition"  # type: ignore[index]
    _refresh_identity(unknown_cause)
    cases.append(("scheduler-event.schema.json", unknown_cause))

    incomplete_budget = _load(examples / "budget-ledger.json")
    del incomplete_budget["content"]["reserved"]["wall_time_seconds"]  # type: ignore[index]
    _refresh_identity(incomplete_budget)
    cases.append(("budget-ledger.schema.json", incomplete_budget))

    forged_approval = _load(examples / "mailbox-message.json")
    approval_content = forged_approval["content"]
    assert isinstance(approval_content, dict)
    approval_content.update(
        {
            "message_type": "approval_decision",
            "direction": "owner_to_scheduler",
            "sender": "WRK-ATTACKER",
            "recipient": "HST-SCHEDULER",
            "payload": {
                "approval_id": "APR-M6-FORGED",
                "approval_type": "owner",
                "decision": "approved",
                "transition": "dispatch",
                "effect_digest": "D" * 64,
                "approved_at": "2026-08-01T00:00:00Z",
                "expires_at": "2026-08-01T01:00:00Z",
                "authority": "Owner",
                "supersedes_approval_id": None,
            },
        }
    )
    _refresh_identity(forged_approval)
    cases.append(("mailbox-message.schema.json", forged_approval))

    missing_usage = _load(examples / "mailbox-message.json")
    result_content = missing_usage["content"]
    assert isinstance(result_content, dict)
    result_content.update(
        {
            "message_type": "task_result",
            "direction": "host_to_scheduler",
            "sender": "HST-SIMULATOR",
            "recipient": "HST-SCHEDULER",
            "payload": {
                "agent_result": {
                    "path": "examples/m2-orchestration/implementer-result.json",
                    "sha256": "E" * 64,
                },
                "outcome": "unknown",
                "effect_observed": "ambiguous",
                "evidence_refs": [],
            },
        }
    )
    _refresh_identity(missing_usage)
    cases.append(("mailbox-message.schema.json", missing_usage))

    capability_identity = _load(examples / "mailbox-message.json")
    capability_content = capability_identity["content"]
    assert isinstance(capability_content, dict)
    capability_content.update(
        {
            "message_type": "capability_observation",
            "direction": "host_to_scheduler",
            "sender": "HST-SIMULATOR",
            "recipient": "HST-SCHEDULER",
            "context_snapshot_id": None,
            "attempt": None,
            "lease_id": None,
            "fence": None,
            "idempotency_key": None,
            "provenance": [],
            "payload": {"capabilities": ["sandbox"]},
        }
    )
    _refresh_identity(capability_identity)
    cases.append(("mailbox-message.schema.json", capability_identity))

    for unsafe_text in (
        "line-one\nline-two",
        "C:" + "/" + "Users/example/private",
        "AKIA" + "A" * 16,
        "unsupported\u202econtrol",
    ):
        heartbeat = _load(examples / "mailbox-message.json")
        heartbeat_content = heartbeat["content"]
        assert isinstance(heartbeat_content, dict)
        heartbeat_content.update(
            {
                "message_type": "heartbeat",
                "direction": "host_to_scheduler",
                "sender": "HST-SIMULATOR",
                "recipient": "HST-SCHEDULER",
                "payload": {"progress": unsafe_text},
            }
        )
        _refresh_identity(heartbeat)
        cases.append(("mailbox-message.schema.json", heartbeat))

    unsafe_event_actor = _load(examples / "scheduler-event.json")
    unsafe_event_actor["content"]["actor"] = "scheduler\nforged"  # type: ignore[index]
    _refresh_identity(unsafe_event_actor)
    cases.append(("scheduler-event.schema.json", unsafe_event_actor))

    unsafe_event_reason = _load(examples / "scheduler-event.json")
    unsafe_event_reason["content"]["reason"] = "ghp_" + "A" * 20  # type: ignore[index]
    _refresh_identity(unsafe_event_reason)
    cases.append(("scheduler-event.schema.json", unsafe_event_reason))

    unsafe_worktree_guidance = _load(examples / "worktree-lease.json")
    unsafe_worktree_guidance["content"][  # type: ignore[index]
        "recovery_guidance"
    ] = "C:" + "/" + "Users/example/private"
    _refresh_identity(unsafe_worktree_guidance)
    cases.append(("worktree-lease.schema.json", unsafe_worktree_guidance))

    unsupported_evidence = _load(examples / "task-graph.json")
    unsupported_evidence["content"]["tasks"][0]["evidence_predicate"] = [  # type: ignore[index]
        "arbitrary-evidence-text"
    ]
    _refresh_identity(unsupported_evidence)
    cases.append(("task-graph.schema.json", unsupported_evidence))

    unsupported_terminal = _load(examples / "task-graph.json")
    unsupported_terminal["content"]["tasks"][0]["terminal_predicate"] = [  # type: ignore[index]
        "arbitrary-terminal-text"
    ]
    _refresh_identity(unsupported_terminal)
    cases.append(("task-graph.schema.json", unsupported_terminal))

    for schema_name, value in cases:
        try:
            validator.validate(schema_name, value)
        except (AssertionError, ValueError):
            schema_rejected = True
        else:
            schema_rejected = False
        try:
            parse_scheduler_artifact_bytes(
                (json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
            )
        except SchedulerContractError:
            runtime_rejected = True
        else:
            runtime_rejected = False
        if not schema_rejected or not runtime_rejected:
            raise RuntimeError("M6 negative runtime/schema parity case was accepted.")


def _validate_positive_contract_parity(
    root: Path, validator: LocalSchemaValidator
) -> None:
    examples = root / "examples" / "m6-scheduler"
    cases: list[tuple[str, dict[str, object]]] = []

    structural_lease = _load(examples / "lease.json")
    structural_lease["content"]["heartbeat_interval_seconds"] = 31  # type: ignore[index]
    structural_lease["content"]["expires_at"] = "2026-08-01T00:00:00Z"  # type: ignore[index]
    _refresh_identity(structural_lease)
    cases.append(("lease.schema.json", structural_lease))

    structural_dispatch = _load(examples / "mailbox-message.json")
    structural_dispatch["content"]["payload"]["heartbeat_interval_seconds"] = 31  # type: ignore[index]
    _refresh_identity(structural_dispatch)
    cases.append(("mailbox-message.schema.json", structural_dispatch))

    structural_approval = _load(examples / "mailbox-message.json")
    approval_content = structural_approval["content"]
    assert isinstance(approval_content, dict)
    approval_content.update(
        {
            "message_type": "approval_decision",
            "direction": "owner_to_scheduler",
            "sender": "HST-OWNER",
            "recipient": "HST-SCHEDULER",
            "payload": {
                "approval_id": "APR-M6-STRUCTURAL",
                "approval_type": "owner",
                "decision": "approved",
                "transition": "dispatch",
                "effect_digest": "D" * 64,
                "approved_at": "2026-08-01T00:00:00Z",
                "expires_at": "2026-08-01T00:00:00Z",
                "authority": "Owner",
                "supersedes_approval_id": None,
            },
        }
    )
    _refresh_identity(structural_approval)
    cases.append(("mailbox-message.schema.json", structural_approval))

    for schema_name, value in cases:
        validator.validate(schema_name, value)
        parse_scheduler_artifact_bytes(
            (json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
        )


def _refresh_identity(value: dict[str, object]) -> None:
    artifact_type = SchedulerArtifactType(str(value["artifact_type"]))
    value["artifact_id"] = scheduler_identity(artifact_type, deepcopy(value["content"]))


def _load(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must be an object.")
    return value


def _object_array(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError("M6 evaluation cases must be object arrays.")
    return [item for item in value if isinstance(item, dict)]


def _contains_aggregate(value: object) -> bool:
    if isinstance(value, dict):
        if any("aggregate" in key.casefold() or key.casefold() == "score" for key in value):
            return True
        return any(_contains_aggregate(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_aggregate(item) for item in value)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
