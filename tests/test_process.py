import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

from sdaqf.adapters.process import SubprocessRunner


def test_subprocess_runner_captures_and_limits_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Completed:
        returncode = 0
        stdout = "abcdef"
        stderr = "uvwxyz"

    captured: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: object) -> Completed:
        captured["args"] = args
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr("subprocess.run", fake_run)
    result = SubprocessRunner(timeout_seconds=2, output_limit=3).run(["tool", "--version"])

    assert result.stdout == "abc"
    assert result.stderr == "uvw"
    assert captured["args"] == ["tool", "--version"]
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert captured["shell"] is False
    assert captured["timeout"] == 2


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


def test_subprocess_runner_normalizes_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_: object, **__: object) -> None:
        raise subprocess.TimeoutExpired("tool", 1)

    monkeypatch.setattr("subprocess.run", timeout)

    with pytest.raises(TimeoutError, match="timed out"):
        SubprocessRunner().run(["tool", "--version"])
