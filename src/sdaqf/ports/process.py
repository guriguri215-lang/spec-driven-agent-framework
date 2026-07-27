"""Process execution port."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Bounded subprocess result."""

    returncode: int
    stdout: str
    stderr: str


class ProcessRunner(Protocol):
    """Replaceable process execution boundary."""

    def run(self, args: Sequence[str]) -> ProcessResult:
        """Run an argument array without a shell."""
