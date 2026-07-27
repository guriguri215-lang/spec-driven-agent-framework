from pathlib import Path

from sdaqf.application.status import StatusService
from sdaqf.application.validation import ProjectValidator


def test_invalid_project_status_is_blocked(tmp_path: Path) -> None:
    status = StatusService(ProjectValidator()).describe(tmp_path)

    assert status["state"] == "blocked"
    assert status["project"] == tmp_path.name
