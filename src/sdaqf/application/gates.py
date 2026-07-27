"""Deterministic quality gate evaluation."""

from __future__ import annotations

from collections.abc import Iterable

from sdaqf.domain.models import GateCheck, GateResult


class GateEngine:
    """Evaluate explicit checks without score-based compensation."""

    def evaluate(self, gate_id: str, checks: Iterable[GateCheck]) -> GateResult:
        """Build a gate result from a non-empty, uniquely identified check set."""

        normalized = tuple(checks)
        if not gate_id.strip():
            raise ValueError("gate_id must not be empty")
        if not normalized:
            raise ValueError("at least one check is required")
        check_ids = [check.check_id for check in normalized]
        if any(not check_id.strip() for check_id in check_ids):
            raise ValueError("check identifiers must not be empty")
        if len(set(check_ids)) != len(check_ids):
            raise ValueError("check identifiers must be unique")
        return GateResult(gate_id=gate_id, checks=normalized)
