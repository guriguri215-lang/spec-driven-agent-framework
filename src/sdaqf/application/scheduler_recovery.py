"""Evidence-preserving M6 scheduler recovery."""

from __future__ import annotations

from pathlib import Path

from sdaqf.adapters.scheduler import recover_scheduler_database
from sdaqf.application.scheduler_contracts import LoadedSchedulerArtifact


class SchedulerRecoveryService:
    """Recover a validated scheduler only to a fresh output."""

    def recover(
        self,
        source: Path,
        root: Path,
        output: Path,
    ) -> LoadedSchedulerArtifact:
        """Return the evidence-equivalent recovered state projection."""

        return recover_scheduler_database(source, output, root).status()
