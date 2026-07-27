from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.application.approvals import BaselineChangeApproval
from sdaqf.application.comparison import BaselineComparator, ChangeKind
from sdaqf.domain.requirements import RequirementPriority, RequirementType
from tests.m1_helpers import ingest_spec


def test_comparison_ignores_import_metadata_only_changes(tmp_path: Path) -> None:
    previous = ingest_spec(tmp_path)
    changed_source = replace(
        previous.source,
        imported_at="2026-07-28T12:00:00+00:00",
    )
    current = replace(previous, source=changed_source)

    comparison = BaselineComparator().compare(previous, current)

    assert comparison.changes == ()
    assert comparison.unresolved_approvals == ()


def test_addition_needs_no_approval_but_removal_does(tmp_path: Path) -> None:
    previous = ingest_spec(tmp_path)
    removed = replace(
        previous,
        baseline_id="RB-1111111111111111",
        requirements=previous.requirements[1:],
    )

    comparison = BaselineComparator().compare(previous, removed)

    assert len(comparison.changes) == 1
    change = comparison.changes[0]
    assert change.kind is ChangeKind.REMOVED
    assert change.approval_required
    assert comparison.unresolved_approvals == (change.change_id,)

    approved = BaselineComparator().compare(
        previous,
        removed,
        approvals=(
            _approval(
                previous.baseline_id,
                removed.baseline_id,
                (change.change_id,),
            ),
        ),
    )
    assert approved.unresolved_approvals == ()
    assert approved.changes[0].approval_status == "approved"

    added = BaselineComparator().compare(removed, previous)
    assert added.changes[0].kind is ChangeKind.ADDED
    assert not added.changes[0].approval_required


def test_priority_weakening_and_statement_change_require_approval(
    tmp_path: Path,
) -> None:
    previous = ingest_spec(tmp_path)
    target = previous.requirements[0]
    weakened = replace(
        target,
        priority=RequirementPriority.COULD,
        statement=target.statement + " Only when convenient.",
    )
    current = replace(
        previous,
        baseline_id="RB-2222222222222222",
        requirements=(weakened, *previous.requirements[1:]),
    )

    comparison = BaselineComparator().compare(previous, current)

    kinds = {item.kind for item in comparison.changes}
    assert kinds == {ChangeKind.STATEMENT_CHANGED, ChangeKind.PRIORITY_CHANGED}
    assert all(item.approval_required for item in comparison.changes)
    assert len(comparison.unresolved_approvals) == 2


def test_priority_strengthening_does_not_require_approval(tmp_path: Path) -> None:
    previous = ingest_spec(tmp_path)
    target = replace(previous.requirements[0], priority=RequirementPriority.SHOULD)
    weak_baseline = replace(previous, requirements=(target, *previous.requirements[1:]))

    comparison = BaselineComparator().compare(weak_baseline, previous)

    assert comparison.changes[0].kind is ChangeKind.PRIORITY_CHANGED
    assert not comparison.changes[0].approval_required


def test_acceptance_verification_type_and_interpretation_changes_are_reported(
    tmp_path: Path,
) -> None:
    previous = ingest_spec(tmp_path)
    target = previous.requirements[0]
    criterion = replace(
        target.acceptance_criteria[0],
        statement="A stricter acceptance statement.",
    )
    changed = replace(
        target,
        requirement_type=RequirementType.NONFUNCTIONAL,
        acceptance_criteria=(criterion,),
        verification_methods=("benchmark",),
        assumptions=("A new assumption.",),
    )
    current = replace(
        previous,
        requirements=(changed, *previous.requirements[1:]),
    )

    comparison = BaselineComparator().compare(previous, current)

    assert {item.kind for item in comparison.changes} == {
        ChangeKind.TYPE_CHANGED,
        ChangeKind.ACCEPTANCE_CHANGED,
        ChangeKind.VERIFICATION_CHANGED,
        ChangeKind.INTERPRETATION_CHANGED,
    }
    assert len(comparison.unresolved_approvals) == 4


def _approval(
    previous_baseline_id: str,
    current_baseline_id: str,
    change_ids: tuple[str, ...],
) -> BaselineChangeApproval:
    return BaselineChangeApproval(
        approval_id="APR-TEST-001",
        previous_baseline_id=previous_baseline_id,
        current_baseline_id=current_baseline_id,
        change_ids=change_ids,
        rationale="The Owner explicitly accepts this synthetic test change.",
        approved_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC).isoformat(),
        expires_at=None,
    )
