"""Public M7 schemas, fixtures, evaluation evidence, and package boundaries."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts.validate_m7_solver import main

import sdaqf
from sdaqf.application.solver_contracts import (
    SolverContractError,
    parse_solver_artifact_bytes,
    solver_identity,
)
from sdaqf.domain.solver import SolverArtifactType
from tests.m6_scheduler_helpers import ROOT
from tests.m7_solver_helpers import build_fixture, registry_with_external_adapter
from tests.schema_validation import LocalSchemaValidator, SchemaValidationError

EXAMPLE_TO_SCHEMA = {
    "solver-registry.json": "solver-registry.schema.json",
    "solver-request.json": "solver-request.schema.json",
    "solver-result.json": "solver-result.schema.json",
    "solver-verification.json": "solver-verification.schema.json",
}


def test_all_public_solver_examples_validate_against_local_schemas() -> None:
    validator = LocalSchemaValidator(ROOT / "schemas")
    for example, schema in EXAMPLE_TO_SCHEMA.items():
        value = json.loads(
            (ROOT / "examples" / "m7-solver" / example).read_text(encoding="ascii")
        )
        validator.validate(schema, value)


def test_external_adapter_structure_validates_against_registry_schema(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(
        tmp_path,
        registry=registry_with_external_adapter(),
        adapter_id="optional-local-cli",
    )
    value = json.loads(fixture.registry_path.read_text(encoding="ascii"))
    LocalSchemaValidator(ROOT / "schemas").validate(
        "solver-registry.schema.json",
        value,
    )


@pytest.mark.parametrize(
    ("example", "schema", "mutation"),
    [
        (
            "solver-registry.json",
            "solver-registry.schema.json",
            ("content", "adapters", 0, "limits", "max_variables", True),
        ),
        (
            "solver-registry.json",
            "solver-registry.schema.json",
            ("content", "sensitivity", "internal"),
        ),
        (
            "solver-request.json",
            "solver-request.schema.json",
            ("content", "tolerance", "absolute", 1),
        ),
        (
            "solver-result.json",
            "solver-result.schema.json",
            ("content", "resources", "solver_steps", 1.5),
        ),
        (
            "solver-verification.json",
            "solver-verification.schema.json",
            ("content", "adoption_allowed", "yes"),
        ),
        (
            "solver-request.json",
            "solver-request.schema.json",
            ("content", "required_claim", "decision"),
        ),
        (
            "solver-request.json",
            "solver-request.schema.json",
            ("content", "problem", "objective", "terms", 0, "coefficient", 0),
        ),
        (
            "solver-result.json",
            "solver-result.schema.json",
            ("content", "proof_disposition", "none"),
        ),
        (
            "solver-result.json",
            "solver-result.schema.json",
            ("content", "task_id", "TSK-" + "A" * 65),
        ),
        (
            "solver-request.json",
            "solver-request.schema.json",
            ("content", "task_id", "TSK-A_B"),
        ),
        (
            "solver-result.json",
            "solver-result.schema.json",
            ("content", "task_id", "TSK-A_B"),
        ),
        (
            "solver-verification.json",
            "solver-verification.schema.json",
            ("content", "task_id", "TSK-A_B"),
        ),
        (
            "solver-verification.json",
            "solver-verification.schema.json",
            ("content", "checks", 0, "passed", False),
        ),
    ],
)
def test_schema_and_runtime_both_reject_closed_boundary_mutations(
    example: str,
    schema: str,
    mutation: tuple[object, ...],
) -> None:
    original = json.loads(
        (ROOT / "examples" / "m7-solver" / example).read_text(encoding="ascii")
    )
    value = deepcopy(original)
    target: Any = value
    for component in mutation[:-2]:
        target = target[component]
    target[mutation[-2]] = mutation[-1]
    with pytest.raises(SchemaValidationError):
        LocalSchemaValidator(ROOT / "schemas").validate(schema, value)
    with pytest.raises(SolverContractError):
        parse_solver_artifact_bytes(_strict(value))


def test_evaluation_covers_all_ten_statuses_without_aggregate_score() -> None:
    suite = json.loads((ROOT / "evals" / "m7-solver-suite.json").read_text())
    result = json.loads(
        (ROOT / "evals" / "results" / "m7-solver-evaluation.json").read_text()
    )
    expected = suite["cases"]
    observed = result["cases"]
    assert len(expected) == len(observed) == 10
    assert [item["case_id"] for item in expected] == [
        item["case_id"] for item in observed
    ]
    assert all(item["passed"] is True for item in observed)
    assert "aggregate_score" not in json.dumps(suite)
    assert "aggregate_score" not in json.dumps(result)


def test_schema_and_runtime_share_the_exact_m5_sensitivity_vocabulary() -> None:
    value = json.loads(
        (ROOT / "examples/m7-solver/solver-registry.json").read_text(encoding="ascii")
    )
    value["content"]["sensitivity"] = "repository-private"
    value["artifact_id"] = solver_identity(
        SolverArtifactType.REGISTRY,
        value["content"],
    )
    LocalSchemaValidator(ROOT / "schemas").validate(
        "solver-registry.schema.json",
        value,
    )
    parsed = parse_solver_artifact_bytes(_strict(value))
    assert parsed.value.to_dict()["sensitivity"] == "repository-private"


@pytest.mark.parametrize(
    "unsafe_path",
    ("CON", "folder/NUL.txt", "folder/name.", "~artifact"),
)
def test_solver_registry_schema_and_runtime_reject_exact_m6_nonportable_paths(
    unsafe_path: str,
) -> None:
    value = json.loads(
        (ROOT / "examples/m7-solver/solver-registry.json").read_text(encoding="ascii")
    )
    value["content"]["adapters"][0]["provenance"][0]["path"] = unsafe_path
    value["artifact_id"] = solver_identity(
        SolverArtifactType.REGISTRY,
        value["content"],
    )
    with pytest.raises(SchemaValidationError):
        LocalSchemaValidator(ROOT / "schemas").validate(
            "solver-registry.schema.json",
            value,
        )
    with pytest.raises(SolverContractError):
        parse_solver_artifact_bytes(_strict(value))


def test_solver_result_schema_and_runtime_require_exact_m6_utc_lease_expiry() -> None:
    value = json.loads(
        (ROOT / "examples/m7-solver/solver-result.json").read_text(encoding="ascii")
    )
    expiry = value["content"]["lease"]["expires_at"]
    assert isinstance(expiry, str) and expiry.endswith("Z")
    value["content"]["lease"]["expires_at"] = expiry[:-1] + "+00:00"
    value["artifact_id"] = solver_identity(
        SolverArtifactType.RESULT,
        value["content"],
    )
    with pytest.raises(SchemaValidationError):
        LocalSchemaValidator(ROOT / "schemas").validate(
            "solver-result.schema.json",
            value,
        )
    with pytest.raises(SolverContractError, match="RFC 3339 UTC"):
        parse_solver_artifact_bytes(_strict(value))


def test_named_validator_and_stable_export_boundary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main() == 0
    assert capsys.readouterr().out == "PASS: M7-SOLVER-EVIDENCE\n"
    assert sdaqf.__all__ == ["GateCheck", "GateResult", "ToolCapability", "ToolStatus"]


def test_ci_enforces_m7_coverage_and_named_validation() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    normalized = " ".join(workflow.split())
    assert "Check M7 critical coverage" in workflow
    assert "src/sdaqf/domain/solver.py" in workflow
    assert "src/sdaqf/application/solver_verification.py" in workflow
    assert "--fail-under=90" in normalized
    assert "Validate M7 solver evidence" in workflow
    assert "python scripts/validate_m7_solver.py" in normalized


def _strict(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
