"""Reference finite-domain solver and pure-verification behavior."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sdaqf.application.solver import SolverService
from sdaqf.application.solver_verification import SolverVerificationService
from sdaqf.domain.scheduler import MailboxMessage, SchedulerState, TaskState
from sdaqf.domain.solver import (
    SolverRequiredClaim,
    SolverResult,
    SolverResultStatus,
    SolverVerification,
    SolverVerificationOutcome,
)
from tests.m6_scheduler_helpers import ROOT
from tests.m7_solver_helpers import (
    FIXED_TIME,
    HOST_ID,
    build_fixture,
    infeasible_problem,
    mixed_constraint_problem,
    solver_task_result,
    start_solver_lease,
)


def test_reference_solver_is_deterministic_and_verification_allows_adoption(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path)
    store, dispatch = start_solver_lease(fixture)
    dispatch_value = dispatch.value
    assert isinstance(dispatch_value, MailboxMessage)
    assert dispatch_value.lease_id is not None

    result = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        dispatch_value.lease_id,
        fixture.result_path,
    )
    result_value = result.value
    assert isinstance(result_value, SolverResult)
    assert result_value.status is SolverResultStatus.OPTIMAL
    assert result_value.witness is not None
    assert result_value.witness.assignments == (("START_A", 0), ("START_B", 2))
    assert result_value.objective_value == 2
    assert result_value.resources.solver_steps == 16

    verification = SolverVerificationService().verify(
        fixture.result_path,
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        dispatch_value.lease_id,
        fixture.verification_path,
    )
    verification_value = verification.value
    assert isinstance(verification_value, SolverVerification)
    assert verification_value.outcome is SolverVerificationOutcome.VERIFIED
    assert verification_value.adoption_allowed
    assert verification_value.verification_steps == 16

    message = solver_task_result(
        dispatch,
        result,
        verification,
        fixture.result_path,
        fixture.verification_path,
    )
    tick = store.tick(ROOT, HOST_ID, (message,), FIXED_TIME + timedelta(seconds=2))
    projection = tick.state.value
    assert isinstance(projection, SchedulerState)
    task = projection.tasks[0]
    assert task.state is TaskState.COMPLETED


def test_reference_solver_reports_infeasible_after_complete_search(tmp_path: Path) -> None:
    fixture = build_fixture(
        tmp_path,
        problem=infeasible_problem(),
        solve_steps=1,
        verification_steps=1,
    )
    _, dispatch = start_solver_lease(fixture)
    dispatch_value = dispatch.value
    assert isinstance(dispatch_value, MailboxMessage)
    assert dispatch_value.lease_id is not None
    result = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        dispatch_value.lease_id,
        fixture.result_path,
    )
    value = result.value
    assert isinstance(value, SolverResult)
    assert value.status is SolverResultStatus.INFEASIBLE
    assert value.resources.visited_assignments == 1


def test_step_limit_truthfully_distinguishes_bounded_and_unknown(tmp_path: Path) -> None:
    bounded_fixture = build_fixture(
        tmp_path / "bounded",
        required_claim=SolverRequiredClaim.BOUNDED,
        solve_steps=3,
        verification_steps=16,
    )
    _, bounded_dispatch = start_solver_lease(bounded_fixture)
    bounded_value = bounded_dispatch.value
    assert isinstance(bounded_value, MailboxMessage)
    assert bounded_value.lease_id is not None
    bounded = SolverService().run(
        bounded_fixture.request_path,
        bounded_fixture.registry_path,
        bounded_fixture.graph_path,
        bounded_fixture.state_path,
        ROOT,
        HOST_ID,
        bounded_value.lease_id,
        bounded_fixture.result_path,
    ).value
    assert isinstance(bounded, SolverResult)
    assert bounded.status is SolverResultStatus.BOUNDED

    unknown_fixture = build_fixture(
        tmp_path / "unknown",
        required_claim=SolverRequiredClaim.BOUNDED,
        solve_steps=1,
        verification_steps=16,
    )
    _, unknown_dispatch = start_solver_lease(unknown_fixture)
    unknown_value = unknown_dispatch.value
    assert isinstance(unknown_value, MailboxMessage)
    assert unknown_value.lease_id is not None
    unknown = SolverService().run(
        unknown_fixture.request_path,
        unknown_fixture.registry_path,
        unknown_fixture.graph_path,
        unknown_fixture.state_path,
        ROOT,
        HOST_ID,
        unknown_value.lease_id,
        unknown_fixture.result_path,
    ).value
    assert isinstance(unknown, SolverResult)
    assert unknown.status is SolverResultStatus.UNKNOWN


def test_all_constraint_variants_and_maximization_are_executed(tmp_path: Path) -> None:
    fixture = build_fixture(
        tmp_path,
        problem=mixed_constraint_problem(),
        solve_steps=9,
        verification_steps=9,
    )
    _, dispatch = start_solver_lease(fixture)
    dispatch_value = dispatch.value
    assert isinstance(dispatch_value, MailboxMessage)
    assert dispatch_value.lease_id is not None
    result = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        dispatch_value.lease_id,
        fixture.result_path,
    ).value
    assert isinstance(result, SolverResult)
    assert result.status is SolverResultStatus.OPTIMAL
    assert result.witness is not None
    assert result.witness.assignments == (("START_A", 0), ("START_B", 2))
    assert result.objective_value == 4
