"""Shared exact fixtures for M7 solver tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    serialize_scheduler_artifact,
)
from sdaqf.application.scheduler_contracts import (
    artifact_from_value as scheduler_artifact_from_value,
)
from sdaqf.application.solver_contracts import (
    REFERENCE_ADAPTER_ID,
    artifact_from_value,
    operational_contract_id,
    serialize_solver_artifact,
    solver_capability_token,
)
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.scheduler import (
    EffectKind,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    TaskGraph,
    TaskKind,
)
from sdaqf.domain.solver import (
    AllDifferentConstraint,
    ClauseConstraint,
    ClauseLiteral,
    IntegerDomain,
    LinearConstraint,
    LinearRelation,
    LinearTerm,
    LoadedSolverArtifact,
    NonOverlapConstraint,
    ObjectiveDirection,
    SolverAdapterDefinition,
    SolverAdapterKind,
    SolverApprovalRequirements,
    SolverArtifactType,
    SolverConstraintKind,
    SolverObjective,
    SolverProblem,
    SolverProblemKind,
    SolverProblemProfile,
    SolverRegistry,
    SolverRequest,
    SolverRequiredClaim,
    SolverResourcePolicy,
    SolverResult,
    SolverVariable,
    SolverVerification,
    SolverVersionObservation,
    SolverVersionObservationStatus,
    TableConstraint,
    TableMode,
)
from tests.m6_scheduler_helpers import ROOT, graph_value, host_message

HOST_ID = "HST-M7-TEST"
FIXED_TIME = datetime(2030, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class M7Fixture:
    """Files and typed values for one exact solver/M6 binding."""

    directory: Path
    registry_path: Path
    request_path: Path
    graph_path: Path
    state_path: Path
    result_path: Path
    verification_path: Path
    registry: LoadedSolverArtifact
    request: LoadedSolverArtifact
    graph: LoadedSchedulerArtifact
    token: str


def reference_registry() -> SolverRegistry:
    """Return the mandatory offline standard-library adapter Registry."""

    provenance = tuple(
        reference(path) for path in (Path("LICENSE"), Path("pyproject.toml"))
    )
    adapter = SolverAdapterDefinition(
        adapter_id=REFERENCE_ADAPTER_ID,
        adapter_kind=SolverAdapterKind.REFERENCE,
        implementation="sdaqf.adapters.solver.FiniteDomainReferenceAdapter",
        version="1.0.0",
        supported_problem_kinds=tuple(
            sorted(SolverProblemKind, key=lambda item: item.value)
        ),
        supported_profiles=tuple(
            sorted(SolverProblemProfile, key=lambda item: item.value)
        ),
        supported_constraints=tuple(
            sorted(SolverConstraintKind, key=lambda item: item.value)
        ),
        numeric_domain="exact-integer",
        max_variables=16,
        max_domain_values=256,
        max_search_space=1_000_000,
        max_constraints=256,
        max_constraint_variables=16,
        max_table_rows=4_096,
        min_scalar=-1_000_000,
        max_scalar=1_000_000,
        max_artifact_bytes=1_048_576,
        network=False,
        optional=False,
        tool_registry=None,
        tool_name=None,
        executable=None,
        input_format=None,
        version_matcher=None,
        version_observation=None,
        approval_requirements=None,
        license_expression="Apache-2.0",
        provenance=provenance,
    )
    return SolverRegistry(Sensitivity.PUBLIC, (adapter,))


def registry_with_external_adapter() -> SolverRegistry:
    """Return a structurally complete but deliberately non-executable CLI adapter."""

    reference_definition = reference_registry().adapters[0]
    external = replace(
        reference_definition,
        adapter_id="optional-local-cli",
        adapter_kind=SolverAdapterKind.EXTERNAL_CLI,
        implementation="external.z3.cli",
        optional=True,
        tool_registry=reference(Path("examples/m2-orchestration/tool-registry.json")),
        tool_name="z3",
        executable="z3",
        input_format="smt2",
        version_matcher=r"Z3 version ([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
        version_observation=SolverVersionObservation(
            SolverVersionObservationStatus.NOT_OBSERVED,
            None,
            None,
        ),
        approval_requirements=SolverApprovalRequirements(
            owner_approval="fresh-required",
            technical_sandbox_approval="fresh-required",
            consumption="single-use-atomic",
        ),
    )
    return SolverRegistry(
        Sensitivity.PUBLIC,
        tuple(sorted((external, reference_definition), key=lambda item: item.adapter_id)),
    )


def scheduling_problem() -> SolverProblem:
    """Return a small deterministic optimization with two tied optima."""

    variables = (
        SolverVariable("START_A", IntegerDomain("integer-range", (0, 1, 2, 3))),
        SolverVariable("START_B", IntegerDomain("integer-range", (0, 1, 2, 3))),
    )
    constraint = NonOverlapConstraint("NO_OVERLAP", "START_A", 2, "START_B", 2)
    objective = SolverObjective(
        ObjectiveDirection.MINIMIZE,
        (LinearTerm("START_A", 1), LinearTerm("START_B", 1)),
        0,
    )
    return SolverProblem(
        SolverProblemKind.OPTIMIZATION,
        SolverProblemProfile.FINITE_SCHEDULING,
        variables,
        (constraint,),
        objective,
    )


def infeasible_problem() -> SolverProblem:
    """Return a finite scheduling instance with no assignment."""

    variables = (
        SolverVariable("START_A", IntegerDomain("integer-set", (0,))),
        SolverVariable("START_B", IntegerDomain("integer-set", (0,))),
    )
    return SolverProblem(
        SolverProblemKind.OPTIMIZATION,
        SolverProblemProfile.FINITE_SCHEDULING,
        variables,
        (NonOverlapConstraint("NO_OVERLAP", "START_A", 2, "START_B", 2),),
        SolverObjective(
            ObjectiveDirection.MINIMIZE,
            (LinearTerm("START_A", 1), LinearTerm("START_B", 1)),
            0,
        ),
    )


def feasibility_problem(*, satisfiable: bool) -> SolverProblem:
    """Return a one-variable Boolean decision instance."""

    constraints = (
        (ClauseConstraint("CLAUSE_A", (ClauseLiteral("X", 1),)),)
        if satisfiable
        else (
            ClauseConstraint("CLAUSE_A", (ClauseLiteral("X", 0),)),
            ClauseConstraint("CLAUSE_B", (ClauseLiteral("X", 1),)),
        )
    )
    return SolverProblem(
        SolverProblemKind.FEASIBILITY,
        SolverProblemProfile.BOOLEAN_SAT,
        (SolverVariable("X", IntegerDomain("integer-set", (0, 1))),),
        constraints,
        None,
    )


def mixed_constraint_problem() -> SolverProblem:
    """Return one instance exercising every first-version constraint variant."""

    variables = (
        SolverVariable("START_A", IntegerDomain("integer-set", (0, 1, 2))),
        SolverVariable("START_B", IntegerDomain("integer-set", (0, 1, 2))),
    )
    constraints = (
        AllDifferentConstraint("ALL_DIFFERENT", ("START_A", "START_B")),
        ClauseConstraint(
            "CLAUSE",
            (ClauseLiteral("START_A", 0), ClauseLiteral("START_B", 1)),
        ),
        LinearConstraint(
            "LINEAR",
            (LinearTerm("START_A", 1), LinearTerm("START_B", 1)),
            LinearRelation.LE,
            2,
        ),
        NonOverlapConstraint("NON_OVERLAP", "START_A", 1, "START_B", 1),
        TableConstraint(
            "TABLE",
            ("START_A", "START_B"),
            TableMode.FORBIDDEN,
            ((2, 0),),
        ),
    )
    return SolverProblem(
        SolverProblemKind.OPTIMIZATION,
        SolverProblemProfile.FINITE_SCHEDULING,
        variables,
        constraints,
        SolverObjective(
            ObjectiveDirection.MAXIMIZE,
            (LinearTerm("START_A", -1), LinearTerm("START_B", 2)),
            0,
        ),
    )


def build_fixture(
    tmp_path: Path,
    *,
    problem: SolverProblem | None = None,
    required_claim: SolverRequiredClaim = SolverRequiredClaim.OPTIMAL,
    solve_steps: int = 16,
    verification_steps: int = 16,
    timeout_milliseconds: int | None = None,
    max_result_bytes: int = 1_048_576,
    registry: SolverRegistry | None = None,
    adapter_id: str = REFERENCE_ADAPTER_ID,
) -> M7Fixture:
    """Publish exact Registry, Request, and M6 graph fixtures under the repo root."""

    selected_problem = scheduling_problem() if problem is None else problem
    tmp_path.mkdir(parents=True, exist_ok=True)
    selected_registry = reference_registry() if registry is None else registry
    registry_artifact = artifact_from_value(SolverArtifactType.REGISTRY, selected_registry)
    registry_path = tmp_path / "solver-registry.json"
    registry_path.write_bytes(serialize_solver_artifact(registry_artifact))
    registry_reference = reference(registry_path)

    base = graph_value()
    context = base.contexts[0]
    placeholder_graph = ArtifactReference("placeholder.json", "0" * 64)
    request_value = SolverRequest(
        sensitivity=context.sensitivity,
        registry=registry_reference,
        registry_id=registry_artifact.artifact_id,
        adapter_id=adapter_id,
        contract_id="M7-SOLVER-CONTRACT-" + "0" * 64,
        task_graph=placeholder_graph,
        graph_id="M6-TASK-GRAPH-" + "0" * 64,
        task_id=base.tasks[0].task_id,
        candidate=base.candidate,
        context_snapshot=context.reference,
        context_snapshot_id=context.artifact_id,
        problem=selected_problem,
        required_claim=required_claim,
        resource_policy=SolverResourcePolicy(
            solve_steps,
            verification_steps,
            timeout_milliseconds,
            max_result_bytes,
        ),
    )
    request_value = replace(
        request_value,
        contract_id=operational_contract_id(request_value.operational_content()),
    )
    token = solver_capability_token(request_value)
    graph_value_bound = replace(
        base,
        budget=replace(
            base.budget,
            max_solver_calls=1,
            max_solver_steps=solve_steps + verification_steps,
        ),
        tasks=(
            replace(
                base.tasks[0],
                kind=TaskKind.SOLVER,
                required_tools=(),
                required_capabilities=(token,),
                owned_paths=(),
                worktree_assignment=None,
                effect_kind=EffectKind.READ_ONLY,
            ),
        ),
    )
    graph_artifact = scheduler_artifact_from_value(
        SchedulerArtifactType.TASK_GRAPH, graph_value_bound
    )
    graph_path = tmp_path / "task-graph.json"
    graph_path.write_bytes(serialize_scheduler_artifact(graph_artifact))

    request_value = replace(
        request_value,
        task_graph=reference(graph_path),
        graph_id=graph_artifact.artifact_id,
    )
    assert request_value.contract_id == operational_contract_id(
        request_value.operational_content()
    )
    request_artifact = artifact_from_value(SolverArtifactType.REQUEST, request_value)
    request_path = tmp_path / "solver-request.json"
    request_path.write_bytes(serialize_solver_artifact(request_artifact))
    return M7Fixture(
        directory=tmp_path,
        registry_path=registry_path,
        request_path=request_path,
        graph_path=graph_path,
        state_path=tmp_path / "state.sqlite3",
        result_path=tmp_path / "solver-result.json",
        verification_path=tmp_path / "solver-verification.json",
        registry=registry_artifact,
        request=request_artifact,
        graph=graph_artifact,
        token=token,
    )


def start_solver_lease(fixture: M7Fixture) -> tuple[SQLiteSchedulerStore, LoadedSchedulerArtifact]:
    """Initialize M6 state, advertise the exact token, dispatch, and acknowledge."""

    graph = fixture.graph.value
    assert isinstance(graph, TaskGraph)
    store = SQLiteSchedulerStore.initialize(
        fixture.state_path,
        ROOT,
        fixture.graph,
        FIXED_TIME,
    )
    observation = scheduler_artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.CAPABILITY_OBSERVATION,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender=HOST_ID,
            recipient="HST-SCHEDULER",
            graph_id=fixture.graph.artifact_id,
            task_id=None,
            candidate=graph.candidate,
            context_snapshot_id=None,
            attempt=None,
            lease_id=None,
            fence=None,
            idempotency_key=None,
            sensitivity=Sensitivity.PUBLIC,
            provenance=(),
            causal_parent_message_ids=(),
            recorded_at=_timestamp(FIXED_TIME),
            payload={"capabilities": [fixture.token]},
        ),
    )
    tick = store.tick(ROOT, HOST_ID, (observation,), FIXED_TIME)
    assert tick.accepted_message_ids == (observation.artifact_id,)
    assert len(tick.outgoing) == 1
    dispatch = tick.outgoing[0]
    acknowledgement = host_message(
        dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {"accepted": True, "effect_observed": "none", "note": None},
        clock=FIXED_TIME + timedelta(seconds=1),
        sender=HOST_ID,
    )
    acknowledged = store.tick(
        ROOT,
        HOST_ID,
        (acknowledgement,),
        FIXED_TIME + timedelta(seconds=1),
    )
    assert acknowledged.accepted_message_ids == (acknowledgement.artifact_id,)
    return store, dispatch


def solver_task_result(
    dispatch: LoadedSchedulerArtifact,
    result: LoadedSolverArtifact,
    verification: LoadedSolverArtifact,
    result_path: Path,
    verification_path: Path,
    *,
    outcome: str = "succeeded",
) -> LoadedSchedulerArtifact:
    """Return a scheduler Task Result bound to exact paired M7 evidence."""

    result_value = result.value
    verification_value = verification.value
    assert isinstance(result_value, SolverResult)
    assert isinstance(verification_value, SolverVerification)
    result_ref = reference(result_path)
    verification_ref = reference(verification_path)
    evidence = sorted(
        (result_ref.to_dict(), verification_ref.to_dict()),
        key=lambda item: str(item["path"]),
    )
    agent_result = reference(Path("examples/m7-solver/solver-agent-result.json"))
    return host_message(
        dispatch,
        MessageType.TASK_RESULT,
        {
            "agent_result": agent_result.to_dict(),
            "outcome": outcome,
            "effect_observed": "none",
            "evidence_refs": evidence,
            "budget_usage": {
                "microunits": 0,
                "solver_calls": result_value.resources.solver_calls,
                "solver_steps": (
                    result_value.resources.solver_steps
                    + verification_value.verification_steps
                ),
                "tool_calls": 0,
            },
        },
        clock=FIXED_TIME + timedelta(seconds=2),
        sender=HOST_ID,
    )


def reference(path: Path) -> ArtifactReference:
    """Create a canonical repo-relative content reference."""

    absolute = path if path.is_absolute() else ROOT / path
    return ArtifactReference(
        absolute.resolve(strict=True).relative_to(ROOT.resolve(strict=True)).as_posix(),
        hashlib.sha256(absolute.read_bytes()).hexdigest().upper(),
    )


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")
