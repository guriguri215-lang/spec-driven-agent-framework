"""Strict canonical contracts for M7 solver artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from pathlib import Path

from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.contracts import (
    ContractError,
    array_value,
    boolean_value,
    enum_value,
    integer_value,
    object_value,
    only_keys,
    optional_string,
    parse_artifact_reference,
    parse_candidate_identity,
    parse_json_object_bytes,
    string_value,
    verify_artifact,
)
from sdaqf.application.scheduler_contracts import utc_timestamp
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.quality import ArtifactReference
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
    ObjectiveInterval,
    SolverAdapterDefinition,
    SolverAdapterKind,
    SolverApprovalRequirements,
    SolverArtifactType,
    SolverConstraint,
    SolverConstraintKind,
    SolverLeaseEvidence,
    SolverObjective,
    SolverProblem,
    SolverProblemKind,
    SolverProblemProfile,
    SolverProofDisposition,
    SolverRegistry,
    SolverRequest,
    SolverRequiredClaim,
    SolverResourceEvidence,
    SolverResourcePolicy,
    SolverResult,
    SolverResultStatus,
    SolverTerminationReason,
    SolverValue,
    SolverVariable,
    SolverVerification,
    SolverVerificationCheck,
    SolverVerificationOutcome,
    SolverVersionObservation,
    SolverVersionObservationStatus,
    SolverWitness,
    TableConstraint,
    TableMode,
)

MAX_ARTIFACT_BYTES = 1_048_576
MAX_VARIABLES = 16
MAX_DOMAIN_VALUES = 256
MAX_SEARCH_SPACE = 1_000_000
MAX_CONSTRAINTS = 256
MAX_CONSTRAINT_VARIABLES = 16
MAX_TABLE_ROWS = 4_096
MAX_SCALAR = 1_000_000
MAX_STEPS = 1_000_000
MAX_TOTAL_STEPS = 2_000_000
REFERENCE_ADAPTER_ID = "stdlib-finite-domain-v1"
NUMERIC_DOMAIN = "exact-integer"

_PREFIX = {
    SolverArtifactType.REGISTRY: "M7-SOLVER-REGISTRY-",
    SolverArtifactType.REQUEST: "M7-SOLVER-REQUEST-",
    SolverArtifactType.RESULT: "M7-SOLVER-RESULT-",
    SolverArtifactType.VERIFICATION: "M7-SOLVER-VERIFICATION-",
}
_CONTRACT_PREFIX = "M7-SOLVER-CONTRACT-"
_TOKEN_PREFIX = "m7-solver-v1@"
_SLUG = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9_-]{0,63}$")
_TASK = re.compile(r"^TSK-[A-Z0-9][A-Z0-9-]{0,63}$")
_HOST = re.compile(r"^HST-[A-Z0-9][A-Z0-9-]{0,63}$")
_GRAPH = re.compile(r"^M6-TASK-GRAPH-[0-9A-F]{64}$")
_CONTEXT = re.compile(r"^CTX-SNAPSHOT-[0-9A-F]{64}$")
_LEASE = re.compile(r"^M6-LEASE-[0-9A-F]{64}$")
_MESSAGE = re.compile(r"^M6-MESSAGE-[0-9A-F]{64}$")
_IDEMPOTENCY = re.compile(r"^IDEM-[0-9A-F]{64}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_LICENSE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{0,63}$")
_DIAGNOSTICS = {
    "adapter-unavailable",
    "adapter-error",
    "request-timeout",
    "lease-deadline",
    "step-limit",
}


class SolverContractError(ContractError):
    """M7 input does not satisfy the strict solver contract."""


def solver_identity(artifact_type: SolverArtifactType, content: object) -> str:
    """Return one full uppercase content identity."""

    digest = hashlib.sha256(canonical_json_bytes(content)).hexdigest().upper()
    return f"{_PREFIX[artifact_type]}{digest}"


def operational_contract_id(content: object) -> str:
    """Return the graph-bindable digest of Request operational content."""

    digest = hashlib.sha256(canonical_json_bytes(content)).hexdigest().upper()
    return f"{_CONTRACT_PREFIX}{digest}"


def solver_capability_token(request: SolverRequest) -> str:
    """Create the exact existing-M6 capability token for one Request."""

    policy = request.resource_policy
    return (
        f"{_TOKEN_PREFIX}{request.contract_id}@{policy.max_solve_steps}"
        f"@{policy.max_verification_steps}"
    )


def parse_solver_capability_token(value: str) -> tuple[str, int, int]:
    """Parse a canonical M7 capability token without loading a Request."""

    if not value.startswith(_TOKEN_PREFIX) or len(value) > 500:
        raise SolverContractError("Solver capability token is invalid.")
    parts = value[len(_TOKEN_PREFIX) :].split("@")
    if len(parts) != 3:
        raise SolverContractError("Solver capability token is invalid.")
    contract_id = solver_id(parts[0], "contract_id", _CONTRACT_PREFIX)
    for part in parts[1:]:
        if not part.isascii() or not part.isdecimal() or part.startswith("0"):
            raise SolverContractError("Solver capability step count is not canonical.")
    solve_steps = int(parts[1])
    verify_steps = int(parts[2])
    if not 1 <= solve_steps <= MAX_STEPS or not 1 <= verify_steps <= MAX_STEPS:
        raise SolverContractError("Solver capability step count is out of bounds.")
    if solve_steps + verify_steps > MAX_TOTAL_STEPS:
        raise SolverContractError("Solver capability total steps exceed the limit.")
    return contract_id, solve_steps, verify_steps


def artifact_from_value(
    artifact_type: SolverArtifactType,
    value: SolverValue,
) -> LoadedSolverArtifact:
    """Create a validated identity envelope from a typed M7 value."""

    content = value.to_dict()
    parsed = _parse_value(artifact_type, content)
    if parsed.to_dict() != content:
        raise SolverContractError("Generated solver artifact is not canonical.")
    return LoadedSolverArtifact(
        artifact_type=artifact_type,
        artifact_id=solver_identity(artifact_type, content),
        value=parsed,
    )


def serialize_solver_artifact(artifact: LoadedSolverArtifact) -> bytes:
    """Serialize deterministic pretty public JSON without overwriting."""

    expected = solver_identity(artifact.artifact_type, artifact.value.to_dict())
    if artifact.artifact_id != expected:
        raise SolverContractError("Solver artifact identity does not match content.")
    encoded = (
        json.dumps(
            artifact.to_dict(), ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False
        ).encode("ascii")
        + b"\n"
    )
    if len(encoded) > MAX_ARTIFACT_BYTES:
        raise SolverContractError("Solver artifact exceeds 1 MiB.")
    return encoded


def load_solver_artifact(
    path: Path,
    *,
    expected_type: SolverArtifactType | None = None,
) -> LoadedSolverArtifact:
    """Load one bounded regular M7 artifact and validate its exact identity."""

    try:
        if not path.is_file() or path.is_symlink() or is_reparse_point(path):
            raise SolverContractError("Solver artifact must be a regular file.")
        raw = path.read_bytes()
    except OSError as exc:
        raise SolverContractError("Solver artifact could not be read.") from exc
    return parse_solver_artifact_bytes(raw, expected_type=expected_type)


def parse_solver_artifact_bytes(
    raw: bytes,
    *,
    expected_type: SolverArtifactType | None = None,
) -> LoadedSolverArtifact:
    """Parse one bounded strict M7 artifact without filesystem authority."""

    if not raw or len(raw) > MAX_ARTIFACT_BYTES:
        raise SolverContractError("Solver artifact size is invalid.")
    try:
        decoded: object = parse_json_object_bytes(
            raw,
            "solver artifact",
            maximum_bytes=MAX_ARTIFACT_BYTES,
        )
    except ContractError as exc:
        raise SolverContractError("Solver artifact is not strict UTF-8 JSON.") from exc
    try:
        return _parse_solver_envelope(decoded, expected_type)
    except SolverContractError:
        raise
    except ContractError as exc:
        raise SolverContractError(str(exc)) from exc


def _parse_solver_envelope(
    decoded: object,
    expected_type: SolverArtifactType | None,
) -> LoadedSolverArtifact:
    envelope = object_value(decoded, "solver artifact")
    only_keys(
        envelope,
        {"schema_version", "artifact_type", "artifact_id", "content"},
        "solver artifact",
    )
    if envelope.get("schema_version") != "1.0":
        raise SolverContractError("Solver schema version is unsupported.")
    artifact_type = enum_value(SolverArtifactType, envelope.get("artifact_type"), "artifact_type")
    if expected_type is not None and artifact_type is not expected_type:
        raise SolverContractError("Solver artifact type is unexpected.")
    value = _parse_value(artifact_type, envelope.get("content"))
    expected_id = solver_identity(artifact_type, value.to_dict())
    artifact_id = solver_id(envelope.get("artifact_id"), "artifact_id", _PREFIX[artifact_type])
    if artifact_id != expected_id:
        raise SolverContractError("Solver artifact identity does not match content.")
    result = LoadedSolverArtifact(artifact_type, artifact_id, value)
    if result.to_dict() != decoded:
        raise SolverContractError("Solver artifact is not canonical.")
    return result


def verify_reference(root: Path, reference: ArtifactReference) -> Path:
    """Verify a repository-bounded immutable reference and return its path."""

    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise SolverContractError("Solver root is unavailable.") from exc
    if not root.is_dir() or root.is_symlink() or is_reparse_point(root):
        raise SolverContractError("Solver root must be a regular directory.")
    if not verify_artifact(resolved_root, reference, maximum_bytes=MAX_ARTIFACT_BYTES):
        raise SolverContractError("Solver artifact reference is invalid.")
    return resolved_root.joinpath(*reference.path.split("/"))


def search_space_size(problem: SolverProblem) -> int:
    """Return the already-bounded Cartesian assignment count."""

    result = 1
    for variable in problem.variables:
        result *= len(variable.domain.values)
    return result


def solver_id(value: object, where: str, prefix: str) -> str:
    text = string_value(value, where, maximum=len(prefix) + 64)
    if not re.fullmatch(re.escape(prefix) + r"[0-9A-F]{64}", text):
        raise SolverContractError(f"{where} has an invalid solver identifier.")
    return text


def _parse_value(artifact_type: SolverArtifactType, value: object) -> SolverValue:
    if artifact_type is SolverArtifactType.REGISTRY:
        return _parse_registry(value)
    if artifact_type is SolverArtifactType.REQUEST:
        return _parse_request(value)
    if artifact_type is SolverArtifactType.RESULT:
        return _parse_result(value)
    return _parse_verification(value)


def _parse_registry(value: object) -> SolverRegistry:
    item = object_value(value, "content")
    only_keys(item, {"sensitivity", "adapters"}, "content")
    sensitivity = enum_value(Sensitivity, item.get("sensitivity"), "content.sensitivity")
    raw_adapters = array_value(item.get("adapters"), "content.adapters", maximum=32)
    if not raw_adapters:
        raise SolverContractError("Solver Registry must contain an adapter.")
    adapters = tuple(_parse_adapter(raw, index) for index, raw in enumerate(raw_adapters))
    if adapters != tuple(sorted(adapters, key=lambda adapter: adapter.adapter_id)):
        raise SolverContractError("Solver Registry adapters must be sorted.")
    if len({adapter.adapter_id for adapter in adapters}) != len(adapters):
        raise SolverContractError("Solver Registry adapter identifiers must be unique.")
    reference = [adapter for adapter in adapters if adapter.adapter_id == REFERENCE_ADAPTER_ID]
    if len(reference) != 1 or reference[0].adapter_kind is not SolverAdapterKind.REFERENCE:
        raise SolverContractError("Solver Registry requires the reference adapter.")
    return SolverRegistry(sensitivity=sensitivity, adapters=adapters)


def _parse_adapter(value: object, index: int) -> SolverAdapterDefinition:
    where = f"content.adapters[{index}]"
    item = object_value(value, where)
    only_keys(
        item,
        {
            "adapter_id",
            "adapter_kind",
            "implementation",
            "version",
            "supported_problem_kinds",
            "supported_profiles",
            "supported_constraints",
            "numeric_domain",
            "limits",
            "network",
            "optional",
            "tool_registry",
            "tool_name",
            "executable",
            "input_format",
            "version_matcher",
            "version_observation",
            "approval_requirements",
            "license_expression",
            "provenance",
        },
        where,
    )
    adapter_id = _slug(item.get("adapter_id"), f"{where}.adapter_id")
    adapter_kind = enum_value(SolverAdapterKind, item.get("adapter_kind"), f"{where}.adapter_kind")
    implementation = string_value(
        item.get("implementation"), f"{where}.implementation", maximum=120
    )
    version = string_value(item.get("version"), f"{where}.version", maximum=32)
    if _VERSION.fullmatch(version) is None:
        raise SolverContractError(f"{where}.version is invalid.")
    problem_kinds = _sorted_enums(
        SolverProblemKind, item.get("supported_problem_kinds"), f"{where}.supported_problem_kinds"
    )
    profiles = _sorted_enums(
        SolverProblemProfile, item.get("supported_profiles"), f"{where}.supported_profiles"
    )
    constraints = _sorted_enums(
        SolverConstraintKind,
        item.get("supported_constraints"),
        f"{where}.supported_constraints",
    )
    if not problem_kinds or not profiles or not constraints:
        raise SolverContractError(f"{where} capability lists must be nonempty.")
    numeric_domain = string_value(
        item.get("numeric_domain"), f"{where}.numeric_domain", maximum=32
    )
    if numeric_domain != NUMERIC_DOMAIN:
        raise SolverContractError(f"{where}.numeric_domain is unsupported.")
    limits = object_value(item.get("limits"), f"{where}.limits")
    only_keys(
        limits,
        {
            "max_variables",
            "max_domain_values",
            "max_search_space",
            "max_constraints",
            "max_constraint_variables",
            "max_table_rows",
            "min_scalar",
            "max_scalar",
            "max_artifact_bytes",
        },
        f"{where}.limits",
    )
    max_variables = integer_value(
        limits.get("max_variables"),
        f"{where}.limits.max_variables",
        minimum=1,
        maximum=MAX_VARIABLES,
    )
    max_domain_values = integer_value(
        limits.get("max_domain_values"),
        f"{where}.limits.max_domain_values",
        minimum=1,
        maximum=MAX_DOMAIN_VALUES,
    )
    max_search_space = integer_value(
        limits.get("max_search_space"),
        f"{where}.limits.max_search_space",
        minimum=1,
        maximum=MAX_SEARCH_SPACE,
    )
    max_constraints = integer_value(
        limits.get("max_constraints"),
        f"{where}.limits.max_constraints",
        minimum=0,
        maximum=MAX_CONSTRAINTS,
    )
    max_constraint_variables = integer_value(
        limits.get("max_constraint_variables"),
        f"{where}.limits.max_constraint_variables",
        minimum=1,
        maximum=MAX_CONSTRAINT_VARIABLES,
    )
    max_table_rows = integer_value(
        limits.get("max_table_rows"),
        f"{where}.limits.max_table_rows",
        minimum=0,
        maximum=MAX_TABLE_ROWS,
    )
    min_scalar = integer_value(
        limits.get("min_scalar"),
        f"{where}.limits.min_scalar",
        minimum=-MAX_SCALAR,
        maximum=MAX_SCALAR,
    )
    max_scalar = integer_value(
        limits.get("max_scalar"),
        f"{where}.limits.max_scalar",
        minimum=-MAX_SCALAR,
        maximum=MAX_SCALAR,
    )
    if min_scalar > max_scalar:
        raise SolverContractError(f"{where}.limits scalar range is reversed.")
    max_artifact_bytes = integer_value(
        limits.get("max_artifact_bytes"),
        f"{where}.limits.max_artifact_bytes",
        minimum=1,
        maximum=MAX_ARTIFACT_BYTES,
    )
    network = boolean_value(item.get("network"), f"{where}.network")
    optional = boolean_value(item.get("optional"), f"{where}.optional")
    tool_registry = (
        None
        if item.get("tool_registry") is None
        else parse_artifact_reference(item.get("tool_registry"), f"{where}.tool_registry")
    )
    tool_name = optional_string(item.get("tool_name"), f"{where}.tool_name", maximum=64)
    executable = optional_string(item.get("executable"), f"{where}.executable", maximum=120)
    input_format = optional_string(item.get("input_format"), f"{where}.input_format", maximum=64)
    version_matcher = optional_string(
        item.get("version_matcher"), f"{where}.version_matcher", maximum=200
    )
    version_observation = _parse_version_observation(
        item.get("version_observation"), where
    )
    approval_requirements = _parse_adapter_approval_requirements(
        item.get("approval_requirements"), where
    )
    license_expression = string_value(
        item.get("license_expression"), f"{where}.license_expression", maximum=64
    )
    if _LICENSE.fullmatch(license_expression) is None:
        raise SolverContractError(f"{where}.license_expression is invalid.")
    provenance = _references(item.get("provenance"), f"{where}.provenance", minimum=1)
    if network:
        raise SolverContractError("M7 adapters must prohibit network access.")
    if adapter_kind is SolverAdapterKind.REFERENCE:
        if (
            adapter_id != REFERENCE_ADAPTER_ID
            or optional
            or any(
                value is not None
                for value in (
                    tool_registry,
                    tool_name,
                    executable,
                    input_format,
                    version_matcher,
                    version_observation,
                    approval_requirements,
                )
            )
        ):
            raise SolverContractError("Reference adapter boundary is invalid.")
        if (
            implementation != "sdaqf.adapters.solver.FiniteDomainReferenceAdapter"
            or version != "1.0.0"
            or license_expression != "Apache-2.0"
            or set(problem_kinds) != set(SolverProblemKind)
            or set(profiles) != set(SolverProblemProfile)
            or set(constraints) != set(SolverConstraintKind)
            or max_variables != MAX_VARIABLES
            or max_domain_values != MAX_DOMAIN_VALUES
            or max_search_space != MAX_SEARCH_SPACE
            or max_constraints != MAX_CONSTRAINTS
            or max_constraint_variables != MAX_CONSTRAINT_VARIABLES
            or max_table_rows != MAX_TABLE_ROWS
            or min_scalar != -MAX_SCALAR
            or max_scalar != MAX_SCALAR
            or max_artifact_bytes != MAX_ARTIFACT_BYTES
        ):
            raise SolverContractError("Reference adapter definition is not exact.")
    elif not optional or any(
        value is None
        for value in (
            tool_registry,
            tool_name,
            executable,
            input_format,
            version_matcher,
            version_observation,
            approval_requirements,
        )
    ):
        raise SolverContractError("External CLI adapter boundary is incomplete.")
    return SolverAdapterDefinition(
        adapter_id=adapter_id,
        adapter_kind=adapter_kind,
        implementation=implementation,
        version=version,
        supported_problem_kinds=problem_kinds,
        supported_profiles=profiles,
        supported_constraints=constraints,
        numeric_domain=numeric_domain,
        max_variables=max_variables,
        max_domain_values=max_domain_values,
        max_search_space=max_search_space,
        max_constraints=max_constraints,
        max_constraint_variables=max_constraint_variables,
        max_table_rows=max_table_rows,
        min_scalar=min_scalar,
        max_scalar=max_scalar,
        max_artifact_bytes=max_artifact_bytes,
        network=network,
        optional=optional,
        tool_registry=tool_registry,
        tool_name=tool_name,
        executable=executable,
        input_format=input_format,
        version_matcher=version_matcher,
        version_observation=version_observation,
        approval_requirements=approval_requirements,
        license_expression=license_expression,
        provenance=provenance,
    )


def _parse_version_observation(
    value: object,
    adapter_where: str,
) -> SolverVersionObservation | None:
    if value is None:
        return None
    where = f"{adapter_where}.version_observation"
    item = object_value(value, where)
    only_keys(item, {"status", "observed_version", "evidence"}, where)
    status = enum_value(
        SolverVersionObservationStatus,
        item.get("status"),
        f"{where}.status",
    )
    observed = optional_string(
        item.get("observed_version"), f"{where}.observed_version", maximum=32
    )
    evidence = (
        None
        if item.get("evidence") is None
        else parse_artifact_reference(item.get("evidence"), f"{where}.evidence")
    )
    if status is SolverVersionObservationStatus.NOT_OBSERVED and (
        observed is not None or evidence is not None
    ):
        raise SolverContractError("Unobserved adapter version cannot claim evidence.")
    if status is SolverVersionObservationStatus.OBSERVED and (
        observed is None or evidence is None or _VERSION.fullmatch(observed) is None
    ):
        raise SolverContractError("Observed adapter version requires exact evidence.")
    return SolverVersionObservation(status, observed, evidence)


def _parse_adapter_approval_requirements(
    value: object,
    adapter_where: str,
) -> SolverApprovalRequirements | None:
    if value is None:
        return None
    where = f"{adapter_where}.approval_requirements"
    item = object_value(value, where)
    only_keys(
        item,
        {"owner_approval", "technical_sandbox_approval", "consumption"},
        where,
    )
    expected = {
        "owner_approval": "fresh-required",
        "technical_sandbox_approval": "fresh-required",
        "consumption": "single-use-atomic",
    }
    if item != expected:
        raise SolverContractError("External adapter approval requirements are not exact.")
    return SolverApprovalRequirements(**expected)


def _parse_request(value: object) -> SolverRequest:
    item = object_value(value, "content")
    only_keys(
        item,
        {
            "sensitivity",
            "registry",
            "registry_id",
            "adapter_id",
            "contract_id",
            "task_graph",
            "graph_id",
            "task_id",
            "candidate",
            "context_snapshot",
            "context_snapshot_id",
            "problem",
            "required_claim",
            "tolerance",
            "resource_policy",
        },
        "content",
    )
    sensitivity = enum_value(Sensitivity, item.get("sensitivity"), "content.sensitivity")
    registry_id = solver_id(
        item.get("registry_id"), "content.registry_id", _PREFIX[SolverArtifactType.REGISTRY]
    )
    adapter_id = _slug(item.get("adapter_id"), "content.adapter_id")
    contract_id = solver_id(item.get("contract_id"), "content.contract_id", _CONTRACT_PREFIX)
    graph_id = _pattern_id(item.get("graph_id"), "content.graph_id", _GRAPH)
    task_id = _pattern_id(item.get("task_id"), "content.task_id", _TASK)
    context_id = _pattern_id(
        item.get("context_snapshot_id"), "content.context_snapshot_id", _CONTEXT
    )
    problem = _parse_problem(item.get("problem"))
    required_claim = enum_value(
        SolverRequiredClaim, item.get("required_claim"), "content.required_claim"
    )
    _validate_claim(problem.problem_kind, required_claim)
    _parse_tolerance(item.get("tolerance"), "content.tolerance")
    policy = _parse_resource_policy(item.get("resource_policy"))
    result = SolverRequest(
        sensitivity=sensitivity,
        registry=parse_artifact_reference(item.get("registry"), "content.registry"),
        registry_id=registry_id,
        adapter_id=adapter_id,
        contract_id=contract_id,
        task_graph=parse_artifact_reference(item.get("task_graph"), "content.task_graph"),
        graph_id=graph_id,
        task_id=task_id,
        candidate=parse_candidate_identity(item.get("candidate"), "content.candidate"),
        context_snapshot=parse_artifact_reference(
            item.get("context_snapshot"), "content.context_snapshot"
        ),
        context_snapshot_id=context_id,
        problem=problem,
        required_claim=required_claim,
        resource_policy=policy,
    )
    if operational_contract_id(result.operational_content()) != contract_id:
        raise SolverContractError("Solver Request contract identity does not match content.")
    return result


def _parse_problem(value: object) -> SolverProblem:
    item = object_value(value, "content.problem")
    only_keys(
        item,
        {"problem_kind", "profile", "variables", "constraints", "objective"},
        "content.problem",
    )
    kind = enum_value(SolverProblemKind, item.get("problem_kind"), "content.problem.problem_kind")
    profile = enum_value(SolverProblemProfile, item.get("profile"), "content.problem.profile")
    if kind is SolverProblemKind.OPTIMIZATION and profile is SolverProblemProfile.BOOLEAN_SAT:
        raise SolverContractError("Boolean SAT profile is feasibility-only.")
    raw_variables = array_value(
        item.get("variables"), "content.problem.variables", maximum=MAX_VARIABLES
    )
    if not raw_variables:
        raise SolverContractError("Solver problem must contain a variable.")
    variables = tuple(_parse_variable(raw, index) for index, raw in enumerate(raw_variables))
    if variables != tuple(sorted(variables, key=lambda value: value.variable_id)) or len(
        {value.variable_id for value in variables}
    ) != len(variables):
        raise SolverContractError("Solver variables must be sorted and unique.")
    variable_domains = {variable.variable_id: set(variable.domain.values) for variable in variables}
    if profile is SolverProblemProfile.BOOLEAN_SAT and any(
        variable.domain.values != (0, 1) for variable in variables
    ):
        raise SolverContractError("Boolean SAT variables must have domain [0, 1].")
    raw_constraints = array_value(
        item.get("constraints"), "content.problem.constraints", maximum=MAX_CONSTRAINTS
    )
    constraints = tuple(
        _parse_constraint(raw, index, variable_domains, profile)
        for index, raw in enumerate(raw_constraints)
    )
    if constraints != tuple(sorted(constraints, key=lambda value: value.constraint_id)) or len(
        {value.constraint_id for value in constraints}
    ) != len(constraints):
        raise SolverContractError("Solver constraints must be sorted and unique.")
    objective = (
        None
        if item.get("objective") is None
        else _parse_objective(item.get("objective"), variable_domains)
    )
    if (kind is SolverProblemKind.FEASIBILITY) != (objective is None):
        raise SolverContractError("Problem kind and objective are inconsistent.")
    problem = SolverProblem(kind, profile, variables, constraints, objective)
    if search_space_size(problem) > MAX_SEARCH_SPACE:
        raise SolverContractError("Solver search space exceeds one million assignments.")
    return problem


def _parse_variable(value: object, index: int) -> SolverVariable:
    where = f"content.problem.variables[{index}]"
    item = object_value(value, where)
    only_keys(item, {"variable_id", "domain"}, where)
    variable_id = _symbol(item.get("variable_id"), f"{where}.variable_id")
    domain_item = object_value(item.get("domain"), f"{where}.domain")
    kind = string_value(domain_item.get("kind"), f"{where}.domain.kind", maximum=20)
    if kind == "integer-set":
        only_keys(domain_item, {"kind", "values"}, f"{where}.domain")
        values = tuple(
            _scalar(raw, f"{where}.domain.values[{position}]")
            for position, raw in enumerate(
                array_value(
                    domain_item.get("values"), f"{where}.domain.values", maximum=MAX_DOMAIN_VALUES
                )
            )
        )
        if not values or values != tuple(sorted(set(values))):
            raise SolverContractError(f"{where}.domain values must be sorted and unique.")
    elif kind == "integer-range":
        only_keys(domain_item, {"kind", "lower", "upper"}, f"{where}.domain")
        lower = _scalar(domain_item.get("lower"), f"{where}.domain.lower")
        upper = _scalar(domain_item.get("upper"), f"{where}.domain.upper")
        if upper < lower or upper - lower + 1 > MAX_DOMAIN_VALUES:
            raise SolverContractError(f"{where}.domain range is invalid.")
        values = tuple(range(lower, upper + 1))
    else:
        raise SolverContractError(f"{where}.domain kind is unsupported.")
    return SolverVariable(variable_id, IntegerDomain(kind, values))


def _parse_constraint(
    value: object,
    index: int,
    variable_domains: dict[str, set[int]],
    profile: SolverProblemProfile,
) -> SolverConstraint:
    where = f"content.problem.constraints[{index}]"
    item = object_value(value, where)
    constraint_id = _symbol(item.get("constraint_id"), f"{where}.constraint_id")
    kind = enum_value(SolverConstraintKind, item.get("constraint_type"), f"{where}.constraint_type")
    if kind is SolverConstraintKind.LINEAR:
        only_keys(
            item,
            {"constraint_id", "constraint_type", "terms", "relation", "right_hand_side"},
            where,
        )
        terms = _parse_terms(item.get("terms"), f"{where}.terms", variable_domains)
        return LinearConstraint(
            constraint_id,
            terms,
            enum_value(LinearRelation, item.get("relation"), f"{where}.relation"),
            _scalar(item.get("right_hand_side"), f"{where}.right_hand_side"),
        )
    if kind is SolverConstraintKind.ALL_DIFFERENT:
        only_keys(item, {"constraint_id", "constraint_type", "variable_ids"}, where)
        variables = _variable_ids(
            item.get("variable_ids"), f"{where}.variable_ids", variable_domains, minimum=2
        )
        return AllDifferentConstraint(constraint_id, variables)
    if kind is SolverConstraintKind.TABLE:
        only_keys(item, {"constraint_id", "constraint_type", "variable_ids", "mode", "rows"}, where)
        variables = _variable_ids(
            item.get("variable_ids"),
            f"{where}.variable_ids",
            variable_domains,
            minimum=1,
        )
        mode = enum_value(TableMode, item.get("mode"), f"{where}.mode")
        raw_rows = array_value(item.get("rows"), f"{where}.rows", maximum=MAX_TABLE_ROWS)
        rows: list[tuple[int, ...]] = []
        for row_index, raw_row in enumerate(raw_rows):
            row_items = array_value(raw_row, f"{where}.rows[{row_index}]", maximum=MAX_VARIABLES)
            if len(row_items) != len(variables):
                raise SolverContractError(f"{where}.rows[{row_index}] has invalid arity.")
            row = tuple(
                _scalar(raw, f"{where}.rows[{row_index}][{column}]")
                for column, raw in enumerate(row_items)
            )
            if any(
                value not in variable_domains[variable]
                for variable, value in zip(variables, row, strict=True)
            ):
                raise SolverContractError(
                    f"{where}.rows[{row_index}] contains an out-of-domain value."
                )
            rows.append(row)
        row_tuple = tuple(rows)
        if row_tuple != tuple(sorted(set(row_tuple))):
            raise SolverContractError(f"{where}.rows must be sorted and unique.")
        return TableConstraint(constraint_id, variables, mode, row_tuple)
    if kind is SolverConstraintKind.CLAUSE:
        only_keys(item, {"constraint_id", "constraint_type", "literals"}, where)
        raw_literals = array_value(item.get("literals"), f"{where}.literals", maximum=MAX_VARIABLES)
        if not raw_literals:
            raise SolverContractError(f"{where}.literals must not be empty.")
        literals: list[ClauseLiteral] = []
        for literal_index, raw_literal in enumerate(raw_literals):
            literal_where = f"{where}.literals[{literal_index}]"
            literal = object_value(raw_literal, literal_where)
            only_keys(literal, {"variable_id", "equals"}, literal_where)
            variable_id = _symbol(literal.get("variable_id"), f"{literal_where}.variable_id")
            if variable_id not in variable_domains:
                raise SolverContractError(f"{literal_where} references an unknown variable.")
            equals = _scalar(literal.get("equals"), f"{literal_where}.equals")
            if equals not in variable_domains[variable_id]:
                raise SolverContractError(f"{literal_where} value is outside the domain.")
            if profile is SolverProblemProfile.BOOLEAN_SAT and equals not in {0, 1}:
                raise SolverContractError("Boolean SAT literal must equal 0 or 1.")
            literals.append(ClauseLiteral(variable_id, equals))
        literal_tuple = tuple(literals)
        if literal_tuple != tuple(
            sorted(set(literal_tuple), key=lambda literal: (literal.variable_id, literal.equals))
        ):
            raise SolverContractError(f"{where}.literals must be sorted and unique.")
        return ClauseConstraint(constraint_id, literal_tuple)
    only_keys(
        item,
        {
            "constraint_id",
            "constraint_type",
            "left_start",
            "left_duration",
            "right_start",
            "right_duration",
        },
        where,
    )
    if profile is not SolverProblemProfile.FINITE_SCHEDULING:
        raise SolverContractError("Non-overlap requires the finite-scheduling profile.")
    left = _symbol(item.get("left_start"), f"{where}.left_start")
    right = _symbol(item.get("right_start"), f"{where}.right_start")
    if left == right or left not in variable_domains or right not in variable_domains:
        raise SolverContractError("Non-overlap start variables are invalid.")
    return NonOverlapConstraint(
        constraint_id,
        left,
        integer_value(
            item.get("left_duration"), f"{where}.left_duration", minimum=1, maximum=MAX_SCALAR
        ),
        right,
        integer_value(
            item.get("right_duration"), f"{where}.right_duration", minimum=1, maximum=MAX_SCALAR
        ),
    )


def _parse_objective(value: object, variable_domains: dict[str, set[int]]) -> SolverObjective:
    item = object_value(value, "content.problem.objective")
    only_keys(item, {"direction", "terms", "constant"}, "content.problem.objective")
    return SolverObjective(
        enum_value(
            ObjectiveDirection, item.get("direction"), "content.problem.objective.direction"
        ),
        _parse_terms(item.get("terms"), "content.problem.objective.terms", variable_domains),
        _scalar(item.get("constant"), "content.problem.objective.constant"),
    )


def _parse_terms(
    value: object, where: str, variable_domains: dict[str, set[int]]
) -> tuple[LinearTerm, ...]:
    raw_terms = array_value(value, where, maximum=MAX_VARIABLES)
    if not raw_terms:
        raise SolverContractError(f"{where} must not be empty.")
    terms: list[LinearTerm] = []
    for index, raw in enumerate(raw_terms):
        term_where = f"{where}[{index}]"
        item = object_value(raw, term_where)
        only_keys(item, {"variable_id", "coefficient"}, term_where)
        variable_id = _symbol(item.get("variable_id"), f"{term_where}.variable_id")
        if variable_id not in variable_domains:
            raise SolverContractError(f"{term_where} references an unknown variable.")
        coefficient = _scalar(item.get("coefficient"), f"{term_where}.coefficient")
        if coefficient == 0:
            raise SolverContractError(f"{term_where}.coefficient must not be zero.")
        terms.append(LinearTerm(variable_id, coefficient))
    result = tuple(terms)
    if result != tuple(sorted(result, key=lambda term: term.variable_id)) or len(
        {term.variable_id for term in result}
    ) != len(result):
        raise SolverContractError(f"{where} must be sorted and unique.")
    return result


def _parse_resource_policy(value: object) -> SolverResourcePolicy:
    where = "content.resource_policy"
    item = object_value(value, where)
    only_keys(
        item,
        {"max_solve_steps", "max_verification_steps", "timeout_milliseconds", "max_result_bytes"},
        where,
    )
    solve = integer_value(
        item.get("max_solve_steps"), f"{where}.max_solve_steps", minimum=1, maximum=MAX_STEPS
    )
    verify = integer_value(
        item.get("max_verification_steps"),
        f"{where}.max_verification_steps",
        minimum=1,
        maximum=MAX_STEPS,
    )
    if solve + verify > MAX_TOTAL_STEPS:
        raise SolverContractError("Solver Request total steps exceed the limit.")
    timeout = (
        None
        if item.get("timeout_milliseconds") is None
        else integer_value(
            item.get("timeout_milliseconds"),
            f"{where}.timeout_milliseconds",
            minimum=1,
            maximum=3_600_000,
        )
    )
    max_result = integer_value(
        item.get("max_result_bytes"),
        f"{where}.max_result_bytes",
        minimum=1,
        maximum=MAX_ARTIFACT_BYTES,
    )
    return SolverResourcePolicy(solve, verify, timeout, max_result)


def _parse_result(value: object) -> SolverResult:
    item = object_value(value, "content")
    only_keys(
        item,
        {
            "sensitivity",
            "request",
            "request_id",
            "contract_id",
            "candidate",
            "graph_id",
            "task_id",
            "context_snapshot_id",
            "adapter_id",
            "adapter_version",
            "license_expression",
            "provenance",
            "lease",
            "status",
            "witness",
            "objective_value",
            "objective_interval",
            "tolerance",
            "proof_disposition",
            "resources",
            "diagnostic_code",
        },
        "content",
    )
    _parse_tolerance(item.get("tolerance"), "content.tolerance")
    status = enum_value(SolverResultStatus, item.get("status"), "content.status")
    witness = None if item.get("witness") is None else _parse_witness(item.get("witness"))
    objective_value = (
        None
        if item.get("objective_value") is None
        else integer_value(
            item.get("objective_value"),
            "content.objective_value",
            minimum=-(10**15),
            maximum=10**15,
        )
    )
    interval = (
        None
        if item.get("objective_interval") is None
        else _parse_interval(item.get("objective_interval"))
    )
    proof = enum_value(
        SolverProofDisposition, item.get("proof_disposition"), "content.proof_disposition"
    )
    diagnostic = optional_string(item.get("diagnostic_code"), "content.diagnostic_code", maximum=64)
    if diagnostic is not None and diagnostic not in _DIAGNOSTICS:
        raise SolverContractError("Result diagnostic code is unsupported.")
    resources = _parse_resources(item.get("resources"))
    _validate_result_shape(status, witness, objective_value, interval, proof, diagnostic, resources)
    version = string_value(item.get("adapter_version"), "content.adapter_version", maximum=32)
    if _VERSION.fullmatch(version) is None:
        raise SolverContractError("Result adapter version is invalid.")
    license_expression = string_value(
        item.get("license_expression"), "content.license_expression", maximum=64
    )
    if _LICENSE.fullmatch(license_expression) is None:
        raise SolverContractError("Result license expression is invalid.")
    return SolverResult(
        sensitivity=enum_value(Sensitivity, item.get("sensitivity"), "content.sensitivity"),
        request=parse_artifact_reference(item.get("request"), "content.request"),
        request_id=solver_id(
            item.get("request_id"), "content.request_id", _PREFIX[SolverArtifactType.REQUEST]
        ),
        contract_id=solver_id(item.get("contract_id"), "content.contract_id", _CONTRACT_PREFIX),
        candidate=parse_candidate_identity(item.get("candidate"), "content.candidate"),
        graph_id=_pattern_id(item.get("graph_id"), "content.graph_id", _GRAPH),
        task_id=_pattern_id(item.get("task_id"), "content.task_id", _TASK),
        context_snapshot_id=_pattern_id(
            item.get("context_snapshot_id"), "content.context_snapshot_id", _CONTEXT
        ),
        adapter_id=_slug(item.get("adapter_id"), "content.adapter_id"),
        adapter_version=version,
        license_expression=license_expression,
        provenance=_references(item.get("provenance"), "content.provenance", minimum=1),
        lease=_parse_lease(item.get("lease")),
        status=status,
        witness=witness,
        objective_value=objective_value,
        objective_interval=interval,
        proof_disposition=proof,
        resources=resources,
        diagnostic_code=diagnostic,
    )


def _parse_verification(value: object) -> SolverVerification:
    item = object_value(value, "content")
    only_keys(
        item,
        {
            "sensitivity",
            "request",
            "request_id",
            "result",
            "result_id",
            "contract_id",
            "candidate",
            "graph_id",
            "task_id",
            "context_snapshot_id",
            "lease",
            "outcome",
            "adoption_allowed",
            "checks",
            "reasons",
            "verification_steps",
        },
        "content",
    )
    checks_raw = array_value(item.get("checks"), "content.checks", maximum=64)
    if not checks_raw:
        raise SolverContractError("Verification checks must not be empty.")
    checks: list[SolverVerificationCheck] = []
    for index, raw in enumerate(checks_raw):
        where = f"content.checks[{index}]"
        check = object_value(raw, where)
        only_keys(check, {"check_id", "passed"}, where)
        checks.append(
            SolverVerificationCheck(
                _slug(check.get("check_id"), f"{where}.check_id"),
                boolean_value(check.get("passed"), f"{where}.passed"),
            )
        )
    check_tuple = tuple(checks)
    if check_tuple != tuple(sorted(check_tuple, key=lambda check: check.check_id)) or len(
        {check.check_id for check in check_tuple}
    ) != len(check_tuple):
        raise SolverContractError("Verification checks must be sorted and unique.")
    reasons = _sorted_slugs(item.get("reasons"), "content.reasons")
    outcome = enum_value(SolverVerificationOutcome, item.get("outcome"), "content.outcome")
    adoption = boolean_value(item.get("adoption_allowed"), "content.adoption_allowed")
    if adoption and (
        outcome is not SolverVerificationOutcome.VERIFIED
        or not all(check.passed for check in check_tuple)
    ):
        raise SolverContractError("Adoption requires all checks to be verified.")
    return SolverVerification(
        sensitivity=enum_value(Sensitivity, item.get("sensitivity"), "content.sensitivity"),
        request=parse_artifact_reference(item.get("request"), "content.request"),
        request_id=solver_id(
            item.get("request_id"), "content.request_id", _PREFIX[SolverArtifactType.REQUEST]
        ),
        result=parse_artifact_reference(item.get("result"), "content.result"),
        result_id=solver_id(
            item.get("result_id"), "content.result_id", _PREFIX[SolverArtifactType.RESULT]
        ),
        contract_id=solver_id(item.get("contract_id"), "content.contract_id", _CONTRACT_PREFIX),
        candidate=parse_candidate_identity(item.get("candidate"), "content.candidate"),
        graph_id=_pattern_id(item.get("graph_id"), "content.graph_id", _GRAPH),
        task_id=_pattern_id(item.get("task_id"), "content.task_id", _TASK),
        context_snapshot_id=_pattern_id(
            item.get("context_snapshot_id"), "content.context_snapshot_id", _CONTEXT
        ),
        lease=_parse_lease(item.get("lease")),
        outcome=outcome,
        adoption_allowed=adoption,
        checks=check_tuple,
        reasons=reasons,
        verification_steps=integer_value(
            item.get("verification_steps"),
            "content.verification_steps",
            minimum=0,
            maximum=MAX_STEPS,
        ),
    )


def _parse_lease(value: object) -> SolverLeaseEvidence:
    where = "content.lease"
    item = object_value(value, where)
    only_keys(
        item,
        {
            "graph_id",
            "task_id",
            "host_id",
            "attempt",
            "lease_id",
            "fence",
            "idempotency_key",
            "dispatch_message_id",
            "expires_at",
            "reserved_solver_calls",
            "reserved_solver_steps",
        },
        where,
    )
    return SolverLeaseEvidence(
        graph_id=_pattern_id(item.get("graph_id"), f"{where}.graph_id", _GRAPH),
        task_id=_pattern_id(item.get("task_id"), f"{where}.task_id", _TASK),
        host_id=_pattern_id(item.get("host_id"), f"{where}.host_id", _HOST),
        attempt=integer_value(item.get("attempt"), f"{where}.attempt", minimum=1, maximum=3),
        lease_id=_pattern_id(item.get("lease_id"), f"{where}.lease_id", _LEASE),
        fence=integer_value(item.get("fence"), f"{where}.fence", minimum=1, maximum=1_000_000_000),
        idempotency_key=_pattern_id(
            item.get("idempotency_key"), f"{where}.idempotency_key", _IDEMPOTENCY
        ),
        dispatch_message_id=_pattern_id(
            item.get("dispatch_message_id"), f"{where}.dispatch_message_id", _MESSAGE
        ),
        expires_at=utc_timestamp(item.get("expires_at"), f"{where}.expires_at"),
        reserved_solver_calls=integer_value(
            item.get("reserved_solver_calls"),
            f"{where}.reserved_solver_calls",
            minimum=1,
            maximum=1,
        ),
        reserved_solver_steps=integer_value(
            item.get("reserved_solver_steps"),
            f"{where}.reserved_solver_steps",
            minimum=2,
            maximum=MAX_TOTAL_STEPS,
        ),
    )


def _parse_witness(value: object) -> SolverWitness:
    item = object_value(value, "content.witness")
    only_keys(item, {"assignments"}, "content.witness")
    raw_assignments = array_value(
        item.get("assignments"), "content.witness.assignments", maximum=MAX_VARIABLES
    )
    assignments: list[tuple[str, int]] = []
    for index, raw in enumerate(raw_assignments):
        where = f"content.witness.assignments[{index}]"
        assignment = object_value(raw, where)
        only_keys(assignment, {"variable_id", "value"}, where)
        assignments.append(
            (
                _symbol(assignment.get("variable_id"), f"{where}.variable_id"),
                _scalar(assignment.get("value"), f"{where}.value"),
            )
        )
    result = tuple(assignments)
    if (
        not result
        or result != tuple(sorted(result))
        or len({item[0] for item in result}) != len(result)
    ):
        raise SolverContractError("Witness assignments must be sorted and unique.")
    return SolverWitness(result)


def _parse_interval(value: object) -> ObjectiveInterval:
    item = object_value(value, "content.objective_interval")
    only_keys(item, {"lower", "upper"}, "content.objective_interval")
    lower = integer_value(
        item.get("lower"), "content.objective_interval.lower", minimum=-(10**15), maximum=10**15
    )
    upper = integer_value(
        item.get("upper"), "content.objective_interval.upper", minimum=-(10**15), maximum=10**15
    )
    if lower > upper:
        raise SolverContractError("Objective interval is reversed.")
    return ObjectiveInterval(lower, upper)


def _parse_resources(value: object) -> SolverResourceEvidence:
    where = "content.resources"
    item = object_value(value, where)
    only_keys(
        item,
        {
            "solver_calls",
            "solver_steps",
            "search_space_size",
            "visited_assignments",
            "unvisited_assignments",
            "constraint_checks",
            "elapsed_milliseconds",
            "step_limit",
            "timeout_milliseconds",
            "termination_reason",
        },
        where,
    )
    calls = integer_value(item.get("solver_calls"), f"{where}.solver_calls", minimum=0, maximum=1)
    steps = integer_value(
        item.get("solver_steps"), f"{where}.solver_steps", minimum=0, maximum=MAX_STEPS
    )
    space = integer_value(
        item.get("search_space_size"),
        f"{where}.search_space_size",
        minimum=1,
        maximum=MAX_SEARCH_SPACE,
    )
    visited = integer_value(
        item.get("visited_assignments"),
        f"{where}.visited_assignments",
        minimum=0,
        maximum=MAX_SEARCH_SPACE,
    )
    unvisited = integer_value(
        item.get("unvisited_assignments"),
        f"{where}.unvisited_assignments",
        minimum=0,
        maximum=MAX_SEARCH_SPACE,
    )
    step_limit = integer_value(
        item.get("step_limit"),
        f"{where}.step_limit",
        minimum=1,
        maximum=MAX_STEPS,
    )
    if visited != steps or visited + unvisited != space:
        raise SolverContractError("Result assignment accounting is inconsistent.")
    if steps > step_limit:
        raise SolverContractError("Result solver steps exceed its solve step limit.")
    timeout = (
        None
        if item.get("timeout_milliseconds") is None
        else integer_value(
            item.get("timeout_milliseconds"),
            f"{where}.timeout_milliseconds",
            minimum=1,
            maximum=3_600_000,
        )
    )
    return SolverResourceEvidence(
        calls,
        steps,
        space,
        visited,
        unvisited,
        integer_value(
            item.get("constraint_checks"),
            f"{where}.constraint_checks",
            minimum=0,
            maximum=MAX_SEARCH_SPACE * MAX_CONSTRAINTS,
        ),
        integer_value(
            item.get("elapsed_milliseconds"),
            f"{where}.elapsed_milliseconds",
            minimum=0,
            maximum=3_600_000,
        ),
        step_limit,
        timeout,
        enum_value(
            SolverTerminationReason, item.get("termination_reason"), f"{where}.termination_reason"
        ),
    )


def _validate_result_shape(
    status: SolverResultStatus,
    witness: SolverWitness | None,
    objective: int | None,
    interval: ObjectiveInterval | None,
    proof: SolverProofDisposition,
    diagnostic: str | None,
    resources: SolverResourceEvidence,
) -> None:
    positive = {
        SolverResultStatus.SATISFIABLE,
        SolverResultStatus.FEASIBLE,
        SolverResultStatus.BOUNDED,
        SolverResultStatus.OPTIMAL,
    }
    negative = {SolverResultStatus.UNSATISFIABLE, SolverResultStatus.INFEASIBLE}
    if status in positive and witness is None:
        raise SolverContractError("Positive Result requires a witness.")
    if status in negative and witness is not None:
        raise SolverContractError("Negative Result cannot contain a witness.")
    if (
        status
        in {SolverResultStatus.FEASIBLE, SolverResultStatus.BOUNDED, SolverResultStatus.OPTIMAL}
        and objective is None
    ):
        raise SolverContractError("Optimization Result requires an objective value.")
    if status in {SolverResultStatus.SATISFIABLE, SolverResultStatus.UNSATISFIABLE} and (
        objective is not None or interval is not None
    ):
        raise SolverContractError("Feasibility Result cannot contain objective evidence.")
    if status is SolverResultStatus.BOUNDED and (
        interval is None or proof is not SolverProofDisposition.OBJECTIVE_BOUND
    ):
        raise SolverContractError("Bounded Result requires objective-bound evidence.")
    if status is SolverResultStatus.OPTIMAL and (
        interval is None
        or interval.lower != interval.upper
        or proof is not SolverProofDisposition.EXHAUSTIVE_ENUMERATION
    ):
        raise SolverContractError("Optimal Result requires exact exhaustive evidence.")
    if status in negative and proof is not SolverProofDisposition.EXHAUSTIVE_ENUMERATION:
        raise SolverContractError("Negative Result requires exhaustive evidence.")
    if (
        status in {SolverResultStatus.SATISFIABLE, SolverResultStatus.FEASIBLE}
        and proof is not SolverProofDisposition.WITNESS
    ):
        raise SolverContractError("Witness Result has an invalid proof disposition.")
    incomplete = {
        SolverResultStatus.TIMEOUT,
        SolverResultStatus.UNAVAILABLE,
        SolverResultStatus.UNKNOWN,
        SolverResultStatus.ERROR,
    }
    if status in incomplete and proof is not SolverProofDisposition.NONE:
        raise SolverContractError("Incomplete Result cannot claim proof.")
    if status in incomplete and diagnostic is None:
        raise SolverContractError("Incomplete Result requires a diagnostic code.")
    if status not in incomplete and diagnostic is not None:
        raise SolverContractError("Complete Result cannot contain a diagnostic code.")
    if status is SolverResultStatus.UNAVAILABLE and (
        resources.solver_calls != 0 or resources.solver_steps != 0
    ):
        raise SolverContractError("Unavailable Result cannot report solver use.")
    expected_termination = {
        SolverResultStatus.SATISFIABLE: {SolverTerminationReason.WITNESS_FOUND},
        SolverResultStatus.FEASIBLE: {SolverTerminationReason.WITNESS_FOUND},
        SolverResultStatus.UNSATISFIABLE: {SolverTerminationReason.SEARCH_EXHAUSTED},
        SolverResultStatus.INFEASIBLE: {SolverTerminationReason.SEARCH_EXHAUSTED},
        SolverResultStatus.OPTIMAL: {SolverTerminationReason.SEARCH_EXHAUSTED},
        SolverResultStatus.BOUNDED: {SolverTerminationReason.STEP_LIMIT},
        SolverResultStatus.UNKNOWN: {SolverTerminationReason.STEP_LIMIT},
        SolverResultStatus.TIMEOUT: {
            SolverTerminationReason.REQUEST_TIMEOUT,
            SolverTerminationReason.LEASE_DEADLINE,
        },
        SolverResultStatus.UNAVAILABLE: {SolverTerminationReason.ADAPTER_UNAVAILABLE},
        SolverResultStatus.ERROR: {SolverTerminationReason.ADAPTER_ERROR},
    }
    if resources.termination_reason not in expected_termination[status]:
        raise SolverContractError("Result status and termination reason are inconsistent.")
    if status in positive | negative and (
        resources.solver_calls != 1 or resources.solver_steps == 0
    ):
        raise SolverContractError("Mathematical Result requires positive solver use.")
    if status in negative | {SolverResultStatus.OPTIMAL} and (
        resources.visited_assignments != resources.search_space_size
        or resources.unvisited_assignments != 0
    ):
        raise SolverContractError("Exhaustive Result requires complete search accounting.")
    if status in {SolverResultStatus.BOUNDED, SolverResultStatus.UNKNOWN} and (
        resources.solver_calls != 1
        or resources.solver_steps != resources.step_limit
        or resources.unvisited_assignments == 0
    ):
        raise SolverContractError("Step-limited Result has inconsistent accounting.")
    if status is SolverResultStatus.TIMEOUT and (
        resources.solver_calls != 1 or resources.unvisited_assignments == 0
    ):
        raise SolverContractError("Timeout Result has inconsistent accounting.")
    if status is not SolverResultStatus.TIMEOUT and resources.elapsed_milliseconds != 0:
        raise SolverContractError(
            "Non-timeout Result must use canonical zero elapsed evidence."
        )
    if status in {SolverResultStatus.UNAVAILABLE, SolverResultStatus.ERROR} and (
        resources.visited_assignments != 0
        or resources.constraint_checks != 0
        or resources.elapsed_milliseconds != 0
    ):
        raise SolverContractError("Non-solve Result must report exact zero-use evidence.")
    if status is SolverResultStatus.ERROR and resources.solver_calls != 1:
        raise SolverContractError("Controlled adapter error requires one solver call.")
    expected_diagnostic = {
        SolverResultStatus.UNKNOWN: "step-limit",
        SolverResultStatus.UNAVAILABLE: "adapter-unavailable",
        SolverResultStatus.ERROR: "adapter-error",
    }
    if status in expected_diagnostic and diagnostic != expected_diagnostic[status]:
        raise SolverContractError("Result diagnostic contradicts its status.")
    if status is SolverResultStatus.TIMEOUT and diagnostic != resources.termination_reason.value:
        raise SolverContractError("Timeout diagnostic contradicts its termination reason.")


def _validate_claim(kind: SolverProblemKind, claim: SolverRequiredClaim) -> None:
    if kind is SolverProblemKind.FEASIBILITY and claim is not SolverRequiredClaim.DECISION:
        raise SolverContractError("Feasibility requires the decision claim.")
    if kind is SolverProblemKind.OPTIMIZATION and claim is SolverRequiredClaim.DECISION:
        raise SolverContractError("Optimization claim is invalid.")


def _parse_tolerance(value: object, where: str) -> None:
    item = object_value(value, where)
    only_keys(item, {"kind", "absolute", "relative"}, where)
    if item != {"kind": "exact", "absolute": 0, "relative": 0}:
        raise SolverContractError("M7 tolerance must be exact zero.")


def _references(value: object, where: str, *, minimum: int = 0) -> tuple[ArtifactReference, ...]:
    refs = tuple(
        parse_artifact_reference(raw, f"{where}[{index}]")
        for index, raw in enumerate(array_value(value, where, maximum=64))
    )
    if (
        len(refs) < minimum
        or refs != tuple(sorted(refs, key=lambda ref: (ref.path, ref.sha256)))
        or len({(ref.path, ref.sha256) for ref in refs}) != len(refs)
    ):
        raise SolverContractError(f"{where} must be sorted and unique.")
    return refs


def _sorted_enums[E: StrEnum](enum_type: type[E], value: object, where: str) -> tuple[E, ...]:
    result = tuple(
        enum_value(enum_type, raw, f"{where}[{index}]")
        for index, raw in enumerate(array_value(value, where, maximum=64))
    )
    if result != tuple(sorted(set(result), key=lambda item: item.value)):
        raise SolverContractError(f"{where} must be sorted and unique.")
    return result


def _variable_ids(
    value: object, where: str, domains: dict[str, set[int]], *, minimum: int
) -> tuple[str, ...]:
    result = tuple(
        _symbol(raw, f"{where}[{index}]")
        for index, raw in enumerate(array_value(value, where, maximum=MAX_VARIABLES))
    )
    if (
        len(result) < minimum
        or len(set(result)) != len(result)
        or result != tuple(sorted(result))
    ):
        raise SolverContractError(f"{where} must be canonical and unique.")
    if any(identifier not in domains for identifier in result):
        raise SolverContractError(f"{where} references an unknown variable.")
    return result


def _sorted_slugs(value: object, where: str) -> tuple[str, ...]:
    result = tuple(
        _slug(raw, f"{where}[{index}]")
        for index, raw in enumerate(array_value(value, where, maximum=64))
    )
    if result != tuple(sorted(set(result))):
        raise SolverContractError(f"{where} must be sorted and unique.")
    return result


def _slug(value: object, where: str) -> str:
    text = string_value(value, where, maximum=64)
    if _SLUG.fullmatch(text) is None:
        raise SolverContractError(f"{where} must be a lowercase slug.")
    return text


def _symbol(value: object, where: str) -> str:
    text = string_value(value, where, maximum=64)
    if _SYMBOL.fullmatch(text) is None:
        raise SolverContractError(f"{where} must be a stable symbol.")
    return text


def _pattern_id(value: object, where: str, pattern: re.Pattern[str]) -> str:
    text = string_value(value, where, maximum=128)
    if pattern.fullmatch(text) is None:
        raise SolverContractError(f"{where} has an invalid identifier.")
    return text


def _scalar(value: object, where: str) -> int:
    return integer_value(value, where, minimum=-MAX_SCALAR, maximum=MAX_SCALAR)
