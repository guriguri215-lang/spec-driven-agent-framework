"""M6 Task Graph validation tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sdaqf.application.scheduler_contracts import (
    SchedulerContractError,
    artifact_from_value,
    bind_review_task_result_evidence,
    load_scheduler_artifact,
    parse_scheduler_artifact_bytes,
    serialize_scheduler_artifact,
    task_input_provenance,
    topological_ranks,
    validate_reviewed_agent_identities,
)
from sdaqf.domain.orchestration import AgentResult, AgentResultStatus
from sdaqf.domain.quality import ArtifactReference, IndependentReview, ReviewStatus
from sdaqf.domain.scheduler import (
    MailboxMessage,
    MessageType,
    SchedulerArtifactType,
    TaskGraph,
    TaskKind,
)
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


def test_review_target_capacity_reserves_one_exact_review_reference() -> None:
    graph = graph_value()
    base = graph.tasks[0]
    targets = tuple(
        replace(
            base,
            task_id=f"TSK-TARGET-{index:02d}",
            dependencies=(),
            review_targets=(),
            owned_paths=(),
        )
        for index in range(64)
    )
    review = replace(
        base,
        task_id="TSK-REVIEW",
        kind=TaskKind.REVIEW,
        dependencies=(),
        review_targets=tuple(item.task_id for item in targets[:63]),
        owned_paths=(),
    )
    accepted = tuple(sorted((*targets[:63], review), key=lambda item: item.task_id))
    _parse_graph(replace(graph, tasks=accepted))

    over_capacity = replace(
        review,
        review_targets=tuple(item.task_id for item in targets),
    )
    rejected = tuple(sorted((*targets, over_capacity), key=lambda item: item.task_id))
    with pytest.raises(SchedulerContractError, match="at most 63 targets"):
        _parse_graph(replace(graph, tasks=rejected))


def test_review_result_binds_one_review_and_every_exact_target_result() -> None:
    graph, message = _review_graph_and_message()
    target_a = ArtifactReference("workflow/target-a.json", "A" * 64)
    target_b = ArtifactReference("workflow/target-b.json", "B" * 64)
    review = ArtifactReference("workflow/review.json", "C" * 64)
    bound = {"TSK-TARGET-A": target_a, "TSK-TARGET-B": target_b}
    exact = _with_evidence(message, review, target_b, target_a)

    assert bind_review_task_result_evidence(graph, exact, bound) == review

    with pytest.raises(SchedulerContractError, match="requires a Task Result"):
        bind_review_task_result_evidence(
            graph,
            replace(exact, message_type=MessageType.HEARTBEAT),
            bound,
        )
    with pytest.raises(SchedulerContractError, match="requires a Review task"):
        bind_review_task_result_evidence(
            graph,
            replace(exact, task_id="TSK-TARGET-A"),
            bound,
        )
    with pytest.raises(SchedulerContractError, match="requires a Review task"):
        bind_review_task_result_evidence(
            graph,
            replace(exact, task_id="TSK-UNKNOWN"),
            bound,
        )
    with pytest.raises(SchedulerContractError, match="not accepted"):
        bind_review_task_result_evidence(graph, exact, {"TSK-TARGET-A": target_a})
    with pytest.raises(SchedulerContractError, match="distinct Agent Results"):
        bind_review_task_result_evidence(
            graph,
            exact,
            {"TSK-TARGET-A": target_a, "TSK-TARGET-B": target_a},
        )

    for invalid in (
        _with_evidence(message, review, target_a),
        _with_evidence(
            message,
            review,
            target_a,
            target_b,
            ArtifactReference("workflow/extra.json", "D" * 64),
        ),
    ):
        with pytest.raises(SchedulerContractError, match="every exact target"):
            bind_review_task_result_evidence(graph, invalid, bound)


def test_review_result_binding_rechecks_capacity_and_agent_identities() -> None:
    graph, message = _review_graph_and_message()

    def agent_result(
        agent_id: str,
        reviewed_agent_ids: tuple[str, ...] = (),
    ) -> AgentResult:
        return AgentResult(
            agent_id=agent_id,
            role_id="test-review-role",
            status=AgentResultStatus.COMPLETED,
            summary="identity binding fixture",
            findings=(),
            changed_paths=(),
            reviewed_agent_ids=reviewed_agent_ids,
            self_approved=False,
        )

    def independent_review(
        reviewer_id: str,
        reviewed_agent_ids: tuple[str, ...],
    ) -> IndependentReview:
        return IndependentReview(
            review_id="REV-M6-IDENTITY-FIXTURE",
            baseline_id="REQ-BASELINE-M6-IDENTITY-FIXTURE",
            candidate=graph.candidate,
            reviewed_at="2026-08-01T00:00:00Z",
            reviewer_id=reviewer_id,
            reviewed_agent_ids=reviewed_agent_ids,
            status=ReviewStatus.COMPLETED,
            read_only=True,
            areas=(),
            findings=(),
            reviewed_paths=(),
            changed_paths=(),
        )

    over_capacity = replace(
        next(task for task in graph.tasks if task.kind is TaskKind.REVIEW),
        review_targets=tuple(f"TSK-CAPACITY-{index:02d}" for index in range(64)),
    )
    over_capacity_graph = replace(graph, tasks=(*graph.tasks[:-1], over_capacity))
    with pytest.raises(SchedulerContractError, match="at most 63 targets"):
        bind_review_task_result_evidence(over_capacity_graph, message, {})

    review_task = next(task for task in graph.tasks if task.kind is TaskKind.REVIEW)
    accepted: dict[str, AgentResult] = {
        "TSK-TARGET-A": agent_result("AGT-TARGET-A"),
        "TSK-TARGET-B": agent_result("AGT-TARGET-B"),
    }
    reviewer = agent_result(
        "AGT-REVIEWER",
        ("AGT-TARGET-A", "AGT-TARGET-B"),
    )
    review = independent_review(
        "AGT-REVIEWER",
        ("AGT-TARGET-B", "AGT-TARGET-A"),
    )
    validate_reviewed_agent_identities(review_task, reviewer, review, accepted)

    with pytest.raises(SchedulerContractError, match="requires a Review task"):
        validate_reviewed_agent_identities(graph.tasks[0], reviewer, review, accepted)
    with pytest.raises(SchedulerContractError, match="not accepted"):
        validate_reviewed_agent_identities(
            review_task,
            reviewer,
            review,
            {"TSK-TARGET-A": accepted["TSK-TARGET-A"]},
        )
    mismatches = (
        (
            reviewer,
            independent_review(
                "AGT-OTHER",
                ("AGT-TARGET-A", "AGT-TARGET-B"),
            ),
            accepted,
        ),
        (
            reviewer,
            independent_review(
                "AGT-REVIEWER",
                ("AGT-TARGET-A",),
            ),
            accepted,
        ),
        (
            agent_result(
                "AGT-REVIEWER",
                ("AGT-TARGET-A", "AGT-EXTRA"),
            ),
            independent_review(
                "AGT-REVIEWER",
                ("AGT-TARGET-A", "AGT-EXTRA"),
            ),
            accepted,
        ),
    )
    for mismatched_reviewer, mismatch, mismatched_accepted in mismatches:
        with pytest.raises(SchedulerContractError, match="completed target agents"):
            validate_reviewed_agent_identities(
                review_task,
                mismatched_reviewer,
                mismatch,
                mismatched_accepted,
            )

    missing_context = replace(graph, contexts=())
    with pytest.raises(SchedulerContractError, match="context binding is unavailable"):
        task_input_provenance(ROOT, missing_context, graph.tasks[0])


def _review_graph_and_message() -> tuple[TaskGraph, MailboxMessage]:
    graph = graph_value()
    base = graph.tasks[0]
    target_a = replace(base, task_id="TSK-TARGET-A")
    target_b = replace(base, task_id="TSK-TARGET-B")
    review = replace(
        base,
        task_id="TSK-REVIEW",
        kind=TaskKind.REVIEW,
        review_targets=(target_a.task_id, target_b.task_id),
    )
    review_graph = replace(graph, tasks=(target_a, target_b, review))
    artifact = load_scheduler_artifact(
        ROOT / "examples/m6-scheduler/mailbox-message.json",
        expected_type=SchedulerArtifactType.MAILBOX_MESSAGE,
        root=ROOT,
    )
    message = artifact.value
    assert isinstance(message, MailboxMessage)
    return review_graph, replace(
        message,
        message_type=MessageType.TASK_RESULT,
        task_id=review.task_id,
        payload={"evidence_refs": []},
    )


def _with_evidence(
    message: MailboxMessage,
    *references: ArtifactReference,
) -> MailboxMessage:
    ordered = sorted(references, key=lambda item: (item.path, item.sha256))
    return replace(
        message,
        payload={"evidence_refs": [item.to_dict() for item in ordered]},
    )
