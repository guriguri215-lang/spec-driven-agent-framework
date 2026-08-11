"""Side-effect-free deterministic M8 Integrated Plan construction."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path, PurePosixPath

from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.adapters.workflow import ExclusiveWorkflowArtifactStore, SystemWorkflowClock
from sdaqf.application.baselines import BaselineContractError, load_baseline
from sdaqf.application.context_contracts import (
    ContextContractError,
    LoadedContextArtifact,
    canonical_json_bytes,
    load_context_artifact,
)
from sdaqf.application.context_selection import ContextSnapshotService
from sdaqf.application.requirements_gate import RequirementsGateService
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    SchedulerContractError,
    load_scheduler_artifact,
)
from sdaqf.application.solver import SolverService
from sdaqf.application.solver_contracts import (
    SolverContractError,
    load_solver_artifact,
    solver_capability_token,
)
from sdaqf.application.tooling import ToolContractError, load_tool_registry
from sdaqf.application.workflow_contracts import (
    LARGE_ARTIFACT_BYTES,
    LoadedWorkflowArtifact,
    WorkflowContractError,
    artifact_from_value,
    load_workflow_artifact,
    serialize_workflow_artifact,
    verify_workflow_reference,
)
from sdaqf.domain.context import (
    SENSITIVITY_RANK,
    ContextArtifactType,
    ContextGraph,
    ContextQuery,
    ContextSelection,
    ContextSnapshot,
)
from sdaqf.domain.models import GateResult
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity
from sdaqf.domain.requirements import RequirementBaseline
from sdaqf.domain.scheduler import (
    EffectKind,
    SchedulerArtifactType,
    SchedulerBudget,
    TaskGraph,
    TaskKind,
    TaskState,
)
from sdaqf.domain.solver import (
    LoadedSolverArtifact,
    SolverArtifactType,
    SolverRegistry,
    SolverRequest,
)
from sdaqf.domain.tooling import ApprovalRequirement, ToolRegistry
from sdaqf.domain.workflow import (
    CompletionProfile,
    DevelopmentIntent,
    IntegratedPlan,
    IntegratedPlanTask,
    IntentTaskLink,
    NativeArtifactBinding,
    ProtectedEffect,
    WorkflowArtifactType,
    WorkflowDecision,
    WorkflowDecisionKind,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowOutcome,
    WorkflowPublicationObservation,
    WorkflowState,
)
from sdaqf.ports.context import BudgetEstimator, ContextSourceReader
from sdaqf.ports.workflow import WorkflowPublicationVerifier


class WorkflowPlanningError(WorkflowContractError):
    """Validated native inputs cannot produce the proposed Integrated Plan."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "blocking-diagnostic",
        subject_kind: str = "plan",
        subject_id: str = "M8-PLAN-PROPOSAL",
        references: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.subject_kind = subject_kind
        self.subject_id = subject_id
        self.references = references

    def to_dict(self) -> dict[str, object]:
        """Return one exact deterministic rejection decision."""

        return {
            "kind": "excluded",
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "reason_code": self.reason_code,
            "references": list(self.references),
            "blocking": True,
        }


class _PinnedContextCandidateVerifier:
    """Adapt one pinned M8 observation to the narrower M5 verifier port."""

    def __init__(
        self,
        verifier: WorkflowPublicationVerifier,
        observation: WorkflowPublicationObservation,
        scheduler_state: Path,
        expected: CandidateIdentity,
    ) -> None:
        self._verifier = verifier
        self._observation = observation
        self._scheduler_state = scheduler_state
        self._expected = expected

    def verify(self, repository_root: Path, expected: CandidateIdentity) -> None:
        if expected != self._expected:
            raise RuntimeError("Pinned Context Candidate identity changed.")
        self._verifier.revalidate(
            repository_root,
            self._observation,
            scheduler_state=self._scheduler_state,
        )


class IntegratedPlanner:
    """Validate native authorities and deterministically construct one Plan."""

    def __init__(
        self,
        candidate_verifier: WorkflowPublicationVerifier,
        source_reader: ContextSourceReader,
        estimator: BudgetEstimator,
    ) -> None:
        self._candidate_verifier = candidate_verifier
        self._source_reader = source_reader
        self._estimator = estimator

    def plan(
        self,
        intent_artifact: LoadedWorkflowArtifact,
        intent_reference: ArtifactReference,
        root: Path,
        scheduler_state: Path,
        *,
        owner_root: Path | None = None,
        publication_observation: WorkflowPublicationObservation | None = None,
        predecessor_scheduler_state: Path | None = None,
    ) -> LoadedWorkflowArtifact:
        """Return a Plan without publishing, ticking, solving, or consuming approval."""

        if intent_artifact.artifact_type is not WorkflowArtifactType.DEVELOPMENT_INTENT:
            raise WorkflowPlanningError("Integrated planning requires Development Intent.")
        intent = intent_artifact.value
        assert isinstance(intent, DevelopmentIntent)
        has_predecessor = intent.predecessor_plan_id is not None
        if has_predecessor != (predecessor_scheduler_state is not None):
            raise WorkflowPlanningError(
                "Predecessor scheduler state is required exactly for a successor Intent."
            )
        if predecessor_scheduler_state is not None:
            try:
                predecessor_resolved = predecessor_scheduler_state.resolve(strict=True)
                successor_resolved = scheduler_state.resolve(strict=True)
                if (
                    predecessor_resolved == successor_resolved
                    or os.path.samefile(predecessor_resolved, successor_resolved)
                ):
                    raise WorkflowPlanningError(
                        "Successor and predecessor scheduler states must be distinct databases."
                    )
            except OSError as exc:
                raise WorkflowPlanningError(
                    "Predecessor scheduler state is unavailable."
                ) from exc
        scheduler = SQLiteSchedulerStore(scheduler_state, root)
        scheduler.validate()
        scheduler.require_workflow_authority()
        publication_scheduler_state = (
            scheduler_state
            if predecessor_scheduler_state is None
            else predecessor_scheduler_state
        )
        observation = self._verify_candidate(
            root,
            intent,
            publication_scheduler_state,
            publication_observation,
            require_scheduler_candidate=predecessor_scheduler_state is None,
        )
        intent_binding = NativeArtifactBinding(
            artifact_type=WorkflowArtifactType.DEVELOPMENT_INTENT.value,
            artifact_id=intent_artifact.artifact_id,
            reference=intent_reference,
            required=True,
        )
        intent_path = verify_workflow_reference(root, intent_binding)
        loaded_intent = load_workflow_artifact_exact(intent_path)
        if loaded_intent.artifact_id != intent_artifact.artifact_id:
            raise WorkflowPlanningError("Development Intent reference drifted.")

        baseline = self._validate_baseline(intent, root)
        requirements_gate = RequirementsGateService().evaluate(baseline)
        graph_artifact, query_artifact, selection_artifact, snapshot_artifact = (
            self._validate_context(
                intent,
                root,
                owner_root,
                scheduler_state=publication_scheduler_state,
                publication_observation=observation,
            )
        )
        task_graph_artifact = self._validate_task_graph(intent, root)
        solver_registry, solver_requests = self._validate_solver(intent, root)
        predecessor_outcome = self._validate_predecessor(
            intent,
            root,
            scheduler_state
            if predecessor_scheduler_state is None
            else predecessor_scheduler_state,
            _publication_observation=observation,
        )
        graph = graph_artifact.value
        query = query_artifact.value
        selection = selection_artifact.value
        snapshot = snapshot_artifact.value
        task_graph = task_graph_artifact.value
        assert isinstance(graph, ContextGraph)
        assert isinstance(query, ContextQuery)
        assert isinstance(selection, ContextSelection)
        assert isinstance(snapshot, ContextSnapshot)
        assert isinstance(task_graph, TaskGraph)
        successor_native = scheduler.status()
        successor_state = successor_native.value
        from sdaqf.domain.scheduler import SchedulerState

        assert isinstance(successor_state, SchedulerState)
        if (
            successor_state.graph_id != task_graph_artifact.artifact_id
            or successor_state.candidate != intent.candidate
        ):
            raise WorkflowPlanningError(
                "Successor M6 scheduler authority is stale for the Intent."
            )

        links = {item.task_id: item for item in intent.task_links}
        native_task_ids = {item.task_id for item in task_graph.tasks}
        if set(links) != native_task_ids:
            raise WorkflowPlanningError("Intent task links must cover the exact Task Graph.")
        self._validate_links(intent, baseline, graph, task_graph, solver_requests)
        self._validate_budget(intent.budget, task_graph.budget)
        self._validate_scope_and_capabilities(intent, task_graph, solver_requests)

        tasks = self._plan_tasks(task_graph, links)
        effects = self._protected_effects(task_graph, root, intent.task_graph.artifact_id)
        solver_sensitivity = tuple(
            artifact.value.sensitivity
            for artifact in (
                *(() if solver_registry is None else (solver_registry,)),
                *solver_requests,
            )
            if isinstance(artifact.value, (SolverRegistry, SolverRequest))
        )
        sensitivity = max(
            (
                intent.sensitivity,
                graph.sensitivity,
                selection.sensitivity,
                snapshot.sensitivity,
                *solver_sensitivity,
            ),
            key=lambda item: SENSITIVITY_RANK[item],
        )
        if SENSITIVITY_RANK[sensitivity] > SENSITIVITY_RANK[intent.clearance]:
            raise WorkflowPlanningError(
                "Selected native artifact exceeds Intent clearance.",
                reason_code="inside-prohibited-scope",
                subject_kind="sensitivity",
                references=tuple(item.artifact_id for item in intent.solver_requests),
            )
        if sensitivity.value == "secret-or-prohibited":
            raise WorkflowPlanningError(
                "Secret-or-prohibited native content cannot enter an Integrated Plan.",
                reason_code="inside-prohibited-scope",
                subject_kind="sensitivity",
            )
        decisions = self._decisions(
            intent,
            baseline,
            graph,
            selection,
            task_graph,
            solver_requests,
            effects,
            requirements_gate,
            predecessor_outcome,
        )
        plan = IntegratedPlan(
            intent=intent_binding,
            project_id=intent.project_id,
            candidate=intent.candidate,
            sensitivity=sensitivity,
            completion_profile=intent.completion_profile,
            specification=intent.specification,
            requirement_baseline_id=intent.requirement_baseline_id,
            requirement_baseline=intent.requirement_baseline,
            context_graph=intent.context_graph,
            context_query=intent.context_query,
            context_selection=intent.context_selection,
            context_snapshot=intent.context_snapshot,
            task_graph=intent.task_graph,
            solver_registry=intent.solver_registry,
            solver_requests=intent.solver_requests,
            tasks=tasks,
            protected_effects=effects,
            decisions=decisions,
            budget=task_graph.budget,
            required_gate_ids=intent.required_gate_ids,
            observation_slots=intent.observation_slots,
            ui_required=intent.ui_required,
            predecessor_plan_id=intent.predecessor_plan_id,
            predecessor_state_id=intent.predecessor_state_id,
            predecessor_outcome_id=intent.predecessor_outcome_id,
            predecessor_plan=intent.predecessor_plan,
            predecessor_state=intent.predecessor_state,
            predecessor_outcome=intent.predecessor_outcome,
        )
        self._verify_candidate(
            root,
            intent,
            publication_scheduler_state,
            observation,
            require_scheduler_candidate=predecessor_scheduler_state is None,
        )
        return artifact_from_value(WorkflowArtifactType.INTEGRATED_PLAN, plan)

    def publish_plan(
        self,
        intent_artifact: LoadedWorkflowArtifact,
        intent_reference: ArtifactReference,
        root: Path,
        scheduler_state: Path,
        output: Path,
        *,
        owner_root: Path | None = None,
        recorded_at: datetime | None = None,
        predecessor_scheduler_state: Path | None = None,
    ) -> LoadedWorkflowArtifact:
        """Derive, reserve, exclusively publish, and confirm one Plan receipt."""

        relative = _workflow_output_path(root, output)
        existing_plan_id: str | None = None
        existing_output = root.resolve(strict=True) / relative
        if existing_output.exists():
            try:
                existing_plan = load_workflow_artifact(
                    existing_output,
                    expected_type=WorkflowArtifactType.INTEGRATED_PLAN,
                )
            except (OSError, RuntimeError, WorkflowContractError) as exc:
                raise WorkflowPlanningError(
                    "Existing Plan output is not an exact workflow artifact."
                ) from exc
            existing_plan_id = existing_plan.artifact_id
        try:
            self._candidate_verifier.classify_output_paths(  # type: ignore[attr-defined]
                root,
                (relative,),
                scheduler_state=scheduler_state,
                plan_id=existing_plan_id,
            )
        except (OSError, RuntimeError) as exc:
            raise WorkflowPlanningError(
                "Plan output failed initial Git publication classification."
            ) from exc
        if intent_artifact.artifact_type is not WorkflowArtifactType.DEVELOPMENT_INTENT:
            raise WorkflowPlanningError("Integrated planning requires Development Intent.")
        intent = intent_artifact.value
        assert isinstance(intent, DevelopmentIntent)
        publication_scheduler_state = (
            scheduler_state
            if predecessor_scheduler_state is None
            else predecessor_scheduler_state
        )
        observation = self._verify_candidate(
            root,
            intent,
            publication_scheduler_state,
            require_scheduler_candidate=predecessor_scheduler_state is None,
        )
        plan_artifact = self.plan(
            intent_artifact,
            intent_reference,
            root,
            scheduler_state,
            owner_root=owner_root,
            publication_observation=observation,
            predecessor_scheduler_state=predecessor_scheduler_state,
        )
        if existing_plan_id is not None and existing_plan_id != plan_artifact.artifact_id:
            raise WorkflowPlanningError("Existing Plan output differs from the derived Plan.")
        plan = plan_artifact.value
        assert isinstance(plan, IntegratedPlan)
        store = SQLiteSchedulerStore(scheduler_state, root)
        store.validate()
        store.require_workflow_authority()
        native_artifact = store.status()
        native = native_artifact.value
        from sdaqf.domain.scheduler import SchedulerState

        assert isinstance(native, SchedulerState)
        if native.graph_id != plan.task_graph.artifact_id or native.candidate != plan.candidate:
            raise WorkflowPlanningError("M6 scheduler authority is stale for the Plan.")
        content = serialize_workflow_artifact(plan_artifact)
        idempotency_key = _plan_publication_idempotency(
            plan_artifact.artifact_id,
            intent_artifact.artifact_id,
            relative,
        )
        now = SystemWorkflowClock().now() if recorded_at is None else recorded_at
        predecessor_plan_id: str | None = None
        predecessor_terminal_event_head_id: str | None = None
        predecessor_state_id: str | None = None
        predecessor_outcome_id: str | None = None
        predecessor_head_identity: tuple[object, ...] | None = None
        if predecessor_scheduler_state is not None:
            assert plan.predecessor_plan_id is not None
            assert plan.predecessor_state_id is not None
            assert plan.predecessor_outcome_id is not None
            predecessor_store = SQLiteSchedulerStore(predecessor_scheduler_state, root)
            predecessor_store.validate()
            predecessor_store.require_workflow_authority()
            predecessor_head = predecessor_store.workflow_head(plan.predecessor_plan_id)
            from sdaqf.domain.scheduler import WorkflowEpochPhase

            if (
                predecessor_head is None
                or predecessor_head.phase is not WorkflowEpochPhase.TERMINAL_CONFIRMED
                or predecessor_head.workflow_state_id != plan.predecessor_state_id
                or predecessor_head.outcome_id != plan.predecessor_outcome_id
            ):
                raise WorkflowPlanningError(
                    "Direct predecessor terminal-head attestation is unavailable."
                )
            predecessor_plan_id = plan.predecessor_plan_id
            predecessor_terminal_event_head_id = predecessor_head.current_event_head_id
            predecessor_state_id = plan.predecessor_state_id
            predecessor_outcome_id = plan.predecessor_outcome_id
            predecessor_head_identity = (
                predecessor_head.current_event_head_id,
                predecessor_head.phase,
                predecessor_head.workflow_state_id,
                predecessor_head.outcome_id,
            )
        try:
            self._candidate_verifier.preflight_outputs(  # type: ignore[attr-defined]
                root,
                (
                    (
                        relative,
                        WorkflowArtifactType.INTEGRATED_PLAN.value,
                        plan_artifact.artifact_id,
                        "workflow-plan",
                    ),
                ),
                scheduler_state=scheduler_state,
                plan_id=plan_artifact.artifact_id,
            )
        except (OSError, RuntimeError) as exc:
            raise WorkflowPlanningError(
                "Plan output failed Git and M6 publication classification."
            ) from exc
        if predecessor_scheduler_state is not None:
            assert predecessor_plan_id is not None
            predecessor_store = SQLiteSchedulerStore(predecessor_scheduler_state, root)
            predecessor_store.validate()
            current_predecessor_head = predecessor_store.workflow_head(predecessor_plan_id)
            if current_predecessor_head is None or (
                current_predecessor_head.current_event_head_id,
                current_predecessor_head.phase,
                current_predecessor_head.workflow_state_id,
                current_predecessor_head.outcome_id,
            ) != predecessor_head_identity:
                raise WorkflowPlanningError(
                    "Direct predecessor terminal head changed before successor epoch-open."
                )
        self._verify_candidate(
            root,
            intent,
            publication_scheduler_state,
            observation,
            require_scheduler_candidate=predecessor_scheduler_state is None,
        )
        head = store.open_workflow_epoch(
            plan_id=plan_artifact.artifact_id,
            candidate=plan.candidate,
            graph_id=native.graph_id,
            scheduler_state_id=native_artifact.artifact_id,
            scheduler_event_sequence=native.event_sequence,
            scheduler_event_head_id=store.current_event_head_id,
            idempotency_key=idempotency_key,
            producer="workflow-plan",
            artifact_id=plan_artifact.artifact_id,
            artifact_type=WorkflowArtifactType.INTEGRATED_PLAN.value,
            path=relative,
            recorded_at=now,
            predecessor_plan_id=predecessor_plan_id,
            predecessor_terminal_event_head_id=predecessor_terminal_event_head_id,
            predecessor_state_id=predecessor_state_id,
            predecessor_outcome_id=predecessor_outcome_id,
        )
        publication = ExclusiveWorkflowArtifactStore(root)
        publication.publish_idempotent(
            output,
            content,
            artifact_type=WorkflowArtifactType.INTEGRATED_PLAN.value,
            artifact_id=plan_artifact.artifact_id,
        )
        store.confirm_workflow_artifact(
            plan_id=plan_artifact.artifact_id,
            expected_head_id=head.current_event_head_id,
            artifact_id=plan_artifact.artifact_id,
            path=relative,
            idempotency_key=idempotency_key,
            recorded_at=now,
            artifact_type=WorkflowArtifactType.INTEGRATED_PLAN.value,
            producer="workflow-plan",
        )
        return plan_artifact

    def _verify_candidate(
        self,
        root: Path,
        intent: DevelopmentIntent,
        scheduler_state: Path,
        observation: WorkflowPublicationObservation | None = None,
        *,
        require_scheduler_candidate: bool = True,
    ) -> WorkflowPublicationObservation:
        try:
            if observation is None:
                observed = self._candidate_verifier.observe(
                    root,
                    intent.candidate,
                    scheduler_state=scheduler_state,
                )
                if require_scheduler_candidate and observed.receipts.candidate != intent.candidate:
                    raise RuntimeError("M6 scheduler Candidate differs from Intent.")
                return observed
            if require_scheduler_candidate and observation.receipts.candidate != intent.candidate:
                raise RuntimeError("Pinned publication Candidate differs from Intent.")
            self._candidate_verifier.revalidate(
                root,
                observation,
                scheduler_state=scheduler_state,
            )
            return observation
        except (OSError, RuntimeError) as exc:
            raise WorkflowPlanningError(
                "Current repository Candidate does not match Development Intent.",
                reason_code="stale-context",
                subject_kind="candidate",
                subject_id=f"CANDIDATE-{intent.candidate.repository_digest}",
            ) from exc

    @staticmethod
    def _validate_baseline(intent: DevelopmentIntent, root: Path) -> RequirementBaseline:
        if intent.specification.sha256 != intent.candidate.source_spec_sha256:
            raise WorkflowPlanningError("Specification digest does not match Candidate identity.")
        specification = NativeArtifactBinding(
            "specification",
            f"SPEC-{intent.specification.sha256}",
            intent.specification,
            True,
        )
        verify_workflow_reference(root, specification, maximum_bytes=2 * 1024 * 1024)
        baseline_binding = NativeArtifactBinding(
            "requirement-baseline",
            intent.requirement_baseline_id,
            intent.requirement_baseline,
            True,
        )
        baseline_path = verify_workflow_reference(root, baseline_binding)
        try:
            baseline = load_baseline(baseline_path)
        except BaselineContractError as exc:
            raise WorkflowPlanningError("Requirement Baseline is invalid.") from exc
        if (
            baseline.baseline_id != intent.requirement_baseline_id
            or baseline.source.sha256 != intent.candidate.source_spec_sha256
        ):
            raise WorkflowPlanningError("Requirement Baseline identity does not match Intent.")
        return baseline

    def _validate_context(
        self,
        intent: DevelopmentIntent,
        root: Path,
        owner_root: Path | None,
        *,
        scheduler_state: Path | None = None,
        publication_observation: WorkflowPublicationObservation | None = None,
    ) -> tuple[
        LoadedContextArtifact,
        LoadedContextArtifact,
        LoadedContextArtifact,
        LoadedContextArtifact,
    ]:
        expected = (
            (intent.context_graph, ContextArtifactType.GRAPH),
            (intent.context_query, ContextArtifactType.QUERY),
            (intent.context_selection, ContextArtifactType.SELECTION),
            (intent.context_snapshot, ContextArtifactType.SNAPSHOT),
        )
        loaded: list[LoadedContextArtifact] = []
        try:
            for binding, artifact_type in expected:
                if binding.artifact_type != artifact_type.value:
                    raise WorkflowPlanningError("Intent Context binding type is incorrect.")
                path = verify_workflow_reference(root, binding)
                artifact = load_context_artifact(path, expected_type=artifact_type)
                if artifact.artifact_id != binding.artifact_id:
                    raise WorkflowPlanningError("Intent Context identity drifted.")
                loaded.append(artifact)
        except ContextContractError as exc:
            raise WorkflowPlanningError("Intent Context artifact is invalid.") from exc
        graph_artifact, query_artifact, selection_artifact, snapshot_artifact = loaded
        graph = graph_artifact.value
        query = query_artifact.value
        selection = selection_artifact.value
        snapshot = snapshot_artifact.value
        assert isinstance(graph, ContextGraph)
        assert isinstance(query, ContextQuery)
        assert isinstance(selection, ContextSelection)
        assert isinstance(snapshot, ContextSnapshot)
        if any(
            value.candidate != intent.candidate for value in (graph, query, selection, snapshot)
        ):
            raise WorkflowPlanningError("Context candidate does not match Intent.")
        if (
            query.graph_id != graph_artifact.artifact_id
            or selection.graph_id != graph_artifact.artifact_id
            or selection.query_id != query_artifact.artifact_id
            or snapshot.graph_id != graph_artifact.artifact_id
            or snapshot.query_id != query_artifact.artifact_id
            or snapshot.selection_id != selection_artifact.artifact_id
        ):
            raise WorkflowPlanningError("Context lineage is inconsistent.")
        try:
            if scheduler_state is None or publication_observation is None:
                raise WorkflowPlanningError(
                    "Context replay requires one pinned publication observation."
                )
            reproduced = ContextSnapshotService(
                self._source_reader,
                _PinnedContextCandidateVerifier(
                    self._candidate_verifier,
                    publication_observation,
                    scheduler_state,
                    intent.candidate,
                ),
                self._estimator,
            ).build(
                graph_artifact,
                selection_artifact,
                repository_root=root,
                owner_root=owner_root,
            )
        except (ContextContractError, OSError, RuntimeError) as exc:
            raise WorkflowPlanningError(
                "Context Snapshot failed current source re-observation.",
                reason_code="stale-context",
                subject_kind="context",
                subject_id=intent.context_snapshot.artifact_id,
                references=(intent.context_snapshot.artifact_id,),
            ) from exc
        if reproduced.artifact_id != snapshot_artifact.artifact_id:
            raise WorkflowPlanningError(
                "Context Snapshot no longer reproduces from current sources.",
                reason_code="stale-context",
                subject_kind="context",
                subject_id=intent.context_snapshot.artifact_id,
                references=(intent.context_snapshot.artifact_id,),
            )
        return graph_artifact, query_artifact, selection_artifact, snapshot_artifact

    @staticmethod
    def _validate_task_graph(
        intent: DevelopmentIntent,
        root: Path,
    ) -> LoadedSchedulerArtifact:
        if intent.task_graph.artifact_type != SchedulerArtifactType.TASK_GRAPH.value:
            raise WorkflowPlanningError("Intent Task Graph binding type is incorrect.")
        path = verify_workflow_reference(root, intent.task_graph)
        try:
            artifact = load_scheduler_artifact(
                path,
                expected_type=SchedulerArtifactType.TASK_GRAPH,
                root=root,
            )
        except SchedulerContractError as exc:
            raise WorkflowPlanningError("Intent Task Graph is invalid.") from exc
        graph = artifact.value
        assert isinstance(graph, TaskGraph)
        if artifact.artifact_id != intent.task_graph.artifact_id:
            raise WorkflowPlanningError("Intent Task Graph identity drifted.")
        if graph.candidate != intent.candidate:
            raise WorkflowPlanningError("Task Graph candidate does not match Intent.")
        context_ids = {item.artifact_id for item in graph.contexts}
        if intent.context_snapshot.artifact_id not in context_ids:
            raise WorkflowPlanningError("Task Graph does not bind the Intent Context Snapshot.")
        return artifact

    @staticmethod
    def _validate_solver(
        intent: DevelopmentIntent,
        root: Path,
    ) -> tuple[LoadedSolverArtifact | None, tuple[LoadedSolverArtifact, ...]]:
        if intent.solver_registry is None:
            return None, ()
        if intent.solver_registry.artifact_type != SolverArtifactType.REGISTRY.value:
            raise WorkflowPlanningError("Intent Solver Registry binding type is incorrect.")
        registry_path = verify_workflow_reference(root, intent.solver_registry)
        try:
            registry = load_solver_artifact(
                registry_path, expected_type=SolverArtifactType.REGISTRY
            )
        except SolverContractError as exc:
            raise WorkflowPlanningError("Intent Solver Registry is invalid.") from exc
        if registry.artifact_id != intent.solver_registry.artifact_id:
            raise WorkflowPlanningError("Intent Solver Registry identity drifted.")
        task_graph_path = verify_workflow_reference(root, intent.task_graph)
        result: list[LoadedSolverArtifact] = []
        for binding in intent.solver_requests:
            if binding.artifact_type != SolverArtifactType.REQUEST.value:
                raise WorkflowPlanningError("Intent Solver Request binding type is incorrect.")
            request_path = verify_workflow_reference(root, binding)
            try:
                request, _, _ = SolverService().validate_request(
                    request_path,
                    registry_path,
                    task_graph_path,
                    root,
                )
            except (SolverContractError, ValueError, OSError) as exc:
                raise WorkflowPlanningError("Intent Solver Request is invalid.") from exc
            if request.artifact_id != binding.artifact_id:
                raise WorkflowPlanningError("Intent Solver Request identity drifted.")
            value = request.value
            assert isinstance(value, SolverRequest)
            if value.candidate != intent.candidate:
                raise WorkflowPlanningError("Solver Request candidate does not match Intent.")
            result.append(request)
        return registry, tuple(result)

    def _validate_predecessor(
        self,
        intent: DevelopmentIntent,
        root: Path,
        scheduler_state: Path,
        *,
        _visited: frozenset[str] = frozenset(),
        _publication_observation: WorkflowPublicationObservation | None = None,
    ) -> WorkflowOutcome | None:
        identifiers = (
            intent.predecessor_plan_id,
            intent.predecessor_state_id,
            intent.predecessor_outcome_id,
        )
        bindings = (
            intent.predecessor_plan,
            intent.predecessor_state,
            intent.predecessor_outcome,
        )
        if not any((*identifiers, *bindings)):
            return None
        if any(item is None for item in (*identifiers, *bindings)):
            raise WorkflowPlanningError(
                "Candidate epoch predecessor requires exact Plan, State, and Outcome bindings."
            )
        assert intent.predecessor_plan is not None
        assert intent.predecessor_state is not None
        assert intent.predecessor_outcome is not None
        expected = (
            (intent.predecessor_plan, WorkflowArtifactType.INTEGRATED_PLAN),
            (intent.predecessor_state, WorkflowArtifactType.WORKFLOW_STATE),
            (intent.predecessor_outcome, WorkflowArtifactType.WORKFLOW_OUTCOME),
        )
        loaded: list[LoadedWorkflowArtifact] = []
        try:
            for binding, artifact_type in expected:
                if binding.artifact_type != artifact_type.value or not binding.required:
                    raise WorkflowPlanningError("Candidate predecessor binding is not exact.")
                path = verify_workflow_reference(root, binding, maximum_bytes=LARGE_ARTIFACT_BYTES)
                artifact = load_workflow_artifact(path, expected_type=artifact_type)
                if artifact.artifact_id != binding.artifact_id:
                    raise WorkflowPlanningError("Candidate predecessor identity drifted.")
                loaded.append(artifact)
        except (OSError, WorkflowContractError) as exc:
            if isinstance(exc, WorkflowPlanningError):
                raise
            raise WorkflowPlanningError("Candidate predecessor binding failed validation.") from exc
        plan_artifact, state_artifact, outcome_artifact = loaded
        prior_plan = plan_artifact.value
        prior_state = state_artifact.value
        prior_outcome = outcome_artifact.value
        assert isinstance(prior_plan, IntegratedPlan)
        assert isinstance(prior_state, WorkflowState)
        assert isinstance(prior_outcome, WorkflowOutcome)
        if plan_artifact.artifact_id in _visited or len(_visited) >= 64:
            raise WorkflowPlanningError("Predecessor lineage is cyclic or exceeds its bound.")
        if prior_plan.candidate == intent.candidate:
            raise WorkflowPlanningError("Candidate epoch must change the exact Candidate identity.")
        if (
            prior_state.plan_id != plan_artifact.artifact_id
            or prior_state.candidate != prior_plan.candidate
            or prior_state.sensitivity != prior_plan.sensitivity
            or prior_state.status is not TaskState.SUPERSEDED
        ):
            raise WorkflowPlanningError("Predecessor State is not the old superseded epoch.")
        latest_path = verify_workflow_reference(root, prior_state.latest_event)
        latest_artifact = load_workflow_artifact(
            latest_path,
            expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
        )
        latest = latest_artifact.value
        assert isinstance(latest, WorkflowEvent)
        if (
            latest_artifact.artifact_id != prior_state.latest_event.artifact_id
            or latest.cause is not WorkflowEventCause.PLAN_SUPERSEDED
            or latest.after_status is not TaskState.SUPERSEDED
        ):
            raise WorkflowPlanningError("Predecessor supersession Event is invalid.")
        # Import lazily because the runtime depends on the planner.  Reusing the
        # runtime's semantic replay keeps predecessor adoption subject to the
        # same Event/State authority as an ordinary status/resume operation.
        from sdaqf.application.workflow_runtime import (
            WorkflowRuntimeError,
            WorkflowRuntimeService,
        )

        try:
            predecessor_observation = _publication_observation or self._verify_candidate(
                root, intent, scheduler_state, require_scheduler_candidate=False
            )
            WorkflowRuntimeService(planner=self).status(
                state_artifact,
                plan_artifact,
                root,
                scheduler_state,
                publication_observation=predecessor_observation,
            )
        except (
            OSError,
            SchedulerContractError,
            WorkflowContractError,
            WorkflowRuntimeError,
        ) as exc:
            raise WorkflowPlanningError(
                "Predecessor supersession Event/State/native history is invalid."
            ) from exc
        scheduler = SQLiteSchedulerStore(scheduler_state, root)
        scheduler.validate()
        scheduler.require_workflow_authority()
        head = scheduler.workflow_head(plan_artifact.artifact_id)
        from sdaqf.domain.scheduler import WorkflowEpochPhase

        if (
            head is None
            or head.phase is not WorkflowEpochPhase.TERMINAL_CONFIRMED
            or head.terminal_at is None
            or not any(
                receipt.artifact_type == WorkflowArtifactType.WORKFLOW_STATE.value
                and receipt.artifact_id == state_artifact.artifact_id
                for receipt in head.receipts
            )
            or not any(
                receipt.artifact_type == WorkflowArtifactType.WORKFLOW_OUTCOME.value
                and receipt.artifact_id == outcome_artifact.artifact_id
                for receipt in head.receipts
            )
        ):
            raise WorkflowPlanningError("Predecessor lacks one published M6 terminal head.")
        from sdaqf.application.workflow_outcome import WorkflowOutcomeService

        expected_outcome = WorkflowOutcomeService(planner=self)._derive_validated(
            prior_plan,
            prior_state,
            plan_artifact.artifact_id,
            state_artifact.artifact_id,
            root,
            completed_at=head.terminal_at,
        )
        if expected_outcome.artifact_id != outcome_artifact.artifact_id:
            raise WorkflowPlanningError(
                "Predecessor Outcome does not completely and deterministically rederive."
            )
        nested_fields = (
            prior_plan.predecessor_plan_id,
            prior_plan.predecessor_state_id,
            prior_plan.predecessor_outcome_id,
            prior_plan.predecessor_plan,
            prior_plan.predecessor_state,
            prior_plan.predecessor_outcome,
        )
        if any(item is not None for item in nested_fields):
            prior_intent_path = verify_workflow_reference(
                root,
                prior_plan.intent,
                maximum_bytes=LARGE_ARTIFACT_BYTES,
            )
            prior_intent_artifact = load_workflow_artifact(
                prior_intent_path,
                expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
            )
            prior_intent = prior_intent_artifact.value
            assert isinstance(prior_intent, DevelopmentIntent)
            if (
                prior_intent_artifact.artifact_id != prior_plan.intent.artifact_id
                or nested_fields
                != (
                    prior_intent.predecessor_plan_id,
                    prior_intent.predecessor_state_id,
                    prior_intent.predecessor_outcome_id,
                    prior_intent.predecessor_plan,
                    prior_intent.predecessor_state,
                    prior_intent.predecessor_outcome,
                )
            ):
                raise WorkflowPlanningError("Predecessor Plan/Intent lineage fields drifted.")
            nested_outcome = self._validate_predecessor(
                prior_intent,
                root,
                scheduler_state,
                _visited=_visited | {plan_artifact.artifact_id},
                _publication_observation=predecessor_observation,
            )
            if (
                nested_outcome is None
                or prior_plan.predecessor_outcome_id is None
                or prior_plan.predecessor_outcome_id
                != prior_intent.predecessor_outcome_id
            ):
                raise WorkflowPlanningError("Predecessor recursive Outcome lineage drifted.")
        return prior_outcome

    @staticmethod
    def _validate_links(
        intent: DevelopmentIntent,
        baseline: RequirementBaseline,
        context_graph: ContextGraph,
        task_graph: TaskGraph,
        solver_requests: tuple[LoadedSolverArtifact, ...],
    ) -> None:
        requirements = {item.requirement_id: item for item in baseline.requirements}
        acceptance = {
            criterion.criterion_id
            for requirement in baseline.requirements
            for criterion in requirement.acceptance_criteria
        } | {item.criterion_id for item in baseline.source_acceptance_criteria}
        if not set(intent.required_requirement_ids) <= requirements.keys():
            raise WorkflowPlanningError("Intent references an unknown required requirement.")
        if not set(intent.required_acceptance_ids) <= acceptance:
            raise WorkflowPlanningError("Intent references an unknown acceptance criterion.")
        context_nodes = {item.node_id for item in context_graph.nodes}
        solver_ids = {item.artifact_id for item in solver_requests}
        tasks = {item.task_id: item for item in task_graph.tasks}
        for link in intent.task_links:
            if not set(link.requirement_ids) <= requirements.keys():
                raise WorkflowPlanningError("Task link references an unknown requirement.")
            if not set(link.acceptance_ids) <= acceptance:
                raise WorkflowPlanningError("Task link references unknown acceptance.")
            if not set(link.context_node_ids) <= context_nodes:
                raise WorkflowPlanningError("Task link references unknown Context.")
            if not set(link.solver_request_ids) <= solver_ids:
                raise WorkflowPlanningError("Task link references unknown Solver Request.")
            task = tasks[link.task_id]
            if task.kind.value == "solver" and not link.solver_request_ids:
                raise WorkflowPlanningError("Solver task lacks its Solver Request link.")
        mapped_requirements = {
            identifier for link in intent.task_links for identifier in link.requirement_ids
        }
        mapped_acceptance = {
            identifier for link in intent.task_links for identifier in link.acceptance_ids
        }
        if not set(intent.required_requirement_ids) <= mapped_requirements:
            raise WorkflowPlanningError("Required requirement is not mapped to a Task.")
        if not set(intent.required_acceptance_ids) <= mapped_acceptance:
            raise WorkflowPlanningError("Required acceptance is not mapped to a Task.")

    @staticmethod
    def _validate_budget(ceiling: SchedulerBudget, selected: SchedulerBudget) -> None:
        fields = (
            "max_agents",
            "max_concurrency",
            "max_dispatches",
            "max_retries",
            "max_wall_time_seconds",
            "max_tool_calls",
            "max_context_bytes_per_dispatch",
            "max_context_bytes_total",
            "max_solver_calls",
            "max_solver_steps",
        )
        if any(getattr(selected, field) > getattr(ceiling, field) for field in fields):
            raise WorkflowPlanningError(
                "Task Graph exceeds the Intent hard budget.",
                reason_code="budget-exceeded",
                subject_kind="budget",
            )
        effort = {"low": 0, "medium": 1, "high": 2}
        if effort[selected.max_reasoning_effort] > effort[ceiling.max_reasoning_effort]:
            raise WorkflowPlanningError(
                "Task Graph exceeds the Intent reasoning budget.",
                reason_code="budget-exceeded",
                subject_kind="budget",
            )
        if ceiling.cost_status == "available":
            if selected.cost_status != "available" or selected.currency != ceiling.currency:
                raise WorkflowPlanningError(
                    "Task Graph cost availability differs from Intent.",
                    reason_code="budget-exceeded",
                    subject_kind="cost",
                )
            assert selected.max_microunits is not None
            assert ceiling.max_microunits is not None
            if selected.max_microunits > ceiling.max_microunits:
                raise WorkflowPlanningError(
                    "Task Graph exceeds the Intent cost budget.",
                    reason_code="budget-exceeded",
                    subject_kind="cost",
                )

    @staticmethod
    def _validate_scope_and_capabilities(
        intent: DevelopmentIntent,
        graph: TaskGraph,
        solver_requests: tuple[LoadedSolverArtifact, ...] = (),
    ) -> None:
        requested_effects = set(intent.requested_effects)
        capabilities = set(intent.capabilities)
        authenticated_solver_tokens = {
            solver_capability_token(request)
            for artifact in solver_requests
            if isinstance((request := artifact.value), SolverRequest)
        }
        for task in graph.tasks:
            if task.effect_kind not in requested_effects:
                raise WorkflowPlanningError(
                    "Task effect was not requested by Intent.",
                    reason_code="outside-allowed-scope",
                    subject_kind="task",
                    subject_id=task.task_id,
                )
            required = set(task.required_capabilities)
            solver_tokens = (
                {item for item in required if item.startswith("m7-solver-v1@")}
                if task.kind is TaskKind.SOLVER
                else set()
            )
            if (
                not solver_tokens <= authenticated_solver_tokens
                or not (required - solver_tokens) <= capabilities
            ):
                raise WorkflowPlanningError(
                    "Task requires an unrequested capability.",
                    reason_code="unsupported-capability",
                    subject_kind="task",
                    subject_id=task.task_id,
                )
            for path in task.owned_paths:
                if any(_path_contains(blocked, path) for blocked in intent.prohibited_paths):
                    raise WorkflowPlanningError(
                        "Task owns a prohibited path.",
                        reason_code="inside-prohibited-scope",
                        subject_kind="task",
                        subject_id=task.task_id,
                        references=(path,),
                    )
                if intent.allowed_paths and not any(
                    _path_contains(allowed, path) for allowed in intent.allowed_paths
                ):
                    raise WorkflowPlanningError(
                        "Task owns a path outside Intent scope.",
                        reason_code="outside-allowed-scope",
                        subject_kind="task",
                        subject_id=task.task_id,
                        references=(path,),
                    )

    @staticmethod
    def _plan_tasks(
        graph: TaskGraph,
        links: dict[str, IntentTaskLink],
    ) -> tuple[IntegratedPlanTask, ...]:
        by_id = {item.task_id: item for item in graph.tasks}
        rank_cache: dict[str, int] = {}

        def rank(identifier: str) -> int:
            cached = rank_cache.get(identifier)
            if cached is not None:
                return cached
            dependencies = by_id[identifier].dependencies
            result = 0 if not dependencies else 1 + max(rank(item) for item in dependencies)
            rank_cache[identifier] = result
            return result

        phase = {
            "discovery": 0,
            "solver": 1,
            "implementation": 2,
            "test": 3,
            "tool": 3,
            "review": 4,
            "integration": 5,
            "handoff": 6,
        }
        planned = []
        for task in graph.tasks:
            link = links[task.task_id]
            planned.append(
                IntegratedPlanTask(
                    task_id=task.task_id,
                    phase=phase[task.kind.value],
                    topological_rank=rank(task.task_id),
                    wave=task.wave,
                    task_kind=task.kind.value,
                    dependencies=task.dependencies,
                    role_id=task.role_id,
                    context_snapshot_id=task.context_snapshot_id,
                    requirement_ids=link.requirement_ids,
                    acceptance_ids=link.acceptance_ids,
                    context_node_ids=link.context_node_ids,
                    solver_request_ids=link.solver_request_ids,
                    effect_kind=task.effect_kind,
                    approval_stops=task.approval_stops,
                    evidence_predicates=task.evidence_predicate,
                    terminal_predicates=task.terminal_predicate,
                )
            )
        return tuple(
            sorted(
                planned,
                key=lambda item: (
                    item.phase,
                    item.topological_rank,
                    item.wave,
                    item.task_kind,
                    item.task_id,
                ),
            )
        )

    @staticmethod
    def _protected_effects(
        graph: TaskGraph,
        root: Path,
        graph_id: str,
    ) -> tuple[ProtectedEffect, ...]:
        registry_binding = NativeArtifactBinding(
            "tool-registry",
            f"TOOL-REGISTRY-{graph.tool_registry.sha256}",
            graph.tool_registry,
            True,
        )
        registry_path = verify_workflow_reference(root, registry_binding)
        try:
            registry = load_tool_registry(registry_path)
        except (ToolContractError, OSError) as exc:
            raise WorkflowPlanningError(
                "Task Graph Tool Registry is invalid.",
                reason_code="unsupported-capability",
                subject_kind="tool-registry",
                subject_id=registry_binding.artifact_id,
            ) from exc
        assert isinstance(registry, ToolRegistry)
        effects = []
        for task in graph.tasks:
            tools = []
            for tool_name in task.required_tools:
                tool = registry.by_name(tool_name)
                if tool is None:
                    raise WorkflowPlanningError(
                        "Task references an unavailable Tool policy.",
                        reason_code="unsupported-capability",
                        subject_kind="task",
                        subject_id=task.task_id,
                        references=(registry_binding.artifact_id,),
                    )
                tools.append(tool)
            protected_path = any(
                _path_contains(protected, owned)
                for tool in tools
                for protected in tool.protected_paths
                for owned in task.owned_paths
            )
            network_destinations = tuple(
                sorted({destination for tool in tools for destination in tool.network_destinations})
            )
            approval_types = set(task.approval_stops)
            for tool in tools:
                if tool.owner_approval in {
                    ApprovalRequirement.REQUIRED,
                    ApprovalRequirement.MAY_BE_REQUIRED,
                }:
                    approval_types.add("owner")
                if tool.technical_approval in {
                    ApprovalRequirement.REQUIRED,
                    ApprovalRequirement.MAY_BE_REQUIRED,
                }:
                    approval_types.add("technical-sandbox")
                if tool.owner_approval is ApprovalRequirement.PROHIBITED:
                    raise WorkflowPlanningError(
                        "Tool policy prohibits the proposed protected effect.",
                        reason_code="inside-prohibited-scope",
                        subject_kind="task",
                        subject_id=task.task_id,
                        references=(registry_binding.artifact_id,),
                    )
            protected = (
                task.effect_kind is not EffectKind.READ_ONLY
                or bool(task.approval_stops)
                or protected_path
                or bool(network_destinations)
                or bool(approval_types)
            )
            if not protected:
                continue
            if len(approval_types) > 2:
                raise WorkflowPlanningError(
                    "Protected effect exceeds the approval-type bound.",
                    reason_code="approval-not-authority",
                    subject_kind="task",
                    subject_id=task.task_id,
                )
            reversible = (
                task.effect_kind in {EffectKind.READ_ONLY, EffectKind.LOCAL_WRITE}
                and not network_destinations
            )
            ambiguous_on_failure = task.effect_kind in {
                EffectKind.EXTERNAL,
                EffectKind.DESTRUCTIVE,
            } or bool(network_destinations)
            content = {
                "task_id": task.task_id,
                "effect_kind": task.effect_kind.value,
                "target_paths": list(task.owned_paths),
                "network_destinations": list(network_destinations),
                "reversible": reversible,
                "ambiguous_on_failure": ambiguous_on_failure,
                "approval_types": sorted(approval_types),
                "idempotency_scope": "native-m6-lease",
                "graph_id": graph_id,
                "graph_candidate": graph.candidate.to_dict(),
                "tool_registry_sha256": graph.tool_registry.sha256,
            }
            digest = hashlib.sha256(canonical_json_bytes(content)).hexdigest().upper()
            effects.append(
                ProtectedEffect(
                    effect_id=f"M8-EFFECT-{digest}",
                    task_id=task.task_id,
                    effect_kind=task.effect_kind,
                    target_paths=task.owned_paths,
                    network_destinations=network_destinations,
                    reversible=reversible,
                    ambiguous_on_failure=ambiguous_on_failure,
                    approval_types=tuple(sorted(approval_types)),
                    idempotency_scope="native-m6-lease",
                    effect_digest=digest,
                )
            )
        return tuple(sorted(effects, key=lambda item: item.effect_id))

    @staticmethod
    def _decisions(
        intent: DevelopmentIntent,
        baseline: RequirementBaseline,
        context_graph: ContextGraph,
        selection: ContextSelection,
        task_graph: TaskGraph,
        solver_requests: tuple[LoadedSolverArtifact, ...],
        effects: tuple[ProtectedEffect, ...],
        requirements_gate: GateResult,
        predecessor_outcome: WorkflowOutcome | None = None,
    ) -> tuple[WorkflowDecision, ...]:
        decisions: list[WorkflowDecision] = []
        if not requirements_gate.passed:
            decisions.append(
                WorkflowDecision(
                    "gate",
                    "G1",
                    WorkflowDecisionKind.UNCERTAINTY,
                    "blocking-diagnostic",
                    (intent.requirement_baseline_id,),
                    True,
                )
            )
        for requirement_id in intent.required_requirement_ids:
            decisions.append(
                WorkflowDecision(
                    "requirement",
                    requirement_id,
                    WorkflowDecisionKind.SELECTED,
                    "required-by-requirement",
                    (intent.requirement_baseline_id,),
                    False,
                )
            )
        for task in task_graph.tasks:
            decisions.append(
                WorkflowDecision(
                    "task",
                    task.task_id,
                    WorkflowDecisionKind.SELECTED,
                    "required-by-intent",
                    tuple(sorted((*task.dependencies, intent.task_graph.artifact_id))),
                    False,
                )
            )
            if task.kind.value == "review":
                decisions.append(
                    WorkflowDecision(
                        "task",
                        task.task_id,
                        WorkflowDecisionKind.SELECTED,
                        "review-separation",
                        tuple(sorted(task.review_targets)),
                        False,
                    )
                )
        for selected in selection.selected:
            decisions.append(
                WorkflowDecision(
                    "context",
                    selected.node_id,
                    WorkflowDecisionKind.SELECTED,
                    "required-context",
                    (intent.context_snapshot.artifact_id,),
                    False,
                )
            )
        for solver in solver_requests:
            decisions.append(
                WorkflowDecision(
                    "solver",
                    solver.artifact_id,
                    WorkflowDecisionKind.SELECTED,
                    "solver-justified",
                    (intent.task_graph.artifact_id,),
                    False,
                )
            )
        for gate_id in intent.required_gate_ids:
            decisions.append(
                WorkflowDecision(
                    "gate",
                    gate_id,
                    WorkflowDecisionKind.SELECTED,
                    "gate-prerequisite",
                    (),
                    False,
                )
            )
        if intent.completion_profile is not CompletionProfile.PLAN_ONLY:
            decisions.append(
                WorkflowDecision(
                    "handoff",
                    "M8-HANDOFF-REQUIRED",
                    WorkflowDecisionKind.SELECTED,
                    "handoff-required",
                    (),
                    False,
                )
            )
        if not intent.ui_required:
            decisions.append(
                WorkflowDecision(
                    "ui",
                    "M8-UI-NOT-APPLICABLE",
                    WorkflowDecisionKind.EXCLUDED,
                    "ui-not-applicable",
                    (),
                    False,
                )
            )
        for effect in effects:
            if effect.approval_types:
                decisions.append(
                    WorkflowDecision(
                        "approval",
                        effect.effect_id,
                        WorkflowDecisionKind.EXCLUDED,
                        "approval-not-authority",
                        (effect.task_id,),
                        False,
                    )
                )
        for diagnostic in baseline.diagnostics:
            if diagnostic.status == "open":
                decisions.append(
                    WorkflowDecision(
                        "diagnostic",
                        diagnostic.diagnostic_id,
                        WorkflowDecisionKind.UNCERTAINTY,
                        "blocking-diagnostic",
                        tuple(sorted(diagnostic.requirement_ids)),
                        True,
                    )
                )
        for contradiction in selection.unresolved_contradiction_ids:
            decisions.append(
                WorkflowDecision(
                    "context",
                    contradiction,
                    WorkflowDecisionKind.UNCERTAINTY,
                    "unresolved-contradiction",
                    (intent.context_selection.artifact_id,),
                    True,
                )
            )
        if predecessor_outcome is not None:
            for ambiguity in predecessor_outcome.ambiguities:
                decisions.append(
                    WorkflowDecision(
                        "predecessor-ambiguity",
                        ambiguity,
                        WorkflowDecisionKind.UNCERTAINTY,
                        "external-effect-ambiguous",
                        (intent.predecessor_outcome_id or "",),
                        True,
                    )
                )
        if task_graph.budget.cost_status == "not_available":
            decisions.append(
                WorkflowDecision(
                    "cost",
                    "M8-COST-NOT-AVAILABLE",
                    WorkflowDecisionKind.UNCERTAINTY,
                    "cost-not-available",
                    (intent.task_graph.artifact_id,),
                    False,
                )
            )
        for excluded in selection.excluded:
            if excluded.node_id not in {item.node_id for item in context_graph.nodes}:
                raise WorkflowPlanningError("Context exclusion references an unknown node.")
            decisions.append(
                WorkflowDecision(
                    "context",
                    excluded.node_id,
                    WorkflowDecisionKind.EXCLUDED,
                    "optional-context-not-selected",
                    (intent.context_selection.artifact_id,),
                    False,
                )
            )
        return tuple(
            sorted(
                decisions,
                key=lambda item: (
                    item.subject_kind,
                    item.subject_id,
                    item.kind.value,
                    item.reason_code,
                    item.references,
                ),
            )
        )


def load_workflow_artifact_exact(path: Path) -> LoadedWorkflowArtifact:
    """Late import helper kept separate for testable exact Intent replay."""

    from sdaqf.application.workflow_contracts import load_workflow_artifact

    return load_workflow_artifact(path, expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT)


def artifact_reference_for(root: Path, path: Path) -> ArtifactReference:
    """Return one exact relative reference after bounded regular-file checks."""

    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if (
        not resolved.is_relative_to(resolved_root)
        or not resolved.is_file()
        or resolved.is_symlink()
        or resolved.stat().st_size > LARGE_ARTIFACT_BYTES
    ):
        raise WorkflowPlanningError("Workflow input is outside its bounded root.")
    return ArtifactReference(
        resolved.relative_to(resolved_root).as_posix(),
        hashlib.sha256(resolved.read_bytes()).hexdigest().upper(),
    )


def _workflow_output_path(root: Path, output: Path) -> str:
    resolved_root = root.resolve(strict=True)
    candidate = output if output.is_absolute() else resolved_root / output
    lexical = Path(os.path.abspath(candidate))
    if not lexical.is_relative_to(resolved_root) or ".." in candidate.parts:
        raise WorkflowPlanningError("Workflow Plan output escapes its explicit root.")
    relative = lexical.relative_to(resolved_root)
    if (
        not relative.parts
        or relative.parts[0] != "workflow"
        or lexical.suffix.casefold() != ".json"
    ):
        raise WorkflowPlanningError("Workflow Plan output must be a JSON under workflow/.")
    return relative.as_posix()


def _plan_publication_idempotency(plan_id: str, intent_id: str, path: str) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {"plan_id": plan_id, "intent_id": intent_id, "output_path": path}
        )
    ).hexdigest().upper()
    return f"M8-IDEM-{digest}"


def _path_contains(parent: str, child: str) -> bool:
    parent_path = PurePosixPath(*(part.casefold() for part in PurePosixPath(parent).parts))
    child_path = PurePosixPath(*(part.casefold() for part in PurePosixPath(child).parts))
    return child_path == parent_path or parent_path in child_path.parents
