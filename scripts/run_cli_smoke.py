"""Run the exact offline M0, M1, and M2 CLI smoke contract."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from sdaqf.cli import main


def _run(label: str, args: Sequence[str], *, json_output: bool = False) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = main(args)
        except SystemExit as exc:
            result = exc.code if isinstance(exc.code, int) else 1
    if result != 0:
        raise RuntimeError(
            f"{label} failed with exit {result}: {stderr.getvalue().strip()}"
        )
    if stderr.getvalue():
        raise RuntimeError(f"{label} emitted unexpected stderr.")
    if json_output:
        json.loads(stdout.getvalue())


def main_smoke() -> int:
    """Execute every preserved and primary CLI path in one temporary directory."""

    root = Path(__file__).resolve().parents[1]
    examples = root / "examples"
    m2 = examples / "m2-orchestration"
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix=".cli-smoke-", dir=root) as raw_temp:
        temporary = Path(raw_temp)
        baseline = temporary / "baseline.json"
        os.chdir(root)
        try:
            _run("help", ["--help"])
            _run(
                "doctor",
                ["doctor", "--current-session-active", "--json"],
                json_output=True,
            )
            _run(
                "init dry run",
                ["init", str(temporary / "project"), "--dry-run", "--json"],
                json_output=True,
            )
            _run(
                "validate",
                ["validate", str(examples / "sample-project"), "--json"],
                json_output=True,
            )
            _run(
                "status",
                ["status", str(examples / "sample-project"), "--json"],
                json_output=True,
            )
            _run("goal template", ["goal-template", "M1"])
            _run(
                "canonical ingest",
                [
                    "ingest",
                    str(root / "docs" / "specification.md"),
                    "--output",
                    str(baseline),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "compare",
                ["compare", str(baseline), str(baseline), "--json"],
                json_output=True,
            )
            for command, filename in (
                ("roadmap", "roadmap.md"),
                ("exec-plan", "exec-plan.md"),
            ):
                _run(
                    command,
                    [
                        command,
                        str(baseline),
                        "M1",
                        "--output",
                        str(temporary / filename),
                    ],
                )
            for command, filename in (
                ("goal", "goal.md"),
                ("prompt", "prompt.md"),
            ):
                _run(
                    command,
                    [
                        command,
                        str(baseline),
                        "M1",
                        "--output",
                        str(temporary / filename),
                        "--json",
                    ],
                    json_output=True,
                )
            _run(
                "Gate G1",
                ["gate", "requirements", str(baseline), "--json"],
                json_output=True,
            )
            agent_registry = m2 / "agent-registry.json"
            tool_registry = m2 / "tool-registry.json"
            _run(
                "Agent Registry",
                [
                    "agents",
                    "validate",
                    str(agent_registry),
                    "--tools",
                    str(tool_registry),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "agent fallback plan",
                [
                    "agents",
                    "plan",
                    str(m2 / "orchestration-request.json"),
                    "--registry",
                    str(agent_registry),
                    "--tools",
                    str(tool_registry),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "isolated write plan",
                [
                    "agents",
                    "plan",
                    str(m2 / "write-request.json"),
                    "--registry",
                    str(agent_registry),
                    "--tools",
                    str(tool_registry),
                    "--worktree-plan",
                    str(m2 / "worktree-plan.json"),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "structured agent result",
                [
                    "agents",
                    "validate-result",
                    str(m2 / "reviewer-result.json"),
                    "--registry",
                    str(agent_registry),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "Skill and template lifecycle",
                [
                    "skills",
                    "validate",
                    str(root / ".agents" / "skills"),
                    "--templates",
                    str(m2 / "template-registry.json"),
                    "--framework-version",
                    "0.1.0",
                    "--available",
                    "independent-review",
                    "--select-skill",
                    "independent-review",
                    "--select-template",
                    "m2-agent-result",
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "Tool Registry",
                ["tools", "validate", str(tool_registry), "--json"],
                json_output=True,
            )
            _run(
                "registered Git probe",
                [
                    "tools",
                    "check",
                    str(tool_registry),
                    "--name",
                    "git",
                    "--json",
                ],
                json_output=True,
            )
            checkpoint = m2 / "execution-checkpoint.json"
            _run(
                "checkpoint",
                ["checkpoint", "validate", str(checkpoint), "--json"],
                json_output=True,
            )
            _run(
                "checkpoint resume",
                [
                    "checkpoint",
                    "resume",
                    str(checkpoint),
                    "--plan-version",
                    "1.0",
                    "--specification-digest",
                    "89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5",
                    "--git-head",
                    "eff9e3abfa6aff3e22d71b23140e838cd222832a",
                    "--worktree-digest",
                    "A" * 64,
                    "--json",
                ],
                json_output=True,
            )
        finally:
            os.chdir(previous)
    print("PASS: offline M0, M1, and M2 CLI smoke checks succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_smoke())
