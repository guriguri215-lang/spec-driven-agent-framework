from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sdaqf.application.approvals import ApprovalContractError, ApprovalLoader
from sdaqf.application.comparison import BaselineComparator
from tests.m1_helpers import ingest_spec


def approval_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "approval_id": "APR-TEST-001",
        "approval_type": "owner",
        "action": "Approve requirement baseline changes",
        "scope": {
            "previous_baseline_id": "RB-1111111111111111",
            "current_baseline_id": "RB-2222222222222222",
            "change_ids": ["CHG-111111111111"],
        },
        "risk": "high",
        "status": "approved",
        "rationale": "The Owner explicitly accepts the named changes.",
        "reversible": True,
        "approved_by": "Owner",
        "approved_at": "2026-07-27T12:00:00+00:00",
        "expires_at": None,
    }


def test_approval_loader_accepts_complete_owner_record(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval_payload()), encoding="utf-8")

    approval = ApprovalLoader(
        clock=lambda: datetime(2026, 7, 27, 13, 0, tzinfo=UTC)
    ).load(path)

    assert approval.approval_id == "APR-TEST-001"
    assert approval.approved_by == "Owner"
    assert approval.change_ids == ("CHG-111111111111",)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("approval_type", "technical_sandbox", "must be owner"),
        ("action", "Approve anything", "not a baseline-change"),
        ("status", "pending", "must be approved"),
        ("approved_by", "Implementer", "must be Owner"),
        ("rationale", "", "non-empty"),
        ("reversible", False, "must be true"),
    ],
)
def test_approval_loader_rejects_missing_owner_provenance(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = approval_payload()
    payload[field] = value

    with pytest.raises(ApprovalContractError, match=message):
        ApprovalLoader().parse(payload)


def test_approval_loader_rejects_expired_record() -> None:
    payload = approval_payload()
    payload["expires_at"] = "2026-07-27T12:30:00+00:00"

    with pytest.raises(ApprovalContractError, match="expired"):
        ApprovalLoader(
            clock=lambda: datetime(2026, 7, 27, 13, 0, tzinfo=UTC)
        ).parse(payload)


def test_comparison_rejects_wrong_baseline_or_unknown_change_scope(
    tmp_path: Path,
) -> None:
    previous = ingest_spec(tmp_path)
    current = copy.deepcopy(previous)
    current = type(previous)(
        baseline_id=previous.baseline_id,
        source=previous.source,
        requirements=previous.requirements[1:],
        source_acceptance_criteria=previous.source_acceptance_criteria,
        diagnostics=previous.diagnostics,
    )
    comparison = BaselineComparator().compare(previous, current)
    payload = approval_payload()
    payload["scope"] = {
        "previous_baseline_id": "RB-1111111111111111",
        "current_baseline_id": current.baseline_id,
        "change_ids": list(comparison.unresolved_approvals),
    }
    wrong_baseline = ApprovalLoader().parse(payload)

    with pytest.raises(ApprovalContractError, match="does not match"):
        BaselineComparator().compare(
            previous,
            current,
            approvals=(wrong_baseline,),
        )

    payload["scope"] = {
        "previous_baseline_id": previous.baseline_id,
        "current_baseline_id": current.baseline_id,
        "change_ids": ["CHG-111111111111"],
    }
    unknown_change = ApprovalLoader().parse(payload)
    with pytest.raises(ApprovalContractError, match="unknown change"):
        BaselineComparator().compare(
            previous,
            current,
            approvals=(unknown_change,),
        )
