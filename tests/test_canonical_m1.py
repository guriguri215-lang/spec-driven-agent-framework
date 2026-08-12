from __future__ import annotations

from pathlib import Path

from sdaqf.application.planning import PromptMode, PromptService
from sdaqf.application.requirements import SpecificationIngestor
from sdaqf.application.requirements_gate import RequirementsGateService
from sdaqf.domain.requirements import RequirementType
from tests.m1_helpers import fixed_clock


def test_canonical_specification_produces_complete_passing_m1_baseline() -> None:
    root = Path(__file__).resolve().parents[1]

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(
        root / "docs" / "specification.md"
    )

    assert baseline.source.sha256 == (
        "99C468EBC7175A5FCF4CBD036247072931AD642DFC07B8284E6B76EE968E9DEC"
    )
    assert baseline.baseline_id == "RB-99C468EBC7175A5F"
    assert len(baseline.requirements) == 228
    assert len(baseline.source_acceptance_criteria) == 23
    assert (
        sum(
            item.requirement_type is RequirementType.OPEN_DECISION
            for item in baseline.requirements
        )
        == 9
    )
    identifiers = {item.requirement_id for item in baseline.requirements}
    assert {f"FR-REQ-{number:03d}" for number in range(1, 13)} <= identifiers
    assert {f"FR-PLN-{number:03d}" for number in range(1, 11)} <= identifiers
    assert RequirementsGateService().evaluate(baseline).passed

    prompt = PromptService().render(
        baseline,
        "M1",
        requested_mode=PromptMode.GOAL,
    ).content
    assert "`FR-REQ-001`" in prompt
    assert "`FR-PLN-010`" in prompt
    for excluded in (
        "FR-AGT-001",
        "FR-TOL-001",
        "FR-QA-001",
        "FR-UI-001",
        "FR-GIT-001",
    ):
        assert f"`{excluded}`" not in prompt
