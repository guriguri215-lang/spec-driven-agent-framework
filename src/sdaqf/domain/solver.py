"""Typed immutable M7 mathematical solver contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sdaqf.domain.context import Sensitivity
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity


class SolverArtifactType(StrEnum):
    """Public M7 artifact discriminator."""

    REGISTRY = "solver-registry"
    REQUEST = "solver-request"
    RESULT = "solver-result"
    VERIFICATION = "solver-verification"


class SolverAdapterKind(StrEnum):
    """Supported adapter boundaries."""

    REFERENCE = "reference"
    EXTERNAL_CLI = "external-cli"


class SolverVersionObservationStatus(StrEnum):
    """Whether an optional executable version was actually observed."""

    NOT_OBSERVED = "not-observed"
    OBSERVED = "observed"


class SolverProblemKind(StrEnum):
    """Closed first-version problem kinds."""

    FEASIBILITY = "finite-domain-feasibility"
    OPTIMIZATION = "finite-domain-optimization"


class SolverProblemProfile(StrEnum):
    """Profiles that add closed validation rules to a finite-domain problem."""

    GENERAL = "general"
    BOOLEAN_SAT = "boolean-sat"
    FINITE_SCHEDULING = "finite-scheduling"


class SolverConstraintKind(StrEnum):
    """Typed constraint union."""

    LINEAR = "linear"
    ALL_DIFFERENT = "all-different"
    TABLE = "table"
    CLAUSE = "clause"
    NON_OVERLAP = "non-overlap"


class LinearRelation(StrEnum):
    """Exact integer comparison."""

    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"


class TableMode(StrEnum):
    """Extensional constraint mode."""

    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"


class ObjectiveDirection(StrEnum):
    """Exact optimization direction."""

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class SolverRequiredClaim(StrEnum):
    """Strength of result required for scheduler adoption."""

    DECISION = "decision"
    FEASIBLE = "feasible"
    BOUNDED = "bounded"
    OPTIMAL = "optimal"


class SolverResultStatus(StrEnum):
    """Truthful closed result status."""

    SATISFIABLE = "satisfiable"
    UNSATISFIABLE = "unsatisfiable"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    OPTIMAL = "optimal"
    BOUNDED = "bounded"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    ERROR = "error"


class SolverProofDisposition(StrEnum):
    """Evidence strength represented by one Result."""

    NONE = "none"
    WITNESS = "witness"
    OBJECTIVE_BOUND = "objective-bound"
    EXHAUSTIVE_ENUMERATION = "exhaustive-enumeration"


class SolverTerminationReason(StrEnum):
    """Why the adapter stopped."""

    WITNESS_FOUND = "witness-found"
    SEARCH_EXHAUSTED = "search-exhausted"
    STEP_LIMIT = "step-limit"
    REQUEST_TIMEOUT = "request-timeout"
    LEASE_DEADLINE = "lease-deadline"
    ADAPTER_UNAVAILABLE = "adapter-unavailable"
    ADAPTER_ERROR = "adapter-error"


class SolverVerificationOutcome(StrEnum):
    """Independent verification conclusion."""

    VERIFIED = "verified"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class IntegerDomain:
    """One exact finite integer domain."""

    kind: str
    values: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        if self.kind == "integer-set":
            return {"kind": self.kind, "values": list(self.values)}
        return {"kind": self.kind, "lower": self.values[0], "upper": self.values[-1]}


@dataclass(frozen=True, slots=True)
class SolverVariable:
    variable_id: str
    domain: IntegerDomain

    def to_dict(self) -> dict[str, object]:
        return {"variable_id": self.variable_id, "domain": self.domain.to_dict()}


@dataclass(frozen=True, slots=True)
class LinearTerm:
    variable_id: str
    coefficient: int

    def to_dict(self) -> dict[str, object]:
        return {"variable_id": self.variable_id, "coefficient": self.coefficient}


@dataclass(frozen=True, slots=True)
class LinearConstraint:
    constraint_id: str
    terms: tuple[LinearTerm, ...]
    relation: LinearRelation
    right_hand_side: int
    constraint_type: SolverConstraintKind = SolverConstraintKind.LINEAR

    def to_dict(self) -> dict[str, object]:
        return {
            "constraint_id": self.constraint_id,
            "constraint_type": self.constraint_type.value,
            "terms": [item.to_dict() for item in self.terms],
            "relation": self.relation.value,
            "right_hand_side": self.right_hand_side,
        }


@dataclass(frozen=True, slots=True)
class AllDifferentConstraint:
    constraint_id: str
    variable_ids: tuple[str, ...]
    constraint_type: SolverConstraintKind = SolverConstraintKind.ALL_DIFFERENT

    def to_dict(self) -> dict[str, object]:
        return {
            "constraint_id": self.constraint_id,
            "constraint_type": self.constraint_type.value,
            "variable_ids": list(self.variable_ids),
        }


@dataclass(frozen=True, slots=True)
class TableConstraint:
    constraint_id: str
    variable_ids: tuple[str, ...]
    mode: TableMode
    rows: tuple[tuple[int, ...], ...]
    constraint_type: SolverConstraintKind = SolverConstraintKind.TABLE

    def to_dict(self) -> dict[str, object]:
        return {
            "constraint_id": self.constraint_id,
            "constraint_type": self.constraint_type.value,
            "variable_ids": list(self.variable_ids),
            "mode": self.mode.value,
            "rows": [list(row) for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class ClauseLiteral:
    variable_id: str
    equals: int

    def to_dict(self) -> dict[str, object]:
        return {"variable_id": self.variable_id, "equals": self.equals}


@dataclass(frozen=True, slots=True)
class ClauseConstraint:
    constraint_id: str
    literals: tuple[ClauseLiteral, ...]
    constraint_type: SolverConstraintKind = SolverConstraintKind.CLAUSE

    def to_dict(self) -> dict[str, object]:
        return {
            "constraint_id": self.constraint_id,
            "constraint_type": self.constraint_type.value,
            "literals": [item.to_dict() for item in self.literals],
        }


@dataclass(frozen=True, slots=True)
class NonOverlapConstraint:
    constraint_id: str
    left_start: str
    left_duration: int
    right_start: str
    right_duration: int
    constraint_type: SolverConstraintKind = SolverConstraintKind.NON_OVERLAP

    def to_dict(self) -> dict[str, object]:
        return {
            "constraint_id": self.constraint_id,
            "constraint_type": self.constraint_type.value,
            "left_start": self.left_start,
            "left_duration": self.left_duration,
            "right_start": self.right_start,
            "right_duration": self.right_duration,
        }


type SolverConstraint = (
    LinearConstraint
    | AllDifferentConstraint
    | TableConstraint
    | ClauseConstraint
    | NonOverlapConstraint
)


@dataclass(frozen=True, slots=True)
class SolverObjective:
    direction: ObjectiveDirection
    terms: tuple[LinearTerm, ...]
    constant: int

    def to_dict(self) -> dict[str, object]:
        return {
            "direction": self.direction.value,
            "terms": [item.to_dict() for item in self.terms],
            "constant": self.constant,
        }


@dataclass(frozen=True, slots=True)
class SolverProblem:
    problem_kind: SolverProblemKind
    profile: SolverProblemProfile
    variables: tuple[SolverVariable, ...]
    constraints: tuple[SolverConstraint, ...]
    objective: SolverObjective | None

    def to_dict(self) -> dict[str, object]:
        return {
            "problem_kind": self.problem_kind.value,
            "profile": self.profile.value,
            "variables": [item.to_dict() for item in self.variables],
            "constraints": [item.to_dict() for item in self.constraints],
            "objective": None if self.objective is None else self.objective.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SolverResourcePolicy:
    max_solve_steps: int
    max_verification_steps: int
    timeout_milliseconds: int | None
    max_result_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "max_solve_steps": self.max_solve_steps,
            "max_verification_steps": self.max_verification_steps,
            "timeout_milliseconds": self.timeout_milliseconds,
            "max_result_bytes": self.max_result_bytes,
        }


@dataclass(frozen=True, slots=True)
class SolverVersionObservation:
    status: SolverVersionObservationStatus
    observed_version: str | None
    evidence: ArtifactReference | None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "observed_version": self.observed_version,
            "evidence": None if self.evidence is None else self.evidence.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SolverApprovalRequirements:
    owner_approval: str
    technical_sandbox_approval: str
    consumption: str

    def to_dict(self) -> dict[str, str]:
        return {
            "owner_approval": self.owner_approval,
            "technical_sandbox_approval": self.technical_sandbox_approval,
            "consumption": self.consumption,
        }


@dataclass(frozen=True, slots=True)
class SolverAdapterDefinition:
    adapter_id: str
    adapter_kind: SolverAdapterKind
    implementation: str
    version: str
    supported_problem_kinds: tuple[SolverProblemKind, ...]
    supported_profiles: tuple[SolverProblemProfile, ...]
    supported_constraints: tuple[SolverConstraintKind, ...]
    numeric_domain: str
    max_variables: int
    max_domain_values: int
    max_search_space: int
    max_constraints: int
    max_constraint_variables: int
    max_table_rows: int
    min_scalar: int
    max_scalar: int
    max_artifact_bytes: int
    network: bool
    optional: bool
    tool_registry: ArtifactReference | None
    tool_name: str | None
    executable: str | None
    input_format: str | None
    version_matcher: str | None
    version_observation: SolverVersionObservation | None
    approval_requirements: SolverApprovalRequirements | None
    license_expression: str
    provenance: tuple[ArtifactReference, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_kind": self.adapter_kind.value,
            "implementation": self.implementation,
            "version": self.version,
            "supported_problem_kinds": [item.value for item in self.supported_problem_kinds],
            "supported_profiles": [item.value for item in self.supported_profiles],
            "supported_constraints": [item.value for item in self.supported_constraints],
            "numeric_domain": self.numeric_domain,
            "limits": {
                "max_variables": self.max_variables,
                "max_domain_values": self.max_domain_values,
                "max_search_space": self.max_search_space,
                "max_constraints": self.max_constraints,
                "max_constraint_variables": self.max_constraint_variables,
                "max_table_rows": self.max_table_rows,
                "min_scalar": self.min_scalar,
                "max_scalar": self.max_scalar,
                "max_artifact_bytes": self.max_artifact_bytes,
            },
            "network": self.network,
            "optional": self.optional,
            "tool_registry": None if self.tool_registry is None else self.tool_registry.to_dict(),
            "tool_name": self.tool_name,
            "executable": self.executable,
            "input_format": self.input_format,
            "version_matcher": self.version_matcher,
            "version_observation": (
                None if self.version_observation is None else self.version_observation.to_dict()
            ),
            "approval_requirements": (
                None if self.approval_requirements is None else self.approval_requirements.to_dict()
            ),
            "license_expression": self.license_expression,
            "provenance": [item.to_dict() for item in self.provenance],
        }


@dataclass(frozen=True, slots=True)
class SolverRegistry:
    sensitivity: Sensitivity
    adapters: tuple[SolverAdapterDefinition, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "sensitivity": self.sensitivity.value,
            "adapters": [item.to_dict() for item in self.adapters],
        }


@dataclass(frozen=True, slots=True)
class SolverRequest:
    sensitivity: Sensitivity
    registry: ArtifactReference
    registry_id: str
    adapter_id: str
    contract_id: str
    task_graph: ArtifactReference
    graph_id: str
    task_id: str
    candidate: CandidateIdentity
    context_snapshot: ArtifactReference
    context_snapshot_id: str
    problem: SolverProblem
    required_claim: SolverRequiredClaim
    resource_policy: SolverResourcePolicy

    def operational_content(self) -> dict[str, object]:
        return {
            "registry_id": self.registry_id,
            "adapter_id": self.adapter_id,
            "problem": self.problem.to_dict(),
            "required_claim": self.required_claim.value,
            "tolerance": {"kind": "exact", "absolute": 0, "relative": 0},
            "resource_policy": self.resource_policy.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "sensitivity": self.sensitivity.value,
            "registry": self.registry.to_dict(),
            "registry_id": self.registry_id,
            "adapter_id": self.adapter_id,
            "contract_id": self.contract_id,
            "task_graph": self.task_graph.to_dict(),
            "graph_id": self.graph_id,
            "task_id": self.task_id,
            "candidate": self.candidate.to_dict(),
            "context_snapshot": self.context_snapshot.to_dict(),
            "context_snapshot_id": self.context_snapshot_id,
            "problem": self.problem.to_dict(),
            "required_claim": self.required_claim.value,
            "tolerance": {"kind": "exact", "absolute": 0, "relative": 0},
            "resource_policy": self.resource_policy.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SolverLeaseEvidence:
    graph_id: str
    task_id: str
    host_id: str
    attempt: int
    lease_id: str
    fence: int
    idempotency_key: str
    dispatch_message_id: str
    expires_at: str
    reserved_solver_calls: int
    reserved_solver_steps: int

    def to_dict(self) -> dict[str, object]:
        return {
            "graph_id": self.graph_id,
            "task_id": self.task_id,
            "host_id": self.host_id,
            "attempt": self.attempt,
            "lease_id": self.lease_id,
            "fence": self.fence,
            "idempotency_key": self.idempotency_key,
            "dispatch_message_id": self.dispatch_message_id,
            "expires_at": self.expires_at,
            "reserved_solver_calls": self.reserved_solver_calls,
            "reserved_solver_steps": self.reserved_solver_steps,
        }


@dataclass(frozen=True, slots=True)
class SolverWitness:
    assignments: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "assignments": [
                {"variable_id": variable_id, "value": value}
                for variable_id, value in self.assignments
            ]
        }


@dataclass(frozen=True, slots=True)
class ObjectiveInterval:
    lower: int
    upper: int

    def to_dict(self) -> dict[str, int]:
        return {"lower": self.lower, "upper": self.upper}


@dataclass(frozen=True, slots=True)
class SolverResourceEvidence:
    solver_calls: int
    solver_steps: int
    search_space_size: int
    visited_assignments: int
    unvisited_assignments: int
    constraint_checks: int
    elapsed_milliseconds: int
    step_limit: int
    timeout_milliseconds: int | None
    termination_reason: SolverTerminationReason

    def to_dict(self) -> dict[str, object]:
        return {
            "solver_calls": self.solver_calls,
            "solver_steps": self.solver_steps,
            "search_space_size": self.search_space_size,
            "visited_assignments": self.visited_assignments,
            "unvisited_assignments": self.unvisited_assignments,
            "constraint_checks": self.constraint_checks,
            "elapsed_milliseconds": self.elapsed_milliseconds,
            "step_limit": self.step_limit,
            "timeout_milliseconds": self.timeout_milliseconds,
            "termination_reason": self.termination_reason.value,
        }


@dataclass(frozen=True, slots=True)
class SolverResult:
    sensitivity: Sensitivity
    request: ArtifactReference
    request_id: str
    contract_id: str
    candidate: CandidateIdentity
    graph_id: str
    task_id: str
    context_snapshot_id: str
    adapter_id: str
    adapter_version: str
    license_expression: str
    provenance: tuple[ArtifactReference, ...]
    lease: SolverLeaseEvidence
    status: SolverResultStatus
    witness: SolverWitness | None
    objective_value: int | None
    objective_interval: ObjectiveInterval | None
    proof_disposition: SolverProofDisposition
    resources: SolverResourceEvidence
    diagnostic_code: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "sensitivity": self.sensitivity.value,
            "request": self.request.to_dict(),
            "request_id": self.request_id,
            "contract_id": self.contract_id,
            "candidate": self.candidate.to_dict(),
            "graph_id": self.graph_id,
            "task_id": self.task_id,
            "context_snapshot_id": self.context_snapshot_id,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "license_expression": self.license_expression,
            "provenance": [item.to_dict() for item in self.provenance],
            "lease": self.lease.to_dict(),
            "status": self.status.value,
            "witness": None if self.witness is None else self.witness.to_dict(),
            "objective_value": self.objective_value,
            "objective_interval": (
                None if self.objective_interval is None else self.objective_interval.to_dict()
            ),
            "tolerance": {"kind": "exact", "absolute": 0, "relative": 0},
            "proof_disposition": self.proof_disposition.value,
            "resources": self.resources.to_dict(),
            "diagnostic_code": self.diagnostic_code,
        }


@dataclass(frozen=True, slots=True)
class SolverVerificationCheck:
    check_id: str
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return {"check_id": self.check_id, "passed": self.passed}


@dataclass(frozen=True, slots=True)
class SolverVerification:
    sensitivity: Sensitivity
    request: ArtifactReference
    request_id: str
    result: ArtifactReference
    result_id: str
    contract_id: str
    candidate: CandidateIdentity
    graph_id: str
    task_id: str
    context_snapshot_id: str
    lease: SolverLeaseEvidence
    outcome: SolverVerificationOutcome
    adoption_allowed: bool
    checks: tuple[SolverVerificationCheck, ...]
    reasons: tuple[str, ...]
    verification_steps: int

    def to_dict(self) -> dict[str, object]:
        return {
            "sensitivity": self.sensitivity.value,
            "request": self.request.to_dict(),
            "request_id": self.request_id,
            "result": self.result.to_dict(),
            "result_id": self.result_id,
            "contract_id": self.contract_id,
            "candidate": self.candidate.to_dict(),
            "graph_id": self.graph_id,
            "task_id": self.task_id,
            "context_snapshot_id": self.context_snapshot_id,
            "lease": self.lease.to_dict(),
            "outcome": self.outcome.value,
            "adoption_allowed": self.adoption_allowed,
            "checks": [item.to_dict() for item in self.checks],
            "reasons": list(self.reasons),
            "verification_steps": self.verification_steps,
        }


type SolverValue = SolverRegistry | SolverRequest | SolverResult | SolverVerification


@dataclass(frozen=True, slots=True)
class LoadedSolverArtifact:
    artifact_type: SolverArtifactType
    artifact_id: str
    value: SolverValue

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "artifact_type": self.artifact_type.value,
            "artifact_id": self.artifact_id,
            "content": self.value.to_dict(),
        }
