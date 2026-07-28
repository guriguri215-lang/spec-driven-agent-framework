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
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    duration_ms: int = 0


class ProcessTimeout(TimeoutError):
    """Timeout with already bounded output retained."""

    def __init__(
        self,
        message: str,
        *,
        stdout: str,
        stderr: str,
        stdout_truncated: bool,
        stderr_truncated: bool,
        duration_ms: int = 0,
    ) -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr
        self.stdout_truncated = stdout_truncated
        self.stderr_truncated = stderr_truncated
        self.duration_ms = duration_ms


class ProcessRunner(Protocol):
    """Replaceable process execution boundary."""

    def run(self, args: Sequence[str]) -> ProcessResult:
        """Run an argument array without a shell."""
