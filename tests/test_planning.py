from __future__ import annotations

from pathlib import Path

import pytest

from sdaqf.application.planning import PlanningService
from tests.m1_helpers import ingest_spec


def test_roadmap_has_separate_milestone_contract_sections(tmp_path: Path) -> None:
    roadmap = PlanningService().render_roadmap(ingest_spec(tmp_path), "M1")

    for heading in (
        "## Objective",
        "## Scope",
        "## Exclusions",
        "## Dependencies",
        "## Risks",
        "## Completion criteria",
        "## Stop conditions",
    ):
        assert heading in roadmap
    assert "Release Contract" in roadmap
    assert "orchestration" in roadmap


def test_exec_plan_is_living_and_has_complete_execution_contract(
    tmp_path: Path,
) -> None:
    plan = PlanningService().render_exec_plan(ingest_spec(tmp_path), "M1")

    for heading in (
        "## Objective",
        "## Scope and non-goals",
        "## Source requirements and acceptance criteria",
        "## Dependencies, risks, and assumptions",
        "## Checkpoints",
        "## Validation commands",
        "## Stop conditions",
        "## Technical sandbox handling",
        "## Owner approval gates",
        "## Language and publication boundary",
        "## Decision log",
        "## Progress log",
    ):
        assert heading in plan
    assert "Status: active" in plan
    assert "python -m pytest" in plan
    assert "python -m sdaqf gate requirements <baseline.json> --json" in plan
    assert "src/sdaqf/application/requirements_gate.py --fail-under=90" in plan


@pytest.mark.parametrize("milestone", ("", "../M1", "M1 and M2"))
def test_planning_rejects_unsafe_milestone(tmp_path: Path, milestone: str) -> None:
    with pytest.raises(ValueError, match="safe ASCII"):
        PlanningService().render_roadmap(ingest_spec(tmp_path), milestone)
