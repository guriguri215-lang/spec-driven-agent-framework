import json
from pathlib import Path

import pytest

from sdaqf.cli import _write_new_file, build_parser, main


def sample_project() -> Path:
    return Path(__file__).resolve().parents[1] / "examples" / "sample-project"


def test_help_lists_vertical_slice(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    for command in ("doctor", "init", "validate", "status", "goal-template"):
        assert command in output


def test_validate_and_status_emit_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(sample_project()), "--json"]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["valid"] is True

    assert main(["status", str(sample_project()), "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "ready"


def test_doctor_emits_current_session_without_nested_codex(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["doctor", "--current-session-active", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    by_name = {item["name"]: item for item in payload["capabilities"]}

    assert by_name["codex-current-session"]["detail"] == "CURRENT_SESSION_ACTIVE"
    assert by_name["codex-external-cli"]["status"] == "NOT_CHECKED"


def test_dry_run_init_does_not_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "project"

    assert main(["init", str(target), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["safe"] is True
    assert not target.exists()


def test_init_writes_new_state_and_is_idempotent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "project"

    assert main(["init", str(target), "--json"]) == 0
    capsys.readouterr()
    assert main(["init", str(target), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["would_create"] == []


def test_goal_template_can_print_or_create_new_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["goal-template", "M1"]) == 0
    assert "## Objective" in capsys.readouterr().out

    output = tmp_path / "goal.md"
    assert main(["goal-template", "M1", "--output", str(output)]) == 0
    assert output.read_text(encoding="utf-8").startswith("# Goal: M1")


def test_write_new_file_refuses_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "existing"
    path.write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError, match="existing"):
        _write_new_file(path, "new")


def test_cli_rejects_writes_outside_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.chdir(allowed)

    assert main(["init", str(tmp_path / "outside"), "--json"]) == 2
    assert main(
        ["goal-template", "M1", "--output", str(tmp_path / "outside.md")]
    ) == 2
    assert "not created" in capsys.readouterr().err


def test_cli_rejects_unsafe_milestone(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["goal-template", "../M1"]) == 2
    assert "safe ASCII" in capsys.readouterr().err
