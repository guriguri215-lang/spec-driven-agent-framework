from pathlib import Path

from sdaqf.application.status import StatusService
from sdaqf.application.validation import ProjectValidator


def test_invalid_project_status_is_blocked(tmp_path: Path) -> None:
    status = StatusService(ProjectValidator()).describe(tmp_path)

    assert status["state"] == "blocked"
    assert status["project"] == tmp_path.name


def test_valid_project_reports_m1_scope_and_m2_next() -> None:
    project = Path(__file__).resolve().parents[1] / "examples" / "sample-project"

    status = StatusService(ProjectValidator()).describe(project)

    assert status["state"] == "ready"
    assert "M1 Requirements and Planning MVP" in str(status["implemented_scope"])
    assert status["next_milestone"] == "M2 Agent, Skill, and Tool Orchestration"
