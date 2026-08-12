"""Public M6 schemas, evaluation records, and package-boundary tests."""

from __future__ import annotations

import json

import pytest
from scripts.validate_m6_scheduler import main

import sdaqf
from sdaqf.application.scheduler_contracts import (
    SchedulerContractError,
    parse_scheduler_artifact_bytes,
)
from sdaqf.domain.scheduler import SchedulerArtifactType
from tests.m6_scheduler_helpers import (
    ROOT,
    example_payload,
    refresh_identity,
    strict_bytes,
)
from tests.schema_validation import LocalSchemaValidator, SchemaValidationError

EXAMPLE_TO_SCHEMA = {
    "task-graph.json": "task-graph.schema.json",
    "scheduler-state.json": "scheduler-state.schema.json",
    "lease.json": "lease.schema.json",
    "mailbox-message.json": "mailbox-message.schema.json",
    "scheduler-event.json": "scheduler-event.schema.json",
    "budget-ledger.json": "budget-ledger.schema.json",
    "worktree-lease.json": "worktree-lease.schema.json",
    "workflow-epoch-event.json": "workflow-epoch-event.schema.json",
    "scheduler-store-migration-approval.json": "scheduler-store-migration-approval.schema.json",
    "scheduler-store-migration-result.json": "scheduler-store-migration-result.schema.json",
}


def test_all_ten_public_examples_validate_against_local_schemas() -> None:
    for example, schema_name in EXAMPLE_TO_SCHEMA.items():
        instance = json.loads(
            (ROOT / "examples" / "m6-scheduler" / example).read_text(encoding="utf-8")
        )
        LocalSchemaValidator(ROOT / "schemas").validate(schema_name, instance)


@pytest.mark.parametrize("invalid_value", [None, 1, [], {}])
@pytest.mark.parametrize(
    ("example_name", "content_field", "expected_type"),
    [
        (
            "workflow-epoch-event.json",
            None,
            SchedulerArtifactType.WORKFLOW_EPOCH_EVENT,
        ),
        (
            "workflow-epoch-event.json",
            "plan_id",
            SchedulerArtifactType.WORKFLOW_EPOCH_EVENT,
        ),
        (
            "workflow-epoch-event.json",
            "idempotency_key",
            SchedulerArtifactType.WORKFLOW_EPOCH_EVENT,
        ),
        (
            "scheduler-store-migration-approval.json",
            None,
            SchedulerArtifactType.SCHEDULER_STORE_MIGRATION_APPROVAL,
        ),
        (
            "scheduler-store-migration-approval.json",
            "root_sha256",
            SchedulerArtifactType.SCHEDULER_STORE_MIGRATION_APPROVAL,
        ),
        (
            "scheduler-store-migration-result.json",
            None,
            SchedulerArtifactType.SCHEDULER_STORE_MIGRATION_RESULT,
        ),
        (
            "scheduler-store-migration-result.json",
            "root_sha256",
            SchedulerArtifactType.SCHEDULER_STORE_MIGRATION_RESULT,
        ),
        (
            "scheduler-store-migration-result.json",
            "approval_id",
            SchedulerArtifactType.SCHEDULER_STORE_MIGRATION_RESULT,
        ),
    ],
)
def test_additive_m6_pattern_fields_reject_non_strings_in_schema_and_runtime(
    example_name: str,
    content_field: str | None,
    expected_type: SchedulerArtifactType,
    invalid_value: object,
) -> None:
    payload = example_payload(example_name)
    if content_field is None:
        payload["artifact_id"] = invalid_value
    else:
        content = payload["content"]
        assert isinstance(content, dict)
        content[content_field] = invalid_value
        refresh_identity(payload)

    with pytest.raises(SchemaValidationError):
        LocalSchemaValidator(ROOT / "schemas").validate(
            EXAMPLE_TO_SCHEMA[example_name],
            payload,
        )
    with pytest.raises(SchedulerContractError):
        parse_scheduler_artifact_bytes(
            strict_bytes(payload),
            expected_type=expected_type,
        )


@pytest.mark.parametrize(
    ("artifact_type", "artifact_id"),
    [
        ("integrated-plan", "M8-WORKFLOW-STATE-" + "A" * 64),
        ("workflow-state", "M8-WORKFLOW-EVENT-" + "A" * 64),
        ("workflow-event", "M8-WORKFLOW-OUTCOME-" + "A" * 64),
        ("workflow-outcome", "M8-INTEGRATED-PLAN-" + "A" * 64),
    ],
)
def test_workflow_epoch_receipt_type_and_id_prefix_mismatch_is_rejected(
    artifact_type: str,
    artifact_id: str,
) -> None:
    payload = example_payload("workflow-epoch-event.json")
    content = payload["content"]
    assert isinstance(content, dict)
    receipts = content["receipts"]
    assert isinstance(receipts, list)
    receipt = receipts[0]
    assert isinstance(receipt, dict)
    receipt["artifact_type"] = artifact_type
    receipt["artifact_id"] = artifact_id

    _assert_workflow_epoch_schema_and_runtime_reject(payload)


@pytest.mark.parametrize("artifact_id", [None, 1, [], {}])
def test_workflow_epoch_receipt_non_string_artifact_id_is_rejected(
    artifact_id: object,
) -> None:
    payload = example_payload("workflow-epoch-event.json")
    content = payload["content"]
    assert isinstance(content, dict)
    receipts = content["receipts"]
    assert isinstance(receipts, list)
    receipt = receipts[0]
    assert isinstance(receipt, dict)
    receipt["artifact_id"] = artifact_id

    _assert_workflow_epoch_schema_and_runtime_reject(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("workflow_event_id", "M8-WORKFLOW-EVENT-" + "A" * 64),
        ("workflow_event_path", "workflow/event.json"),
        ("workflow_state_id", "M8-WORKFLOW-STATE-" + "A" * 64),
        ("workflow_state_path", "workflow/state.json"),
        ("outcome_id", "M8-WORKFLOW-OUTCOME-" + "A" * 64),
        ("outcome_path", "workflow/outcome.json"),
    ],
)
def test_workflow_epoch_artifact_head_id_and_path_must_be_paired(
    field: str,
    value: str,
) -> None:
    payload = example_payload("workflow-epoch-event.json")
    content = payload["content"]
    assert isinstance(content, dict)
    content[field] = value

    _assert_workflow_epoch_schema_and_runtime_reject(payload)


def _assert_workflow_epoch_schema_and_runtime_reject(
    payload: dict[str, object],
) -> None:
    refresh_identity(payload)
    with pytest.raises(SchemaValidationError):
        LocalSchemaValidator(ROOT / "schemas").validate(
            "workflow-epoch-event.schema.json",
            payload,
        )
    with pytest.raises(SchedulerContractError):
        parse_scheduler_artifact_bytes(
            strict_bytes(payload),
            expected_type=SchedulerArtifactType.WORKFLOW_EPOCH_EVENT,
        )


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
def test_capability_observation_schema_requires_exact_null_task_identity(
    field: str, value: object
) -> None:
    instance = json.loads(
        (ROOT / "examples" / "m6-scheduler" / "mailbox-message.json").read_text()
    )
    content = instance["content"]
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
    with pytest.raises(SchemaValidationError):
        LocalSchemaValidator(ROOT / "schemas").validate(
            "mailbox-message.schema.json", instance
        )


@pytest.mark.parametrize(
    ("example", "schema", "field", "value"),
    [
        (
            "scheduler-event.json",
            "scheduler-event.schema.json",
            "actor",
            "scheduler\nforged",
        ),
        (
            "scheduler-event.json",
            "scheduler-event.schema.json",
            "reason",
            "ghp_" + "A" * 20,
        ),
        (
            "worktree-lease.json",
            "worktree-lease.schema.json",
            "recovery_guidance",
            "C:" + "/" + "Users/example/private",
        ),
        (
            "worktree-lease.json",
            "worktree-lease.schema.json",
            "recovery_guidance",
            "unsupported\u202econtrol",
        ),
    ],
)
def test_public_text_schemas_match_runtime_path_free_policy(
    example: str, schema: str, field: str, value: str
) -> None:
    instance = json.loads((ROOT / "examples" / "m6-scheduler" / example).read_text())
    instance["content"][field] = value
    with pytest.raises(SchemaValidationError):
        LocalSchemaValidator(ROOT / "schemas").validate(schema, instance)


@pytest.mark.parametrize(
    "progress",
    [
        "heartbeat\nforged",
        "C:" + "/" + "Users/example/private",
        "AKIA" + "A" * 16,
        "unsupported\u202econtrol",
    ],
)
def test_mailbox_text_schema_matches_runtime_path_free_policy(progress: str) -> None:
    instance = json.loads(
        (ROOT / "examples" / "m6-scheduler" / "mailbox-message.json").read_text()
    )
    content = instance["content"]
    content.update(
        {
            "message_type": "heartbeat",
            "direction": "host_to_scheduler",
            "sender": "HST-SIMULATOR",
            "recipient": "HST-SCHEDULER",
            "payload": {"progress": progress},
        }
    )
    with pytest.raises(SchemaValidationError):
        LocalSchemaValidator(ROOT / "schemas").validate(
            "mailbox-message.schema.json", instance
        )


def test_evaluation_is_named_and_has_no_aggregate_score() -> None:
    suite = json.loads((ROOT / "evals" / "m6-scheduler-suite.json").read_text())
    result = json.loads((ROOT / "evals" / "results" / "m6-scheduler-evaluation.json").read_text())
    expected = [case["case_id"] for case in suite["cases"]]
    assert len(expected) == 10
    assert [case["case_id"] for case in result["cases"]] == expected
    assert "aggregate_score" not in result
    assert all(case["passed"] is True for case in result["cases"])
    assert all(
        case["expected_wait_kind"] in {"clear", "stall", "deadlock"}
        for case in suite["cases"]
    )
    assert all(
        case["observed_wait_kind"] == expected_case["expected_wait_kind"]
        and case["observed_blockers"] == expected_case["expected_blockers"]
        for case, expected_case in zip(result["cases"], suite["cases"], strict=True)
    )


def test_stable_top_level_exports_do_not_widen_for_m6() -> None:
    assert all("scheduler" not in item.casefold() for item in sdaqf.__all__)
    assert all("lease" not in item.casefold() for item in sdaqf.__all__)


def test_named_validator_is_callable_and_passes() -> None:
    assert main() == 0


def test_current_ci_enforces_m6_coverage_and_named_validation() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    normalized = " ".join(workflow.split())
    gate_runner = (ROOT / "scripts" / "run_local_gate.py").read_text(encoding="utf-8")
    assert "M1 through M8 critical branch coverage" in workflow
    assert "src/sdaqf/domain/scheduler.py" in gate_runner
    assert "src/sdaqf/application/scheduler_simulation.py" in gate_runner
    assert "90," in gate_runner
    assert "Validate M6 scheduler safety" in workflow
    assert (
        "python scripts/run_local_gate.py script scripts/validate_m6_scheduler.py"
        in normalized
    )
