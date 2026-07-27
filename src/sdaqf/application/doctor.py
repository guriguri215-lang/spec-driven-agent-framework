"""Local capability diagnosis with explicit denial classification."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable, Sequence

from sdaqf.domain.models import ToolCapability, ToolStatus
from sdaqf.ports.process import ProcessRunner

Locator = Callable[[str], str | None]

_DENIAL_MARKERS = (
    "access is denied",
    "permission denied",
    "operation not permitted",
    "winerror 5",
)


class DoctorService:
    """Probe safe local capabilities without launching a nested Codex CLI."""

    def __init__(
        self,
        runner: ProcessRunner,
        *,
        locator: Locator = shutil.which,
        python_executable: str = sys.executable,
    ) -> None:
        self._runner = runner
        self._locator = locator
        self._python_executable = python_executable

    def inspect(self, *, current_session_active: bool = False) -> tuple[ToolCapability, ...]:
        """Return a stable capability report."""

        session = ToolCapability(
            name="codex-current-session",
            status=ToolStatus.AVAILABLE if current_session_active else ToolStatus.NOT_CHECKED,
            detail=(
                "CURRENT_SESSION_ACTIVE"
                if current_session_active
                else "Session state was not asserted by the caller."
            ),
        )
        nested_codex = ToolCapability(
            name="codex-external-cli",
            status=ToolStatus.NOT_CHECKED,
            detail="NOT_CHECKED_NONBLOCKING: nested Codex execution is disabled by policy.",
        )
        browser = ToolCapability(
            name="browser",
            status=ToolStatus.NOT_CHECKED,
            detail="Optional browser capability is not probed by the offline doctor.",
        )
        return (
            session,
            self._probe(
                "python",
                (self._python_executable, "--version"),
                executable=self._python_executable,
            ),
            self._probe("git", ("git", "--version")),
            nested_codex,
            self._probe("github-cli", ("gh", "--version")),
            self._probe("node", ("node", "--version")),
            browser,
        )

    def _probe(
        self,
        name: str,
        args: Sequence[str],
        *,
        executable: str | None = None,
    ) -> ToolCapability:
        candidate = executable or self._locator(args[0])
        if candidate is None:
            return ToolCapability(
                name=name,
                status=ToolStatus.UNAVAILABLE,
                detail="Executable was not found.",
            )
        try:
            result = self._runner.run(args)
        except FileNotFoundError:
            return ToolCapability(
                name=name,
                status=ToolStatus.UNAVAILABLE,
                detail="Executable was not found.",
            )
        except PermissionError:
            return ToolCapability(
                name=name,
                status=ToolStatus.PERMISSION_DENIED,
                detail="The executable or probe was denied.",
            )
        except TimeoutError:
            return ToolCapability(
                name=name,
                status=ToolStatus.UNAVAILABLE,
                detail="The bounded probe timed out.",
            )
        except OSError:
            return ToolCapability(
                name=name,
                status=ToolStatus.UNAVAILABLE,
                detail="The executable resolved, but the operating system could not run it.",
            )

        output = " ".join((result.stdout, result.stderr)).strip()
        if result.returncode == 0:
            version = output.splitlines()[0] if output else None
            return ToolCapability(
                name=name,
                status=ToolStatus.AVAILABLE,
                detail="Safe version probe succeeded.",
                version=version,
            )
        if any(marker in output.casefold() for marker in _DENIAL_MARKERS):
            return ToolCapability(
                name=name,
                status=ToolStatus.PERMISSION_DENIED,
                detail="The executable resolved, but the probe was denied.",
            )
        return ToolCapability(
            name=name,
            status=ToolStatus.UNAVAILABLE,
            detail=f"Version probe failed with exit code {result.returncode}.",
        )
