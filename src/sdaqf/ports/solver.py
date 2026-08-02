"""Application ports for bounded M7 solver execution."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.solver import (
    LoadedSolverArtifact,
    SolverAdapterDefinition,
    SolverLeaseEvidence,
)


class SolverClock(Protocol):
    """Inject wall and monotonic time for deterministic timeout tests."""

    def now(self) -> datetime:
        """Return a timezone-aware UTC instant."""

    def monotonic_milliseconds(self) -> int:
        """Return a nondecreasing local duration observation."""


class SolverAdapterPort(Protocol):
    """Execute one already-validated typed solver request."""

    def solve(
        self,
        request: LoadedSolverArtifact,
        request_reference: ArtifactReference,
        adapter: SolverAdapterDefinition,
        lease: SolverLeaseEvidence,
    ) -> LoadedSolverArtifact:
        """Return one strict Solver Result without mutating scheduler state."""


class SolverLeaseEvidencePort(Protocol):
    """Read exact M6 Lease and reservation authority without mutation."""

    def observe(
        self,
        state: Path,
        root: Path,
        *,
        graph_id: str,
        task_id: str,
        host_id: str,
        lease_id: str,
        require_current: bool,
    ) -> SolverLeaseEvidence:
        """Return one validated current or historical Lease observation."""
