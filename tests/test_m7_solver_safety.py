"""Fail-closed M7 path, timeout, optional-adapter, and error behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from sdaqf.adapters.solver import (
    FiniteDomainReferenceAdapter,
    SolverAdapterError,
    SQLiteSolverLeaseEvidenceReader,
    evaluate_objective,
    objective_domain_bounds,
)
from sdaqf.application.scheduler_contracts import LoadedSchedulerArtifact
from sdaqf.application.solver import SolverService
from sdaqf.application.solver_contracts import SolverContractError
from sdaqf.application.solver_verification import SolverVerificationService
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.scheduler import MailboxMessage
from sdaqf.domain.solver import (
    LoadedSolverArtifact,
    SolverAdapterDefinition,
    SolverAdapterKind,
    SolverRegistry,
    SolverRequest,
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
    feasibility_problem,
    mixed_constraint_problem,
    reference,
    registry_with_external_adapter,
    start_solver_lease,
)


class FailingAdapter:
    """Controlled failing adapter test double."""

    def solve(
        self,
        request: LoadedSolverArtifact,
        request_reference: ArtifactReference,
        adapter: SolverAdapterDefinition,
        lease: object,
    ) -> LoadedSolverArtifact:
        raise SolverAdapterError("controlled adapter failure")


class MustNotRunAdapter:
    """Fail loudly if an external adapter crosses the execution boundary."""

    called = False

    def solve(
        self,
        request: LoadedSolverArtifact,
        request_reference: ArtifactReference,
        adapter: SolverAdapterDefinition,
        lease: object,
    ) -> LoadedSolverArtifact:
        self.called = True
        raise AssertionError("external adapter execution was attempted")


class ImmediateTimeoutClock:
    """Deterministically reaches the request duration before enumeration."""

    def __init__(self) -> None:
        self._monotonic = 0

    def now(self) -> datetime:
        return FIXED_TIME

    def monotonic_milliseconds(self) -> int:
        observed = self._monotonic
        self._monotonic += 1
        return observed


def test_controlled_adapter_failure_publishes_error_without_proof(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    result = SolverService(adapter=FailingAdapter()).run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    ).value
    assert isinstance(result, SolverResult)
    assert result.status is SolverResultStatus.ERROR
    assert result.diagnostic_code == "adapter-error"
    assert result.witness is None
    assert result.resources.solver_calls == 1
    assert result.resources.solver_steps == 0


def test_timeout_and_optional_external_adapter_are_truthful(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path, timeout_milliseconds=1)
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    request = fixture.request.value
    registry = fixture.registry.value
    assert isinstance(request, SolverRequest)
    assert isinstance(registry, SolverRegistry)
    adapter = registry.adapters[0]
    lease = SQLiteSolverLeaseEvidenceReader().observe(
        fixture.state_path,
        ROOT,
        graph_id=request.graph_id,
        task_id=request.task_id,
        host_id=HOST_ID,
        lease_id=lease_id,
        require_current=True,
    )
    timed_out = FiniteDomainReferenceAdapter(ImmediateTimeoutClock()).solve(
        fixture.request,
        reference(fixture.request_path),
        adapter,
        lease,
    ).value
    assert isinstance(timed_out, SolverResult)
    assert timed_out.status is SolverResultStatus.TIMEOUT
    assert timed_out.diagnostic_code == "request-timeout"
    assert timed_out.resources.solver_steps == 0

    external = replace(
        adapter,
        adapter_id="optional-local-cli",
        adapter_kind=SolverAdapterKind.EXTERNAL_CLI,
        optional=True,
        tool_name="z3",
        executable="z3",
        input_format="smt2",
    )
    unavailable = FiniteDomainReferenceAdapter(ImmediateTimeoutClock()).solve(
        fixture.request,
        reference(fixture.request_path),
        external,
        lease,
    ).value
    assert isinstance(unavailable, SolverResult)
    assert unavailable.status is SolverResultStatus.UNAVAILABLE
    assert unavailable.resources.solver_calls == 0


def test_external_adapter_service_boundary_is_zero_use_and_unadoptable(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(
        tmp_path,
        registry=registry_with_external_adapter(),
        adapter_id="optional-local-cli",
    )
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    adapter = MustNotRunAdapter()
    result = SolverService(adapter=adapter).run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    ).value
    assert not adapter.called
    assert isinstance(result, SolverResult)
    assert result.status is SolverResultStatus.UNAVAILABLE
    assert result.resources.solver_calls == 0
    assert result.resources.solver_steps == 0
    verification = SolverVerificationService().verify(
        fixture.result_path,
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.verification_path,
    ).value
    assert isinstance(verification, SolverVerification)
    assert verification.outcome is SolverVerificationOutcome.INCONCLUSIVE
    assert not verification.adoption_allowed
    assert next(
        check.passed for check in verification.checks if check.check_id == "resource-accounting"
    )


def test_selected_adapter_search_space_limit_is_enforced(tmp_path: Path) -> None:
    registry = registry_with_external_adapter()
    external, reference_adapter = registry.adapters
    constrained = replace(external, max_search_space=1)
    fixture = build_fixture(
        tmp_path,
        registry=replace(registry, adapters=(constrained, reference_adapter)),
        adapter_id=constrained.adapter_id,
    )
    with pytest.raises(SolverContractError, match="adapter capability"):
        SolverService().validate_request(
            fixture.request_path,
            fixture.registry_path,
            fixture.graph_path,
            ROOT,
        )


def test_outputs_are_exclusive_and_inputs_must_remain_under_root(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    service = SolverService()
    service.run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    )
    with pytest.raises(SolverContractError, match="fresh JSON"):
        service.run(
            fixture.request_path,
            fixture.registry_path,
            fixture.graph_path,
            fixture.state_path,
            ROOT,
            HOST_ID,
            lease_id,
            fixture.result_path,
        )
    with pytest.raises(SolverContractError):
        service.validate_registry(ROOT.parent / "outside.json", ROOT)


def test_linked_or_reparse_input_ancestor_is_rejected_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_fixture(tmp_path)
    monkeypatch.setattr(
        "sdaqf.application.solver.is_reparse_point",
        lambda path: path == fixture.directory or is_reparse_point(path),
    )
    with pytest.raises(SolverContractError, match="linked or reparse"):
        SolverService().validate_request(
            fixture.request_path,
            fixture.registry_path,
            fixture.graph_path,
            ROOT,
        )


def test_external_adapter_must_match_exact_tool_registry_entry(tmp_path: Path) -> None:
    registry = registry_with_external_adapter()
    external, reference_adapter = registry.adapters
    fixture = build_fixture(
        tmp_path,
        registry=replace(
            registry,
            adapters=(replace(external, executable="not-z3"), reference_adapter),
        ),
        adapter_id=external.adapter_id,
    )
    with pytest.raises(SolverContractError, match="Tool Registry entry"):
        SolverService().validate_registry(fixture.registry_path, ROOT)


def test_reference_adapter_rejects_wrong_identity_and_observes_lease_deadline(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path)
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    request = fixture.request.value
    registry = fixture.registry.value
    assert isinstance(request, SolverRequest)
    assert isinstance(registry, SolverRegistry)
    adapter = registry.adapters[0]
    lease = SQLiteSolverLeaseEvidenceReader().observe(
        fixture.state_path,
        ROOT,
        graph_id=request.graph_id,
        task_id=request.task_id,
        host_id=HOST_ID,
        lease_id=lease_id,
        require_current=True,
    )
    solver = FiniteDomainReferenceAdapter(ImmediateTimeoutClock())
    with pytest.raises(SolverAdapterError, match="Solver Request"):
        solver.solve(fixture.registry, reference(fixture.registry_path), adapter, lease)
    with pytest.raises(SolverAdapterError, match="adapter identity"):
        solver.solve(
            fixture.request,
            reference(fixture.request_path),
            replace(adapter, adapter_id="wrong-reference"),
            lease,
        )
    expired = solver.solve(
        fixture.request,
        reference(fixture.request_path),
        adapter,
        replace(lease, expires_at="2029-12-31T23:59:59Z"),
    ).value
    assert isinstance(expired, SolverResult)
    assert expired.status is SolverResultStatus.TIMEOUT
    assert expired.diagnostic_code == "lease-deadline"


def test_feasibility_has_no_objective_and_maximization_bound_is_directional(
    tmp_path: Path,
) -> None:
    feasibility = feasibility_problem(satisfiable=True)
    with pytest.raises(SolverAdapterError, match="no objective"):
        evaluate_objective(feasibility, {"X": 1})
    with pytest.raises(SolverAdapterError, match="no objective bounds"):
        objective_domain_bounds(feasibility)

    fixture = build_fixture(
        tmp_path,
        problem=mixed_constraint_problem(),
        required_claim=SolverRequiredClaim.BOUNDED,
        solve_steps=2,
        verification_steps=9,
    )
    _, dispatch = start_solver_lease(fixture)
    bounded = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        _lease_id(dispatch),
        fixture.result_path,
    ).value
    assert isinstance(bounded, SolverResult)
    assert bounded.status is SolverResultStatus.BOUNDED
    assert bounded.objective_interval is not None
    assert bounded.objective_interval.lower == bounded.objective_value
    assert bounded.objective_interval.upper > bounded.objective_interval.lower


def _lease_id(dispatch: LoadedSchedulerArtifact) -> str:
    value = dispatch.value
    assert isinstance(value, MailboxMessage)
    assert value.lease_id is not None
    return value.lease_id
