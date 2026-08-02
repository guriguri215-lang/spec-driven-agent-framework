"""Public M6 schemas, evaluation records, and package-boundary tests."""

from __future__ import annotations

import json

import pytest
from scripts.validate_m6_scheduler import main

import sdaqf
from tests.m6_scheduler_helpers import ROOT
from tests.schema_validation import LocalSchemaValidator, SchemaValidationError

EXAMPLE_TO_SCHEMA = {
    "task-graph.json": "task-graph.schema.json",
    "scheduler-state.json": "scheduler-state.schema.json",
    "lease.json": "lease.schema.json",
    "mailbox-message.json": "mailbox-message.schema.json",
    "scheduler-event.json": "scheduler-event.schema.json",
    "budget-ledger.json": "budget-ledger.schema.json",
    "worktree-lease.json": "worktree-lease.schema.json",
}


def test_all_seven_public_examples_validate_against_local_schemas() -> None:
    for example, schema_name in EXAMPLE_TO_SCHEMA.items():
        instance = json.loads(
            (ROOT / "examples" / "m6-scheduler" / example).read_text(encoding="utf-8")
        )
        LocalSchemaValidator(ROOT / "schemas").validate(schema_name, instance)


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
    assert "Check M6 critical coverage" in workflow
    assert "src/sdaqf/domain/scheduler.py" in workflow
    assert "src/sdaqf/application/scheduler_simulation.py" in workflow
    assert "--fail-under=90" in normalized
    assert "Validate M6 scheduler safety" in workflow
    assert "python scripts/validate_m6_scheduler.py" in normalized
