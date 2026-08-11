"""Ports for deterministic host-agnostic M8 workflow integration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from sdaqf.domain.quality import ArtifactReference, CandidateIdentity
from sdaqf.domain.workflow import (
    NativeArtifactBinding,
    WorkflowPublicationObservation,
)


class WorkflowClock(Protocol):
    """Inject a timezone-aware UTC clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC instant."""


class WorkflowArtifactStorePort(Protocol):
    """Load exact artifacts/chains and exclusively publish immutable JSON."""

    def load(self, reference: ArtifactReference, maximum_bytes: int) -> bytes:
        """Return exact root-confined bytes after digest and regular-file checks."""

    def read_event_chain(
        self,
        bindings: tuple[NativeArtifactBinding, ...],
        maximum_events: int,
    ) -> tuple[bytes, ...]:
        """Return the complete explicitly referenced Event chain in order."""

    def publish(self, output: Path, content: bytes) -> None:
        """Create output without replacing any existing path."""

    def publish_idempotent(
        self,
        output: Path,
        content: bytes,
        *,
        artifact_type: str,
        artifact_id: str,
    ) -> None:
        """Publish once or accept the same canonical artifact on exact retry."""


class WorkflowPublicationVerifier(Protocol):
    """Build and revalidate one pinned Git-plus-M6 publication observation."""

    def observe(
        self,
        repository_root: Path,
        expected: CandidateIdentity,
        *,
        scheduler_state: Path,
        plan_id: str | None = None,
    ) -> WorkflowPublicationObservation:
        """Return one validated immutable observation."""

    def revalidate(
        self,
        repository_root: Path,
        observation: WorkflowPublicationObservation,
        *,
        scheduler_state: Path,
    ) -> None:
        """Reject Git or M6 head drift from the pinned observation."""
