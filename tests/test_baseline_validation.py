from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sdaqf.application.baselines import (
    BaselineContractError,
    baseline_from_dict,
    load_baseline,
)
from tests.m1_helpers import ingest_spec


def test_baseline_contract_round_trip(tmp_path: Path) -> None:
    baseline = ingest_spec(tmp_path)
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(baseline.to_dict()), encoding="utf-8")

    loaded = load_baseline(path)

    assert loaded.to_dict() == baseline.to_dict()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update({"unexpected": True}), "unsupported field"),
        (
            lambda data: data.update({"schema_version": "2.0"}),
            "schema_version must be 1.0",
        ),
        (
            lambda data: data.update({"baseline_id": "bad"}),
            "stable RB identifier",
        ),
        (
            lambda data: data.update({"requirements": []}),
            "must not be empty",
        ),
        (
            lambda data: data["source"].update(
                {"path": "C:\\" + "Users\\person\\spec.md"}
            ),
            "relative display path",
        ),
        (
            lambda data: data["source"].update({"filename": "../spec.md"}),
            "safe filename",
        ),
        (
            lambda data: data["source"].update({"sha256": "bad"}),
            "SHA-256 digest",
        ),
        (
            lambda data: data["source"].update({"size_bytes": -1}),
            "must not be negative",
        ),
        (
            lambda data: data["source"].update(
                {"imported_at": "2026-07-27T12:00:00"}
            ),
            "include a timezone",
        ),
        (
            lambda data: data["requirements"][0].update({"id": "bad"}),
            "uppercase stable identifier",
        ),
        (
            lambda data: data["requirements"][0].update({"type": "unknown"}),
            "unsupported value",
        ),
        (
            lambda data: data["requirements"][0].update({"status": "unknown"}),
            "status is invalid",
        ),
        (
            lambda data: data["requirements"][0].update(
                {"identifier_source": "unknown"}
            ),
            "identifier_source is invalid",
        ),
        (
            lambda data: data["requirements"][0]["source"].update(
                {"line_start": 0}
            ),
            "invalid line range",
        ),
        (
            lambda data: data["requirements"][0]["acceptance_criteria"][0].update(
                {"id": "bad"}
            ),
            "stable identifier",
        ),
        (
            lambda data: data["requirements"][0]["acceptance_criteria"][0].update(
                {"verification_methods": []}
            ),
            "must not be empty",
        ),
        (
            lambda data: data["requirements"][0].update({"acceptance_criteria": []}),
            "acceptance and verification",
        ),
        (
            lambda data: data.update({"baseline_id": "RB-1111111111111111"}),
            "match the source digest",
        ),
        (
            lambda data: data["source"].update({"modified_at": "not-a-time"}),
            "ISO 8601",
        ),
        (
            lambda data: data["approval_state"].update(
                {"granted": ["CHG-111111111111"]}
            ),
            "not trusted",
        ),
        (
            lambda data: data["approval_state"].update(
                {
                    "required": [
                        "CHG-111111111111",
                        "CHG-111111111111",
                    ]
                }
            ),
            "must be unique",
        ),
        (
            lambda data: data["requirements"][0]["trace_links"].update(
                {"tests": "not-an-array"}
            ),
            "must be an array",
        ),
        (
            lambda data: data["requirements"][0].update({"statement": ""}),
            "non-empty string",
        ),
    ],
)
def test_baseline_contract_rejects_invalid_shapes(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = copy.deepcopy(ingest_spec(tmp_path).to_dict())
    assert callable(mutation)
    mutation(payload)

    with pytest.raises(BaselineContractError, match=message):
        baseline_from_dict(payload)


def test_baseline_contract_rejects_duplicate_requirement_id(tmp_path: Path) -> None:
    payload = copy.deepcopy(ingest_spec(tmp_path).to_dict())
    payload["requirements"].append(copy.deepcopy(payload["requirements"][0]))

    with pytest.raises(BaselineContractError, match="must be unique"):
        baseline_from_dict(payload)


def test_baseline_contract_rejects_duplicate_acceptance_id(tmp_path: Path) -> None:
    payload = copy.deepcopy(ingest_spec(tmp_path).to_dict())
    criteria = payload["requirements"][0]["acceptance_criteria"]
    criteria.append(copy.deepcopy(criteria[0]))

    with pytest.raises(BaselineContractError, match="IDs must be unique"):
        baseline_from_dict(payload)


def test_baseline_contract_enforces_generated_id_and_acceptance_link(
    tmp_path: Path,
) -> None:
    payload = copy.deepcopy(ingest_spec(tmp_path).to_dict())
    generated = next(
        item for item in payload["requirements"] if item["identifier_source"] == "generated"
    )
    generated["id"] = "OD-AUTO-111111111111"
    generated["acceptance_criteria"][0]["id"] = "AC-OD-AUTO-111111111111-01"
    with pytest.raises(BaselineContractError, match="generated identifier"):
        baseline_from_dict(payload)

    payload = copy.deepcopy(ingest_spec(tmp_path).to_dict())
    payload["requirements"][0]["acceptance_criteria"][0]["id"] = "AC-FR-OTHER-001-01"
    with pytest.raises(BaselineContractError, match="must link"):
        baseline_from_dict(payload)


@pytest.mark.parametrize(
    "document",
    [
        "C:\\" + "Users\\person\\spec.md",
        "../spec.md",
        "..",
        "line\nbreak.md",
        "nul\0name.md",
    ],
)
def test_baseline_contract_rejects_unsafe_trace_document(
    tmp_path: Path,
    document: str,
) -> None:
    payload = copy.deepcopy(ingest_spec(tmp_path).to_dict())
    payload["requirements"][0]["source"]["document"] = document

    with pytest.raises(BaselineContractError, match="safe filename"):
        baseline_from_dict(payload)


def test_source_acceptance_criteria_are_unique_and_linked(tmp_path: Path) -> None:
    baseline = ingest_spec(
        tmp_path,
        """# Contract
## Functional requirements
- `FR-APP-001`: The app validates input.
- `AC-FR-APP-001-01`: Invalid input is rejected.
""",
    )
    payload = copy.deepcopy(baseline.to_dict())
    payload["source_acceptance_criteria"].append(
        copy.deepcopy(payload["source_acceptance_criteria"][0])
    )
    with pytest.raises(BaselineContractError, match="must be unique"):
        baseline_from_dict(payload)

    payload = copy.deepcopy(baseline.to_dict())
    payload["source_acceptance_criteria"][0]["id"] = "AC-UNKNOWN-001"
    with pytest.raises(BaselineContractError, match="link a requirement or milestone"):
        baseline_from_dict(payload)


def test_baseline_contract_validates_diagnostic_references_and_shape(
    tmp_path: Path,
) -> None:
    baseline = ingest_spec(
        tmp_path,
        """# Contract
## Functional requirements
- `FR-APP-001`: The app must create a snapshot when practical.
""",
    )
    payload = copy.deepcopy(baseline.to_dict())
    payload["diagnostics"][0]["requirement_ids"] = ["FR-UNKNOWN-001"]
    with pytest.raises(BaselineContractError, match="known requirements"):
        baseline_from_dict(payload)

    payload = copy.deepcopy(baseline.to_dict())
    payload["diagnostics"].append(copy.deepcopy(payload["diagnostics"][0]))
    with pytest.raises(BaselineContractError, match="diagnostic identifiers"):
        baseline_from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", "bad", "stable diagnostic"),
        ("status", "unknown", "status is invalid"),
        ("kind", "unknown", "unsupported value"),
        ("severity", "unknown", "unsupported value"),
        ("line_end", 0, "invalid line range"),
    ],
)
def test_baseline_contract_rejects_invalid_diagnostic_fields(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    baseline = ingest_spec(
        tmp_path,
        """# Contract
## Functional requirements
- `FR-APP-001`: The app must create a snapshot when practical.
""",
    )
    payload = copy.deepcopy(baseline.to_dict())
    payload["diagnostics"][0][field] = value

    with pytest.raises(BaselineContractError, match=message):
        baseline_from_dict(payload)


def test_load_baseline_rejects_non_json_missing_and_invalid_json(
    tmp_path: Path,
) -> None:
    wrong = tmp_path / "baseline.txt"
    wrong.write_text("{}", encoding="utf-8")
    with pytest.raises(BaselineContractError, match="JSON file"):
        load_baseline(wrong)

    with pytest.raises(BaselineContractError, match="regular"):
        load_baseline(tmp_path / "missing.json")

    invalid = tmp_path / "baseline.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(BaselineContractError, match="valid JSON"):
        load_baseline(invalid)


def test_load_baseline_classifies_size_and_read_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sdaqf.application import baselines

    path = tmp_path / "baseline.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baselines, "_MAX_BASELINE_BYTES", 1)
    with pytest.raises(BaselineContractError, match="size limit"):
        load_baseline(path)

    monkeypatch.setattr(baselines, "_MAX_BASELINE_BYTES", 100)

    def denied_read(
        self: Path, encoding: str | None = None, errors: str | None = None
    ) -> str:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", denied_read)
    with pytest.raises(BaselineContractError, match="could not be read"):
        load_baseline(path)
