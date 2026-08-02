"""Independent deterministic verification for M7 solver evidence."""

from __future__ import annotations

import hashlib
import itertools
from pathlib import Path

from sdaqf.adapters.context import ExclusiveJSONPublisher
from sdaqf.adapters.solver import (
    SQLiteSolverLeaseEvidenceReader,
    evaluate_constraints,
    evaluate_objective,
    objective_domain_bounds,
)
from sdaqf.application.solver import (
    SolverService,
    _existing_json_under_root,
    _fresh_json_under_root,
    _regular_root,
)
from sdaqf.application.solver_contracts import (
    SolverContractError,
    artifact_from_value,
    load_solver_artifact,
    parse_solver_artifact_bytes,
    search_space_size,
    serialize_solver_artifact,
    solver_capability_token,
    verify_reference,
)
from sdaqf.domain.context import SENSITIVITY_RANK
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.solver import (
    LoadedSolverArtifact,
    ObjectiveDirection,
    ObjectiveInterval,
    SolverAdapterDefinition,
    SolverAdapterKind,
    SolverArtifactType,
    SolverLeaseEvidence,
    SolverProofDisposition,
    SolverRequest,
    SolverRequiredClaim,
    SolverResult,
    SolverResultStatus,
    SolverTerminationReason,
    SolverVerification,
    SolverVerificationCheck,
    SolverVerificationOutcome,
    SolverWitness,
)
from sdaqf.ports.context import ImmutableJSONPublisher
from sdaqf.ports.solver import SolverLeaseEvidencePort


class SolverVerificationService:
    """Recompute exact result evidence before any scheduler adoption."""

    def __init__(
        self,
        *,
        lease_reader: SolverLeaseEvidencePort | None = None,
        publisher: ImmutableJSONPublisher | None = None,
    ) -> None:
        self._lease_reader = (
            SQLiteSolverLeaseEvidenceReader() if lease_reader is None else lease_reader
        )
        self._publisher = ExclusiveJSONPublisher() if publisher is None else publisher

    def verify(
        self,
        result: Path,
        request: Path,
        registry: Path,
        task_graph: Path,
        state: Path,
        root: Path,
        host_id: str,
        lease_id: str,
        output: Path,
    ) -> LoadedSolverArtifact:
        """Reauthenticate inputs and exclusively publish one pure Verification."""

        root = _regular_root(root)
        request_artifact, _, adapter = SolverService().validate_request(
            request, registry, task_graph, root
        )
        request_value = request_artifact.value
        assert isinstance(request_value, SolverRequest)
        result_path = _existing_json_under_root(root, result)
        result_bytes = _read_artifact_bytes(result_path)
        result_artifact = parse_solver_artifact_bytes(
            result_bytes,
            expected_type=SolverArtifactType.RESULT,
        )
        result_value = result_artifact.value
        assert isinstance(result_value, SolverResult)
        request_path = _existing_json_under_root(root, request)
        _require_reference_path(root, request_path, result_value.request)
        lease = self._lease_reader.observe(
            state,
            root,
            graph_id=request_value.graph_id,
            task_id=request_value.task_id,
            host_id=host_id,
            lease_id=lease_id,
            require_current=False,
        )
        verification = verify_loaded_solver_result(
            request_artifact,
            result_artifact,
            _reference_for(root, request_path),
            _reference_for_bytes(root, result_path, result_bytes),
            adapter,
            lease,
            result_size_bytes=len(result_bytes),
        )
        target = _fresh_json_under_root(root, output)
        self._publisher.publish(target, serialize_solver_artifact(verification))
        return verification


def validate_solver_task_result_evidence(
    root: Path,
    message_payload: dict[str, object],
    lease: SolverLeaseEvidence,
    *,
    expected_graph_id: str,
    expected_task_id: str,
    expected_solver_capability: str,
) -> tuple[LoadedSolverArtifact, LoadedSolverArtifact]:
    """Validate and reproduce the exact paired evidence in an M6 task result."""

    raw_refs = message_payload.get("evidence_refs")
    if not isinstance(raw_refs, list) or len(raw_refs) != 2:
        raise SolverContractError("Solver task result requires exactly two evidence references.")
    references = tuple(
        ArtifactReference(str(item["path"]), str(item["sha256"]))
        for item in raw_refs
        if isinstance(item, dict) and set(item) == {"path", "sha256"}
    )
    if len(references) != 2:
        raise SolverContractError("Solver task result evidence references are invalid.")
    resolved_paths = tuple(verify_reference(root, reference) for reference in references)
    artifact_bytes = tuple(_read_artifact_bytes(path) for path in resolved_paths)
    if any(
        hashlib.sha256(raw).hexdigest().upper() != reference.sha256
        for raw, reference in zip(artifact_bytes, references, strict=True)
    ):
        raise SolverContractError("Solver artifact changed after reference validation.")
    loaded = tuple(parse_solver_artifact_bytes(raw) for raw in artifact_bytes)
    results = tuple(item for item in loaded if item.artifact_type is SolverArtifactType.RESULT)
    verifications = tuple(
        item for item in loaded if item.artifact_type is SolverArtifactType.VERIFICATION
    )
    if len(results) != 1 or len(verifications) != 1:
        raise SolverContractError("Solver task result requires Result and Verification evidence.")
    result_artifact = results[0]
    verification_artifact = verifications[0]
    result_value = result_artifact.value
    verification_value = verification_artifact.value
    assert isinstance(result_value, SolverResult)
    assert isinstance(verification_value, SolverVerification)
    request_path = verify_reference(root, result_value.request)
    request_artifact = load_solver_artifact(request_path, expected_type=SolverArtifactType.REQUEST)
    request_value = request_artifact.value
    assert isinstance(request_value, SolverRequest)
    if (
        lease.graph_id != expected_graph_id
        or lease.task_id != expected_task_id
        or request_value.graph_id != expected_graph_id
        or request_value.task_id != expected_task_id
        or solver_capability_token(request_value) != expected_solver_capability
    ):
        raise SolverContractError("Solver evidence does not match current M6 task authority.")
    registry_path = verify_reference(root, request_value.registry)
    graph_path = verify_reference(root, request_value.task_graph)
    _, _, adapter = SolverService().validate_request(request_path, registry_path, graph_path, root)
    result_reference = next(
        reference
        for reference, artifact in zip(references, loaded, strict=True)
        if artifact.artifact_type is SolverArtifactType.RESULT
    )
    result_bytes = next(
        raw
        for raw, artifact in zip(artifact_bytes, loaded, strict=True)
        if artifact.artifact_type is SolverArtifactType.RESULT
    )
    expected = verify_loaded_solver_result(
        request_artifact,
        result_artifact,
        result_value.request,
        result_reference,
        adapter,
        lease,
        result_size_bytes=len(result_bytes),
    )
    if expected.to_dict() != verification_artifact.to_dict():
        raise SolverContractError("Solver Verification does not reproduce exact evidence.")
    if verification_value.outcome is SolverVerificationOutcome.REJECTED:
        raise SolverContractError("Rejected solver evidence cannot back a Task Result.")
    usage = message_payload.get("budget_usage")
    if not isinstance(usage, dict):
        raise SolverContractError("Solver task result budget usage is missing.")
    if (
        usage.get("solver_calls") != result_value.resources.solver_calls
        or usage.get("solver_steps")
        != result_value.resources.solver_steps + verification_value.verification_steps
        or usage.get("tool_calls") != 0
    ):
        raise SolverContractError("Solver task result budget usage contradicts evidence.")
    outcome = message_payload.get("outcome")
    effect = message_payload.get("effect_observed")
    if effect != "none":
        raise SolverContractError("M7 reference solver result must report no external effect.")
    if outcome == "succeeded" and not verification_value.adoption_allowed:
        raise SolverContractError("Successful solver task result lacks adoption authority.")
    if outcome != "succeeded" and verification_value.adoption_allowed:
        raise SolverContractError("Failed solver task result contradicts verified adoption.")
    return result_artifact, verification_artifact


def verify_loaded_solver_result(
    request_artifact: LoadedSolverArtifact,
    result_artifact: LoadedSolverArtifact,
    request_reference: ArtifactReference,
    result_reference: ArtifactReference,
    adapter: SolverAdapterDefinition,
    lease: SolverLeaseEvidence,
    *,
    result_size_bytes: int,
) -> LoadedSolverArtifact:
    """Purely reproduce one Verification from exact typed evidence."""

    request = request_artifact.value
    result = result_artifact.value
    if not isinstance(request, SolverRequest) or not isinstance(result, SolverResult):
        raise SolverContractError("Solver verification requires Request and Result artifacts.")
    checks: dict[str, bool] = {}
    checks["identity-bindings"] = (
        result.request == request_reference
        and result.request_id == request_artifact.artifact_id
        and result.contract_id == request.contract_id
        and result.candidate == request.candidate
        and result.graph_id == request.graph_id
        and result.task_id == request.task_id
        and result.context_snapshot_id == request.context_snapshot_id
        and result.adapter_id == request.adapter_id
        and SENSITIVITY_RANK[result.sensitivity] >= SENSITIVITY_RANK[request.sensitivity]
    )
    checks["lease-authority"] = result.lease == lease and (
        lease.graph_id == request.graph_id
        and lease.task_id == request.task_id
        and lease.reserved_solver_calls == 1
        and lease.reserved_solver_steps
        == request.resource_policy.max_solve_steps + request.resource_policy.max_verification_steps
    )
    checks["adapter-provenance"] = (
        result.adapter_id == adapter.adapter_id
        and result.adapter_version == adapter.version
        and result.license_expression == adapter.license_expression
        and result.provenance == adapter.provenance
    )
    replay_checks, verification_complete, verification_steps = _resource_replay_matches(
        request,
        result,
        adapter,
        lease,
        request.resource_policy.max_verification_steps,
        result_size_bytes,
    )
    checks.update(replay_checks)
    claim_allowed = _claim_allows(request.required_claim, result.status)
    checks["required-claim"] = claim_allowed

    incomplete_status = result.status in {
        SolverResultStatus.TIMEOUT,
        SolverResultStatus.UNAVAILABLE,
        SolverResultStatus.UNKNOWN,
        SolverResultStatus.ERROR,
    }
    base_checks = tuple(
        SolverVerificationCheck(check_id, passed) for check_id, passed in sorted(checks.items())
    )
    failed_nonclaim = tuple(
        check.check_id
        for check in base_checks
        if not check.passed and check.check_id != "required-claim"
    )
    reasons: tuple[str, ...]
    if failed_nonclaim:
        outcome = SolverVerificationOutcome.REJECTED
        reasons = tuple(sorted(f"failed-{check_id}" for check_id in failed_nonclaim))
    elif incomplete_status or not verification_complete:
        outcome = SolverVerificationOutcome.INCONCLUSIVE
        reasons = (
            ("verification-step-limit",)
            if not verification_complete
            else (f"result-{result.status.value}",)
        )
    else:
        outcome = SolverVerificationOutcome.VERIFIED
        reasons = () if claim_allowed else ("required-claim-unsatisfied",)
    adoption_allowed = outcome is SolverVerificationOutcome.VERIFIED and claim_allowed
    verification = SolverVerification(
        sensitivity=result.sensitivity,
        request=request_reference,
        request_id=request_artifact.artifact_id,
        result=result_reference,
        result_id=result_artifact.artifact_id,
        contract_id=request.contract_id,
        candidate=request.candidate,
        graph_id=request.graph_id,
        task_id=request.task_id,
        context_snapshot_id=request.context_snapshot_id,
        lease=lease,
        outcome=outcome,
        adoption_allowed=adoption_allowed,
        checks=base_checks,
        reasons=reasons,
        verification_steps=verification_steps,
    )
    return artifact_from_value(SolverArtifactType.VERIFICATION, verification)


def _resource_replay_matches(
    request: SolverRequest,
    result: SolverResult,
    adapter: SolverAdapterDefinition,
    lease: SolverLeaseEvidence,
    max_verification_steps: int,
    result_size_bytes: int,
) -> tuple[dict[str, bool], bool, int]:
    """Replay causal solve evidence within the exact verification-step budget."""

    resources = result.resources
    problem = request.problem
    space = search_space_size(problem)
    common = (
        resources.search_space_size == space
        and resources.step_limit == request.resource_policy.max_solve_steps
        and resources.timeout_milliseconds == request.resource_policy.timeout_milliseconds
        and resources.solver_steps == resources.visited_assignments
        and resources.solver_steps <= request.resource_policy.max_solve_steps
        and 0 < result_size_bytes <= request.resource_policy.max_result_bytes
        and resources.visited_assignments + resources.unvisited_assignments == space
        and resources.solver_calls <= lease.reserved_solver_calls
    )
    if not common:
        return _replay_checks(resource=False), True, 0
    if adapter.adapter_kind is SolverAdapterKind.EXTERNAL_CLI:
        resource = (
            resources.termination_reason is SolverTerminationReason.ADAPTER_UNAVAILABLE
            and resources.solver_calls == 0
            and resources.solver_steps == 0
            and resources.visited_assignments == 0
            and resources.unvisited_assignments == space
            and resources.constraint_checks == 0
            and resources.elapsed_milliseconds == 0
        )
        return (
            _replay_checks(
                resource=resource,
                witness=result.witness is None,
                objective=(
                    result.objective_value is None and result.objective_interval is None
                ),
                proof=(
                    result.status is SolverResultStatus.UNAVAILABLE
                    and result.proof_disposition is SolverProofDisposition.NONE
                    and result.diagnostic_code == "adapter-unavailable"
                ),
            ),
            True,
            0,
        )
    if adapter.adapter_kind is not SolverAdapterKind.REFERENCE:
        return _replay_checks(resource=False, proof=False), True, 0
    if resources.termination_reason is SolverTerminationReason.ADAPTER_ERROR:
        resource = (
            resources.solver_calls == 1
            and resources.solver_steps == 0
            and resources.visited_assignments == 0
            and resources.unvisited_assignments == space
            and resources.constraint_checks == 0
            and resources.elapsed_milliseconds == 0
        )
        return (
            _replay_checks(
                resource=resource,
                witness=result.witness is None,
                objective=(
                    result.objective_value is None and result.objective_interval is None
                ),
                proof=(
                    result.status is SolverResultStatus.ERROR
                    and result.proof_disposition is SolverProofDisposition.NONE
                    and result.diagnostic_code == "adapter-error"
                ),
            ),
            True,
            0,
        )
    if resources.solver_calls != 1 or resources.visited_assignments > space:
        return _replay_checks(resource=False), True, 0

    variable_ids = tuple(variable.variable_id for variable in problem.variables)
    domains = tuple(variable.domain.values for variable in problem.variables)
    best_assignment: tuple[int, ...] | None = None
    best_objective: int | None = None
    checks = 0
    early_witness_step: int | None = None
    replay_target = min(resources.visited_assignments, max_verification_steps)
    evaluated_steps = 0
    for step, assignment in enumerate(itertools.product(*domains), start=1):
        if step > replay_target:
            break
        evaluated_steps += 1
        values = dict(zip(variable_ids, assignment, strict=True))
        feasible, evaluated = evaluate_constraints(problem, values)
        checks += evaluated
        if not feasible:
            continue
        if problem.objective is None:
            best_assignment = assignment
            early_witness_step = step
            break
        objective = evaluate_objective(problem, values)
        if request.required_claim is SolverRequiredClaim.FEASIBLE:
            best_assignment = assignment
            best_objective = objective
            early_witness_step = step
            break
        if best_objective is None or best_assignment is None:
            best_assignment, best_objective = assignment, objective
            continue
        better = (
            objective < best_objective
            if problem.objective.direction is ObjectiveDirection.MINIMIZE
            else objective > best_objective
        )
        if better or (objective == best_objective and assignment < best_assignment):
            best_assignment, best_objective = assignment, objective
    if checks > resources.constraint_checks:
        return _replay_checks(resource=False), True, evaluated_steps
    if early_witness_step is not None and early_witness_step != resources.visited_assignments:
        return _replay_checks(resource=False, proof=False), True, evaluated_steps
    if replay_target < resources.visited_assignments:
        return _replay_checks(), False, evaluated_steps
    if checks != resources.constraint_checks:
        return _replay_checks(resource=False), True, evaluated_steps

    termination = resources.termination_reason
    diagnostic: str | None = None
    interval: ObjectiveInterval | None = None
    if termination is SolverTerminationReason.WITNESS_FOUND:
        if early_witness_step is None:
            return _replay_checks(resource=False, proof=False), True, evaluated_steps
        status = (
            SolverResultStatus.SATISFIABLE
            if problem.objective is None
            else SolverResultStatus.FEASIBLE
        )
        proof = SolverProofDisposition.WITNESS
    elif termination is SolverTerminationReason.SEARCH_EXHAUSTED:
        if resources.visited_assignments != space or early_witness_step is not None:
            return _replay_checks(resource=False, proof=False), True, evaluated_steps
        if problem.objective is None:
            status = SolverResultStatus.UNSATISFIABLE
        elif best_assignment is None:
            status = SolverResultStatus.INFEASIBLE
        else:
            status = SolverResultStatus.OPTIMAL
            assert best_objective is not None
            interval = ObjectiveInterval(best_objective, best_objective)
        proof = SolverProofDisposition.EXHAUSTIVE_ENUMERATION
    elif termination is SolverTerminationReason.STEP_LIMIT:
        if (
            resources.visited_assignments != request.resource_policy.max_solve_steps
            or resources.visited_assignments >= space
            or early_witness_step is not None
        ):
            return _replay_checks(resource=False, proof=False), True, evaluated_steps
        if problem.objective is not None and best_assignment is not None:
            status = SolverResultStatus.BOUNDED
            proof = SolverProofDisposition.OBJECTIVE_BOUND
            assert best_objective is not None
            bounds = objective_domain_bounds(problem)
            interval = (
                ObjectiveInterval(bounds.lower, best_objective)
                if problem.objective.direction is ObjectiveDirection.MINIMIZE
                else ObjectiveInterval(best_objective, bounds.upper)
            )
        else:
            status = SolverResultStatus.UNKNOWN
            proof = SolverProofDisposition.NONE
            diagnostic = "step-limit"
    elif termination in {
        SolverTerminationReason.REQUEST_TIMEOUT,
        SolverTerminationReason.LEASE_DEADLINE,
    }:
        if resources.visited_assignments >= space or early_witness_step is not None:
            return _replay_checks(resource=False, proof=False), True, evaluated_steps
        if (
            termination is SolverTerminationReason.REQUEST_TIMEOUT
            and (
                request.resource_policy.timeout_milliseconds is None
                or resources.elapsed_milliseconds
                < request.resource_policy.timeout_milliseconds
            )
        ):
            return _replay_checks(resource=False, proof=False), True, evaluated_steps
        status = SolverResultStatus.TIMEOUT
        proof = SolverProofDisposition.NONE
        diagnostic = (
            "request-timeout"
            if termination is SolverTerminationReason.REQUEST_TIMEOUT
            else "lease-deadline"
        )
    else:
        return _replay_checks(resource=False, proof=False), True, evaluated_steps

    witness = (
        None
        if best_assignment is None
        else SolverWitness(tuple(zip(variable_ids, best_assignment, strict=True)))
    )
    elapsed_valid = (
        resources.elapsed_milliseconds == 0
        if termination
        not in {SolverTerminationReason.REQUEST_TIMEOUT, SolverTerminationReason.LEASE_DEADLINE}
        else True
    )
    replay_checks = _replay_checks(
        resource=elapsed_valid,
        witness=result.witness == witness,
        objective=(
            result.objective_value == best_objective
            and result.objective_interval == interval
        ),
        proof=(
            result.status is status
            and result.proof_disposition is proof
            and result.diagnostic_code == diagnostic
        ),
    )
    return replay_checks, True, evaluated_steps


def _replay_checks(
    *,
    resource: bool = True,
    witness: bool = True,
    objective: bool = True,
    proof: bool = True,
) -> dict[str, bool]:
    return {
        "resource-accounting": resource,
        "witness-feasibility": witness,
        "objective-evidence": objective,
        "proof-disposition": proof,
    }


def _claim_allows(claim: SolverRequiredClaim, status: SolverResultStatus) -> bool:
    if claim is SolverRequiredClaim.DECISION:
        return status in {SolverResultStatus.SATISFIABLE, SolverResultStatus.UNSATISFIABLE}
    if claim is SolverRequiredClaim.FEASIBLE:
        return status in {
            SolverResultStatus.FEASIBLE,
            SolverResultStatus.BOUNDED,
            SolverResultStatus.OPTIMAL,
        }
    if claim is SolverRequiredClaim.BOUNDED:
        return status in {SolverResultStatus.BOUNDED, SolverResultStatus.OPTIMAL}
    return status is SolverResultStatus.OPTIMAL


def _require_reference_path(root: Path, path: Path, reference: ArtifactReference) -> None:
    if verify_reference(root, reference).resolve(strict=True) != path.resolve(strict=True):
        raise SolverContractError("Solver Result Request reference is inconsistent.")


def _reference_for(root: Path, path: Path) -> ArtifactReference:
    raw = _read_artifact_bytes(path)
    return _reference_for_bytes(root, path, raw)


def _reference_for_bytes(root: Path, path: Path, raw: bytes) -> ArtifactReference:
    return ArtifactReference(
        path.relative_to(root).as_posix(),
        hashlib.sha256(raw).hexdigest().upper(),
    )


def _read_artifact_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SolverContractError("Solver artifact could not be read.") from exc
