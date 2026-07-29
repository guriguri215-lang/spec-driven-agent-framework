from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sdaqf.application.contracts import ContractError
from sdaqf.application.quality_gates import (
    FindingAcceptanceLoader,
    ImplementationEvidenceGateService,
    IndependentReviewGateService,
    finding_digest,
    parse_independent_review,
)
from sdaqf.domain.quality import (
    ClaimState,
    EvidenceStatus,
    EvidenceType,
    ReviewFindingSeverity,
    ReviewFindingStatus,
)
from tests.m3_helpers import (
    BASELINE_ID,
    baseline,
    candidate,
    ledger,
    review_payload,
    write_evidence_artifacts,
)


def test_gate_g2_passes_complete_traceable_evidence(tmp_path: Path) -> None:
    write_evidence_artifacts(tmp_path)
    result = ImplementationEvidenceGateService().evaluate(
        baseline(),
        ledger(),
        candidate=candidate(),
        root=tmp_path,
    )

    assert result.passed
    assert result.hard_blockers == ()
    assert result.to_dict()["gate_id"] == "G2"


def test_gate_g2_rejects_identity_mapping_and_test_only_conformance(
    tmp_path: Path,
) -> None:
    write_evidence_artifacts(tmp_path)
    service = ImplementationEvidenceGateService()
    mismatched = replace(ledger(), source_spec_sha256="B" * 64)
    assert "G2-IDENTITY" in service.evaluate(
        baseline(), mismatched, candidate=candidate(), root=tmp_path
    ).hard_blockers

    claim = replace(
        ledger().claims[0],
        acceptance_criteria=("AC-FR-UNKNOWN-01",),
    )
    bad_trace = replace(ledger(), claims=(claim,))
    assert "G2-TRACE" in service.evaluate(
        baseline(), bad_trace, candidate=candidate(), root=tmp_path
    ).hard_blockers

    test_only = replace(ledger(), evidence=ledger().evidence[:2])
    assert "G2-CONSISTENCY" in service.evaluate(
        baseline(), test_only, candidate=candidate(), root=tmp_path
    ).hard_blockers


def test_gate_g2_rejects_failed_or_unverified_must_claim(
    tmp_path: Path,
) -> None:
    write_evidence_artifacts(tmp_path)
    source = ledger()
    failed_install = replace(source.evidence[1], status=EvidenceStatus.FAIL)
    failed = replace(
        source,
        evidence=(source.evidence[0], failed_install, source.evidence[2]),
    )
    failed_result = ImplementationEvidenceGateService().evaluate(
        baseline(),
        failed,
        candidate=candidate(),
        root=tmp_path,
    )

    assert "G2-CONSISTENCY" in failed_result.hard_blockers
    assert "G2-CRITICAL" in failed_result.hard_blockers

    unverified_claim = replace(source.claims[0], state=ClaimState.UNVERIFIED)
    unverified = replace(source, claims=(unverified_claim,))
    result = ImplementationEvidenceGateService().evaluate(
        baseline(), unverified, candidate=candidate(), root=tmp_path
    )
    assert "G2-CONSISTENCY" in result.hard_blockers
    assert "G2-MUST-VERIFIED" in result.hard_blockers


def test_gate_g2_rejects_candidate_replay_and_contradictory_evidence(
    tmp_path: Path,
) -> None:
    write_evidence_artifacts(tmp_path)
    service = ImplementationEvidenceGateService()
    replayed_candidate = replace(candidate(), repository_digest="E" * 64)
    replay = service.evaluate(
        baseline(),
        ledger(),
        candidate=replayed_candidate,
        root=tmp_path,
    )
    assert {"G2-IDENTITY", "G2-EVIDENCE"} <= set(replay.hard_blockers)

    source = ledger()
    not_verified = replace(
        source.evidence[2],
        evidence_id="EV-UNVERIFIED-0001",
        evidence_type=EvidenceType.UNVERIFIED,
        status=EvidenceStatus.NOT_VERIFIED,
    )
    contradictory = replace(
        source,
        evidence=(*source.evidence, not_verified),
    )
    result = service.evaluate(
        baseline(),
        contradictory,
        candidate=candidate(),
        root=tmp_path,
    )
    assert "G2-CONSISTENCY" in result.hard_blockers


def test_independent_review_loader_and_gate_pass() -> None:
    review = parse_independent_review(review_payload())
    result = IndependentReviewGateService().evaluate(
        review,
        baseline_id=BASELINE_ID,
        candidate=candidate(),
        changed_paths=review.reviewed_paths,
    )

    assert result.passed
    assert review.to_dict() == review_payload()


def test_clean_candidate_review_requires_full_publication_scope() -> None:
    review = parse_independent_review(review_payload())
    result = IndependentReviewGateService().evaluate(
        review,
        baseline_id=BASELINE_ID,
        candidate=candidate(),
        changed_paths=(),
        candidate_paths=(
            "README.md",
            "src/sdaqf/application/quality_gates.py",
        ),
    )

    assert "G3-COVERAGE" in result.hard_blockers


def test_gate_g3_rejects_review_candidate_replay() -> None:
    review = parse_independent_review(review_payload())
    result = IndependentReviewGateService().evaluate(
        review,
        baseline_id=BASELINE_ID,
        candidate=replace(candidate(), repository_digest="E" * 64),
        changed_paths=review.reviewed_paths,
    )

    assert "G3-CANDIDATE" in result.hard_blockers


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"schema_version": "2.0"}),
        lambda value: value.update(
            {"reviewed_agent_ids": ["AGT-REVIEWER-1"]}
        ),
        lambda value: value.update(
            {"areas": ["regression", "regression"]}
        ),
        lambda value: value.update({"reviewed_agent_ids": ["bad"]}),
        lambda value: value.update({"reviewed_paths": []}),
        lambda value: value.update({"baseline_id": "bad"}),
        lambda value: value.update(
            {
                "findings": [
                    _finding("FND-Z", "low", "open"),
                    _finding("FND-A", "low", "open"),
                ]
            }
        ),
    ],
)
def test_review_loader_rejects_invalid_contracts(mutation: Any) -> None:
    payload = copy.deepcopy(review_payload())
    mutation(payload)

    with pytest.raises(ContractError):
        parse_independent_review(payload)


def test_gate_g3_rejects_writes_incomplete_coverage_and_material_findings() -> None:
    payload = review_payload()
    payload["read_only"] = False
    payload["changed_paths"] = ["src/file.py"]
    payload["areas"] = ["security"]
    payload["findings"] = [_finding("FND-MEDIUM", "medium", "open")]
    review = parse_independent_review(payload)

    result = IndependentReviewGateService().evaluate(
        review,
        baseline_id=BASELINE_ID,
        candidate=candidate(),
        changed_paths=review.reviewed_paths,
    )

    assert {
        "G3-INDEPENDENCE",
        "G3-COVERAGE",
        "G3-MATERIAL-FINDINGS",
    } <= set(result.hard_blockers)


def test_critical_finding_requires_exact_owner_acceptance() -> None:
    payload = review_payload()
    payload["findings"] = [
        _finding(
            "FND-CRITICAL",
            "critical",
            "accepted",
            approval_id="APR-CRITICAL",
        )
    ]
    review = parse_independent_review(payload)
    without = IndependentReviewGateService().evaluate(
        review,
        baseline_id=BASELINE_ID,
        candidate=candidate(),
        changed_paths=review.reviewed_paths,
    )
    assert "G3-CRITICAL-FINDINGS" in without.hard_blockers

    approval = FindingAcceptanceLoader(
        clock=lambda: datetime(2026, 7, 30, tzinfo=UTC)
    ).parse(_approval_payload(finding_digest(review.findings[0])))
    with_approval = IndependentReviewGateService().evaluate(
        review,
        baseline_id=BASELINE_ID,
        candidate=candidate(),
        changed_paths=review.reviewed_paths,
        approvals=(approval,),
    )
    assert with_approval.passed

    wrong_scope = replace(approval, finding_id="FND-OTHER")
    rejected = IndependentReviewGateService().evaluate(
        review,
        baseline_id=BASELINE_ID,
        candidate=candidate(),
        changed_paths=review.reviewed_paths,
        approvals=(wrong_scope,),
    )
    assert "G3-CRITICAL-FINDINGS" in rejected.hard_blockers


def test_finding_acceptance_loader_rejects_future_expired_and_wrong_authority() -> None:
    future_loader = FindingAcceptanceLoader(
        clock=lambda: datetime(2026, 7, 28, tzinfo=UTC)
    )
    with pytest.raises(ContractError, match="future"):
        future_loader.parse(_approval_payload())

    expired = _approval_payload()
    expired["expires_at"] = "2026-07-29T01:00:00+00:00"
    with pytest.raises(ContractError, match="expired"):
        FindingAcceptanceLoader(
            clock=lambda: datetime(2026, 7, 30, tzinfo=UTC)
        ).parse(expired)

    no_expiry = _approval_payload()
    no_expiry["expires_at"] = None
    with pytest.raises(ContractError, match="expires_at"):
        FindingAcceptanceLoader(
            clock=lambda: datetime(2026, 7, 30, tzinfo=UTC)
        ).parse(no_expiry)

    authority = _approval_payload()
    authority["approval_type"] = "technical_sandbox"
    with pytest.raises(ContractError, match="approval contract"):
        FindingAcceptanceLoader(
            clock=lambda: datetime(2026, 7, 30, tzinfo=UTC)
        ).parse(authority)

    irreversible = _approval_payload()
    irreversible["reversible"] = False
    with pytest.raises(ContractError, match="reversible"):
        FindingAcceptanceLoader(
            clock=lambda: datetime(2026, 7, 30, tzinfo=UTC)
        ).parse(irreversible)

    bad_expiry = _approval_payload()
    bad_expiry["expires_at"] = "2026-07-28T00:00:00+00:00"
    with pytest.raises(ContractError, match="follow"):
        FindingAcceptanceLoader(
            clock=lambda: datetime(2026, 7, 30, tzinfo=UTC)
        ).parse(bad_expiry)

    with pytest.raises(ValueError, match="timezone-aware"):
        FindingAcceptanceLoader(
            clock=lambda: datetime(2026, 7, 30)
        ).parse(_approval_payload())


def test_gate_g3_rejects_duplicate_approval_and_noncritical_acceptance() -> None:
    payload = review_payload()
    payload["findings"] = [
        _finding(
            "FND-HIGH",
            ReviewFindingSeverity.HIGH.value,
            ReviewFindingStatus.ACCEPTED.value,
            approval_id="APR-CRITICAL",
        )
    ]
    review = parse_independent_review(payload)
    approval = FindingAcceptanceLoader(
        clock=lambda: datetime(2026, 7, 30, tzinfo=UTC)
    ).parse(_approval_payload())

    result = IndependentReviewGateService().evaluate(
        review,
        baseline_id=BASELINE_ID,
        candidate=candidate(),
        changed_paths=review.reviewed_paths,
        approvals=(approval, approval),
    )

    assert "G3-MATERIAL-FINDINGS" in result.hard_blockers
    assert "G3-APPROVALS" in result.hard_blockers


def _finding(
    finding_id: str,
    severity: str,
    status: str,
    *,
    approval_id: str | None = None,
) -> dict[str, object]:
    return {
        "finding_id": finding_id,
        "severity": severity,
        "status": status,
        "statement": "A bounded finding.",
        "specification_refs": ["FR-QA-001"],
        "evidence_refs": ["EV-DIFF-0001"],
        "approval_id": approval_id,
    }


def _approval_payload(finding_sha256: str = "A" * 64) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "approval_id": "APR-CRITICAL",
        "approval_type": "owner",
        "action": "Accept independent review finding",
        "scope": {
            "review_id": "REV-M3-0001",
            "finding_id": "FND-CRITICAL",
            "finding_sha256": finding_sha256,
            "candidate": candidate().to_dict(),
        },
        "risk": "high",
        "status": "approved",
        "rationale": "Exact residual risk accepted.",
        "reversible": True,
        "approved_by": "Owner",
        "approved_at": "2026-07-29T00:00:00+00:00",
        "expires_at": "2026-08-01T00:00:00+00:00",
    }
