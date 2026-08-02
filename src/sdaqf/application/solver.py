"""Application services for strict M7 solver validation and execution."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sdaqf.adapters.context import ExclusiveJSONPublisher
from sdaqf.adapters.solver import (
    FiniteDomainReferenceAdapter,
    SolverAdapterError,
    SQLiteSolverLeaseEvidenceReader,
    adapter_error_result,
    adapter_unavailable_result,
)
from sdaqf.application.context_contracts import load_context_artifact
from sdaqf.application.scheduler_contracts import load_scheduler_artifact
from sdaqf.application.solver_contracts import (
    SolverContractError,
    load_solver_artifact,
    parse_solver_capability_token,
    search_space_size,
    serialize_solver_artifact,
    solver_capability_token,
    verify_reference,
)
from sdaqf.application.tooling import load_tool_registry
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.context import SENSITIVITY_RANK, ContextArtifactType, ContextSnapshot
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.scheduler import EffectKind, SchedulerArtifactType, TaskGraph, TaskKind
from sdaqf.domain.solver import (
    AllDifferentConstraint,
    ClauseConstraint,
    LinearConstraint,
    LoadedSolverArtifact,
    NonOverlapConstraint,
    SolverAdapterDefinition,
    SolverAdapterKind,
    SolverArtifactType,
    SolverProblem,
    SolverRegistry,
    SolverRequest,
    TableConstraint,
)
from sdaqf.ports.context import ImmutableJSONPublisher
from sdaqf.ports.solver import SolverAdapterPort, SolverLeaseEvidencePort


class SolverService:
    """Coordinate explicit local M7 validation and reference execution."""

    def __init__(
        self,
        *,
        adapter: SolverAdapterPort | None = None,
        lease_reader: SolverLeaseEvidencePort | None = None,
        publisher: ImmutableJSONPublisher | None = None,
    ) -> None:
        self._adapter = FiniteDomainReferenceAdapter() if adapter is None else adapter
        self._lease_reader = (
            SQLiteSolverLeaseEvidenceReader() if lease_reader is None else lease_reader
        )
        self._publisher = ExclusiveJSONPublisher() if publisher is None else publisher

    def validate_registry(self, registry: Path, root: Path) -> LoadedSolverArtifact:
        """Validate one Registry and every exact provenance reference."""

        resolved_root = _regular_root(root)
        path = _existing_json_under_root(resolved_root, registry)
        artifact = load_solver_artifact(path, expected_type=SolverArtifactType.REGISTRY)
        value = artifact.value
        assert isinstance(value, SolverRegistry)
        for adapter in value.adapters:
            for reference in adapter.provenance:
                verify_reference(resolved_root, reference)
            if adapter.tool_registry is not None:
                tool_registry_path = verify_reference(resolved_root, adapter.tool_registry)
                tool_registry = load_tool_registry(tool_registry_path)
                tool = (
                    None
                    if adapter.tool_name is None
                    else tool_registry.by_name(adapter.tool_name)
                )
                if (
                    tool is None
                    or adapter.executable != tool.version_command[0]
                    or adapter.version_matcher != tool.version_pattern
                    or tool.network_required
                    or tool.network_destinations
                    or not tool.optional
                ):
                    raise SolverContractError(
                        "External adapter does not match its exact Tool Registry entry."
                    )
            if (
                adapter.version_observation is not None
                and adapter.version_observation.evidence is not None
            ):
                verify_reference(resolved_root, adapter.version_observation.evidence)
        return artifact

    def validate_request(
        self,
        request: Path,
        registry: Path,
        task_graph: Path,
        root: Path,
    ) -> tuple[LoadedSolverArtifact, LoadedSolverArtifact, SolverAdapterDefinition]:
        """Validate a Request against exact Registry, M6 graph, and M5 Snapshot."""

        resolved_root = _regular_root(root)
        request_path = _existing_json_under_root(resolved_root, request)
        registry_path = _existing_json_under_root(resolved_root, registry)
        graph_path = _existing_json_under_root(resolved_root, task_graph)
        request_artifact = load_solver_artifact(
            request_path, expected_type=SolverArtifactType.REQUEST
        )
        registry_artifact = self.validate_registry(registry_path, resolved_root)
        request_value = request_artifact.value
        registry_value = registry_artifact.value
        assert isinstance(request_value, SolverRequest)
        assert isinstance(registry_value, SolverRegistry)
        _require_exact_path(resolved_root, registry_path, request_value.registry)
        if registry_artifact.artifact_id != request_value.registry_id:
            raise SolverContractError("Request Registry identity is inconsistent.")

        graph_reference_path = _require_exact_path(
            resolved_root, graph_path, request_value.task_graph
        )
        graph_artifact = load_scheduler_artifact(
            graph_reference_path,
            expected_type=SchedulerArtifactType.TASK_GRAPH,
            root=resolved_root,
        )
        graph = graph_artifact.value
        assert isinstance(graph, TaskGraph)
        if graph_artifact.artifact_id != request_value.graph_id:
            raise SolverContractError("Request Task Graph identity is inconsistent.")
        if graph.candidate != request_value.candidate:
            raise SolverContractError("Request candidate does not match the Task Graph.")
        tasks = {task.task_id: task for task in graph.tasks}
        task = tasks.get(request_value.task_id)
        if task is None or task.kind is not TaskKind.SOLVER:
            raise SolverContractError("Request does not bind an M6 solver task.")
        if (
            task.effect_kind is not EffectKind.READ_ONLY
            or task.required_tools
            or task.owned_paths
            or task.worktree_assignment is not None
            or task.evidence_predicate != ("evidence-reference-present",)
            or task.terminal_predicate != ("agent-result-valid",)
        ):
            raise SolverContractError("M6 solver task boundary is incompatible with M7.")
        tokens = tuple(
            capability
            for capability in task.required_capabilities
            if capability.startswith("m7-solver-v1@")
        )
        if len(tokens) != 1 or tokens[0] != solver_capability_token(request_value):
            raise SolverContractError("M6 solver task token does not match the Request.")
        contract_id, solve_steps, verification_steps = parse_solver_capability_token(tokens[0])
        if (
            contract_id != request_value.contract_id
            or solve_steps != request_value.resource_policy.max_solve_steps
            or verification_steps != request_value.resource_policy.max_verification_steps
            or graph.budget.max_solver_calls < 1
            or solve_steps + verification_steps > graph.budget.max_solver_steps
        ):
            raise SolverContractError("Request exceeds the exact M6 solver budget.")

        contexts = {binding.artifact_id: binding for binding in graph.contexts}
        context = contexts.get(request_value.context_snapshot_id)
        if context is None or task.context_snapshot_id != request_value.context_snapshot_id:
            raise SolverContractError("Request Context Snapshot is not assigned to the task.")
        if context.reference != request_value.context_snapshot:
            raise SolverContractError("Request Context Snapshot reference is inconsistent.")
        context_path = verify_reference(resolved_root, request_value.context_snapshot)
        context_artifact = load_context_artifact(
            context_path, expected_type=ContextArtifactType.SNAPSHOT
        )
        snapshot = context_artifact.value
        assert isinstance(snapshot, ContextSnapshot)
        if (
            context_artifact.artifact_id != request_value.context_snapshot_id
            or snapshot.candidate != request_value.candidate
            or context.candidate != request_value.candidate
            or context.sensitivity != snapshot.sensitivity
            or SENSITIVITY_RANK[request_value.sensitivity]
            < max(
                SENSITIVITY_RANK[registry_value.sensitivity],
                SENSITIVITY_RANK[context.sensitivity],
            )
        ):
            raise SolverContractError("Request Context/candidate/sensitivity binding is invalid.")

        matching = tuple(
            adapter
            for adapter in registry_value.adapters
            if adapter.adapter_id == request_value.adapter_id
        )
        if len(matching) != 1:
            raise SolverContractError("Request adapter is absent or ambiguous.")
        adapter = matching[0]
        problem = request_value.problem
        constraint_kinds = {constraint.constraint_type for constraint in problem.constraints}
        if (
            problem.problem_kind not in adapter.supported_problem_kinds
            or problem.profile not in adapter.supported_profiles
            or not constraint_kinds.issubset(adapter.supported_constraints)
            or len(problem.variables) > adapter.max_variables
            or any(
                len(variable.domain.values) > adapter.max_domain_values
                for variable in problem.variables
            )
            or search_space_size(problem) > adapter.max_search_space
            or len(problem.constraints) > adapter.max_constraints
            or any(
                _constraint_variable_count(constraint) > adapter.max_constraint_variables
                for constraint in problem.constraints
            )
            or any(
                isinstance(constraint, TableConstraint)
                and len(constraint.rows) > adapter.max_table_rows
                for constraint in problem.constraints
            )
            or any(
                scalar < adapter.min_scalar or scalar > adapter.max_scalar
                for scalar in _problem_scalars(problem)
            )
            or request_path.stat().st_size > adapter.max_artifact_bytes
            or request_value.resource_policy.max_result_bytes > adapter.max_artifact_bytes
        ):
            raise SolverContractError("Request exceeds the selected adapter capability.")
        return request_artifact, registry_artifact, adapter

    def run(
        self,
        request: Path,
        registry: Path,
        task_graph: Path,
        state: Path,
        root: Path,
        host_id: str,
        lease_id: str,
        output: Path,
    ) -> LoadedSolverArtifact:
        """Run one authorized local solve and exclusively publish its Result."""

        resolved_root = _regular_root(root)
        request_artifact, _, adapter = self.validate_request(
            request, registry, task_graph, resolved_root
        )
        request_value = request_artifact.value
        assert isinstance(request_value, SolverRequest)
        request_path = _existing_json_under_root(resolved_root, request)
        request_reference = _reference_for_path(resolved_root, request_path)
        lease = self._lease_reader.observe(
            state,
            resolved_root,
            graph_id=request_value.graph_id,
            task_id=request_value.task_id,
            host_id=host_id,
            lease_id=lease_id,
            require_current=True,
        )
        expected_steps = (
            request_value.resource_policy.max_solve_steps
            + request_value.resource_policy.max_verification_steps
        )
        if lease.reserved_solver_calls != 1 or lease.reserved_solver_steps != expected_steps:
            raise SolverContractError("M6 Lease reservation does not match the Request.")
        if adapter.adapter_kind is SolverAdapterKind.EXTERNAL_CLI:
            result = adapter_unavailable_result(
                request_artifact, request_reference, adapter, lease
            )
        else:
            try:
                result = self._adapter.solve(request_artifact, request_reference, adapter, lease)
            except SolverAdapterError:
                result = adapter_error_result(
                    request_artifact,
                    request_reference,
                    adapter,
                    lease,
                )
        encoded = serialize_solver_artifact(result)
        if len(encoded) > request_value.resource_policy.max_result_bytes:
            raise SolverContractError("Solver Result exceeds the Request byte limit.")
        target = _fresh_json_under_root(resolved_root, output)
        self._publisher.publish(target, encoded)
        return result


def _regular_root(root: Path) -> Path:
    try:
        lexical = root.absolute()
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise SolverContractError("Solver root is unavailable.") from exc
    if (
        lexical != resolved
        or not resolved.is_dir()
        or root.is_symlink()
        or is_reparse_point(root)
    ):
        raise SolverContractError("Solver root must be a regular directory.")
    return resolved


def _constraint_variable_count(
    constraint: LinearConstraint
    | AllDifferentConstraint
    | TableConstraint
    | ClauseConstraint
    | NonOverlapConstraint,
) -> int:
    if isinstance(constraint, LinearConstraint):
        return len(constraint.terms)
    if isinstance(constraint, (AllDifferentConstraint, TableConstraint)):
        return len(constraint.variable_ids)
    if isinstance(constraint, ClauseConstraint):
        return len({literal.variable_id for literal in constraint.literals})
    return 2


def _problem_scalars(problem: SolverProblem) -> tuple[int, ...]:
    scalars: list[int] = []
    for variable in problem.variables:
        scalars.extend(variable.domain.values)
    for constraint in problem.constraints:
        if isinstance(constraint, LinearConstraint):
            scalars.extend(term.coefficient for term in constraint.terms)
            scalars.append(constraint.right_hand_side)
        elif isinstance(constraint, TableConstraint):
            scalars.extend(value for row in constraint.rows for value in row)
        elif isinstance(constraint, ClauseConstraint):
            scalars.extend(literal.equals for literal in constraint.literals)
        elif isinstance(constraint, NonOverlapConstraint):
            scalars.extend((constraint.left_duration, constraint.right_duration))
    if problem.objective is not None:
        scalars.extend(term.coefficient for term in problem.objective.terms)
        scalars.append(problem.objective.constant)
    return tuple(scalars)


def _existing_json_under_root(root: Path, path: Path) -> Path:
    candidate = _lexical_under_root(root, path, include_target=True)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SolverContractError("Solver input is unavailable.") from exc
    if (
        not resolved.is_relative_to(root)
        or resolved.suffix.casefold() != ".json"
        or not resolved.is_file()
        or resolved.is_symlink()
        or is_reparse_point(resolved)
    ):
        raise SolverContractError("Solver input must be a regular JSON file under root.")
    return resolved


def _fresh_json_under_root(root: Path, path: Path) -> Path:
    candidate = _lexical_under_root(root, path, include_target=False)
    try:
        parent = candidate.parent.resolve(strict=True)
    except OSError as exc:
        raise SolverContractError("Solver output parent is unavailable.") from exc
    if (
        not parent.is_relative_to(root)
        or parent.is_symlink()
        or is_reparse_point(parent)
        or candidate.suffix.casefold() != ".json"
        or candidate.exists()
        or candidate.is_symlink()
        or is_reparse_point(candidate)
    ):
        raise SolverContractError("Solver output must be a fresh JSON file under root.")
    return candidate


def _lexical_under_root(root: Path, path: Path, *, include_target: bool) -> Path:
    """Reject every lexical link/reparse component before any path resolution."""

    try:
        candidate = (path if path.is_absolute() else root / path).absolute()
        relative = candidate.relative_to(root)
    except (OSError, ValueError) as exc:
        raise SolverContractError("Solver path is outside the explicit root.") from exc
    components = relative.parts if include_target else relative.parts[:-1]
    current = root
    for component in components:
        current = current / component
        if current.is_symlink() or is_reparse_point(current):
            raise SolverContractError("Solver path contains a linked or reparse component.")
    if not include_target and (candidate.is_symlink() or is_reparse_point(candidate)):
        raise SolverContractError("Solver output target must be unlinked.")
    return candidate


def _require_exact_path(root: Path, explicit: Path, reference: ArtifactReference) -> Path:
    referenced = verify_reference(root, reference)
    if explicit.resolve(strict=True) != referenced.resolve(strict=True):
        raise SolverContractError("Explicit solver input does not match its reference.")
    return referenced


def _reference_for_path(root: Path, path: Path) -> ArtifactReference:
    relative = path.relative_to(root).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    return ArtifactReference(relative, digest)
