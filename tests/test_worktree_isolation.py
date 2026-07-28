from dataclasses import replace
from pathlib import Path

import pytest

from sdaqf.application.orchestration import (
    AgentOrchestrator,
    OrchestrationContractError,
    load_agent_registry,
    load_orchestration_request,
    load_worktree_plan,
)
from sdaqf.domain.orchestration import ParallelismMode
from tests.m2_helpers import load_example, m2_example, write_json


def test_isolated_write_plan_has_distinct_owners_and_integrator() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    request = load_orchestration_request(m2_example("write-request.json"))
    worktrees = load_worktree_plan(m2_example("worktree-plan.json"))

    plan = AgentOrchestrator().plan(
        registry,
        request,
        worktree_plan=worktrees,
    )

    assert request.parallelism is ParallelismMode.WRITE_PARALLEL
    assert {item.role_id for item in plan.assignments} == {
        "implementer",
        "independent-reviewer",
        "integrator",
        "test-implementer",
    }
    assert plan.effective_concurrency == 2
    waves = {item.role_id: item.wave for item in plan.assignments}
    assert waves == {
        "implementer": 1,
        "independent-reviewer": 3,
        "integrator": 2,
        "test-implementer": 1,
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda value: value["assignments"][1].update(
                worktree=value["assignments"][0]["worktree"]
            ),
            "distinct worktrees",
        ),
        (
            lambda value: value["assignments"][1].update(owned_paths=["src/sdaqf/cli.py"]),
            "overlap",
        ),
        (
            lambda value: value.update(integrator_role="implementer"),
            "integrator",
        ),
        (
            lambda value: value["assignments"][0].update(owned_paths=["../outside"]),
            "safe relative",
        ),
        (
            lambda value: value["assignments"][1].update(owned_paths=["SRC/SDAQF"]),
            "overlap",
        ),
    ),
)
def test_worktree_plan_rejects_same_worktree_scope_and_unsafe_path(
    tmp_path: Path,
    mutate: object,
    message: str,
) -> None:
    value = load_example("worktree-plan.json")
    assert callable(mutate)
    mutate(value)

    with pytest.raises(OrchestrationContractError, match=message):
        load_worktree_plan(write_json(tmp_path / "plan.json", value))


def test_parallel_write_requires_explicit_plan() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    request = load_orchestration_request(m2_example("write-request.json"))

    with pytest.raises(OrchestrationContractError, match="explicit worktree"):
        AgentOrchestrator().plan(registry, request)


def test_parallel_write_rejects_read_only_writer_and_reviewer_integrator() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    request = load_orchestration_request(m2_example("write-request.json"))
    worktrees = load_worktree_plan(m2_example("worktree-plan.json"))
    read_only_writer = replace(
        worktrees,
        assignments=(
            replace(
                worktrees.assignments[0],
                role_id="independent-reviewer",
            ),
            worktrees.assignments[1],
        ),
    )
    reviewer_integrator = replace(
        worktrees,
        integrator_role="independent-reviewer",
    )

    with pytest.raises(OrchestrationContractError, match="read-only"):
        AgentOrchestrator().plan(
            registry,
            request,
            worktree_plan=read_only_writer,
        )
    with pytest.raises(OrchestrationContractError, match="cannot act"):
        AgentOrchestrator().plan(
            registry,
            request,
            worktree_plan=reviewer_integrator,
        )


def test_parallel_write_rejects_unjustified_worktree_role() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    request = load_orchestration_request(m2_example("write-request.json"))
    worktrees = load_worktree_plan(m2_example("worktree-plan.json"))
    unjustified = replace(
        worktrees,
        assignments=(
            replace(
                worktrees.assignments[0],
                role_id="discovery-analyst",
            ),
            worktrees.assignments[1],
        ),
    )

    with pytest.raises(OrchestrationContractError, match="not justified"):
        AgentOrchestrator().plan(
            registry,
            request,
            worktree_plan=unjustified,
        )
