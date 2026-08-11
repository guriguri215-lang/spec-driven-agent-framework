"""Evidence-preserving M8 recovery into fresh Event and State artifacts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.adapters.scheduler import SchedulerAdapterError, SQLiteSchedulerStore
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
from sdaqf.domain.scheduler import SchedulerState
from sdaqf.domain.workflow import (
    EffectDisposition,
    IntegratedPlan,
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowState,
)
from sdaqf.ports.workflow import WorkflowArtifactStorePort, WorkflowClock


class WorkflowRecoveryError(WorkflowContractError):
    """M8 recovery evidence cannot reproduce a fresh truthful projection."""


class WorkflowRecoveryService:
    """Recover only to new artifacts while retaining source and ambiguity."""

    def __init__(
        self,
        clock: WorkflowClock | None = None,
        store: WorkflowArtifactStorePort | None = None,
        planner: IntegratedPlanner | None = None,
    ) -> None:
        self._clock = SystemWorkflowClock() if clock is None else clock
        self._store = store
        if planner is None:
            raise TypeError("Workflow recovery requires an explicit candidate-aware planner.")
        self._planner = planner

    def recover(
        self,
        source_state_artifact: LoadedWorkflowArtifact,
        source_state_binding: NativeArtifactBinding,
        plan_artifact: LoadedWorkflowArtifact,
        observed_events: tuple[LoadedWorkflowArtifact, ...],
        root: Path,
        scheduler_state: Path,
        output_state: Path,
        output_event: Path,
        observed_event_bindings: tuple[NativeArtifactBinding, ...] = (),
        *,
        predecessor_scheduler_state: Path | None = None,
    ) -> tuple[LoadedWorkflowArtifact, LoadedWorkflowArtifact]:
        """Publish one recovery Event then a fresh State without mutating sources."""

        _require_runtime_private_path(root, scheduler_state, existing=True)
        _require_runtime_private_path(root, output_state, existing=False)
        _require_runtime_private_path(root, output_event, existing=False)

        if source_state_artifact.artifact_type is not WorkflowArtifactType.WORKFLOW_STATE:
            raise WorkflowRecoveryError("Workflow recovery requires source Workflow State.")
        if plan_artifact.artifact_type is not WorkflowArtifactType.INTEGRATED_PLAN:
            raise WorkflowRecoveryError("Workflow recovery requires Integrated Plan.")
        source = source_state_artifact.value
        plan = plan_artifact.value
        assert isinstance(source, WorkflowState)
        assert isinstance(plan, IntegratedPlan)
        if (
            source_state_binding.artifact_type != WorkflowArtifactType.WORKFLOW_STATE.value
            or source_state_binding.artifact_id != source_state_artifact.artifact_id
            or not source_state_binding.required
        ):
            raise WorkflowRecoveryError("Recovery requires the exact source State binding.")
        rebound_source = parse_workflow_artifact_bytes(
            (ExclusiveWorkflowArtifactStore(root) if self._store is None else self._store).load(
                source_state_binding.reference,
                16 * 1024 * 1024,
            ),
            expected_type=WorkflowArtifactType.WORKFLOW_STATE,
        )
        if rebound_source.artifact_id != source_state_artifact.artifact_id:
            raise WorkflowRecoveryError("Recovery source State binding drifted.")
        try:
            runtime = WorkflowRuntimeService(
                self._clock,
                self._store,
                planner=self._planner,
            )
            validated_plan, validated_source, publication_observation = runtime._validate_inputs(
                plan_artifact,
                source_state_artifact,
                root,
                scheduler_state,
                predecessor_scheduler_state=predecessor_scheduler_state,
            )
            assert validated_source is not None
            if runtime._terminal_cause(validated_source, root) is not None:
                raise WorkflowRecoveryError("A terminal Workflow State cannot be recovered.")
            store = SQLiteSchedulerStore(scheduler_state, root)
            store.validate()
            native_artifact = store.status()
            native_for_lineage = native_artifact.value
            assert isinstance(native_for_lineage, SchedulerState)
            runtime._validate_scheduler_lineage(
                validated_plan,
                validated_source,
                store,
                native_for_lineage,
            )
            if native_artifact.artifact_id == source.scheduler_state_id:
                runtime._require_exact_state(
                    plan_artifact.artifact_id,
                    plan,
                    source_state_artifact,
                    source,
                    native_for_lineage,
                    store,
                    root,
                    publication_observation,
                )
        except WorkflowRecoveryError:
            raise
        except (SchedulerAdapterError, WorkflowContractError, OSError) as exc:
            raise WorkflowRecoveryError(
                "Native scheduler evidence is invalid; use agents recover to a fresh DB first."
            ) from exc
        native = native_artifact.value
        assert isinstance(native, SchedulerState)
        supplied = self._validate_observed_events(
            source_state_artifact,
            plan_artifact,
            source,
            observed_events,
        )
        if len(supplied) != len(observed_event_bindings) or any(
            binding.artifact_id != artifact.artifact_id
            or binding.artifact_type != WorkflowArtifactType.WORKFLOW_EVENT.value
            or not binding.required
            for binding, artifact in zip(observed_event_bindings, supplied, strict=True)
        ):
            raise WorkflowRecoveryError(
                "Every orphan Event requires its exact required root-confined binding."
            )
        if supplied:
            orphan = supplied[-1].value
            assert isinstance(orphan, WorkflowEvent)
            preview = runtime._derive_state(
                plan_artifact.artifact_id,
                plan,
                native,
                source.event_chain,
                observed_event_bindings[-1],
                orphan.recorded_at,
                store,
                root,
                publication_observation,
                latest_cause=orphan.cause,
            )
            preview_artifact = artifact_from_value(
                WorkflowArtifactType.WORKFLOW_STATE,
                preview,
            )
            try:
                runtime._validate_inputs(
                    plan_artifact,
                    preview_artifact,
                    root,
                    scheduler_state,
                    predecessor_scheduler_state=predecessor_scheduler_state,
                )
            except (OSError, WorkflowContractError) as exc:
                raise WorkflowRecoveryError(
                    "Orphan Workflow Event failed complete semantic replay."
                ) from exc
        previous_event_id = (
            source.latest_event.artifact_id if not supplied else supplied[-1].artifact_id
        )
        sequence = source.transition_count + 1 + len(supplied)
        ambiguities = tuple(
            sorted(
                set(source.ambiguities) | set(WorkflowRuntimeService._ambiguities(store, native))
            )
        )
        request_idempotency = _recovery_idempotency(
            plan_artifact.artifact_id,
            source_state_artifact.artifact_id,
            native_artifact.artifact_id,
            tuple(item.artifact_id for item in supplied),
        )
        head = store.workflow_head(plan_artifact.artifact_id)
        if head is None:
            raise WorkflowRecoveryError("M6 workflow epoch is not open for recovery.")
        same_request_replay = (
            head.producer == "workflow-recover"
            and head.source_state_id == source_state_artifact.artifact_id
            and head.idempotency_key == request_idempotency
        )
        now = head.recorded_at if same_request_replay else _format_utc(self._clock.now())
        projected_status = runtime._project_status(
            plan,
            native,
            store,
            root,
            publication_observation,
        )
        event = WorkflowEvent(
            sequence=sequence,
            previous_event_id=previous_event_id,
            prior_state_id=source_state_artifact.artifact_id,
            plan_id=plan_artifact.artifact_id,
            candidate=plan.candidate,
            sensitivity=plan.sensitivity,
            cause=WorkflowEventCause.RECOVERY_OBSERVED,
            before_status=source.status,
            after_status=projected_status,
            scheduler_event_head_before=source.scheduler_event_head_sha256,
            scheduler_event_head_after=native.event_head_sha256,
            effect_disposition=(
                EffectDisposition.AMBIGUOUS if ambiguities else EffectDisposition.NOT_APPLICABLE
            ),
            actor="M8 workflow recovery service",
            recorded_at=now,
            idempotency_key=request_idempotency,
            native_input_ids=tuple(
                sorted(
                    {
                        plan_artifact.artifact_id,
                        source_state_artifact.artifact_id,
                        source.latest_event.artifact_id,
                        native_artifact.artifact_id,
                        *(item.artifact_id for item in supplied),
                    }
                )
            ),
            native_output_ids=(native_artifact.artifact_id,),
            task_id=None,
            effect_id=None,
            approval_id=None,
            reason_codes=tuple(sorted({"recovery-observed", "source-preserved", *ambiguities})),
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
        recovered = runtime._derive_state(
            plan_artifact.artifact_id,
            plan,
            native,
            (*source.event_chain, *observed_event_bindings),
            event_binding,
            now,
            store,
            root,
            publication_observation,
            latest_cause=WorkflowEventCause.RECOVERY_OBSERVED,
        )
        if recovered.transition_count != sequence:
            raise WorkflowRecoveryError("Recovery Event/State sequence did not reproduce.")
        state_artifact = artifact_from_value(WorkflowArtifactType.WORKFLOW_STATE, recovered)
        state_bytes = serialize_workflow_artifact(state_artifact)
        event_path = _output_reference(root, output_event, event_bytes).path
        state_path = _output_reference(root, output_state, state_bytes).path
        head = store.workflow_head(plan_artifact.artifact_id)
        if head is None:
            raise WorkflowRecoveryError("M6 workflow epoch is not open for recovery.")
        publication = ExclusiveWorkflowArtifactStore(root) if self._store is None else self._store
        if same_request_replay:
            if (
                head.workflow_event_id != event_artifact.artifact_id
                or head.workflow_state_id != state_artifact.artifact_id
                or head.workflow_event_path != event_path
                or head.workflow_state_path != state_path
            ):
                raise WorkflowRecoveryError("M6 recovery replay differs from its first request.")
            publication.publish_idempotent(
                output_event,
                event_bytes,
                artifact_type=WorkflowArtifactType.WORKFLOW_EVENT.value,
                artifact_id=event_artifact.artifact_id,
            )
            publication.publish_idempotent(
                output_state,
                state_bytes,
                artifact_type=WorkflowArtifactType.WORKFLOW_STATE.value,
                artifact_id=state_artifact.artifact_id,
            )
            return state_artifact, event_artifact
        if head.workflow_state_id != source_state_artifact.artifact_id:
            raise WorkflowRecoveryError("M6 workflow head rejects historical recovery.")
        reserved = store.reserve_workflow_transition(
            plan_id=plan_artifact.artifact_id,
            expected_head_id=head.current_event_head_id,
            scheduler_state_id=native_artifact.artifact_id,
            scheduler_event_sequence=native.event_sequence,
            scheduler_event_head_id=store.current_event_head_id,
            source_state_id=source_state_artifact.artifact_id,
            workflow_event_id=event_artifact.artifact_id,
            workflow_state_id=state_artifact.artifact_id,
            idempotency_key=event.idempotency_key,
            producer="workflow-recover",
            event_path=event_path,
            state_path=state_path,
            recorded_at=now,
        )
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
            producer="workflow-recover",
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
            producer="workflow-recover",
        )
        return state_artifact, event_artifact

    @staticmethod
    def _validate_observed_events(
        source_state_artifact: LoadedWorkflowArtifact,
        plan_artifact: LoadedWorkflowArtifact,
        source: WorkflowState,
        events: tuple[LoadedWorkflowArtifact, ...],
    ) -> tuple[LoadedWorkflowArtifact, ...]:
        typed: list[tuple[LoadedWorkflowArtifact, WorkflowEvent]] = []
        for artifact in events:
            if artifact.artifact_type is not WorkflowArtifactType.WORKFLOW_EVENT:
                raise WorkflowRecoveryError("Recovery observation is not a Workflow Event.")
            event = artifact.value
            assert isinstance(event, WorkflowEvent)
            if event.plan_id != plan_artifact.artifact_id or event.candidate != source.candidate:
                raise WorkflowRecoveryError("Recovery Event identity is stale.")
            typed.append((artifact, event))
        typed.sort(key=lambda item: (item[1].sequence, item[0].artifact_id))
        unique = {artifact.artifact_id for artifact, _ in typed}
        if len(unique) != len(typed):
            raise WorkflowRecoveryError("Recovery Event list contains duplicates.")
        supplied = tuple(
            (artifact, event)
            for artifact, event in typed
            if artifact.artifact_id != source.latest_event.artifact_id
        )
        if len(supplied) > 1:
            raise WorkflowRecoveryError("At most one orphan M8 Event can precede recovery.")
        if supplied:
            artifact, event = supplied[0]
            if (
                event.sequence != source.transition_count + 1
                or event.previous_event_id != source.latest_event.artifact_id
                or event.prior_state_id != source_state_artifact.artifact_id
            ):
                raise WorkflowRecoveryError("Orphan Workflow Event does not extend source State.")
            return (artifact,)
        return ()


def _recovery_idempotency(
    plan_id: str,
    source_state_id: str,
    scheduler_state_id: str,
    event_ids: tuple[str, ...],
) -> str:
    digest = (
        hashlib.sha256(
            canonical_json_bytes(
                {
                    "plan_id": plan_id,
                    "source_state_id": source_state_id,
                    "scheduler_state_id": scheduler_state_id,
                    "event_ids": list(event_ids),
                }
            )
        )
        .hexdigest()
        .upper()
    )
    return f"M8-IDEM-{digest}"


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise WorkflowRecoveryError("Workflow clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
