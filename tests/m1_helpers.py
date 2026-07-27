from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sdaqf.application.requirements import SpecificationIngestor
from sdaqf.domain.requirements import RequirementBaseline

SIMPLE_SPEC = """# Example

## Functional requirements

- `FR-APP-001`: The command must validate one input.

## Constraints

- `C-APP-001`: The core must work without network access.

## Open decisions

1. Decide the final public name.
"""


def write_spec(tmp_path: Path, text: str = SIMPLE_SPEC, name: str = "spec.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def fixed_clock() -> datetime:
    return datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def ingest_spec(tmp_path: Path, text: str = SIMPLE_SPEC) -> RequirementBaseline:
    return SpecificationIngestor(clock=fixed_clock).ingest(write_spec(tmp_path, text))
