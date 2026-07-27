"""Safe local subprocess adapter."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from sdaqf.ports.process import ProcessResult


class SubprocessRunner:
    """Run bounded commands without a shell."""

    def __init__(self, *, timeout_seconds: float = 5.0, output_limit: int = 4096) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if output_limit <= 0:
            raise ValueError("output_limit must be positive")
        self._timeout_seconds = timeout_seconds
        self._output_limit = output_limit

    def run(self, args: Sequence[str]) -> ProcessResult:
        """Execute a non-empty argument array and limit captured output."""

        if not args or any(not isinstance(arg, str) or not arg for arg in args):
            raise ValueError("args must contain non-empty strings")
        try:
            completed = subprocess.run(
                list(args),
                capture_output=True,
                check=False,
                encoding="utf-8",
                errors="replace",
                shell=False,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("bounded process probe timed out") from exc
        return ProcessResult(
            returncode=completed.returncode,
            stdout=completed.stdout[: self._output_limit],
            stderr=completed.stderr[: self._output_limit],
        )
