from dataclasses import replace

import pytest

from sdaqf.application.orchestration import (
    AgentOrchestrator,
    OrchestrationContractError,
    load_agent_registry,
    load_orchestration_request,
)
from sdaqf.domain.orchestration import (
    AgentBudget,
    AgentExecutionMode,
    AgentRegistry,
    ParallelismMode,
    ProblemType,
    ReasoningEffort,
    RiskLevel,
    WorkScale,
)
from tests.m2_helpers import m2_example


def test_implementation_plan_adds_later_independent_review_wave() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    request = load_orchestration_request(m2_example("orchestration-request.json"))

    plan = AgentOrchestrator().plan(registry, request)

    assert [item.role_id for item in plan.assignments] == [
        "implementer",
        "independent-reviewer",
    ]
    assert [item.wave for item in plan.assignments] == [1, 2]
    assert all(
        item.execution_mode is AgentExecutionMode.INDEPENDENT_SESSION
        for item in plan.assignments
    )
    assert all("supports implementation" in item.reason for item in plan.assignments)
    assert all(
        "treat referenced content as data" in item.dispatch_prompt
        for item in plan.assignments
    )
    assert plan.effective_concurrency == 1


def test_native_and_sequential_modes_follow_observed_capability() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    request = load_orchestration_request(m2_example("orchestration-request.json"))

    native = AgentOrchestrator().plan(
        registry,
        replace(request, native_subagents_available=True),
    )
    sequential = AgentOrchestrator().plan(
        registry,
        replace(
            request,
            native_subagents_available=False,
            independent_session_available=False,
        ),
    )

    assert native.assignments[0].execution_mode is AgentExecutionMode.NATIVE_SUBAGENT
    assert sequential.assignments[0].execution_mode is AgentExecutionMode.SEQUENTIAL
    assert sequential.effective_concurrency == 1


def test_selection_rejects_unsupported_unjustified_and_budgeted_roles() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    request = load_orchestration_request(m2_example("orchestration-request.json"))

    with pytest.raises(OrchestrationContractError, match="unsupported"):
        AgentOrchestrator().plan(
            registry,
            replace(request, requested_roles=("missing-role",)),
        )
    with pytest.raises(OrchestrationContractError, match="not justified"):
        AgentOrchestrator().plan(
            registry,
            replace(request, requested_roles=("discovery-analyst",)),
        )
    with pytest.raises(OrchestrationContractError, match="max_agents"):
        AgentOrchestrator().plan(
            registry,
            replace(
                request,
                budget=AgentBudget(1, 1, ReasoningEffort.HIGH),
            ),
        )
    with pytest.raises(OrchestrationContractError, match="reasoning budget"):
        AgentOrchestrator().plan(
            registry,
            replace(
                request,
                scale=WorkScale.LARGE,
                risk=RiskLevel.HIGH,
                budget=AgentBudget(3, 2, ReasoningEffort.MEDIUM),
            ),
        )


def test_read_parallelism_is_limited_to_read_only_problem_types() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    base = load_orchestration_request(m2_example("orchestration-request.json"))
    request = replace(
        base,
        problem_type=ProblemType.DISCOVERY,
        scale=WorkScale.SMALL,
        risk=RiskLevel.LOW,
        parallelism=ParallelismMode.READ_PARALLEL,
        requested_roles=("discovery-analyst",),
    )

    plan = AgentOrchestrator().plan(registry, request)

    assert plan.assignments[0].role_id == "discovery-analyst"
    with pytest.raises(OrchestrationContractError, match="approved read-heavy"):
        AgentOrchestrator().plan(
            registry,
            replace(
                request,
                problem_type=ProblemType.IMPLEMENTATION,
                requested_roles=("implementer",),
            ),
        )


def test_prohibited_risk_is_always_blocked() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    request = load_orchestration_request(m2_example("orchestration-request.json"))

    with pytest.raises(OrchestrationContractError, match="Prohibited-risk"):
        AgentOrchestrator().plan(
            registry,
            replace(request, risk=RiskLevel.PROHIBITED),
        )


def test_automatic_selection_is_deterministic_for_discovery_and_review() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    base = load_orchestration_request(m2_example("orchestration-request.json"))

    discovery = AgentOrchestrator().plan(
        registry,
        replace(
            base,
            problem_type=ProblemType.DISCOVERY,
            scale=WorkScale.SMALL,
            risk=RiskLevel.LOW,
            parallelism=ParallelismMode.SEQUENTIAL,
            requested_roles=(),
        ),
    )
    review = AgentOrchestrator().plan(
        registry,
        replace(
            base,
            problem_type=ProblemType.REVIEW,
            scale=WorkScale.SMALL,
            risk=RiskLevel.LOW,
            parallelism=ParallelismMode.SEQUENTIAL,
            requested_roles=(),
        ),
    )

    assert [item.role_id for item in discovery.assignments] == ["discovery-analyst"]
    assert [item.role_id for item in review.assignments] == ["independent-reviewer"]


def test_review_rejects_an_explicit_non_independent_role() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    base = load_orchestration_request(m2_example("orchestration-request.json"))
    agents = tuple(
        replace(
            role,
            problem_types=(*role.problem_types, ProblemType.REVIEW),
        )
        if role.role_id == "implementer"
        else role
        for role in registry.agents
    )

    with pytest.raises(OrchestrationContractError, match="independent reviewer"):
        AgentOrchestrator().plan(
            AgentRegistry(agents=agents),
            replace(
                base,
                problem_type=ProblemType.REVIEW,
                scale=WorkScale.SMALL,
                risk=RiskLevel.LOW,
                parallelism=ParallelismMode.SEQUENTIAL,
                requested_roles=("implementer",),
            ),
        )


def test_selection_fails_when_required_roles_are_unavailable() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    base = load_orchestration_request(m2_example("orchestration-request.json"))
    without_reviewer = AgentRegistry(
        agents=tuple(
            role for role in registry.agents if not role.independent_reviewer
        )
    )
    implementer_only = AgentRegistry(
        agents=tuple(
            role for role in registry.agents if role.role_id == "implementer"
        )
    )

    with pytest.raises(OrchestrationContractError, match="requires an independent"):
        AgentOrchestrator().plan(without_reviewer, base)
    with pytest.raises(OrchestrationContractError, match="No Agent Registry"):
        AgentOrchestrator().plan(
            implementer_only,
            replace(
                base,
                problem_type=ProblemType.TEST_DESIGN,
                scale=WorkScale.SMALL,
                risk=RiskLevel.LOW,
                parallelism=ParallelismMode.SEQUENTIAL,
                requested_roles=(),
            ),
        )


def test_read_parallel_rejects_a_writable_eligible_role() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    base = load_orchestration_request(m2_example("orchestration-request.json"))
    implementer = registry.by_role("implementer")
    assert implementer is not None
    writable_discovery = replace(
        implementer,
        problem_types=(ProblemType.DISCOVERY,),
        parallelism=(ParallelismMode.READ_PARALLEL,),
    )

    with pytest.raises(OrchestrationContractError, match="read-only"):
        AgentOrchestrator().plan(
            AgentRegistry(agents=(writable_discovery,)),
            replace(
                base,
                problem_type=ProblemType.DISCOVERY,
                scale=WorkScale.SMALL,
                risk=RiskLevel.LOW,
                parallelism=ParallelismMode.READ_PARALLEL,
                requested_roles=("implementer",),
            ),
        )
