"""Run the named offline M7-SOLVER-EVIDENCE validator."""

# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from tests.m7_solver_helpers import (
    FIXED_TIME,
    HOST_ID,
    build_fixture,
    feasibility_problem,
    infeasible_problem,
    reference,
    registry_with_external_adapter,
    solver_task_result,
    start_solver_lease,
)
from tests.schema_validation import LocalSchemaValidator, SchemaValidationError

import sdaqf
from sdaqf.adapters.scheduler import recover_scheduler_database
from sdaqf.adapters.solver import (
    FiniteDomainReferenceAdapter,
    SolverAdapterError,
    SQLiteSolverLeaseEvidenceReader,
)
from sdaqf.application.orchestration import load_agent_registry, load_agent_result
from sdaqf.application.scheduler_contracts import (
    SchedulerContractError,
    load_scheduler_artifact,
)
from sdaqf.application.solver import SolverService
from sdaqf.application.solver_contracts import (
    SolverContractError,
    load_solver_artifact,
    parse_solver_artifact_bytes,
    serialize_solver_artifact,
    solver_identity,
    verify_reference,
)
from sdaqf.application.solver_verification import (
    SolverVerificationService,
    verify_loaded_solver_result,
)
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.scheduler import MailboxMessage, SchedulerArtifactType
from sdaqf.domain.solver import (
    LoadedSolverArtifact,
    SolverAdapterDefinition,
    SolverArtifactType,
    SolverLeaseEvidence,
    SolverProblem,
    SolverRegistry,
    SolverRequest,
    SolverRequiredClaim,
    SolverResult,
    SolverResultStatus,
    SolverVerification,
    SolverVerificationOutcome,
)

_FILES = {
    SolverArtifactType.REGISTRY: "solver-registry.json",
    SolverArtifactType.REQUEST: "solver-request.json",
    SolverArtifactType.RESULT: "solver-result.json",
    SolverArtifactType.VERIFICATION: "solver-verification.json",
}


def main() -> int:
    """Reproduce public M7 schema, binding, proof, and evaluation evidence."""

    root = Path.cwd().resolve(strict=True)
    if root != _REPOSITORY_ROOT.resolve(strict=True):
        raise RuntimeError("M7-SOLVER-EVIDENCE must run from the repository root.")
    examples = root / "examples" / "m7-solver"
    schema_validator = LocalSchemaValidator(root / "schemas")
    artifacts = {}
    for artifact_type, filename in _FILES.items():
        artifact = load_solver_artifact(examples / filename, expected_type=artifact_type)
        schema_validator.validate(filename.replace(".json", ".schema.json"), artifact.to_dict())
        if load_solver_artifact(examples / filename) != artifact:
            raise RuntimeError("M7 artifact round trip is not deterministic.")
        if not serialize_solver_artifact(artifact).endswith(b"\n"):
            raise RuntimeError("M7 serialization is not newline terminated.")
        artifacts[artifact_type] = artifact
    _validate_negative_contract_parity(root, schema_validator)

    graph = load_scheduler_artifact(
        examples / "task-graph.json",
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    request_artifact, _, adapter = SolverService().validate_request(
        examples / "solver-request.json",
        examples / "solver-registry.json",
        examples / "task-graph.json",
        root,
    )
    if request_artifact != artifacts[SolverArtifactType.REQUEST]:
        raise RuntimeError("M7 Request binding validation drifted.")

    result_artifact = artifacts[SolverArtifactType.RESULT]
    verification_artifact = artifacts[SolverArtifactType.VERIFICATION]
    request = request_artifact.value
    result = result_artifact.value
    verification = verification_artifact.value
    if not isinstance(request, SolverRequest) or not isinstance(result, SolverResult):
        raise RuntimeError("M7 public solve values have invalid types.")
    if not isinstance(verification, SolverVerification):
        raise RuntimeError("M7 public verification has an invalid type.")
    reproduced = verify_loaded_solver_result(
        request_artifact,
        result_artifact,
        result.request,
        verification.result,
        adapter,
        result.lease,
        result_size_bytes=(examples / "solver-result.json").stat().st_size,
    )
    if reproduced != verification_artifact:
        raise RuntimeError("M7 independent Verification does not reproduce.")
    if (
        result.status is not SolverResultStatus.OPTIMAL
        or verification.outcome is not SolverVerificationOutcome.VERIFIED
        or not verification.adoption_allowed
        or verification.verification_steps != result.resources.search_space_size
        or graph.artifact_id != request.graph_id
    ):
        raise RuntimeError("M7 public optimal evidence is not adoptable.")
    verify_reference(root, result.request)
    verify_reference(root, verification.result)

    registry = load_agent_registry(root / "examples" / "m2-orchestration" / "agent-registry.json")
    agent_result = load_agent_result(examples / "solver-agent-result.json", registry)
    if agent_result.status.value != "completed" or agent_result.changed_paths:
        raise RuntimeError("M7 read-only Agent Result is invalid.")

    suite = _load(root / "evals" / "m7-solver-suite.json")
    recorded = _load(root / "evals" / "results" / "m7-solver-evaluation.json")
    expected_cases = _object_array(suite.get("cases"))
    observed_cases = _object_array(recorded.get("cases"))
    reproduced_cases = _run_production_cases(root)
    statuses = {status.value for status in SolverResultStatus}
    if (
        suite.get("suite_id") != recorded.get("suite_id")
        or len(expected_cases) != 10
        or len(observed_cases) != 10
        or {str(item.get("expected_status")) for item in expected_cases} != statuses
        or [item.get("case_id") for item in observed_cases]
        != [item.get("case_id") for item in expected_cases]
        or reproduced_cases != observed_cases
        or any(item.get("passed") is not True for item in observed_cases)
        or _contains_aggregate(suite)
        or _contains_aggregate(recorded)
    ):
        raise RuntimeError("M7 ten-disposition evaluation evidence is invalid.")
    for expected, observed in zip(expected_cases, observed_cases, strict=True):
        for expected_key, observed_key in (
            ("expected_status", "observed_status"),
            ("expected_verification", "observed_verification"),
            ("expected_adoption", "observed_adoption"),
        ):
            if expected.get(expected_key) != observed.get(observed_key):
                raise RuntimeError("M7 evaluation observation contradicts its expectation.")
    evidence = recorded.get("public_evidence")
    if not isinstance(evidence, dict):
        raise RuntimeError("M7 public evaluation references are missing.")
    evidence_types = {
        "request": SolverArtifactType.REQUEST,
        "result": SolverArtifactType.RESULT,
        "verification": SolverArtifactType.VERIFICATION,
    }
    for name, artifact_type in evidence_types.items():
        reference = evidence.get(name)
        if not isinstance(reference, dict):
            raise RuntimeError("M7 public evaluation reference is invalid.")
        path = root.joinpath(*str(reference.get("path")).split("/"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if digest != reference.get("sha256"):
            raise RuntimeError("M7 public evaluation reference drifted.")
        if reference.get("artifact_id") != artifacts[artifact_type].artifact_id:
            raise RuntimeError("M7 public evaluation artifact identity drifted.")

    if sdaqf.__all__ != ["GateCheck", "GateResult", "ToolCapability", "ToolStatus"]:
        raise RuntimeError("M7 changed the stable top-level export surface.")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if project.get("project", {}).get("dependencies") != []:
        raise RuntimeError("M7 changed the dependency-free runtime boundary.")
    print("PASS: M7-SOLVER-EVIDENCE")
    return 0


def _validate_negative_contract_parity(
    root: Path,
    schema_validator: LocalSchemaValidator,
) -> None:
    request = _load(root / "examples" / "m7-solver" / "solver-request.json")
    content = request.get("content")
    if not isinstance(content, dict):
        raise RuntimeError("M7 public Request content is invalid.")
    tolerance = content.get("tolerance")
    if not isinstance(tolerance, dict):
        raise RuntimeError("M7 public Request tolerance is invalid.")
    tolerance["absolute"] = 1
    request["artifact_id"] = solver_identity(SolverArtifactType.REQUEST, content)
    schema_rejected = False
    runtime_rejected = False
    try:
        schema_validator.validate("solver-request.schema.json", request)
    except SchemaValidationError:
        schema_rejected = True
    try:
        parse_solver_artifact_bytes(
            (json.dumps(request, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
        )
    except SolverContractError:
        runtime_rejected = True
    if not schema_rejected or not runtime_rejected:
        raise RuntimeError("M7 schema/runtime negative contract parity drifted.")


class _ImmediateTimeoutClock:
    def __init__(self) -> None:
        self._monotonic = 0

    def now(self) -> datetime:
        return FIXED_TIME

    def monotonic_milliseconds(self) -> int:
        value = self._monotonic
        self._monotonic += 1
        return value


class _FailingAdapter:
    def solve(
        self,
        request: LoadedSolverArtifact,
        request_reference: ArtifactReference,
        adapter: SolverAdapterDefinition,
        lease: SolverLeaseEvidence,
    ) -> LoadedSolverArtifact:
        raise SolverAdapterError("deterministic M7 evaluation failure")


@dataclass(frozen=True, slots=True)
class _EvaluationCase:
    case_id: str
    problem: SolverProblem | None = None
    required_claim: SolverRequiredClaim = SolverRequiredClaim.OPTIMAL
    solve_steps: int = 16
    verification_steps: int = 16
    timeout_milliseconds: int | None = None
    registry: SolverRegistry | None = None
    adapter_id: str = "stdlib-finite-domain-v1"


def _run_production_cases(root: Path) -> list[dict[str, Any]]:
    cases = (
        _EvaluationCase(
            "satisfiable",
            problem=feasibility_problem(satisfiable=True),
            required_claim=SolverRequiredClaim.DECISION,
            solve_steps=2,
            verification_steps=2,
        ),
        _EvaluationCase(
            "unsatisfiable",
            problem=feasibility_problem(satisfiable=False),
            required_claim=SolverRequiredClaim.DECISION,
            solve_steps=2,
            verification_steps=2,
        ),
        _EvaluationCase(
            "feasible",
            required_claim=SolverRequiredClaim.FEASIBLE,
        ),
        _EvaluationCase(
            "infeasible",
            problem=infeasible_problem(),
            solve_steps=1,
            verification_steps=1,
        ),
        _EvaluationCase("optimal"),
        _EvaluationCase(
            "bounded",
            required_claim=SolverRequiredClaim.BOUNDED,
            solve_steps=3,
        ),
        _EvaluationCase("timeout", timeout_milliseconds=1),
        _EvaluationCase(
            "unavailable",
            registry=registry_with_external_adapter(),
            adapter_id="optional-local-cli",
        ),
        _EvaluationCase("unknown", solve_steps=1),
        _EvaluationCase("error"),
    )
    reproduced: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=".sdaqf-m7-validator-", dir=root) as raw:
        temporary = Path(raw)
        for case in cases:
            case_id = case.case_id
            fixture = build_fixture(
                temporary / case_id,
                problem=case.problem,
                required_claim=case.required_claim,
                solve_steps=case.solve_steps,
                verification_steps=case.verification_steps,
                timeout_milliseconds=case.timeout_milliseconds,
                registry=case.registry,
                adapter_id=case.adapter_id,
            )
            store, dispatch = start_solver_lease(fixture)
            dispatch_value = dispatch.value
            if not isinstance(dispatch_value, MailboxMessage) or dispatch_value.lease_id is None:
                raise RuntimeError("M7 evaluation dispatch lacks Lease authority.")
            service = SolverService()
            if case_id == "timeout":
                service = SolverService(
                    adapter=FiniteDomainReferenceAdapter(_ImmediateTimeoutClock())
                )
            elif case_id == "error":
                service = SolverService(adapter=_FailingAdapter())
            result_artifact = service.run(
                fixture.request_path,
                fixture.registry_path,
                fixture.graph_path,
                fixture.state_path,
                root,
                HOST_ID,
                dispatch_value.lease_id,
                fixture.result_path,
            )
            verification_artifact = SolverVerificationService().verify(
                fixture.result_path,
                fixture.request_path,
                fixture.registry_path,
                fixture.graph_path,
                fixture.state_path,
                root,
                HOST_ID,
                dispatch_value.lease_id,
                fixture.verification_path,
            )
            result = result_artifact.value
            verification = verification_artifact.value
            if not isinstance(result, SolverResult) or not isinstance(
                verification, SolverVerification
            ):
                raise RuntimeError("M7 evaluation returned invalid typed evidence.")
            reproduced.append(
                {
                    "case_id": case_id,
                    "observed_status": result.status.value,
                    "observed_verification": verification.outcome.value,
                    "observed_adoption": verification.adoption_allowed,
                    "passed": True,
                }
            )
            if case_id == "optimal":
                message = solver_task_result(
                    dispatch,
                    result_artifact,
                    verification_artifact,
                    fixture.result_path,
                    fixture.verification_path,
                )
                store.tick(
                    root,
                    HOST_ID,
                    (message,),
                    FIXED_TIME + timedelta(seconds=2),
                )
                store.validate()
                recovered = recover_scheduler_database(
                    fixture.state_path,
                    temporary / "recovered.sqlite3",
                    root,
                )
                if recovered.status() != store.status():
                    raise RuntimeError("M7 scheduler recovery changed adopted evidence.")
        _validate_failed_rejected_evidence(root, temporary)
    return reproduced


def _validate_failed_rejected_evidence(root: Path, temporary: Path) -> None:
    fixture = build_fixture(
        temporary / "failed-rejected-evidence",
        max_result_bytes=4_096,
    )
    store, dispatch = start_solver_lease(fixture)
    dispatch_value = dispatch.value
    request = fixture.request.value
    registry = fixture.registry.value
    if (
        not isinstance(dispatch_value, MailboxMessage)
        or dispatch_value.lease_id is None
        or not isinstance(request, SolverRequest)
        or not isinstance(registry, SolverRegistry)
    ):
        raise RuntimeError("M7 rejected-evidence fixture is invalid.")
    lease = SQLiteSolverLeaseEvidenceReader().observe(
        fixture.state_path,
        root,
        graph_id=request.graph_id,
        task_id=request.task_id,
        host_id=HOST_ID,
        lease_id=dispatch_value.lease_id,
        require_current=True,
    )
    result_artifact = FiniteDomainReferenceAdapter().solve(
        fixture.request,
        reference(fixture.request_path),
        registry.adapters[0],
        lease,
    )
    canonical = serialize_solver_artifact(result_artifact)
    padding = b" " * (request.resource_policy.max_result_bytes - len(canonical) + 1)
    if not padding:
        raise RuntimeError("M7 Result byte-limit fixture is not bounded.")
    fixture.result_path.write_bytes(canonical + padding)
    verification_artifact = SolverVerificationService().verify(
        fixture.result_path,
        fixture.request_path,
        fixture.registry_path,
        fixture.graph_path,
        fixture.state_path,
        root,
        HOST_ID,
        dispatch_value.lease_id,
        fixture.verification_path,
    )
    verification = verification_artifact.value
    if (
        not isinstance(verification, SolverVerification)
        or verification.outcome is not SolverVerificationOutcome.REJECTED
    ):
        raise RuntimeError("M7 oversized Result was not rejected.")
    message = solver_task_result(
        dispatch,
        result_artifact,
        verification_artifact,
        fixture.result_path,
        fixture.verification_path,
        outcome="failed",
    )
    try:
        store.tick(
            root,
            HOST_ID,
            (message,),
            FIXED_TIME + timedelta(seconds=2),
        )
    except SchedulerContractError:
        return
    raise RuntimeError("M7 accepted rejected evidence for a failed Task Result.")


def _load(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must contain an object.")
    return value


def _object_array(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError("M7 evaluation cases must be an object array.")
    return value


def _contains_aggregate(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key == "aggregate_score" or _contains_aggregate(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_aggregate(item) for item in value)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
