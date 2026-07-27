from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.application.approvals import BaselineChangeApproval
from sdaqf.application.comparison import BaselineComparator
from sdaqf.application.requirements_gate import RequirementsGateService
from sdaqf.domain.requirements import RequirementPriority
from tests.m1_helpers import ingest_spec


def test_requirements_gate_passes_complete_baseline(tmp_path: Path) -> None:
    result = RequirementsGateService().evaluate(ingest_spec(tmp_path))

    assert result.passed
    assert result.hard_blockers == ()
    assert {item.check_id for item in result.checks} == {
        "G1-SOURCE",
        "G1-STABLE-IDS",
        "G1-MUST-PRESENT",
        "G1-ACCEPTANCE",
        "G1-VERIFICATION",
        "G1-SOURCE-TRACE",
        "G1-DOWNSTREAM-TRACE",
        "G1-OPEN-DECISIONS",
        "G1-DIAGNOSTICS",
        "G1-APPROVALS",
        "G1-NO-UNVERIFIED-CLAIM",
    }


def test_recorded_nonblocking_diagnostics_do_not_fail_gate(tmp_path: Path) -> None:
    baseline = ingest_spec(
        tmp_path,
        """# Contract
## Functional requirements
- `FR-APP-001`: The app must create a snapshot when practical.
""",
    )

    result = RequirementsGateService().evaluate(baseline)

    assert baseline.diagnostics
    assert result.passed


def test_unresolved_blocking_diagnostic_fails_gate(tmp_path: Path) -> None:
    baseline = ingest_spec(
        tmp_path,
        """# Contract
## Functional requirements
- `FR-APP-001`: The app must be user-friendly.
""",
    )

    result = RequirementsGateService().evaluate(baseline)

    assert not result.passed
    assert "G1-DIAGNOSTICS" in result.hard_blockers


def test_removal_requires_approval_before_gate_can_pass(tmp_path: Path) -> None:
    previous = ingest_spec(tmp_path)
    current = replace(
        previous,
        baseline_id="RB-1111111111111111",
        requirements=previous.requirements[1:],
    )
    comparison = BaselineComparator().compare(previous, current)

    blocked = RequirementsGateService().evaluate(current, comparison=comparison)
    assert not blocked.passed
    assert "G1-APPROVALS" in blocked.hard_blockers

    approved_comparison = BaselineComparator().compare(
        previous,
        current,
        approvals=(
            BaselineChangeApproval(
                approval_id="APR-TEST-GATE",
                previous_baseline_id=previous.baseline_id,
                current_baseline_id=current.baseline_id,
                change_ids=comparison.unresolved_approvals,
                rationale="The Owner explicitly accepts this synthetic test removal.",
                approved_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC).isoformat(),
                expires_at=None,
            ),
        ),
    )
    approved = RequirementsGateService().evaluate(
        current, comparison=approved_comparison
    )
    assert approved.passed


def test_gate_rejects_baseline_approval_and_unverified_claim(tmp_path: Path) -> None:
    baseline = ingest_spec(tmp_path)
    claimed = replace(baseline.requirements[0], status="implemented")
    unsafe = replace(
        baseline,
        requirements=(claimed, *baseline.requirements[1:]),
        approval_required=("CHG-111111111111",),
    )

    result = RequirementsGateService().evaluate(unsafe)

    assert not result.passed
    assert {"G1-APPROVALS", "G1-NO-UNVERIFIED-CLAIM"} <= set(result.hard_blockers)


def test_gate_requires_at_least_one_must_requirement(tmp_path: Path) -> None:
    baseline = ingest_spec(tmp_path)
    optional = tuple(
        replace(item, priority=RequirementPriority.SHOULD)
        for item in baseline.requirements
    )

    result = RequirementsGateService().evaluate(
        replace(baseline, requirements=optional)
    )

    assert not result.passed
    assert "G1-MUST-PRESENT" in result.hard_blockers


def test_gate_rejects_generated_id_and_acceptance_link_tampering(
    tmp_path: Path,
) -> None:
    baseline = ingest_spec(tmp_path)
    generated = next(
        item for item in baseline.requirements if item.identifier_source == "generated"
    )
    fake_id = "OD-AUTO-111111111111"
    fake_criterion = replace(
        generated.acceptance_criteria[0],
        criterion_id=f"AC-{fake_id}-01",
    )
    fake_generated = replace(
        generated,
        requirement_id=fake_id,
        acceptance_criteria=(fake_criterion,),
    )
    requirements = tuple(
        fake_generated if item is generated else item
        for item in baseline.requirements
    )
    result = RequirementsGateService().evaluate(
        replace(baseline, requirements=requirements)
    )
    assert "G1-STABLE-IDS" in result.hard_blockers

    explicit = next(
        item for item in baseline.requirements if item.identifier_source == "explicit"
    )
    wrong_criterion = replace(
        explicit.acceptance_criteria[0],
        criterion_id="AC-FR-OTHER-001-01",
    )
    wrong_link = replace(explicit, acceptance_criteria=(wrong_criterion,))
    requirements = tuple(
        wrong_link if item is explicit else item for item in baseline.requirements
    )
    result = RequirementsGateService().evaluate(
        replace(baseline, requirements=requirements)
    )
    assert "G1-ACCEPTANCE" in result.hard_blockers


def test_gate_rejects_unlinked_optional_acceptance_criterion(
    tmp_path: Path,
) -> None:
    baseline = ingest_spec(tmp_path)
    optional = replace(
        baseline.requirements[1],
        priority=RequirementPriority.SHOULD,
    )
    wrong_criterion = replace(
        optional.acceptance_criteria[0],
        criterion_id="AC-FR-OTHER-001-01",
    )
    wrong_link = replace(optional, acceptance_criteria=(wrong_criterion,))
    requirements = tuple(
        wrong_link if item is baseline.requirements[1] else item
        for item in baseline.requirements
    )

    result = RequirementsGateService().evaluate(
        replace(baseline, requirements=requirements)
    )

    assert not result.passed
    assert "G1-ACCEPTANCE" in result.hard_blockers
