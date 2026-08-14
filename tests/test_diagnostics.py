from __future__ import annotations

from pathlib import Path

import pytest

from sdaqf.application.requirements import SpecificationIngestor
from tests.m1_helpers import fixed_clock, write_spec


def test_diagnostics_cover_ambiguity_assumption_and_unverifiable_language(
    tmp_path: Path,
) -> None:
    text = """# Contract
## Functional requirements
- `FR-APP-001`: The app must be user-friendly.
- `FR-APP-002`: The app must save a snapshot when practical.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))
    diagnostics = {(item.kind.value, item.severity.value) for item in baseline.diagnostics}

    assert ("unverifiable", "blocker") in diagnostics
    assert ("ambiguity", "warning") in diagnostics
    assert ("missing-assumption", "info") in diagnostics


def test_conflicting_polarity_is_a_blocking_contradiction(tmp_path: Path) -> None:
    text = """# Contract
## Functional requirements
- `FR-APP-001`: The app must retain records.
- `FR-APP-002`: The app must not retain records.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))

    contradictions = [
        item for item in baseline.diagnostics if item.kind.value == "contradiction"
    ]
    assert len(contradictions) == 1
    assert contradictions[0].severity.value == "blocker"
    assert contradictions[0].requirement_ids == ("FR-APP-001", "FR-APP-002")


def test_duplicate_identifier_is_never_silently_adopted(tmp_path: Path) -> None:
    text = """# Contract
## Functional requirements
- `FR-APP-001`: The app must retain records.
- `FR-APP-001`: The app must not retain records.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))

    assert len(baseline.requirements) == 1
    kinds = {item.kind.value for item in baseline.diagnostics}
    assert {"duplicate-identifier", "contradiction"} <= kinds


@pytest.mark.parametrize(
    "statement",
    (
        "Rotate the audit key every day.",
        "Encrypt audit records at rest.",
        "Do not log access tokens.",
    ),
)
def test_unstructured_requirement_prose_is_a_blocker_not_silently_dropped(
    tmp_path: Path,
    statement: str,
) -> None:
    text = f"""# Contract

## Security requirements
{statement}

## Functional requirements
- `FR-APP-001`: The app must retain records.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))

    diagnostic = next(
        item
        for item in baseline.diagnostics
        if item.message == "A normative statement was not recognized as a requirement."
    )
    assert diagnostic.kind.value == "unverifiable"
    assert diagnostic.severity.value == "blocker"
    assert diagnostic.requirement_ids == ()
    assert diagnostic.line_start == 4


def test_objective_prose_and_fenced_normative_examples_are_not_blocked(
    tmp_path: Path,
) -> None:
    text = """# Contract

The introduction says operators must understand the project context.

## Security requirements
This section describes background context for operators.

## Examples
```text
The service must do something illustrative.
```

## Functional requirements
- `FR-APP-001`: The app must retain records.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))

    assert not any(
        item.message == "A normative statement was not recognized as a requirement."
        for item in baseline.diagnostics
    )


def test_malformed_stable_identifier_is_a_blocker(tmp_path: Path) -> None:
    text = """# Contract

## Functional requirements
- FR-APP-001: The app must retain records.
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))

    assert any(
        item.severity.value == "blocker"
        and item.message
        == "A stable identifier was not recognized as an explicit requirement."
        for item in baseline.diagnostics
    )


@pytest.mark.parametrize(
    "heading, statement",
    (
        ("Security requirements", "- Rotate the audit key daily."),
        ("Acceptance criteria", "1. Invalid input is rejected."),
    ),
)
def test_unrecognized_requirement_list_item_is_a_blocking_unknown(
    tmp_path: Path,
    heading: str,
    statement: str,
) -> None:
    text = f"""# Contract

## Functional requirements
- `FR-APP-001`: The app must retain records.

## {heading}
{statement}
"""

    baseline = SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))

    assert any(
        item.kind.value == "unverifiable"
        and item.severity.value == "blocker"
        and item.requirement_ids == ()
        and item.message == "A normative statement was not recognized as a requirement."
        for item in baseline.diagnostics
    )
