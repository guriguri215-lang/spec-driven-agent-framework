from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sdaqf.application.orchestration import (
    OrchestrationContractError,
    load_agent_registry,
    load_agent_result,
    load_orchestration_request,
    load_worktree_plan,
)
from tests.m2_helpers import load_example, m2_example, write_json

Mutation = Callable[[dict[str, Any]], None]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(agents=[]), "must not be empty"),
        (
            lambda value: value["agents"][0].update(responsibilities=[]),
            "must not be empty",
        ),
        (
            lambda value: value["agents"][0].update(inputs=["same", "SAME"]),
            "unique",
        ),
        (
            lambda value: value["agents"][0].update(problem_types=["unknown"]),
            "unsupported",
        ),
        (
            lambda value: value["agents"][0].update(scales=[]),
            "must not be empty",
        ),
        (
            lambda value: value["agents"][0].update(can_write="yes"),
            "boolean",
        ),
        (lambda value: value.update(agents={}), "array"),
        (lambda value: value.update(agents=["invalid"]), "object"),
    ),
)
def test_agent_registry_boundary_matrix(
    tmp_path: Path,
    mutation: Mutation,
    message: str,
) -> None:
    payload = load_example("agent-registry.json")
    mutation(payload)

    with pytest.raises(OrchestrationContractError, match=message):
        load_agent_registry(write_json(tmp_path / "agents.json", payload))


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(schema_version="2.0"), "schema_version"),
        (lambda value: value.update(request_id="unsafe"), "ORQ"),
        (
            lambda value: value["budget"].update(max_agents=0),
            "between 1 and 16",
        ),
        (
            lambda value: value["budget"].update(max_agents=17),
            "between 1 and 16",
        ),
        (
            lambda value: value["budget"].update(max_concurrency=0),
            "positive",
        ),
        (
            lambda value: value["budget"].update(
                max_agents=2,
                max_concurrency=3,
            ),
            "not exceed",
        ),
        (
            lambda value: value["budget"].update(max_agents=True),
            "integer",
        ),
        (
            lambda value: value.update(problem_type="unsupported"),
            "unsupported",
        ),
        (
            lambda value: value.update(
                requested_roles=["implementer", "IMPLEMENTER"]
            ),
            "unique",
        ),
        (
            lambda value: value.update(native_subagents_available="yes"),
            "boolean",
        ),
    ),
)
def test_orchestration_request_boundary_matrix(
    tmp_path: Path,
    mutation: Mutation,
    message: str,
) -> None:
    payload = load_example("orchestration-request.json")
    mutation(payload)

    with pytest.raises(OrchestrationContractError, match=message):
        load_orchestration_request(write_json(tmp_path / "request.json", payload))


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(schema_version="2.0"), "schema_version"),
        (lambda value: value.update(base_commit="ABC"), "40-hex"),
        (lambda value: value.update(integrator_role="BAD ROLE"), "safe role"),
        (lambda value: value.update(assignments=value["assignments"][:1]), "at least two"),
        (
            lambda value: value["assignments"][0].update(role_id="BAD ROLE"),
            "role_id",
        ),
        (
            lambda value: value["assignments"][0].update(owned_paths=["CON/file"]),
            "safe relative",
        ),
        (
            lambda value: value["assignments"][0].update(owned_paths=[]),
            "must not be empty",
        ),
    ),
)
def test_worktree_plan_boundary_matrix(
    tmp_path: Path,
    mutation: Mutation,
    message: str,
) -> None:
    payload = load_example("worktree-plan.json")
    mutation(payload)

    with pytest.raises(OrchestrationContractError, match=message):
        load_worktree_plan(write_json(tmp_path / "worktrees.json", payload))


@pytest.mark.parametrize(
    ("filename", "mutation", "message"),
    (
        (
            "implementer-result.json",
            lambda value: value.update(schema_version="2.0"),
            "schema_version",
        ),
        (
            "implementer-result.json",
            lambda value: value.update(agent_id="unsafe"),
            "AGT",
        ),
        (
            "implementer-result.json",
            lambda value: value.update(role_id="unknown-role"),
            "unsupported role",
        ),
        (
            "implementer-result.json",
            lambda value: value["findings"].append(value["findings"][0]),
            "Finding identifiers",
        ),
        (
            "implementer-result.json",
            lambda value: value["findings"][0].update(finding_id="unsafe"),
            "finding_id",
        ),
        (
            "implementer-result.json",
            lambda value: value.update(reviewed_agent_ids=["AGT-REVIEWER-1"]),
            "Only an independent",
        ),
        (
            "reviewer-result.json",
            lambda value: value.update(
                reviewed_agent_ids=[value["agent_id"]]
            ),
            "cannot review its own",
        ),
        (
            "implementer-result.json",
            lambda value: value.update(status="unknown"),
            "unsupported",
        ),
    ),
)
def test_agent_result_boundary_matrix(
    tmp_path: Path,
    filename: str,
    mutation: Mutation,
    message: str,
) -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    payload = load_example(filename)
    mutation(payload)

    with pytest.raises(OrchestrationContractError, match=message):
        load_agent_result(write_json(tmp_path / "result.json", payload), registry)


def test_orchestration_loader_rejects_non_object_and_nul(tmp_path: Path) -> None:
    non_object = tmp_path / "non-object.json"
    non_object.write_text("[]", encoding="utf-8")
    contains_nul = tmp_path / "nul.json"
    contains_nul.write_bytes(b'{"schema_version":"2.0"}\x00')

    with pytest.raises(OrchestrationContractError, match="object"):
        load_agent_registry(non_object)
    with pytest.raises(OrchestrationContractError, match="NUL"):
        load_agent_registry(contains_nul)
