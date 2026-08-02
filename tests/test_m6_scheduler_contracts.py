"""Strict M6 scheduler artifact contract tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    SchedulerContractError,
    artifact_from_value,
    load_scheduler_artifact,
    parse_scheduler_artifact_bytes,
    serialize_scheduler_artifact,
)
from sdaqf.domain.scheduler import (
    BudgetLedger,
    MailboxMessage,
    SchedulerArtifactType,
    SchedulerEvent,
)
from tests.m6_scheduler_helpers import ROOT, example_payload, refresh_identity, strict_bytes

EXAMPLES = {
    "task-graph.json": SchedulerArtifactType.TASK_GRAPH,
    "scheduler-state.json": SchedulerArtifactType.SCHEDULER_STATE,
    "lease.json": SchedulerArtifactType.LEASE,
    "mailbox-message.json": SchedulerArtifactType.MAILBOX_MESSAGE,
    "scheduler-event.json": SchedulerArtifactType.SCHEDULER_EVENT,
    "budget-ledger.json": SchedulerArtifactType.BUDGET_LEDGER,
    "worktree-lease.json": SchedulerArtifactType.WORKTREE_LEASE,
}


def test_content_addressed_mapping_values_are_deeply_immutable() -> None:
    mailbox_artifact = load_scheduler_artifact(
        ROOT / "examples" / "m6-scheduler" / "mailbox-message.json"
    )
    mailbox = mailbox_artifact.value
    assert isinstance(mailbox, MailboxMessage)
    payload = mailbox.to_dict()["payload"]
    assert isinstance(payload, dict)
    copied = replace(mailbox, payload=payload)
    artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, copied)
    reservation = payload["budget_reservation"]
    assert isinstance(reservation, dict)
    reservation["tool_calls"] = 999
    required_tools = payload["required_tools"]
    assert isinstance(required_tools, list)
    required_tools.append("forged-tool")
    assert artifact.value.to_dict()["payload"]["budget_reservation"]["tool_calls"] == 1  # type: ignore[index]
    with pytest.raises(TypeError):
        copied.payload["effect_digest"] = "A" * 64  # type: ignore[index]

    ledger_artifact = load_scheduler_artifact(
        ROOT / "examples" / "m6-scheduler" / "budget-ledger.json"
    )
    ledger = ledger_artifact.value
    assert isinstance(ledger, BudgetLedger)
    reserved = dict(ledger.reserved)
    copied_ledger = replace(ledger, reserved=reserved)
    reserved["concurrency"] = 99
    assert copied_ledger.reserved["concurrency"] == 1
    with pytest.raises(TypeError):
        copied_ledger.reserved["concurrency"] = 2  # type: ignore[index]

    event_artifact = load_scheduler_artifact(
        ROOT / "examples" / "m6-scheduler" / "scheduler-event.json"
    )
    event = event_artifact.value
    assert isinstance(event, SchedulerEvent)
    deltas = dict(event.budget_deltas)
    copied_event = replace(event, budget_deltas=deltas)
    deltas["concurrency"] = 100
    assert copied_event.budget_deltas["concurrency"] == 1


def test_generated_artifacts_are_reparsed_before_identity_is_returned() -> None:
    artifact = load_scheduler_artifact(
        ROOT / "examples" / "m6-scheduler" / "mailbox-message.json"
    )
    message = artifact.value
    assert isinstance(message, MailboxMessage)
    with pytest.raises(SchedulerContractError, match="sender"):
        artifact_from_value(
            SchedulerArtifactType.MAILBOX_MESSAGE,
            replace(message, sender="not-a-host"),
        )


@pytest.mark.parametrize(("name", "artifact_type"), EXAMPLES.items())
def test_public_examples_round_trip_exactly(
    name: str, artifact_type: SchedulerArtifactType
) -> None:
    path = ROOT / "examples" / "m6-scheduler" / name
    artifact = load_scheduler_artifact(
        path,
        expected_type=artifact_type,
        root=ROOT if artifact_type is SchedulerArtifactType.TASK_GRAPH else None,
    )
    assert artifact.artifact_id.startswith("M6-")
    reparsed = parse_scheduler_artifact_bytes(
        serialize_scheduler_artifact(artifact),
        expected_type=artifact_type,
        root=ROOT if artifact_type is SchedulerArtifactType.TASK_GRAPH else None,
    )
    assert reparsed == artifact


@pytest.mark.parametrize(
    "content",
    [
        b'{"schema_version":"1.0","schema_version":"1.0"}',
        b'{"schema_version":"1.0","artifact_type":NaN}',
        b"[]",
        b"\xff",
    ],
)
def test_strict_json_rejects_duplicate_nonfinite_nonobject_and_nonutf8(
    content: bytes,
) -> None:
    with pytest.raises(SchedulerContractError):
        parse_scheduler_artifact_bytes(content)


def test_envelope_unknown_field_and_identity_tampering_fail_closed() -> None:
    payload = example_payload("lease.json")
    payload["unexpected"] = True
    with pytest.raises(SchedulerContractError):
        parse_scheduler_artifact_bytes(strict_bytes(payload))

    payload = example_payload("lease.json")
    payload["content"]["fence"] = 2  # type: ignore[index]
    with pytest.raises(SchedulerContractError, match="identity"):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


def test_expected_type_and_size_limits_are_enforced(tmp_path: Path) -> None:
    path = ROOT / "examples" / "m6-scheduler" / "lease.json"
    with pytest.raises(SchedulerContractError, match="unexpected"):
        load_scheduler_artifact(
            path,
            expected_type=SchedulerArtifactType.MAILBOX_MESSAGE,
        )

    oversized = tmp_path / "message.json"
    oversized.write_bytes(b" " * 65_537)
    with pytest.raises(SchedulerContractError):
        load_scheduler_artifact(
            oversized,
            expected_type=SchedulerArtifactType.MAILBOX_MESSAGE,
        )


def test_valid_content_change_requires_refreshed_identity() -> None:
    payload = example_payload("lease.json")
    payload["content"]["owner_id"] = "HST-ALTERNATE"  # type: ignore[index]
    refresh_identity(payload)
    artifact = parse_scheduler_artifact_bytes(strict_bytes(payload))
    assert artifact.value.to_dict()["owner_id"] == "HST-ALTERNATE"


def test_float_is_never_accepted_as_an_integer() -> None:
    payload = example_payload("budget-ledger.json")
    payload["content"]["event_sequence"] = 1.0  # type: ignore[index]
    with pytest.raises(SchedulerContractError):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


@pytest.mark.parametrize(
    ("message_type", "direction", "payload_value"),
    [
        (
            "dispatch_acknowledgement",
            "host_to_scheduler",
            {"accepted": True, "effect_observed": "none", "note": None},
        ),
        ("heartbeat", "host_to_scheduler", {"progress": "bounded progress"}),
        (
            "task_result",
            "host_to_scheduler",
            {
                "agent_result": {
                    "path": "examples/m2-orchestration/implementer-result.json",
                    "sha256": "E" * 64,
                },
                "outcome": "unknown",
                    "effect_observed": "ambiguous",
                    "evidence_refs": [],
                    "budget_usage": {
                        "microunits": 0,
                        "solver_calls": 0,
                        "solver_steps": 0,
                        "tool_calls": 0,
                    },
                },
        ),
        ("cancel_request", "scheduler_to_host", {"reason": "Owner requested stop."}),
        (
            "cancel_acknowledgement",
            "host_to_scheduler",
            {"cancelled": True, "effect_observed": "none"},
        ),
        (
            "worktree_request",
            "scheduler_to_host",
            {"worktree": "worktrees/implementation", "owned_paths": ["src/sdaqf"]},
        ),
        (
            "worktree_observation",
            "host_to_scheduler",
            {
                "worktree": "worktrees/implementation",
                "observed_digest": None,
                "state": "created",
            },
        ),
        (
            "approval_decision",
            "owner_to_scheduler",
            {
                "approval_id": "APR-M6-TEST",
                "approval_type": "owner",
                "decision": "approved",
                "transition": "dispatch",
                "effect_digest": "D" * 64,
                "approved_at": "2026-08-01T00:00:00Z",
                "expires_at": "2026-08-01T01:00:00Z",
                "authority": "Owner",
                "supersedes_approval_id": None,
            },
        ),
        (
            "capability_observation",
            "host_to_scheduler",
            {"capabilities": ["sandbox"]},
        ),
    ],
)
def test_all_typed_mailbox_payload_variants_are_exact(
    message_type: str,
    direction: str,
    payload_value: dict[str, object],
) -> None:
    payload = example_payload("mailbox-message.json")
    content = payload["content"]
    assert isinstance(content, dict)
    content["message_type"] = message_type
    content["direction"] = direction
    content["sender"] = (
        "HST-OWNER"
        if direction == "owner_to_scheduler"
        else ("HST-SCHEDULER" if direction == "scheduler_to_host" else "HST-SIMULATOR")
    )
    content["recipient"] = "HST-SIMULATOR" if direction == "scheduler_to_host" else "HST-SCHEDULER"
    content["payload"] = payload_value
    if message_type == "capability_observation":
        for field in (
            "task_id",
            "context_snapshot_id",
            "attempt",
            "lease_id",
            "fence",
            "idempotency_key",
        ):
            content[field] = None
        content["provenance"] = []
    refresh_identity(payload)
    artifact = parse_scheduler_artifact_bytes(strict_bytes(payload))
    assert artifact.value.to_dict()["message_type"] == message_type


def test_scheduler_egress_direction_cannot_be_rehashed_as_host_ingress() -> None:
    payload = example_payload("mailbox-message.json")
    content = payload["content"]
    assert isinstance(content, dict)
    content["direction"] = "host_to_scheduler"
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError, match="direction"):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", "TSK-M6-DEMO"),
        (
            "context_snapshot_id",
            "CTX-SNAPSHOT-60806B57F8C2C1B3E8AA059428C0FAD2D1629DD06B4E3A402F476497E4038A2C",
        ),
        ("attempt", 1),
        (
            "lease_id",
            "M6-LEASE-3D0DEA45CDE6A5DCB4916C25F2868E20B91E57E21D44D1FE8A42977E3A10B62D",
        ),
        ("fence", 1),
        (
            "idempotency_key",
            "IDEM-051E895E82EB2C77D3C43F45B43E98FD40CB0BFF708B4F389A71736D8BA7DEBF",
        ),
    ],
)
def test_capability_observation_requires_every_task_identity_to_be_null(
    field: str, value: object
) -> None:
    payload = example_payload("mailbox-message.json")
    content = payload["content"]
    assert isinstance(content, dict)
    content.update(
        {
            "message_type": "capability_observation",
            "direction": "host_to_scheduler",
            "sender": "HST-SIMULATOR",
            "recipient": "HST-SCHEDULER",
            "task_id": None,
            "context_snapshot_id": None,
            "attempt": None,
            "lease_id": None,
            "fence": None,
            "idempotency_key": None,
            "provenance": [],
            "payload": {"capabilities": ["sandbox"]},
        }
    )
    content[field] = value
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError, match="must all be null"):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


@pytest.mark.parametrize(
    ("name", "path", "value"),
    [
        (
            "scheduler-event.json",
            ("content", "actor"),
            "scheduler\nforged",
        ),
        (
            "scheduler-event.json",
            ("content", "reason"),
            "ghp_" + "A" * 20,
        ),
        (
            "worktree-lease.json",
            ("content", "recovery_guidance"),
            "C:" + "/" + "Users/example/private",
        ),
        (
            "worktree-lease.json",
            ("content", "recovery_guidance"),
            "unsupported\u202econtrol",
        ),
    ],
)
def test_public_event_and_worktree_text_matches_runtime_safety_policy(
    name: str, path: tuple[object, ...], value: str
) -> None:
    payload = example_payload(name)
    _set_path(payload, path, value)
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


@pytest.mark.parametrize(
    "progress",
    [
        "heartbeat\nforged",
        "C:" + "/" + "Users/example/private",
        "AKIA" + "A" * 16,
        "unsupported\u202econtrol",
    ],
)
def test_public_mailbox_text_matches_runtime_safety_policy(progress: str) -> None:
    payload = example_payload("mailbox-message.json")
    content = payload["content"]
    assert isinstance(content, dict)
    content.update(
        {
            "message_type": "heartbeat",
            "direction": "host_to_scheduler",
            "sender": "HST-SIMULATOR",
            "recipient": "HST-SCHEDULER",
            "payload": {"progress": progress},
        }
    )
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


def _set_path(value: object, path: tuple[object, ...], replacement: object) -> None:
    current = value
    for component in path[:-1]:
        current = current[component]  # type: ignore[index]
    current[path[-1]] = replacement  # type: ignore[index]


@pytest.mark.parametrize(
    ("name", "path", "replacement"),
    [
        ("task-graph.json", ("content", "contexts"), []),
        (
            "task-graph.json",
            ("content", "contexts", 0, "artifact_id"),
            "CTX-BAD",
        ),
        (
            "task-graph.json",
            ("content", "contexts", 0, "sensitivity"),
            "secret-or-prohibited",
        ),
        (
            "task-graph.json",
            ("content", "budget", "max_reasoning_effort"),
            "ultra",
        ),
        (
            "task-graph.json",
            ("content", "budget", "cost", "status"),
            "unknown",
        ),
        (
            "task-graph.json",
            ("content", "tasks", 0, "role_id"),
            "Invalid Role",
        ),
        (
            "task-graph.json",
            ("content", "tasks", 0, "context_snapshot_id"),
            "CTX-BAD",
        ),
        (
            "task-graph.json",
            ("content", "tasks", 0, "approval_stops"),
            ["technical_sandbox", "owner"],
        ),
        (
            "task-graph.json",
            ("content", "tasks", 0, "evidence_predicate"),
            ["arbitrary-evidence-text"],
        ),
        (
            "task-graph.json",
            ("content", "tasks", 0, "terminal_predicate"),
            ["arbitrary-terminal-text"],
        ),
        (
            "task-graph.json",
            ("content", "tasks", 0, "owned_paths"),
            ["CON"],
        ),
        (
            "task-graph.json",
            ("content", "tasks", 0, "owned_paths"),
            ["dir/trailing."],
        ),
        (
            "task-graph.json",
            ("content", "tasks", 0, "required_tools"),
            ["ghp_" + "A" * 36],
        ),
        (
            "task-graph.json",
            ("content", "tasks", 0, "required_capabilities"),
            ["line\nbreak"],
        ),
        (
            "scheduler-state.json",
            ("content", "ready_order"),
            ["TSK-UNKNOWN"],
        ),
        ("lease.json", ("content", "idempotency_key"), "bad"),
        ("mailbox-message.json", ("content", "idempotency_key"), "bad"),
        ("mailbox-message.json", ("content", "fence"), None),
        ("budget-ledger.json", ("content", "availability", "extra"), "available"),
        (
            "worktree-lease.json",
            ("content", "owned_paths"),
            ["src", "src/sdaqf"],
        ),
        (
            "scheduler-event.json",
            ("content", "budget_deltas", "unsupported"),
            1,
        ),
        ("scheduler-event.json", ("content", "cause"), "invented-cause"),
    ],
)
def test_targeted_contract_invariants_reject_semantic_drift(
    name: str,
    path: tuple[object, ...],
    replacement: object,
) -> None:
    payload = example_payload(name)
    _set_path(payload, path, replacement)
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


def test_duplicate_context_state_task_and_unsorted_blockers_are_rejected() -> None:
    graph = example_payload("task-graph.json")
    contexts = graph["content"]["contexts"]  # type: ignore[index]
    graph["content"]["contexts"] = [*contexts, *contexts]  # type: ignore[index]
    refresh_identity(graph)
    with pytest.raises(SchedulerContractError, match="unique"):
        parse_scheduler_artifact_bytes(strict_bytes(graph))

    state = example_payload("scheduler-state.json")
    tasks = state["content"]["tasks"]  # type: ignore[index]
    state["content"]["tasks"] = [*tasks, *tasks]  # type: ignore[index]
    refresh_identity(state)
    with pytest.raises(SchedulerContractError, match="sorted"):
        parse_scheduler_artifact_bytes(strict_bytes(state))

    state = example_payload("scheduler-state.json")
    state["content"]["tasks"][0]["blockers"] = [  # type: ignore[index]
        {"code": "z", "references": []},
        {"code": "a", "references": []},
    ]
    refresh_identity(state)
    with pytest.raises(SchedulerContractError, match="blockers"):
        parse_scheduler_artifact_bytes(strict_bytes(state))


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("content", "heartbeat_interval_seconds"), 31),
        (("content", "expires_at"), "2026-08-01T00:00:00Z"),
    ],
)
def test_standalone_lease_contract_accepts_cross_field_values_for_store_validation(
    path: tuple[object, ...], replacement: object
) -> None:
    payload = example_payload("lease.json")
    _set_path(payload, path, replacement)
    refresh_identity(payload)
    artifact = parse_scheduler_artifact_bytes(strict_bytes(payload))
    assert artifact.artifact_type is SchedulerArtifactType.LEASE


def test_standalone_mailbox_accepts_cross_field_values_for_scheduler_validation() -> None:
    dispatch = example_payload("mailbox-message.json")
    dispatch["content"]["payload"]["heartbeat_interval_seconds"] = 31  # type: ignore[index]
    refresh_identity(dispatch)
    assert (
        parse_scheduler_artifact_bytes(strict_bytes(dispatch)).artifact_type
        is SchedulerArtifactType.MAILBOX_MESSAGE
    )

    approval = example_payload("mailbox-message.json")
    content = approval["content"]
    assert isinstance(content, dict)
    content.update(
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
    refresh_identity(approval)
    assert (
        parse_scheduler_artifact_bytes(strict_bytes(approval)).artifact_type
        is SchedulerArtifactType.MAILBOX_MESSAGE
    )


def test_max_concurrency_cannot_exceed_max_agents() -> None:
    payload = example_payload("task-graph.json")
    payload["content"]["budget"]["max_agents"] = 1  # type: ignore[index]
    payload["content"]["budget"]["max_concurrency"] = 16  # type: ignore[index]
    refresh_identity(payload)
    with pytest.raises(SchedulerContractError, match="max_concurrency"):
        parse_scheduler_artifact_bytes(strict_bytes(payload))


def test_first_event_chain_and_approval_time_identity_rules_are_strict() -> None:
    event = example_payload("scheduler-event.json")
    event["content"]["sequence"] = 1  # type: ignore[index]
    refresh_identity(event)
    with pytest.raises(SchedulerContractError, match="zero chain"):
        parse_scheduler_artifact_bytes(strict_bytes(event))

    for field, value in (
        ("approval_id", "bad"),
        ("supersedes_approval_id", "bad"),
    ):
        message = example_payload("mailbox-message.json")
        content = message["content"]
        assert isinstance(content, dict)
        content["message_type"] = "approval_decision"
        content["direction"] = "owner_to_scheduler"
        content["sender"] = "HST-OWNER"
        content["recipient"] = "HST-SCHEDULER"
        content["payload"] = {
            "approval_id": "APR-M6-VALID",
            "approval_type": "owner",
            "decision": "approved",
            "transition": "dispatch",
            "effect_digest": "D" * 64,
            "approved_at": "2026-08-01T00:00:00Z",
            "expires_at": "2026-08-01T01:00:00Z",
            "authority": "Owner",
            "supersedes_approval_id": None,
        }
        content["payload"][field] = value
        refresh_identity(message)
        with pytest.raises(SchedulerContractError):
            parse_scheduler_artifact_bytes(strict_bytes(message))


def test_loader_suffix_and_stale_serialization_are_rejected(tmp_path: Path) -> None:
    wrong = tmp_path / "lease.txt"
    wrong.write_bytes((ROOT / "examples" / "m6-scheduler" / "lease.json").read_bytes())
    with pytest.raises(SchedulerContractError, match="JSON"):
        load_scheduler_artifact(wrong)

    artifact = load_scheduler_artifact(ROOT / "examples" / "m6-scheduler" / "lease.json")
    stale = LoadedSchedulerArtifact(
        artifact.artifact_type,
        "M6-LEASE-" + "0" * 64,
        artifact.value,
    )
    with pytest.raises(SchedulerContractError, match="stale"):
        serialize_scheduler_artifact(stale)
