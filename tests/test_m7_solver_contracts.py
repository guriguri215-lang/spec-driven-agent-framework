"""Strict M7 envelope, identity, and numeric contract tests."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from sdaqf.application.solver_contracts import (
    SolverContractError,
    load_solver_artifact,
    parse_solver_artifact_bytes,
    parse_solver_capability_token,
    serialize_solver_artifact,
    solver_identity,
)
from sdaqf.domain.solver import SolverArtifactType, SolverRequiredClaim, SolverResult
from tests.m7_solver_helpers import (
    build_fixture,
    feasibility_problem,
    mixed_constraint_problem,
    registry_with_external_adapter,
)


def test_all_generated_solver_envelopes_round_trip_exactly(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    for path, artifact_type in (
        (fixture.registry_path, SolverArtifactType.REGISTRY),
        (fixture.request_path, SolverArtifactType.REQUEST),
    ):
        loaded = load_solver_artifact(path, expected_type=artifact_type)
        assert serialize_solver_artifact(loaded) == path.read_bytes()


def test_envelope_rejects_unknown_keys_and_wrong_content_identity(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    payload = json.loads(fixture.request_path.read_text(encoding="ascii"))
    payload["forged"] = True
    with pytest.raises(SolverContractError, match="unsupported field"):
        parse_solver_artifact_bytes(_strict(payload))

    payload.pop("forged")
    payload["content"]["adapter_id"] = "forged-adapter"
    with pytest.raises(SolverContractError, match="identity"):
        parse_solver_artifact_bytes(_strict(payload))


def test_raw_solver_json_rejects_duplicate_keys_and_nonfinite_numbers(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path)
    raw = fixture.request_path.read_bytes()
    duplicate = raw.replace(
        b'  "schema_version": "1.0"',
        b'  "schema_version": "1.0",\n  "schema_version": "1.0"',
        1,
    )
    with pytest.raises(SolverContractError, match="strict UTF-8 JSON"):
        parse_solver_artifact_bytes(duplicate)

    nonfinite = raw.replace(b'"max_solve_steps": 16', b'"max_solve_steps": NaN', 1)
    with pytest.raises(SolverContractError, match="strict UTF-8 JSON"):
        parse_solver_artifact_bytes(nonfinite)

@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("content", "resource_policy", "max_solve_steps"), True),
        (("content", "resource_policy", "timeout_milliseconds"), 1.5),
        (("content", "problem", "variables", 0, "domain", "lower"), -1.0),
    ],
)
def test_floats_and_booleans_never_cross_integer_boundaries(
    tmp_path: Path,
    path: tuple[str | int, ...],
    value: object,
) -> None:
    fixture = build_fixture(tmp_path)
    payload = json.loads(fixture.request_path.read_text(encoding="ascii"))
    target: Any = payload
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value
    with pytest.raises(SolverContractError):
        parse_solver_artifact_bytes(_strict(payload))


def test_request_rejects_noncanonical_operational_contract_and_ordering(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path)
    payload = json.loads(fixture.request_path.read_text(encoding="ascii"))
    payload["content"]["contract_id"] = "M7-SOLVER-CONTRACT-" + "F" * 64
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError, match="contract identity"):
        parse_solver_artifact_bytes(_strict(payload))

    payload = json.loads(fixture.request_path.read_text(encoding="ascii"))
    payload["content"]["problem"]["variables"].reverse()
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError, match="sorted"):
        parse_solver_artifact_bytes(_strict(payload))


def test_exact_zero_tolerance_and_search_space_bounds_are_closed(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    payload = json.loads(fixture.request_path.read_text(encoding="ascii"))
    payload["content"]["tolerance"]["absolute"] = 1
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError, match="exact zero"):
        parse_solver_artifact_bytes(_strict(payload))

    payload = json.loads(fixture.request_path.read_text(encoding="ascii"))
    payload["content"]["problem"]["variables"][0]["domain"] = {
        "kind": "integer-range",
        "lower": 0,
        "upper": 256,
    }
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError):
        parse_solver_artifact_bytes(_strict(payload))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("profile",), "general"),
        (("variables",), []),
        (("variables", 0, "domain", "values"), [0, 0]),
        (("variables", 0, "domain", "kind"), "opaque"),
        (("constraints", 4, "rows", 0), [2]),
        (("constraints", 4, "rows", 0), [3, 0]),
        (("constraints", 4, "rows"), [[2, 0], [2, 0]]),
        (("constraints", 4, "variable_ids"), ["START_B", "START_A"]),
        (("constraints", 1, "literals"), []),
        (("constraints", 1, "literals", 0, "variable_id"), "UNKNOWN"),
        (("constraints", 1, "literals", 0, "equals"), 3),
        (
            ("constraints", 1, "literals"),
            [
                {"variable_id": "START_B", "equals": 1},
                {"variable_id": "START_A", "equals": 0},
            ],
        ),
        (("constraints", 3, "right_start"), "START_A"),
        (("constraints", 2, "terms"), []),
        (("constraints", 2, "terms", 0, "variable_id"), "UNKNOWN"),
        (("constraints", 2, "terms", 0, "coefficient"), 0),
        (
            ("constraints", 2, "terms"),
            [
                {"variable_id": "START_B", "coefficient": 1},
                {"variable_id": "START_A", "coefficient": 1},
            ],
        ),
        (("objective",), None),
    ],
)
def test_problem_union_rejects_each_noncanonical_boundary(
    tmp_path: Path,
    path: tuple[str | int, ...],
    value: object,
) -> None:
    fixture = build_fixture(tmp_path, problem=mixed_constraint_problem())
    payload = json.loads(fixture.request_path.read_text(encoding="ascii"))
    problem: Any = payload["content"]["problem"]
    _set(problem, path, value)
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError):
        parse_solver_artifact_bytes(_strict(payload))


def test_profile_search_space_order_and_claim_invariants(tmp_path: Path) -> None:
    optimization = build_fixture(tmp_path / "optimization", problem=mixed_constraint_problem())
    payload = json.loads(optimization.request_path.read_text(encoding="ascii"))
    payload["content"]["problem"]["profile"] = "boolean-sat"
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError, match="feasibility-only"):
        parse_solver_artifact_bytes(_strict(payload))

    decision = build_fixture(
        tmp_path / "decision",
        problem=feasibility_problem(satisfiable=True),
        required_claim=SolverRequiredClaim.DECISION,
        solve_steps=2,
        verification_steps=2,
    )
    payload = json.loads(decision.request_path.read_text(encoding="ascii"))
    payload["content"]["problem"]["variables"][0]["domain"]["values"] = [0, 1, 2]
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError, match="Boolean SAT variables"):
        parse_solver_artifact_bytes(_strict(payload))

    payload = json.loads(optimization.request_path.read_text(encoding="ascii"))
    payload["content"]["problem"]["constraints"].reverse()
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError, match="constraints must be sorted"):
        parse_solver_artifact_bytes(_strict(payload))

    payload = json.loads(optimization.request_path.read_text(encoding="ascii"))
    payload["content"]["problem"] = {
        "problem_kind": "finite-domain-optimization",
        "profile": "general",
        "variables": [
            {"variable_id": name, "domain": {"kind": "integer-range", "lower": 0, "upper": 100}}
            for name in ("A", "B", "C")
        ],
        "constraints": [],
        "objective": {
            "direction": "minimize",
            "terms": [
                {"variable_id": name, "coefficient": 1} for name in ("A", "B", "C")
            ],
            "constant": 0,
        },
    }
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError, match="one million"):
        parse_solver_artifact_bytes(_strict(payload))

    payload = json.loads(optimization.request_path.read_text(encoding="ascii"))
    payload["content"]["required_claim"] = "decision"
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError, match="Optimization claim"):
        parse_solver_artifact_bytes(_strict(payload))

    payload = json.loads(decision.request_path.read_text(encoding="ascii"))
    payload["content"]["required_claim"] = "feasible"
    _refresh(payload, SolverArtifactType.REQUEST)
    with pytest.raises(SolverContractError, match="Feasibility requires"):
        parse_solver_artifact_bytes(_strict(payload))


@pytest.mark.parametrize(
    "mutations",
    [
        [(("witness",), None)],
        [(("status",), "infeasible")],
        [(("objective_value",), None)],
        [(("status",), "satisfiable")],
        [(("status",), "bounded"), (("objective_interval",), None)],
        [(("objective_interval", "upper"), 3)],
        [(("status",), "infeasible"), (("witness",), None), (("proof_disposition",), "none")],
        [(("status",), "feasible"), (("proof_disposition",), "exhaustive-enumeration")],
        [(("status",), "timeout"), (("diagnostic_code",), "request-timeout")],
        [
            (("status",), "timeout"),
            (("proof_disposition",), "none"),
            (("diagnostic_code",), None),
        ],
        [(("diagnostic_code",), "step-limit")],
        [
            (("status",), "unavailable"),
            (("proof_disposition",), "none"),
            (("diagnostic_code",), "adapter-unavailable"),
        ],
        [(("diagnostic_code",), "unsupported-diagnostic")],
        [(("adapter_version",), "latest")],
        [(("license_expression",), "bad license")],
    ],
)
def test_result_status_shape_rejects_contradictory_evidence(
    mutations: list[tuple[tuple[str | int, ...], object]],
) -> None:
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/m7-solver/solver-result.json").read_text()
    )
    content: Any = payload["content"]
    for path, value in mutations:
        _set(content, path, value)
    _refresh(payload, SolverArtifactType.RESULT)
    with pytest.raises(SolverContractError):
        parse_solver_artifact_bytes(_strict(payload))


def test_registry_verification_and_token_negative_contracts(tmp_path: Path) -> None:
    external = build_fixture(
        tmp_path,
        registry=registry_with_external_adapter(),
        adapter_id="optional-local-cli",
    )
    registry_payload = json.loads(external.registry_path.read_text(encoding="ascii"))
    external_adapter: dict[str, Any] = registry_payload["content"]["adapters"][0]
    assert external_adapter["version_matcher"] == (
        r"Z3 version ([0-9]+\.[0-9]+(?:\.[0-9]+)?)"
    )
    assert external_adapter["version_observation"] == {
        "status": "not-observed",
        "observed_version": None,
        "evidence": None,
    }
    assert external_adapter["approval_requirements"] == {
        "owner_approval": "fresh-required",
        "technical_sandbox_approval": "fresh-required",
        "consumption": "single-use-atomic",
    }
    for mutation in (
        "empty",
        "reverse",
        "duplicate",
        "missing-reference",
        "network",
        "tool",
        "matcher",
        "observation",
        "approval",
    ):
        value = deepcopy(registry_payload)
        content: Any = value["content"]
        adapters: list[dict[str, Any]] = content["adapters"]
        if mutation == "empty":
            content["adapters"] = []
        elif mutation == "reverse":
            adapters.reverse()
        elif mutation == "duplicate":
            adapters.append(deepcopy(adapters[0]))
        elif mutation == "missing-reference":
            adapters.pop()
        elif mutation == "network":
            adapters[0]["network"] = True
        elif mutation == "tool":
            adapters[0]["tool_name"] = None
        elif mutation == "matcher":
            adapters[0]["version_matcher"] = None
        elif mutation == "observation":
            adapters[0]["version_observation"]["observed_version"] = "4.12.2"
        else:
            adapters[0]["approval_requirements"]["owner_approval"] = "reused"
        _refresh(value, SolverArtifactType.REGISTRY)
        with pytest.raises(SolverContractError):
            parse_solver_artifact_bytes(_strict(value))

    verification = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "examples/m7-solver/solver-verification.json"
        ).read_text()
    )
    verification_mutations: tuple[
        list[tuple[tuple[str | int, ...], object]], ...
    ] = (
        [(("checks",), [])],
        [(("checks",), [verification["content"]["checks"][0]] * 2)],
        [(("outcome",), "rejected")],
    )
    for mutations in verification_mutations:
        value = deepcopy(verification)
        for path, replacement in mutations:
            _set(value["content"], path, replacement)
        _refresh(value, SolverArtifactType.VERIFICATION)
        with pytest.raises(SolverContractError):
            parse_solver_artifact_bytes(_strict(value))

    for token in (
        "forged",
        "m7-solver-v1@too@few",
        "m7-solver-v1@M7-SOLVER-CONTRACT-" + "A" * 64 + "@01@1",
        "m7-solver-v1@M7-SOLVER-CONTRACT-" + "A" * 64 + "@1000001@1",
        "m7-solver-v1@M7-SOLVER-CONTRACT-" + "A" * 64 + "@1000000@1000001",
    ):
        with pytest.raises(SolverContractError):
            parse_solver_capability_token(token)


def test_solver_lease_host_id_matches_the_full_m6_host_grammar() -> None:
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "examples/m7-solver/solver-result.json").read_text()
    )
    maximum_m6_host = "HST-" + "A" * 64
    payload["content"]["lease"]["host_id"] = maximum_m6_host
    _refresh(payload, SolverArtifactType.RESULT)
    parsed = parse_solver_artifact_bytes(_strict(payload))
    assert isinstance(parsed.value, SolverResult)
    assert parsed.value.lease.host_id == maximum_m6_host

    payload["content"]["lease"]["host_id"] = "HST-A_B"
    _refresh(payload, SolverArtifactType.RESULT)
    with pytest.raises(SolverContractError, match="invalid identifier"):
        parse_solver_artifact_bytes(_strict(payload))


def _refresh(payload: dict[str, object], artifact_type: SolverArtifactType) -> None:
    payload["artifact_id"] = solver_identity(artifact_type, payload["content"])


def _strict(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def _set(target: Any, path: tuple[str | int, ...], value: object) -> None:
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value
