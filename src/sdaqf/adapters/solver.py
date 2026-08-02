"""Standard-library M7 finite-domain and M6 evidence adapters."""

from __future__ import annotations

import itertools
import sqlite3
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.scheduler_contracts import parse_scheduler_artifact_bytes
from sdaqf.application.solver_contracts import (
    REFERENCE_ADAPTER_ID,
    SolverContractError,
    artifact_from_value,
    search_space_size,
)
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.scheduler import (
    Lease,
    LeaseStatus,
    MailboxMessage,
    MessageType,
    SchedulerArtifactType,
)
from sdaqf.domain.solver import (
    AllDifferentConstraint,
    ClauseConstraint,
    LinearConstraint,
    LinearRelation,
    LoadedSolverArtifact,
    NonOverlapConstraint,
    ObjectiveDirection,
    ObjectiveInterval,
    SolverAdapterDefinition,
    SolverAdapterKind,
    SolverArtifactType,
    SolverLeaseEvidence,
    SolverProblem,
    SolverProofDisposition,
    SolverRequest,
    SolverRequiredClaim,
    SolverResourceEvidence,
    SolverResult,
    SolverResultStatus,
    SolverTerminationReason,
    SolverWitness,
    TableConstraint,
    TableMode,
)
from sdaqf.ports.solver import SolverClock


class SolverAdapterError(SolverContractError):
    """A bounded M7 adapter or evidence observation failed closed."""


class SystemSolverClock:
    """Production UTC and monotonic clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_milliseconds(self) -> int:
        return time.monotonic_ns() // 1_000_000


class FiniteDomainReferenceAdapter:
    """Deterministic complete-assignment finite-domain enumerator."""

    def __init__(self, clock: SolverClock | None = None) -> None:
        self._clock = SystemSolverClock() if clock is None else clock

    def solve(
        self,
        request: LoadedSolverArtifact,
        request_reference: ArtifactReference,
        adapter: SolverAdapterDefinition,
        lease: SolverLeaseEvidence,
    ) -> LoadedSolverArtifact:
        if request.artifact_type is not SolverArtifactType.REQUEST or not isinstance(
            request.value, SolverRequest
        ):
            raise SolverAdapterError("Reference adapter requires a Solver Request.")
        value = request.value
        if adapter.adapter_kind is not SolverAdapterKind.REFERENCE:
            return adapter_unavailable_result(request, request_reference, adapter, lease)
        if adapter.adapter_id != REFERENCE_ADAPTER_ID:
            raise SolverAdapterError("Reference adapter identity is invalid.")

        problem = value.problem
        policy = value.resource_policy
        space = search_space_size(problem)
        start_ms = self._clock.monotonic_milliseconds()
        request_deadline = (
            None if policy.timeout_milliseconds is None else start_ms + policy.timeout_milliseconds
        )
        lease_deadline = _parse_utc(lease.expires_at)
        variable_ids = tuple(variable.variable_id for variable in problem.variables)
        domains = tuple(variable.domain.values for variable in problem.variables)
        visited = 0
        checks = 0
        best_assignment: tuple[int, ...] | None = None
        best_objective: int | None = None
        termination: SolverTerminationReason | None = None

        for assignment in itertools.product(*domains):
            if self._clock.now() >= lease_deadline:
                termination = SolverTerminationReason.LEASE_DEADLINE
                break
            if (
                request_deadline is not None
                and self._clock.monotonic_milliseconds() >= request_deadline
            ):
                termination = SolverTerminationReason.REQUEST_TIMEOUT
                break
            if visited >= policy.max_solve_steps:
                termination = SolverTerminationReason.STEP_LIMIT
                break
            visited += 1
            values = dict(zip(variable_ids, assignment, strict=True))
            satisfied, evaluated = evaluate_constraints(problem, values)
            checks += evaluated
            if not satisfied:
                continue
            if problem.objective is None:
                best_assignment = assignment
                termination = SolverTerminationReason.WITNESS_FOUND
                break
            objective = evaluate_objective(problem, values)
            if value.required_claim is SolverRequiredClaim.FEASIBLE:
                best_assignment = assignment
                best_objective = objective
                termination = SolverTerminationReason.WITNESS_FOUND
                break
            if _is_better(problem, objective, assignment, best_objective, best_assignment):
                best_assignment = assignment
                best_objective = objective
        else:
            termination = SolverTerminationReason.SEARCH_EXHAUSTED

        assert termination is not None
        status, proof, diagnostic = _result_disposition(
            problem,
            termination,
            best_assignment,
        )
        witness = _witness(variable_ids, best_assignment)
        interval = _objective_interval(problem, status, best_objective)
        elapsed = (
            max(0, self._clock.monotonic_milliseconds() - start_ms)
            if termination
            in {SolverTerminationReason.REQUEST_TIMEOUT, SolverTerminationReason.LEASE_DEADLINE}
            else 0
        )
        resources = SolverResourceEvidence(
            solver_calls=1,
            solver_steps=visited,
            search_space_size=space,
            visited_assignments=visited,
            unvisited_assignments=space - visited,
            constraint_checks=checks,
            elapsed_milliseconds=min(elapsed, 3_600_000),
            step_limit=policy.max_solve_steps,
            timeout_milliseconds=policy.timeout_milliseconds,
            termination_reason=termination,
        )
        result = SolverResult(
            sensitivity=value.sensitivity,
            request=request_reference,
            request_id=request.artifact_id,
            contract_id=value.contract_id,
            candidate=value.candidate,
            graph_id=value.graph_id,
            task_id=value.task_id,
            context_snapshot_id=value.context_snapshot_id,
            adapter_id=adapter.adapter_id,
            adapter_version=adapter.version,
            license_expression=adapter.license_expression,
            provenance=adapter.provenance,
            lease=lease,
            status=status,
            witness=witness,
            objective_value=best_objective,
            objective_interval=interval,
            proof_disposition=proof,
            resources=resources,
            diagnostic_code=diagnostic,
        )
        return artifact_from_value(SolverArtifactType.RESULT, result)


class SQLiteSolverLeaseEvidenceReader:
    """Read exact Lease and dispatch reservation evidence from validated M6 state."""

    def observe(
        self,
        state: Path,
        root: Path,
        *,
        graph_id: str,
        task_id: str,
        host_id: str,
        lease_id: str,
        require_current: bool,
    ) -> SolverLeaseEvidence:
        store = SQLiteSchedulerStore(state, root)
        store.validate()
        uri = store.path.resolve(strict=True).as_uri() + "?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
            lease_value, current = self._lease(
                connection, task_id, lease_id, require_current=require_current
            )
            if (
                lease_value.graph_id != graph_id
                or lease_value.task_id != task_id
                or lease_value.owner_id != host_id
            ):
                raise SolverAdapterError("M6 Lease identity does not match the solver run.")
            if require_current and lease_value.status is not LeaseStatus.CURRENT:
                raise SolverAdapterError("Solver run requires an active M6 Lease.")
            if require_current and _parse_utc(lease_value.expires_at) <= datetime.now(UTC):
                raise SolverAdapterError("Solver run Lease is already expired.")
            dispatch_id, reservation = self._dispatch(connection, task_id, lease_id)
            if current is not None and (
                current["owner_id"] != host_id
                or int(current["attempt"]) != lease_value.attempt
                or int(current["fence"]) != lease_value.fence
                or current["idempotency_key"] != lease_value.idempotency_key
                or current["expires_at"] != lease_value.expires_at
            ):
                raise SolverAdapterError("Current M6 Lease projection is inconsistent.")
            calls_value = reservation.get("solver_calls")
            steps_value = reservation.get("solver_steps")
            if (
                not isinstance(calls_value, int)
                or isinstance(calls_value, bool)
                or not isinstance(steps_value, int)
                or isinstance(steps_value, bool)
            ):
                raise SolverAdapterError("M6 solver reservation is invalid.")
            calls = calls_value
            steps = steps_value
            if calls != 1 or steps < 2:
                raise SolverAdapterError("M6 solver reservation is invalid.")
            return SolverLeaseEvidence(
                graph_id=graph_id,
                task_id=task_id,
                host_id=host_id,
                attempt=lease_value.attempt,
                lease_id=lease_id,
                fence=lease_value.fence,
                idempotency_key=lease_value.idempotency_key,
                dispatch_message_id=dispatch_id,
                expires_at=lease_value.expires_at,
                reserved_solver_calls=calls,
                reserved_solver_steps=steps,
            )
        except (sqlite3.Error, OSError) as exc:
            raise SolverAdapterError("M6 solver Lease evidence could not be read.") from exc
        finally:
            if "connection" in locals():
                connection.close()

    @staticmethod
    def _lease(
        connection: sqlite3.Connection,
        task_id: str,
        lease_id: str,
        *,
        require_current: bool,
    ) -> tuple[Lease, sqlite3.Row | None]:
        current = connection.execute(
            "SELECT * FROM current_leases WHERE task_id = ? AND lease_id = ?",
            (task_id, lease_id),
        ).fetchone()
        if current is not None:
            artifact = parse_scheduler_artifact_bytes(
                str(current["artifact_json"]).encode("utf-8"),
                expected_type=SchedulerArtifactType.LEASE,
            )
            assert isinstance(artifact.value, Lease)
            return artifact.value, current
        if require_current:
            raise SolverAdapterError("M6 solver Lease is not current.")
        history = connection.execute(
            "SELECT artifact_json FROM lease_history "
            "WHERE task_id = ? AND authority_lease_id = ? "
            "ORDER BY event_sequence DESC LIMIT 1",
            (task_id, lease_id),
        ).fetchone()
        if history is None:
            raise SolverAdapterError("M6 solver Lease history is unavailable.")
        artifact = parse_scheduler_artifact_bytes(
            str(history["artifact_json"]).encode("utf-8"),
            expected_type=SchedulerArtifactType.LEASE,
        )
        assert isinstance(artifact.value, Lease)
        return artifact.value, None

    @staticmethod
    def _dispatch(
        connection: sqlite3.Connection,
        task_id: str,
        lease_id: str,
    ) -> tuple[str, dict[str, object]]:
        rows = connection.execute(
            "SELECT artifact_id, artifact_json FROM messages "
            "WHERE task_id = ? AND message_type = ? ORDER BY sequence DESC",
            (task_id, MessageType.DISPATCH_INTENT.value),
        ).fetchall()
        matches: list[tuple[str, dict[str, object]]] = []
        for row in rows:
            artifact = parse_scheduler_artifact_bytes(
                str(row["artifact_json"]).encode("utf-8"),
                expected_type=SchedulerArtifactType.MAILBOX_MESSAGE,
            )
            message = artifact.value
            assert isinstance(message, MailboxMessage)
            if message.lease_id != lease_id:
                continue
            payload = message.to_dict()["payload"]
            assert isinstance(payload, dict)
            reservation = payload.get("budget_reservation")
            if not isinstance(reservation, dict):
                raise SolverAdapterError("M6 dispatch reservation is unavailable.")
            matches.append((artifact.artifact_id, reservation))
        if len(matches) != 1:
            raise SolverAdapterError("M6 dispatch evidence is ambiguous.")
        return matches[0]


def adapter_error_result(
    request: LoadedSolverArtifact,
    request_reference: ArtifactReference,
    adapter: SolverAdapterDefinition,
    lease: SolverLeaseEvidence,
) -> LoadedSolverArtifact:
    """Return deterministic, non-proof evidence for a controlled adapter failure."""

    return _incomplete_result(
        request,
        request_reference,
        adapter,
        lease,
        SolverResultStatus.ERROR,
        SolverTerminationReason.ADAPTER_ERROR,
        "adapter-error",
        solver_calls=1,
        start_ms=0,
        clock=None,
    )


def adapter_unavailable_result(
    request: LoadedSolverArtifact,
    request_reference: ArtifactReference,
    adapter: SolverAdapterDefinition,
    lease: SolverLeaseEvidence,
) -> LoadedSolverArtifact:
    """Return deterministic zero-use evidence for an external adapter boundary."""

    return _incomplete_result(
        request,
        request_reference,
        adapter,
        lease,
        SolverResultStatus.UNAVAILABLE,
        SolverTerminationReason.ADAPTER_UNAVAILABLE,
        "adapter-unavailable",
        solver_calls=0,
        start_ms=0,
        clock=None,
    )


def evaluate_constraints(
    problem: SolverProblem,
    values: Mapping[str, int],
) -> tuple[bool, int]:
    """Evaluate constraints in canonical order and return the checked count."""

    checks = 0
    for constraint in problem.constraints:
        checks += 1
        if isinstance(constraint, LinearConstraint):
            left = sum(values[term.variable_id] * term.coefficient for term in constraint.terms)
            right = constraint.right_hand_side
            comparisons = {
                LinearRelation.EQ: left == right,
                LinearRelation.NE: left != right,
                LinearRelation.LT: left < right,
                LinearRelation.LE: left <= right,
                LinearRelation.GT: left > right,
                LinearRelation.GE: left >= right,
            }
            passed = comparisons[constraint.relation]
        elif isinstance(constraint, AllDifferentConstraint):
            selected = tuple(values[identifier] for identifier in constraint.variable_ids)
            passed = len(selected) == len(set(selected))
        elif isinstance(constraint, TableConstraint):
            row = tuple(values[identifier] for identifier in constraint.variable_ids)
            present = row in constraint.rows
            passed = present if constraint.mode is TableMode.ALLOWED else not present
        elif isinstance(constraint, ClauseConstraint):
            passed = any(
                values[literal.variable_id] == literal.equals for literal in constraint.literals
            )
        elif isinstance(constraint, NonOverlapConstraint):
            left = values[constraint.left_start]
            right = values[constraint.right_start]
            passed = (
                left + constraint.left_duration <= right
                or right + constraint.right_duration <= left
            )
        else:  # pragma: no cover - closed by the typed parser
            raise SolverAdapterError("Unknown constraint reached the reference adapter.")
        if not passed:
            return False, checks
    return True, checks


def evaluate_objective(problem: SolverProblem, values: Mapping[str, int]) -> int:
    """Evaluate the exact integer linear objective."""

    if problem.objective is None:
        raise SolverAdapterError("Feasibility problem has no objective.")
    return problem.objective.constant + sum(
        values[term.variable_id] * term.coefficient for term in problem.objective.terms
    )


def objective_domain_bounds(problem: SolverProblem) -> ObjectiveInterval:
    """Calculate conservative exact bounds without assuming feasibility."""

    if problem.objective is None:
        raise SolverAdapterError("Feasibility problem has no objective bounds.")
    domains = {variable.variable_id: variable.domain.values for variable in problem.variables}
    lower = problem.objective.constant
    upper = problem.objective.constant
    for term in problem.objective.terms:
        products = tuple(term.coefficient * value for value in domains[term.variable_id])
        lower += min(products)
        upper += max(products)
    return ObjectiveInterval(lower, upper)


def _is_better(
    problem: SolverProblem,
    objective: int,
    assignment: tuple[int, ...],
    best_objective: int | None,
    best_assignment: tuple[int, ...] | None,
) -> bool:
    if best_objective is None or best_assignment is None:
        return True
    assert problem.objective is not None
    if problem.objective.direction is ObjectiveDirection.MINIMIZE:
        return objective < best_objective or (
            objective == best_objective and assignment < best_assignment
        )
    return objective > best_objective or (
        objective == best_objective and assignment < best_assignment
    )


def _result_disposition(
    problem: SolverProblem,
    termination: SolverTerminationReason,
    best_assignment: tuple[int, ...] | None,
) -> tuple[SolverResultStatus, SolverProofDisposition, str | None]:
    if termination is SolverTerminationReason.WITNESS_FOUND:
        status = (
            SolverResultStatus.SATISFIABLE
            if problem.objective is None
            else SolverResultStatus.FEASIBLE
        )
        return status, SolverProofDisposition.WITNESS, None
    if termination is SolverTerminationReason.SEARCH_EXHAUSTED:
        if problem.objective is None:
            return (
                SolverResultStatus.UNSATISFIABLE,
                SolverProofDisposition.EXHAUSTIVE_ENUMERATION,
                None,
            )
        if best_assignment is None:
            return (
                SolverResultStatus.INFEASIBLE,
                SolverProofDisposition.EXHAUSTIVE_ENUMERATION,
                None,
            )
        return SolverResultStatus.OPTIMAL, SolverProofDisposition.EXHAUSTIVE_ENUMERATION, None
    if termination is SolverTerminationReason.STEP_LIMIT:
        if problem.objective is not None and best_assignment is not None:
            return SolverResultStatus.BOUNDED, SolverProofDisposition.OBJECTIVE_BOUND, None
        return SolverResultStatus.UNKNOWN, SolverProofDisposition.NONE, "step-limit"
    if termination is SolverTerminationReason.REQUEST_TIMEOUT:
        return SolverResultStatus.TIMEOUT, SolverProofDisposition.NONE, "request-timeout"
    if termination is SolverTerminationReason.LEASE_DEADLINE:
        return SolverResultStatus.TIMEOUT, SolverProofDisposition.NONE, "lease-deadline"
    raise SolverAdapterError("Unexpected reference termination reason.")


def _witness(
    variable_ids: tuple[str, ...], assignment: tuple[int, ...] | None
) -> SolverWitness | None:
    return (
        None
        if assignment is None
        else SolverWitness(tuple(zip(variable_ids, assignment, strict=True)))
    )


def _objective_interval(
    problem: SolverProblem,
    status: SolverResultStatus,
    objective: int | None,
) -> ObjectiveInterval | None:
    if problem.objective is None or objective is None:
        return None
    if status is SolverResultStatus.OPTIMAL:
        return ObjectiveInterval(objective, objective)
    if status is not SolverResultStatus.BOUNDED:
        return None
    global_interval = objective_domain_bounds(problem)
    if problem.objective.direction is ObjectiveDirection.MINIMIZE:
        return ObjectiveInterval(global_interval.lower, objective)
    return ObjectiveInterval(objective, global_interval.upper)


def _incomplete_result(
    request: LoadedSolverArtifact,
    request_reference: ArtifactReference,
    adapter: SolverAdapterDefinition,
    lease: SolverLeaseEvidence,
    status: SolverResultStatus,
    termination: SolverTerminationReason,
    diagnostic: str,
    *,
    solver_calls: int,
    start_ms: int,
    clock: SolverClock | None,
) -> LoadedSolverArtifact:
    value = request.value
    assert isinstance(value, SolverRequest)
    elapsed = 0 if clock is None else max(0, clock.monotonic_milliseconds() - start_ms)
    space = search_space_size(value.problem)
    result = SolverResult(
        sensitivity=value.sensitivity,
        request=request_reference,
        request_id=request.artifact_id,
        contract_id=value.contract_id,
        candidate=value.candidate,
        graph_id=value.graph_id,
        task_id=value.task_id,
        context_snapshot_id=value.context_snapshot_id,
        adapter_id=adapter.adapter_id,
        adapter_version=adapter.version,
        license_expression=adapter.license_expression,
        provenance=adapter.provenance,
        lease=lease,
        status=status,
        witness=None,
        objective_value=None,
        objective_interval=None,
        proof_disposition=SolverProofDisposition.NONE,
        resources=SolverResourceEvidence(
            solver_calls=solver_calls,
            solver_steps=0,
            search_space_size=space,
            visited_assignments=0,
            unvisited_assignments=space,
            constraint_checks=0,
            elapsed_milliseconds=min(elapsed, 3_600_000),
            step_limit=value.resource_policy.max_solve_steps,
            timeout_milliseconds=value.resource_policy.timeout_milliseconds,
            termination_reason=termination,
        ),
        diagnostic_code=diagnostic,
    )
    return artifact_from_value(SolverArtifactType.RESULT, result)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SolverAdapterError("M6 Lease deadline lacks timezone authority.")
    return parsed.astimezone(UTC)
