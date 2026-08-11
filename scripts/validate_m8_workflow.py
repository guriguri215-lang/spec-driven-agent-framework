"""Run the named offline M8-WORKFLOW-INTEGRATION validator."""

# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from tests.m8_workflow_helpers import (
    FixedClock,
    create_explainer,
    create_outcome,
    create_plan,
    create_planner,
    create_recovery,
    create_runtime,
    create_scheduler,
    create_workspace,
    workflow_binding,
)
from tests.schema_validation import LocalSchemaValidator, SchemaValidationError

import sdaqf
from scripts.validate_m5_context import main as validate_m5
from scripts.validate_m6_scheduler import main as validate_m6
from scripts.validate_m7_solver import main as validate_m7
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.baselines import load_baseline
from sdaqf.application.context_contracts import canonical_json_bytes, load_context_artifact
from sdaqf.application.context_quality import measure_context_quality
from sdaqf.application.contracts import load_json_object, parse_artifact_reference
from sdaqf.application.evidence import load_evidence_ledger
from sdaqf.application.handoffs import load_automated_handoff
from sdaqf.application.quality_gates import load_independent_review
from sdaqf.application.release_qa import load_release_candidate
from sdaqf.application.scheduler_contracts import (
    artifact_from_value as scheduler_artifact_from_value,
)
from sdaqf.application.scheduler_contracts import load_scheduler_artifact
from sdaqf.application.solver_contracts import load_solver_artifact
from sdaqf.application.ui_validation import load_manifest_ui, load_ui_validation
from sdaqf.application.workflow_contracts import (
    LoadedWorkflowArtifact,
    WorkflowContractError,
    load_workflow_artifact,
    parse_workflow_artifact_bytes,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_runtime import _replay_scheduler_state
from sdaqf.application.workflow_simulation import (
    SCENARIOS,
    WorkflowSimulationError,
    WorkflowSimulationEvidence,
    WorkflowSimulationResult,
    run_all_scenarios,
)
from sdaqf.domain.context import (
    ContextArtifactType,
    ContextGraph,
    ContextQualityReport,
    ContextSelection,
    ContextSnapshot,
)
from sdaqf.domain.scheduler import (
    BudgetLedger,
    MailboxMessage,
    MessageType,
    SchedulerArtifactType,
    SchedulerEvent,
    SchedulerState,
    TaskGraph,
    TaskKind,
    TaskOutcome,
    TaskState,
    WorktreeLease,
)
from sdaqf.domain.solver import SolverArtifactType, SolverVerification
from sdaqf.domain.workflow import (
    CompletionProfile,
    IntegratedPlan,
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowMeasurement,
    WorkflowOutcome,
    WorkflowState,
)

_FILES = {
    WorkflowArtifactType.DEVELOPMENT_INTENT: "development-intent.json",
    WorkflowArtifactType.INTEGRATED_PLAN: "integrated-plan.json",
    WorkflowArtifactType.WORKFLOW_STATE: "workflow-state.json",
    WorkflowArtifactType.WORKFLOW_EVENT: "workflow-event.json",
    WorkflowArtifactType.WORKFLOW_OUTCOME: "workflow-outcome.json",
}
_MEASUREMENT_CONTRACT = {
    "requirements": (
        "required_requirement_count",
        "covered_requirement_count",
        "uncovered_requirement_ids",
        "scope_addition_count",
        "blocking_diagnostic_count",
    ),
    "context": (
        "required_reference_count",
        "selected_required_reference_count",
        "stale_required_count",
        "provenance_missing_count",
        "sensitivity_violation_count",
        "selected_context_bytes",
        "context_budget_bytes",
        "unresolved_contradiction_count",
    ),
    "scheduling": (
        "task_count",
        "completed_task_count",
        "blocked_task_count",
        "retry_used_count",
        "duplicate_rejection_count",
        "late_result_rejection_count",
        "deadlock_count",
    ),
    "solver": (
        "solver_task_count",
        "status_counts",
        "verified_result_count",
        "adoptable_result_count",
        "solver_calls_used",
        "solver_steps_used",
    ),
    "evidence": (
        "claim_count",
        "verified_claim_count",
        "unverified_claim_count",
        "known_problem_count",
        "missing_evidence_count",
    ),
    "handoff": (
        "handoff_created_count",
        "handoff_resume_failure_count",
        "incomplete_item_count",
        "open_decision_count",
        "known_problem_count",
    ),
    "recovery": (
        "resume_attempt_count",
        "successful_resume_count",
        "recovery_attempt_count",
        "successful_recovery_count",
        "ambiguous_effect_count",
    ),
    "approval": (
        "required_approval_count",
        "consumed_approval_count",
        "refused_approval_count",
        "expired_approval_count",
        "pending_approval_count",
        "approval_revalidation_failure_count",
    ),
    "available_cost": (
        "status",
        "currency",
        "budget_microunits",
        "used_microunits",
        "remaining_microunits",
    ),
}
_MEASUREMENT_GROUPS = set(_MEASUREMENT_CONTRACT)
_MEASUREMENT_OBSERVATION_TYPES = {
    SolverArtifactType.VERIFICATION.value,
    "automated-handoff",
    "evidence-ledger",
    "independent-review",
    "project-manifest",
    "release-candidate",
    "ui-validation",
}


def main() -> int:
    """Reproduce public schemas, native composition, simulation, and recovery."""

    root = Path.cwd().resolve(strict=True)
    if root != _REPOSITORY_ROOT.resolve(strict=True):
        raise RuntimeError("M8-WORKFLOW-INTEGRATION must run from repository root.")
    validator = LocalSchemaValidator(root / "schemas")
    examples = root / "examples" / "m8-workflow"
    artifacts = {}
    for artifact_type, filename in _FILES.items():
        artifact = load_workflow_artifact(
            examples / filename,
            expected_type=artifact_type,
        )
        validator.validate(filename.replace(".json", ".schema.json"), artifact.to_dict())
        reparsed = parse_workflow_artifact_bytes(
            serialize_workflow_artifact(artifact),
            expected_type=artifact_type,
        )
        if reparsed != artifact:
            raise RuntimeError("M8 public artifact does not round trip exactly.")
        artifacts[artifact_type] = artifact
    state = artifacts[WorkflowArtifactType.WORKFLOW_STATE].value
    outcome = artifacts[WorkflowArtifactType.WORKFLOW_OUTCOME].value
    assert isinstance(state, WorkflowState)
    assert isinstance(outcome, WorkflowOutcome)
    if (
        state.latest_event.artifact_id != artifacts[WorkflowArtifactType.WORKFLOW_EVENT].artifact_id
        or outcome.terminal_state_id != artifacts[WorkflowArtifactType.WORKFLOW_STATE].artifact_id
    ):
        raise RuntimeError("M8 public Event, State, and Outcome lineage drifted.")
    _negative_contract_parity(root, validator)

    with tempfile.TemporaryDirectory(prefix="m8-") as name:
        workspace = create_workspace(Path(name))
        plan, _ = create_plan(workspace)
        scheduler = create_scheduler(workspace)
        explanation = create_explainer().explain(plan, workspace, scheduler)
        if not explanation.get("deterministic") or not explanation.get("side_effect_free"):
            raise RuntimeError("M8 Plan explanation is not deterministic and pure.")
        runtime = create_runtime(FixedClock())
        transition = runtime.run(
            plan,
            workspace,
            scheduler,
            workspace / "workflow/state.json",
            workspace / "workflow/event.json",
        )
        if transition.host_dispatch_performed or not transition.outgoing_intent_ids:
            raise RuntimeError("M8 runtime dispatched a host or lost typed intent.")
        status = runtime.status(transition.state, plan, workspace, scheduler)
        if not status.get("side_effect_free"):
            raise RuntimeError("M8 status is not side-effect-free.")
        recovered, recovery_event = create_recovery(FixedClock()).recover(
            transition.state,
            workflow_binding(
                workspace,
                workspace / "workflow/state.json",
                transition.state,
            ),
            plan,
            (),
            workspace,
            scheduler,
            workspace / "workflow/recovered-state.json",
            workspace / "workflow/recovery-event.json",
        )
        if recovered.artifact_id == transition.state.artifact_id:
            raise RuntimeError("M8 recovery did not produce a fresh State.")
        recovery_event_value = recovery_event.value
        if not isinstance(recovery_event_value, WorkflowEvent):
            raise RuntimeError("M8 recovery did not publish a Workflow Event.")
        if recovery_event_value.cause.value != "recovery-observed":
            raise RuntimeError("M8 recovery Event cause drifted.")
        derived, outcome_event, outcome_state = create_outcome(FixedClock()).publish(
            recovered,
            workflow_binding(
                workspace,
                workspace / "workflow/recovered-state.json",
                recovered,
            ),
            plan,
            workspace,
            scheduler,
            workspace / "workflow/outcome.json",
            workspace / "workflow/outcome-event.json",
            workspace / "workflow/outcome-state.json",
        )
        derived_value = derived.value
        outcome_event_value = outcome_event.value
        outcome_state_value = outcome_state.value
        if not isinstance(derived_value, WorkflowOutcome):
            raise RuntimeError("M8 outcome derivation returned the wrong artifact.")
        if not isinstance(outcome_event_value, WorkflowEvent) or not isinstance(
            outcome_state_value, WorkflowState
        ):
            raise RuntimeError("M8 Outcome Event/State closure drifted.")
        if derived_value.disposition.value != "completed":
            raise RuntimeError("M8 plan-only completion predicate drifted.")
        if (
            outcome_event_value.cause.value != "outcome-produced"
            or outcome_state_value.latest_event.artifact_id != outcome_event.artifact_id
            or derived_value.terminal_state_id != outcome_state.artifact_id
        ):
            raise RuntimeError("M8 normal Outcome Event was not adopted exactly.")
        simulations = run_all_scenarios(
            plan,
            workspace,
            scheduler,
            create_planner(),
            evidence_validator=_independently_validate_simulation_evidence,
        )
        for simulation in simulations:
            _validate_simulation_result(simulation)
        if (
            tuple(item.scenario for item in simulations) != SCENARIOS
            or any(not item.offline for item in simulations)
            or any(item.real_ui_observed or item.hosted_runtime_used for item in simulations)
            or any(set(item.measurements) != _MEASUREMENT_GROUPS for item in simulations)
            or any(not item.native_artifact_ids or not item.event_ids for item in simulations)
            or any(
                not {"planner", "runtime", "status", "outcome"} <= set(item.contract_trace)
                for item in simulations
            )
            or "supersession"
            not in next(
                item.contract_trace
                for item in simulations
                if item.scenario == "candidate-supersession"
            )
        ):
            raise RuntimeError("M8 deterministic simulation contract drifted.")
        reproduced = [
            {
                "case_id": f"M8-{index:02d}",
                "scenario": item.scenario,
                "project_fixture": item.project_fixture,
                "project_fixture_root": item.project_fixture_root,
                "fixture_bundle_id": item.fixture_bundle_id,
                "observed_outcome": item.outcome,
                "observed_blockers": list(item.blockers),
                "outcome_artifact_id": item.outcome_artifact_id,
                "terminal_state_id": item.terminal_state_id,
                "current_event_head_id": item.current_event_head_id,
                "measurement_groups": sorted(item.measurements),
                "passed": True,
            }
            for index, item in enumerate(simulations, start=1)
        ]

    suite = _object(root / "evals/m8-workflow-suite.json")
    result = _object(root / "evals/results/m8-workflow-evaluation.json")
    expected = _object_array(suite.get("cases"))
    observed = _object_array(result.get("cases"))
    fixture_bundles = _object_array(suite.get("fixture_bundles"))
    measurement_contract = suite.get("measurement_contract")
    if (
        suite.get("suite_id") != "M8-WORKFLOW-INTEGRATION"
        or result.get("suite_id") != suite.get("suite_id")
        or suite.get("measurement_authority") != "native-artifacts-and-event-history"
        or result.get("measurement_authority") != suite.get("measurement_authority")
        or result.get("contract_execution") != "reproduced-by-named-validator"
        or set(_string_array(suite.get("required_contracts")))
        != {"planner", "runtime", "status", "recovery", "supersession", "outcome"}
        or len(expected) != 12
        or len(fixture_bundles) != 3
        or measurement_contract
        != {group: list(names) for group, names in _MEASUREMENT_CONTRACT.items()}
        or observed != reproduced
        or _contains_aggregate(suite)
        or _contains_aggregate(result)
    ):
        raise RuntimeError("M8 public evaluation evidence is invalid.")
    fixture_by_name = {
        str(item.get("project_fixture")): item for item in fixture_bundles
    }
    if set(fixture_by_name) != {"offline-config", "ui-issue-tracker", "secure-export"}:
        raise RuntimeError("M8 fixture bundle registry drifted.")
    for project_fixture, record in fixture_by_name.items():
        root_value = record.get("root")
        paths_value = record.get("paths")
        if not isinstance(root_value, str) or not isinstance(paths_value, list):
            raise RuntimeError("M8 fixture bundle routing is invalid.")
        bundle_id, paths = _independent_fixture_bundle(root / root_value)
        if (
            record.get("fixture_bundle_id") != bundle_id
            or paths_value != list(paths)
            or project_fixture not in root_value
        ):
            raise RuntimeError("M8 fixture bundle identity or path order drifted.")
    for expected_case, observed_case in zip(expected, observed, strict=True):
        expected_fixture = expected_case.get("project_fixture")
        fixture_record = (
            fixture_by_name.get(expected_fixture)
            if isinstance(expected_fixture, str)
            else None
        )
        if (
            fixture_record is None
            or expected_case.get("scenario") != observed_case.get("scenario")
            or expected_case.get("project_fixture") != observed_case.get("project_fixture")
            or expected_case.get("expected_outcome") != observed_case.get("observed_outcome")
            or expected_case.get("expected_blockers") != observed_case.get("observed_blockers")
            or fixture_record.get("root") != observed_case.get("project_fixture_root")
            or fixture_record.get("fixture_bundle_id")
            != observed_case.get("fixture_bundle_id")
        ):
            raise RuntimeError("M8 evaluation contradicts its expected case.")

    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    if project.get("project", {}).get("dependencies") != []:
        raise RuntimeError("M8 changed the dependency-free runtime boundary.")
    if sdaqf.__all__ != ["GateCheck", "GateResult", "ToolCapability", "ToolStatus"]:
        raise RuntimeError("M8 changed the stable top-level Python exports.")
    if validate_m5() != 0 or validate_m6() != 0 or validate_m7() != 0:
        raise RuntimeError("M8 native M5-M7 validators did not pass.")
    print("PASS: M8-WORKFLOW-INTEGRATION")
    return 0


def _validate_simulation_result(result: WorkflowSimulationResult) -> None:
    """Resolve one result's measurement, Event-lineage, and contract-trace claims."""

    if set(result.measurements) != _MEASUREMENT_GROUPS:
        raise WorkflowSimulationError("Simulation measurement groups drifted.")
    for group, names in _MEASUREMENT_CONTRACT.items():
        if set(result.measurements[group]) != set(names):
            raise WorkflowSimulationError("Simulation measurement vocabulary drifted.")
    native_ids = set(result.native_artifact_ids)
    if len(native_ids) != len(result.native_artifact_ids):
        raise WorkflowSimulationError("Simulation native artifact identity is duplicated.")
    if not result.event_ids or not set(result.event_ids) <= native_ids:
        raise WorkflowSimulationError("Simulation Event lineage is not natively resolved.")
    for group, measurements in result.measurements.items():
        if not measurements:
            raise WorkflowSimulationError(f"Simulation measurement group {group} is empty.")
        for name, payload in measurements.items():
            if set(payload) != {"status", "value", "unit", "source_ids"}:
                raise WorkflowSimulationError("Simulation measurement contract drifted.")
            status = payload["status"]
            value = payload["value"]
            unit = payload["unit"]
            source_ids = payload["source_ids"]
            if (
                not isinstance(source_ids, list)
                or not source_ids
                or not all(isinstance(item, str) for item in source_ids)
                or not set(source_ids) <= native_ids
            ):
                raise WorkflowSimulationError(
                    f"Simulation measurement source {group}.{name} is unresolved."
                )
            if status == "observed":
                if value is None or not isinstance(unit, str) or not unit:
                    raise WorkflowSimulationError("Observed simulation measurement is incomplete.")
            elif status == "not-available":
                if value is not None or unit is not None:
                    raise WorkflowSimulationError(
                        "Unavailable simulation measurement claimed an observed value."
                    )
            else:
                raise WorkflowSimulationError("Simulation measurement status is invalid.")
    required_trace = {"planner", "runtime", "status", "outcome"}
    if not required_trace <= set(result.contract_trace):
        raise WorkflowSimulationError("Simulation contract trace is incomplete.")
    if result.scenario == "crash-and-recovery" and "recovery" not in result.contract_trace:
        raise WorkflowSimulationError("Simulation contract trace omitted recovery.")
    if result.scenario == "candidate-supersession" and "supersession" not in result.contract_trace:
        raise WorkflowSimulationError("Simulation contract trace omitted supersession.")


def _independently_validate_simulation_evidence(
    result: WorkflowSimulationResult,
    evidence: WorkflowSimulationEvidence,
) -> None:
    """Reload and independently resolve all D7 values from native evidence."""

    fixture_root = _REPOSITORY_ROOT / evidence.fixture.relative_root
    fixture_id, fixture_paths = _independent_fixture_bundle(fixture_root)
    if (
        fixture_id != result.fixture_bundle_id
        or fixture_id != evidence.fixture.fixture_bundle_id
        or fixture_paths != tuple(path for path, _ in evidence.fixture.files)
    ):
        raise WorkflowSimulationError("Simulation fixture bundle did not resolve exactly.")
    plan_artifact = load_workflow_artifact(
        evidence.plan_path,
        expected_type=WorkflowArtifactType.INTEGRATED_PLAN,
    )
    _validate_fixture_causality(plan_artifact, evidence, fixture_id)
    state_artifact = load_workflow_artifact(
        evidence.terminal_state_path,
        expected_type=WorkflowArtifactType.WORKFLOW_STATE,
    )
    outcome_artifact = load_workflow_artifact(
        evidence.outcome_path,
        expected_type=WorkflowArtifactType.WORKFLOW_OUTCOME,
    )
    state = state_artifact.value
    outcome = outcome_artifact.value
    if not isinstance(state, WorkflowState) or not isinstance(outcome, WorkflowOutcome):
        raise WorkflowSimulationError("Simulation terminal artifacts have invalid types.")
    if (
        outcome_artifact.artifact_id != result.outcome_artifact_id
        or state_artifact.artifact_id != result.terminal_state_id
        or outcome.terminal_state_id != state_artifact.artifact_id
        or outcome.disposition.value != result.outcome
        or state.plan_id != plan_artifact.artifact_id
        or outcome.plan_id != plan_artifact.artifact_id
    ):
        raise WorkflowSimulationError("Simulation public result is not terminal-artifact-derived.")
    state_blockers = tuple(sorted(item.code for item in state.blockers))
    outcome_blockers = tuple(sorted(item.code for item in outcome.blockers))
    if state_blockers != result.blockers or outcome_blockers != result.blockers:
        raise WorkflowSimulationError("Simulation blocker result is not State/Outcome-derived.")
    events: list[WorkflowEvent] = []
    event_ids: list[str] = []
    for binding in state.event_chain:
        loaded = load_workflow_artifact(
            evidence.root / binding.reference.path,
            expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
        )
        if loaded.artifact_id != binding.artifact_id:
            raise WorkflowSimulationError("Simulation Event binding did not reload exactly.")
        event = loaded.value
        if not isinstance(event, WorkflowEvent):
            raise WorkflowSimulationError("Simulation Event chain has an invalid type.")
        events.append(event)
        event_ids.append(loaded.artifact_id)
    if (
        not event_ids
        or tuple(event_ids) != tuple(result.event_ids)
        or state.latest_event.artifact_id != event_ids[-1]
    ):
        raise WorkflowSimulationError("Simulation Event chain is incomplete or reordered.")
    store = SQLiteSchedulerStore(evidence.scheduler_state, evidence.root)
    store.validate()
    store.require_workflow_authority()
    epoch_events = store.export("workflow-epochs")
    epoch_head = store.workflow_head(plan_artifact.artifact_id)
    if (
        not epoch_events
        or epoch_head is None
        or epoch_head.phase.value != "terminal-confirmed"
        or epoch_head.current_event_head_id != result.current_event_head_id
    ):
        raise WorkflowSimulationError("Simulation M6 terminal epoch did not replay exactly.")
    terminal_receipts = {
        (item.artifact_type, item.artifact_id, item.path, item.status.value)
        for item in epoch_head.receipts
    }
    required_receipts = {
        (
            WorkflowArtifactType.WORKFLOW_EVENT.value,
            state.latest_event.artifact_id,
            state.latest_event.reference.path,
            "confirmed",
        ),
        (
            WorkflowArtifactType.WORKFLOW_STATE.value,
            state_artifact.artifact_id,
            evidence.terminal_state_path.relative_to(evidence.root).as_posix(),
            "confirmed",
        ),
        (
            WorkflowArtifactType.WORKFLOW_OUTCOME.value,
            outcome_artifact.artifact_id,
            evidence.outcome_path.relative_to(evidence.root).as_posix(),
            "confirmed",
        ),
    }
    if not terminal_receipts >= required_receipts:
        raise WorkflowSimulationError("Simulation terminal receipts are incomplete.")
    expected = _independent_measurements(plan_artifact, state, tuple(events), store, evidence.root)
    state_measurements = _group_measurements(state.measurements)
    outcome_measurements = _group_measurements(outcome.measurements)
    for group, names in _MEASUREMENT_CONTRACT.items():
        for name in names:
            if (
                expected[group][name] != state_measurements.get(group, {}).get(name)
                or expected[group][name] != outcome_measurements.get(group, {}).get(name)
            ):
                raise WorkflowSimulationError(
                    f"Independent D7 resolver rejected {group}.{name}: "
                    f"expected={expected[group][name]!r}; "
                    f"state={state_measurements.get(group, {}).get(name)!r}; "
                    f"outcome={outcome_measurements.get(group, {}).get(name)!r}."
                )
    if expected != result.measurements:
        raise WorkflowSimulationError("Simulation result measurements drifted from native truth.")


def _validate_fixture_causality(
    plan_artifact: LoadedWorkflowArtifact,
    evidence: WorkflowSimulationEvidence,
    fixture_id: str,
) -> None:
    """Independently prove fixture bytes feed M1/M5/M6/M3 and the Plan."""

    plan = plan_artifact.value
    if not isinstance(plan, IntegratedPlan):
        raise WorkflowSimulationError("Simulation fixture Plan has the wrong type.")
    files = dict(evidence.fixture.files)
    try:
        specification = files["specification.md"]
        expected = json.loads(files["expected-normalized.json"])
        structured = json.loads(files["structured-run.json"])
    except (KeyError, UnicodeError, ValueError) as exc:
        raise WorkflowSimulationError("Simulation fixture core bytes are invalid.") from exc
    if not isinstance(expected, dict) or not isinstance(structured, dict):
        raise WorkflowSimulationError("Simulation fixture core bytes are not objects.")
    source_sha256 = hashlib.sha256(specification).hexdigest().upper()
    fixture_digest = fixture_id.rsplit("-", 1)[-1]
    if (
        plan.project_id != evidence.fixture.project_fixture
        or plan.candidate.source_spec_sha256 != source_sha256
        or plan.candidate.repository_digest != fixture_digest
        or expected.get("source_sha256") != source_sha256
        or expected.get("baseline_id") != plan.requirement_baseline_id
        or structured.get("input_identity", {}).get("project_id") != plan.project_id
    ):
        raise WorkflowSimulationError("Simulation Plan is not fixture-byte-bound.")
    specification_bytes = (evidence.root / plan.specification.path).read_bytes()
    if specification_bytes != specification:
        raise WorkflowSimulationError("Simulation Plan specification is not the fixture bytes.")
    baseline = load_baseline(evidence.root / plan.requirement_baseline.path)
    raw_requirements = expected.get("requirements")
    if not isinstance(raw_requirements, list):
        raise WorkflowSimulationError("Simulation fixture requirements are invalid.")
    expected_requirement_ids = tuple(
        str(item.get("requirement_id")) for item in raw_requirements if isinstance(item, dict)
    )
    expected_acceptance_ids = tuple(
        str(acceptance_id)
        for item in raw_requirements
        if isinstance(item, dict)
        for acceptance_id in item.get("acceptance_ids", [])
    )
    if (
        tuple(item.requirement_id for item in baseline.requirements)
        != expected_requirement_ids
        or tuple(
            criterion.criterion_id
            for item in baseline.requirements
            for criterion in item.acceptance_criteria
        )
        != expected_acceptance_ids
    ):
        raise WorkflowSimulationError("Simulation M1 Baseline is not fixture-derived.")

    graph_loaded = load_context_artifact(
        evidence.root / plan.context_graph.reference.path,
        expected_type=ContextArtifactType.GRAPH,
    )
    selection_loaded = load_context_artifact(
        evidence.root / plan.context_selection.reference.path,
        expected_type=ContextArtifactType.SELECTION,
    )
    snapshot_loaded = load_context_artifact(
        evidence.root / plan.context_snapshot.reference.path,
        expected_type=ContextArtifactType.SNAPSHOT,
    )
    graph = graph_loaded.value
    selection = selection_loaded.value
    snapshot = snapshot_loaded.value
    if (
        not isinstance(graph, ContextGraph)
        or not isinstance(selection, ContextSelection)
        or not isinstance(snapshot, ContextSnapshot)
        or graph.candidate != plan.candidate
        or selection.candidate != plan.candidate
        or snapshot.candidate != plan.candidate
    ):
        raise WorkflowSimulationError("Simulation M5 chain is not Candidate-bound.")
    canonical = tuple(
        node for node in graph.nodes if node.authority.value == "canonical-specification"
    )
    if len(canonical) != 1:
        raise WorkflowSimulationError("Simulation M5 canonical fixture node is ambiguous.")
    m3_references = tuple(
        item
        for item in canonical[0].provenance.references
        if item.path.endswith("fixture-evidence-ledger.json")
    )
    if len(m3_references) != 1:
        raise WorkflowSimulationError("Simulation M5 chain omitted fixture M3 evidence.")
    m3_reference = m3_references[0]
    manifest_digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "fixture_bundle_id": fixture_id,
                "m3_evidence_ledger": m3_reference.to_dict(),
            }
        )
    ).hexdigest().upper()
    if graph.manifest_id != f"CTX-MANIFEST-{manifest_digest}":
        raise WorkflowSimulationError("Simulation M5 identity omitted fixture causality.")
    ledger = load_evidence_ledger(evidence.root / m3_reference.path)
    if (
        ledger.baseline_id != plan.requirement_baseline_id
        or ledger.source_spec_sha256 != source_sha256
        or ledger.git_head != plan.candidate.git_head
        or ledger.repository_digest != fixture_digest
    ):
        raise WorkflowSimulationError("Simulation M3 ledger is not fixture-bound.")
    expected_evidence = {
        (f"workflow/fixture/{path}", hashlib.sha256(content).hexdigest().upper())
        for path, content in evidence.fixture.files
        if path.startswith("evidence/")
    }
    observed_evidence = {
        (reference.path, reference.sha256)
        for record in ledger.evidence
        for reference in record.artifacts
    }
    if observed_evidence != expected_evidence:
        raise WorkflowSimulationError("Simulation M3 ledger omitted fixture evidence bytes.")
    task_graph_loaded = load_scheduler_artifact(
        evidence.root / plan.task_graph.reference.path,
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=evidence.root,
    )
    task_graph = task_graph_loaded.value
    if (
        not isinstance(task_graph, TaskGraph)
        or task_graph.candidate != plan.candidate
        or {item.artifact_id for item in task_graph.contexts}
        != {plan.context_snapshot.artifact_id}
        or any(
            task.context_snapshot_id != plan.context_snapshot.artifact_id
            for task in task_graph.tasks
        )
    ):
        raise WorkflowSimulationError("Simulation M6 graph is not fixture-M5-bound.")


def _independent_fixture_bundle(root: Path) -> tuple[str, tuple[str, ...]]:
    """Recompute the sole fixture identity without using the simulator helper."""

    if not root.is_dir() or root.is_symlink():
        raise WorkflowSimulationError("Fixture resolver requires one unlinked directory.")
    entries: list[tuple[str, bytes]] = []
    folded: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise WorkflowSimulationError("Fixture resolver rejects linked paths.")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.casefold() in folded:
            raise WorkflowSimulationError("Fixture resolver found a path case collision.")
        folded.add(relative.casefold())
        entries.append((relative, path.read_bytes()))
    entries.sort(key=lambda item: (item[0].casefold(), item[0]))
    required = {"specification.md", "expected-normalized.json", "structured-run.json"}
    if not required <= {path for path, _ in entries}:
        raise WorkflowSimulationError("Fixture resolver found a missing required file.")
    digest = hashlib.sha256(b"M8-FIXTURE-BUNDLE\0")
    for relative, body in entries:
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    return (
        f"M8-FIXTURE-BUNDLE-{digest.hexdigest().upper()}",
        tuple(path for path, _ in entries),
    )


def _independent_measurements(
    plan_artifact: LoadedWorkflowArtifact,
    state: WorkflowState,
    workflow_events: tuple[WorkflowEvent, ...],
    store: SQLiteSchedulerStore,
    root: Path,
) -> dict[str, dict[str, dict[str, object]]]:
    """Recompute the 52 measurements without producer measurement code."""

    plan = plan_artifact.value
    if not isinstance(plan, IntegratedPlan):
        raise WorkflowSimulationError("Independent resolver requires Integrated Plan.")
    graph_artifact = load_context_artifact(
        root / plan.context_graph.reference.path,
        expected_type=ContextArtifactType.GRAPH,
    )
    selection_artifact = load_context_artifact(
        root / plan.context_selection.reference.path,
        expected_type=ContextArtifactType.SELECTION,
    )
    snapshot_artifact = load_context_artifact(
        root / plan.context_snapshot.reference.path,
        expected_type=ContextArtifactType.SNAPSHOT,
    )
    context_graph = graph_artifact.value
    selection = selection_artifact.value
    snapshot = snapshot_artifact.value
    if not isinstance(context_graph, ContextGraph):
        raise WorkflowSimulationError("Independent resolver found invalid Context Graph.")
    if not isinstance(selection, ContextSelection) or not isinstance(snapshot, ContextSnapshot):
        raise WorkflowSimulationError("Independent resolver found invalid Context selection.")
    context_quality_artifact = measure_context_quality(
        graph_artifact,
        selection_artifact,
        snapshot_artifact,
    )
    context_quality = context_quality_artifact.value
    if not isinstance(context_quality, ContextQualityReport):
        raise WorkflowSimulationError("Independent resolver found invalid Context quality.")
    baseline = load_baseline(root / plan.requirement_baseline.path)
    native_artifact = _replay_scheduler_state(store, state.scheduler_event_sequence)
    native = native_artifact.value
    if not isinstance(native, SchedulerState):
        raise WorkflowSimulationError("Independent resolver found invalid M6 State.")
    if (
        native_artifact.artifact_id != state.scheduler_state_id
        or native.graph_id != state.scheduler_graph_id
        or native.event_sequence != state.scheduler_event_sequence
    ):
        raise WorkflowSimulationError("Terminal State does not match replayed M6 State.")
    scheduler_events = tuple(
        item.value
        for item in store.export("events")
        if isinstance(item.value, SchedulerEvent)
        and item.value.sequence <= native.event_sequence
    )
    budgets = tuple(
        item.value
        for item in store.export("budget")
        if isinstance(item.value, BudgetLedger)
        and item.value.event_sequence <= native.event_sequence
    )
    budget = None if not budgets else budgets[-1]
    used_budget = {} if budget is None else dict(budget.used)
    measurement_event_bindings = state.event_chain
    if workflow_events and workflow_events[-1].cause in {
        WorkflowEventCause.OUTCOME_PRODUCED,
        WorkflowEventCause.PLAN_SUPERSEDED,
    }:
        measurement_event_bindings = measurement_event_bindings[:-1]
    sources = tuple(
        sorted(
            {
                plan_artifact.artifact_id,
                native.graph_id,
                scheduler_artifact_from_value(
                    SchedulerArtifactType.SCHEDULER_STATE,
                    native,
                ).artifact_id,
                plan.requirement_baseline_id,
                plan.context_graph.artifact_id,
                plan.context_query.artifact_id,
                plan.context_selection.artifact_id,
                plan.context_snapshot.artifact_id,
                *(
                    item.artifact_id
                    for item in state.observation_artifacts
                    if item.artifact_type in _MEASUREMENT_OBSERVATION_TYPES
                ),
                *(item.artifact_id for item in measurement_event_bindings),
            }
        )
    )
    required_requirements = {
        item.subject_id
        for item in plan.decisions
        if item.subject_kind == "requirement"
        and item.kind.value == "selected"
        and item.reason_code == "required-by-requirement"
    }
    mapped_requirements = {item for task in plan.tasks for item in task.requirement_ids}
    required_context = {item.node_id for item in context_graph.nodes if item.required} | set(
        selection.query.required_node_ids
    )
    selected_required = required_context & {item.node_id for item in snapshot.nodes}
    expected_observations = _expected_observation_bindings(plan, store, root)
    reported_observations = tuple(
        item
        for item in state.observation_artifacts
        if item.artifact_type in _MEASUREMENT_OBSERVATION_TYPES
    )
    if reported_observations != expected_observations:
        raise WorkflowSimulationError(
            "Terminal State observation bindings differ from M6 accepted evidence."
        )
    observations = _independent_native_observations(expected_observations, root)
    covered = required_requirements & observations["covered_requirement_ids"]
    blocker_codes = {
        blocker.code for task in native.tasks for blocker in task.blockers
    }
    native_approval_ids = {
        item.approval_id
        for item in scheduler_events
        if item.cause == "approval-consumed" and item.approval_id is not None
    }
    active_worktree_ids = set(native.worktree_lease_ids)
    native_ambiguities = {
        "external-effect-ambiguous"
        for task in native.tasks
        if task.outcome is TaskOutcome.UNKNOWN
        or any(
            "ambiguous" in blocker.code or "unknown" in blocker.code
            for blocker in task.blockers
        )
    }
    if any(
        isinstance(item.value, WorktreeLease)
        and item.artifact_id in active_worktree_ids
        and item.value.ambiguous
        for item in store.export("worktrees")
    ):
        native_ambiguities.add("external-effect-ambiguous")
    duplicate_rejections = sum(item.cause == "duplicate-message" for item in scheduler_events)
    late_rejections = sum(
        item.cause == "message-rejected"
        and item.reason is not None
        and ("late" in item.reason or "lease-expiry" in item.reason)
        for item in scheduler_events
    )
    approval_expired = sum(
        item.cause == "approval-proposal-expired" for item in scheduler_events
    )
    approval_refused = sum(
        item.cause == "message-rejected"
        and item.reason is not None
        and item.reason.startswith("approval-")
        and "time-window" not in item.reason
        for item in scheduler_events
    )
    approval_failures = sum(
        item.cause in {"dispatch-approval-blocked", "approval-proposal-expired"}
        or (
            item.cause == "message-rejected"
            and item.reason is not None
            and item.reason.startswith("approval-")
        )
        for item in scheduler_events
    )
    measurements: dict[str, dict[str, dict[str, object]]] = {
        group: {} for group in _MEASUREMENT_CONTRACT
    }

    def observed(group: str, name: str, value: int | str, unit: str) -> None:
        measurements[group][name] = {
            "status": "observed",
            "value": value,
            "unit": unit,
            "source_ids": list(sources),
        }

    def unavailable(group: str, name: str) -> None:
        measurements[group][name] = {
            "status": "not-available",
            "value": None,
            "unit": None,
            "source_ids": list(sources),
        }

    observed("requirements", "required_requirement_count", len(required_requirements), "count")
    if observations["requirement_coverage_available"]:
        observed("requirements", "covered_requirement_count", len(covered), "count")
        observed(
            "requirements",
            "uncovered_requirement_ids",
            ",".join(sorted(required_requirements - covered)) or "none",
            "identifier-list",
        )
    else:
        unavailable("requirements", "covered_requirement_count")
        unavailable("requirements", "uncovered_requirement_ids")
    observed(
        "requirements",
        "scope_addition_count",
        len(mapped_requirements - required_requirements),
        "count",
    )
    observed(
        "requirements",
        "blocking_diagnostic_count",
        sum(item.status == "open" for item in baseline.diagnostics),
        "count",
    )
    observed("context", "required_reference_count", len(required_context), "count")
    observed(
        "context",
        "selected_required_reference_count",
        len(selected_required),
        "count",
    )
    for name, value, unit in (
        ("stale_required_count", context_quality.stale_required_count, "count"),
        ("provenance_missing_count", context_quality.provenance_missing_count, "count"),
        ("sensitivity_violation_count", context_quality.sensitivity_violation_count, "count"),
        ("selected_context_bytes", context_quality.selected_context_bytes, "canonical-utf8-bytes"),
        ("context_budget_bytes", context_quality.budget_bytes, "canonical-utf8-bytes"),
        (
            "unresolved_contradiction_count",
            context_quality.unresolved_contradiction_count,
            "count",
        ),
    ):
        observed("context", name, value, unit)
    observed("scheduling", "task_count", len(native.tasks), "count")
    observed(
        "scheduling",
        "completed_task_count",
        sum(item.state is TaskState.COMPLETED for item in native.tasks),
        "count",
    )
    observed(
        "scheduling",
        "blocked_task_count",
        sum(item.state is TaskState.BLOCKED for item in native.tasks),
        "count",
    )
    observed("scheduling", "retry_used_count", int(used_budget.get("retries", 0)), "count")
    observed("scheduling", "duplicate_rejection_count", duplicate_rejections, "count")
    observed("scheduling", "late_result_rejection_count", late_rejections, "count")
    observed(
        "scheduling",
        "deadlock_count",
        sum("deadlock" in code for code in blocker_codes),
        "count",
    )
    solver_counts = observations["solver_status_counts"]
    observed("solver", "solver_task_count", len(plan.solver_requests), "count")
    observed(
        "solver",
        "status_counts",
        ";".join(f"{name}:{solver_counts[name]}" for name in sorted(solver_counts)) or "none",
        "status-counts",
    )
    observed("solver", "verified_result_count", solver_counts.get("verified", 0), "count")
    observed(
        "solver",
        "adoptable_result_count",
        observations["adoptable_result_count"],
        "count",
    )
    observed("solver", "solver_calls_used", int(used_budget.get("solver_calls", 0)), "count")
    observed("solver", "solver_steps_used", int(used_budget.get("solver_steps", 0)), "count")
    for group, names in (
        (
            "evidence",
            (
                "claim_count",
                "verified_claim_count",
                "unverified_claim_count",
                "known_problem_count",
                "missing_evidence_count",
            ),
        ),
        (
            "handoff",
            (
                "handoff_created_count",
                "handoff_resume_failure_count",
                "incomplete_item_count",
                "open_decision_count",
                "known_problem_count",
            ),
        ),
    ):
        if observations[f"{group}_available"]:
            for name in names:
                observed(group, name, observations[f"{group}_{name}"], "count")
        else:
            for name in names:
                unavailable(group, name)
    unavailable("recovery", "resume_attempt_count")
    observed(
        "recovery",
        "successful_resume_count",
        sum(
            item.cause
            not in {
                WorkflowEventCause.RUNTIME_STARTED,
                WorkflowEventCause.RECOVERY_OBSERVED,
                WorkflowEventCause.PLAN_SUPERSEDED,
                WorkflowEventCause.OUTCOME_PRODUCED,
            }
            for item in workflow_events
        ),
        "count",
    )
    unavailable("recovery", "recovery_attempt_count")
    observed(
        "recovery",
        "successful_recovery_count",
        sum(item.cause is WorkflowEventCause.RECOVERY_OBSERVED for item in workflow_events),
        "count",
    )
    observed("recovery", "ambiguous_effect_count", len(native_ambiguities), "count")
    observed(
        "approval",
        "required_approval_count",
        sum(len(item.approval_types) for item in plan.protected_effects),
        "count",
    )
    observed("approval", "consumed_approval_count", len(native_approval_ids), "count")
    observed("approval", "refused_approval_count", approval_refused, "count")
    observed("approval", "expired_approval_count", approval_expired, "count")
    observed(
        "approval",
        "pending_approval_count",
        sum(
            any(blocker.code == "approval-required" for blocker in item.blockers)
            for item in native.tasks
        ),
        "count",
    )
    observed(
        "approval",
        "approval_revalidation_failure_count",
        approval_failures,
        "count",
    )
    observed(
        "available_cost",
        "status",
        plan.budget.cost_status,
        "availability-status",
    )
    if plan.budget.cost_status == "available":
        assert plan.budget.currency is not None
        assert plan.budget.max_microunits is not None
        used = int(used_budget.get("microunits", 0))
        observed("available_cost", "currency", plan.budget.currency, "iso-4217")
        observed(
            "available_cost",
            "budget_microunits",
            plan.budget.max_microunits,
            "microunits",
        )
        observed("available_cost", "used_microunits", used, "microunits")
        observed(
            "available_cost",
            "remaining_microunits",
            max(0, plan.budget.max_microunits - used),
            "microunits",
        )
    else:
        for name in (
            "currency",
            "budget_microunits",
            "used_microunits",
            "remaining_microunits",
        ):
            unavailable("available_cost", name)
    if {
        f"{group}.{name}" for group, names in _MEASUREMENT_CONTRACT.items() for name in names
    } != {
        f"{group}.{name}" for group, names in measurements.items() for name in names
    }:
        raise WorkflowSimulationError("Independent resolver did not produce exact D7 names.")
    return {group: dict(sorted(values.items())) for group, values in sorted(measurements.items())}


def _expected_observation_bindings(
    plan: IntegratedPlan,
    store: SQLiteSchedulerStore,
    root: Path,
) -> tuple[NativeArtifactBinding, ...]:
    """Derive the sole expected M3/M7 binding set from immutable M6 history."""

    if plan.completion_profile is CompletionProfile.PLAN_ONLY:
        return ()
    graph_loaded = load_scheduler_artifact(
        root / plan.task_graph.reference.path,
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    graph = graph_loaded.value
    if not isinstance(graph, TaskGraph):
        raise WorkflowSimulationError("Independent resolver found invalid Task Graph.")
    completed_result_ids = {
        event.result_id
        for artifact in store.export("events")
        if isinstance((event := artifact.value), SchedulerEvent)
        and event.cause == "verification-completed"
        and event.result_id is not None
    }
    messages = {
        artifact.artifact_id: artifact.value
        for artifact in store.export("messages")
        if artifact.artifact_id in completed_result_ids
        and isinstance(artifact.value, MailboxMessage)
        and artifact.value.message_type is MessageType.TASK_RESULT
    }
    task_by_id = {item.task_id: item for item in graph.tasks}
    bindings: dict[str, NativeArtifactBinding] = {}
    for message_id in sorted(messages):
        message = messages[message_id]
        task = task_by_id.get(message.task_id or "")
        if task is None:
            raise WorkflowSimulationError("Accepted result lacks a Task Graph task.")
        payload = message.to_dict()["payload"]
        if not isinstance(payload, dict) or not isinstance(payload.get("evidence_refs"), list):
            raise WorkflowSimulationError("Accepted result evidence references are invalid.")
        for index, raw in enumerate(payload["evidence_refs"]):
            reference = parse_artifact_reference(raw, f"evidence_refs[{index}]")
            path = root / reference.path
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest().upper() != reference.sha256:
                raise WorkflowSimulationError("Accepted result evidence digest drifted.")
            if task.kind is TaskKind.SOLVER:
                loaded = load_solver_artifact(
                    path,
                    expected_type=SolverArtifactType.VERIFICATION,
                )
                identifier = loaded.artifact_id
                artifact_type = SolverArtifactType.VERIFICATION.value
            elif task.kind is TaskKind.REVIEW:
                review = load_independent_review(path)
                identifier = review.review_id
                artifact_type = "independent-review"
            elif task.kind is TaskKind.HANDOFF:
                load_automated_handoff(path)
                identifier = f"M3-HANDOFF-{reference.sha256}"
                artifact_type = "automated-handoff"
            elif task.kind is TaskKind.INTEGRATION:
                record = load_json_object(
                    path,
                    "M8 integration observation",
                    maximum_bytes=16 * 1024 * 1024,
                )
                keys = set(record)
                if "install_evidence_id" in keys:
                    load_release_candidate(path)
                    identifier = f"M3-RELEASE-CANDIDATE-{reference.sha256}"
                    artifact_type = "release-candidate"
                elif {"ui_present", "observations"} <= keys:
                    load_ui_validation(path)
                    identifier = f"M3-UI-VALIDATION-{reference.sha256}"
                    artifact_type = "ui-validation"
                elif {"source_spec", "platforms", "ui"} <= keys:
                    load_manifest_ui(path)
                    identifier = f"M3-PROJECT-MANIFEST-{reference.sha256}"
                    artifact_type = "project-manifest"
                else:
                    raise WorkflowSimulationError(
                        "Accepted integration observation is unsupported."
                    )
            else:
                load_evidence_ledger(path)
                identifier = f"M3-EVIDENCE-LEDGER-{reference.sha256}"
                artifact_type = "evidence-ledger"
            if identifier in bindings:
                raise WorkflowSimulationError("Accepted M3/M7 evidence is duplicated.")
            bindings[identifier] = NativeArtifactBinding(
                artifact_type,
                identifier,
                reference,
                True,
            )
    return tuple(sorted(bindings.values(), key=lambda item: item.artifact_id))


def _independent_native_observations(
    observation_artifacts: tuple[NativeArtifactBinding, ...],
    root: Path,
) -> dict[str, Any]:
    """Reload M7 and M3 evidence without trusting State measurement values."""

    result: dict[str, Any] = {
        "solver_status_counts": {},
        "adoptable_result_count": 0,
        "evidence_available": False,
        "evidence_claim_count": 0,
        "evidence_verified_claim_count": 0,
        "evidence_unverified_claim_count": 0,
        "evidence_known_problem_count": 0,
        "evidence_missing_evidence_count": 0,
        "handoff_available": False,
        "handoff_handoff_created_count": 0,
        "handoff_handoff_resume_failure_count": 0,
        "handoff_incomplete_item_count": 0,
        "handoff_open_decision_count": 0,
        "handoff_known_problem_count": 0,
        "covered_requirement_ids": set(),
        "requirement_coverage_available": False,
    }
    for binding in observation_artifacts:
        path = root / binding.reference.path
        if binding.artifact_type == SolverArtifactType.VERIFICATION.value:
            loaded = load_solver_artifact(path, expected_type=SolverArtifactType.VERIFICATION)
            verification = loaded.value
            if not isinstance(verification, SolverVerification):
                raise WorkflowSimulationError("Independent resolver found invalid M7 evidence.")
            counts = result["solver_status_counts"]
            assert isinstance(counts, dict)
            counts[verification.outcome.value] = counts.get(verification.outcome.value, 0) + 1
            result["adoptable_result_count"] = int(result["adoptable_result_count"]) + int(
                verification.adoption_allowed
            )
        elif binding.artifact_type == "evidence-ledger":
            ledger = load_evidence_ledger(path)
            result["evidence_available"] = True
            result["requirement_coverage_available"] = True
            result["evidence_claim_count"] = int(result["evidence_claim_count"]) + len(
                ledger.claims
            )
            passing = {
                claim_id
                for item in ledger.evidence
                if item.status.value == "PASS"
                for claim_id in item.claim_ids
            }
            covered = result["covered_requirement_ids"]
            assert isinstance(covered, set)
            for claim in ledger.claims:
                state_name = claim.state.value
                result["evidence_verified_claim_count"] = int(
                    result["evidence_verified_claim_count"]
                ) + int(state_name == "verified")
                result["evidence_unverified_claim_count"] = int(
                    result["evidence_unverified_claim_count"]
                ) + int(state_name in {"implemented", "unverified"})
                result["evidence_known_problem_count"] = int(
                    result["evidence_known_problem_count"]
                ) + int(state_name == "known_problem")
                result["evidence_missing_evidence_count"] = int(
                    result["evidence_missing_evidence_count"]
                ) + int(claim.claim_id not in passing)
                if claim.claim_id in passing and state_name == "verified":
                    covered.update(getattr(claim, "requirement_ids", ()))
        elif binding.artifact_type == "automated-handoff":
            handoff = load_automated_handoff(path)
            result["handoff_available"] = True
            result["handoff_handoff_created_count"] = 1
            result["handoff_handoff_resume_failure_count"] = int(
                handoff.status.value != "completed"
            )
            result["handoff_incomplete_item_count"] = len(handoff.incomplete)
            result["handoff_open_decision_count"] = len(handoff.open_decisions)
            result["handoff_known_problem_count"] = len(handoff.known_problems)
        elif binding.artifact_type == "independent-review":
            load_independent_review(path)
        else:
            if not path.is_file() or path.is_symlink():
                raise WorkflowSimulationError("Independent resolver found missing M3 evidence.")
            path.read_bytes()
    return result


def _group_measurements(
    measurements: tuple[WorkflowMeasurement, ...],
) -> dict[str, dict[str, dict[str, object]]]:
    expected_names = tuple(
        f"{group}.{name}"
        for group, names in _MEASUREMENT_CONTRACT.items()
        for name in names
    )
    if tuple(item.name for item in measurements) != expected_names:
        raise WorkflowSimulationError(
            "Terminal artifact measurements are not the exact canonical D7 sequence."
        )
    grouped: dict[str, dict[str, dict[str, object]]] = {}
    for measurement in measurements:
        payload = measurement.to_dict()
        name_value = payload.pop("name")
        if not isinstance(name_value, str):
            raise WorkflowSimulationError("Terminal artifact measurement name is invalid.")
        name = name_value
        group, separator, local_name = name.partition(".")
        if not separator:
            raise WorkflowSimulationError("Terminal artifact has an ungrouped measurement.")
        grouped.setdefault(group, {})[local_name] = payload
    return {group: dict(sorted(values.items())) for group, values in sorted(grouped.items())}


def _negative_contract_parity(root: Path, validator: LocalSchemaValidator) -> None:
    intent_path = root / "examples/m8-workflow/development-intent.json"
    payloads: list[tuple[str, dict[str, object]]] = []

    extra_field = _object(intent_path)
    extra_content = _content_object(extra_field, "Intent")
    extra_content["approval"] = True
    payloads.append(("development-intent.schema.json", extra_field))

    optional_binding = _object(intent_path)
    optional_content = _content_object(optional_binding, "Intent")
    context_graph = optional_content.get("context_graph")
    if not isinstance(context_graph, dict):
        raise RuntimeError("M8 public Intent context binding is invalid.")
    context_graph["required"] = False
    payloads.append(("development-intent.schema.json", optional_binding))

    invalid_path = _object(intent_path)
    invalid_path_content = _content_object(invalid_path, "Intent")
    specification = invalid_path_content.get("specification")
    if not isinstance(specification, dict):
        raise RuntimeError("M8 public Intent specification is invalid.")
    specification["path"] = "CON/file.json"
    payloads.append(("development-intent.schema.json", invalid_path))

    invalid_date = _object(root / "examples/m8-workflow/workflow-event.json")
    event_content = _content_object(invalid_date, "Event")
    event_content["recorded_at"] = "2026-02-30T00:00:00Z"
    payloads.append(("workflow-event.schema.json", invalid_date))

    for schema_name, payload in payloads:
        _assert_negative_contract_parity(validator, schema_name, payload)


def _assert_negative_contract_parity(
    validator: LocalSchemaValidator,
    schema_name: str,
    payload: dict[str, object],
) -> None:
    schema_rejected = False
    runtime_rejected = False
    try:
        validator.validate(schema_name, payload)
    except SchemaValidationError:
        schema_rejected = True
    try:
        parse_workflow_artifact_bytes(json.dumps(payload).encode("utf-8"))
    except WorkflowContractError:
        runtime_rejected = True
    if not schema_rejected or not runtime_rejected:
        raise RuntimeError("M8 schema/runtime negative contract parity drifted.")


def _content_object(payload: dict[str, object], name: str) -> dict[str, object]:
    content = payload.get("content")
    if not isinstance(content, dict):
        raise RuntimeError(f"M8 public {name} content is invalid.")
    return content


def _object(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must be an object.")
    return value


def _object_array(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError("M8 evaluation cases must be object arrays.")
    return value


def _string_array(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError("M8 evaluation contract list must contain strings.")
    return value


def _contains_aggregate(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key == "aggregate_score" or _contains_aggregate(item) for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_aggregate(item) for item in value)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
