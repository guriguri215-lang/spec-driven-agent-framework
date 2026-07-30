import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sdaqf.cli import main
from tests.m2_helpers import (
    load_example,
    m2_example,
    repository_root,
    write_json,
)


def test_agent_validation_plan_and_result_cli(capsys: object) -> None:
    root = m2_example("agent-registry.json")
    tools = m2_example("tool-registry.json")

    assert main(["agents", "validate", str(root), "--tools", str(tools), "--json"]) == 0
    assert main(
        [
            "agents",
            "plan",
            str(m2_example("orchestration-request.json")),
            "--registry",
            str(root),
            "--tools",
            str(tools),
            "--json",
        ]
    ) == 0
    assert main(
        [
            "agents",
            "validate-result",
            str(m2_example("reviewer-result.json")),
            "--registry",
            str(root),
            "--json",
        ]
    ) == 0

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert '"tool_references": "valid"' in output
    assert '"execution_mode": "independent_session"' in output
    assert '"role_id": "independent-reviewer"' in output


def test_isolated_write_plan_cli(capsys: object) -> None:
    result = main(
        [
            "agents",
            "plan",
            str(m2_example("write-request.json")),
            "--registry",
            str(m2_example("agent-registry.json")),
            "--tools",
            str(m2_example("tool-registry.json")),
            "--worktree-plan",
            str(m2_example("worktree-plan.json")),
            "--json",
        ]
    )

    output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert result == 0
    assert output["effective_concurrency"] == 2
    assert output["worktree_plan"]["integrator_role"] == "integrator"


def test_skill_tool_and_checkpoint_cli(capsys: object) -> None:
    assert main(
        [
            "skills",
            "validate",
            str(repository_root() / ".agents" / "skills"),
            "--templates",
            str(m2_example("template-registry.json")),
            "--framework-version",
            "1.0.0",
            "--available",
            "independent-review",
            "--select-skill",
            "independent-review",
            "--select-template",
            "m2-agent-result",
            "--json",
        ]
    ) == 0
    assert main(
        [
            "tools",
            "validate",
            str(m2_example("tool-registry.json")),
            "--json",
        ]
    ) == 0
    assert main(
        [
            "checkpoint",
            "validate",
            str(m2_example("execution-checkpoint.json")),
            "--json",
        ]
    ) == 0
    assert main(
        [
            "checkpoint",
            "resume",
            str(m2_example("execution-checkpoint.json")),
            "--plan-version",
            "1.0",
            "--specification-digest",
            "89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5",
            "--git-head",
            "eff9e3abfa6aff3e22d71b23140e838cd222832a",
            "--worktree-digest",
            "A" * 64,
            "--json",
        ]
    ) == 0

    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert '"state": "selected"' in output
    assert '"tools": [' in output
    assert '"checkpoint_id": "CHK-0123456789ABCDEF"' in output


def test_m2_cli_rejects_invalid_input_without_disclosing_path(
    tmp_path: object,
    capsys: object,
) -> None:
    invalid = tmp_path / "invalid.json"  # type: ignore[operator]
    invalid.write_text("{}", encoding="utf-8")

    result = main(
        [
            "agents",
            "plan",
            str(invalid),
            "--registry",
            str(m2_example("agent-registry.json")),
            "--tools",
            str(m2_example("tool-registry.json")),
            "--json",
        ]
    )

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert result == 2
    assert str(invalid) not in captured.err
    assert captured.out == ""


def test_tool_cli_rejects_unvalidated_approval(
    tmp_path: Path,
    capsys: object,
) -> None:
    approval = tmp_path / "approval.json"
    approval.write_text("{}", encoding="utf-8")

    result = main(
        [
            "tools",
            "check",
            str(m2_example("tool-registry.json")),
            "--name",
            "python",
            "--approval",
            str(approval),
            "--json",
        ]
    )

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert result == 2
    assert captured.out == ""
    assert str(approval) not in captured.err


def test_tool_cli_persistently_consumes_single_execution_approval(
    tmp_path: Path,
    capsys: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_payload = load_example("tool-registry.json")
    tools = registry_payload["tools"]
    assert isinstance(tools, list)
    git_tool = tools[0]
    assert isinstance(git_tool, dict)
    git_tool["owner_approval"] = "required"
    (tmp_path / ".git").mkdir()
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    registry = write_json(contracts / "tools.json", registry_payload)
    now = datetime.now(UTC)
    approval = write_json(
        tmp_path / "approval.json",
        {
            "schema_version": "1.0",
            "approval_id": "APR-CLI-M2-0001",
            "approval_type": "owner",
            "action": "Execute one registered tool version probe",
            "scope": {
                "tool_name": git_tool["name"],
                "command": git_tool["version_command"],
                "normal_scope": git_tool["normal_scope"],
                "protected_paths": git_tool["protected_paths"],
                "network_destinations": git_tool["network"]["destinations"],
            },
            "risk": git_tool["risk"],
            "status": "approved",
            "rationale": "Permit one exact CLI version probe.",
            "reversible": True,
            "approved_by": "Owner",
            "approved_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "lifetime": "single_execution",
            "conditions": {
                "execution": "version_probe",
                "max_executions": 1,
            },
        },
    )
    first_cwd = tmp_path / "first-cwd"
    second_cwd = tmp_path / "second-cwd"
    first_cwd.mkdir()
    second_cwd.mkdir()
    monkeypatch.chdir(first_cwd)
    command = [
        "tools",
        "check",
        str(registry),
        "--name",
        "git",
        "--approval",
        str(approval),
        "--json",
    ]

    first = main(command)
    first_output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    monkeypatch.chdir(second_cwd)
    second = main(command)
    second_output = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    assert first == 0
    assert first_output["status"] == "AVAILABLE"
    assert second == 2
    assert second_output["status"] == "BLOCKED"
    assert "already consumed" in second_output["detail"]
    assert (
        tmp_path / ".sdaqf" / "execution-approval-consumption.json"
    ).is_file()
    assert not (first_cwd / ".sdaqf").exists()
    assert not (second_cwd / ".sdaqf").exists()
