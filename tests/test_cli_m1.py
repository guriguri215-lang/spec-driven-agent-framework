from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdaqf.cli import build_parser, main
from tests.m1_helpers import SIMPLE_SPEC


def test_help_lists_m1_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    for command in (
        "ingest",
        "compare",
        "roadmap",
        "exec-plan",
        "goal",
        "prompt",
        "gate",
    ):
        assert command in output


def test_complete_m1_cli_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("spec.md").write_text(SIMPLE_SPEC, encoding="utf-8")

    assert main(["ingest", "spec.md", "--output", "baseline.json", "--json"]) == 0
    ingested = json.loads(capsys.readouterr().out)
    assert ingested["baseline_id"].startswith("RB-")
    assert Path("baseline.json").is_file()

    assert main(["compare", "baseline.json", "baseline.json", "--json"]) == 0
    compared = json.loads(capsys.readouterr().out)
    assert compared["changes"] == []

    assert main(["roadmap", "baseline.json", "M1", "--output", "roadmap.md"]) == 0
    assert "Planning artifact created" in capsys.readouterr().out
    assert Path("roadmap.md").read_text(encoding="utf-8").startswith(
        "# Product Roadmap: M1"
    )

    assert main(["exec-plan", "baseline.json", "M1", "--output", "plan.md"]) == 0
    capsys.readouterr()
    assert "Status: active" in Path("plan.md").read_text(encoding="utf-8")

    assert main(["goal", "baseline.json", "M1", "--output", "goal.md", "--json"]) == 0
    goal_metadata = json.loads(capsys.readouterr().out)
    assert goal_metadata["selected_mode"] == "goal"
    assert "## Done when" in Path("goal.md").read_text(encoding="utf-8")

    assert (
        main(["prompt", "baseline.json", "M1", "--output", "prompt.md", "--json"])
        == 0
    )
    prompt_metadata = json.loads(capsys.readouterr().out)
    assert prompt_metadata["selected_mode"] == "standard"
    assert "## Role" in Path("prompt.md").read_text(encoding="utf-8")

    assert main(["gate", "requirements", "baseline.json", "--json"]) == 0
    gate = json.loads(capsys.readouterr().out)
    assert gate["gate_id"] == "G1"
    assert gate["passed"] is True


def test_cli_refuses_overwrite_and_preserves_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("spec.md").write_text(SIMPLE_SPEC, encoding="utf-8")
    Path("baseline.json").write_text("existing", encoding="utf-8")

    assert main(["ingest", "spec.md", "--output", "baseline.json"]) == 2
    assert "without creating output" in capsys.readouterr().err
    assert Path("baseline.json").read_text(encoding="utf-8") == "existing"


def test_cli_rejects_invalid_baseline_without_disclosing_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("invalid.json").write_text("{}", encoding="utf-8")

    assert main(["gate", "requirements", "invalid.json"]) == 2
    error = capsys.readouterr().err
    assert "input is invalid" in error
    assert str(tmp_path) not in error


def test_goal_cli_reports_standard_fallback_for_multiple_objectives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("spec.md").write_text(SIMPLE_SPEC, encoding="utf-8")
    assert main(["ingest", "spec.md", "--output", "baseline.json"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "prompt",
                "baseline.json",
                "M1",
                "--mode",
                "goal",
                "--objective",
                "intake",
                "--objective",
                "planning",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["requested_mode"] == "goal"
    assert payload["selected_mode"] == "standard"


def test_cli_requires_structured_owner_approval_for_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("previous.md").write_text(
        """# Contract
## Functional requirements
- `FR-REQ-001`: The app validates input.
- `FR-REQ-002`: The app stores input.
""",
        encoding="utf-8",
    )
    Path("current.md").write_text(
        """# Contract
## Functional requirements
- `FR-REQ-001`: The app validates input.
""",
        encoding="utf-8",
    )
    assert main(["ingest", "previous.md", "--output", "previous.json"]) == 0
    capsys.readouterr()
    assert main(["ingest", "current.md", "--output", "current.json"]) == 0
    capsys.readouterr()
    assert main(["compare", "previous.json", "current.json", "--json"]) == 0
    comparison = json.loads(capsys.readouterr().out)
    assert len(comparison["unresolved_approvals"]) == 1

    approval = {
        "schema_version": "1.0",
        "approval_id": "APR-CLI-001",
        "approval_type": "owner",
        "action": "Approve requirement baseline changes",
        "scope": {
            "previous_baseline_id": comparison["previous_baseline_id"],
            "current_baseline_id": comparison["current_baseline_id"],
            "change_ids": comparison["unresolved_approvals"],
        },
        "risk": "high",
        "status": "approved",
        "rationale": "The Owner explicitly approves the synthetic removal.",
        "reversible": True,
        "approved_by": "Owner",
        "approved_at": "2026-07-27T12:00:00+00:00",
        "expires_at": None,
    }
    Path("approval.json").write_text(json.dumps(approval), encoding="utf-8")

    assert (
        main(
            [
                "compare",
                "previous.json",
                "current.json",
                "--approval",
                "approval.json",
                "--json",
            ]
        )
        == 0
    )
    approved = json.loads(capsys.readouterr().out)
    assert approved["unresolved_approvals"] == []

    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "compare",
                "previous.json",
                "current.json",
                "--approve",
                comparison["unresolved_approvals"][0],
            ]
        )
