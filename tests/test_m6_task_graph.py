"""M6 Task Graph validation tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sdaqf.application.scheduler_contracts import (
    SchedulerContractError,
    artifact_from_value,
    parse_scheduler_artifact_bytes,
    serialize_scheduler_artifact,
    topological_ranks,
)
from sdaqf.domain.scheduler import SchedulerArtifactType, TaskKind
from tests.m6_scheduler_helpers import ROOT, graph_value


def _parse_graph(graph: object, *, validate_inputs: bool = False) -> object:
    artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)  # type: ignore[arg-type]
    return parse_scheduler_artifact_bytes(
        serialize_scheduler_artifact(artifact),
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=ROOT if validate_inputs else None,
    )


def test_public_graph_inputs_and_topological_rank_are_exact() -> None:
    graph = graph_value()
    loaded = _parse_graph(graph, validate_inputs=True)
    assert loaded.artifact_type is SchedulerArtifactType.TASK_GRAPH  # type: ignore[attr-defined]
    assert topological_ranks(graph) == {"TSK-M6-DEMO": 0}


def test_cycle_missing_dependency_and_self_reference_are_rejected() -> None:
    graph = graph_value()
    first = graph.tasks[0]
    for dependencies in (("TSK-M6-DEMO",), ("TSK-MISSING",)):
        changed = replace(first, dependencies=dependencies)
        with pytest.raises(SchedulerContractError):
            _parse_graph(replace(graph, tasks=(changed,)))


def test_task_sorting_and_duplicate_identity_are_rejected() -> None:
    graph = graph_value()
    first = graph.tasks[0]
    second = replace(first, task_id="TSK-SECOND", owned_paths=())
    with pytest.raises(SchedulerContractError, match="sorted"):
        _parse_graph(replace(graph, tasks=(second, first)))
    with pytest.raises(SchedulerContractError):
        _parse_graph(replace(graph, tasks=(first, first)))


def test_overlapping_owned_paths_are_rejected() -> None:
    graph = graph_value()
    first = replace(graph.tasks[0], owned_paths=("src/sdaqf",))
    second = replace(first, task_id="TSK-SECOND", owned_paths=("src/sdaqf/cli.py",))
    with pytest.raises(SchedulerContractError, match="overlap"):
        _parse_graph(replace(graph, tasks=(first, second)))


def test_budget_concurrency_and_cost_combinations_fail_closed() -> None:
    graph = graph_value()
    with pytest.raises(SchedulerContractError, match="max_concurrency"):
        _parse_graph(replace(graph, budget=replace(graph.budget, max_agents=1, max_concurrency=2)))
    with pytest.raises(SchedulerContractError, match="available"):
        _parse_graph(
            replace(
                graph,
                budget=replace(
                    graph.budget,
                    cost_status="available",
                    currency=None,
                    max_microunits=None,
                ),
            )
        )


def test_exact_input_hash_and_role_authority_are_revalidated() -> None:
    graph = graph_value()
    bad_reference = replace(graph.agent_registry, sha256="0" * 64)
    with pytest.raises(SchedulerContractError):
        _parse_graph(replace(graph, agent_registry=bad_reference), validate_inputs=True)

    unauthorized = replace(graph.tasks[0], role_id="unrequested-role")
    with pytest.raises(SchedulerContractError):
        _parse_graph(replace(graph, tasks=(unauthorized,)), validate_inputs=True)


def test_m2_budget_context_and_tool_authority_cannot_be_widened() -> None:
    graph = graph_value()
    widened = replace(graph, budget=replace(graph.budget, max_agents=4))
    with pytest.raises(SchedulerContractError, match="max_agents"):
        _parse_graph(widened, validate_inputs=True)

    drifted_candidate = replace(graph.candidate, git_head="a" * 40)
    binding = replace(graph.contexts[0], candidate=drifted_candidate)
    with pytest.raises(SchedulerContractError, match="candidate"):
        _parse_graph(replace(graph, contexts=(binding,)), validate_inputs=True)

    tool_widened = replace(graph.tasks[0], required_tools=("network",))
    with pytest.raises(SchedulerContractError, match="tool"):
        _parse_graph(replace(graph, tasks=(tool_widened,)), validate_inputs=True)


def test_task_kind_worktree_and_review_authority_fail_closed() -> None:
    graph = graph_value()
    review = replace(graph.tasks[0], kind=TaskKind.REVIEW)
    with pytest.raises(SchedulerContractError, match="reviewer"):
        _parse_graph(replace(graph, tasks=(review,)), validate_inputs=True)

    integration = replace(graph.tasks[0], kind=TaskKind.INTEGRATION)
    with pytest.raises(SchedulerContractError, match="integrator"):
        _parse_graph(replace(graph, tasks=(integration,)), validate_inputs=True)

    assigned = replace(
        graph.tasks[0],
        owned_paths=("src/sdaqf",),
        worktree_assignment="worktrees/implementation",
    )
    with pytest.raises(SchedulerContractError, match="worktree"):
        _parse_graph(replace(graph, tasks=(assigned,)), validate_inputs=True)

    first = graph.tasks[0]
    second = replace(first, task_id="TSK-SECOND", review_targets=())
    reviewer = replace(first, review_targets=(second.task_id,))
    with pytest.raises(SchedulerContractError, match="own role"):
        _parse_graph(replace(graph, tasks=(reviewer, second)), validate_inputs=True)
