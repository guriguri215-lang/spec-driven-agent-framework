"""Ports for durable host-agnostic M6 scheduling."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from sdaqf.domain.scheduler import MailboxMessage


class SchedulerClock(Protocol):
    """Inject a timezone-aware UTC clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC instant."""


class SchedulerArtifactStorePort(Protocol):
    """Exclusively publish one immutable JSON artifact."""

    def publish(self, output: Path, content: bytes) -> None:
        """Create output without replacing an existing path."""


class SchedulerStorePort(Protocol):
    """Transactional durable scheduler state boundary."""

    @property
    def path(self) -> Path:
        """Return the explicit database path."""

    def validate(self) -> None:
        """Validate version, shape, audit chain, and projections."""


class AgentHostPort(Protocol):
    """Host-owned agent dispatch boundary."""

    def dispatch(self, message: MailboxMessage) -> None:
        """Offer a validated dispatch intent to the host."""

    def cancel(self, message: MailboxMessage) -> None:
        """Offer a cooperative cancellation request to the host."""


class WorktreeHostPort(Protocol):
    """Host-owned worktree lifecycle boundary."""

    def request(self, message: MailboxMessage) -> None:
        """Offer a validated worktree intent to the host."""
