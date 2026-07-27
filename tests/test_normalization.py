from __future__ import annotations

from pathlib import Path

from sdaqf.application.requirements import SpecificationIngestor
from sdaqf.domain.requirements import RequirementPriority, RequirementType
from tests.m1_helpers import fixed_clock, write_spec


def test_normalization_distinguishes_all_types_and_priorities(tmp_path: Path) -> None:
    text = """# Contract

## Functional requirements
- `FR-APP-001`: The app must save records.

## Non-functional requirements
- `NFR-001`: The app `SHOULD` finish within two seconds.

## Constraints
- `C-001`: The core `MAY` use an optional cache.

## Non-goals
- `NG-001`: The product must not replace human judgment.

## Assumptions
- The clock is monotonic.

## Open decisions
1. Decide the retention period.
"""
    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))
    by_type = {item.requirement_type: item for item in baseline.requirements}

    assert set(by_type) == set(RequirementType)
    assert by_type[RequirementType.FUNCTIONAL].priority is RequirementPriority.MUST
    assert by_type[RequirementType.NONFUNCTIONAL].priority is RequirementPriority.SHOULD
    assert by_type[RequirementType.CONSTRAINT].priority is RequirementPriority.COULD
    assert by_type[RequirementType.ASSUMPTION].assumptions == ("The clock is monotonic.",)
    assert by_type[RequirementType.OPEN_DECISION].open_questions == (
        "Decide the retention period.",
    )


def test_priority_normalization_is_case_insensitive(tmp_path: Path) -> None:
    text = """# Contract
## Functional requirements
- `FR-APP-001`: The app should retain records.
- `FR-APP-002`: The app CoUlD export records.
- `FR-APP-003`: The app may archive records.
- `FR-APP-004`: The app must validate records.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))
    priorities = {
        item.requirement_id: item.priority for item in baseline.requirements
    }

    assert priorities == {
        "FR-APP-001": RequirementPriority.SHOULD,
        "FR-APP-002": RequirementPriority.COULD,
        "FR-APP-003": RequirementPriority.COULD,
        "FR-APP-004": RequirementPriority.MUST,
    }


def test_generated_identifiers_are_stable_across_reordering(tmp_path: Path) -> None:
    first = """# Contract
## Assumptions
- The clock is monotonic.
- Storage is local.
"""
    second = """# Contract
## Assumptions
- Storage is local.
- The clock is monotonic.
"""

    first_baseline = SpecificationIngestor(clock=fixed_clock).ingest(
        write_spec(tmp_path, first, "first.md")
    )
    second_baseline = SpecificationIngestor(clock=fixed_clock).ingest(
        write_spec(tmp_path, second, "second.md")
    )

    first_map = {item.statement: item.requirement_id for item in first_baseline.requirements}
    second_map = {item.statement: item.requirement_id for item in second_baseline.requirements}
    assert first_map == second_map
    assert all(identifier.startswith("ASM-AUTO-") for identifier in first_map.values())


def test_acceptance_and_complete_traceability_are_generated(tmp_path: Path) -> None:
    text = """# Contract
## Functional requirements
- `FR-APP-001`: The command validates input.
- `AC-FR-APP-001-01`: Invalid input returns a non-zero exit code.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))
    requirement = baseline.requirements[0]

    assert requirement.acceptance_criteria[0].criterion_id == "AC-FR-APP-001-01"
    assert requirement.verification_methods == ("test",)
    assert requirement.source.document == "spec.md"
    assert requirement.source.section.endswith("Functional requirements")
    assert requirement.source.line_start == 3
    assert requirement.source.line_end == 3
    assert requirement.source.excerpt.startswith("- `FR-APP-001`")
    assert requirement.source.derivation_basis
    assert requirement.trace_links.to_dict() == {
        "design": [],
        "code": [],
        "tests": [],
        "evidence": [],
        "releases": [],
    }
    assert requirement.status == "baselined"


def test_explicit_records_do_not_require_bullet_markers(tmp_path: Path) -> None:
    text = """# Contract
## Requirement
`FR-APP-001`: The command validates input.

## Acceptance criterion
`AC-FR-APP-001-01`: Invalid input returns a non-zero exit code.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))

    assert len(baseline.requirements) == 1
    assert (
        baseline.requirements[0].acceptance_criteria[0].criterion_id
        == "AC-FR-APP-001-01"
    )


def test_open_decision_prose_list_is_split_into_stable_records(
    tmp_path: Path,
) -> None:
    text = """# Contract
## Open decisions
The Owner must decide the public name, license, and whether a UI is desired.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))

    assert len(baseline.requirements) == 3
    assert all(
        item.requirement_type is RequirementType.OPEN_DECISION
        for item in baseline.requirements
    )
    assert {item.statement for item in baseline.requirements} == {
        "Decide the public name.",
        "Decide license.",
        "Decide whether a UI is desired.",
    }
    assert all(item.open_questions for item in baseline.requirements)


def test_explicit_duplicate_statements_preserve_both_identifiers(
    tmp_path: Path,
) -> None:
    text = """# Contract
## Functional requirements
- `FR-APP-001`: The command validates input.
- `FR-APP-002`: The command validates input.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))

    assert {item.requirement_id for item in baseline.requirements} == {
        "FR-APP-001",
        "FR-APP-002",
    }
    assert any(item.kind.value == "duplicate-statement" for item in baseline.diagnostics)
