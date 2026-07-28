import io
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from typing import Any, cast

import pytest

from sdaqf.adapters.process import SubprocessRunner
from sdaqf.ports.process import ProcessTimeout


def test_subprocess_runner_captures_and_limits_both_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = subprocess.Popen
    captured: dict[str, Any] = {}

    def recording_popen(
        args: list[str],
        **kwargs: Any,
    ) -> subprocess.Popen[bytes]:
        captured["args"] = args
        captured.update(kwargs)
        return cast("subprocess.Popen[bytes]", real_popen(args, **kwargs))

    monkeypatch.setattr("subprocess.Popen", recording_popen)
    result = SubprocessRunner(timeout_seconds=2, output_limit=3).run(
        [
            sys.executable,
            "-c",
            "import sys;sys.stdout.write('abcdef');sys.stderr.write('uvwxyz')",
        ]
    )

    assert result.stdout == "abc"
    assert result.stderr == "uvw"
    assert result.stdout_truncated
    assert result.stderr_truncated
    assert captured["args"][0] == sys.executable
    assert captured["shell"] is False
    assert captured["stdin"] is subprocess.DEVNULL
    assert "env" in captured
    assert result.duration_ms >= 0


@pytest.mark.parametrize(
    ("timeout_seconds", "output_limit"),
    [(0, 1), (1, 0)],
)
def test_subprocess_runner_rejects_invalid_limits(
    timeout_seconds: float,
    output_limit: int,
) -> None:
    with pytest.raises(ValueError):
        SubprocessRunner(timeout_seconds=timeout_seconds, output_limit=output_limit)


@pytest.mark.parametrize("args", [[], [""], ["tool", ""]])
def test_subprocess_runner_rejects_invalid_arguments(args: Sequence[str]) -> None:
    with pytest.raises(ValueError, match="args"):
        SubprocessRunner().run(args)


def test_subprocess_runner_kills_timeout_and_retains_bounded_output() -> None:
    with pytest.raises(ProcessTimeout, match="timed out") as raised:
        SubprocessRunner(timeout_seconds=0.1, output_limit=8).run(
            [
                sys.executable,
                "-c",
                (
                    "import sys,time;"
                    "sys.stdout.write('before-timeout');sys.stdout.flush();"
                    "time.sleep(5)"
                ),
            ]
        )

    assert raised.value.stdout == "before-t"
    assert raised.value.stdout_truncated


def test_subprocess_runner_does_not_mark_exact_limit_as_truncated() -> None:
    result = SubprocessRunner(timeout_seconds=2, output_limit=3).run(
        [sys.executable, "-c", "print('abc', end='')"]
    )

    assert result.stdout == "abc"
    assert not result.stdout_truncated


def test_subprocess_reader_errors_are_retained_for_the_caller() -> None:
    class FailingStream(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            raise OSError("simulated reader failure")

    stream = FailingStream()
    errors: list[OSError] = []

    SubprocessRunner()._drain(
        stream,
        bytearray(),
        {"stdout": False},
        "stdout",
        errors,
    )

    assert str(errors[0]) == "simulated reader failure"
    assert stream.closed


def test_subprocess_reader_join_is_bounded() -> None:
    release = threading.Event()
    readers = (
        (threading.Thread(target=release.wait, daemon=True), "stdout"),
        (threading.Thread(target=release.wait, daemon=True), "stderr"),
    )
    for thread, _ in readers:
        thread.start()
    truncated = {"stdout": False, "stderr": False}
    started = time.perf_counter()

    complete = SubprocessRunner(timeout_seconds=0.01)._join_readers(
        readers,
        truncated,
    )
    elapsed = time.perf_counter() - started
    release.set()
    for thread, _ in readers:
        thread.join(timeout=1)

    assert not complete
    assert truncated == {"stdout": True, "stderr": True}
    assert elapsed < 0.2
