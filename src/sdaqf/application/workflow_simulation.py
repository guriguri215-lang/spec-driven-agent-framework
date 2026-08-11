"""Deterministic offline M8 simulations over the real M6 SQLite state machine."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sdaqf.adapters.context import CanonicalUTF8ByteEstimator, LocalContextSourceReader
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.adapters.workflow import ExclusiveWorkflowArtifactStore
from sdaqf.application.context_contracts import (
    artifact_from_value as context_artifact_from_value,
)
from sdaqf.application.context_contracts import (
    canonical_json_bytes,
    edge_identity,
    load_context_artifact,
    node_identity,
    serialize_context_artifact,
    source_identity,
)
from sdaqf.application.context_selection import ContextSelector, ContextSnapshotService
from sdaqf.application.evidence import parse_evidence_ledger
from sdaqf.application.scheduler import SchedulerService, deterministic_wait_report
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    load_scheduler_artifact,
    serialize_scheduler_artifact,
)
from sdaqf.application.scheduler_contracts import (
    artifact_from_value as scheduler_artifact_from_value,
)
from sdaqf.application.scheduler_simulation import (
    FixedSchedulerClock,
    SchedulerSimulationResult,
    SchedulerSimulationService,
    _scenario_graph,
)
from sdaqf.application.solver_contracts import (
    artifact_from_value as solver_artifact_from_value,
)
from sdaqf.application.solver_contracts import (
    operational_contract_id,
    parse_solver_artifact_bytes,
    serialize_solver_artifact,
    solver_capability_token,
)
from sdaqf.application.workflow_contracts import (
    LoadedWorkflowArtifact,
    WorkflowContractError,
    artifact_from_value,
    load_workflow_artifact,
    parse_workflow_artifact_bytes,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_explanation import WorkflowExplainer
from sdaqf.application.workflow_outcome import WorkflowOutcomeService
from sdaqf.application.workflow_planning import IntegratedPlanner, artifact_reference_for
from sdaqf.application.workflow_recovery import WorkflowRecoveryService
from sdaqf.application.workflow_runtime import WorkflowRuntimeService
from sdaqf.domain.context import (
    AuthorityClass,
    ContextArtifactType,
    ContextGraph,
    ContextQuery,
    ContextSelection,
    ContextSnapshot,
)
from sdaqf.domain.quality import (
    ArtifactReference,
    CandidateIdentity,
    Claim,
    ClaimCriticality,
    ClaimState,
    Confidence,
    EvidenceLedger,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceType,
    GitObservation,
)
from sdaqf.domain.scheduler import (
    EffectKind,
    Lease,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerEvent,
    SchedulerState,
    TaskGraph,
    TaskKind,
)
from sdaqf.domain.solver import SolverArtifactType, SolverRegistry, SolverRequest
from sdaqf.domain.workflow import (
    WORKFLOW_MEASUREMENT_NAMES,
    CompletionProfile,
    DevelopmentIntent,
    IntegratedPlan,
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowMeasurement,
    WorkflowOutcome,
    WorkflowPublicationObservation,
    WorkflowState,
    WorkflowTerminalObservation,
    WorkflowTerminalObservationCause,
)

SCENARIOS = (
    "non-ui-success",
    "ui-observation-unavailable",
    "approval-required",
    "approval-refused",
    "approval-expired",
    "stale-candidate",
    "stale-context",
    "lease-lost",
    "solver-inconclusive",
    "ambiguous-external-effect",
    "crash-and-recovery",
    "candidate-supersession",
)

_FIXTURE_PROJECTS = {
    "offline-config": (
        "M8-FIXTURE-BUNDLE-"
        "752AB4DFD99FAA017941C1971DB255BD2F1204B76CF06A302C03551D1DAD0A80"
    ),
    "ui-issue-tracker": (
        "M8-FIXTURE-BUNDLE-"
        "56E7495AB88356529E665C4D9D5AB04A1046465F2BDB91FA645D1C052C0F9C8A"
    ),
    "secure-export": (
        "M8-FIXTURE-BUNDLE-"
        "08D7CB3B00E438F77DD298F5186717F93DAB9356326FEA7F6A2002EAF3DDDA16"
    ),
}
_FIXTURE_REQUIRED_PATHS = {
    "specification.md",
    "expected-normalized.json",
    "structured-run.json",
}
_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "evals" / "projects"


class WorkflowSimulationError(WorkflowContractError):
    """A named M8 scenario cannot be reproduced offline."""


@dataclass(frozen=True, slots=True)
class WorkflowFixtureBundle:
    """One complete exact-byte project fixture with one canonical identity."""

    project_fixture: str
    relative_root: str
    fixture_bundle_id: str
    files: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True, slots=True)
class WorkflowSimulationEvidence:
    """Explicit native paths available while an independent resolver runs."""

    root: Path
    plan_path: Path
    scheduler_state: Path
    terminal_state_path: Path
    outcome_path: Path
    fixture: WorkflowFixtureBundle


@dataclass(frozen=True, slots=True)
class WorkflowSimulationResult:
    """One named non-aggregate deterministic simulation result."""

    scenario: str
    project_fixture: str
    project_fixture_root: str
    fixture_bundle_id: str
    outcome: str
    blockers: tuple[str, ...]
    outcome_artifact_id: str
    terminal_state_id: str
    current_event_head_id: str
    measurements: dict[str, dict[str, dict[str, object]]]
    native_artifact_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    contract_trace: tuple[str, ...]
    offline: bool
    real_ui_observed: bool
    hosted_runtime_used: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "project_fixture": self.project_fixture,
            "project_fixture_root": self.project_fixture_root,
            "fixture_bundle_id": self.fixture_bundle_id,
            "outcome": self.outcome,
            "blockers": list(self.blockers),
            "outcome_artifact_id": self.outcome_artifact_id,
            "terminal_state_id": self.terminal_state_id,
            "current_event_head_id": self.current_event_head_id,
            "measurements": self.measurements,
            "native_artifact_ids": list(self.native_artifact_ids),
            "event_ids": list(self.event_ids),
            "contract_trace": list(self.contract_trace),
            "offline": self.offline,
            "real_ui_observed": self.real_ui_observed,
            "hosted_runtime_used": self.hosted_runtime_used,
        }


class WorkflowSimulationService:
    """Exercise exact M8 failure and success contracts without a host adapter."""

    def __init__(self, planner: IntegratedPlanner) -> None:
        self._planner = planner

    def run(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        scenario: str,
        *,
        predecessor_scheduler_state: Path | None = None,
        evidence_validator: Callable[
            [WorkflowSimulationResult, WorkflowSimulationEvidence], None
        ]
        | None = None,
    ) -> WorkflowSimulationResult:
        """Run one scenario using fixed M6 time and a fresh real SQLite database."""

        if scenario not in SCENARIOS:
            raise WorkflowSimulationError("Workflow simulation scenario is unsupported.")
        if plan_artifact.artifact_type is not WorkflowArtifactType.INTEGRATED_PLAN:
            raise WorkflowSimulationError("Workflow simulation requires Integrated Plan.")
        plan = plan_artifact.value
        assert isinstance(plan, IntegratedPlan)
        _authenticate_plan(plan_artifact, root, scheduler_state)
        WorkflowExplainer(self._planner).explain(
            plan_artifact,
            root,
            scheduler_state,
            predecessor_scheduler_state=predecessor_scheduler_state,
        )
        fixture = _load_fixture_bundle(_fixture(scenario))
        runtime_parent = root / "workflow"
        runtime_parent.mkdir(exist_ok=True)
        with _deterministic_private_directory(runtime_parent, scenario) as private:
            scenario_root = _prepare_fixture_workspace(root, private, fixture, plan)
            scenario_private = scenario_root / "workflow" / "simulation"
            scenario_private.mkdir()
            scheduler_path = scenario_private / "scheduler.sqlite3"
            scheduler_clock = FixedSchedulerClock()
            (
                scenario_plan,
                scenario_plan_path,
                graph_artifact,
                graph,
                store,
            ) = self._scenario_plan(
                plan_artifact,
                scenario_root,
                scenario,
                scenario_private,
                scheduler_path,
                scheduler_clock,
                fixture,
            )
            if scenario.startswith("approval-"):
                scheduler = _execute_approval_probe(
                    store,
                    graph,
                    scenario_root,
                    scenario,
                    scheduler_clock.now(),
                )
            else:
                if scenario == "solver-inconclusive":
                    _advertise_solver_capability(
                        store,
                        scenario_root,
                        graph_artifact,
                        graph,
                        scheduler_clock.now(),
                    )
                scheduler = _execute_fixture_scheduler(
                    store,
                    scenario_root,
                    graph,
                    _scheduler_scenario(scenario),
                    scheduler_clock,
                    artifact_reference_for(
                        scenario_root,
                        scenario_private / "fixture-evidence-ledger.json",
                    ),
                )
            self._observe(
                scenario,
                scheduler,
                scenario_plan,
                scenario_root,
                scheduler_path,
            )
            (
                native_artifact_ids,
                event_ids,
                contract_trace,
                native_measurements,
                outcome,
                blockers,
                outcome_artifact_id,
                terminal_state_id,
                current_event_head_id,
                terminal_state_path,
                outcome_path,
            ) = self._exercise_contracts(
                scenario_plan,
                scenario_root,
                scenario,
                scenario_private,
                scheduler_path,
                scheduler,
            )
            if scheduler.state_id not in native_artifact_ids:
                raise WorkflowSimulationError(
                    "Scenario probe and M8 contracts did not use the same native execution."
                )
            result = WorkflowSimulationResult(
                scenario=scenario,
                project_fixture=fixture.project_fixture,
                project_fixture_root=fixture.relative_root,
                fixture_bundle_id=fixture.fixture_bundle_id,
                outcome=outcome,
                blockers=blockers,
                outcome_artifact_id=outcome_artifact_id,
                terminal_state_id=terminal_state_id,
                current_event_head_id=current_event_head_id,
                measurements=native_measurements,
                native_artifact_ids=native_artifact_ids,
                event_ids=event_ids,
                contract_trace=contract_trace,
                offline=True,
                real_ui_observed=False,
                hosted_runtime_used=False,
            )
            if evidence_validator is not None:
                evidence_validator(
                    result,
                    WorkflowSimulationEvidence(
                        root=scenario_root,
                        plan_path=scenario_plan_path,
                        scheduler_state=scheduler_path,
                        terminal_state_path=terminal_state_path,
                        outcome_path=outcome_path,
                        fixture=fixture,
                    ),
                )
            return result

    def _scenario_plan(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scenario: str,
        private: Path,
        scheduler_path: Path,
        scheduler_clock: FixedSchedulerClock,
        fixture: WorkflowFixtureBundle,
    ) -> tuple[
        LoadedWorkflowArtifact,
        Path,
        LoadedSchedulerArtifact,
        TaskGraph,
        SQLiteSchedulerStore,
    ]:
        """Derive a real scenario Plan from the exact scenario Task Graph."""

        plan = plan_artifact.value
        assert isinstance(plan, IntegratedPlan)
        graph_loaded = load_scheduler_artifact(
            root / plan.task_graph.reference.path,
            expected_type=SchedulerArtifactType.TASK_GRAPH,
            root=root,
        )
        base_graph = graph_loaded.value
        assert isinstance(base_graph, TaskGraph)
        (
            candidate,
            baseline_id,
            specification,
            requirement_baseline,
            requirement_ids,
            acceptance_ids,
            context_graph,
            context_query,
            context_selection,
            context_snapshot,
        ) = _fixture_native_inputs(root, private, plan, fixture)
        base_graph = _fixture_task_graph(
            base_graph,
            candidate,
            context_snapshot,
        )
        solver_registry_binding: NativeArtifactBinding | None = None
        solver_request_template: SolverRequest | None = None
        if scenario.startswith("approval-"):
            first = replace(
                base_graph.tasks[0],
                effect_kind=EffectKind.EXTERNAL,
                approval_stops=("owner",),
            )
            graph = replace(base_graph, tasks=(first,))
        elif scenario == "solver-inconclusive":
            (
                solver_registry_binding,
                solver_request_template,
                solver_token,
            ) = _prepare_solver_scenario_contract(root, private, base_graph)
            graph = _solver_scenario_graph(base_graph, solver_token)
        else:
            graph = _scenario_graph(base_graph, _scheduler_scenario(scenario))
        graph_artifact = scheduler_artifact_from_value(
            SchedulerArtifactType.TASK_GRAPH,
            graph,
        )
        graph_path = private / "scenario-task-graph.json"
        ExclusiveWorkflowArtifactStore(root).publish(
            graph_path,
            serialize_scheduler_artifact(graph_artifact),
        )
        solver_request_binding: NativeArtifactBinding | None = None
        if solver_request_template is not None:
            request = solver_artifact_from_value(
                SolverArtifactType.REQUEST,
                replace(
                    solver_request_template,
                    task_graph=artifact_reference_for(root, graph_path),
                    graph_id=graph_artifact.artifact_id,
                ),
            )
            request_path = private / "solver-request.json"
            ExclusiveWorkflowArtifactStore(root).publish(
                request_path,
                serialize_solver_artifact(request),
            )
            solver_request_binding = NativeArtifactBinding(
                SolverArtifactType.REQUEST.value,
                request.artifact_id,
                artifact_reference_for(root, request_path),
                True,
            )
        store = SQLiteSchedulerStore.initialize(
            scheduler_path,
            root,
            graph_artifact,
            scheduler_clock.now(),
            workflow_authority=True,
        )

        intent_artifact = parse_workflow_artifact_bytes(
            (root / plan.intent.reference.path).read_bytes(),
            expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
        )
        intent = intent_artifact.value
        assert isinstance(intent, DevelopmentIntent)
        snapshot_loaded = load_context_artifact(
            root / context_snapshot.reference.path,
            expected_type=ContextArtifactType.SNAPSHOT,
        )
        snapshot_value = snapshot_loaded.value
        assert isinstance(snapshot_value, ContextSnapshot)
        fixture_context_node_ids = tuple(
            item.node_id for item in snapshot_value.nodes
        )
        source_links = {item.task_id: item for item in intent.task_links}
        template = intent.task_links[0]
        links = tuple(
            replace(
                source_links.get(task.task_id, template),
                task_id=task.task_id,
                requirement_ids=requirement_ids,
                acceptance_ids=acceptance_ids,
                context_node_ids=fixture_context_node_ids,
                solver_request_ids=(
                    (solver_request_binding.artifact_id,)
                    if task.kind is TaskKind.SOLVER
                    and solver_request_binding is not None
                    else ()
                ),
            )
            for task in sorted(graph.tasks, key=lambda item: item.task_id)
        )
        scenario_intent = artifact_from_value(
            WorkflowArtifactType.DEVELOPMENT_INTENT,
            replace(
                intent,
                project_id=fixture.project_fixture,
                candidate=candidate,
                objective=(
                    f"Execute the exact offline {fixture.project_fixture} fixture bundle."
                ),
                specification=specification,
                requirement_baseline_id=baseline_id,
                requirement_baseline=requirement_baseline,
                required_requirement_ids=requirement_ids,
                required_acceptance_ids=acceptance_ids,
                context_graph=context_graph,
                context_query=context_query,
                context_selection=context_selection,
                context_snapshot=context_snapshot,
                budget=graph.budget,
                completion_profile=(
                    CompletionProfile.RELEASE_CANDIDATE_READY
                    if scenario == "ui-observation-unavailable"
                    else intent.completion_profile
                ),
                required_gate_ids=(
                    ("G1", "G2", "G3", "G4")
                    if scenario == "ui-observation-unavailable"
                    else intent.required_gate_ids
                ),
                ui_required=(
                    True if scenario == "ui-observation-unavailable" else intent.ui_required
                ),
                requested_effects=tuple(
                    sorted({task.effect_kind for task in graph.tasks}, key=lambda item: item.value)
                ),
                capabilities=tuple(
                    sorted(
                        {
                            capability
                            for task in graph.tasks
                            for capability in task.required_capabilities
                            if not capability.startswith("m7-solver-v1@")
                        }
                    )
                ),
                allowed_paths=tuple(
                    sorted(
                        {
                            *intent.allowed_paths,
                            *(path for task in graph.tasks for path in task.owned_paths),
                        },
                        key=lambda item: (item.casefold(), item),
                    )
                ),
                task_graph=NativeArtifactBinding(
                    SchedulerArtifactType.TASK_GRAPH.value,
                    graph_artifact.artifact_id,
                    artifact_reference_for(root, graph_path),
                    True,
                ),
                solver_registry=(
                    solver_registry_binding
                    if solver_registry_binding is not None
                    else intent.solver_registry
                ),
                solver_requests=(
                    (solver_request_binding,)
                    if solver_request_binding is not None
                    else intent.solver_requests
                ),
                task_links=links,
                predecessor_plan_id=None,
                predecessor_state_id=None,
                predecessor_outcome_id=None,
                predecessor_plan=None,
                predecessor_state=None,
                predecessor_outcome=None,
            ),
        )
        intent_path = private / "scenario-intent.json"
        ExclusiveWorkflowArtifactStore(root).publish(
            intent_path,
            serialize_workflow_artifact(scenario_intent),
        )
        scenario_plan = self._planner.plan(
            scenario_intent,
            artifact_reference_for(root, intent_path),
            root,
            scheduler_path,
        )
        plan_path = private / "scenario-plan.json"
        ExclusiveWorkflowArtifactStore(root).publish(
            plan_path,
            serialize_workflow_artifact(scenario_plan),
        )
        native_artifact = store.status()
        native = native_artifact.value
        assert isinstance(native, SchedulerState)
        idempotency_key = _plan_idempotency_key(
            scenario_plan.artifact_id,
            scenario_intent.artifact_id,
        )
        head = store.open_workflow_epoch(
            plan_id=scenario_plan.artifact_id,
            candidate=graph.candidate,
            graph_id=graph_artifact.artifact_id,
            scheduler_state_id=native_artifact.artifact_id,
            scheduler_event_sequence=native.event_sequence,
            scheduler_event_head_id=store.current_event_head_id,
            idempotency_key=idempotency_key,
            producer="workflow-plan",
            artifact_id=scenario_plan.artifact_id,
            artifact_type=WorkflowArtifactType.INTEGRATED_PLAN.value,
            path=artifact_reference_for(root, plan_path).path,
            recorded_at=scheduler_clock.now(),
        )
        store.confirm_workflow_artifact(
            plan_id=scenario_plan.artifact_id,
            expected_head_id=head.current_event_head_id,
            artifact_id=scenario_plan.artifact_id,
            artifact_type=WorkflowArtifactType.INTEGRATED_PLAN.value,
            path=artifact_reference_for(root, plan_path).path,
            producer="workflow-plan",
            idempotency_key=idempotency_key,
            recorded_at=scheduler_clock.now(),
        )
        WorkflowExplainer(self._planner).explain(scenario_plan, root, scheduler_path)
        return scenario_plan, plan_path, graph_artifact, graph, store

    def _exercise_contracts(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scenario: str,
        private: Path,
        scheduler_state: Path,
        scheduler_probe: SchedulerSimulationResult,
    ) -> tuple[
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        dict[str, dict[str, dict[str, object]]],
        str,
        tuple[str, ...],
        str,
        str,
        str,
        Path,
        Path,
    ]:
        """Run the real planner/runtime/status/recovery/outcome chain offline."""

        plan = plan_artifact.value
        assert isinstance(plan, IntegratedPlan)
        observation_cause = _terminal_observation_cause(scenario)
        if observation_cause is not None:
            return self._exercise_terminal_observation(
                plan_artifact,
                root,
                private,
                scheduler_state,
                scheduler_probe,
                observation_cause,
            )
        clock = _SimulationClock(
            value=(
                datetime(2026, 8, 1, 0, 0, 1, tzinfo=UTC)
                if scenario == "crash-and-recovery"
                else datetime(2026, 8, 2, 0, 0, 0, tzinfo=UTC)
            )
        )
        runtime = WorkflowRuntimeService(clock, planner=self._planner)
        try:
            state_path = private / "state.json"
            event_path = private / "event.json"
            transition = runtime.run(
                plan_artifact,
                root,
                scheduler_state,
                state_path,
                event_path,
            )
            runtime.status(transition.state, plan_artifact, root, scheduler_state)
            state_artifact = transition.state
            state_binding = _workflow_binding(root, state_path, state_artifact)
            event_ids = [transition.event.artifact_id]
            trace = ["planner", "runtime", "status"]

            if scenario == "crash-and-recovery":
                recovered_path = private / "recovered-state.json"
                recovery_event_path = private / "recovery-event.json"
                state_artifact, recovery_event = WorkflowRecoveryService(
                    clock,
                    planner=self._planner,
                ).recover(
                    state_artifact,
                    state_binding,
                    plan_artifact,
                    (),
                    root,
                    scheduler_state,
                    recovered_path,
                    recovery_event_path,
                )
                state_path = recovered_path
                state_binding = _workflow_binding(root, state_path, state_artifact)
                event_ids.append(recovery_event.artifact_id)
                trace.extend(("recovery", "status"))
                runtime.status(state_artifact, plan_artifact, root, scheduler_state)
            if scenario == "candidate-supersession":
                intent_artifact = parse_workflow_artifact_bytes(
                    (root / plan.intent.reference.path).read_bytes(),
                    expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
                )
                intent = intent_artifact.value
                assert isinstance(intent, DevelopmentIntent)
                successor_candidate = CandidateIdentity(
                    plan.candidate.source_spec_sha256,
                    plan.candidate.git_head,
                    "D" * 64,
                )
                successor = artifact_from_value(
                    WorkflowArtifactType.DEVELOPMENT_INTENT,
                    replace(intent, candidate=successor_candidate),
                )
                successor_path = private / "successor-intent.json"
                ExclusiveWorkflowArtifactStore(root).publish(
                    successor_path,
                    serialize_workflow_artifact(successor),
                )
                (root / "workflow" / "candidate.json").write_text(
                    json.dumps(
                        successor_candidate.to_dict(),
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                supersession_planner = IntegratedPlanner(
                    _ExactCandidateVerifier(successor_candidate),
                    self._planner._source_reader,
                    self._planner._estimator,
                )
                superseded_path = private / "superseded-state.json"
                supersession_event_path = private / "supersession-event.json"
                supersession_runtime = WorkflowRuntimeService(
                    clock,
                    planner=supersession_planner,
                )
                superseded = supersession_runtime.supersede(
                    state_artifact,
                    state_binding,
                    plan_artifact,
                    successor,
                    _workflow_binding(root, successor_path, successor),
                    root,
                    scheduler_state,
                    superseded_path,
                    supersession_event_path,
                    private / "supersession-outcome.json",
                )
                state_artifact = superseded.state
                state_path = superseded_path
                state_binding = _workflow_binding(root, state_path, state_artifact)
                event_ids.append(superseded.event.artifact_id)
                trace.extend(("supersession", "outcome", "status"))
                outcome_artifact = superseded.outcome
                if outcome_artifact is None:
                    raise WorkflowSimulationError("Supersession did not publish its Outcome.")
                closure = state_artifact
            else:
                outcome_path = private / "outcome.json"
                outcome_event_path = private / "outcome-event.json"
                outcome_state_path = private / "outcome-state.json"
                outcome_artifact, outcome_event, closure = WorkflowOutcomeService(
                    clock,
                    planner=self._planner,
                ).publish(
                    state_artifact,
                    state_binding,
                    plan_artifact,
                    root,
                    scheduler_state,
                    outcome_path,
                    outcome_event_path,
                    outcome_state_path,
                )
                event_ids.append(outcome_event.artifact_id)
                trace.extend(("outcome", "status"))
            outcome_value = outcome_artifact.value
            closure_value = closure.value
            assert isinstance(outcome_value, WorkflowOutcome)
            assert isinstance(closure_value, WorkflowState)
            outcome_blockers = tuple(sorted(item.code for item in outcome_value.blockers))
            state_blockers = tuple(sorted(item.code for item in closure_value.blockers))
            if outcome_blockers != state_blockers:
                raise WorkflowSimulationError(
                    "Workflow Outcome and terminal State blockers diverged."
                )
            if scenario != "candidate-supersession":
                runtime.status(closure, plan_artifact, root, scheduler_state)
            native_artifact_ids = tuple(
                sorted(
                    {
                        scheduler_probe.state_id,
                        plan_artifact.artifact_id,
                        state_artifact.artifact_id,
                        closure.artifact_id,
                        outcome_artifact.artifact_id,
                        closure_value.scheduler_state_id,
                        *event_ids,
                        *(
                            source_id
                            for measurement in closure_value.measurements
                            for source_id in measurement.source_ids
                        ),
                        *(item.artifact_id for item in closure_value.observation_artifacts),
                    }
                )
            )
            measurements = _measurement_payload(closure_value.measurements)
        except (OSError, WorkflowContractError) as exc:
            raise WorkflowSimulationError("M8 scenario contract execution failed.") from exc
        epoch_head = SQLiteSchedulerStore(scheduler_state, root).workflow_head(
            plan_artifact.artifact_id
        )
        if epoch_head is None:
            raise WorkflowSimulationError("Simulation Plan epoch head is unavailable.")
        return (
            native_artifact_ids,
            tuple(event_ids),
            tuple(trace),
            measurements,
            outcome_value.disposition.value,
            outcome_blockers,
            outcome_artifact.artifact_id,
            closure.artifact_id,
            epoch_head.current_event_head_id,
            state_path if scenario == "candidate-supersession" else outcome_state_path,
            (
                private / "supersession-outcome.json"
                if scenario == "candidate-supersession"
                else outcome_path
            ),
        )

    def _exercise_terminal_observation(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        private: Path,
        scheduler_state: Path,
        scheduler_probe: SchedulerSimulationResult,
        cause: WorkflowTerminalObservationCause,
    ) -> tuple[
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        dict[str, dict[str, dict[str, object]]],
        str,
        tuple[str, ...],
        str,
        str,
        str,
        Path,
        Path,
    ]:
        """Finalize an authenticated M6 observation into the public terminal triple."""

        store = SQLiteSchedulerStore(scheduler_state, root)
        native_artifact = store.status()
        native = native_artifact.value
        assert isinstance(native, SchedulerState)
        plan = plan_artifact.value
        assert isinstance(plan, IntegratedPlan)
        source_ids = _terminal_observation_source_ids(plan, cause, store, native)
        observation = WorkflowTerminalObservation(
            cause=cause,
            scheduler_state_id=native_artifact.artifact_id,
            scheduler_event_head_id=store.current_event_head_id,
            source_artifact_ids=source_ids,
        )
        event_path = private / "outcome-event.json"
        state_path = private / "outcome-state.json"
        outcome_path = private / "outcome.json"
        transition = WorkflowRuntimeService(
            _SimulationClock(),
            planner=self._planner,
        ).finalize_observation(
            plan_artifact,
            root,
            scheduler_state,
            observation,
            event_path,
            state_path,
            outcome_path,
        )
        outcome_artifact = transition.outcome
        if outcome_artifact is None:
            raise WorkflowSimulationError("Observation finalizer omitted Workflow Outcome.")
        state_artifact = load_workflow_artifact(
            state_path,
            expected_type=WorkflowArtifactType.WORKFLOW_STATE,
        )
        reloaded_outcome = load_workflow_artifact(
            outcome_path,
            expected_type=WorkflowArtifactType.WORKFLOW_OUTCOME,
        )
        if (
            state_artifact != transition.state
            or reloaded_outcome != outcome_artifact
        ):
            raise WorkflowSimulationError("Observation terminal outputs did not reload exactly.")
        state = state_artifact.value
        outcome = outcome_artifact.value
        assert isinstance(state, WorkflowState)
        assert isinstance(outcome, WorkflowOutcome)
        state_blockers = tuple(sorted(item.code for item in state.blockers))
        outcome_blockers = tuple(sorted(item.code for item in outcome.blockers))
        if state_blockers != outcome_blockers:
            raise WorkflowSimulationError("Observation terminal blockers diverged.")
        event_ids = tuple(item.artifact_id for item in state.event_chain)
        epoch_head = store.workflow_head(plan_artifact.artifact_id)
        if epoch_head is None or epoch_head.phase.value != "terminal-confirmed":
            raise WorkflowSimulationError("Observation terminal epoch did not confirm.")
        native_ids = tuple(
            sorted(
                {
                    scheduler_probe.state_id,
                    plan_artifact.artifact_id,
                    state_artifact.artifact_id,
                    outcome_artifact.artifact_id,
                    *source_ids,
                    *event_ids,
                    *(source for item in state.measurements for source in item.source_ids),
                }
            )
        )
        return (
            native_ids,
            event_ids,
            ("planner", "runtime", "status", "outcome"),
            _measurement_payload(state.measurements),
            outcome.disposition.value,
            outcome_blockers,
            outcome_artifact.artifact_id,
            state_artifact.artifact_id,
            epoch_head.current_event_head_id,
            state_path,
            outcome_path,
        )

    def _observe(
        self,
        scenario: str,
        scheduler: SchedulerSimulationResult,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
    ) -> tuple[str, tuple[str, ...]]:
        """Assert a native side property without authoring the public result."""

        if not hasattr(scheduler, "outcome") or not hasattr(scheduler, "blockers"):
            raise WorkflowSimulationError("Scheduler probe returned no native observation.")
        observed_outcome = str(scheduler.outcome)
        native_blockers = tuple(str(item) for item in scheduler.blockers)
        if scenario == "non-ui-success":
            _require_probe(observed_outcome == "completed-after-verification")
            return "completed-contract-simulation", ()
        if scenario == "ui-observation-unavailable":
            _require_probe(observed_outcome == "completed-after-verification")
            return "blocked-without-external-effect", ("ui-evidence-unavailable",)
        if scenario == "approval-required":
            _require_probe("approval-required" in native_blockers)
            return "blocked-without-external-effect", ("approval-required",)
        if scenario == "approval-refused":
            _require_probe(observed_outcome == "approval-refused-without-dispatch")
            return "blocked-without-external-effect", ("approval-refused",)
        if scenario == "approval-expired":
            _require_probe(observed_outcome == "approval-expired-without-dispatch")
            return "blocked-without-external-effect", ("approval-expired",)
        if scenario == "stale-candidate":
            plan = plan_artifact.value
            assert isinstance(plan, IntegratedPlan)
            stale = artifact_from_value(
                WorkflowArtifactType.INTEGRATED_PLAN,
                replace(
                    plan,
                    candidate=CandidateIdentity(
                        plan.candidate.source_spec_sha256,
                        plan.candidate.git_head,
                        "D" * 64,
                    ),
                ),
            )
            _require_explainer_rejection(self._planner, stale, root, scheduler_state)
            return "blocked-without-external-effect", ("stale-candidate",)
        if scenario == "stale-context":
            plan = plan_artifact.value
            assert isinstance(plan, IntegratedPlan)
            stale = artifact_from_value(
                WorkflowArtifactType.INTEGRATED_PLAN,
                replace(
                    plan,
                    context_snapshot=replace(
                        plan.context_snapshot,
                        reference=replace(
                            plan.context_snapshot.reference,
                            sha256="A" * 64,
                        ),
                    ),
                ),
            )
            _require_explainer_rejection(self._planner, stale, root, scheduler_state)
            return "blocked-without-external-effect", ("stale-context",)
        if scenario == "lease-lost":
            _require_probe(observed_outcome == "safe-read-only-attempt-redispatched")
            return "blocked-without-external-effect", ("lease-lost",)
        if scenario == "solver-inconclusive":
            _require_probe(observed_outcome == "one-running-one-budget-blocked")
            return "blocked-without-external-effect", ("solver-inconclusive",)
        if scenario == "ambiguous-external-effect":
            _require_probe(
                observed_outcome == "blocked-unknown-no-automatic-retry" and bool(native_blockers)
            )
            return "blocked-without-external-effect", ("external-effect-ambiguous",)
        if scenario == "crash-and-recovery":
            _require_probe(observed_outcome == "running-with-current-fenced-lease")
            return "recoverable-from-native-evidence", ("recovery-required",)
        _require_probe(observed_outcome == "completed-after-verification")
        return "superseded-without-authority-migration", ("predecessor-superseded",)


def run_all_scenarios(
    plan_artifact: LoadedWorkflowArtifact,
    root: Path,
    scheduler_state: Path,
    planner: IntegratedPlanner,
    *,
    predecessor_scheduler_state: Path | None = None,
    evidence_validator: Callable[
        [WorkflowSimulationResult, WorkflowSimulationEvidence], None
    ]
    | None = None,
) -> tuple[WorkflowSimulationResult, ...]:
    """Execute all twelve scenarios in exact public order."""

    service = WorkflowSimulationService(planner)
    return tuple(
        service.run(
            plan_artifact,
            root,
            scheduler_state,
            scenario,
            predecessor_scheduler_state=predecessor_scheduler_state,
            evidence_validator=evidence_validator,
        )
        for scenario in SCENARIOS
    )


def _scheduler_scenario(scenario: str) -> str:
    if scenario in {
        "non-ui-success",
        "ui-observation-unavailable",
        "candidate-supersession",
    }:
        return "success"
    if scenario in {"stale-candidate", "stale-context", "crash-and-recovery"}:
        return "worker-crash-after-dispatch"
    if scenario == "lease-lost":
        return "host-timeout"
    if scenario == "solver-inconclusive":
        return "budget-exhaustion"
    if scenario == "ambiguous-external-effect":
        return "ambiguous-external-effect"
    raise WorkflowSimulationError("Scenario has no scheduler probe.")


def _execute_fixture_scheduler(
    store: SQLiteSchedulerStore,
    root: Path,
    graph: TaskGraph,
    scenario: str,
    clock: FixedSchedulerClock,
    evidence: ArtifactReference,
) -> SchedulerSimulationResult:
    """Execute result-producing probes with the fixture-native M3 reference."""

    if scenario not in {"success", "ambiguous-external-effect"}:
        return SchedulerSimulationService()._execute(
            store,
            root,
            graph,
            scenario,
            clock,
        )
    first_tick = store.tick(root, "HST-SIMULATOR", (), clock.now())
    if len(first_tick.outgoing) != 1:
        raise WorkflowSimulationError("Fixture scheduler did not dispatch one task.")
    dispatch = first_tick.outgoing[0]
    acknowledgement = _fixture_host_message(
        dispatch,
        MessageType.DISPATCH_ACKNOWLEDGEMENT,
        {
            "accepted": True,
            "effect_observed": "none",
            "note": "Simulator accepted the bounded intent.",
        },
        clock.now(),
    )
    ack_tick = store.tick(root, "HST-SIMULATOR", (acknowledgement,), clock.now())
    result = _fixture_host_message(
        dispatch,
        MessageType.TASK_RESULT,
        {
            "agent_result": artifact_reference_for(
                root,
                root / "examples" / "m2-orchestration" / "implementer-result.json",
            ).to_dict(),
            "outcome": "unknown" if scenario == "ambiguous-external-effect" else "succeeded",
            "effect_observed": (
                "ambiguous" if scenario == "ambiguous-external-effect" else "none"
            ),
            "evidence_refs": [evidence.to_dict()],
            "budget_usage": {
                "microunits": 0,
                "solver_calls": 0,
                "solver_steps": 0,
                "tool_calls": 0,
            },
        },
        clock.now(),
    )
    final_tick = store.tick(root, "HST-SIMULATOR", (result,), clock.now())
    accepted = len(ack_tick.accepted_message_ids) + len(final_tick.accepted_message_ids)
    rejected = len(ack_tick.rejected_message_ids) + len(final_tick.rejected_message_ids)
    store.validate()
    wait_report = deterministic_wait_report(store.wait_for_projection())
    native = store.status()
    native_value = native.value
    assert isinstance(native_value, SchedulerState)
    states = [item.state.value for item in native_value.tasks]
    outcomes = [item.outcome.value for item in native_value.tasks]
    valid = (
        states == ["completed"] and outcomes == ["succeeded"]
        if scenario == "success"
        else states == ["blocked"] and outcomes == ["unknown"]
    )
    if not valid:
        raise WorkflowSimulationError("Fixture scheduler result property did not hold.")
    events = store.export("events")
    messages = store.export("messages")
    blockers = (
        wait_report.cycle
        if wait_report.kind == "deadlock"
        else wait_report.blockers
    )
    outcome = (
        "blocked-unknown-no-automatic-retry"
        if scenario == "ambiguous-external-effect"
        else "completed-after-verification"
    )
    payload: dict[str, object] = {
        "scenario": scenario,
        "outcome": outcome,
        "state_id": native.artifact_id,
        "event_count": len(events),
        "message_count": len(messages),
        "accepted_messages": accepted,
        "rejected_messages": rejected,
        "wait_kind": wait_report.kind,
        "blockers": list(blockers),
        "offline": True,
    }
    return SchedulerSimulationResult(
        scenario=scenario,
        outcome=outcome,
        state_id=native.artifact_id,
        event_count=len(events),
        message_count=len(messages),
        accepted_messages=accepted,
        rejected_messages=rejected,
        wait_kind=wait_report.kind,
        blockers=blockers,
        offline=True,
        deterministic_digest=hashlib.sha256(
            canonical_json_bytes(payload)
        ).hexdigest().upper(),
    )


def _fixture_host_message(
    dispatch_artifact: LoadedSchedulerArtifact,
    message_type: MessageType,
    payload: dict[str, object],
    recorded_at: datetime,
) -> LoadedSchedulerArtifact:
    """Create one M6 host message without changing the validated Agent Result wrapper."""

    dispatch = dispatch_artifact.value
    if not isinstance(dispatch, MailboxMessage):
        raise WorkflowSimulationError("Fixture scheduler dispatch is invalid.")
    return scheduler_artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=message_type,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender="HST-SIMULATOR",
            recipient="HST-SCHEDULER",
            graph_id=dispatch.graph_id,
            task_id=dispatch.task_id,
            candidate=dispatch.candidate,
            context_snapshot_id=dispatch.context_snapshot_id,
            attempt=dispatch.attempt,
            lease_id=dispatch.lease_id,
            fence=dispatch.fence,
            idempotency_key=dispatch.idempotency_key,
            sensitivity=dispatch.sensitivity,
            provenance=dispatch.provenance,
            causal_parent_message_ids=(dispatch_artifact.artifact_id,),
            recorded_at=recorded_at.isoformat(timespec="seconds").replace(
                "+00:00",
                "Z",
            ),
            payload=payload,
        ),
    )


def _terminal_observation_cause(
    scenario: str,
) -> WorkflowTerminalObservationCause | None:
    """Map an approved failed scenario to its closed native observation cause."""

    return {
        "ui-observation-unavailable": (
            WorkflowTerminalObservationCause.UI_EVIDENCE_UNAVAILABLE
        ),
        "approval-required": WorkflowTerminalObservationCause.APPROVAL_REQUIRED,
        "approval-refused": WorkflowTerminalObservationCause.APPROVAL_REFUSED,
        "approval-expired": WorkflowTerminalObservationCause.APPROVAL_EXPIRED,
        "stale-candidate": WorkflowTerminalObservationCause.STALE_CANDIDATE,
        "stale-context": WorkflowTerminalObservationCause.STALE_CONTEXT,
        "lease-lost": WorkflowTerminalObservationCause.LEASE_LOST,
        "solver-inconclusive": WorkflowTerminalObservationCause.SOLVER_INCONCLUSIVE,
        "ambiguous-external-effect": (
            WorkflowTerminalObservationCause.EXTERNAL_EFFECT_AMBIGUOUS
        ),
    }.get(scenario)


def _terminal_observation_source_ids(
    plan: IntegratedPlan,
    cause: WorkflowTerminalObservationCause,
    store: SQLiteSchedulerStore,
    native: SchedulerState,
) -> tuple[str, ...]:
    """Select only the exact authenticated native evidence for one closed cause."""

    if cause is WorkflowTerminalObservationCause.STALE_CANDIDATE:
        return (plan.intent.artifact_id,)
    if cause is WorkflowTerminalObservationCause.STALE_CONTEXT:
        return (plan.context_snapshot.artifact_id,)
    if cause is WorkflowTerminalObservationCause.SOLVER_INCONCLUSIVE:
        if not plan.solver_requests:
            raise WorkflowSimulationError(
                "Terminal solver observation lacks an admitted M7 request."
            )
        return (plan.solver_requests[0].artifact_id,)
    if cause in {
        WorkflowTerminalObservationCause.APPROVAL_REFUSED,
        WorkflowTerminalObservationCause.APPROVAL_EXPIRED,
    }:
        decision = (
            "rejected"
            if cause is WorkflowTerminalObservationCause.APPROVAL_REFUSED
            else "approved"
        )
        matches = tuple(
            artifact.artifact_id
            for artifact in store.export("messages")
            if isinstance((message := artifact.value), MailboxMessage)
            and message.message_type is MessageType.APPROVAL_DECISION
            and message.payload.get("decision") == decision
        )
        if len(matches) != 1:
            raise WorkflowSimulationError(
                "Terminal approval observation lacks one exact M6 decision."
            )
        return matches
    if cause is WorkflowTerminalObservationCause.LEASE_LOST:
        matches = tuple(
            artifact.artifact_id
            for artifact in store.export("events")
            if isinstance((event := artifact.value), SchedulerEvent)
            and event.cause == "lease-expired"
        )
        if not matches:
            raise WorkflowSimulationError(
                "Terminal lease observation lacks the M6 lease-expired Event."
            )
        return tuple(sorted(matches))
    return (store.current_event_head_id,)


def _prepare_solver_scenario_contract(
    root: Path,
    private: Path,
    graph: TaskGraph,
) -> tuple[NativeArtifactBinding, SolverRequest, str]:
    """Publish one real private M7 Registry and prepare its graph-bound Request."""

    source_root = Path(__file__).resolve().parents[3]
    registry_template = parse_solver_artifact_bytes(
        (source_root / "examples/m7-solver/solver-registry.json").read_bytes(),
        expected_type=SolverArtifactType.REGISTRY,
    ).value
    request_template = parse_solver_artifact_bytes(
        (source_root / "examples/m7-solver/solver-request.json").read_bytes(),
        expected_type=SolverArtifactType.REQUEST,
    ).value
    assert isinstance(registry_template, SolverRegistry)
    assert isinstance(request_template, SolverRequest)
    context = graph.contexts[0]
    registry = solver_artifact_from_value(
        SolverArtifactType.REGISTRY,
        replace(
            registry_template,
            adapters=tuple(
                replace(adapter, provenance=(context.reference,))
                for adapter in registry_template.adapters
            ),
        ),
    )
    registry_path = private / "solver-registry.json"
    ExclusiveWorkflowArtifactStore(root).publish(
        registry_path,
        serialize_solver_artifact(registry),
    )
    registry_binding = NativeArtifactBinding(
        SolverArtifactType.REGISTRY.value,
        registry.artifact_id,
        artifact_reference_for(root, registry_path),
        True,
    )
    prepared = replace(
        request_template,
        registry=registry_binding.reference,
        registry_id=registry.artifact_id,
        task_id=graph.tasks[0].task_id,
        candidate=graph.candidate,
        context_snapshot=context.reference,
        context_snapshot_id=context.artifact_id,
    )
    prepared = replace(
        prepared,
        contract_id=operational_contract_id(prepared.operational_content()),
    )
    return registry_binding, prepared, solver_capability_token(prepared)


def _solver_scenario_graph(graph: TaskGraph, token: str) -> TaskGraph:
    """Build the native two-task M6 budget boundary around one real M7 task."""

    expanded = _scenario_graph(graph, "budget-exhaustion")
    first_id = graph.tasks[0].task_id
    tasks = tuple(
        replace(
            task,
            kind=TaskKind.SOLVER,
            effect_kind=EffectKind.READ_ONLY,
            required_capabilities=(token,),
            required_tools=(),
            owned_paths=(),
            worktree_assignment=None,
            evidence_predicate=("evidence-reference-present",),
            terminal_predicate=("agent-result-valid",),
        )
        if task.task_id == first_id
        else task
        for task in expanded.tasks
    )
    return replace(
        expanded,
        tasks=tasks,
        budget=replace(
            expanded.budget,
            max_solver_calls=1,
            max_solver_steps=32,
        ),
    )


def _advertise_solver_capability(
    store: SQLiteSchedulerStore,
    root: Path,
    graph_artifact: LoadedSchedulerArtifact,
    graph: TaskGraph,
    now: datetime,
) -> None:
    """Admit the exact M7 token so M6 observes only its bounded budget result."""

    tokens = tuple(
        capability
        for task in graph.tasks
        for capability in task.required_capabilities
        if capability.startswith("m7-solver-v1@")
    )
    if len(tokens) != 1:
        raise WorkflowSimulationError("Solver scenario lacks one exact M7 capability.")
    observation = scheduler_artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.CAPABILITY_OBSERVATION,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender="HST-SIMULATOR",
            recipient="HST-SCHEDULER",
            graph_id=graph_artifact.artifact_id,
            task_id=None,
            candidate=graph.candidate,
            context_snapshot_id=None,
            attempt=None,
            lease_id=None,
            fence=None,
            idempotency_key=None,
            sensitivity=graph.contexts[0].sensitivity,
            provenance=(),
            causal_parent_message_ids=(),
            recorded_at=now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            payload={"capabilities": list(tokens)},
        ),
    )
    tick = store.tick(
        root=root,
        host_id="HST-SIMULATOR",
        messages=(observation,),
        now=now,
    )
    if tick.accepted_message_ids != (observation.artifact_id,) or len(tick.outgoing) != 1:
        raise WorkflowSimulationError("M7 capability did not establish the budget probe.")


def _execute_approval_probe(
    store: SQLiteSchedulerStore,
    graph: TaskGraph,
    root: Path,
    scenario: str,
    now: datetime,
) -> SchedulerSimulationResult:
    """Observe approval behavior in the same M6 store later adopted by M8."""

    task = graph.tasks[0]
    first = store.tick(root, "HST-M8-RUNTIME", (), now)
    accepted = len(first.accepted_message_ids)
    rejected = len(first.rejected_message_ids)
    if first.outgoing:
        raise WorkflowSimulationError("Approval probe dispatched before approval.")
    if scenario != "approval-required":
        proposal_artifact = store.export("leases")[-1]
        proposal = proposal_artifact.value
        assert isinstance(proposal, Lease)
        binding = next(
            item for item in graph.contexts if item.artifact_id == task.context_snapshot_id
        )
        stamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        expires = now + (
            timedelta(hours=1) if scenario == "approval-refused" else timedelta(seconds=1)
        )
        approval = scheduler_artifact_from_value(
            SchedulerArtifactType.MAILBOX_MESSAGE,
            MailboxMessage(
                message_type=MessageType.APPROVAL_DECISION,
                direction=MessageDirection.OWNER_TO_SCHEDULER,
                sender="HST-OWNER",
                recipient="HST-SCHEDULER",
                graph_id=store.status().value.graph_id,  # type: ignore[union-attr]
                task_id=task.task_id,
                candidate=graph.candidate,
                context_snapshot_id=task.context_snapshot_id,
                attempt=proposal.attempt,
                lease_id=proposal_artifact.artifact_id,
                fence=proposal.fence,
                idempotency_key=proposal.idempotency_key,
                sensitivity=binding.sensitivity,
                provenance=(binding.reference,),
                causal_parent_message_ids=(),
                recorded_at=stamp,
                payload={
                    "approval_id": (
                        "APR-M8-SIM-REFUSED"
                        if scenario == "approval-refused"
                        else "APR-M8-SIM-EXPIRED"
                    ),
                    "approval_type": "owner",
                    "decision": "rejected" if scenario == "approval-refused" else "approved",
                    "transition": "dispatch",
                    "effect_digest": hashlib.sha256(canonical_json_bytes(task.to_dict()))
                    .hexdigest()
                    .upper(),
                    "approved_at": stamp,
                    "expires_at": expires.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "authority": "Owner",
                    "supersedes_approval_id": None,
                },
            ),
        )
        observed_at = now if scenario == "approval-refused" else now + timedelta(seconds=2)
        decision_tick = store.tick(root, "HST-M8-RUNTIME", (approval,), observed_at)
        accepted += len(decision_tick.accepted_message_ids)
        rejected += len(decision_tick.rejected_message_ids)
        if decision_tick.outgoing:
            raise WorkflowSimulationError("Rejected or expired approval dispatched work.")
        if scenario == "approval-expired":
            expiry_tick = store.tick(
                root,
                "HST-M8-RUNTIME",
                (),
                observed_at + timedelta(seconds=1),
            )
            accepted += len(expiry_tick.accepted_message_ids)
            rejected += len(expiry_tick.rejected_message_ids)
            if expiry_tick.outgoing:
                raise WorkflowSimulationError("Expired approval dispatched work.")
    store.validate()
    state_artifact = store.status()
    state = state_artifact.value
    assert isinstance(state, SchedulerState)
    blockers = tuple(
        sorted({blocker.code for projection in state.tasks for blocker in projection.blockers})
    )
    if "approval-required" not in blockers:
        raise WorkflowSimulationError("Approval probe did not remain fail closed.")
    events = store.export("events")
    messages = store.export("messages")
    if scenario == "approval-refused":
        if accepted != 1:
            raise WorkflowSimulationError("Rejected approval was not recorded exactly.")
        observed_outcome = "approval-refused-without-dispatch"
    elif scenario == "approval-expired":
        expired_messages = tuple(
            message.value
            for message in messages
            if isinstance(message.value, MailboxMessage)
            and message.value.message_type is MessageType.APPROVAL_DECISION
            and str(message.value.payload["expires_at"])
            < (now + timedelta(seconds=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
        )
        if accepted != 1 or rejected != 0 or len(expired_messages) != 1:
            raise WorkflowSimulationError("Expired approval observation drifted.")
        observed_outcome = "approval-expired-without-dispatch"
    else:
        observed_outcome = "approval-pending-without-dispatch"
    wait = SchedulerService().wait_report(store.path, root)
    payload: dict[str, object] = {
        "scenario": scenario,
        "outcome": observed_outcome,
        "state_id": state_artifact.artifact_id,
        "event_count": len(events),
        "message_count": len(messages),
        "accepted_messages": accepted,
        "rejected_messages": rejected,
        "wait_kind": wait.kind,
        "blockers": list(blockers),
        "offline": True,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest().upper()
    return SchedulerSimulationResult(
        scenario=scenario,
        outcome=observed_outcome,
        state_id=state_artifact.artifact_id,
        event_count=len(events),
        message_count=len(messages),
        accepted_messages=accepted,
        rejected_messages=rejected,
        wait_kind=wait.kind,
        blockers=blockers,
        offline=True,
        deterministic_digest=digest,
    )


def _require_explainer_rejection(
    planner: IntegratedPlanner,
    plan: LoadedWorkflowArtifact,
    root: Path,
    scheduler_state: Path,
) -> None:
    try:
        WorkflowExplainer(planner).explain(plan, root, scheduler_state)
    except WorkflowContractError:
        return
    raise WorkflowSimulationError("Stale or superseding Plan was accepted by explainer.")


def _require_probe(condition: bool) -> None:
    if not condition:
        raise WorkflowSimulationError("Native scenario property did not reproduce.")


@dataclass(slots=True)
class _SimulationClock:
    """Advance a deterministic native timestamp for each persisted transition."""

    value: datetime = datetime(2026, 8, 2, 0, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        observed = self.value
        self.value += timedelta(seconds=1)
        return observed


@dataclass(frozen=True, slots=True)
class _ExactCandidateVerifier:
    """Accept only the explicit successor Candidate used by one offline scenario."""

    expected: CandidateIdentity

    def verify(self, repository_root: Path, expected: CandidateIdentity) -> None:
        marker = json.loads(
            (repository_root / "workflow" / "candidate.json").read_text(
                encoding="utf-8"
            )
        )
        if expected != self.expected or marker != expected.to_dict():
            raise WorkflowSimulationError("Simulation Candidate observation drifted.")

    def observe(
        self,
        repository_root: Path,
        expected: CandidateIdentity,
        *,
        scheduler_state: Path,
        plan_id: str | None = None,
    ) -> WorkflowPublicationObservation:
        if not repository_root.is_dir():
            raise WorkflowSimulationError(
                "Simulation Candidate observation root disappeared."
            )
        self.verify(repository_root, expected)
        store = SQLiteSchedulerStore(scheduler_state, repository_root)
        snapshot = store.workflow_receipt_snapshot(plan_id)
        return WorkflowPublicationObservation(
            git=GitObservation(
                root_matches=True,
                branch="simulation",
                head=expected.git_head,
                clean=True,
                repository_digest=expected.repository_digest,
            ),
            scheduler_state_path=scheduler_state.resolve().relative_to(
                repository_root.resolve()
            ).as_posix(),
            receipts=snapshot,
            tracked_paths=(),
            untracked_non_ignored_paths=(),
            receipt_excluded_paths=(),
            receipt_plan_id=plan_id,
        )

    def revalidate(
        self,
        repository_root: Path,
        observation: WorkflowPublicationObservation,
        *,
        scheduler_state: Path,
    ) -> None:
        if observation != self.observe(
            repository_root,
            self.expected,
            scheduler_state=scheduler_state,
            plan_id=observation.receipt_plan_id,
        ):
            raise WorkflowSimulationError("Simulation Candidate observation drifted.")

    def classify_output_paths(
        self,
        repository_root: Path,
        paths: tuple[str, ...],
        *,
        scheduler_state: Path,
        plan_id: str | None,
    ) -> None:
        head = (
            None
            if plan_id is None
            else SQLiteSchedulerStore(scheduler_state, repository_root).workflow_head(plan_id)
        )
        receipts = {} if head is None else {item.path: item for item in head.receipts}
        folded: set[str] = set()
        for relative in paths:
            key = relative.casefold()
            if key in folded:
                raise WorkflowSimulationError("Simulation output path collides.")
            folded.add(key)
            target = repository_root / relative
            if target.exists() and relative not in receipts:
                raise WorkflowSimulationError("Simulation output is foreign.")

    def preflight_outputs(
        self,
        repository_root: Path,
        artifacts: tuple[tuple[str, str, str, str], ...],
        *,
        scheduler_state: Path,
        plan_id: str,
    ) -> None:
        head = SQLiteSchedulerStore(scheduler_state, repository_root).workflow_head(plan_id)
        receipts = {} if head is None else {item.path: item for item in head.receipts}
        self.classify_output_paths(
            repository_root,
            tuple(item[0] for item in artifacts),
            scheduler_state=scheduler_state,
            plan_id=plan_id,
        )
        for relative, artifact_type, artifact_id, producer in artifacts:
            if not (repository_root / relative).exists():
                continue
            receipt = receipts.get(relative)
            if receipt is None or (
                receipt.artifact_type,
                receipt.artifact_id,
                receipt.producer,
            ) != (artifact_type, artifact_id, producer):
                raise WorkflowSimulationError("Simulation output receipt is foreign.")

    def confirm_outputs(
        self,
        repository_root: Path,
        observation: WorkflowPublicationObservation,
        expected: CandidateIdentity,
        artifacts: tuple[tuple[str, str, str, str], ...],
        *,
        scheduler_state: Path,
        plan_id: str,
    ) -> None:
        self.verify(repository_root, expected)
        if observation.git.head != expected.git_head:
            raise WorkflowSimulationError("Simulation pinned Candidate drifted.")
        head = SQLiteSchedulerStore(scheduler_state, repository_root).workflow_head(plan_id)
        if head is None:
            raise WorkflowSimulationError("Simulation terminal head disappeared.")
        receipts = {item.path: item for item in head.receipts}
        for relative, artifact_type, artifact_id, producer in artifacts:
            receipt = receipts.get(relative)
            if receipt is None or (
                receipt.artifact_type,
                receipt.artifact_id,
                receipt.producer,
                receipt.status.value,
            ) != (artifact_type, artifact_id, producer, "confirmed"):
                raise WorkflowSimulationError("Simulation terminal receipt is not confirmed.")


@contextmanager
def _deterministic_private_directory(
    runtime_parent: Path,
    scenario: str,
) -> Iterator[Path]:
    """Create one collision-failing stable private namespace, then remove only it."""

    private = runtime_parent / f".simulation-{scenario}"
    try:
        private.mkdir()
    except FileExistsError as exc:
        raise WorkflowSimulationError("Simulation private namespace already exists.") from exc
    try:
        yield private
    finally:
        shutil.rmtree(private)


def _workflow_binding(
    root: Path,
    path: Path,
    artifact: LoadedWorkflowArtifact,
) -> NativeArtifactBinding:
    return NativeArtifactBinding(
        artifact_type=artifact.artifact_type.value,
        artifact_id=artifact.artifact_id,
        reference=artifact_reference_for(root, path),
        required=True,
    )


def _authenticate_plan(
    plan_artifact: LoadedWorkflowArtifact,
    root: Path,
    scheduler_state: Path,
) -> None:
    """Authenticate the supplied Plan solely from its confirmed M6 v2 receipt."""

    plan = plan_artifact.value
    assert isinstance(plan, IntegratedPlan)
    store = SQLiteSchedulerStore(scheduler_state, root)
    store.validate()
    store.require_workflow_authority()
    head = store.workflow_head(plan_artifact.artifact_id)
    if head is None:
        raise WorkflowSimulationError("Workflow simulation Plan has no M6 epoch authority.")
    matches = tuple(
        receipt
        for receipt in head.receipts
        if receipt.artifact_type == WorkflowArtifactType.INTEGRATED_PLAN.value
        and receipt.artifact_id == plan_artifact.artifact_id
        and receipt.producer == "workflow-plan"
        and receipt.status.value == "confirmed"
    )
    if len(matches) != 1:
        raise WorkflowSimulationError(
            "Workflow simulation Plan receipt is not unique and confirmed."
        )
    store.authenticate_workflow_artifact(
        plan_id=plan_artifact.artifact_id,
        artifact_type=WorkflowArtifactType.INTEGRATED_PLAN.value,
        artifact_id=plan_artifact.artifact_id,
        path=matches[0].path,
        producer="workflow-plan",
        candidate=plan.candidate,
        graph_id=plan.task_graph.artifact_id,
    )


def _plan_idempotency_key(plan_id: str, intent_id: str) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes({"plan_id": plan_id, "intent_id": intent_id})
    ).hexdigest().upper()
    return f"M8-IDEM-{digest}"


def _prepare_fixture_workspace(
    source_root: Path,
    private: Path,
    fixture: WorkflowFixtureBundle,
    plan: IntegratedPlan,
) -> Path:
    """Create one isolated execution root without mutating the caller workspace."""

    scenario_root = private / "root"
    scenario_root.mkdir()
    for name in ("examples", "requirements"):
        source = source_root / name
        if source.is_dir():
            shutil.copytree(source, scenario_root / name)
    workflow = scenario_root / "workflow"
    workflow.mkdir()
    intent_source = source_root / plan.intent.reference.path
    intent_target = scenario_root / plan.intent.reference.path
    intent_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(intent_source, intent_target)
    source_references = (
        plan.requirement_baseline,
        plan.context_graph.reference,
        plan.context_query.reference,
        plan.context_selection.reference,
        plan.context_snapshot.reference,
        plan.task_graph.reference,
    )
    for reference in source_references:
        source = source_root / reference.path
        target = scenario_root / reference.path
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    marker = workflow / "candidate.json"
    marker.write_text(
        json.dumps(plan.candidate.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fixture_root = workflow / "fixture"
    for relative, content in fixture.files:
        target = fixture_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return scenario_root


def _fixture_native_inputs(
    root: Path,
    private: Path,
    source_plan: IntegratedPlan,
    fixture: WorkflowFixtureBundle,
) -> tuple[
    CandidateIdentity,
    str,
    ArtifactReference,
    ArtifactReference,
    tuple[str, ...],
    tuple[str, ...],
    NativeArtifactBinding,
    NativeArtifactBinding,
    NativeArtifactBinding,
    NativeArtifactBinding,
]:
    """Derive fixture-native M1, M5, and M3 inputs from exact bundle bytes."""

    files = dict(fixture.files)
    try:
        specification_bytes = files["specification.md"]
        expected = json.loads(files["expected-normalized.json"])
        structured = json.loads(files["structured-run.json"])
    except (KeyError, UnicodeError, ValueError) as exc:
        raise WorkflowSimulationError("Workflow fixture core inputs are invalid.") from exc
    if not isinstance(expected, dict) or not isinstance(structured, dict):
        raise WorkflowSimulationError("Workflow fixture core inputs are not objects.")
    specification_sha256 = hashlib.sha256(specification_bytes).hexdigest().upper()
    try:
        specification_text = specification_bytes.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise WorkflowSimulationError("Workflow fixture specification is not UTF-8.") from exc
    requirements_raw = expected.get("requirements")
    if (
        expected.get("project_id") != fixture.project_fixture
        or expected.get("source_sha256") != specification_sha256
        or not isinstance(requirements_raw, list)
        or not requirements_raw
    ):
        raise WorkflowSimulationError("Workflow fixture normalization is not content-bound.")
    candidate = replace(
        source_plan.candidate,
        source_spec_sha256=specification_sha256,
        repository_digest=fixture.fixture_bundle_id.rsplit("-", 1)[-1],
    )
    (root / "workflow" / "candidate.json").write_text(
        json.dumps(candidate.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    specification_path = root / "workflow" / "fixture" / "specification.md"
    specification = artifact_reference_for(root, specification_path)

    template_path = root / source_plan.requirement_baseline.path
    try:
        baseline = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise WorkflowSimulationError("M1 Baseline template is invalid.") from exc
    if not isinstance(baseline, dict):
        raise WorkflowSimulationError("M1 Baseline template is not an object.")
    baseline_id = expected.get("baseline_id")
    if baseline_id != f"RB-{specification_sha256[:16]}":
        raise WorkflowSimulationError("Fixture Baseline identity is not source-bound.")
    normalized_requirements: list[dict[str, object]] = []
    requirement_ids: list[str] = []
    acceptance_ids: list[str] = []
    for index, raw in enumerate(requirements_raw, start=1):
        if not isinstance(raw, dict):
            raise WorkflowSimulationError("Fixture requirement is not an object.")
        requirement_id = raw.get("requirement_id")
        statement = raw.get("statement")
        raw_acceptance = raw.get("acceptance_ids")
        methods = raw.get("verification_methods")
        if (
            not isinstance(requirement_id, str)
            or not isinstance(statement, str)
            or not isinstance(raw_acceptance, list)
            or not raw_acceptance
            or any(not isinstance(item, str) for item in raw_acceptance)
            or not isinstance(methods, list)
            or not methods
            or any(not isinstance(item, str) for item in methods)
        ):
            raise WorkflowSimulationError("Fixture requirement normalization is invalid.")
        if requirement_id not in specification_text or statement not in specification_text:
            raise WorkflowSimulationError(
                "Fixture normalized requirement is not present in the specification bytes."
            )
        requirement_ids.append(requirement_id)
        acceptance_ids.extend(raw_acceptance)
        normalized_requirements.append(
            {
                "id": requirement_id,
                "title": statement,
                "type": raw.get("type"),
                "priority": raw.get("priority"),
                "status": "baselined",
                "source": {
                    "document": "specification.md",
                    "section": "Fixture specification",
                    "line_start": index,
                    "line_end": index,
                    "excerpt": statement,
                    "derivation_basis": "Derived from expected-normalized.json.",
                },
                "statement": statement,
                "acceptance_criteria": [
                    {
                        "id": item,
                        "statement": statement,
                        "verification_methods": methods,
                    }
                    for item in raw_acceptance
                ],
                "verification_methods": methods,
                "assumptions": [],
                "open_questions": [],
                "trace_links": {
                    "design": [],
                    "code": [],
                    "tests": [],
                    "evidence": [
                        f"workflow/fixture/{path}"
                        for path, _ in fixture.files
                        if path.startswith("evidence/")
                    ],
                    "releases": [],
                },
                "identifier_source": "explicit",
            }
        )
    baseline.update(
        {
            "baseline_id": baseline_id,
            "source": {
                "filename": "specification.md",
                "path": specification.path,
                "sha256": specification.sha256,
                "size_bytes": len(specification_bytes),
                "modified_at": "2026-08-01T00:00:00+00:00",
                "imported_at": "2026-08-01T00:00:00+00:00",
            },
            "requirements": normalized_requirements,
            "source_acceptance_criteria": [],
            "diagnostics": [],
            "approval_state": {"required": [], "granted": []},
        }
    )
    baseline_path = private / "fixture-requirement-baseline.json"
    ExclusiveWorkflowArtifactStore(root).publish(
        baseline_path,
        (json.dumps(baseline, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    requirement_baseline = artifact_reference_for(root, baseline_path)

    m3_reference = _fixture_evidence_ledger(
        root,
        candidate,
        baseline_id,
        tuple(requirement_ids),
        tuple(normalized_requirements),
        fixture,
        structured,
    )
    if structured.get("requirements_implemented") != requirement_ids:
        raise WorkflowSimulationError(
            "Structured fixture run does not implement the exact normalized requirements."
        )
    context_bindings = _fixture_context_chain(
        root,
        private,
        source_plan,
        candidate,
        fixture,
        m3_reference,
    )
    return (
        candidate,
        baseline_id,
        specification,
        requirement_baseline,
        tuple(requirement_ids),
        tuple(acceptance_ids),
        *context_bindings,
    )


def _fixture_context_chain(
    root: Path,
    private: Path,
    source_plan: IntegratedPlan,
    candidate: CandidateIdentity,
    fixture: WorkflowFixtureBundle,
    m3_reference: ArtifactReference,
) -> tuple[
    NativeArtifactBinding,
    NativeArtifactBinding,
    NativeArtifactBinding,
    NativeArtifactBinding,
]:
    """Re-identity the exact M5 chain with the full fixture bundle identity."""

    graph_loaded = load_context_artifact(
        root / source_plan.context_graph.reference.path,
        expected_type=ContextArtifactType.GRAPH,
    )
    query_loaded = load_context_artifact(
        root / source_plan.context_query.reference.path,
        expected_type=ContextArtifactType.QUERY,
    )
    selection_loaded = load_context_artifact(
        root / source_plan.context_selection.reference.path,
        expected_type=ContextArtifactType.SELECTION,
    )
    snapshot_loaded = load_context_artifact(
        root / source_plan.context_snapshot.reference.path,
        expected_type=ContextArtifactType.SNAPSHOT,
    )
    graph = graph_loaded.value
    query = query_loaded.value
    selection = selection_loaded.value
    snapshot = snapshot_loaded.value
    assert isinstance(graph, ContextGraph)
    assert isinstance(query, ContextQuery)
    assert isinstance(selection, ContextSelection)
    assert isinstance(snapshot, ContextSnapshot)
    canonical = tuple(
        node
        for node in graph.nodes
        if node.authority is AuthorityClass.CANONICAL_SPECIFICATION
    )
    if len(canonical) != 1:
        raise WorkflowSimulationError("M5 template canonical source is ambiguous.")
    source_node = canonical[0]
    specification_path = root / "workflow" / "fixture" / "specification.md"
    specification_bytes = specification_path.read_bytes()
    specification_text = specification_bytes.decode("utf-8", errors="strict")
    line_count = max(1, len(specification_text.splitlines()))
    specification_reference = artifact_reference_for(root, specification_path)
    locator = replace(
        source_node.locator,
        path=specification_reference.path,
        sha256=specification_reference.sha256,
        line_start=1,
        line_end=line_count,
    )
    provenance = replace(
        source_node.provenance,
        references=tuple(
            sorted(
                (specification_reference, m3_reference),
                key=lambda item: (item.path, item.sha256),
            )
        ),
    )
    fixture_source = replace(
        source_node,
        node_id="",
        source_id="",
        title=f"{fixture.project_fixture} fixture specification",
        text=specification_text,
        text_sha256=hashlib.sha256(specification_text.encode("utf-8")).hexdigest().upper(),
        locator=locator,
        provenance=provenance,
        identifiers=(fixture.project_fixture,),
        labels=("fixture", "specification"),
    )
    fixture_source = replace(
        fixture_source,
        source_id=source_identity(fixture_source.source_content_dict()),
    )
    fixture_source = replace(
        fixture_source,
        node_id=node_identity(fixture_source.content_dict()),
    )
    node_map = {source_node.node_id: fixture_source.node_id}
    nodes = tuple(
        sorted(
            (
                fixture_source if node.node_id == source_node.node_id else node
                for node in graph.nodes
            ),
            key=lambda item: item.node_id,
        )
    )
    edges = []
    for edge in graph.edges:
        changed = replace(
            edge,
            edge_id="",
            source_node_id=node_map.get(edge.source_node_id, edge.source_node_id),
            target_node_id=node_map.get(edge.target_node_id, edge.target_node_id),
        )
        edges.append(replace(changed, edge_id=edge_identity(changed.content_dict())))
    edges.sort(key=lambda item: item.edge_id)
    bundle_digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "fixture_bundle_id": fixture.fixture_bundle_id,
                "m3_evidence_ledger": m3_reference.to_dict(),
            }
        )
    ).hexdigest().upper()
    graph_artifact = context_artifact_from_value(
        ContextArtifactType.GRAPH,
        replace(
            graph,
            candidate=candidate,
            manifest_id=f"CTX-MANIFEST-{bundle_digest}",
            nodes=nodes,
            edges=tuple(edges),
        ),
    )
    query_value = replace(
        query,
        candidate=candidate,
        graph_id=graph_artifact.artifact_id,
        required_node_ids=tuple(
            sorted(node_map.get(value, value) for value in query.required_node_ids)
        ),
        seed_node_ids=tuple(
            sorted(node_map.get(value, value) for value in query.seed_node_ids)
        ),
    )
    query_artifact = context_artifact_from_value(ContextArtifactType.QUERY, query_value)
    selection_artifact = ContextSelector(CanonicalUTF8ByteEstimator()).select(
        graph_artifact,
        query_artifact,
    )
    snapshot_artifact = ContextSnapshotService(
        LocalContextSourceReader(),
        _ExactCandidateVerifier(candidate),
        CanonicalUTF8ByteEstimator(),
    ).build(
        graph_artifact,
        selection_artifact,
        repository_root=root,
    )
    store = ExclusiveWorkflowArtifactStore(root)
    values = (
        (graph_artifact, private / "fixture-context-graph.json"),
        (query_artifact, private / "fixture-context-query.json"),
        (selection_artifact, private / "fixture-context-selection.json"),
        (snapshot_artifact, private / "fixture-context-snapshot.json"),
    )
    bindings: list[NativeArtifactBinding] = []
    for artifact, path in values:
        store.publish(path, serialize_context_artifact(artifact))
        bindings.append(
            NativeArtifactBinding(
                artifact.artifact_type.value,
                artifact.artifact_id,
                artifact_reference_for(root, path),
                True,
            )
        )
    return tuple(bindings)  # type: ignore[return-value]


def _fixture_task_graph(
    graph: TaskGraph,
    candidate: CandidateIdentity,
    context_snapshot: NativeArtifactBinding,
) -> TaskGraph:
    """Bind every M6 task to the fixture-specific M5 snapshot."""

    template = graph.contexts[0]
    context = replace(
        template,
        artifact_id=context_snapshot.artifact_id,
        reference=context_snapshot.reference,
        candidate=candidate,
    )
    return replace(
        graph,
        candidate=candidate,
        contexts=(context,),
        tasks=tuple(
            replace(task, context_snapshot_id=context_snapshot.artifact_id)
            for task in graph.tasks
        ),
    )


def _fixture_evidence_ledger(
    root: Path,
    candidate: CandidateIdentity,
    baseline_id: str,
    requirement_ids: tuple[str, ...],
    normalized_requirements: tuple[dict[str, object], ...],
    fixture: WorkflowFixtureBundle,
    structured: dict[str, object],
) -> ArtifactReference:
    """Materialize one valid M3 ledger from the fixture's exact evidence bytes."""

    input_identity = structured.get("input_identity")
    structured_evidence = structured.get("evidence")
    if (
        not isinstance(input_identity, dict)
        or input_identity.get("project_id") != fixture.project_fixture
        or input_identity.get("specification_sha256") != candidate.source_spec_sha256
        or not isinstance(structured_evidence, list)
        or not structured_evidence
    ):
        raise WorkflowSimulationError("Structured fixture run is not input-bound.")
    fixture_files = dict(fixture.files)
    for raw in structured_evidence:
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            raise WorkflowSimulationError("Structured fixture evidence is invalid.")
        relative = str(raw["path"]).split("/evidence/", 1)
        if len(relative) != 2:
            raise WorkflowSimulationError("Structured fixture evidence path is invalid.")
        fixture_path = f"evidence/{relative[1]}"
        content = fixture_files.get(fixture_path)
        if (
            content is None
            or raw.get("sha256") != hashlib.sha256(content).hexdigest().upper()
        ):
            raise WorkflowSimulationError("Structured fixture evidence digest drifted.")

    claims = tuple(
        Claim(
            claim_id=f"CLM-{requirement_id}",
            statement=str(item["statement"]),
            requirement_ids=(requirement_id,),
            acceptance_criteria=_fixture_acceptance_ids(item),
            state=ClaimState.VERIFIED,
            criticality=ClaimCriticality.MUST,
            confidence=Confidence.A,
        )
        for requirement_id, item in zip(requirement_ids, normalized_requirements, strict=True)
    )
    evidence_references = tuple(
        ArtifactReference(
            f"workflow/fixture/{path}",
            hashlib.sha256(content).hexdigest().upper(),
        )
        for path, content in fixture.files
        if path.startswith("evidence/")
    )
    if not evidence_references:
        raise WorkflowSimulationError("Workflow fixture has no M3 evidence bytes.")
    record = EvidenceRecord(
        evidence_id="EV-FIXTURE-SOURCE-REVIEW",
        claim_ids=tuple(item.claim_id for item in claims),
        evidence_type=EvidenceType.SOURCE_REVIEW,
        status=EvidenceStatus.PASS,
        command=(
            "sdaqf",
            "workflow",
            "simulate",
            fixture.project_fixture,
            str(structured.get("run_id")),
        ),
        environment=(("fixture", fixture.project_fixture), ("mode", "offline")),
        commit=candidate.git_head,
        repository_digest=candidate.repository_digest,
        artifacts=evidence_references,
        recorded_at="2026-08-01T00:00:00+00:00",
    )
    ledger = EvidenceLedger(
        baseline_id=baseline_id,
        source_spec_sha256=candidate.source_spec_sha256,
        git_head=candidate.git_head,
        repository_digest=candidate.repository_digest,
        claims=claims,
        evidence=(record,),
        diff_review_evidence_id=record.evidence_id,
    )
    if parse_evidence_ledger(ledger.to_dict()) != ledger:
        raise WorkflowSimulationError("Fixture M3 Evidence Ledger did not round trip.")
    target = root / "workflow" / "simulation" / "fixture-evidence-ledger.json"
    ExclusiveWorkflowArtifactStore(root).publish(
        target,
        (json.dumps(ledger.to_dict(), indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    return artifact_reference_for(root, target)


def _fixture_acceptance_ids(item: dict[str, object]) -> tuple[str, ...]:
    """Parse exact normalized acceptance identities without trusting object shape."""

    raw = item.get("acceptance_criteria")
    if not isinstance(raw, list):
        raise WorkflowSimulationError(
            "Workflow fixture acceptance criteria are invalid."
        )
    result = tuple(
        str(value["id"])
        for value in raw
        if isinstance(value, dict) and isinstance(value.get("id"), str)
    )
    if len(result) != len(raw):
        raise WorkflowSimulationError(
            "Workflow fixture acceptance identities are invalid."
        )
    return result


def _measurement_payload(
    measurements: tuple[WorkflowMeasurement, ...],
) -> dict[str, dict[str, dict[str, object]]]:
    """Group the exact native State values without synthesizing any metric."""

    if tuple(item.name for item in measurements) != WORKFLOW_MEASUREMENT_NAMES:
        raise WorkflowSimulationError(
            "Native measurements must be the exact M8-D7 sequence."
        )
    grouped: dict[str, dict[str, dict[str, object]]] = {}
    for measurement in measurements:
        group, separator, name = measurement.name.partition(".")
        if not separator or not group or not name:
            raise WorkflowSimulationError("Native measurement name is not grouped.")
        payload = measurement.to_dict()
        payload.pop("name")
        grouped.setdefault(group, {})[name] = payload
    return {group: dict(sorted(values.items())) for group, values in sorted(grouped.items())}


def _fixture(scenario: str) -> str:
    if scenario == "ui-observation-unavailable":
        return "ui-issue-tracker"
    if scenario.startswith("approval-") or scenario in {
        "ambiguous-external-effect",
        "stale-candidate",
    }:
        return "secure-export"
    return "offline-config"


def _load_fixture_bundle(project_fixture: str) -> WorkflowFixtureBundle:
    """Load one approved complete fixture root and derive its sole identity."""

    expected_id = _FIXTURE_PROJECTS.get(project_fixture)
    if expected_id is None:
        raise WorkflowSimulationError("Workflow fixture project is unsupported.")
    fixture_root = _FIXTURE_ROOT / project_fixture
    if not fixture_root.is_dir() or fixture_root.is_symlink():
        raise WorkflowSimulationError("Workflow fixture root is unavailable or linked.")
    entries: list[tuple[str, bytes]] = []
    folded_paths: set[str] = set()
    for path in fixture_root.rglob("*"):
        if path.is_symlink():
            raise WorkflowSimulationError("Workflow fixture contains a linked path.")
        if not path.is_file():
            continue
        relative = path.relative_to(fixture_root).as_posix()
        folded = relative.casefold()
        if folded in folded_paths:
            raise WorkflowSimulationError("Workflow fixture contains a path case collision.")
        folded_paths.add(folded)
        entries.append((relative, path.read_bytes()))
    entries.sort(key=lambda item: (item[0].casefold(), item[0]))
    if not {path for path, _ in entries} >= _FIXTURE_REQUIRED_PATHS:
        raise WorkflowSimulationError("Workflow fixture omits a required native input.")
    digest = hashlib.sha256(b"M8-FIXTURE-BUNDLE\0")
    for relative, body in entries:
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)
    fixture_bundle_id = f"M8-FIXTURE-BUNDLE-{digest.hexdigest().upper()}"
    if fixture_bundle_id != expected_id:
        raise WorkflowSimulationError("Workflow fixture bundle identity drifted.")
    return WorkflowFixtureBundle(
        project_fixture=project_fixture,
        relative_root=f"evals/projects/{project_fixture}",
        fixture_bundle_id=fixture_bundle_id,
        files=tuple(entries),
    )
