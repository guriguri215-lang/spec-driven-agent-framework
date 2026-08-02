"""Independent M7 witness, proof, claim, and lease verification tests."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import sdaqf.application.solver_verification as solver_verification_module
from sdaqf.adapters.scheduler import SchedulerAdapterError, recover_scheduler_database
from sdaqf.adapters.solver import (
    FiniteDomainReferenceAdapter,
    SQLiteSolverLeaseEvidenceReader,
)
from sdaqf.adapters.solver import evaluate_constraints as evaluate_solver_constraints
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    SchedulerContractError,
)
from sdaqf.application.solver import SolverService
from sdaqf.application.solver_contracts import (
    SolverContractError,
    artifact_from_value,
    serialize_solver_artifact,
    solver_identity,
)
from sdaqf.application.solver_verification import (
    SolverVerificationService,
    validate_solver_task_result_evidence,
    verify_loaded_solver_result,
)
from sdaqf.domain.scheduler import MailboxMessage
from sdaqf.domain.solver import (
    LoadedSolverArtifact,
    SolverArtifactType,
    SolverProblem,
    SolverProofDisposition,
    SolverRegistry,
    SolverRequest,
    SolverRequiredClaim,
    SolverResult,
    SolverResultStatus,
    SolverTerminationReason,
    SolverVerification,
    SolverVerificationOutcome,
    SolverWitness,
)
from tests.m6_scheduler_helpers import ROOT
from tests.m7_solver_helpers import (
    FIXED_TIME,
    HOST_ID,
    build_fixture,
    feasibility_problem,
    reference,
    solver_task_result,
    start_solver_lease,
)


def test_forged_witness_is_rejected_by_independent_re_evaluation(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    genuine = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    )
    value = genuine.value
    assert isinstance(value, SolverResult)
    forged_value = replace(
        value,
        witness=SolverWitness((("START_A", 0), ("START_B", 0))),
        objective_value=0,
    )
    forged = artifact_from_value(SolverArtifactType.RESULT, forged_value)
    forged_path = tmp_path / "forged-result.json"
    forged_path.write_bytes(serialize_solver_artifact(forged))
    verification = SolverVerificationService().verify(
        forged_path,
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
    assert verification.outcome is SolverVerificationOutcome.REJECTED
    assert not verification.adoption_allowed
    assert "failed-witness-feasibility" in verification.reasons


def test_rejected_early_witness_reports_only_actual_evaluations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_fixture(tmp_path, required_claim=SolverRequiredClaim.FEASIBLE)
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    genuine = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    ).value
    assert isinstance(genuine, SolverResult)
    assert genuine.resources.unvisited_assignments > 0
    forged_resources = replace(
        genuine.resources,
        solver_steps=genuine.resources.solver_steps + 1,
        visited_assignments=genuine.resources.visited_assignments + 1,
        unvisited_assignments=genuine.resources.unvisited_assignments - 1,
    )
    forged = artifact_from_value(
        SolverArtifactType.RESULT,
        replace(genuine, resources=forged_resources),
    )
    forged_path = tmp_path / "forged-early-witness-result.json"
    forged_path.write_bytes(serialize_solver_artifact(forged))

    actual_evaluations = 0

    def count_evaluation(
        problem: SolverProblem,
        values: Mapping[str, int],
    ) -> tuple[bool, int]:
        nonlocal actual_evaluations
        actual_evaluations += 1
        return evaluate_solver_constraints(problem, values)

    monkeypatch.setattr(
        solver_verification_module,
        "evaluate_constraints",
        count_evaluation,
    )
    verification = SolverVerificationService().verify(
        forged_path,
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
    assert verification.outcome is SolverVerificationOutcome.REJECTED
    assert not verification.adoption_allowed
    assert actual_evaluations == genuine.resources.visited_assignments
    assert verification.verification_steps == actual_evaluations


def test_forged_resource_and_termination_evidence_cannot_be_adopted(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path)
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    genuine = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    )
    value = genuine.value
    assert isinstance(value, SolverResult)
    zero_use = replace(
        value.resources,
        solver_calls=0,
        solver_steps=0,
        visited_assignments=0,
        unvisited_assignments=value.resources.search_space_size,
        constraint_checks=0,
        termination_reason=SolverTerminationReason.ADAPTER_UNAVAILABLE,
    )
    with pytest.raises(SolverContractError):
        artifact_from_value(
            SolverArtifactType.RESULT,
            replace(value, resources=zero_use),
        )

    forged = artifact_from_value(
        SolverArtifactType.RESULT,
        replace(value, resources=replace(value.resources, constraint_checks=0)),
    )
    forged_path = tmp_path / "forged-resources.json"
    forged_path.write_bytes(serialize_solver_artifact(forged))
    verification = SolverVerificationService().verify(
        forged_path,
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
    assert verification.outcome is SolverVerificationOutcome.REJECTED
    assert verification.reasons == ("failed-resource-accounting",)
    assert not verification.adoption_allowed

    forged_elapsed_value = replace(
        value,
        resources=replace(value.resources, elapsed_milliseconds=12_345),
    )
    with pytest.raises(SolverContractError, match="canonical zero elapsed"):
        artifact_from_value(SolverArtifactType.RESULT, forged_elapsed_value)
    registry = fixture.registry.value
    assert isinstance(registry, SolverRegistry)
    elapsed_verification = verify_loaded_solver_result(
        fixture.request,
        replace(genuine, value=forged_elapsed_value),
        reference(fixture.request_path),
        reference(fixture.result_path),
        registry.adapters[0],
        value.lease,
        result_size_bytes=fixture.result_path.stat().st_size,
    ).value
    assert isinstance(elapsed_verification, SolverVerification)
    assert elapsed_verification.outcome is SolverVerificationOutcome.REJECTED
    assert not elapsed_verification.adoption_allowed
    assert "failed-resource-accounting" in elapsed_verification.reasons


def test_solver_work_beyond_the_separate_solve_cap_is_rejected(tmp_path: Path) -> None:
    fixture = build_fixture(
        tmp_path,
        problem=feasibility_problem(satisfiable=True),
        required_claim=SolverRequiredClaim.DECISION,
        solve_steps=1,
        verification_steps=3,
    )
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    result_artifact = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    )
    result = result_artifact.value
    assert isinstance(result, SolverResult)
    assert result.status is SolverResultStatus.UNKNOWN
    over_cap_resources = replace(
        result.resources,
        solver_steps=2,
        visited_assignments=2,
        unvisited_assignments=0,
        constraint_checks=2,
        termination_reason=SolverTerminationReason.WITNESS_FOUND,
    )
    over_cap_result = replace(
        result,
        status=SolverResultStatus.SATISFIABLE,
        witness=SolverWitness((("X", 1),)),
        proof_disposition=SolverProofDisposition.WITNESS,
        resources=over_cap_resources,
        diagnostic_code=None,
    )
    with pytest.raises(SolverContractError, match="solve step limit"):
        artifact_from_value(SolverArtifactType.RESULT, over_cap_result)

    direct_artifact = replace(
        result_artifact,
        artifact_id=solver_identity(SolverArtifactType.RESULT, over_cap_result.to_dict()),
        value=over_cap_result,
    )
    registry = fixture.registry.value
    assert isinstance(registry, SolverRegistry)
    verification = verify_loaded_solver_result(
        fixture.request,
        direct_artifact,
        reference(fixture.request_path),
        reference(fixture.result_path),
        registry.adapters[0],
        result.lease,
        result_size_bytes=fixture.result_path.stat().st_size,
    ).value
    assert isinstance(verification, SolverVerification)
    assert verification.outcome is SolverVerificationOutcome.REJECTED
    assert verification.reasons == ("failed-resource-accounting",)
    assert verification.verification_steps == 0
    assert not verification.adoption_allowed


def test_raw_result_byte_limit_is_replayed_by_verifier_scheduler_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_fixture(tmp_path, max_result_bytes=4_096)
    store, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    request = fixture.request.value
    registry = fixture.registry.value
    assert isinstance(request, SolverRequest)
    assert isinstance(registry, SolverRegistry)
    lease = SQLiteSolverLeaseEvidenceReader().observe(
        fixture.state_path,
        ROOT,
        graph_id=request.graph_id,
        task_id=request.task_id,
        host_id=HOST_ID,
        lease_id=lease_id,
        require_current=True,
    )
    result_artifact = FiniteDomainReferenceAdapter().solve(
        fixture.request,
        reference(fixture.request_path),
        registry.adapters[0],
        lease,
    )
    canonical = serialize_solver_artifact(result_artifact)
    assert len(canonical) < request.resource_policy.max_result_bytes
    padding = b" " * (request.resource_policy.max_result_bytes - len(canonical) + 1)
    raw_result = canonical + padding
    fixture.result_path.write_bytes(raw_result)
    assert fixture.result_path.stat().st_size == request.resource_policy.max_result_bytes + 1

    verification_artifact = SolverVerificationService().verify(
        fixture.result_path,
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.verification_path,
    )
    verification = verification_artifact.value
    assert isinstance(verification, SolverVerification)
    assert verification.outcome is SolverVerificationOutcome.REJECTED
    assert verification.reasons == ("failed-resource-accounting",)
    assert verification.verification_steps == 0
    assert not verification.adoption_allowed

    message = solver_task_result(
        dispatch,
        result_artifact,
        verification_artifact,
        fixture.result_path,
        fixture.verification_path,
    )
    with pytest.raises(SchedulerContractError, match="evidence is invalid"):
        store.tick(ROOT, HOST_ID, (message,), FIXED_TIME + timedelta(seconds=2))

    failed_message = solver_task_result(
        dispatch,
        result_artifact,
        verification_artifact,
        fixture.result_path,
        fixture.verification_path,
        outcome="failed",
    )
    with pytest.raises(SchedulerContractError, match="evidence is invalid"):
        store.tick(
            ROOT,
            HOST_ID,
            (failed_message,),
            FIXED_TIME + timedelta(seconds=2),
        )

    def accept_legacy_oversized_evidence(
        *args: object,
        **kwargs: object,
    ) -> tuple[LoadedSolverArtifact, LoadedSolverArtifact]:
        return result_artifact, verification_artifact

    with monkeypatch.context() as patch:
        patch.setattr(
            solver_verification_module,
            "validate_solver_task_result_evidence",
            accept_legacy_oversized_evidence,
        )
        accepted = store.tick(
            ROOT,
            HOST_ID,
            (failed_message,),
            FIXED_TIME + timedelta(seconds=2),
        )
    assert accepted.accepted_message_ids == (failed_message.artifact_id,)

    with pytest.raises(
        (SchedulerAdapterError, SchedulerContractError),
        match="evidence is invalid",
    ):
        store.validate()
    recovered = tmp_path / "oversized-result-recovered.sqlite3"
    with pytest.raises(
        (SchedulerAdapterError, SchedulerContractError),
        match="evidence is invalid",
    ):
        recover_scheduler_database(store.path, recovered, ROOT)
    assert not recovered.exists()


def test_failed_task_accepts_truthful_inconclusive_solver_evidence(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path, solve_steps=1, verification_steps=16)
    store, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    result_artifact = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    )
    verification_artifact = SolverVerificationService().verify(
        fixture.result_path,
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.verification_path,
    )
    verification = verification_artifact.value
    assert isinstance(verification, SolverVerification)
    assert verification.outcome is SolverVerificationOutcome.INCONCLUSIVE
    assert not verification.adoption_allowed
    failed_message = solver_task_result(
        dispatch,
        result_artifact,
        verification_artifact,
        fixture.result_path,
        fixture.verification_path,
        outcome="failed",
    )
    accepted = store.tick(
        ROOT,
        HOST_ID,
        (failed_message,),
        FIXED_TIME + timedelta(seconds=2),
    )
    assert accepted.accepted_message_ids == (failed_message.artifact_id,)
    store.validate()
    recovered = recover_scheduler_database(
        store.path,
        tmp_path / "truthful-failed-recovered.sqlite3",
        ROOT,
    )
    assert recovered.status() == store.status()


def test_verification_budget_shortage_is_inconclusive_not_rejection(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path, solve_steps=16, verification_steps=1)
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    )
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
    assert verification.reasons == ("verification-step-limit",)
    assert not verification.adoption_allowed


def test_resource_prefix_replay_is_bounded_and_fully_accounted(tmp_path: Path) -> None:
    fixture = build_fixture(
        tmp_path,
        required_claim=SolverRequiredClaim.BOUNDED,
        solve_steps=3,
        verification_steps=1,
    )
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    result = SolverService().run(
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
    assert result.status is SolverResultStatus.BOUNDED
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
    assert verification.reasons == ("verification-step-limit",)
    assert verification.verification_steps == 1
    assert not verification.adoption_allowed


def test_verification_reauthenticates_historical_lease_evidence(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path)
    store, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    result = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    )
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
    )
    message = solver_task_result(
        dispatch,
        result,
        verification,
        fixture.result_path,
        fixture.verification_path,
    )
    completed = store.tick(
        ROOT,
        HOST_ID,
        (message,),
        FIXED_TIME + timedelta(seconds=2),
    )
    assert completed.accepted_message_ids == (message.artifact_id,)

    historical = SolverVerificationService().verify(
        fixture.result_path,
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        tmp_path / "historical-verification.json",
    )
    assert historical.to_dict() == verification.to_dict()


def test_scheduler_rejects_evidence_for_a_different_graph_and_contract(
    tmp_path: Path,
) -> None:
    intended = build_fixture(tmp_path / "intended")
    evidence = build_fixture(
        tmp_path / "evidence",
        problem=feasibility_problem(satisfiable=True),
        required_claim=SolverRequiredClaim.DECISION,
    )
    assert intended.graph.artifact_id != evidence.graph.artifact_id
    assert intended.token != evidence.token

    intended_store, intended_dispatch = start_solver_lease(intended)
    intended_lease_id = _lease_id(intended_dispatch)
    intended_result = SolverService().run(
        intended.request_path,
        intended.registry_path,
        intended.graph_path,
        intended.state_path,
        ROOT,
        HOST_ID,
        intended_lease_id,
        intended.result_path,
    ).value
    assert isinstance(intended_result, SolverResult)

    _, evidence_dispatch = start_solver_lease(evidence)
    evidence_lease_id = _lease_id(evidence_dispatch)
    evidence_result_artifact = SolverService().run(
        evidence.request_path,
        evidence.registry_path,
        evidence.graph_path,
        evidence.state_path,
        ROOT,
        HOST_ID,
        evidence_lease_id,
        evidence.result_path,
    )
    evidence_verification_artifact = SolverVerificationService().verify(
        evidence.result_path,
        evidence.request_path,
        evidence.registry_path,
        evidence.graph_path,
        evidence.state_path,
        ROOT,
        HOST_ID,
        evidence_lease_id,
        evidence.verification_path,
    )
    evidence_result = evidence_result_artifact.value
    evidence_verification = evidence_verification_artifact.value
    assert isinstance(evidence_result, SolverResult)
    assert isinstance(evidence_verification, SolverVerification)
    assert evidence_verification.adoption_allowed

    mismatched_result = artifact_from_value(
        SolverArtifactType.RESULT,
        replace(evidence_result, lease=intended_result.lease),
    )
    mismatched_result_path = evidence.directory / "mismatched-result.json"
    mismatched_result_path.write_bytes(serialize_solver_artifact(mismatched_result))
    evidence_registry = evidence.registry.value
    assert isinstance(evidence_registry, SolverRegistry)
    replayed = verify_loaded_solver_result(
        evidence.request,
        mismatched_result,
        reference(evidence.request_path),
        reference(mismatched_result_path),
        evidence_registry.adapters[0],
        intended_result.lease,
        result_size_bytes=mismatched_result_path.stat().st_size,
    ).value
    assert isinstance(replayed, SolverVerification)
    assert replayed.outcome is SolverVerificationOutcome.REJECTED
    assert replayed.reasons == ("failed-lease-authority",)
    assert not replayed.adoption_allowed

    mismatched_verification = artifact_from_value(
        SolverArtifactType.VERIFICATION,
        replace(
            evidence_verification,
            result=reference(mismatched_result_path),
            result_id=mismatched_result.artifact_id,
            lease=intended_result.lease,
        ),
    )
    mismatched_verification_path = evidence.directory / "mismatched-verification.json"
    mismatched_verification_path.write_bytes(
        serialize_solver_artifact(mismatched_verification)
    )
    message = solver_task_result(
        intended_dispatch,
        mismatched_result,
        mismatched_verification,
        mismatched_result_path,
        mismatched_verification_path,
    )
    with pytest.raises(SchedulerContractError, match="evidence is invalid"):
        intended_store.tick(
            ROOT,
            HOST_ID,
            (message,),
            FIXED_TIME + timedelta(seconds=2),
        )


def test_incomplete_result_and_unsatisfied_claim_are_never_adopted(tmp_path: Path) -> None:
    incomplete = build_fixture(
        tmp_path / "incomplete",
        required_claim=SolverRequiredClaim.OPTIMAL,
        solve_steps=1,
        verification_steps=16,
    )
    _, dispatch = start_solver_lease(incomplete)
    lease_id = _lease_id(dispatch)
    result = SolverService().run(
        incomplete.request_path,
        incomplete.registry_path,
        incomplete.graph_path,
        incomplete.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        incomplete.result_path,
    ).value
    assert isinstance(result, SolverResult)
    assert result.status is SolverResultStatus.UNKNOWN
    verification = SolverVerificationService().verify(
        incomplete.result_path,
        incomplete.request_path,
        incomplete.registry_path,
        incomplete.graph_path,
        incomplete.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        incomplete.verification_path,
    ).value
    assert isinstance(verification, SolverVerification)
    assert verification.outcome is SolverVerificationOutcome.INCONCLUSIVE
    assert not verification.adoption_allowed


def test_scheduler_evidence_replay_rejects_every_payload_contradiction(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path)
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    result_artifact = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    )
    verification_artifact = SolverVerificationService().verify(
        fixture.result_path,
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.verification_path,
    )
    result = result_artifact.value
    verification = verification_artifact.value
    assert isinstance(result, SolverResult)
    assert isinstance(verification, SolverVerification)
    result_ref = reference(fixture.result_path).to_dict()
    verification_ref = reference(fixture.verification_path).to_dict()
    payload: dict[str, object] = {
        "evidence_refs": sorted(
            (result_ref, verification_ref), key=lambda item: str(item["path"])
        ),
        "budget_usage": {
            "microunits": 0,
            "solver_calls": result.resources.solver_calls,
            "solver_steps": result.resources.solver_steps + verification.verification_steps,
            "tool_calls": 0,
        },
        "outcome": "succeeded",
        "effect_observed": "none",
    }
    validate_solver_task_result_evidence(
        ROOT,
        payload,
        result.lease,
        expected_graph_id=result.graph_id,
        expected_task_id=result.task_id,
        expected_solver_capability=fixture.token,
    )

    invalid_payloads = []
    one_reference = deepcopy(payload)
    one_reference["evidence_refs"] = [result_ref]
    invalid_payloads.append(one_reference)
    malformed = deepcopy(payload)
    malformed["evidence_refs"] = [result_ref, {"path": "missing"}]
    invalid_payloads.append(malformed)
    same_type = deepcopy(payload)
    same_type["evidence_refs"] = [result_ref, result_ref]
    invalid_payloads.append(same_type)
    missing_usage = deepcopy(payload)
    missing_usage["budget_usage"] = None
    invalid_payloads.append(missing_usage)
    wrong_usage = deepcopy(payload)
    wrong_usage_value = wrong_usage["budget_usage"]
    assert isinstance(wrong_usage_value, dict)
    steps = wrong_usage_value["solver_steps"]
    assert isinstance(steps, int)
    wrong_usage_value["solver_steps"] = steps + 1
    invalid_payloads.append(wrong_usage)
    wrong_effect = deepcopy(payload)
    wrong_effect["effect_observed"] = "possible"
    invalid_payloads.append(wrong_effect)
    failed_adoptable = deepcopy(payload)
    failed_adoptable["outcome"] = "failed"
    invalid_payloads.append(failed_adoptable)
    for invalid in invalid_payloads:
        with pytest.raises(SolverContractError):
            validate_solver_task_result_evidence(
                ROOT,
                invalid,
                result.lease,
                expected_graph_id=result.graph_id,
                expected_task_id=result.task_id,
                expected_solver_capability=fixture.token,
            )


def test_successful_scheduler_payload_cannot_adopt_inconclusive_result(
    tmp_path: Path,
) -> None:
    fixture = build_fixture(tmp_path, solve_steps=1, verification_steps=16)
    _, dispatch = start_solver_lease(fixture)
    lease_id = _lease_id(dispatch)
    result_artifact = SolverService().run(
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.result_path,
    )
    verification_artifact = SolverVerificationService().verify(
        fixture.result_path,
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        fixture.verification_path,
    )
    result = result_artifact.value
    verification = verification_artifact.value
    assert isinstance(result, SolverResult)
    assert isinstance(verification, SolverVerification)
    payload: dict[str, object] = {
        "evidence_refs": sorted(
            (
                reference(fixture.result_path).to_dict(),
                reference(fixture.verification_path).to_dict(),
            ),
            key=lambda item: str(item["path"]),
        ),
        "budget_usage": {
            "microunits": 0,
            "solver_calls": result.resources.solver_calls,
            "solver_steps": result.resources.solver_steps + verification.verification_steps,
            "tool_calls": 0,
        },
        "outcome": "succeeded",
        "effect_observed": "none",
    }
    with pytest.raises(SolverContractError, match="lacks adoption"):
        validate_solver_task_result_evidence(
            ROOT,
            payload,
            result.lease,
            expected_graph_id=result.graph_id,
            expected_task_id=result.task_id,
            expected_solver_capability=fixture.token,
        )

    unmet = build_fixture(
        tmp_path / "unmet",
        required_claim=SolverRequiredClaim.OPTIMAL,
        solve_steps=3,
        verification_steps=16,
    )
    _, dispatch = start_solver_lease(unmet)
    lease_id = _lease_id(dispatch)
    bounded = SolverService().run(
        unmet.request_path,
        unmet.registry_path,
        unmet.graph_path,
        unmet.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        unmet.result_path,
    ).value
    assert isinstance(bounded, SolverResult)
    assert bounded.status is SolverResultStatus.BOUNDED
    verification = SolverVerificationService().verify(
        unmet.result_path,
        unmet.request_path,
        unmet.registry_path,
        unmet.graph_path,
        unmet.state_path,
        ROOT,
        HOST_ID,
        lease_id,
        unmet.verification_path,
    ).value
    assert isinstance(verification, SolverVerification)
    assert verification.outcome is SolverVerificationOutcome.VERIFIED
    assert verification.reasons == ("required-claim-unsatisfied",)
    assert not verification.adoption_allowed


def _lease_id(dispatch: LoadedSchedulerArtifact) -> str:
    value = dispatch.value
    assert isinstance(value, MailboxMessage)
    assert value.lease_id is not None
    return value.lease_id
