from __future__ import annotations

from pathlib import Path

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
