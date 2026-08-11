"""Truthful M8 completion, Gate, Outcome, and handoff predicates."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.adapters.workflow import ExclusiveWorkflowArtifactStore, SystemWorkflowClock
from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.workflow_contracts import (
    LoadedWorkflowArtifact,
    WorkflowContractError,
    artifact_from_value,
    parse_workflow_artifact_bytes,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_planning import IntegratedPlanner
from sdaqf.application.workflow_runtime import (
    WorkflowRuntimeService,
    _output_reference,
    _require_runtime_private_path,
)
from sdaqf.domain.scheduler import TaskOutcome, TaskState, WorkflowEpochPhase
from sdaqf.domain.workflow import (
    CompletionProfile,
    EffectDisposition,
    GateStatus,
    IntegratedPlan,
    NativeArtifactBinding,
    OutcomeClaimState,
    WorkflowArtifactType,
    WorkflowBlocker,
    WorkflowDisposition,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowOutcome,
    WorkflowPublicationObservation,
    WorkflowState,
)
from sdaqf.ports.workflow import WorkflowArtifactStorePort, WorkflowClock


class WorkflowOutcomeError(WorkflowContractError):
    """Native evidence cannot support the requested Workflow Outcome."""


class WorkflowOutcomeService:
    """Derive and publish an Outcome without upgrading native truth."""

    def __init__(
        self,
        clock: WorkflowClock | None = None,
        store: WorkflowArtifactStorePort | None = None,
        planner: IntegratedPlanner | None = None,
    ) -> None:
        self._clock = SystemWorkflowClock() if clock is None else clock
        self._store = store
        if planner is None:
            raise TypeError("Workflow Outcome requires an explicit candidate-aware planner.")
        self._planner = planner

    def derive(
        self,
        state_artifact: LoadedWorkflowArtifact,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
    ) -> LoadedWorkflowArtifact:
        """Return one content-addressed Outcome after exact native replay."""

        plan, state, _publication_observation = self._validated_values(
            state_artifact,
            plan_artifact,
            root,
            scheduler_state,
        )
        return self._derive_validated(
            plan,
            state,
            plan_artifact.artifact_id,
            state_artifact.artifact_id,
            root,
            completed_at=_terminal_event_time(state, root, self._store),
        )

    def _derive_validated(
        self,
        plan: IntegratedPlan,
        state: WorkflowState,
        plan_id: str,
        terminal_state_id: str,
        root: Path,
        *,
        completed_at: str,
    ) -> LoadedWorkflowArtifact:
        """Derive Outcome bytes from an already replayed terminal State."""

        disposition, extra_blockers = completion_disposition(plan, state)
        blockers = tuple(
            WorkflowBlocker(code, references)
            for code, references in sorted(
                {(item.code, item.references) for item in state.blockers} | set(extra_blockers)
            )
        )
        lineage_ids = {plan_id}
        if plan.predecessor_outcome is not None:
            predecessor_artifact = parse_workflow_artifact_bytes(
                (ExclusiveWorkflowArtifactStore(root) if self._store is None else self._store).load(
                    plan.predecessor_outcome.reference,
                    16 * 1024 * 1024,
                ),
                expected_type=WorkflowArtifactType.WORKFLOW_OUTCOME,
            )
            predecessor = predecessor_artifact.value
            assert isinstance(predecessor, WorkflowOutcome)
            if predecessor_artifact.artifact_id != plan.predecessor_outcome.artifact_id:
                raise WorkflowOutcomeError("Predecessor Outcome binding drifted.")
            lineage_ids.update(predecessor.lineage_plan_ids)
        lineage = tuple(sorted(lineage_ids))
        outcome = WorkflowOutcome(
            plan_id=plan_id,
            lineage_plan_ids=lineage,
            terminal_state_id=terminal_state_id,
            candidate=plan.candidate,
            sensitivity=plan.sensitivity,
            disposition=disposition,
            claim_state=(
                OutcomeClaimState.VERIFIED
                if disposition is WorkflowDisposition.COMPLETED
                else OutcomeClaimState.KNOWN_PROBLEM
                if blockers or state.ambiguities
                else OutcomeClaimState.UNVERIFIED
            ),
            completion_profile=plan.completion_profile,
            scheduler_state_id=state.scheduler_state_id,
            solver_verification_ids=state.solver_verification_ids,
            evidence_ids=state.evidence_ids,
            review_ids=state.review_ids,
            gates=state.gates,
            effect_ids=tuple(sorted(item.effect_id for item in plan.protected_effects)),
            approval_ids=state.approval_ids,
            ambiguities=state.ambiguities,
            blockers=blockers,
            measurements=state.measurements,
            observation_artifacts=state.observation_artifacts,
            handoff_id=state.handoff_id,
            handoff_status=state.handoff_status,
            next_action=_next_action(disposition, blockers),
            completed_at=completed_at,
        )
        return artifact_from_value(WorkflowArtifactType.WORKFLOW_OUTCOME, outcome)

    def publish(
        self,
        state_artifact: LoadedWorkflowArtifact,
        state_binding: NativeArtifactBinding,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        output: Path,
        output_event: Path,
        output_state: Path,
    ) -> tuple[
        LoadedWorkflowArtifact,
        LoadedWorkflowArtifact,
        LoadedWorkflowArtifact,
    ]:
        """Publish Event, adopting State, then Outcome without an orphan."""

        _require_runtime_private_path(root, scheduler_state, existing=True)
        output_lexical = _require_runtime_private_path(root, output, existing=False)
        event_lexical = _require_runtime_private_path(root, output_event, existing=False)
        state_lexical = _require_runtime_private_path(root, output_state, existing=False)
        resolved_root = root.resolve(strict=True)
        try:
            self._planner._candidate_verifier.classify_output_paths(  # type: ignore[attr-defined]
                root,
                tuple(
                    item.relative_to(resolved_root).as_posix()
                    for item in (event_lexical, state_lexical, output_lexical)
                ),
                scheduler_state=scheduler_state,
                plan_id=plan_artifact.artifact_id,
            )
        except (OSError, RuntimeError) as exc:
            raise WorkflowOutcomeError(
                "Terminal outputs failed initial Git publication classification."
            ) from exc

        supplied = state_artifact.value
        if isinstance(supplied, WorkflowState):
            terminal_runtime = WorkflowRuntimeService(
                self._clock,
                self._store,
                planner=self._planner,
            )
            if terminal_runtime._terminal_cause(supplied, root) is not None:
                raise WorkflowOutcomeError("A terminal Workflow State cannot republish Outcome.")
        plan, state, publication_observation = self._validated_values(
            state_artifact,
            plan_artifact,
            root,
            scheduler_state,
        )
        runtime = WorkflowRuntimeService(
            self._clock,
            self._store,
            planner=self._planner,
        )
        if runtime._terminal_cause(state, root) is not None:
            raise WorkflowOutcomeError("A terminal Workflow State cannot republish Outcome.")
        scheduler_store = SQLiteSchedulerStore(scheduler_state, root)
        scheduler_store.validate()
        scheduler_store.require_workflow_authority()
        pinned_native = scheduler_store.status()
        pinned_native_value = pinned_native.value
        from sdaqf.domain.scheduler import SchedulerState

        assert isinstance(pinned_native_value, SchedulerState)
        pinned_scheduler_event_head_id = scheduler_store.current_event_head_id
        if (
            pinned_native.artifact_id != state.scheduler_state_id
            or pinned_native_value.event_sequence != state.scheduler_event_sequence
        ):
            raise WorkflowOutcomeError(
                "M6 scheduler authority changed after the pinned Outcome observation."
            )
        head = scheduler_store.workflow_head(plan_artifact.artifact_id)
        if head is None:
            raise WorkflowOutcomeError("M6 workflow epoch is not open for this Plan.")
        request_idempotency = _outcome_idempotency(
            plan_artifact.artifact_id,
            state_artifact.artifact_id,
        )
        if head.phase in {
            WorkflowEpochPhase.TERMINAL_RESERVED,
            WorkflowEpochPhase.TERMINAL_CONFIRMED,
        }:
            if (
                head.source_state_id != state_artifact.artifact_id
                or head.idempotency_key != request_idempotency
                or head.producer != "workflow-outcome"
                or head.terminal_at is None
            ):
                raise WorkflowOutcomeError("M6 terminal authority rejects a different request.")
            now = head.terminal_at
        else:
            now = _format_utc(self._clock.now())
        if (
            state_binding.artifact_type != WorkflowArtifactType.WORKFLOW_STATE.value
            or state_binding.artifact_id != state_artifact.artifact_id
            or not state_binding.required
        ):
            raise WorkflowOutcomeError("Outcome requires the exact source State binding.")
        source = (
            ExclusiveWorkflowArtifactStore(root) if self._store is None else self._store
        ).load(
            state_binding.reference,
            16 * 1024 * 1024,
        )
        rebound = parse_workflow_artifact_bytes(
            source,
            expected_type=WorkflowArtifactType.WORKFLOW_STATE,
        )
        if rebound.artifact_id != state_artifact.artifact_id:
            raise WorkflowOutcomeError("Outcome source State binding drifted.")
        event = WorkflowEvent(
            sequence=state.transition_count + 1,
            previous_event_id=state.latest_event.artifact_id,
            prior_state_id=state_artifact.artifact_id,
            plan_id=plan_artifact.artifact_id,
            candidate=plan.candidate,
            sensitivity=plan.sensitivity,
            cause=WorkflowEventCause.OUTCOME_PRODUCED,
            before_status=state.status,
            after_status=state.status,
            scheduler_event_head_before=state.scheduler_event_head_sha256,
            scheduler_event_head_after=state.scheduler_event_head_sha256,
            effect_disposition=(
                EffectDisposition.AMBIGUOUS
                if state.ambiguities
                else EffectDisposition.NOT_APPLICABLE
            ),
            actor="M8 workflow outcome service",
            recorded_at=now,
            idempotency_key=request_idempotency,
            native_input_ids=tuple(
                sorted(
                    {
                        plan_artifact.artifact_id,
                        state_artifact.artifact_id,
                        state.latest_event.artifact_id,
                        state.scheduler_state_id,
                    }
                )
            ),
            native_output_ids=(),
            task_id=None,
            effect_id=None,
            approval_id=None,
            reason_codes=("outcome-produced",),
            prior_state=state_binding,
        )
        event_artifact = artifact_from_value(WorkflowArtifactType.WORKFLOW_EVENT, event)
        event_bytes = serialize_workflow_artifact(event_artifact)
        event_binding = NativeArtifactBinding(
            WorkflowArtifactType.WORKFLOW_EVENT.value,
            event_artifact.artifact_id,
            _output_reference(root, output_event, event_bytes),
            True,
        )
        closure_value = replace(
            state,
            event_chain=(*state.event_chain, event_binding),
            latest_event=event_binding,
            transition_count=state.transition_count + 1,
            recorded_at=now,
        )
        closure_artifact = artifact_from_value(
            WorkflowArtifactType.WORKFLOW_STATE,
            closure_value,
        )
        closure_bytes = serialize_workflow_artifact(closure_artifact)
        outcome_artifact = self._derive_validated(
            plan,
            closure_value,
            plan_artifact.artifact_id,
            closure_artifact.artifact_id,
            root,
            completed_at=now,
        )
        outcome_bytes = serialize_workflow_artifact(outcome_artifact)
        outcome_path = _output_reference(root, output, outcome_bytes).path
        state_path = _output_reference(root, output_state, closure_bytes).path
        event_path = _output_reference(root, output_event, event_bytes).path
        if len({event_path.casefold(), state_path.casefold(), outcome_path.casefold()}) != 3:
            raise WorkflowOutcomeError("Terminal output paths must be distinct and case-unique.")
        publication = ExclusiveWorkflowArtifactStore(root) if self._store is None else self._store
        preflight = (
            (output_event, event_bytes, WorkflowArtifactType.WORKFLOW_EVENT, event_artifact),
            (output_state, closure_bytes, WorkflowArtifactType.WORKFLOW_STATE, closure_artifact),
            (output, outcome_bytes, WorkflowArtifactType.WORKFLOW_OUTCOME, outcome_artifact),
        )
        try:
            self._planner._candidate_verifier.preflight_outputs(  # type: ignore[attr-defined]
                root,
                tuple(
                    (
                        _output_reference(root, target, content).path,
                        artifact_type.value,
                        artifact.artifact_id,
                        "workflow-outcome",
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
            raise WorkflowOutcomeError(
                "Terminal outputs or pinned publication authority changed before reserve."
            ) from exc
        reserved = scheduler_store.reserve_workflow_terminal(
            plan_id=plan_artifact.artifact_id,
            expected_head_id=head.current_event_head_id,
            scheduler_state_id=state.scheduler_state_id,
            scheduler_event_sequence=state.scheduler_event_sequence,
            scheduler_event_head_id=pinned_scheduler_event_head_id,
            source_state_id=state_artifact.artifact_id,
            workflow_event_id=event_artifact.artifact_id,
            workflow_state_id=closure_artifact.artifact_id,
            outcome_id=outcome_artifact.artifact_id,
            idempotency_key=request_idempotency,
            producer="workflow-outcome",
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
                closure_bytes,
                WorkflowArtifactType.WORKFLOW_STATE,
                closure_artifact,
                state_path,
            ),
            (
                output,
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
            confirmed = scheduler_store.confirm_workflow_artifact(
                plan_id=plan_artifact.artifact_id,
                expected_head_id=confirmed.current_event_head_id,
                artifact_id=artifact.artifact_id,
                path=path,
                idempotency_key=request_idempotency,
                recorded_at=now,
                artifact_type=artifact_type.value,
                producer="workflow-outcome",
            )
        try:
            self._planner._candidate_verifier.confirm_outputs(  # type: ignore[attr-defined]
                root,
                publication_observation,
                plan.candidate,
                tuple(
                    (
                        path,
                        artifact_type.value,
                        artifact.artifact_id,
                        "workflow-outcome",
                    )
                    for _, _, artifact_type, artifact, path in confirmations
                ),
                scheduler_state=scheduler_state,
                plan_id=plan_artifact.artifact_id,
            )
        except (OSError, RuntimeError) as exc:
            raise WorkflowOutcomeError(
                "Terminal outputs failed final Git and M6 confirmation."
            ) from exc
        scheduler_store.confirm_workflow_terminal(
            plan_id=plan_artifact.artifact_id,
            expected_head_id=confirmed.current_event_head_id,
            idempotency_key=request_idempotency,
            recorded_at=now,
            producer="workflow-outcome",
        )
        return outcome_artifact, event_artifact, closure_artifact

    def _validated_values(
        self,
        state_artifact: LoadedWorkflowArtifact,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
    ) -> tuple[IntegratedPlan, WorkflowState, WorkflowPublicationObservation]:
        if state_artifact.artifact_type is not WorkflowArtifactType.WORKFLOW_STATE:
            raise WorkflowOutcomeError("Workflow Outcome requires Workflow State.")
        if plan_artifact.artifact_type is not WorkflowArtifactType.INTEGRATED_PLAN:
            raise WorkflowOutcomeError("Workflow Outcome requires Integrated Plan.")
        plan = plan_artifact.value
        state = state_artifact.value
        assert isinstance(plan, IntegratedPlan)
        assert isinstance(state, WorkflowState)
        observation = self._planner._candidate_verifier.observe(
            root,
            plan.candidate,
            scheduler_state=scheduler_state,
            plan_id=plan_artifact.artifact_id,
        )
        WorkflowRuntimeService(
            self._clock,
            self._store,
            planner=self._planner,
        ).status(
            state_artifact,
            plan_artifact,
            root,
            scheduler_state,
            publication_observation=observation,
        )
        return plan, state, observation


def completion_disposition(
    plan: IntegratedPlan,
    state: WorkflowState,
) -> tuple[WorkflowDisposition, tuple[tuple[str, tuple[str, ...]], ...]]:
    """Apply closed completion profiles without strengthening native status."""

    if state.status is TaskState.REJECTED:
        return WorkflowDisposition.REJECTED, ()
    if state.status is TaskState.SUPERSEDED:
        return WorkflowDisposition.SUPERSEDED, ()
    # Native Workflow blockers are already the complete, deterministic reason
    # set for a blocked terminal projection.  Adding profile-shaped fallback
    # blockers here would change the observed cause (and lets a summary invent
    # authority that the State did not record).
    if state.blockers:
        return (
            WorkflowDisposition.BLOCKED,
            tuple((item.code, item.references) for item in state.blockers),
        )
    missing: set[tuple[str, tuple[str, ...]]] = set()
    gate_status = {item.gate_id: item.status for item in state.gates}
    required_gates = {
        CompletionProfile.PLAN_ONLY: ("G1",),
        CompletionProfile.IMPLEMENTATION_VERIFIED: ("G1", "G2"),
        CompletionProfile.INDEPENDENT_REVIEW_ACCEPTED: ("G1", "G2", "G3"),
        CompletionProfile.RELEASE_CANDIDATE_READY: ("G1", "G2", "G3", "G4"),
    }[plan.completion_profile]
    for gate_id in required_gates:
        if gate_status.get(gate_id) is not GateStatus.PASS:
            missing.add((f"{gate_id.casefold()}-not-passed", (gate_id,)))
    if plan.completion_profile is not CompletionProfile.PLAN_ONLY:
        if not state.tasks or any(
            item.state is not TaskState.COMPLETED or item.outcome is not TaskOutcome.SUCCEEDED
            for item in state.tasks
        ):
            missing.add(("scheduler-not-completed", (state.scheduler_state_id,)))
        required_solver = len(plan.solver_requests)
        if len(state.solver_verification_ids) < required_solver:
            missing.add(("solver-evidence-unavailable", (plan.task_graph.artifact_id,)))
        if state.handoff_id is None or state.handoff_status != "completed":
            missing.add(("handoff-not-completed", (plan.task_graph.artifact_id,)))
    if (
        plan.completion_profile
        in {
            CompletionProfile.INDEPENDENT_REVIEW_ACCEPTED,
            CompletionProfile.RELEASE_CANDIDATE_READY,
        }
        and not state.review_ids
    ):
        missing.add(("review-evidence-unavailable", (plan.task_graph.artifact_id,)))
    if (
        plan.completion_profile is CompletionProfile.RELEASE_CANDIDATE_READY
        and plan.ui_required
        and gate_status.get("G4") is not GateStatus.PASS
    ):
        missing.add(("ui-evidence-unavailable", ("G4",)))
    if state.ambiguities:
        missing.add(("external-effect-ambiguous", (state.scheduler_state_id,)))
    if state.status is not TaskState.COMPLETED:
        missing.add(("workflow-state-not-completed", (state.scheduler_state_id,)))
    if missing:
        return WorkflowDisposition.BLOCKED, tuple(sorted(missing))
    return WorkflowDisposition.COMPLETED, ()


def _outcome_idempotency(plan_id: str, state_id: str) -> str:
    digest = (
        hashlib.sha256(canonical_json_bytes({"plan_id": plan_id, "state_id": state_id}))
        .hexdigest()
        .upper()
    )
    return f"M8-IDEM-{digest}"


def _terminal_event_time(
    state: WorkflowState,
    root: Path,
    store: WorkflowArtifactStorePort | None,
) -> str:
    """Return the recorded terminal Event time used as Outcome authority."""

    publication = ExclusiveWorkflowArtifactStore(root) if store is None else store
    event_artifact = parse_workflow_artifact_bytes(
        publication.load(state.latest_event.reference, 1_048_576),
        expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
    )
    if event_artifact.artifact_id != state.latest_event.artifact_id:
        raise WorkflowOutcomeError("Workflow terminal Event binding drifted.")
    event = event_artifact.value
    assert isinstance(event, WorkflowEvent)
    if event.cause not in {
        WorkflowEventCause.OUTCOME_PRODUCED,
        WorkflowEventCause.PLAN_SUPERSEDED,
    }:
        raise WorkflowOutcomeError("Workflow Outcome requires a terminal Event.")
    return event.recorded_at


def _next_action(
    disposition: WorkflowDisposition,
    blockers: tuple[WorkflowBlocker, ...],
) -> str:
    if disposition is WorkflowDisposition.COMPLETED:
        return "Retain the verified artifacts; no action is executed automatically."
    if disposition is WorkflowDisposition.SUPERSEDED:
        return "Create a new candidate-bound Plan with exact predecessor references."
    if disposition is WorkflowDisposition.REJECTED:
        return "Revise the rejected proposal and obtain any required fresh authority."
    codes = ",".join(item.code for item in blockers[:8]) or "unverified-native-evidence"
    return f"Resolve the exact blockers ({codes}) and revalidate without automatic retry."


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise WorkflowOutcomeError("Workflow clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
