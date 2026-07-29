"""Project status reporting."""

from __future__ import annotations

from pathlib import Path

from sdaqf.application.validation import ProjectValidator


class StatusService:
    """Describe a local project without exposing an absolute path."""

    def __init__(self, validator: ProjectValidator) -> None:
        self._validator = validator

    def describe(self, project_dir: Path) -> dict[str, object]:
        """Return validation and implementation state."""

        report = self._validator.validate(project_dir)
        return {
            "project": project_dir.name,
            "state": "ready" if report.valid else "blocked",
            "validation": report.to_dict(),
            "implemented_scope": (
                "M0 Bootstrap Foundation, M1 Requirements and Planning MVP, "
                "M2 Agent, Skill, and Tool Orchestration, and "
                "M3 Evidence, UI/UX, and Release QA"
            ),
            "next_milestone": "M4 Public Beta Hardening",
        }
