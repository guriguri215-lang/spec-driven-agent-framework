"""Safe local subprocess adapter with truly bounded stream capture."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Sequence
from typing import BinaryIO

from sdaqf.ports.process import ProcessResult, ProcessTimeout

_SAFE_ENVIRONMENT = (
    "LANG",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TMP",
    "TEMP",
    "WINDIR",
)


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
        """Execute an argument array while draining both streams within limits."""

        if not args or any(not isinstance(arg, str) or not arg for arg in args):
            raise ValueError("args must contain non-empty strings")
        environment = {
            name: value
            for name in _SAFE_ENVIRONMENT
            if (value := os.environ.get(name)) is not None
        }
        environment["PYTHONIOENCODING"] = "utf-8"
        started = time.perf_counter()
        process = subprocess.Popen(
            list(args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=environment,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stdout = bytearray()
        stderr = bytearray()
        truncated = {"stdout": False, "stderr": False}
        reader_errors: list[OSError] = []
        stdout_thread = threading.Thread(
            target=self._drain,
            args=(process.stdout, stdout, truncated, "stdout", reader_errors),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._drain,
            args=(process.stderr, stderr, truncated, "stderr", reader_errors),
            daemon=True,
        )
        readers = (
            (stdout_thread, "stdout"),
            (stderr_thread, "stderr"),
        )
        stdout_thread.start()
        stderr_thread.start()
        try:
            returncode = process.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            self._join_readers(readers, truncated)
            raise ProcessTimeout(
                "bounded process probe timed out",
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                stdout_truncated=truncated["stdout"],
                stderr_truncated=truncated["stderr"],
                duration_ms=max(
                    0,
                    round((time.perf_counter() - started) * 1000),
                ),
            ) from None
        if not self._join_readers(readers, truncated):
            raise TimeoutError("bounded process stream drain timed out")
        if reader_errors:
            raise reader_errors[0]
        return ProcessResult(
            returncode=returncode,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            stdout_truncated=truncated["stdout"],
            stderr_truncated=truncated["stderr"],
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
        )

    def _join_readers(
        self,
        readers: tuple[
            tuple[threading.Thread, str],
            tuple[threading.Thread, str],
        ],
        truncated: dict[str, bool],
    ) -> bool:
        deadline = time.perf_counter() + min(1.0, self._timeout_seconds)
        complete = True
        for thread, name in readers:
            thread.join(max(0.0, deadline - time.perf_counter()))
            if thread.is_alive():
                truncated[name] = True
                complete = False
        return complete

    def _drain(
        self,
        stream: BinaryIO,
        retained: bytearray,
        truncated: dict[str, bool],
        name: str,
        errors: list[OSError],
    ) -> None:
        try:
            while chunk := stream.read(4096):
                remaining = self._output_limit - len(retained)
                if remaining > 0:
                    retained.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated[name] = True
        except OSError as exc:
            errors.append(exc)
        finally:
            stream.close()
