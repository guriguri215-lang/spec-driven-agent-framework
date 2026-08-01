"""Injected boundaries for the M5 Context Framework."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from sdaqf.domain.context import SourceLocator
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity


class ContextSourceError(RuntimeError):
    """A source, provenance, or candidate observation failed closed."""


@dataclass(frozen=True, slots=True)
class ObservedContextSource:
    """One stable bounded source observation."""

    content: bytes
    text: str
    selected_text: str
    sha256: str


class ContextSourceReader(Protocol):
    """Read only an explicitly located bounded source."""

    def observe(self, root: Path, locator: SourceLocator) -> ObservedContextSource:
        """Return a stable source observation or fail closed."""

    def verify_reference(self, root: Path, reference: ArtifactReference) -> None:
        """Verify one bounded provenance reference under an explicit root."""


class ContextCandidateVerifier(Protocol):
    """Verify an exact locally observed repository candidate."""

    def verify(self, repository_root: Path, expected: CandidateIdentity) -> None:
        """Fail unless the current publication candidate exactly matches."""


class ContextClock(Protocol):
    """UTC clock used only for authoring explicit time-bearing input."""

    def now(self) -> datetime:
        """Return a timezone-aware current UTC value."""


class BudgetEstimator(Protocol):
    """Portable exact context-cost boundary."""

    def cost(self, content: object) -> int:
        """Return a nonnegative deterministic cost."""


class ImmutableJSONPublisher(Protocol):
    """Exclusive publication boundary for immutable JSON."""

    def publish(self, target: Path, content: bytes) -> None:
        """Publish a fresh target without overwriting existing content."""
