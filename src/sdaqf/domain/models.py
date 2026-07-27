"""Core immutable models used by the M0 application services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ToolStatus(StrEnum):
    """Observed state of a local tool capability."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_CHECKED = "NOT_CHECKED"


@dataclass(frozen=True, slots=True)
class ToolCapability:
    """Result of one bounded capability probe."""

    name: str
    status: ToolStatus
    detail: str
    version: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Return a JSON-compatible representation."""

        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class GateCheck:
    """One deterministic gate check."""

    check_id: str
    passed: bool
    hard_blocker: bool
    evidence: str


@dataclass(frozen=True, slots=True)
class GateResult:
    """Aggregate result that never allows a hard blocker to be scored away."""

    gate_id: str
    checks: tuple[GateCheck, ...]

    @property
    def passed(self) -> bool:
        """Return true only when every check passes."""

        return bool(self.checks) and all(check.passed for check in self.checks)

    @property
    def hard_blockers(self) -> tuple[str, ...]:
        """Return failed hard-blocker identifiers."""

        return tuple(
            check.check_id
            for check in self.checks
            if check.hard_blocker and not check.passed
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""

        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "hard_blockers": list(self.hard_blockers),
            "checks": [
                {
                    "check_id": check.check_id,
                    "passed": check.passed,
                    "hard_blocker": check.hard_blocker,
                    "evidence": check.evidence,
                }
                for check in self.checks
            ],
        }
