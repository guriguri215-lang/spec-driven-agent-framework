"""Deterministic comparison of two requirement baselines."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import StrEnum

from sdaqf.application.approvals import ApprovalContractError, BaselineChangeApproval
from sdaqf.domain.requirements import (
    AcceptanceCriterion,
    RequirementBaseline,
    RequirementPriority,
)


class ChangeKind(StrEnum):
    """Supported baseline-change classifications."""

    ADDED = "added"
    REMOVED = "removed"
    STATEMENT_CHANGED = "statement-changed"
    PRIORITY_CHANGED = "priority-changed"
    TYPE_CHANGED = "type-changed"
    ACCEPTANCE_CHANGED = "acceptance-changed"
    VERIFICATION_CHANGED = "verification-changed"
    INTERPRETATION_CHANGED = "interpretation-changed"


@dataclass(frozen=True, slots=True)
class BaselineChange:
    """One requirement-level baseline change."""

    change_id: str
    requirement_id: str
    kind: ChangeKind
    previous: str | None
    current: str | None
    approval_required: bool
    approval_status: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "id": self.change_id,
            "requirement_id": self.requirement_id,
            "kind": self.kind.value,
            "previous": self.previous,
            "current": self.current,
            "approval_required": self.approval_required,
            "approval_status": self.approval_status,
        }


@dataclass(frozen=True, slots=True)
class BaselineDiff:
    """Complete comparison result and approval state."""

    previous_baseline_id: str
    current_baseline_id: str
    changes: tuple[BaselineChange, ...]

    @property
    def unresolved_approvals(self) -> tuple[str, ...]:
        """Return required change IDs without explicit approval."""

        return tuple(
            item.change_id
            for item in self.changes
            if item.approval_required and item.approval_status != "approved"
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "schema_version": "1.0",
            "previous_baseline_id": self.previous_baseline_id,
            "current_baseline_id": self.current_baseline_id,
            "changes": [item.to_dict() for item in self.changes],
            "unresolved_approvals": list(self.unresolved_approvals),
        }


class BaselineComparator:
    """Compare normalized semantic fields, ignoring import timestamps."""

    def compare(
        self,
        previous: RequirementBaseline,
        current: RequirementBaseline,
        *,
        approvals: tuple[BaselineChangeApproval, ...] = (),
    ) -> BaselineDiff:
        """Return deterministic additions, removals, and material changes."""

        old = {item.requirement_id: item for item in previous.requirements}
        new = {item.requirement_id: item for item in current.requirements}
        changes: list[BaselineChange] = []
        for identifier in sorted(old.keys() | new.keys()):
            prior = old.get(identifier)
            present = new.get(identifier)
            if prior is None and present is not None:
                changes.append(
                    _change(
                        identifier,
                        ChangeKind.ADDED,
                        None,
                        present.statement,
                        approval_required=False,
                    )
                )
                continue
            if prior is not None and present is None:
                changes.append(
                    _change(
                        identifier,
                        ChangeKind.REMOVED,
                        prior.statement,
                        None,
                        approval_required=True,
                    )
                )
                continue
            if prior is None or present is None:
                raise AssertionError("comparison state is incomplete")
            if prior.statement != present.statement:
                changes.append(
                    _change(
                        identifier,
                        ChangeKind.STATEMENT_CHANGED,
                        prior.statement,
                        present.statement,
                        approval_required=True,
                    )
                )
            if prior.priority is not present.priority:
                weakening = _priority_rank(present.priority) < _priority_rank(prior.priority)
                changes.append(
                    _change(
                        identifier,
                        ChangeKind.PRIORITY_CHANGED,
                        prior.priority.value,
                        present.priority.value,
                        approval_required=weakening,
                    )
                )
            if prior.requirement_type is not present.requirement_type:
                changes.append(
                    _change(
                        identifier,
                        ChangeKind.TYPE_CHANGED,
                        prior.requirement_type.value,
                        present.requirement_type.value,
                        approval_required=True,
                    )
                )
            prior_acceptance = _criteria_value(prior.acceptance_criteria)
            present_acceptance = _criteria_value(present.acceptance_criteria)
            if prior_acceptance != present_acceptance:
                changes.append(
                    _change(
                        identifier,
                        ChangeKind.ACCEPTANCE_CHANGED,
                        prior_acceptance,
                        present_acceptance,
                        approval_required=True,
                    )
                )
            prior_verification = _tuple_value(prior.verification_methods)
            present_verification = _tuple_value(present.verification_methods)
            if prior_verification != present_verification:
                changes.append(
                    _change(
                        identifier,
                        ChangeKind.VERIFICATION_CHANGED,
                        prior_verification,
                        present_verification,
                        approval_required=True,
                    )
                )
            prior_interpretation = _tuple_value(
                (*prior.assumptions, *prior.open_questions)
            )
            present_interpretation = _tuple_value(
                (*present.assumptions, *present.open_questions)
            )
            if prior_interpretation != present_interpretation:
                changes.append(
                    _change(
                        identifier,
                        ChangeKind.INTERPRETATION_CHANGED,
                        prior_interpretation,
                        present_interpretation,
                        approval_required=True,
                    )
                )
        changes = _apply_approvals(
            previous.baseline_id,
            current.baseline_id,
            changes,
            approvals,
        )
        return BaselineDiff(
            previous_baseline_id=previous.baseline_id,
            current_baseline_id=current.baseline_id,
            changes=tuple(changes),
        )


def _priority_rank(priority: RequirementPriority) -> int:
    return {
        RequirementPriority.COULD: 1,
        RequirementPriority.SHOULD: 2,
        RequirementPriority.MUST: 3,
    }[priority]


def _criteria_value(criteria: tuple[AcceptanceCriterion, ...]) -> str:
    return json.dumps(
        [criterion.to_dict() for criterion in criteria],
        sort_keys=True,
        separators=(",", ":"),
    )


def _tuple_value(values: tuple[str, ...]) -> str:
    return json.dumps(values, separators=(",", ":"))


def _apply_approvals(
    previous_baseline_id: str,
    current_baseline_id: str,
    changes: list[BaselineChange],
    approvals: tuple[BaselineChangeApproval, ...],
) -> list[BaselineChange]:
    known_change_ids = {change.change_id for change in changes}
    approved_change_ids: set[str] = set()
    approval_ids: set[str] = set()
    for approval in approvals:
        if approval.approval_id in approval_ids:
            raise ApprovalContractError("Approval records must have unique identifiers.")
        approval_ids.add(approval.approval_id)
        if (
            approval.previous_baseline_id != previous_baseline_id
            or approval.current_baseline_id != current_baseline_id
        ):
            raise ApprovalContractError(
                "Approval scope does not match the compared baselines."
            )
        unknown = set(approval.change_ids) - known_change_ids
        if unknown:
            raise ApprovalContractError("Approval scope contains an unknown change ID.")
        approved_change_ids.update(approval.change_ids)
    return [
        replace(change, approval_status="approved")
        if change.approval_required and change.change_id in approved_change_ids
        else change
        for change in changes
    ]


def _change(
    requirement_id: str,
    kind: ChangeKind,
    previous: str | None,
    current: str | None,
    *,
    approval_required: bool,
) -> BaselineChange:
    stable = "|".join((requirement_id, kind.value, previous or "", current or ""))
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12].upper()
    change_id = f"CHG-{digest}"
    approval_status = "required" if approval_required else "not-required"
    return BaselineChange(
        change_id=change_id,
        requirement_id=requirement_id,
        kind=kind,
        previous=previous,
        current=current,
        approval_required=approval_required,
        approval_status=approval_status,
    )
