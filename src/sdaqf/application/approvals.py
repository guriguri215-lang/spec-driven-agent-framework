"""Structured Owner approval records for requirement baseline changes."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.application.workspace import is_reparse_point

_MAX_APPROVAL_BYTES = 64 * 1024


class ApprovalContractError(ValueError):
    """A structured Owner approval record is invalid or inapplicable."""


@dataclass(frozen=True, slots=True)
class BaselineChangeApproval:
    """Explicit Owner approval for named changes between two baselines."""

    approval_id: str
    previous_baseline_id: str
    current_baseline_id: str
    change_ids: tuple[str, ...]
    rationale: str
    approved_at: str
    expires_at: str | None
    approved_by: str = "Owner"


class ApprovalLoader:
    """Load a bounded approval file and validate Owner provenance fields."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def load(self, path: Path) -> BaselineChangeApproval:
        """Load one regular JSON approval record."""

        if path.suffix.lower() != ".json":
            raise ApprovalContractError("Approval record must be a JSON file.")
        if path.is_symlink() or is_reparse_point(path) or not path.is_file():
            raise ApprovalContractError("Approval record must be a regular, unlinked file.")
        try:
            if path.stat().st_size > _MAX_APPROVAL_BYTES:
                raise ApprovalContractError("Approval record exceeds the size limit.")
            payload: object = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ApprovalContractError("Approval record could not be read.") from exc
        return self.parse(payload)

    def parse(self, payload: object) -> BaselineChangeApproval:
        """Validate a decoded approval record."""

        root = _object(payload, "approval")
        expected = {
            "schema_version",
            "approval_id",
            "approval_type",
            "action",
            "scope",
            "risk",
            "status",
            "rationale",
            "reversible",
            "approved_by",
            "approved_at",
            "expires_at",
        }
        _only_keys(root, expected, "approval")
        if _string(root.get("schema_version"), "schema_version") != "1.0":
            raise ApprovalContractError("schema_version must be 1.0.")
        approval_id = _string(root.get("approval_id"), "approval_id")
        if not re.fullmatch(r"APR-[A-Z0-9-]+", approval_id):
            raise ApprovalContractError("approval_id must be a stable APR identifier.")
        if _string(root.get("approval_type"), "approval_type") != "owner":
            raise ApprovalContractError("approval_type must be owner.")
        if (
            _string(root.get("action"), "action")
            != "Approve requirement baseline changes"
        ):
            raise ApprovalContractError("action is not a baseline-change approval.")
        if _string(root.get("risk"), "risk") not in {"medium", "high"}:
            raise ApprovalContractError("risk must be medium or high.")
        if _string(root.get("status"), "status") != "approved":
            raise ApprovalContractError("status must be approved.")
        if root.get("reversible") is not True:
            raise ApprovalContractError("reversible must be true.")
        approved_by = _string(root.get("approved_by"), "approved_by")
        if approved_by != "Owner":
            raise ApprovalContractError("approved_by must be Owner.")
        approved_at = _timestamp(root.get("approved_at"), "approved_at")
        expires_value = root.get("expires_at")
        expires_at = (
            None
            if expires_value is None
            else _timestamp(expires_value, "expires_at")
        )
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        approved_time = datetime.fromisoformat(approved_at)
        if approved_time > now:
            raise ApprovalContractError("Approval time cannot be in the future.")
        if expires_at is not None:
            expires_time = datetime.fromisoformat(expires_at)
            if expires_time <= approved_time:
                raise ApprovalContractError("Approval expiry must follow approval time.")
            if expires_time <= now:
                raise ApprovalContractError("Approval record has expired.")
        scope = _object(root.get("scope"), "scope")
        _only_keys(
            scope,
            {"previous_baseline_id", "current_baseline_id", "change_ids"},
            "scope",
        )
        change_ids = _string_tuple(scope.get("change_ids"), "scope.change_ids")
        if not change_ids or len(change_ids) != len(set(change_ids)):
            raise ApprovalContractError("scope.change_ids must be non-empty and unique.")
        previous_baseline_id = _string(
            scope.get("previous_baseline_id"), "scope.previous_baseline_id"
        )
        current_baseline_id = _string(
            scope.get("current_baseline_id"), "scope.current_baseline_id"
        )
        if not re.fullmatch(r"RB-[0-9A-F]{16}", previous_baseline_id):
            raise ApprovalContractError(
                "scope.previous_baseline_id must be a stable RB identifier."
            )
        if not re.fullmatch(r"RB-[0-9A-F]{16}", current_baseline_id):
            raise ApprovalContractError(
                "scope.current_baseline_id must be a stable RB identifier."
            )
        if any(not re.fullmatch(r"CHG-[0-9A-F]{12}", item) for item in change_ids):
            raise ApprovalContractError(
                "scope.change_ids must contain stable CHG identifiers."
            )
        return BaselineChangeApproval(
            approval_id=approval_id,
            previous_baseline_id=previous_baseline_id,
            current_baseline_id=current_baseline_id,
            change_ids=change_ids,
            rationale=_string(root.get("rationale"), "rationale"),
            approved_at=approved_at,
            expires_at=expires_at,
            approved_by=approved_by,
        )


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ApprovalContractError(f"{name} must be an object.")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalContractError(f"{name} must be a non-empty string.")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ApprovalContractError(f"{name} must be an array.")
    return tuple(_string(item, f"{name}[{index}]") for index, item in enumerate(value))


def _timestamp(value: object, name: str) -> str:
    text = _string(value, name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ApprovalContractError(f"{name} must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ApprovalContractError(f"{name} must include a timezone.")
    return text


def _only_keys(item: dict[str, object], expected: set[str], name: str) -> None:
    missing = expected - item.keys()
    extra = item.keys() - expected
    if missing:
        raise ApprovalContractError(f"{name} is missing {sorted(missing)[0]}.")
    if extra:
        raise ApprovalContractError(
            f"{name} contains unsupported field {sorted(extra)[0]}."
        )
