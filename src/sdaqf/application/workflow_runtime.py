"""Resumable one-tick M8 runtime over the authoritative M6 scheduler."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.adapters.scheduler import (
    MAX_EXPORT,
    SchedulerAdapterError,
    SchedulerTick,
    SQLiteSchedulerStore,
)
from sdaqf.adapters.workflow import (
    ExclusiveWorkflowArtifactStore,
    SystemWorkflowClock,
)
from sdaqf.application.baselines import load_baseline
from sdaqf.application.context_contracts import canonical_json_bytes, load_context_artifact
from sdaqf.application.context_quality import measure_context_quality
from sdaqf.application.contracts import (
    ContractError,
    load_json_object,
    parse_artifact_reference,
)
from sdaqf.application.evidence import load_evidence_ledger
from sdaqf.application.handoffs import load_automated_handoff
from sdaqf.application.quality_gates import (
    ImplementationEvidenceGateService,
    IndependentReviewGateService,
    load_independent_review,
)
from sdaqf.application.release_qa import ReleaseCandidateGateService, load_release_candidate
from sdaqf.application.scheduler import SchedulerService
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    bind_review_task_result_evidence,
    event_digest,
    load_task_agent_result,
    parse_scheduler_artifact_bytes,
    validate_reviewed_agent_identities,
)
from sdaqf.application.scheduler_contracts import (
    artifact_from_value as scheduler_artifact_from_value,
)
from sdaqf.application.skills import SkillContractError, resolve_skill_capabilities
from sdaqf.application.solver_contracts import load_solver_artifact
from sdaqf.application.ui_validation import (
    UiValidationService,
    load_manifest_ui,
    load_ui_validation,
)
from sdaqf.application.workflow_contracts import (
    LoadedWorkflowArtifact,
    WorkflowContractError,
    artifact_from_value,
    parse_workflow_artifact_bytes,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_explanation import WorkflowExplainer
from sdaqf.application.workflow_planning import IntegratedPlanner
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.context import (
    ContextArtifactType,
    ContextGraph,
    ContextQualityReport,
    ContextSelection,
    ContextSnapshot,
)
from sdaqf.domain.orchestration import AgentResult
from sdaqf.domain.quality import ArtifactReference, EvidenceLedger, HandoffStatus, IndependentReview
from sdaqf.domain.scheduler import (
    BudgetLedger,
    DispatchPhase,
    Lease,
    LeaseStatus,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerEvent,
    SchedulerState,
    TaskGraph,
    TaskKind,
    TaskOutcome,
    TaskState,
    WorkflowEpochPhase,
    WorktreeLease,
)
from sdaqf.domain.solver import SolverArtifactType, SolverVerification
from sdaqf.domain.workflow import (
    WORKFLOW_MEASUREMENT_NAMES,
    CompletionProfile,
    EffectDisposition,
    GateObservation,
    GateStatus,
    IntegratedPlan,
    MeasurementStatus,
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowBlocker,
    WorkflowDecisionKind,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowMeasurement,
    WorkflowPublicationObservation,
    WorkflowState,
    WorkflowTaskProjection,
    WorkflowTerminalObservation,
    WorkflowTerminalObservationCause,
)
from sdaqf.ports.scheduler import AgentHostPort
from sdaqf.ports.workflow import WorkflowArtifactStorePort, WorkflowClock


class WorkflowRuntimeError(WorkflowContractError):
    """One workflow transition failed closed before protected host dispatch."""


@dataclass(frozen=True, slots=True)
class WorkflowTransition:
    """Published M8 transition and unexecuted native host intents."""

    event: LoadedWorkflowArtifact
    state: LoadedWorkflowArtifact
    outgoing_intent_ids: tuple[str, ...]
    protected_effect_ids: tuple[str, ...]
    approval_ids: tuple[str, ...]
    host_dispatch_performed: bool = False
    outcome: LoadedWorkflowArtifact | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "event": self.event.to_dict(),
            "state": self.state.to_dict(),
            "outgoing_intent_ids": list(self.outgoing_intent_ids),
            "protected_effect_ids": list(self.protected_effect_ids),
            "approval_ids": list(self.approval_ids),
            "host_dispatch_performed": self.host_dispatch_performed,
            "outcome": None if self.outcome is None else self.outcome.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class NativeWorkflowObservations:
    """Strictly adopted M3/M7 observations found in accepted M6 results."""

    bindings: tuple[NativeArtifactBinding, ...]
    solver_verification_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    handoff_id: str | None
    handoff_status: str | None
    g2_passed: bool
    g3_passed: bool
    ui_observation_ids: tuple[str, ...] = ()
    release_candidate_ids: tuple[str, ...] = ()
    g4_result_ids: tuple[str, ...] = ()
    g4_passed: bool = False
    solver_status_counts: tuple[tuple[str, int], ...] = ()
    claim_count: int = 0
    verified_claim_count: int = 0
    unverified_claim_count: int = 0
    evidence_known_problem_count: int = 0
    missing_evidence_count: int = 0
    handoff_created_count: int = 0
    handoff_resume_failure_count: int = 0
    handoff_incomplete_item_count: int = 0
    handoff_open_decision_count: int = 0
    handoff_known_problem_count: int = 0
    covered_requirement_ids: tuple[str, ...] = ()
    requirement_coverage_available: bool = False


class WorkflowRuntimeService:
    """Advance M6 once and publish an immutable Event then State projection."""

    def __init__(
        self,
        clock: WorkflowClock | None = None,
        store: WorkflowArtifactStorePort | None = None,
        planner: IntegratedPlanner | None = None,
    ) -> None:
        self._clock = SystemWorkflowClock() if clock is None else clock
        self._store = store
        if planner is None:
            raise TypeError("Workflow runtime requires an explicit candidate-aware planner.")
        self._planner = planner

    def run(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        output_state: Path,
        output_event: Path,
        *,
        predecessor_scheduler_state: Path | None = None,
        messages: tuple[Path, ...] = (),
        agent_host: AgentHostPort | None = None,
    ) -> WorkflowTransition:
        """Start one Plan and optionally offer exact intents to an explicit host."""

        return self._transition(
            None,
            None,
            plan_artifact,
            root,
            scheduler_state,
            output_state,
            output_event,
            predecessor_scheduler_state=predecessor_scheduler_state,
            messages=messages,
            agent_host=agent_host,
        )

    def resume(
        self,
        prior_state_artifact: LoadedWorkflowArtifact,
        prior_state_binding: NativeArtifactBinding,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        output_state: Path,
        output_event: Path,
        *,
        predecessor_scheduler_state: Path | None = None,
        messages: tuple[Path, ...] = (),
        agent_host: AgentHostPort | None = None,
    ) -> WorkflowTransition:
        """Resume from an exact State/Event chain and at most one M6 tick."""

        return self._transition(
            prior_state_artifact,
            prior_state_binding,
            plan_artifact,
            root,
            scheduler_state,
            output_state,
            output_event,
            predecessor_scheduler_state=predecessor_scheduler_state,
            messages=messages,
            agent_host=agent_host,
        )

    def finalize_observation(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        observation: WorkflowTerminalObservation,
        output_event: Path,
        output_state: Path,
        output_outcome: Path,
        *,
        predecessor_scheduler_state: Path | None = None,
    ) -> WorkflowTransition:
        """Close one authenticated native observation through the M6 v2 epoch.

        The caller supplies a closed native cause and exact M6 identities, never
        a disposition or blocker.  This service owns the cause-to-State mapping,
        publishes a deterministic source transition when necessary, and then
        uses the ordinary terminal reserve/confirm path for the public triple.
        """

        _require_runtime_private_path(root, scheduler_state, existing=True)
        for target in (output_event, output_state, output_outcome):
            _require_runtime_private_path(root, target, existing=False)
        plan, _unused, publication_observation = self._validate_inputs(
            plan_artifact,
            None,
            root,
            scheduler_state,
            predecessor_scheduler_state=predecessor_scheduler_state,
        )
        store = SQLiteSchedulerStore(scheduler_state, root)
        store.validate()
        store.require_workflow_authority()
        native_artifact = store.status()
        native = native_artifact.value
        assert isinstance(native, SchedulerState)
        head = store.workflow_head(plan_artifact.artifact_id)
        if head is None:
            raise WorkflowRuntimeError("M6 workflow epoch is not open for this observation.")
        self._authenticate_terminal_observation(
            plan_artifact,
            plan,
            observation,
            store,
            native_artifact,
            native,
        )
        if observation.cause in {
            WorkflowTerminalObservationCause.COMPLETION_OBSERVED,
            WorkflowTerminalObservationCause.RECOVERED_COMPLETION,
        }:
            raise WorkflowRuntimeError(
                "Successful completion uses ordinary run/resume/recovery and Outcome publication."
            )

        source_event_path = output_event.with_name(
            f"{output_event.stem}-observation-source{output_event.suffix}"
        )
        source_state_path = output_state.with_name(
            f"{output_state.stem}-observation-source{output_state.suffix}"
        )
        for target in (source_event_path, source_state_path):
            _require_runtime_private_path(root, target, existing=False)
        relative_paths = {
            _output_reference(root, target, b"{}").path.casefold()
            for target in (
                source_event_path,
                source_state_path,
                output_event,
                output_state,
                output_outcome,
            )
        }
        if len(relative_paths) != 5:
            raise WorkflowRuntimeError("Observation finalization paths must be case-unique.")

        request_idempotency = _observation_idempotency(
            plan_artifact.artifact_id,
            observation,
        )
        if head.phase in {
            WorkflowEpochPhase.TERMINAL_RESERVED,
            WorkflowEpochPhase.TERMINAL_CONFIRMED,
        }:
            if head.producer != "workflow-outcome":
                raise WorkflowRuntimeError("M6 terminal authority rejects this observation.")
            source_receipt = next(
                (
                    item
                    for item in head.receipts
                    if item.artifact_type == WorkflowArtifactType.WORKFLOW_STATE.value
                    and item.path
                    == _output_reference(root, source_state_path, b"{}").path
                ),
                None,
            )
            if source_receipt is None:
                raise WorkflowRuntimeError("M6 terminal observation source receipt is absent.")
            source_path = root.resolve(strict=True) / source_receipt.path
            source_artifact = parse_workflow_artifact_bytes(
                source_path.read_bytes(),
                expected_type=WorkflowArtifactType.WORKFLOW_STATE,
            )
            if source_artifact.artifact_id != source_receipt.artifact_id:
                raise WorkflowRuntimeError("M6 terminal observation source receipt drifted.")
            source_value = source_artifact.value
            assert isinstance(source_value, WorkflowState)
            source_event_artifact = parse_workflow_artifact_bytes(
                (root.resolve(strict=True) / source_value.latest_event.reference.path).read_bytes(),
                expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
            )
            source_event = source_event_artifact.value
            assert isinstance(source_event, WorkflowEvent)
            if (
                head.source_state_id != source_artifact.artifact_id
                or source_event_artifact.artifact_id
                != source_value.latest_event.artifact_id
                or _terminal_observation_cause(source_event) is not observation.cause
                or tuple(
                    sorted(
                        set(source_event.native_input_ids)
                        - {plan_artifact.artifact_id, observation.scheduler_state_id}
                    )
                )
                != observation.source_artifact_ids
                or source_event.idempotency_key != request_idempotency
            ):
                raise WorkflowRuntimeError(
                    "M6 terminal observation retry differs from the reserved request."
                )
        else:
            recorded_at = (
                head.recorded_at
                if head.producer == "workflow-run"
                and head.idempotency_key == request_idempotency
                else _format_utc(self._clock.now())
            )
            event = self._observation_event(
                plan_artifact,
                plan,
                native_artifact,
                native,
                observation,
                recorded_at,
                request_idempotency,
            )
            event_artifact = artifact_from_value(
                WorkflowArtifactType.WORKFLOW_EVENT,
                event,
            )
            event_bytes = serialize_workflow_artifact(event_artifact)
            event_binding = NativeArtifactBinding(
                WorkflowArtifactType.WORKFLOW_EVENT.value,
                event_artifact.artifact_id,
                _output_reference(root, source_event_path, event_bytes),
                True,
            )
            state = self._observation_state(
                plan_artifact.artifact_id,
                plan,
                native,
                observation,
                event_binding,
                recorded_at,
                store,
                root,
                publication_observation,
            )
            source_artifact = artifact_from_value(
                WorkflowArtifactType.WORKFLOW_STATE,
                state,
            )
            state_bytes = serialize_workflow_artifact(source_artifact)
            event_relative = _output_reference(root, source_event_path, event_bytes).path
            state_relative = _output_reference(root, source_state_path, state_bytes).path
            if head.workflow_state_id is None:
                reserved = store.reserve_workflow_transition(
                    plan_id=plan_artifact.artifact_id,
                    expected_head_id=head.current_event_head_id,
                    scheduler_state_id=native_artifact.artifact_id,
                    scheduler_event_sequence=native.event_sequence,
                    scheduler_event_head_id=store.current_event_head_id,
                    source_state_id=None,
                    workflow_event_id=event_artifact.artifact_id,
                    workflow_state_id=source_artifact.artifact_id,
                    idempotency_key=request_idempotency,
                    producer="workflow-run",
                    event_path=event_relative,
                    state_path=state_relative,
                    recorded_at=recorded_at,
                )
                publication = self._artifact_store(root)
                publication.publish_idempotent(
                    source_event_path,
                    event_bytes,
                    artifact_type=WorkflowArtifactType.WORKFLOW_EVENT.value,
                    artifact_id=event_artifact.artifact_id,
                )
                confirmed = store.confirm_workflow_artifact(
                    plan_id=plan_artifact.artifact_id,
                    expected_head_id=reserved.current_event_head_id,
                    artifact_id=event_artifact.artifact_id,
                    path=event_relative,
                    idempotency_key=request_idempotency,
                    recorded_at=recorded_at,
                    artifact_type=WorkflowArtifactType.WORKFLOW_EVENT.value,
                    producer="workflow-run",
                )
                publication.publish_idempotent(
                    source_state_path,
                    state_bytes,
                    artifact_type=WorkflowArtifactType.WORKFLOW_STATE.value,
                    artifact_id=source_artifact.artifact_id,
                )
                store.confirm_workflow_artifact(
                    plan_id=plan_artifact.artifact_id,
                    expected_head_id=confirmed.current_event_head_id,
                    artifact_id=source_artifact.artifact_id,
                    path=state_relative,
                    idempotency_key=request_idempotency,
                    recorded_at=recorded_at,
                    artifact_type=WorkflowArtifactType.WORKFLOW_STATE.value,
                    producer="workflow-run",
                )
            elif (
                head.workflow_state_id != source_artifact.artifact_id
                or head.idempotency_key != request_idempotency
                or head.producer != "workflow-run"
            ):
                raise WorkflowRuntimeError("M6 workflow head rejects this observation request.")

        source_value = source_artifact.value
        assert isinstance(source_value, WorkflowState)
        source_bytes = serialize_workflow_artifact(source_artifact)
        source_binding = NativeArtifactBinding(
            WorkflowArtifactType.WORKFLOW_STATE.value,
            source_artifact.artifact_id,
            _output_reference(root, source_state_path, source_bytes),
            True,
        )
        from sdaqf.application.workflow_outcome import WorkflowOutcomeService

        outcome_artifact, terminal_event_artifact, terminal_state_artifact = WorkflowOutcomeService(
            self._clock,
            self._store,
            planner=self._planner,
        ).publish(
            source_artifact,
            source_binding,
            plan_artifact,
            root,
            scheduler_state,
            output_outcome,
            output_event,
            output_state,
        )
        return WorkflowTransition(
            terminal_event_artifact,
            terminal_state_artifact,
            (),
            (),
            (),
            outcome=outcome_artifact,
        )

    @staticmethod
    def _authenticate_terminal_observation(
        plan_artifact: LoadedWorkflowArtifact,
        plan: IntegratedPlan,
        observation: WorkflowTerminalObservation,
        store: SQLiteSchedulerStore,
        native_artifact: LoadedSchedulerArtifact,
        native: SchedulerState,
    ) -> None:
        """Bind a closed cause to the current exact M6 v2 observation."""

        if (
            observation.scheduler_state_id != native_artifact.artifact_id
            or observation.scheduler_event_head_id != store.current_event_head_id
            or not observation.source_artifact_ids
            or observation.source_artifact_ids
            != tuple(sorted(set(observation.source_artifact_ids)))
            or plan_artifact.artifact_id in observation.source_artifact_ids
            or native_artifact.artifact_id in observation.source_artifact_ids
        ):
            raise WorkflowRuntimeError("Terminal observation is not current M6 authority.")
        head = store.workflow_head(plan_artifact.artifact_id)
        if head is None or head.candidate != plan.candidate or head.graph_id != native.graph_id:
            raise WorkflowRuntimeError("Terminal observation Plan epoch identity drifted.")
        plan_receipt = next(
            (
                item
                for item in head.receipts
                if item.artifact_type == WorkflowArtifactType.INTEGRATED_PLAN.value
                and item.artifact_id == plan_artifact.artifact_id
                and item.producer == "workflow-plan"
            ),
            None,
        )
        if plan_receipt is None:
            raise WorkflowRuntimeError("Terminal observation Plan receipt is absent.")
        store.authenticate_workflow_artifact(
            plan_id=plan_artifact.artifact_id,
            artifact_type=WorkflowArtifactType.INTEGRATED_PLAN.value,
            artifact_id=plan_artifact.artifact_id,
            path=plan_receipt.path,
            producer="workflow-plan",
            candidate=plan.candidate,
            graph_id=plan.task_graph.artifact_id,
        )
        known_ids = {
            plan_artifact.artifact_id,
            plan.task_graph.artifact_id,
            native_artifact.artifact_id,
            store.current_event_head_id,
            *(
                item.artifact_id
                for kind in ("leases", "messages", "events", "budget", "worktrees")
                for item in store.evidence_history(
                    kind,
                    through_event_sequence=native.event_sequence,
                )
            ),
            plan.intent.artifact_id,
            plan.context_graph.artifact_id,
            plan.context_query.artifact_id,
            plan.context_selection.artifact_id,
            plan.context_snapshot.artifact_id,
            *(item.artifact_id for item in plan.solver_requests),
        }
        if not set(observation.source_artifact_ids) <= known_ids:
            raise WorkflowRuntimeError("Terminal observation source identity is unauthenticated.")
        native_blockers = {
            blocker.code for task in native.tasks for blocker in task.blockers
        }
        source_ids = set(observation.source_artifact_ids)
        messages = store.evidence_history(
            "messages",
            through_event_sequence=native.event_sequence,
        )
        rejected_approvals = {
            artifact.artifact_id
            for artifact in messages
            if isinstance((message := artifact.value), MailboxMessage)
            and message.message_type is MessageType.APPROVAL_DECISION
            and message.payload.get("decision") == "rejected"
        }
        expired_approvals = {
            artifact.artifact_id
            for artifact in messages
            if isinstance((message := artifact.value), MailboxMessage)
            and message.message_type is MessageType.APPROVAL_DECISION
            and message.payload.get("decision") == "approved"
            and isinstance(message.payload.get("expires_at"), str)
            and _parse_utc(str(message.payload["expires_at"]))
            <= max(
                (
                    _parse_utc(event.recorded_at)
                    for artifact_event in store.evidence_history(
                        "events",
                        through_event_sequence=native.event_sequence,
                    )
                    if isinstance((event := artifact_event.value), SchedulerEvent)
                ),
                default=_parse_utc(str(message.payload["expires_at"])),
            )
        }
        lease_loss_events = {
            artifact.artifact_id
            for artifact in store.evidence_history(
                "events",
                through_event_sequence=native.event_sequence,
            )
            if isinstance(artifact.value, SchedulerEvent)
            and artifact.value.cause == "lease-expired"
        }
        if (
            observation.cause is WorkflowTerminalObservationCause.UI_EVIDENCE_UNAVAILABLE
            and not plan.ui_required
        ):
            raise WorkflowRuntimeError("UI evidence cause requires a UI-required Plan.")
        if (
            observation.cause is WorkflowTerminalObservationCause.APPROVAL_REQUIRED
            and "approval-required" not in native_blockers
        ):
            raise WorkflowRuntimeError("Approval-required cause is absent from M6 State.")
        if (
            observation.cause is WorkflowTerminalObservationCause.APPROVAL_REFUSED
            and not source_ids & rejected_approvals
        ):
            raise WorkflowRuntimeError("Approval-refused cause lacks its M6 decision.")
        if (
            observation.cause is WorkflowTerminalObservationCause.APPROVAL_EXPIRED
            and not source_ids & expired_approvals
        ):
            raise WorkflowRuntimeError("Approval-expired cause lacks its M6 decision.")
        if (
            observation.cause is WorkflowTerminalObservationCause.STALE_CANDIDATE
            and plan.intent.artifact_id not in source_ids
        ):
            raise WorkflowRuntimeError("Stale-candidate cause lacks its admitted Intent source.")
        if (
            observation.cause is WorkflowTerminalObservationCause.STALE_CONTEXT
            and plan.context_snapshot.artifact_id not in source_ids
        ):
            raise WorkflowRuntimeError("Stale-context cause lacks its Context source.")
        if (
            observation.cause is WorkflowTerminalObservationCause.LEASE_LOST
            and not source_ids & lease_loss_events
        ):
            raise WorkflowRuntimeError("Lease-lost cause lacks its M6 lease-expired Event.")
        if (
            observation.cause is WorkflowTerminalObservationCause.SOLVER_INCONCLUSIVE
            and (
                not plan.solver_requests
                or not any(item.task_kind == "solver" for item in plan.tasks)
                or not native_blockers & {"budget-exhausted", "solver-inconclusive"}
                or not source_ids
                & ({native.budget_ledger_id} | {item.artifact_id for item in plan.solver_requests})
            )
        ):
            raise WorkflowRuntimeError("Solver-inconclusive cause lacks native Solver evidence.")
        if (
            observation.cause
            is WorkflowTerminalObservationCause.EXTERNAL_EFFECT_AMBIGUOUS
            and not WorkflowRuntimeService._ambiguities(store, native)
        ):
            raise WorkflowRuntimeError("External-effect ambiguity is absent from M6 State.")

    @staticmethod
    def _observation_event(
        plan_artifact: LoadedWorkflowArtifact,
        plan: IntegratedPlan,
        native_artifact: LoadedSchedulerArtifact,
        native: SchedulerState,
        observation: WorkflowTerminalObservation,
        recorded_at: str,
        idempotency_key: str,
    ) -> WorkflowEvent:
        ambiguous = (
            observation.cause
            is WorkflowTerminalObservationCause.EXTERNAL_EFFECT_AMBIGUOUS
        )
        return WorkflowEvent(
            sequence=1,
            previous_event_id=None,
            prior_state_id=None,
            plan_id=plan_artifact.artifact_id,
            candidate=plan.candidate,
            sensitivity=plan.sensitivity,
            cause=WorkflowEventCause.GATE_EVALUATED,
            before_status=TaskState.PLANNED,
            after_status=TaskState.BLOCKED,
            scheduler_event_head_before=native.event_head_sha256,
            scheduler_event_head_after=native.event_head_sha256,
            effect_disposition=(
                EffectDisposition.AMBIGUOUS if ambiguous else EffectDisposition.BLOCKED
            ),
            actor="M8 workflow observation finalizer",
            recorded_at=recorded_at,
            idempotency_key=idempotency_key,
            native_input_ids=tuple(
                sorted(
                    {
                        plan_artifact.artifact_id,
                        native_artifact.artifact_id,
                        *observation.source_artifact_ids,
                    }
                )
            ),
            native_output_ids=(native_artifact.artifact_id,),
            task_id=None,
            effect_id=None,
            approval_id=None,
            reason_codes=tuple(
                sorted({"native-observation-closed", observation.cause.value})
            ),
            prior_state=None,
        )

    @staticmethod
    def _observation_state(
        plan_id: str,
        plan: IntegratedPlan,
        native: SchedulerState,
        observation: WorkflowTerminalObservation,
        event_binding: NativeArtifactBinding,
        recorded_at: str,
        store: SQLiteSchedulerStore,
        root: Path,
        publication_observation: WorkflowPublicationObservation,
    ) -> WorkflowState:
        tasks = _task_projections(native)
        approval_ids = tuple(
            sorted(
                {
                    event.approval_id
                    for artifact in store.evidence_history(
                        "events",
                        through_event_sequence=native.event_sequence,
                    )
                    if isinstance((event := artifact.value), SchedulerEvent)
                    and event.sequence <= native.event_sequence
                    and event.cause == "approval-consumed"
                    and event.approval_id is not None
                }
            )
        )
        blocker = WorkflowBlocker(
            observation.cause.value,
            observation.source_artifact_ids,
        )
        ambiguities = (
            (WorkflowTerminalObservationCause.EXTERNAL_EFFECT_AMBIGUOUS.value,)
            if observation.cause
            is WorkflowTerminalObservationCause.EXTERNAL_EFFECT_AMBIGUOUS
            else ()
        )
        observations = _derive_native_observations(
            plan,
            native,
            store,
            root,
            publication_observation,
        )
        gates = _derive_gates(
            plan,
            tasks,
            observations.evidence_ids if observations.g2_passed else (),
            observations.review_ids if observations.g3_passed else (),
            observations.handoff_status,
            observations.g4_result_ids,
            observations.g4_passed,
        )
        measurements = _derive_measurements(
            plan_id,
            plan,
            native,
            tasks,
            approval_ids,
            ambiguities,
            observations=observations,
            event_chain=(event_binding,),
            store=store,
            root=root,
            latest_cause=WorkflowEventCause.GATE_EVALUATED,
        )
        return WorkflowState(
            plan_id=plan_id,
            candidate=plan.candidate,
            sensitivity=plan.sensitivity,
            status=TaskState.BLOCKED,
            scheduler_graph_id=native.graph_id,
            scheduler_state_id=artifact_from_scheduler_state(native),
            scheduler_event_sequence=native.event_sequence,
            scheduler_event_head_sha256=native.event_head_sha256,
            tasks=tasks,
            solver_verification_ids=observations.solver_verification_ids,
            evidence_ids=observations.evidence_ids,
            review_ids=observations.review_ids,
            approval_ids=approval_ids,
            gates=gates,
            handoff_id=observations.handoff_id,
            handoff_status=observations.handoff_status,
            blockers=(blocker,),
            ambiguities=ambiguities,
            measurements=measurements,
            observation_artifacts=observations.bindings,
            event_chain=(event_binding,),
            latest_event=event_binding,
            transition_count=1,
            recorded_at=recorded_at,
        )

    def supersede(
        self,
        source_state_artifact: LoadedWorkflowArtifact,
        source_state_binding: NativeArtifactBinding,
        plan_artifact: LoadedWorkflowArtifact,
        successor_intent_artifact: LoadedWorkflowArtifact,
        successor_intent_binding: NativeArtifactBinding,
        root: Path,
        scheduler_state: Path,
        output_state: Path,
        output_event: Path,
        output_outcome: Path | None = None,
    ) -> WorkflowTransition:
        """Close the old candidate epoch through M6 terminal authority."""

        _require_runtime_private_path(root, scheduler_state, existing=True)
        state_lexical = _require_runtime_private_path(root, output_state, existing=False)
        event_lexical = _require_runtime_private_path(root, output_event, existing=False)
        selected_outcome = (
            output_state.with_name(f"{output_state.stem}-outcome.json")
            if output_outcome is None
            else output_outcome
        )
        outcome_lexical = _require_runtime_private_path(root, selected_outcome, existing=False)
        resolved_root = root.resolve(strict=True)
        try:
            self._planner._candidate_verifier.classify_output_paths(  # type: ignore[attr-defined]
                root,
                tuple(
                    item.relative_to(resolved_root).as_posix()
                    for item in (event_lexical, state_lexical, outcome_lexical)
                ),
                scheduler_state=scheduler_state,
                plan_id=plan_artifact.artifact_id,
            )
        except (OSError, RuntimeError) as exc:
            raise WorkflowRuntimeError(
                "Terminal outputs failed initial Git publication classification."
            ) from exc
        if successor_intent_artifact.artifact_type is not WorkflowArtifactType.DEVELOPMENT_INTENT:
            raise WorkflowRuntimeError("Supersession requires successor Development Intent.")
        successor = successor_intent_artifact.value
        from sdaqf.domain.workflow import DevelopmentIntent

        assert isinstance(successor, DevelopmentIntent)
        if (
            successor_intent_binding.artifact_type != WorkflowArtifactType.DEVELOPMENT_INTENT.value
            or successor_intent_binding.artifact_id != successor_intent_artifact.artifact_id
            or not successor_intent_binding.required
        ):
            raise WorkflowRuntimeError("Supersession successor Intent binding is invalid.")
        rebound = parse_workflow_artifact_bytes(
            self._artifact_store(root).load(
                successor_intent_binding.reference,
                1_048_576,
            ),
            expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
        )
        if rebound.artifact_id != successor_intent_artifact.artifact_id:
            raise WorkflowRuntimeError("Supersession successor Intent binding drifted.")
        publication_observation = self._planner._verify_candidate(
            root,
            successor,
            scheduler_state,
            require_scheduler_candidate=False,
        )
        plan, source, publication_observation = self._validate_inputs(
            plan_artifact,
            source_state_artifact,
            root,
            scheduler_state,
            revalidate_plan=False,
            publication_observation=publication_observation,
        )
        assert source is not None
        if self._terminal_cause(source, root) is not None:
            raise WorkflowRuntimeError("A terminal Workflow State cannot be superseded again.")
        if successor.candidate == plan.candidate:
            raise WorkflowRuntimeError("Supersession requires a changed Candidate identity.")
        if (
            source_state_binding.artifact_type != WorkflowArtifactType.WORKFLOW_STATE.value
            or source_state_binding.artifact_id != source_state_artifact.artifact_id
            or not source_state_binding.required
        ):
            raise WorkflowRuntimeError("Supersession source State binding is invalid.")
        source_bytes = self._artifact_store(root).load(
            source_state_binding.reference,
            16 * 1024 * 1024,
        )
        rebound_source = parse_workflow_artifact_bytes(
            source_bytes,
            expected_type=WorkflowArtifactType.WORKFLOW_STATE,
        )
        if rebound_source.artifact_id != source_state_artifact.artifact_id:
            raise WorkflowRuntimeError("Supersession source State binding drifted.")
        store = SQLiteSchedulerStore(scheduler_state, root)
        store.validate()
        native_artifact = store.status()
        native = native_artifact.value
        assert isinstance(native, SchedulerState)
        pinned_scheduler_event_head_id = store.current_event_head_id
        self._validate_scheduler_lineage(plan, source, store, native)
        if native_artifact.artifact_id != source.scheduler_state_id:
            raise WorkflowRuntimeError("Supersession refuses an unadopted Scheduler advance.")
        self._require_exact_state(
            plan_artifact.artifact_id,
            plan,
            source_state_artifact,
            source,
            native,
            store,
            root,
            publication_observation,
        )
        request_idempotency = _supersession_idempotency(
            plan_artifact.artifact_id,
            source_state_artifact.artifact_id,
            successor_intent_artifact.artifact_id,
        )
        existing_head = store.workflow_head(plan_artifact.artifact_id)
        if existing_head is None:
            raise WorkflowRuntimeError("M6 workflow epoch is not open for supersession.")
        if existing_head.phase in {
            WorkflowEpochPhase.TERMINAL_RESERVED,
            WorkflowEpochPhase.TERMINAL_CONFIRMED,
        }:
            if (
                existing_head.source_state_id != source_state_artifact.artifact_id
                or existing_head.idempotency_key != request_idempotency
                or existing_head.producer != "workflow-supersede"
                or existing_head.terminal_at is None
            ):
                raise WorkflowRuntimeError("M6 terminal authority rejects this supersession.")
            now = existing_head.terminal_at
        else:
            now = _format_utc(self._clock.now())
        event = WorkflowEvent(
            sequence=source.transition_count + 1,
            previous_event_id=source.latest_event.artifact_id,
            prior_state_id=source_state_artifact.artifact_id,
            plan_id=plan_artifact.artifact_id,
            candidate=plan.candidate,
            sensitivity=plan.sensitivity,
            cause=WorkflowEventCause.PLAN_SUPERSEDED,
            before_status=source.status,
            after_status=TaskState.SUPERSEDED,
            scheduler_event_head_before=source.scheduler_event_head_sha256,
            scheduler_event_head_after=source.scheduler_event_head_sha256,
            effect_disposition=(
                EffectDisposition.AMBIGUOUS
                if source.ambiguities
                else EffectDisposition.NOT_APPLICABLE
            ),
            actor="M8 workflow supersession service",
            recorded_at=now,
            idempotency_key=request_idempotency,
            native_input_ids=tuple(
                sorted(
                    {
                        plan_artifact.artifact_id,
                        source_state_artifact.artifact_id,
                        source.latest_event.artifact_id,
                        source.scheduler_state_id,
                        successor_intent_artifact.artifact_id,
                    }
                )
            ),
            native_output_ids=(source.scheduler_state_id,),
            task_id=None,
            effect_id=None,
            approval_id=None,
            reason_codes=tuple(
                sorted(
                    {
                        "plan-superseded",
                        "predecessor-authority-preserved",
                        *source.ambiguities,
                    }
                )
            ),
            prior_state=source_state_binding,
        )
        event_artifact = artifact_from_value(WorkflowArtifactType.WORKFLOW_EVENT, event)
        event_bytes = serialize_workflow_artifact(event_artifact)
        event_binding = NativeArtifactBinding(
            WorkflowArtifactType.WORKFLOW_EVENT.value,
            event_artifact.artifact_id,
            _output_reference(root, output_event, event_bytes),
            True,
        )
        superseded = replace(
            source,
            status=TaskState.SUPERSEDED,
            blockers=tuple(
                sorted(
                    {
                        *source.blockers,
                        WorkflowBlocker(
                            "predecessor-superseded",
                            (successor_intent_artifact.artifact_id,),
                        ),
                    },
                    key=lambda item: (item.code, item.references),
                )
            ),
            observation_artifacts=tuple(
                sorted(
                    (*source.observation_artifacts, successor_intent_binding),
                    key=lambda item: item.artifact_id,
                )
            ),
            event_chain=(*source.event_chain, event_binding),
            latest_event=event_binding,
            transition_count=source.transition_count + 1,
            recorded_at=now,
        )
        state_artifact = artifact_from_value(
            WorkflowArtifactType.WORKFLOW_STATE,
            superseded,
        )
        state_bytes = serialize_workflow_artifact(state_artifact)
        from sdaqf.application.workflow_outcome import WorkflowOutcomeService

        outcome_artifact = WorkflowOutcomeService(
            self._clock,
            self._store,
            planner=self._planner,
        )._derive_validated(
            plan,
            superseded,
            plan_artifact.artifact_id,
            state_artifact.artifact_id,
            root,
            completed_at=now,
        )
        outcome_bytes = serialize_workflow_artifact(outcome_artifact)
        head = store.workflow_head(plan_artifact.artifact_id)
        if head is None:
            raise WorkflowRuntimeError("M6 workflow epoch is not open for supersession.")
        event_path = _output_reference(root, output_event, event_bytes).path
        state_path = _output_reference(root, output_state, state_bytes).path
        outcome_path = _output_reference(root, selected_outcome, outcome_bytes).path
        if len({event_path.casefold(), state_path.casefold(), outcome_path.casefold()}) != 3:
            raise WorkflowRuntimeError("Terminal output paths must be distinct and case-unique.")
        publication = self._artifact_store(root)
        preflight = (
            (output_event, event_bytes, WorkflowArtifactType.WORKFLOW_EVENT, event_artifact),
            (output_state, state_bytes, WorkflowArtifactType.WORKFLOW_STATE, state_artifact),
            (
                selected_outcome,
                outcome_bytes,
                WorkflowArtifactType.WORKFLOW_OUTCOME,
                outcome_artifact,
            ),
        )
        try:
            self._planner._candidate_verifier.preflight_outputs(  # type: ignore[attr-defined]
                root,
                tuple(
                    (
                        _output_reference(root, target, content).path,
                        artifact_type.value,
                        artifact.artifact_id,
                        "workflow-supersede",
                    )
                    for target, content, artifact_type, artifact in preflight
                ),
                scheduler_state=scheduler_state,
                plan_id=plan_artifact.artifact_id,
            )
            self._planner._candidate_verifier.revalidate(
                root,
                publication_observation,
                scheduler_state=scheduler_state,
            )
        except (OSError, RuntimeError) as exc:
            raise WorkflowRuntimeError(
                "Terminal outputs or pinned publication authority changed before reserve."
            ) from exc
        reserved = store.reserve_workflow_terminal(
            plan_id=plan_artifact.artifact_id,
            expected_head_id=head.current_event_head_id,
            scheduler_state_id=source.scheduler_state_id,
            scheduler_event_sequence=source.scheduler_event_sequence,
            scheduler_event_head_id=pinned_scheduler_event_head_id,
            source_state_id=source_state_artifact.artifact_id,
            workflow_event_id=event_artifact.artifact_id,
            workflow_state_id=state_artifact.artifact_id,
            outcome_id=outcome_artifact.artifact_id,
            idempotency_key=event.idempotency_key,
            producer="workflow-supersede",
            event_path=event_path,
            state_path=state_path,
            outcome_path=outcome_path,
            recorded_at=now,
        )
        confirmations = (
            (
                output_event,
                event_bytes,
                WorkflowArtifactType.WORKFLOW_EVENT,
                event_artifact,
                event_path,
            ),
            (
                output_state,
                state_bytes,
                WorkflowArtifactType.WORKFLOW_STATE,
                state_artifact,
                state_path,
            ),
            (
                selected_outcome,
                outcome_bytes,
                WorkflowArtifactType.WORKFLOW_OUTCOME,
                outcome_artifact,
                outcome_path,
            ),
        )
        confirmed = reserved
        for target, content, artifact_type, artifact, path in confirmations:
            publication.publish_idempotent(
                target,
                content,
                artifact_type=artifact_type.value,
                artifact_id=artifact.artifact_id,
            )
            confirmed = store.confirm_workflow_artifact(
                plan_id=plan_artifact.artifact_id,
                expected_head_id=confirmed.current_event_head_id,
                artifact_id=artifact.artifact_id,
                path=path,
                idempotency_key=event.idempotency_key,
                recorded_at=now,
                artifact_type=artifact_type.value,
                producer="workflow-supersede",
            )
        try:
            self._planner._candidate_verifier.confirm_outputs(  # type: ignore[attr-defined]
                root,
                publication_observation,
                successor.candidate,
                tuple(
                    (
                        path,
                        artifact_type.value,
                        artifact.artifact_id,
                        "workflow-supersede",
                    )
                    for _, _, artifact_type, artifact, path in confirmations
                ),
                scheduler_state=scheduler_state,
                plan_id=plan_artifact.artifact_id,
            )
        except (OSError, RuntimeError) as exc:
            raise WorkflowRuntimeError(
                "Terminal outputs failed final Git and M6 confirmation."
            ) from exc
        store.confirm_workflow_terminal(
            plan_id=plan_artifact.artifact_id,
            expected_head_id=confirmed.current_event_head_id,
            idempotency_key=event.idempotency_key,
            recorded_at=now,
            producer="workflow-supersede",
        )
        return WorkflowTransition(
            event_artifact,
            state_artifact,
            (),
            (),
            (),
            outcome=outcome_artifact,
        )

    def status(
        self,
        state_artifact: LoadedWorkflowArtifact,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        *,
        predecessor_scheduler_state: Path | None = None,
        publication_observation: WorkflowPublicationObservation | None = None,
    ) -> dict[str, object]:
        """Revalidate exact state without mutating M6 or publishing M8 artifacts."""

        supplied_state = state_artifact.value
        revalidate_current_candidate = publication_observation is None and not (
            isinstance(supplied_state, WorkflowState)
            and supplied_state.status is TaskState.SUPERSEDED
        )
        plan, state, publication_observation = self._validate_inputs(
            plan_artifact,
            state_artifact,
            root,
            scheduler_state,
            revalidate_plan=revalidate_current_candidate,
            publication_observation=publication_observation,
            predecessor_scheduler_state=predecessor_scheduler_state,
        )
        assert state is not None
        store = SQLiteSchedulerStore(scheduler_state, root)
        _require_runtime_private_path(root, scheduler_state, existing=True)
        store.validate()
        store.require_workflow_authority()
        head = store.workflow_head(plan_artifact.artifact_id)
        if head is None or state_artifact.artifact_id not in {
            receipt.artifact_id for receipt in head.receipts
        }:
            raise WorkflowRuntimeError("Workflow State has no M6 v2 epoch receipt.")
        current = store.status()
        native = current.value
        assert isinstance(native, SchedulerState)
        self._validate_scheduler_lineage(plan, state, store, native)
        self._require_exact_state(
            plan_artifact.artifact_id,
            plan,
            state_artifact,
            state,
            native,
            store,
            root,
            publication_observation,
        )
        return {
            "plan_id": plan_artifact.artifact_id,
            "state_id": state_artifact.artifact_id,
            "scheduler_state_id": current.artifact_id,
            "scheduler_advanced": current.artifact_id != state.scheduler_state_id,
            "is_epoch_head": head.workflow_state_id == state_artifact.artifact_id,
            "epoch_phase": head.phase.value,
            "authoritative_state_id": head.workflow_state_id,
            "authoritative_outcome_id": head.outcome_id,
            "current_workflow_event_head_id": head.current_event_head_id,
            "event_sequence": native.event_sequence,
            "wait_report": SchedulerService().wait_report(scheduler_state, root).to_dict(),
            "valid": True,
            "side_effect_free": True,
        }

    def _transition(
        self,
        prior_state_artifact: LoadedWorkflowArtifact | None,
        prior_state_binding: NativeArtifactBinding | None,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        output_state: Path,
        output_event: Path,
        *,
        predecessor_scheduler_state: Path | None = None,
        messages: tuple[Path, ...] = (),
        agent_host: AgentHostPort | None = None,
    ) -> WorkflowTransition:
        _require_runtime_private_path(root, scheduler_state, existing=True)
        state_lexical = _require_runtime_private_path(root, output_state, existing=False)
        event_lexical = _require_runtime_private_path(root, output_event, existing=False)
        resolved_root = root.resolve(strict=True)
        try:
            self._planner._candidate_verifier.classify_output_paths(  # type: ignore[attr-defined]
                root,
                (
                    event_lexical.relative_to(resolved_root).as_posix(),
                    state_lexical.relative_to(resolved_root).as_posix(),
                ),
                scheduler_state=scheduler_state,
                plan_id=plan_artifact.artifact_id,
            )
        except (OSError, RuntimeError) as exc:
            raise WorkflowRuntimeError(
                "Workflow transition outputs failed initial publication classification."
            ) from exc
        plan, prior, publication_observation = self._validate_inputs(
            plan_artifact,
            prior_state_artifact,
            root,
            scheduler_state,
            predecessor_scheduler_state=predecessor_scheduler_state,
        )
        if prior is not None and self._terminal_cause(prior, root) is not None:
            raise WorkflowRuntimeError("A terminal Workflow State cannot be resumed.")
        if prior_state_artifact is None:
            if prior_state_binding is not None:
                raise WorkflowRuntimeError("Initial transition cannot bind a prior State.")
        elif (
            prior_state_binding is None
            or prior_state_binding.artifact_type != WorkflowArtifactType.WORKFLOW_STATE.value
            or prior_state_binding.artifact_id != prior_state_artifact.artifact_id
            or not prior_state_binding.required
        ):
            raise WorkflowRuntimeError("Resume requires the exact prior State binding.")
        else:
            prior_bytes = self._artifact_store(root).load(
                prior_state_binding.reference,
                16 * 1024 * 1024,
            )
            rebound = parse_workflow_artifact_bytes(
                prior_bytes,
                expected_type=WorkflowArtifactType.WORKFLOW_STATE,
            )
            if rebound.artifact_id != prior_state_artifact.artifact_id:
                raise WorkflowRuntimeError("Resume prior State binding drifted.")
        store = SQLiteSchedulerStore(scheduler_state, root)
        store.validate()
        store.require_workflow_authority()
        epoch_head = store.workflow_head(plan_artifact.artifact_id)
        if epoch_head is None:
            raise WorkflowRuntimeError("M6 workflow epoch is not open for this Plan.")
        if epoch_head.phase in {
            WorkflowEpochPhase.TERMINAL_RESERVED,
            WorkflowEpochPhase.TERMINAL_CONFIRMED,
        }:
            raise WorkflowRuntimeError("M6 terminal authority permanently closes this epoch.")
        if prior_state_artifact is None:
            if epoch_head.workflow_state_id is not None:
                raise WorkflowRuntimeError("M6 workflow epoch already has a current State.")
        elif epoch_head.workflow_state_id != prior_state_artifact.artifact_id:
            raise WorkflowRuntimeError("Supplied Workflow State is historical, not epoch head.")
        before_artifact = store.status()
        before = before_artifact.value
        assert isinstance(before, SchedulerState)
        self._validate_scheduler_lineage(plan, prior, store, before)
        scheduler_advanced = (
            prior is not None and before_artifact.artifact_id != prior.scheduler_state_id
        )
        if scheduler_advanced and messages:
            raise WorkflowRuntimeError(
                "Host messages cannot be ingested after the scheduler advanced externally."
            )
        if prior is not None and not scheduler_advanced:
            assert prior_state_artifact is not None
            self._require_exact_state(
                plan_artifact.artifact_id,
                plan,
                prior_state_artifact,
                prior,
                before,
                store,
                root,
                publication_observation,
            )
        if scheduler_advanced:
            tick = SchedulerTick(
                state=before_artifact,
                outgoing=(),
                accepted_message_ids=(),
                rejected_message_ids=(),
            )
        else:
            self._revalidate_plan_effects_before_tick(plan, root)
            try:
                tick = SchedulerService(self._clock).tick(
                    scheduler_state,
                    root,
                    "HST-M8-RUNTIME",
                    messages,
                )
            except (SchedulerAdapterError, OSError, ValueError) as exc:
                raise WorkflowRuntimeError("M6 scheduler tick failed closed.") from exc
        after = tick.state.value
        assert isinstance(after, SchedulerState)
        if after.graph_id != plan.task_graph.artifact_id or after.candidate != plan.candidate:
            raise WorkflowRuntimeError("M6 scheduler identity drifted during transition.")
        publication_observation = self._planner._candidate_verifier.observe(
            root,
            plan.candidate,
            scheduler_state=scheduler_state,
            plan_id=plan_artifact.artifact_id,
        )
        protected, approvals = self._revalidate_protected_effects(
            plan,
            tick,
            scheduler_state,
            root,
        )
        ambiguities = self._ambiguities(store, after)
        cause = self._event_cause(plan, prior, after, protected, approvals, ambiguities)
        sequence = 1 if prior is None else prior.transition_count + 1
        previous_event_id = None if prior is None else prior.latest_event.artifact_id
        prior_state_id = None if prior_state_artifact is None else prior_state_artifact.artifact_id
        now = _format_utc(self._clock.now())
        outgoing_ids = tuple(sorted(item.artifact_id for item in tick.outgoing))
        task_ids = tuple(
            sorted(
                {
                    message.task_id
                    for artifact in tick.outgoing
                    if isinstance((message := artifact.value), MailboxMessage)
                    and message.task_id is not None
                }
            )
        )
        native_inputs = tuple(
            sorted(
                {
                    plan_artifact.artifact_id,
                    before_artifact.artifact_id,
                    *(() if prior_state_id is None else (prior_state_id,)),
                    *(() if previous_event_id is None else (previous_event_id,)),
                }
            )
        )
        native_outputs = tuple(
            sorted({tick.state.artifact_id, *outgoing_ids, *protected, *approvals})
        )
        reason_codes = _transition_reason_codes(cause, protected, approvals, ambiguities)
        before_status = TaskState.PLANNED if prior is None else prior.status
        projected_tasks = _task_projections(after)
        transition_observations = _derive_native_observations(
            plan,
            after,
            store,
            root,
            publication_observation,
        )
        provisional_gates = _derive_gates(
            plan,
            projected_tasks,
            (transition_observations.evidence_ids if transition_observations.g2_passed else ()),
            (transition_observations.review_ids if transition_observations.g3_passed else ()),
            transition_observations.handoff_status,
            transition_observations.g4_result_ids,
            transition_observations.g4_passed,
        )
        provisional_blockers = _derive_blockers(
            plan, projected_tasks, provisional_gates, ambiguities
        )
        after_status = _derive_status(plan, projected_tasks, provisional_blockers, ambiguities)
        effect_disposition = (
            EffectDisposition.AMBIGUOUS
            if ambiguities
            else EffectDisposition.REVALIDATED
            if protected
            else EffectDisposition.BLOCKED
            if cause is WorkflowEventCause.APPROVAL_BLOCKED
            else EffectDisposition.NOT_APPLICABLE
        )
        event = WorkflowEvent(
            sequence=sequence,
            previous_event_id=previous_event_id,
            prior_state_id=prior_state_id,
            plan_id=plan_artifact.artifact_id,
            candidate=plan.candidate,
            sensitivity=plan.sensitivity,
            cause=cause,
            before_status=before_status,
            after_status=after_status,
            scheduler_event_head_before=(
                before.event_head_sha256
                if prior is None or not scheduler_advanced
                else prior.scheduler_event_head_sha256
            ),
            scheduler_event_head_after=after.event_head_sha256,
            effect_disposition=effect_disposition,
            actor="M8 workflow runtime",
            recorded_at=now,
            idempotency_key=_idempotency_key(
                plan_artifact.artifact_id,
                sequence,
                prior_state_id,
                after.event_head_sha256,
            ),
            native_input_ids=native_inputs,
            native_output_ids=native_outputs,
            task_id=task_ids[0] if len(task_ids) == 1 else None,
            effect_id=protected[0] if len(protected) == 1 else None,
            approval_id=approvals[0] if len(approvals) == 1 else None,
            reason_codes=reason_codes,
            prior_state=prior_state_binding,
        )
        event_artifact = artifact_from_value(WorkflowArtifactType.WORKFLOW_EVENT, event)
        event_bytes = serialize_workflow_artifact(event_artifact)
        event_binding = NativeArtifactBinding(
            WorkflowArtifactType.WORKFLOW_EVENT.value,
            event_artifact.artifact_id,
            _output_reference(root, output_event, event_bytes),
            True,
        )
        state = self._derive_state(
            plan_artifact.artifact_id,
            plan,
            after,
            (() if prior is None else prior.event_chain),
            event_binding,
            now,
            store,
            root,
            publication_observation,
            latest_cause=cause,
        )
        state_artifact = artifact_from_value(WorkflowArtifactType.WORKFLOW_STATE, state)
        state_bytes = serialize_workflow_artifact(state_artifact)
        self._planner._candidate_verifier.revalidate(
            root,
            publication_observation,
            scheduler_state=scheduler_state,
        )
        head = store.workflow_head(plan_artifact.artifact_id)
        if head is None:
            raise WorkflowRuntimeError("M6 workflow epoch is not open for this Plan.")
        event_path = _output_reference(root, output_event, event_bytes).path
        state_path = _output_reference(root, output_state, state_bytes).path
        producer = "workflow-run" if prior is None else "workflow-resume"
        try:
            self._planner._candidate_verifier.preflight_outputs(  # type: ignore[attr-defined]
                root,
                (
                    (
                        event_path,
                        WorkflowArtifactType.WORKFLOW_EVENT.value,
                        event_artifact.artifact_id,
                        producer,
                    ),
                    (
                        state_path,
                        WorkflowArtifactType.WORKFLOW_STATE.value,
                        state_artifact.artifact_id,
                        producer,
                    ),
                ),
                scheduler_state=scheduler_state,
                plan_id=plan_artifact.artifact_id,
            )
        except (OSError, RuntimeError) as exc:
            raise WorkflowRuntimeError(
                "Workflow transition outputs failed publication classification."
            ) from exc
        try:
            reserved = store.reserve_workflow_transition(
                plan_id=plan_artifact.artifact_id,
                expected_head_id=head.current_event_head_id,
                scheduler_state_id=tick.state.artifact_id,
                scheduler_event_sequence=after.event_sequence,
                scheduler_event_head_id=store.current_event_head_id,
                source_state_id=prior_state_id,
                workflow_event_id=event_artifact.artifact_id,
                workflow_state_id=state_artifact.artifact_id,
                idempotency_key=event.idempotency_key,
                producer=producer,
                event_path=event_path,
                state_path=state_path,
                recorded_at=now,
            )
        except (SchedulerAdapterError, OSError, ValueError) as exc:
            raise WorkflowRuntimeError("M6 transition reservation failed closed.") from exc
        publication = ExclusiveWorkflowArtifactStore(root) if self._store is None else self._store
        publication.publish_idempotent(
            output_event,
            event_bytes,
            artifact_type=WorkflowArtifactType.WORKFLOW_EVENT.value,
            artifact_id=event_artifact.artifact_id,
        )
        confirmed = store.confirm_workflow_artifact(
            plan_id=plan_artifact.artifact_id,
            expected_head_id=reserved.current_event_head_id,
            artifact_id=event_artifact.artifact_id,
            path=event_path,
            idempotency_key=event.idempotency_key,
            recorded_at=now,
            artifact_type=WorkflowArtifactType.WORKFLOW_EVENT.value,
            producer=producer,
        )
        publication.publish_idempotent(
            output_state,
            state_bytes,
            artifact_type=WorkflowArtifactType.WORKFLOW_STATE.value,
            artifact_id=state_artifact.artifact_id,
        )
        store.confirm_workflow_artifact(
            plan_id=plan_artifact.artifact_id,
            expected_head_id=confirmed.current_event_head_id,
            artifact_id=state_artifact.artifact_id,
            path=state_path,
            idempotency_key=event.idempotency_key,
            recorded_at=now,
            artifact_type=WorkflowArtifactType.WORKFLOW_STATE.value,
            producer=producer,
        )
        host_dispatch_performed = self._offer_agent_intents(store, after, agent_host)
        return WorkflowTransition(
            event=event_artifact,
            state=state_artifact,
            outgoing_intent_ids=outgoing_ids,
            protected_effect_ids=protected,
            approval_ids=approvals,
            host_dispatch_performed=host_dispatch_performed,
        )

    @staticmethod
    def _offer_agent_intents(
        store: SQLiteSchedulerStore,
        native: SchedulerState,
        agent_host: AgentHostPort | None,
    ) -> bool:
        """Offer exact pending M6 intents after M8 publication, retrying idempotently."""

        if agent_host is None:
            return False
        try:
            intents = WorkflowRuntimeService._pending_agent_intents(store, native)
            if intents is None or not intents:
                return False
            for artifact in intents:
                message = artifact.value
                assert isinstance(message, MailboxMessage)
                if message.message_type is MessageType.DISPATCH_INTENT:
                    agent_host.dispatch(message)
                else:
                    assert message.message_type is MessageType.CANCEL_REQUEST
                    agent_host.cancel(message)
        except Exception:
            # M6/M8 publication is already durable. An open host port may raise an
            # implementation-specific error, so reporting the committed transition as
            # failed would make its exact State head unusable for a later retry.
            return False
        return True

    @staticmethod
    def _pending_agent_intents(
        store: SQLiteSchedulerStore,
        native: SchedulerState,
    ) -> tuple[LoadedSchedulerArtifact, ...] | None:
        """Recover one exact durable host intent for each pending task projection."""

        expected_by_phase = {
            DispatchPhase.INTENT_PENDING: MessageType.DISPATCH_INTENT,
            DispatchPhase.CANCELLATION_REQUESTED: MessageType.CANCEL_REQUEST,
        }
        pending: list[LoadedSchedulerArtifact] = []
        for task in native.tasks:
            expected = expected_by_phase.get(task.dispatch_phase)
            if expected is None:
                continue
            matches = tuple(
                artifact
                for artifact in store.inspect_mailbox(
                    task_id=task.task_id,
                    direction=MessageDirection.SCHEDULER_TO_HOST.value,
                    limit=MAX_EXPORT,
                )
                if isinstance((message := artifact.value), MailboxMessage)
                and message.message_type is expected
                and message.direction is MessageDirection.SCHEDULER_TO_HOST
                and message.graph_id == native.graph_id
                and message.candidate == native.candidate
                and message.task_id == task.task_id
                and message.attempt == task.attempt
                and message.fence == task.fence
            )
            if len(matches) != 1:
                return None
            pending.append(matches[0])
        return tuple(pending)

    def _validate_inputs(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        state_artifact: LoadedWorkflowArtifact | None,
        root: Path,
        scheduler_state: Path,
        *,
        revalidate_plan: bool = True,
        publication_observation: WorkflowPublicationObservation | None = None,
        predecessor_scheduler_state: Path | None = None,
    ) -> tuple[
        IntegratedPlan,
        WorkflowState | None,
        WorkflowPublicationObservation,
    ]:
        if plan_artifact.artifact_type is not WorkflowArtifactType.INTEGRATED_PLAN:
            raise WorkflowRuntimeError("Workflow runtime requires Integrated Plan.")
        plan = plan_artifact.value
        assert isinstance(plan, IntegratedPlan)
        if revalidate_plan:
            _explanation, publication_observation = WorkflowExplainer(
                self._planner
            ).explain_with_observation(
                plan_artifact,
                root,
                scheduler_state,
                predecessor_scheduler_state=predecessor_scheduler_state,
            )
        if publication_observation is None:
            raise WorkflowRuntimeError("Workflow runtime lacks one pinned publication observation.")
        if state_artifact is None:
            return plan, None, publication_observation
        if state_artifact.artifact_type is not WorkflowArtifactType.WORKFLOW_STATE:
            raise WorkflowRuntimeError("Workflow resume requires Workflow State.")
        state = state_artifact.value
        assert isinstance(state, WorkflowState)
        if (
            state.plan_id != plan_artifact.artifact_id
            or state.candidate != plan.candidate
            or state.sensitivity != plan.sensitivity
        ):
            raise WorkflowRuntimeError("Workflow State identity is stale for this Plan.")
        publication = self._artifact_store(root)
        try:
            event_bytes = publication.read_event_chain(
                state.event_chain,
                2_147_483_647,
            )
        except (OSError, RuntimeError) as exc:
            raise WorkflowRuntimeError("Workflow Event chain could not be loaded.") from exc
        previous_id: str | None = None
        chain: list[tuple[NativeArtifactBinding, LoadedWorkflowArtifact, WorkflowEvent]] = []
        for index, (binding, content) in enumerate(
            zip(state.event_chain, event_bytes, strict=True), start=1
        ):
            event_artifact = parse_workflow_artifact_bytes(
                content,
                expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
            )
            event = event_artifact.value
            assert isinstance(event, WorkflowEvent)
            if (
                binding.artifact_type != WorkflowArtifactType.WORKFLOW_EVENT.value
                or event_artifact.artifact_id != binding.artifact_id
                or event.plan_id != plan_artifact.artifact_id
                or event.candidate != plan.candidate
                or event.sensitivity != plan.sensitivity
                or event.sequence != index
                or event.previous_event_id != previous_id
            ):
                raise WorkflowRuntimeError("Workflow State/Event chain is inconsistent.")
            chain.append((binding, event_artifact, event))
            previous_id = event_artifact.artifact_id
        latest_artifact = parse_workflow_artifact_bytes(
            event_bytes[-1],
            expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
        )
        latest = latest_artifact.value
        assert isinstance(latest, WorkflowEvent)
        if (
            latest_artifact.artifact_id != state.latest_event.artifact_id
            or latest.sequence != state.transition_count
            or latest.after_status is not state.status
            or latest.scheduler_event_head_after != state.scheduler_event_head_sha256
            or latest.recorded_at != state.recorded_at
        ):
            raise WorkflowRuntimeError("Workflow State does not reproduce its latest Event.")
        self._validate_event_chain_semantics(
            plan_artifact.artifact_id,
            plan,
            state_artifact,
            state,
            tuple(chain),
            publication,
            root,
            scheduler_state,
            publication_observation,
        )
        return plan, state, publication_observation

    @staticmethod
    def _validate_event_chain_semantics(
        plan_id: str,
        plan: IntegratedPlan,
        state_artifact: LoadedWorkflowArtifact,
        state: WorkflowState,
        chain: tuple[tuple[NativeArtifactBinding, LoadedWorkflowArtifact, WorkflowEvent], ...],
        publication: WorkflowArtifactStorePort,
        root: Path,
        scheduler_state: Path,
        publication_observation: WorkflowPublicationObservation,
    ) -> None:
        """Reproduce every M8 Event from its exact prior and adopted State."""

        prior_states: list[tuple[LoadedWorkflowArtifact, WorkflowState] | None] = []
        for index, (_, _, event) in enumerate(chain, start=1):
            if index == 1:
                prior_states.append(None)
                continue
            if event.prior_state is None:
                raise WorkflowRuntimeError("Workflow Event semantic prior State is missing.")
            try:
                content = publication.load(event.prior_state.reference, 16 * 1024 * 1024)
                artifact = parse_workflow_artifact_bytes(
                    content,
                    expected_type=WorkflowArtifactType.WORKFLOW_STATE,
                )
            except (OSError, RuntimeError, WorkflowContractError) as exc:
                raise WorkflowRuntimeError(
                    "Workflow Event semantic prior State could not be loaded."
                ) from exc
            loaded_prior = artifact.value
            assert isinstance(loaded_prior, WorkflowState)
            if artifact.artifact_id != event.prior_state.artifact_id:
                raise WorkflowRuntimeError("Workflow Event semantic prior State drifted.")
            prior_states.append((artifact, loaded_prior))

        for index, (binding, event_artifact, event) in enumerate(chain, start=1):
            prior_entry = prior_states[index - 1]
            orphan_adopted_by_recovery = (
                index < len(chain)
                and chain[index][2].cause is WorkflowEventCause.RECOVERY_OBSERVED
                and chain[index][2].prior_state_id == event.prior_state_id
            )
            after_entry = (
                (state_artifact, state)
                if index == len(chain) or orphan_adopted_by_recovery
                else prior_states[index]
            )
            if after_entry is None:
                raise WorkflowRuntimeError("Workflow Event semantic adopted State is missing.")
            _, after = after_entry
            prior_artifact = None if prior_entry is None else prior_entry[0]
            prior = None if prior_entry is None else prior_entry[1]
            expected_prefix = tuple(item[0] for item in chain[:index])
            if (
                after.plan_id != plan_id
                or after.candidate != plan.candidate
                or after.sensitivity != plan.sensitivity
                or event.after_status is not after.status
                or event.scheduler_event_head_after != after.scheduler_event_head_sha256
                or (
                    not orphan_adopted_by_recovery
                    and (
                        after.event_chain != expected_prefix
                        or after.latest_event != binding
                        or after.transition_count != index
                        or after.recorded_at != event.recorded_at
                    )
                )
            ):
                raise WorkflowRuntimeError(
                    "Workflow Event semantic adopted State does not reproduce."
                )
            if prior is None:
                if (
                    event.prior_state_id is not None
                    or event.prior_state is not None
                    or event.before_status is not TaskState.PLANNED
                ):
                    raise WorkflowRuntimeError("Workflow Event semantic genesis is invalid.")
            else:
                assert prior_artifact is not None
                chain_before = tuple(item[0] for item in chain[: index - 1])
                recovery_extension = event.cause is WorkflowEventCause.RECOVERY_OBSERVED
                if (
                    event.prior_state_id != prior_artifact.artifact_id
                    or event.prior_state is None
                    or event.prior_state.artifact_id != prior_artifact.artifact_id
                    or prior.plan_id != plan_id
                    or prior.candidate != plan.candidate
                    or prior.sensitivity != plan.sensitivity
                    or (
                        recovery_extension
                        and (
                            chain_before[: prior.transition_count] != prior.event_chain
                            or event.previous_event_id != chain_before[-1].artifact_id
                        )
                    )
                    or (
                        not recovery_extension
                        and (
                            prior.event_chain != chain_before
                            or prior.latest_event.artifact_id != event.previous_event_id
                            or prior.transition_count != index - 1
                        )
                    )
                    or event.before_status is not prior.status
                    or event.scheduler_event_head_before != prior.scheduler_event_head_sha256
                    or _parse_utc(event.recorded_at) < _parse_utc(prior.recorded_at)
                ):
                    raise WorkflowRuntimeError(
                        "Workflow Event semantic prior State does not reproduce."
                    )
            if index > 1 and _parse_utc(event.recorded_at) < _parse_utc(
                chain[index - 2][2].recorded_at
            ):
                raise WorkflowRuntimeError("Workflow Event semantic timestamps are not monotonic.")
            if event_artifact.artifact_id != binding.artifact_id:
                raise WorkflowRuntimeError("Workflow Event semantic identity drifted.")
            protected = tuple(
                sorted(
                    item.effect_id
                    for item in plan.protected_effects
                    if item.effect_id in event.native_output_ids
                )
            )
            approvals = tuple(
                sorted(item for item in after.approval_ids if item in event.native_output_ids)
            )
            input_ids = set(event.native_input_ids)
            structural_inputs = {plan_id}
            if prior is not None:
                assert prior_artifact is not None
                structural_inputs.update(
                    {prior_artifact.artifact_id, prior.latest_event.artifact_id}
                )
            scheduler_inputs = {
                item for item in input_ids if item.startswith("M6-SCHEDULER-STATE-")
            }
            allowed_scheduler_inputs = (
                scheduler_inputs
                if prior is None
                else {prior.scheduler_state_id, after.scheduler_state_id}
            )
            output_ids = set(event.native_output_ids)
            message_outputs = {item for item in output_ids if item.startswith("M6-MESSAGE-")}
            effect_outputs = {item for item in output_ids if item.startswith("M8-EFFECT-")}
            approval_outputs = {item for item in output_ids if item.startswith("APR-")}
            known_effects = {item.effect_id for item in plan.protected_effects}
            known_tasks = {item.task_id for item in plan.tasks}
            structurally_expected_outputs = {
                after.scheduler_state_id,
                *message_outputs,
                *effect_outputs,
                *approval_outputs,
            }
            special_event = event.cause in {
                WorkflowEventCause.RECOVERY_OBSERVED,
                WorkflowEventCause.PLAN_SUPERSEDED,
                WorkflowEventCause.OUTCOME_PRODUCED,
            } or event.actor == "M8 workflow observation finalizer"
            regular_identity_invalid = not special_event and (
                len(scheduler_inputs) != 1
                or not scheduler_inputs <= allowed_scheduler_inputs
                or input_ids != structural_inputs | scheduler_inputs
                or not effect_outputs <= known_effects
                or not approval_outputs <= set(after.approval_ids)
                or output_ids != structurally_expected_outputs
                or (event.task_id is not None and event.task_id not in known_tasks)
            )
            expected_effect = (
                EffectDisposition.AMBIGUOUS
                if after.ambiguities
                else EffectDisposition.REVALIDATED
                if protected
                else EffectDisposition.BLOCKED
                if event.cause is WorkflowEventCause.APPROVAL_BLOCKED
                else EffectDisposition.NOT_APPLICABLE
            )
            expected_cause = _semantic_event_cause(
                event,
                prior,
                after,
                protected,
                approvals,
            )
            observation_event = event.actor == "M8 workflow observation finalizer"
            if (
                event.plan_id != plan_id
                or event.candidate != plan.candidate
                or event.sensitivity != plan.sensitivity
                or (not observation_event and event.cause is not expected_cause)
                or (not observation_event and event.effect_disposition is not expected_effect)
                or event.effect_id != (protected[0] if len(protected) == 1 else None)
                or event.approval_id != (approvals[0] if len(approvals) == 1 else None)
                or regular_identity_invalid
                or (
                    event.cause is not WorkflowEventCause.OUTCOME_PRODUCED
                    and after.scheduler_state_id not in event.native_output_ids
                )
            ):
                raise WorkflowRuntimeError("Workflow Event semantic fields do not reproduce.")
            if observation_event:
                cause = _terminal_observation_cause(event)
                source_ids = tuple(
                    sorted(
                        set(event.native_input_ids)
                        - {plan_id, after.scheduler_state_id}
                    )
                )
                expected_ambiguities = (
                    (WorkflowTerminalObservationCause.EXTERNAL_EFFECT_AMBIGUOUS.value,)
                    if cause
                    is WorkflowTerminalObservationCause.EXTERNAL_EFFECT_AMBIGUOUS
                    else ()
                )
                observation_store = SQLiteSchedulerStore(scheduler_state, root)
                observation_native_artifact = _replay_scheduler_state(
                    observation_store,
                    after.scheduler_event_sequence,
                )
                observation_native = observation_native_artifact.value
                assert isinstance(observation_native, SchedulerState)
                if observation_native_artifact.artifact_id != after.scheduler_state_id:
                    raise WorkflowRuntimeError(
                        "Workflow observation State does not match M6 event replay."
                    )
                expected_observations = _derive_native_observations(
                    plan,
                    observation_native,
                    observation_store,
                    root,
                    publication_observation,
                )
                if (
                    prior is not None
                    or event.sequence != 1
                    or event.cause is not WorkflowEventCause.GATE_EVALUATED
                    or event.native_output_ids != (after.scheduler_state_id,)
                    or not source_ids
                    or event.task_id is not None
                    or event.effect_id is not None
                    or event.approval_id is not None
                    or after.status is not TaskState.BLOCKED
                    or after.blockers
                    != (WorkflowBlocker(cause.value, source_ids),)
                    or after.ambiguities != expected_ambiguities
                    or after.observation_artifacts != expected_observations.bindings
                    or after.solver_verification_ids
                    != expected_observations.solver_verification_ids
                    or after.evidence_ids != expected_observations.evidence_ids
                    or after.review_ids != expected_observations.review_ids
                    or event.effect_disposition
                    is not (
                        EffectDisposition.AMBIGUOUS
                        if expected_ambiguities
                        else EffectDisposition.BLOCKED
                    )
                ):
                    raise WorkflowRuntimeError(
                        "Workflow Event semantic terminal observation does not reproduce."
                    )
            elif event.cause not in {
                WorkflowEventCause.RECOVERY_OBSERVED,
                WorkflowEventCause.PLAN_SUPERSEDED,
                WorkflowEventCause.OUTCOME_PRODUCED,
            }:
                expected_key = _idempotency_key(
                    plan_id,
                    index,
                    None if prior_artifact is None else prior_artifact.artifact_id,
                    after.scheduler_event_head_sha256,
                )
                if (
                    event.actor != "M8 workflow runtime"
                    or event.idempotency_key != expected_key
                    or event.reason_codes
                    != _transition_reason_codes(
                        event.cause,
                        protected,
                        approvals,
                        after.ambiguities,
                    )
                ):
                    raise WorkflowRuntimeError(
                        "Workflow Event semantic runtime disposition does not reproduce."
                    )
            elif event.cause is WorkflowEventCause.PLAN_SUPERSEDED:
                if prior_artifact is None or prior is None:
                    raise WorkflowRuntimeError(
                        "Workflow Event semantic supersession prior State is missing."
                    )
                successor_ids = tuple(
                    item
                    for item in event.native_input_ids
                    if item.startswith("M8-DEVELOPMENT-INTENT-")
                )
                if (
                    len(successor_ids) != 1
                    or event.native_input_ids
                    != tuple(
                        sorted(
                            {
                                plan_id,
                                prior_artifact.artifact_id,
                                prior.latest_event.artifact_id,
                                prior.scheduler_state_id,
                                successor_ids[0],
                            }
                        )
                    )
                    or event.native_output_ids != (prior.scheduler_state_id,)
                    or event.task_id is not None
                    or event.effect_id is not None
                    or event.approval_id is not None
                    or event.actor != "M8 workflow supersession service"
                    or event.idempotency_key
                    != _supersession_idempotency(
                        plan_id,
                        prior_artifact.artifact_id,
                        successor_ids[0],
                    )
                    or event.reason_codes
                    != tuple(
                        sorted(
                            {
                                "plan-superseded",
                                "predecessor-authority-preserved",
                                *prior.ambiguities,
                            }
                        )
                    )
                ):
                    raise WorkflowRuntimeError(
                        "Workflow Event semantic supersession disposition does not reproduce."
                    )
            elif event.cause is WorkflowEventCause.RECOVERY_OBSERVED:
                if prior_artifact is None or prior is None:
                    raise WorkflowRuntimeError(
                        "Workflow Event semantic recovery prior State is missing."
                    )
                from sdaqf.application.workflow_recovery import _recovery_idempotency

                orphan_ids = tuple(
                    item[0].artifact_id for item in chain[prior.transition_count : index - 1]
                )
                expected_inputs = tuple(
                    sorted(
                        {
                            plan_id,
                            prior_artifact.artifact_id,
                            prior.latest_event.artifact_id,
                            after.scheduler_state_id,
                            *orphan_ids,
                        }
                    )
                )
                if (
                    event.actor != "M8 workflow recovery service"
                    or event.idempotency_key
                    != _recovery_idempotency(
                        plan_id,
                        prior_artifact.artifact_id,
                        after.scheduler_state_id,
                        orphan_ids,
                    )
                    or event.native_input_ids != expected_inputs
                    or event.native_output_ids != (after.scheduler_state_id,)
                    or event.task_id is not None
                    or event.effect_id is not None
                    or event.approval_id is not None
                    or event.reason_codes
                    != tuple(sorted({"recovery-observed", "source-preserved", *after.ambiguities}))
                ):
                    raise WorkflowRuntimeError(
                        "Workflow Event semantic recovery disposition does not reproduce."
                    )
            elif event.cause is WorkflowEventCause.OUTCOME_PRODUCED:
                if prior_artifact is None or prior is None:
                    raise WorkflowRuntimeError(
                        "Workflow Event semantic Outcome prior State is missing."
                    )
                from sdaqf.application.workflow_outcome import _outcome_idempotency

                expected_inputs = tuple(
                    sorted(
                        {
                            plan_id,
                            prior_artifact.artifact_id,
                            prior.latest_event.artifact_id,
                            prior.scheduler_state_id,
                        }
                    )
                )
                if (
                    event.actor != "M8 workflow outcome service"
                    or event.idempotency_key
                    != _outcome_idempotency(
                        plan_id,
                        prior_artifact.artifact_id,
                    )
                    or event.native_input_ids != expected_inputs
                    or event.native_output_ids
                    or event.task_id is not None
                    or event.effect_id is not None
                    or event.approval_id is not None
                    or event.reason_codes != ("outcome-produced",)
                ):
                    raise WorkflowRuntimeError(
                        "Workflow Event semantic Outcome disposition does not reproduce."
                    )

    def _artifact_store(self, root: Path) -> WorkflowArtifactStorePort:
        return ExclusiveWorkflowArtifactStore(root) if self._store is None else self._store

    def _terminal_cause(
        self,
        state: WorkflowState,
        root: Path,
    ) -> WorkflowEventCause | None:
        latest_artifact = parse_workflow_artifact_bytes(
            self._artifact_store(root).load(state.latest_event.reference, 1_048_576),
            expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
        )
        if latest_artifact.artifact_id != state.latest_event.artifact_id:
            raise WorkflowRuntimeError("Workflow terminal Event binding drifted.")
        latest = latest_artifact.value
        assert isinstance(latest, WorkflowEvent)
        if latest.cause in {
            WorkflowEventCause.OUTCOME_PRODUCED,
            WorkflowEventCause.PLAN_SUPERSEDED,
        }:
            return latest.cause
        return None

    @staticmethod
    def _validate_scheduler_lineage(
        plan: IntegratedPlan,
        prior: WorkflowState | None,
        store: SQLiteSchedulerStore,
        current: SchedulerState,
    ) -> None:
        if current.graph_id != plan.task_graph.artifact_id or current.candidate != plan.candidate:
            raise WorkflowRuntimeError("Scheduler database is stale for this Plan.")
        if prior is None:
            return
        if (
            prior.scheduler_graph_id != current.graph_id
            or current.event_sequence < prior.scheduler_event_sequence
        ):
            raise WorkflowRuntimeError("Scheduler history moved behind Workflow State.")
        if current.event_sequence == prior.scheduler_event_sequence:
            if (
                current.event_head_sha256 != prior.scheduler_event_head_sha256
                or store.status().artifact_id != prior.scheduler_state_id
            ):
                raise WorkflowRuntimeError("Scheduler projection drifted without an event.")
            return
        exported = store.export(
            "events",
            after_sequence=prior.scheduler_event_sequence - 1,
            limit=1,
        )
        if not exported or event_digest(exported[0]) != prior.scheduler_event_head_sha256:
            raise WorkflowRuntimeError("Scheduler history does not extend prior Workflow State.")

    @staticmethod
    def _revalidate_protected_effects(
        plan: IntegratedPlan,
        tick: SchedulerTick,
        scheduler_state: Path,
        root: Path,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        effects = {item.task_id: item for item in plan.protected_effects}
        if not effects or not tick.outgoing:
            return (), ()
        state = tick.state.value
        assert isinstance(state, SchedulerState)
        projections = {item.task_id: item for item in state.tasks}
        store = SQLiteSchedulerStore(scheduler_state, root)
        leases = tuple(
            (artifact.artifact_id, artifact.value)
            for artifact in store.evidence_history(
                "leases",
                through_event_sequence=state.event_sequence,
            )
            if isinstance(artifact.value, Lease)
        )
        events = tuple(
            artifact.value
            for artifact in store.evidence_history(
                "events",
                through_event_sequence=state.event_sequence,
            )
            if isinstance(artifact.value, SchedulerEvent)
        )
        protected: set[str] = set()
        approvals: set[str] = set()
        for artifact in tick.outgoing:
            message = artifact.value
            if not isinstance(message, MailboxMessage) or message.task_id not in effects:
                continue
            if message.message_type not in {
                MessageType.DISPATCH_INTENT,
                MessageType.WORKTREE_REQUEST,
            }:
                continue
            effect = effects[message.task_id]
            projection = projections[message.task_id]
            current = tuple(
                lease
                for lease_id, lease in leases
                if lease.task_id == message.task_id
                and lease.status is LeaseStatus.CURRENT
                and lease_id == message.lease_id
                and lease.fence == message.fence
                and lease.attempt == message.attempt
                and lease.idempotency_key == message.idempotency_key
                and lease.candidate == message.candidate
            )
            if (
                len(current) != 1
                or projection.state is not TaskState.RUNNING
                or projection.fence != message.fence
                or projection.attempt != message.attempt
                or message.candidate != plan.candidate
                or message.graph_id != plan.task_graph.artifact_id
            ):
                raise WorkflowRuntimeError("Protected effect lacks a fresh fenced Lease.")
            consumed = tuple(
                event
                for event in events
                if event.cause == "approval-consumed"
                and event.task_id == message.task_id
                and event.lease_id == message.lease_id
                and event.approval_id is not None
            )
            if effect.approval_types and len({item.approval_id for item in consumed}) < len(
                effect.approval_types
            ):
                raise WorkflowRuntimeError("Protected effect lacks fresh native approval.")
            protected.add(effect.effect_id)
            approvals.update(item.approval_id for item in consumed if item.approval_id is not None)
        return tuple(sorted(protected)), tuple(sorted(approvals))

    def _revalidate_plan_effects_before_tick(
        self,
        plan: IntegratedPlan,
        root: Path,
    ) -> None:
        """Recompute exact Tool/target/effect policy before M6 may consume approval."""

        try:
            graph_path = self._artifact_store(root).load(
                plan.task_graph.reference,
                16 * 1024 * 1024,
            )
            graph_artifact = parse_scheduler_artifact_bytes(
                graph_path,
                expected_type=SchedulerArtifactType.TASK_GRAPH,
                root=root,
            )
        except (OSError, RuntimeError, WorkflowContractError) as exc:
            raise WorkflowRuntimeError(
                "Protected effect Task Graph could not be replayed."
            ) from exc
        graph = graph_artifact.value
        assert isinstance(graph, TaskGraph)
        reproduced = IntegratedPlanner._protected_effects(
            graph,
            root,
            plan.task_graph.artifact_id,
        )
        if reproduced != plan.protected_effects:
            raise WorkflowRuntimeError("Protected effect identity or Tool policy drifted.")

    @staticmethod
    def _ambiguities(
        store: SQLiteSchedulerStore,
        state: SchedulerState,
    ) -> tuple[str, ...]:
        result: set[str] = set()
        for task in state.tasks:
            if task.outcome is TaskOutcome.UNKNOWN:
                result.add("external-effect-ambiguous")
            for blocker in task.blockers:
                if "ambiguous" in blocker.code or "unknown" in blocker.code:
                    result.add("external-effect-ambiguous")
        for artifact in store.evidence_history(
            "worktrees",
            through_event_sequence=state.event_sequence,
        ):
            value = artifact.value
            if (
                artifact.artifact_id in state.worktree_lease_ids
                and isinstance(value, WorktreeLease)
                and value.ambiguous
            ):
                result.add("external-effect-ambiguous")
        return tuple(sorted(result))

    @staticmethod
    def _event_cause(
        plan: IntegratedPlan,
        prior: WorkflowState | None,
        state: SchedulerState,
        protected: tuple[str, ...],
        approvals: tuple[str, ...],
        ambiguities: tuple[str, ...],
    ) -> WorkflowEventCause:
        if ambiguities:
            return WorkflowEventCause.AMBIGUITY_RECORDED
        if any(
            blocker.code.startswith("approval-")
            for task in state.tasks
            for blocker in task.blockers
        ):
            return WorkflowEventCause.APPROVAL_BLOCKED
        if protected and approvals:
            return WorkflowEventCause.APPROVAL_REVALIDATED
        if prior is None:
            return WorkflowEventCause.RUNTIME_STARTED
        return WorkflowEventCause.SCHEDULER_ADVANCED

    def _derive_state(
        self,
        plan_id: str,
        plan: IntegratedPlan,
        native: SchedulerState,
        prior_events: tuple[NativeArtifactBinding, ...],
        latest_event: NativeArtifactBinding,
        recorded_at: str,
        store: SQLiteSchedulerStore,
        root: Path,
        publication_observation: WorkflowPublicationObservation,
        *,
        latest_cause: WorkflowEventCause | None = None,
    ) -> WorkflowState:
        tasks = _task_projections(native)
        approval_ids = tuple(
            sorted(
                {
                    event.approval_id
                    for artifact in store.evidence_history(
                        "events",
                        through_event_sequence=native.event_sequence,
                    )
                    if isinstance((event := artifact.value), SchedulerEvent)
                    and event.sequence <= native.event_sequence
                    and event.cause == "approval-consumed"
                    and event.approval_id is not None
                }
            )
        )
        ambiguities = self._ambiguities(store, native)
        observations = _derive_native_observations(
            plan,
            native,
            store,
            root,
            publication_observation,
        )
        gates = _derive_gates(
            plan,
            tasks,
            observations.evidence_ids if observations.g2_passed else (),
            observations.review_ids if observations.g3_passed else (),
            observations.handoff_status,
            observations.g4_result_ids,
            observations.g4_passed,
        )
        blockers = _derive_blockers(plan, tasks, gates, ambiguities)
        status = _derive_status(plan, tasks, blockers, ambiguities)
        measurements = _derive_measurements(
            plan_id,
            plan,
            native,
            tasks,
            approval_ids,
            ambiguities,
            observations=observations,
            event_chain=(*prior_events, latest_event),
            store=store,
            root=root,
            latest_cause=latest_cause,
        )
        return WorkflowState(
            plan_id=plan_id,
            candidate=plan.candidate,
            sensitivity=plan.sensitivity,
            status=status,
            scheduler_graph_id=native.graph_id,
            scheduler_state_id=artifact_from_scheduler_state(native),
            scheduler_event_sequence=native.event_sequence,
            scheduler_event_head_sha256=native.event_head_sha256,
            tasks=tasks,
            solver_verification_ids=observations.solver_verification_ids,
            evidence_ids=observations.evidence_ids,
            review_ids=observations.review_ids,
            approval_ids=approval_ids,
            gates=gates,
            handoff_id=observations.handoff_id,
            handoff_status=observations.handoff_status,
            blockers=blockers,
            ambiguities=ambiguities,
            measurements=measurements,
            observation_artifacts=observations.bindings,
            event_chain=(*prior_events, latest_event),
            latest_event=latest_event,
            transition_count=len(prior_events) + 1,
            recorded_at=recorded_at,
        )

    def _require_exact_state(
        self,
        plan_id: str,
        plan: IntegratedPlan,
        state_artifact: LoadedWorkflowArtifact,
        state: WorkflowState,
        native: SchedulerState,
        store: SQLiteSchedulerStore,
        root: Path,
        publication_observation: WorkflowPublicationObservation,
    ) -> None:
        if state.scheduler_event_sequence > native.event_sequence:
            raise WorkflowRuntimeError("Workflow State extends beyond its M6 event prefix.")
        bound_artifact = _replay_scheduler_state(
            store,
            state.scheduler_event_sequence,
        )
        bound_native = bound_artifact.value
        assert isinstance(bound_native, SchedulerState)
        if (
            bound_artifact.artifact_id != state.scheduler_state_id
            or bound_native.graph_id != plan.task_graph.artifact_id
            or bound_native.candidate != plan.candidate
            or bound_native.event_sequence != state.scheduler_event_sequence
            or bound_native.event_head_sha256 != state.scheduler_event_head_sha256
        ):
            raise WorkflowRuntimeError("Workflow State does not match M6 event replay.")
        latest_artifact = parse_workflow_artifact_bytes(
            self._artifact_store(root).load(state.latest_event.reference, 1_048_576),
            expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
        )
        latest = latest_artifact.value
        assert isinstance(latest, WorkflowEvent)
        native_scheduler_inputs = {
            item for item in latest.native_input_ids if item.startswith("M6-SCHEDULER-STATE-")
        }
        native_scheduler_outputs = {
            item for item in latest.native_output_ids if item.startswith("M6-SCHEDULER-STATE-")
        }
        if (
            not (native_scheduler_inputs or native_scheduler_outputs)
            or bound_artifact.artifact_id
            not in (native_scheduler_inputs | native_scheduler_outputs)
            or latest.scheduler_event_head_after != bound_native.event_head_sha256
            or (
                latest.cause is not WorkflowEventCause.OUTCOME_PRODUCED
                and bound_artifact.artifact_id not in latest.native_output_ids
            )
        ):
            raise WorkflowRuntimeError(
                "Workflow Event native Scheduler input/output does not resolve."
            )
        scheduler_events = store.evidence_history(
            "events",
            through_event_sequence=bound_native.event_sequence,
        )
        known_native_ids = {
            plan_id,
            state.latest_event.artifact_id,
            bound_artifact.artifact_id,
            *native_scheduler_inputs,
            *(item.artifact_id for item in state.event_chain),
            *(item.effect_id for item in plan.protected_effects),
            *(item.artifact_id for item in state.observation_artifacts),
            *(item.artifact_id for item in store.evidence_history(
                "leases",
                through_event_sequence=bound_native.event_sequence,
            )),
            *(item.artifact_id for item in store.evidence_history(
                "messages",
                through_event_sequence=bound_native.event_sequence,
            )),
            *(item.artifact_id for item in scheduler_events),
            *(item.artifact_id for item in store.evidence_history(
                "budget",
                through_event_sequence=bound_native.event_sequence,
            )),
            *(item.artifact_id for item in store.evidence_history(
                "worktrees",
                through_event_sequence=bound_native.event_sequence,
            )),
            plan.intent.artifact_id,
            plan.context_graph.artifact_id,
            plan.context_query.artifact_id,
            plan.context_selection.artifact_id,
            plan.context_snapshot.artifact_id,
            *(item.artifact_id for item in plan.solver_requests),
            *(
                scheduler_event.approval_id
                for artifact in scheduler_events
                if isinstance((scheduler_event := artifact.value), SchedulerEvent)
                and scheduler_event.approval_id is not None
            ),
        }
        if latest.prior_state is not None:
            known_native_ids.add(latest.prior_state.artifact_id)
        unresolved = (set(latest.native_input_ids) | set(latest.native_output_ids)) - (
            known_native_ids
        )
        if unresolved:
            raise WorkflowRuntimeError(
                "Workflow Event native input/output identity is missing or stale."
            )
        if latest.cause in {
            WorkflowEventCause.PLAN_SUPERSEDED,
            WorkflowEventCause.OUTCOME_PRODUCED,
        }:
            if latest.prior_state is None:
                raise WorkflowRuntimeError("Terminal Event lacks its prior State binding.")
            prior_artifact = parse_workflow_artifact_bytes(
                self._artifact_store(root).load(
                    latest.prior_state.reference,
                    16 * 1024 * 1024,
                ),
                expected_type=WorkflowArtifactType.WORKFLOW_STATE,
            )
            prior = prior_artifact.value
            assert isinstance(prior, WorkflowState)
            if prior.scheduler_state_id != state.scheduler_state_id:
                raise WorkflowRuntimeError(
                    "Terminal Workflow State does not preserve its native Scheduler State."
                )
            self._require_exact_state(
                plan_id,
                plan,
                prior_artifact,
                prior,
                bound_native,
                store,
                root,
                publication_observation,
            )
            expected = replace(
                prior,
                status=(
                    TaskState.SUPERSEDED
                    if latest.cause is WorkflowEventCause.PLAN_SUPERSEDED
                    else prior.status
                ),
                blockers=(
                    tuple(
                        sorted(
                            {
                                *prior.blockers,
                                WorkflowBlocker(
                                    "predecessor-superseded",
                                    tuple(
                                        item
                                        for item in latest.native_input_ids
                                        if item.startswith("M8-DEVELOPMENT-INTENT-")
                                    ),
                                ),
                            },
                            key=lambda item: (item.code, item.references),
                        )
                    )
                    if latest.cause is WorkflowEventCause.PLAN_SUPERSEDED
                    else prior.blockers
                ),
                observation_artifacts=state.observation_artifacts,
                event_chain=(*prior.event_chain, state.latest_event),
                latest_event=state.latest_event,
                transition_count=prior.transition_count + 1,
                recorded_at=state.recorded_at,
            )
        elif latest.actor == "M8 workflow observation finalizer":
            cause = _terminal_observation_cause(latest)
            source_ids = tuple(
                sorted(
                    set(latest.native_input_ids)
                    - {plan_id, bound_artifact.artifact_id}
                )
            )
            observation = WorkflowTerminalObservation(
                cause,
                bound_artifact.artifact_id,
                scheduler_events[-1].artifact_id,
                source_ids,
            )
            if latest.idempotency_key != _observation_idempotency(plan_id, observation):
                raise WorkflowRuntimeError(
                    "Workflow terminal observation idempotency does not reproduce."
                )
            expected = self._observation_state(
                plan_id,
                plan,
                bound_native,
                observation,
                state.latest_event,
                state.recorded_at,
                store,
                root,
                publication_observation,
            )
        else:
            expected = self._derive_state(
                plan_id,
                plan,
                bound_native,
                state.event_chain[:-1],
                state.latest_event,
                state.recorded_at,
                store,
                root,
                publication_observation,
            )
        expected_artifact = artifact_from_value(
            WorkflowArtifactType.WORKFLOW_STATE,
            expected,
        )
        if expected != state or expected_artifact.artifact_id != state_artifact.artifact_id:
            raise WorkflowRuntimeError("Workflow State is not the exact native-derived projection.")
        if latest.prior_state is not None and latest.cause not in {
            WorkflowEventCause.PLAN_SUPERSEDED,
            WorkflowEventCause.OUTCOME_PRODUCED,
        }:
            prior_artifact = parse_workflow_artifact_bytes(
                self._artifact_store(root).load(
                    latest.prior_state.reference,
                    16 * 1024 * 1024,
                ),
                expected_type=WorkflowArtifactType.WORKFLOW_STATE,
            )
            prior = prior_artifact.value
            assert isinstance(prior, WorkflowState)
            self._require_exact_state(
                plan_id,
                plan,
                prior_artifact,
                prior,
                bound_native,
                store,
                root,
                publication_observation,
            )

    @staticmethod
    def _project_status(
        plan: IntegratedPlan,
        native: SchedulerState,
        store: SQLiteSchedulerStore,
        root: Path,
        publication_observation: WorkflowPublicationObservation,
    ) -> TaskState:
        tasks = _task_projections(native)
        observations = _derive_native_observations(
            plan,
            native,
            store,
            root,
            publication_observation,
        )
        gates = _derive_gates(
            plan,
            tasks,
            observations.evidence_ids if observations.g2_passed else (),
            observations.review_ids if observations.g3_passed else (),
            observations.handoff_status,
            observations.g4_result_ids,
            observations.g4_passed,
        )
        ambiguities = WorkflowRuntimeService._ambiguities(store, native)
        blockers = _derive_blockers(plan, tasks, gates, ambiguities)
        return _derive_status(plan, tasks, blockers, ambiguities)


def artifact_from_scheduler_state(state: SchedulerState) -> str:
    """Use the native M6 identity algorithm without creating a second authority."""

    from sdaqf.application.scheduler_contracts import artifact_from_value
    from sdaqf.domain.scheduler import SchedulerArtifactType

    return artifact_from_value(SchedulerArtifactType.SCHEDULER_STATE, state).artifact_id


def _replay_scheduler_state(
    store: SQLiteSchedulerStore,
    event_sequence: int,
) -> LoadedSchedulerArtifact:
    """Load an exact historical M6 projection from the adapter authority."""

    try:
        return store.historical_status(event_sequence)
    except SchedulerAdapterError as exc:
        raise WorkflowRuntimeError("Historical native Scheduler replay failed closed.") from exc


def _task_projections(native: SchedulerState) -> tuple[WorkflowTaskProjection, ...]:
    return tuple(
        WorkflowTaskProjection(
            task_id=item.task_id,
            state=item.state,
            outcome=item.outcome,
            attempt=item.attempt,
            fence=item.fence,
            blocker_codes=tuple(sorted(blocker.code for blocker in item.blockers)),
        )
        for item in sorted(native.tasks, key=lambda item: item.task_id)
    )


def _derive_native_observations(
    plan: IntegratedPlan,
    native: SchedulerState,
    store: SQLiteSchedulerStore,
    root: Path,
    publication_observation: WorkflowPublicationObservation,
) -> NativeWorkflowObservations:
    """Adopt only strict M3/M7 artifacts referenced by accepted M6 results."""

    artifact_store = ExclusiveWorkflowArtifactStore(root)
    graph_bytes = artifact_store.load(plan.task_graph.reference, 16 * 1024 * 1024)
    graph_artifact = parse_scheduler_artifact_bytes(
        graph_bytes,
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    graph = graph_artifact.value
    assert isinstance(graph, TaskGraph)
    baseline_bytes = artifact_store.load(plan.requirement_baseline, 16 * 1024 * 1024)
    baseline_path = root / plan.requirement_baseline.path
    if hashlib.sha256(baseline_bytes).hexdigest().upper() != plan.requirement_baseline.sha256:
        raise WorkflowRuntimeError("Requirement Baseline observation drifted.")
    baseline = load_baseline(baseline_path)
    if plan.completion_profile is CompletionProfile.PLAN_ONLY:
        return NativeWorkflowObservations((), (), (), (), None, None, False, False)
    completed_task_ids = {
        task.task_id for task in native.tasks if task.state is TaskState.COMPLETED
    }
    messages = {
        artifact.artifact_id: artifact.value
        for artifact in store.completed_task_result_messages()
        if isinstance(artifact.value, MailboxMessage)
        and artifact.value.message_type is MessageType.TASK_RESULT
        and artifact.value.task_id in completed_task_ids
    }
    task_by_id = {item.task_id: item for item in graph.tasks}
    bindings: dict[str, NativeArtifactBinding] = {}
    solver_ids: set[str] = set()
    evidence_ids: set[str] = set()
    review_ids: set[str] = set()
    ledgers: list[EvidenceLedger] = []
    reviews: list[IndependentReview] = []
    manifest = None
    ui_validation = None
    release_candidate = None
    ui_observation_ids: set[str] = set()
    release_candidate_ids: set[str] = set()
    handoff_id: str | None = None
    handoff_status: str | None = None
    solver_status_counts: dict[str, int] = {}
    claim_count = 0
    verified_claim_count = 0
    unverified_claim_count = 0
    evidence_known_problem_count = 0
    missing_evidence_count = 0
    handoff_created_count = 0
    handoff_resume_failure_count = 0
    handoff_incomplete_item_count = 0
    handoff_open_decision_count = 0
    handoff_known_problem_count = 0
    covered_requirement_ids: set[str] = set()
    requirement_coverage_available = False
    agent_results_by_task: dict[str, AgentResult] = {}
    agent_result_references_by_task: dict[str, ArtifactReference] = {}
    agent_result_digests: set[str] = set()
    for message_id in sorted(messages):
        message = messages[message_id]
        if message.task_id is None or message.task_id not in task_by_id:
            raise WorkflowRuntimeError("Accepted result does not map to the Task Graph.")
        try:
            result, reference = load_task_agent_result(root, graph, message)
            artifact_store.load(reference, 16 * 1024 * 1024)
        except (ContractError, OSError, ValueError) as exc:
            raise WorkflowRuntimeError("Accepted Agent Result failed validation.") from exc
        if reference.sha256 in agent_result_digests:
            raise WorkflowRuntimeError("Accepted Agent Result reference is duplicated.")
        agent_result_digests.add(reference.sha256)
        agent_results_by_task[message.task_id] = result
        agent_result_references_by_task[message.task_id] = reference
        identifier = f"M2-AGENT-RESULT-{reference.sha256}"
        bindings[identifier] = NativeArtifactBinding(
            "agent-result",
            identifier,
            reference,
            True,
        )
        try:
            resolved_skills = resolve_skill_capabilities(
                root,
                task_by_id[message.task_id].required_capabilities,
            )
        except SkillContractError as exc:
            raise WorkflowRuntimeError("Accepted Skill provenance is invalid.") from exc
        for skill in resolved_skills:
            skill_identifier = f"M2-SKILL-{skill.digest}"
            bindings[skill_identifier] = NativeArtifactBinding(
                "skill",
                skill_identifier,
                skill.reference,
                True,
            )
    for message_id in sorted(messages):
        message = messages[message_id]
        if message.task_id is None or message.task_id not in task_by_id:
            raise WorkflowRuntimeError("Accepted result does not map to the Task Graph.")
        task = task_by_id[message.task_id]
        agent_result = agent_results_by_task[task.task_id]
        payload = message.to_dict()["payload"]
        assert isinstance(payload, dict)
        raw_references = payload.get("evidence_refs")
        if not isinstance(raw_references, list):
            raise WorkflowRuntimeError("Accepted result evidence references are invalid.")
        review_reference = None
        if task.kind is TaskKind.REVIEW:
            try:
                review_reference = bind_review_task_result_evidence(
                    graph,
                    message,
                    agent_result_references_by_task,
                )
            except ContractError as exc:
                raise WorkflowRuntimeError(
                    "Independent Review lacks exact target Agent Result lineage."
                ) from exc
        solver_types: set[SolverArtifactType] = set()
        for index, raw in enumerate(raw_references):
            try:
                reference = parse_artifact_reference(raw, f"evidence_refs[{index}]")
                artifact_store.load(reference, 16 * 1024 * 1024)
                path = root / reference.path
                if task.kind is TaskKind.SOLVER:
                    loaded = load_solver_artifact(path)
                    solver_types.add(loaded.artifact_type)
                    identifier = loaded.artifact_id
                    artifact_type = loaded.artifact_type.value
                    if loaded.artifact_type is SolverArtifactType.VERIFICATION:
                        verification = loaded.value
                        assert isinstance(verification, SolverVerification)
                        if (
                            not verification.adoption_allowed
                            or verification.candidate != plan.candidate
                            or verification.graph_id != plan.task_graph.artifact_id
                            or verification.task_id != task.task_id
                        ):
                            raise WorkflowRuntimeError(
                                "M7 verification is stale or not adoptable."
                            )
                        solver_ids.add(identifier)
                        solver_status_counts[verification.outcome.value] = (
                            solver_status_counts.get(verification.outcome.value, 0) + 1
                        )
                    elif loaded.artifact_type is not SolverArtifactType.RESULT:
                        raise WorkflowRuntimeError("Solver evidence type is unsupported.")
                elif task.kind is TaskKind.REVIEW:
                    if reference != review_reference:
                        continue
                    candidate_review = load_independent_review(path)
                    if candidate_review.candidate != plan.candidate:
                        raise WorkflowRuntimeError("Independent Review candidate is stale.")
                    if any(
                        target not in agent_results_by_task
                        for target in task.review_targets
                    ):
                        raise WorkflowRuntimeError(
                            "Independent Review target result is unavailable."
                        )
                    try:
                        validate_reviewed_agent_identities(
                            task,
                            agent_result,
                            candidate_review,
                            agent_results_by_task,
                        )
                    except ContractError as exc:
                        raise WorkflowRuntimeError(
                            "Independent Review does not match completed target agents."
                        ) from exc
                    reviews.append(candidate_review)
                    identifier = candidate_review.review_id
                    artifact_type = "independent-review"
                    review_ids.add(identifier)
                elif task.kind is TaskKind.HANDOFF:
                    handoff = load_automated_handoff(path)
                    identifier = f"M3-HANDOFF-{reference.sha256}"
                    artifact_type = "automated-handoff"
                    if handoff_id is not None:
                        raise WorkflowRuntimeError(
                            "Automated Handoff observation slot is duplicated."
                        )
                    if (
                        handoff.baseline_id != plan.requirement_baseline_id
                        or handoff.source_spec_sha256 != plan.candidate.source_spec_sha256
                        or handoff.head != plan.candidate.git_head
                        or handoff.repository_digest != plan.candidate.repository_digest
                        or handoff.incomplete
                        or handoff.open_decisions
                        or handoff.known_problems
                    ):
                        raise WorkflowRuntimeError("Automated Handoff is stale or incomplete.")
                    handoff_id = identifier
                    handoff_status = handoff.status.value
                    handoff_created_count = 1
                    handoff_resume_failure_count = int(
                        handoff.status is not HandoffStatus.COMPLETED
                    )
                    handoff_incomplete_item_count = len(handoff.incomplete)
                    handoff_open_decision_count = len(handoff.open_decisions)
                    handoff_known_problem_count = len(handoff.known_problems)
                elif task.kind is TaskKind.INTEGRATION:
                    record = load_json_object(
                        path,
                        "M8 integration observation",
                        maximum_bytes=16 * 1024 * 1024,
                    )
                    keys = set(record)
                    if "install_evidence_id" in keys:
                        if release_candidate is not None:
                            raise WorkflowRuntimeError(
                                "Release Candidate observation slot is duplicated."
                            )
                        release_candidate = load_release_candidate(path)
                        identifier = f"M3-RELEASE-CANDIDATE-{reference.sha256}"
                        artifact_type = "release-candidate"
                        release_candidate_ids.add(identifier)
                    elif {"ui_present", "observations"} <= keys:
                        if ui_validation is not None:
                            raise WorkflowRuntimeError(
                                "UI validation observation slot is duplicated."
                            )
                        ui_validation = load_ui_validation(path)
                        if ui_validation.candidate != plan.candidate:
                            raise WorkflowRuntimeError("UI validation candidate is stale.")
                        identifier = f"M3-UI-VALIDATION-{reference.sha256}"
                        artifact_type = "ui-validation"
                        ui_observation_ids.add(identifier)
                    elif {"source_spec", "platforms", "ui"} <= keys:
                        if manifest is not None:
                            raise WorkflowRuntimeError(
                                "Project Manifest observation slot is duplicated."
                            )
                        manifest = load_manifest_ui(path)
                        if (
                            manifest.project_id != plan.project_id
                            or manifest.source_spec_sha256 != plan.candidate.source_spec_sha256
                        ):
                            raise WorkflowRuntimeError("Project manifest candidate is stale.")
                        identifier = f"M3-PROJECT-MANIFEST-{reference.sha256}"
                        artifact_type = "project-manifest"
                        ui_observation_ids.add(identifier)
                    else:
                        raise WorkflowRuntimeError("Integration observation type is unsupported.")
                else:
                    candidate_ledger = load_evidence_ledger(path)
                    if (
                        candidate_ledger.baseline_id != plan.requirement_baseline_id
                        or candidate_ledger.source_spec_sha256 != plan.candidate.source_spec_sha256
                        or candidate_ledger.git_head != plan.candidate.git_head
                        or candidate_ledger.repository_digest != plan.candidate.repository_digest
                    ):
                        raise WorkflowRuntimeError("Evidence Ledger candidate is stale.")
                    ledgers.append(candidate_ledger)
                    identifier = f"M3-EVIDENCE-LEDGER-{reference.sha256}"
                    artifact_type = "evidence-ledger"
                    evidence_ids.update(item.evidence_id for item in candidate_ledger.evidence)
                    claim_count += len(candidate_ledger.claims)
                    verified_claim_count += sum(
                        item.state.value == "verified" for item in candidate_ledger.claims
                    )
                    unverified_claim_count += sum(
                        item.state.value in {"implemented", "unverified"}
                        for item in candidate_ledger.claims
                    )
                    evidence_known_problem_count += sum(
                        item.state.value == "known_problem" for item in candidate_ledger.claims
                    )
                    passing_claim_ids = {
                        claim_id
                        for evidence in candidate_ledger.evidence
                        if evidence.status.value == "PASS"
                        for claim_id in evidence.claim_ids
                    }
                    missing_evidence_count += sum(
                        item.claim_id not in passing_claim_ids for item in candidate_ledger.claims
                    )
                    requirement_coverage_available = True
                    covered_requirement_ids.update(
                        requirement_id
                        for item in candidate_ledger.claims
                        if item.claim_id in passing_claim_ids and item.state.value == "verified"
                        for requirement_id in getattr(item, "requirement_ids", ())
                    )
            except WorkflowRuntimeError:
                raise
            except (ContractError, OSError, ValueError) as exc:
                raise WorkflowRuntimeError(
                    "Accepted native observation failed its existing validator."
                ) from exc
            if identifier in bindings:
                raise WorkflowRuntimeError("Accepted native observation is duplicated.")
            bindings[identifier] = NativeArtifactBinding(
                artifact_type,
                identifier,
                reference,
                True,
            )
        if task.kind is TaskKind.SOLVER and solver_types != {
            SolverArtifactType.RESULT,
            SolverArtifactType.VERIFICATION,
        }:
            raise WorkflowRuntimeError(
                "Solver Task Result must bind one Result and one Verification."
            )
    g2_results = tuple(
        ImplementationEvidenceGateService()
        .evaluate(
            baseline,
            ledger,
            candidate=plan.candidate,
            root=root,
        )
        .passed
        for ledger in ledgers
    )
    g2_passed = bool(g2_results) and all(g2_results)
    g3_passed = False
    git = publication_observation.git
    changed_paths = git.changed_paths
    candidate_paths = git.publication_paths
    if reviews:
        g3_passed = all(
            IndependentReviewGateService()
            .evaluate(
                review,
                baseline_id=plan.requirement_baseline_id,
                candidate=plan.candidate,
                changed_paths=changed_paths,
                candidate_paths=candidate_paths,
            )
            .passed
            for review in reviews
        )
    g4_passed = False
    g4_result_ids: tuple[str, ...] = ()
    if (
        len(ledgers) == 1
        and len(reviews) == 1
        and manifest is not None
        and ui_validation is not None
        and release_candidate is not None
    ):
        ledger = ledgers[0]
        review = reviews[0]
        g2 = ImplementationEvidenceGateService().evaluate(
            baseline,
            ledger,
            candidate=plan.candidate,
            root=root,
        )
        g3 = IndependentReviewGateService().evaluate(
            review,
            baseline_id=plan.requirement_baseline_id,
            candidate=plan.candidate,
            changed_paths=changed_paths,
            candidate_paths=candidate_paths,
        )
        ui = UiValidationService().evaluate(
            manifest=manifest,
            candidate=plan.candidate,
            validation=ui_validation,
            root=root,
        )
        g4 = ReleaseCandidateGateService().evaluate(
            root=root,
            baseline=baseline,
            ledger=ledger,
            review=review,
            candidate=release_candidate,
            g2=g2,
            g3=g3,
            ui=ui,
            git=git,
        )
        g4_passed = g4.passed
        digest = hashlib.sha256(canonical_json_bytes(g4.to_dict())).hexdigest().upper()
        g4_result_ids = (f"M3-GATE-G4-{digest}",)
    return NativeWorkflowObservations(
        bindings=tuple(sorted(bindings.values(), key=lambda item: item.artifact_id)),
        solver_verification_ids=tuple(sorted(solver_ids)),
        evidence_ids=tuple(sorted(evidence_ids)),
        review_ids=tuple(sorted(review_ids)),
        handoff_id=handoff_id,
        handoff_status=handoff_status,
        g2_passed=g2_passed,
        g3_passed=g3_passed,
        ui_observation_ids=tuple(sorted(ui_observation_ids)),
        release_candidate_ids=tuple(sorted(release_candidate_ids)),
        g4_result_ids=g4_result_ids,
        g4_passed=g4_passed,
        solver_status_counts=tuple(sorted(solver_status_counts.items())),
        claim_count=claim_count,
        verified_claim_count=verified_claim_count,
        unverified_claim_count=unverified_claim_count,
        evidence_known_problem_count=evidence_known_problem_count,
        missing_evidence_count=missing_evidence_count,
        handoff_created_count=handoff_created_count,
        handoff_resume_failure_count=handoff_resume_failure_count,
        handoff_incomplete_item_count=handoff_incomplete_item_count,
        handoff_open_decision_count=handoff_open_decision_count,
        handoff_known_problem_count=handoff_known_problem_count,
        covered_requirement_ids=tuple(sorted(covered_requirement_ids)),
        requirement_coverage_available=requirement_coverage_available,
    )


def _derive_gates(
    plan: IntegratedPlan,
    tasks: tuple[WorkflowTaskProjection, ...],
    evidence_ids: tuple[str, ...],
    review_ids: tuple[str, ...],
    handoff_status: str | None,
    g4_result_ids: tuple[str, ...],
    g4_passed: bool,
) -> tuple[GateObservation, ...]:
    blocking_plan = tuple(sorted(item.reason_code for item in plan.decisions if item.blocking))
    complete = bool(tasks) and all(item.state is TaskState.COMPLETED for item in tasks)
    gates = []
    for gate_id in plan.required_gate_ids:
        blockers: tuple[str, ...]
        evidence: tuple[str, ...]
        if gate_id == "G1":
            status = GateStatus.PASS if not blocking_plan else GateStatus.FAIL
            blockers = blocking_plan
            evidence = (plan.requirement_baseline_id,)
        elif gate_id == "G2" and complete and evidence_ids and handoff_status == "completed":
            status = GateStatus.PASS
            blockers = ()
            evidence = evidence_ids
        elif gate_id == "G3" and complete and review_ids:
            status = GateStatus.PASS
            blockers = ()
            evidence = review_ids
        elif gate_id == "G4" and complete and g4_passed and g4_result_ids:
            status = GateStatus.PASS
            blockers = ()
            evidence = g4_result_ids
        else:
            status = GateStatus.NOT_VERIFIED
            blockers = (
                ("evidence-unavailable", "handoff-unavailable")
                if gate_id == "G2" and complete
                else (f"{gate_id.casefold()}-not-verified",)
            )
            evidence = ()
        gates.append(
            GateObservation(gate_id, status, tuple(sorted(evidence)), tuple(sorted(blockers)))
        )
    return tuple(gates)


def _derive_blockers(
    plan: IntegratedPlan,
    tasks: tuple[WorkflowTaskProjection, ...],
    gates: tuple[GateObservation, ...],
    ambiguities: tuple[str, ...],
) -> tuple[WorkflowBlocker, ...]:
    blockers: set[tuple[str, tuple[str, ...]]] = set()
    for decision in plan.decisions:
        if decision.blocking:
            blockers.add((decision.reason_code, (decision.subject_id,)))
    for task in tasks:
        for code in task.blocker_codes:
            blockers.add((code, (task.task_id,)))
    for ambiguity in ambiguities:
        blockers.add((ambiguity, (plan.task_graph.artifact_id,)))
    if all(item.state is TaskState.COMPLETED for item in tasks):
        for gate in gates:
            if gate.status is not GateStatus.PASS:
                for code in gate.blocker_codes:
                    blockers.add((code, (gate.gate_id,)))
        gate_status = {item.gate_id: item.status for item in gates}
        if plan.ui_required and gate_status.get("G4") is not GateStatus.PASS:
            blockers.add(("ui-evidence-unavailable", ("G4",)))
    return tuple(WorkflowBlocker(code, references) for code, references in sorted(blockers))


def _derive_status(
    plan: IntegratedPlan,
    tasks: tuple[WorkflowTaskProjection, ...],
    blockers: tuple[WorkflowBlocker, ...],
    ambiguities: tuple[str, ...],
) -> TaskState:
    if plan.completion_profile is CompletionProfile.PLAN_ONLY:
        return TaskState.BLOCKED if blockers else TaskState.COMPLETED
    states = {item.state for item in tasks}
    if TaskState.REJECTED in states:
        return TaskState.REJECTED
    if TaskState.SUPERSEDED in states:
        return TaskState.SUPERSEDED
    if ambiguities or TaskState.BLOCKED in states:
        return TaskState.BLOCKED
    if tasks and all(item.state is TaskState.COMPLETED for item in tasks):
        return TaskState.BLOCKED if blockers else TaskState.COMPLETED
    if TaskState.RUNNING in states:
        return TaskState.RUNNING
    if TaskState.VERIFICATION in states:
        return TaskState.VERIFICATION
    if TaskState.READY in states:
        return TaskState.READY
    return TaskState.PLANNED


def _derive_measurements(
    plan_id: str,
    plan: IntegratedPlan,
    native: SchedulerState,
    tasks: tuple[WorkflowTaskProjection, ...],
    approval_ids: tuple[str, ...],
    ambiguities: tuple[str, ...],
    *,
    observations: NativeWorkflowObservations | None = None,
    event_chain: tuple[NativeArtifactBinding, ...] = (),
    store: SQLiteSchedulerStore | None = None,
    root: Path | None = None,
    latest_cause: WorkflowEventCause | None = None,
) -> tuple[WorkflowMeasurement, ...]:
    observations = observations or NativeWorkflowObservations(
        (), (), (), (), None, None, False, False
    )
    sources = tuple(
        sorted(
            {
                plan_id,
                native.graph_id,
                artifact_from_scheduler_state(native),
                plan.requirement_baseline_id,
                plan.context_graph.artifact_id,
                plan.context_query.artifact_id,
                plan.context_selection.artifact_id,
                plan.context_snapshot.artifact_id,
                *(item.artifact_id for item in observations.bindings),
                *(item.artifact_id for item in event_chain),
            }
        )
    )
    required_requirements = {
        item.subject_id
        for item in plan.decisions
        if item.subject_kind == "requirement"
        and item.kind is WorkflowDecisionKind.SELECTED
        and item.reason_code == "required-by-requirement"
    }
    mapped_requirements = {identifier for task in plan.tasks for identifier in task.requirement_ids}
    covered_requirements = set(observations.covered_requirement_ids) & required_requirements
    required_context: set[str] = set()
    selected_required_context: set[str] = set()
    context_quality: ContextQualityReport | None = None
    blocking_diagnostic_count: int | None = None
    scheduler_events: tuple[SchedulerEvent, ...] = ()
    budget: BudgetLedger | None = None
    workflow_causes: list[WorkflowEventCause] = []
    if store is not None:
        scheduler_events = tuple(
            artifact.value
            for artifact in store.evidence_history(
                "events",
                through_event_sequence=native.event_sequence,
            )
            if isinstance(artifact.value, SchedulerEvent)
        )
        budgets = tuple(
            artifact.value
            for artifact in store.evidence_history(
                "budget",
                through_event_sequence=native.event_sequence,
            )
            if isinstance(artifact.value, BudgetLedger)
        )
        if not budgets:
            raise WorkflowRuntimeError(
                "Native Scheduler budget evidence is unavailable."
            )
        budget = replace(budgets[-1], event_sequence=native.event_sequence)
        if scheduler_artifact_from_value(
            SchedulerArtifactType.BUDGET_LEDGER,
            budget,
        ).artifact_id != native.budget_ledger_id:
            raise WorkflowRuntimeError("Native Scheduler budget evidence does not reproduce.")
    if root is not None:
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
        graph = graph_artifact.value
        selection = selection_artifact.value
        snapshot = snapshot_artifact.value
        assert isinstance(graph, ContextGraph)
        assert isinstance(selection, ContextSelection)
        assert isinstance(snapshot, ContextSnapshot)
        quality_artifact = measure_context_quality(
            graph_artifact,
            selection_artifact,
            snapshot_artifact,
        )
        context_quality_value = quality_artifact.value
        assert isinstance(context_quality_value, ContextQualityReport)
        context_quality = context_quality_value
        required_context = {item.node_id for item in graph.nodes if item.required} | set(
            selection.query.required_node_ids
        )
        selected_required_context = required_context & {item.node_id for item in snapshot.nodes}
        baseline = load_baseline(root / plan.requirement_baseline.path)
        blocking_diagnostic_count = sum(item.status == "open" for item in baseline.diagnostics)
        bindings_to_load = event_chain if latest_cause is None else event_chain[:-1]
        artifact_store = ExclusiveWorkflowArtifactStore(root)
        for binding in bindings_to_load:
            loaded = parse_workflow_artifact_bytes(
                artifact_store.load(binding.reference, 1_048_576),
                expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
            )
            event = loaded.value
            assert isinstance(event, WorkflowEvent)
            workflow_causes.append(event.cause)
    if latest_cause is not None:
        workflow_causes.append(latest_cause)
    used_budget = {} if budget is None else dict(budget.used)
    blocker_codes = {
        blocker.code
        for task in tasks
        for blocker in (WorkflowBlocker(code, (task.task_id,)) for code in task.blocker_codes)
    }
    duplicate_rejections = sum(item.cause == "duplicate-message" for item in scheduler_events)
    late_rejections = sum(
        item.cause == "message-rejected"
        and item.reason is not None
        and ("late" in item.reason or "lease-expiry" in item.reason)
        for item in scheduler_events
    )
    approval_expired = sum(item.cause == "approval-proposal-expired" for item in scheduler_events)
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
    solver_status_counts = (
        ";".join(f"{name}:{count}" for name, count in observations.solver_status_counts) or "none"
    )
    observation_types = {item.artifact_type for item in observations.bindings}
    evidence_available = "evidence-ledger" in observation_types
    handoff_available = "automated-handoff" in observation_types
    values: list[WorkflowMeasurement] = [
        _observed(
            "requirements.required_requirement_count", len(required_requirements), "count", sources
        ),
        *(
            (
                _observed(
                    "requirements.covered_requirement_count",
                    len(covered_requirements),
                    "count",
                    sources,
                ),
                _observed(
                    "requirements.uncovered_requirement_ids",
                    ",".join(sorted(required_requirements - covered_requirements)) or "none",
                    "identifier-list",
                    sources,
                ),
            )
            if observations.requirement_coverage_available
            else (
                _unavailable("requirements.covered_requirement_count", sources),
                _unavailable("requirements.uncovered_requirement_ids", sources),
            )
        ),
        _observed(
            "requirements.scope_addition_count",
            len(mapped_requirements - required_requirements),
            "count",
            sources,
        ),
        (
            _observed(
                "requirements.blocking_diagnostic_count",
                blocking_diagnostic_count,
                "count",
                sources,
            )
            if blocking_diagnostic_count is not None
            else _unavailable("requirements.blocking_diagnostic_count", sources)
        ),
        _observed("context.required_reference_count", len(required_context), "count", sources),
        _observed(
            "context.selected_required_reference_count",
            len(selected_required_context),
            "count",
            sources,
        ),
        *(
            (
                _observed(
                    "context.stale_required_count",
                    context_quality.stale_required_count,
                    "count",
                    sources,
                ),
                _observed(
                    "context.provenance_missing_count",
                    context_quality.provenance_missing_count,
                    "count",
                    sources,
                ),
                _observed(
                    "context.sensitivity_violation_count",
                    context_quality.sensitivity_violation_count,
                    "count",
                    sources,
                ),
                _observed(
                    "context.selected_context_bytes",
                    context_quality.selected_context_bytes,
                    "canonical-utf8-bytes",
                    sources,
                ),
                _observed(
                    "context.context_budget_bytes",
                    context_quality.budget_bytes,
                    "canonical-utf8-bytes",
                    sources,
                ),
                _observed(
                    "context.unresolved_contradiction_count",
                    context_quality.unresolved_contradiction_count,
                    "count",
                    sources,
                ),
            )
            if context_quality is not None
            else tuple(
                _unavailable(name, sources)
                for name in (
                    "context.stale_required_count",
                    "context.provenance_missing_count",
                    "context.sensitivity_violation_count",
                    "context.selected_context_bytes",
                    "context.context_budget_bytes",
                    "context.unresolved_contradiction_count",
                )
            )
        ),
        _observed("scheduling.task_count", len(tasks), "count", sources),
        _observed(
            "scheduling.completed_task_count",
            sum(item.state is TaskState.COMPLETED for item in tasks),
            "count",
            sources,
        ),
        _observed(
            "scheduling.blocked_task_count",
            sum(item.state is TaskState.BLOCKED for item in tasks),
            "count",
            sources,
        ),
        _observed(
            "scheduling.retry_used_count", int(used_budget.get("retries", 0)), "count", sources
        ),
        _observed("scheduling.duplicate_rejection_count", duplicate_rejections, "count", sources),
        _observed("scheduling.late_result_rejection_count", late_rejections, "count", sources),
        _observed(
            "scheduling.deadlock_count",
            sum("deadlock" in code for code in blocker_codes),
            "count",
            sources,
        ),
        _observed("solver.solver_task_count", len(plan.solver_requests), "count", sources),
        _observed("solver.status_counts", solver_status_counts, "status-counts", sources),
        _observed(
            "solver.verified_result_count",
            dict(observations.solver_status_counts).get("verified", 0),
            "count",
            sources,
        ),
        _observed(
            "solver.adoptable_result_count",
            len(observations.solver_verification_ids),
            "count",
            sources,
        ),
        _observed(
            "solver.solver_calls_used", int(used_budget.get("solver_calls", 0)), "count", sources
        ),
        _observed(
            "solver.solver_steps_used", int(used_budget.get("solver_steps", 0)), "count", sources
        ),
        *(
            (
                _observed("evidence.claim_count", observations.claim_count, "count", sources),
                _observed(
                    "evidence.verified_claim_count",
                    observations.verified_claim_count,
                    "count",
                    sources,
                ),
                _observed(
                    "evidence.unverified_claim_count",
                    observations.unverified_claim_count,
                    "count",
                    sources,
                ),
                _observed(
                    "evidence.known_problem_count",
                    observations.evidence_known_problem_count,
                    "count",
                    sources,
                ),
                _observed(
                    "evidence.missing_evidence_count",
                    observations.missing_evidence_count,
                    "count",
                    sources,
                ),
            )
            if evidence_available
            else tuple(
                _unavailable(name, sources)
                for name in (
                    "evidence.claim_count",
                    "evidence.verified_claim_count",
                    "evidence.unverified_claim_count",
                    "evidence.known_problem_count",
                    "evidence.missing_evidence_count",
                )
            )
        ),
        *(
            (
                _observed(
                    "handoff.handoff_created_count",
                    observations.handoff_created_count,
                    "count",
                    sources,
                ),
                _observed(
                    "handoff.handoff_resume_failure_count",
                    observations.handoff_resume_failure_count,
                    "count",
                    sources,
                ),
                _observed(
                    "handoff.incomplete_item_count",
                    observations.handoff_incomplete_item_count,
                    "count",
                    sources,
                ),
                _observed(
                    "handoff.open_decision_count",
                    observations.handoff_open_decision_count,
                    "count",
                    sources,
                ),
                _observed(
                    "handoff.known_problem_count",
                    observations.handoff_known_problem_count,
                    "count",
                    sources,
                ),
            )
            if handoff_available
            else tuple(
                _unavailable(name, sources)
                for name in (
                    "handoff.handoff_created_count",
                    "handoff.handoff_resume_failure_count",
                    "handoff.incomplete_item_count",
                    "handoff.open_decision_count",
                    "handoff.known_problem_count",
                )
            )
        ),
        _unavailable("recovery.resume_attempt_count", sources),
        _observed(
            "recovery.successful_resume_count",
            sum(
                item
                not in {
                    WorkflowEventCause.RUNTIME_STARTED,
                    WorkflowEventCause.RECOVERY_OBSERVED,
                    WorkflowEventCause.PLAN_SUPERSEDED,
                    WorkflowEventCause.OUTCOME_PRODUCED,
                }
                for item in workflow_causes
            ),
            "count",
            sources,
        ),
        _unavailable("recovery.recovery_attempt_count", sources),
        _observed(
            "recovery.successful_recovery_count",
            sum(item is WorkflowEventCause.RECOVERY_OBSERVED for item in workflow_causes),
            "count",
            sources,
        ),
        _observed("recovery.ambiguous_effect_count", len(ambiguities), "count", sources),
        _observed(
            "approval.required_approval_count",
            sum(len(item.approval_types) for item in plan.protected_effects),
            "count",
            sources,
        ),
        _observed("approval.consumed_approval_count", len(approval_ids), "count", sources),
        _observed("approval.refused_approval_count", approval_refused, "count", sources),
        _observed("approval.expired_approval_count", approval_expired, "count", sources),
        _observed(
            "approval.pending_approval_count",
            sum("approval-required" in item.blocker_codes for item in tasks),
            "count",
            sources,
        ),
        _observed(
            "approval.approval_revalidation_failure_count", approval_failures, "count", sources
        ),
        _observed(
            "available_cost.status",
            plan.budget.cost_status,
            "availability-status",
            sources,
        ),
    ]
    if plan.budget.cost_status == "available":
        assert plan.budget.max_microunits is not None
        assert plan.budget.currency is not None
        used = int(used_budget.get("microunits", 0))
        values.extend(
            (
                _observed(
                    "available_cost.currency", plan.budget.currency, "iso-4217", sources
                ),
                _observed(
                    "available_cost.budget_microunits",
                    plan.budget.max_microunits,
                    "microunits",
                    sources,
                ),
                _observed("available_cost.used_microunits", used, "microunits", sources),
                _observed(
                    "available_cost.remaining_microunits",
                    max(0, plan.budget.max_microunits - used),
                    "microunits",
                    sources,
                ),
            )
        )
    else:
        values.extend(
            (
                _unavailable("available_cost.currency", sources),
                _unavailable("available_cost.budget_microunits", sources),
                _unavailable("available_cost.used_microunits", sources),
                _unavailable("available_cost.remaining_microunits", sources),
            )
        )
    result = tuple(values)
    if tuple(item.name for item in result) != WORKFLOW_MEASUREMENT_NAMES:
        raise WorkflowRuntimeError("Native measurement derivation drifted from exact M8-D7.")
    return result


def _observed(
    name: str,
    value: int | str,
    unit: str,
    sources: tuple[str, ...],
) -> WorkflowMeasurement:
    return WorkflowMeasurement(
        name,
        MeasurementStatus.OBSERVED,
        value,
        unit,
        tuple(sorted(set(sources))),
    )


def _unavailable(name: str, sources: tuple[str, ...]) -> WorkflowMeasurement:
    return WorkflowMeasurement(
        name,
        MeasurementStatus.NOT_AVAILABLE,
        None,
        None,
        tuple(sorted(set(sources))),
    )


def _transition_reason_codes(
    cause: WorkflowEventCause,
    protected: tuple[str, ...],
    approvals: tuple[str, ...],
    ambiguities: tuple[str, ...],
) -> tuple[str, ...]:
    reasons = {cause.value, "no-host-dispatch"}
    if protected:
        reasons.add("protected-effect-revalidated")
    if approvals:
        reasons.add("approval-revalidated")
    reasons.update(ambiguities)
    return tuple(sorted(reasons))


def _idempotency_key(
    plan_id: str,
    sequence: int,
    prior_state_id: str | None,
    scheduler_event_head: str,
) -> str:
    payload = {
        "plan_id": plan_id,
        "sequence": sequence,
        "prior_state_id": prior_state_id,
        "scheduler_event_head": scheduler_event_head,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest().upper()
    return f"M8-IDEM-{digest}"


def _supersession_idempotency(
    plan_id: str,
    source_state_id: str,
    successor_intent_id: str,
) -> str:
    digest = (
        hashlib.sha256(
            canonical_json_bytes(
                {
                    "plan_id": plan_id,
                    "source_state_id": source_state_id,
                    "successor_intent_id": successor_intent_id,
                }
            )
        )
        .hexdigest()
        .upper()
    )
    return f"M8-IDEM-{digest}"


def _observation_idempotency(
    plan_id: str,
    observation: WorkflowTerminalObservation,
) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "plan_id": plan_id,
                "cause": observation.cause.value,
                "scheduler_state_id": observation.scheduler_state_id,
                "scheduler_event_head_id": observation.scheduler_event_head_id,
                "source_artifact_ids": list(observation.source_artifact_ids),
            }
        )
    ).hexdigest().upper()
    return f"M8-IDEM-{digest}"


def _terminal_observation_cause(
    event: WorkflowEvent,
) -> WorkflowTerminalObservationCause:
    reasons = set(event.reason_codes)
    if "native-observation-closed" not in reasons or len(reasons) != 2:
        raise WorkflowRuntimeError("Terminal observation reason code is invalid.")
    raw = next(item for item in reasons if item != "native-observation-closed")
    try:
        return WorkflowTerminalObservationCause(raw)
    except ValueError as exc:
        raise WorkflowRuntimeError("Terminal observation cause is not closed.") from exc


def _output_reference(root: Path, output: Path, content: bytes) -> ArtifactReference:
    resolved_root = root.resolve(strict=True)
    candidate = output if output.is_absolute() else resolved_root / output
    lexical = Path(os.path.abspath(candidate))
    if not lexical.is_relative_to(resolved_root) or ".." in candidate.parts:
        raise WorkflowRuntimeError("Workflow output escapes its explicit root.")
    return ArtifactReference(
        lexical.relative_to(resolved_root).as_posix(),
        hashlib.sha256(content).hexdigest().upper(),
    )


def _require_runtime_private_path(
    root: Path,
    path: Path,
    *,
    existing: bool,
) -> Path:
    """Confine mutable M8/M6 runtime files to the reserved ``workflow/`` tree."""

    resolved_root = root.resolve(strict=True)
    candidate = path if path.is_absolute() else resolved_root / path
    lexical = Path(os.path.abspath(candidate))
    if not lexical.is_relative_to(resolved_root) or ".." in candidate.parts:
        raise WorkflowRuntimeError("Workflow runtime-private path escapes its root.")
    relative = lexical.relative_to(resolved_root)
    if (
        not relative.parts
        or relative.parts[0].casefold() != "workflow"
        or relative.parts[0] != "workflow"
    ):
        raise WorkflowRuntimeError(
            "Workflow and Scheduler outputs must remain under runtime-private workflow/."
        )
    if existing and (
        not lexical.is_file() or lexical.is_symlink() or lexical.resolve(strict=True) != lexical
    ):
        raise WorkflowRuntimeError("Workflow runtime-private input is not a regular file.")
    parent = lexical.parent.resolve(strict=True)
    if not parent.is_relative_to(resolved_root) or parent.is_symlink() or is_reparse_point(parent):
        raise WorkflowRuntimeError("Workflow runtime-private parent is invalid.")
    current = resolved_root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink() or is_reparse_point(current):
            raise WorkflowRuntimeError(
                "Workflow runtime-private path contains a link or reparse point."
            )
    return lexical


def _semantic_event_cause(
    event: WorkflowEvent,
    prior: WorkflowState | None,
    after: WorkflowState,
    protected: tuple[str, ...],
    approvals: tuple[str, ...],
) -> WorkflowEventCause:
    if event.cause is WorkflowEventCause.RECOVERY_OBSERVED:
        if prior is None or "recovery-observed" not in event.reason_codes:
            raise WorkflowRuntimeError("Workflow Event semantic recovery cause is invalid.")
        return event.cause
    if event.cause is WorkflowEventCause.PLAN_SUPERSEDED:
        if (
            prior is None
            or after.status is not TaskState.SUPERSEDED
            or event.scheduler_event_head_before != event.scheduler_event_head_after
            or "plan-superseded" not in event.reason_codes
        ):
            raise WorkflowRuntimeError("Workflow Event semantic supersession cause is invalid.")
        return event.cause
    if event.cause is WorkflowEventCause.OUTCOME_PRODUCED:
        if (
            prior is None
            or after.status is not prior.status
            or event.scheduler_event_head_before != event.scheduler_event_head_after
            or event.native_output_ids
            or event.reason_codes != ("outcome-produced",)
        ):
            raise WorkflowRuntimeError("Workflow Event semantic Outcome cause is invalid.")
        return event.cause
    if after.ambiguities:
        return WorkflowEventCause.AMBIGUITY_RECORDED
    if any(code.startswith("approval-") for task in after.tasks for code in task.blocker_codes):
        return WorkflowEventCause.APPROVAL_BLOCKED
    if protected and approvals:
        return WorkflowEventCause.APPROVAL_REVALIDATED
    if prior is None:
        return WorkflowEventCause.RUNTIME_STARTED
    return WorkflowEventCause.SCHEDULER_ADVANCED


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkflowRuntimeError("Workflow Event semantic timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise WorkflowRuntimeError("Workflow Event semantic timestamp is not UTC.")
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise WorkflowRuntimeError("Workflow clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
