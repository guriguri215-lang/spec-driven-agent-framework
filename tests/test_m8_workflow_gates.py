"""M8 completion-profile composition tests over existing G1-G4 semantics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import sdaqf.application.workflow_runtime as runtime_module
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.contracts import ContractError
from sdaqf.application.scheduler_contracts import (
    parse_scheduler_artifact_bytes,
    validate_reviewed_agent_identities,
)
from sdaqf.application.skills import SkillContractError
from sdaqf.application.workflow_outcome import completion_disposition
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.quality import ArtifactReference, GitObservation, HandoffStatus
from sdaqf.domain.scheduler import (
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
)
from sdaqf.domain.solver import SolverArtifactType
from sdaqf.domain.workflow import (
    CompletionProfile,
    GateObservation,
    GateStatus,
    IntegratedPlan,
    WorkflowDisposition,
    WorkflowPublicationObservation,
    WorkflowState,
    WorkflowTaskProjection,
)
from tests.m8_workflow_helpers import (
    FixedClock,
    create_plan,
    create_runtime,
    create_scheduler,
    create_workspace,
)


@pytest.mark.parametrize(
    ("target_agents", "reviewed_agent_ids", "reviewer_agent_ids"),
    (
        (
            {"TSK-A": "AGT-A", "TSK-B": "AGT-B"},
            ("AGT-B", "AGT-A"),
            ("AGT-A", "AGT-B"),
        ),
        (
            {"TSK-A": "AGT-SHARED", "TSK-B": "AGT-SHARED"},
            ("AGT-SHARED",),
            ("AGT-SHARED",),
        ),
    ),
)
def test_reviewed_agent_identity_binding_is_order_independent_and_many_to_one(
    target_agents: dict[str, str],
    reviewed_agent_ids: tuple[str, ...],
    reviewer_agent_ids: tuple[str, ...],
) -> None:
    task: Any = SimpleNamespace(
        kind=TaskKind.REVIEW,
        review_targets=tuple(target_agents),
    )
    reviewer_result: Any = SimpleNamespace(
        agent_id="AGT-REVIEWER",
        reviewed_agent_ids=reviewer_agent_ids,
    )
    review: Any = SimpleNamespace(
        reviewer_id="AGT-REVIEWER",
        reviewed_agent_ids=reviewed_agent_ids,
    )
    accepted_results: Any = {
        task_id: SimpleNamespace(agent_id=agent_id)
        for task_id, agent_id in target_agents.items()
    }

    validate_reviewed_agent_identities(
        task,
        reviewer_result,
        review,
        accepted_results,
    )


def test_implementation_profile_requires_native_completion_evidence_and_handoff(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan_artifact, _ = create_plan(root)
    scheduler = create_scheduler(root)
    state_artifact = (
        create_runtime(FixedClock())
        .run(
            plan_artifact,
            root,
            scheduler,
            root / "workflow/state.json",
            root / "workflow/event.json",
        )
        .state
    )
    plan_value = plan_artifact.value
    assert isinstance(plan_value, IntegratedPlan)
    plan = replace(
        plan_value,
        completion_profile=CompletionProfile.IMPLEMENTATION_VERIFIED,
        required_gate_ids=("G1", "G2"),
    )
    state = state_artifact.value
    assert isinstance(state, WorkflowState)
    disposition, blockers = completion_disposition(plan, state)
    assert disposition is WorkflowDisposition.BLOCKED
    assert {item[0] for item in blockers} >= {
        "scheduler-not-completed",
        "handoff-not-completed",
        "g2-not-passed",
    }


def test_implementation_profile_completes_only_with_native_success_and_gates(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan_artifact, _ = create_plan(root)
    scheduler = create_scheduler(root)
    state_artifact = (
        create_runtime(FixedClock())
        .run(
            plan_artifact,
            root,
            scheduler,
            root / "workflow/state.json",
            root / "workflow/event.json",
        )
        .state
    )
    plan_value = plan_artifact.value
    assert isinstance(plan_value, IntegratedPlan)
    plan = replace(
        plan_value,
        completion_profile=CompletionProfile.IMPLEMENTATION_VERIFIED,
        required_gate_ids=("G1", "G2"),
    )
    state = state_artifact.value
    assert isinstance(state, WorkflowState)
    tasks = tuple(
        replace(item, state=TaskState.COMPLETED, outcome=TaskOutcome.SUCCEEDED)
        for item in state.tasks
    )
    complete = replace(
        state,
        status=TaskState.COMPLETED,
        tasks=tasks,
        gates=(
            GateObservation("G1", GateStatus.PASS, (), ()),
            GateObservation("G2", GateStatus.PASS, ("EV-M8-DEMO",), ()),
        ),
        handoff_id="HANDOFF-M8-DEMO",
        handoff_status="completed",
        blockers=(),
    )
    disposition, blockers = completion_disposition(plan, complete)
    assert disposition is WorkflowDisposition.COMPLETED
    assert blockers == ()


def test_release_profile_adopts_native_observations_and_reaches_g1_through_g4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    (root / "workflow/source.py").write_text("VALUE = 1\n", encoding="utf-8")
    plan_artifact, _ = create_plan(root)
    plan_value = plan_artifact.value
    assert isinstance(plan_value, IntegratedPlan)
    plan = replace(
        plan_value,
        completion_profile=CompletionProfile.RELEASE_CANDIDATE_READY,
        required_gate_ids=("G1", "G2", "G3", "G4"),
    )
    scheduler = create_scheduler(root)
    native_store = SQLiteSchedulerStore(scheduler, root)
    graph_artifact = parse_scheduler_artifact_bytes(
        (root / plan.task_graph.reference.path).read_bytes(),
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    graph = graph_artifact.value
    assert isinstance(graph, TaskGraph)
    base = graph.tasks[0]
    task_kinds = (
        ("TSK-M8-EVIDENCE", TaskKind.IMPLEMENTATION),
        ("TSK-M8-REVIEW", TaskKind.REVIEW),
        ("TSK-M8-HANDOFF", TaskKind.HANDOFF),
        ("TSK-M8-INTEGRATION", TaskKind.INTEGRATION),
        ("TSK-M8-SOLVER", TaskKind.SOLVER),
    )
    synthetic_graph = replace(
        graph,
        tasks=tuple(
            replace(
                base,
                task_id=task_id,
                kind=kind,
                dependencies=(),
                review_targets=("TSK-M8-EVIDENCE",) if kind is TaskKind.REVIEW else (),
            )
            for task_id, kind in task_kinds
        ),
    )
    monkeypatch.setattr(
        runtime_module,
        "parse_scheduler_artifact_bytes",
        lambda *_args, **_kwargs: replace(graph_artifact, value=synthetic_graph),
    )

    observation_contents: dict[str, dict[str, object]] = {
        "ledger": {},
        "review": {},
        "review_fail": {},
        "handoff": {},
        "manifest": {"source_spec": {}, "platforms": {}, "ui": {}},
        "ui": {"ui_present": False, "observations": []},
        "release": {"install_evidence_id": "EV-INSTALL-M8"},
        "solver_result": {},
        "solver_verification": {},
    }
    references = {
        name: _write_observation(root, name, content)
        for name, content in observation_contents.items()
    }
    agent_references = {
        task_id: _write_observation(
            root,
            f"agent-{task_id.casefold()}",
            {"task_id": task_id},
        )
        for task_id, _kind in task_kinds
    }
    message_references = {
        "TSK-M8-EVIDENCE": (references["ledger"],),
        "TSK-M8-REVIEW": tuple(
            sorted(
                (references["review"], agent_references["TSK-M8-EVIDENCE"]),
                key=lambda item: (item.path, item.sha256),
            )
        ),
        "TSK-M8-HANDOFF": (references["handoff"],),
        "TSK-M8-INTEGRATION": (
            references["manifest"],
            references["release"],
            references["ui"],
        ),
        "TSK-M8-SOLVER": (
            references["solver_result"],
            references["solver_verification"],
        ),
    }
    messages = []
    events = []
    for sequence, (task_id, _) in enumerate(task_kinds, start=1):
        message_id = f"M6-MAILBOX-M8-{sequence}"
        message = MailboxMessage(
            message_type=MessageType.TASK_RESULT,
            direction=MessageDirection.HOST_TO_SCHEDULER,
            sender="HST-M8-FIXTURE",
            recipient="HST-M8-RUNTIME",
            graph_id=plan.task_graph.artifact_id,
            task_id=task_id,
            candidate=plan.candidate,
            context_snapshot_id=base.context_snapshot_id,
            attempt=1,
            lease_id=f"M6-LEASE-M8-{sequence}",
            fence=sequence,
            idempotency_key=f"M6-IDEM-M8-{sequence}",
            sensitivity=Sensitivity.PUBLIC,
            provenance=(),
            causal_parent_message_ids=(),
            recorded_at="2026-08-01T00:00:00Z",
            payload={
                "evidence_refs": [reference.to_dict() for reference in message_references[task_id]]
            },
        )
        messages.append(SimpleNamespace(artifact_id=message_id, value=message))
        events.append(
            SimpleNamespace(
                artifact_id=f"M6-EVENT-M8-{sequence}",
                value=SchedulerEvent(
                    sequence=sequence,
                    previous_event_sha256="0" * 64,
                    actor="HST-M8-FIXTURE",
                    cause="verification-completed",
                    graph_id=plan.task_graph.artifact_id,
                    task_id=task_id,
                    candidate=plan.candidate,
                    context_snapshot_id=base.context_snapshot_id,
                    before_state=TaskState.VERIFICATION.value,
                    after_state=TaskState.COMPLETED.value,
                    lease_id=f"M6-LEASE-M8-{sequence}",
                    message_id=message_id,
                    result_id=message_id,
                    approval_id=None,
                    budget_deltas={},
                    task_projection=None,
                    reason=None,
                    recorded_at="2026-08-01T00:00:00Z",
                ),
            )
        )

    class AcceptedResultStore:
        def completed_task_result_messages(self) -> tuple[Any, ...]:
            return tuple(messages)

        def export(self, kind: str) -> tuple[Any, ...]:
            if kind == "events":
                return tuple(events)
            if kind == "messages":
                return tuple(messages)
            return native_store.export(kind)

    ledger = SimpleNamespace(
        baseline_id=plan.requirement_baseline_id,
        source_spec_sha256=plan.candidate.source_spec_sha256,
        git_head=plan.candidate.git_head,
        repository_digest=plan.candidate.repository_digest,
        claims=(
            SimpleNamespace(claim_id="CLM-M8-VERIFIED", state=SimpleNamespace(value="verified")),
            SimpleNamespace(
                claim_id="CLM-M8-IMPLEMENTED",
                state=SimpleNamespace(value="implemented"),
            ),
            SimpleNamespace(
                claim_id="CLM-M8-KNOWN-PROBLEM",
                state=SimpleNamespace(value="known_problem"),
            ),
        ),
        evidence=(
            SimpleNamespace(
                evidence_id="EV-M8-NATIVE",
                status=SimpleNamespace(value="PASS"),
                claim_ids=("CLM-M8-VERIFIED",),
            ),
        ),
    )
    review = SimpleNamespace(
        candidate=plan.candidate,
        review_id="REV-M8-NATIVE",
        reviewer_id="AGT-M8-REVIEW",
        reviewed_agent_ids=("AGT-M8-EVIDENCE",),
        reviewed_paths=(
            "docs/decoy-authored-by-review.json",
            "examples/m2-orchestration/implementer-result.json",
        ),
    )
    failing_review = SimpleNamespace(
        candidate=plan.candidate,
        review_id="REV-M8-FAIL",
        reviewer_id=review.reviewer_id,
        reviewed_agent_ids=review.reviewed_agent_ids,
        reviewed_paths=review.reviewed_paths,
    )
    handoff = SimpleNamespace(
        baseline_id=plan.requirement_baseline_id,
        source_spec_sha256=plan.candidate.source_spec_sha256,
        head=plan.candidate.git_head,
        repository_digest=plan.candidate.repository_digest,
        incomplete=(),
        open_decisions=(),
        known_problems=(),
        status=HandoffStatus.COMPLETED,
    )
    manifest = SimpleNamespace(
        project_id=plan.project_id,
        source_spec_sha256=plan.candidate.source_spec_sha256,
    )
    ui_validation = SimpleNamespace(candidate=plan.candidate)
    verification = SimpleNamespace(
        adoption_allowed=True,
        candidate=plan.candidate,
        graph_id=plan.task_graph.artifact_id,
        task_id="TSK-M8-SOLVER",
        outcome=SimpleNamespace(value="verified"),
    )
    loaded_verification = SimpleNamespace(
        artifact_id="M7-SOLVER-VERIFICATION-M8",
        artifact_type=SolverArtifactType.VERIFICATION,
        value=verification,
    )
    loaded_solver_result = SimpleNamespace(
        artifact_id="M7-SOLVER-RESULT-M8",
        artifact_type=SolverArtifactType.RESULT,
        value=SimpleNamespace(),
    )

    monkeypatch.setattr(runtime_module, "SolverVerification", type(verification))
    monkeypatch.setattr(
        runtime_module,
        "load_solver_artifact",
        lambda path, **_kwargs: (
            loaded_verification
            if path.stem.endswith("solver_verification")
            else loaded_solver_result
        ),
    )
    agent_ids = {
        "TSK-M8-EVIDENCE": "AGT-M8-EVIDENCE",
        "TSK-M8-REVIEW": "AGT-M8-REVIEW",
        "TSK-M8-HANDOFF": "AGT-M8-HANDOFF",
        "TSK-M8-INTEGRATION": "AGT-M8-INTEGRATION",
        "TSK-M8-SOLVER": "AGT-M8-SOLVER",
    }

    def load_fixture_agent_result(
        _root: Path,
        _graph: TaskGraph,
        message: MailboxMessage,
    ) -> tuple[SimpleNamespace, ArtifactReference]:
        assert message.task_id is not None
        agent_id = agent_ids[message.task_id]
        return (
            SimpleNamespace(
                agent_id=agent_id,
                reviewed_agent_ids=("AGT-M8-EVIDENCE",)
                if message.task_id == "TSK-M8-REVIEW"
                else (),
            ),
            agent_references[message.task_id],
        )

    monkeypatch.setattr(runtime_module, "load_task_agent_result", load_fixture_agent_result)
    monkeypatch.setattr(runtime_module, "load_evidence_ledger", lambda _path: ledger)
    monkeypatch.setattr(
        runtime_module,
        "load_independent_review",
        lambda path: failing_review if path.stem.endswith("review_fail") else review,
    )
    monkeypatch.setattr(runtime_module, "load_automated_handoff", lambda _path: handoff)
    monkeypatch.setattr(runtime_module, "load_manifest_ui", lambda _path: manifest)
    monkeypatch.setattr(runtime_module, "load_ui_validation", lambda _path: ui_validation)
    monkeypatch.setattr(
        runtime_module,
        "load_release_candidate",
        lambda _path: SimpleNamespace(candidate=plan.candidate),
    )

    class PassingGateService:
        def evaluate(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(passed=True, to_dict=lambda: {"passed": True})

    class RecordingReviewGateService:
        def evaluate(self, *args: Any, **kwargs: Any) -> SimpleNamespace:
            assert kwargs["changed_paths"] == (
                "examples/m2-orchestration/implementer-result.json",
                "workflow/source.py",
            )
            assert kwargs["candidate_paths"] == (
                "examples/m2-orchestration/implementer-result.json",
                "workflow/source.py",
            )
            passed = args[0].review_id != failing_review.review_id
            return SimpleNamespace(passed=passed, to_dict=lambda: {"passed": passed})

    class FixtureGitInspector:
        def __init__(self, _runner: object) -> None:
            pass

        def inspect(self, _root: Path) -> GitObservation:
            return GitObservation(
                root_matches=True,
                branch="main",
                head=plan.candidate.git_head,
                clean=False,
                repository_digest="D" * 64,
                changed_paths=(
                    "examples/m2-orchestration/implementer-result.json",
                    "workflow/source.py",
                ),
                publication_paths=(
                    "examples/m2-orchestration/implementer-result.json",
                    "workflow/source.py",
                ),
            )

    monkeypatch.setattr(runtime_module, "ImplementationEvidenceGateService", PassingGateService)
    monkeypatch.setattr(
        runtime_module,
        "IndependentReviewGateService",
        RecordingReviewGateService,
    )
    monkeypatch.setattr(runtime_module, "UiValidationService", PassingGateService)
    monkeypatch.setattr(runtime_module, "ReleaseCandidateGateService", PassingGateService)
    publication_observation = WorkflowPublicationObservation(
        git=FixtureGitInspector(None).inspect(root),
        scheduler_state_path="workflow/scheduler.sqlite3",
        receipts=native_store.workflow_receipt_snapshot(plan_artifact.artifact_id),
        tracked_paths=(),
        untracked_non_ignored_paths=(),
        receipt_excluded_paths=(),
    )
    native = native_store.status().value
    assert isinstance(native, SchedulerState)
    native = replace(
        native,
        tasks=tuple(
            replace(
                native.tasks[0],
                task_id=task_id,
                state=TaskState.COMPLETED,
                outcome=TaskOutcome.SUCCEEDED,
            )
            for task_id, _kind in task_kinds
        ),
    )

    observations = runtime_module._derive_native_observations(
        plan,
        native,
        AcceptedResultStore(),  # type: ignore[arg-type]
        root,
        publication_observation,
    )
    assert observations.g2_passed is True
    assert observations.g3_passed is True
    assert observations.g4_passed is True
    assert observations.solver_verification_ids == ("M7-SOLVER-VERIFICATION-M8",)
    assert observations.evidence_ids == ("EV-M8-NATIVE",)
    assert observations.review_ids == ("REV-M8-NATIVE",)
    assert observations.handoff_status == "completed"
    assert len(observations.bindings) == 13
    assert observations.claim_count == 3
    assert observations.verified_claim_count == 1
    assert observations.unverified_claim_count == 1
    assert observations.evidence_known_problem_count == 1
    assert observations.missing_evidence_count == 2

    historical_native = replace(
        native,
        tasks=tuple(
            replace(
                task,
                state=(
                    TaskState.COMPLETED
                    if task.task_id == "TSK-M8-EVIDENCE"
                    else TaskState.RUNNING
                ),
                outcome=(
                    TaskOutcome.SUCCEEDED
                    if task.task_id == "TSK-M8-EVIDENCE"
                    else TaskOutcome.NONE
                ),
            )
            for task in native.tasks
        ),
    )
    historical = runtime_module._derive_native_observations(
        plan,
        historical_native,
        AcceptedResultStore(),  # type: ignore[arg-type]
        root,
        publication_observation,
    )
    assert historical.evidence_ids == ("EV-M8-NATIVE",)
    assert historical.review_ids == ()
    assert historical.handoff_status is None
    assert all(
        item.artifact_type not in {"independent-review", "automated-handoff"}
        for item in historical.bindings
    )

    def accepted_store_with(
        changed_messages: tuple[Any, ...],
    ) -> AcceptedResultStore:
        class ChangedAcceptedStore(AcceptedResultStore):
            def completed_task_result_messages(self) -> tuple[Any, ...]:
                return changed_messages

            def export(self, kind: str) -> tuple[Any, ...]:
                if kind == "messages":
                    return changed_messages
                return super().export(kind)

        return ChangedAcceptedStore()

    def result_messages_with(
        task_id: str,
        evidence_references: tuple[ArtifactReference, ...],
    ) -> tuple[Any, ...]:
        return tuple(
            SimpleNamespace(
                artifact_id=item.artifact_id,
                value=replace(
                    item.value,
                    payload={
                        "evidence_refs": [
                            reference.to_dict() for reference in evidence_references
                        ]
                    },
                ),
            )
            if item.value.task_id == task_id
            else item
            for item in messages
        )

    unknown_task_id = "TSK-M8-UNKNOWN"
    unknown_native = replace(
        native,
        tasks=(
            *native.tasks,
            replace(native.tasks[0], task_id=unknown_task_id),
        ),
    )
    unknown_message = SimpleNamespace(
        artifact_id="M6-MAILBOX-M8-0",
        value=replace(messages[0].value, task_id=unknown_task_id),
    )
    with pytest.raises(
        runtime_module.WorkflowRuntimeError,
        match="does not map to the Task Graph",
    ):
        runtime_module._derive_native_observations(
            plan,
            unknown_native,
            accepted_store_with((unknown_message, *messages)),  # type: ignore[arg-type]
            root,
            publication_observation,
        )

    def invalid_agent_result(
        _root: Path,
        _graph: TaskGraph,
        _message: MailboxMessage,
    ) -> tuple[SimpleNamespace, ArtifactReference]:
        raise ContractError("injected invalid Agent Result")

    with monkeypatch.context() as scoped:
        scoped.setattr(runtime_module, "load_task_agent_result", invalid_agent_result)
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="Accepted Agent Result failed validation",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                AcceptedResultStore(),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    def duplicate_agent_result_reference(
        _root: Path,
        graph_value: TaskGraph,
        message: MailboxMessage,
    ) -> tuple[SimpleNamespace, ArtifactReference]:
        result, _reference = load_fixture_agent_result(_root, graph_value, message)
        return result, agent_references["TSK-M8-EVIDENCE"]

    with monkeypatch.context() as scoped:
        scoped.setattr(
            runtime_module,
            "load_task_agent_result",
            duplicate_agent_result_reference,
        )
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="Agent Result reference is duplicated",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                AcceptedResultStore(),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    def invalid_skill_provenance(
        _root: Path,
        _capabilities: tuple[str, ...],
    ) -> tuple[object, ...]:
        raise SkillContractError("injected invalid Skill provenance")

    with monkeypatch.context() as scoped:
        scoped.setattr(
            runtime_module,
            "resolve_skill_capabilities",
            invalid_skill_provenance,
        )
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="Accepted Skill provenance is invalid",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                AcceptedResultStore(),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    invalid_reference_messages = tuple(
        SimpleNamespace(
            artifact_id=item.artifact_id,
            value=replace(item.value, payload={"evidence_refs": "not-a-list"}),
        )
        if item.value.task_id == "TSK-M8-EVIDENCE"
        else item
        for item in messages
    )
    with pytest.raises(
        runtime_module.WorkflowRuntimeError,
        match="evidence references are invalid",
    ):
        runtime_module._derive_native_observations(
            plan,
            native,
            accepted_store_with(invalid_reference_messages),  # type: ignore[arg-type]
            root,
            publication_observation,
        )

    stale_target = _write_observation(
        root,
        "stale-target-agent-result",
        {"agent_id": "AGT-M8-EVIDENCE"},
    )

    def review_store_with(
        review_references: tuple[ArtifactReference, ...],
    ) -> AcceptedResultStore:
        changed_messages = tuple(
            SimpleNamespace(
                artifact_id=item.artifact_id,
                value=replace(
                    item.value,
                    payload={
                        "evidence_refs": [
                            reference.to_dict()
                            for reference in sorted(
                                review_references,
                                key=lambda reference: (
                                    reference.path,
                                    reference.sha256,
                                ),
                            )
                        ]
                    },
                ),
            )
            if item.value.task_id == "TSK-M8-REVIEW"
            else item
            for item in messages
        )

        class ChangedReviewStore(AcceptedResultStore):
            def completed_task_result_messages(self) -> tuple[Any, ...]:
                return changed_messages

            def export(self, kind: str) -> tuple[Any, ...]:
                if kind == "messages":
                    return changed_messages
                return super().export(kind)

        return ChangedReviewStore()

    for invalid_references in (
        (references["review"],),
        (references["review"], stale_target),
        (
            references["review_fail"],
            references["review"],
            agent_references["TSK-M8-EVIDENCE"],
        ),
    ):
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="exact target Agent Result lineage",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                review_store_with(invalid_references),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    stale_review_reference = _write_observation(root, "review-stale", {})
    stale_review = SimpleNamespace(
        candidate=replace(plan.candidate, git_head="c" * 40),
        review_id="REV-M8-STALE",
        reviewer_id=review.reviewer_id,
        reviewed_agent_ids=review.reviewed_agent_ids,
        reviewed_paths=review.reviewed_paths,
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(
            runtime_module,
            "load_independent_review",
            lambda path: (
                stale_review if path.stem.endswith("review-stale") else review
            ),
        )
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="Independent Review candidate is stale",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                review_store_with(
                    (
                        stale_review_reference,
                        agent_references["TSK-M8-EVIDENCE"],
                    )
                ),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    identity_review_reference = _write_observation(root, "review-identity", {})
    identity_mismatch_review = SimpleNamespace(
        candidate=plan.candidate,
        review_id="REV-M8-IDENTITY-MISMATCH",
        reviewer_id="AGT-M8-WRONG-REVIEWER",
        reviewed_agent_ids=review.reviewed_agent_ids,
        reviewed_paths=review.reviewed_paths,
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(
            runtime_module,
            "load_independent_review",
            lambda path: (
                identity_mismatch_review
                if path.stem.endswith("review-identity")
                else review
            ),
        )
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="does not match completed target agents",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                review_store_with(
                    (
                        identity_review_reference,
                        agent_references["TSK-M8-EVIDENCE"],
                    )
                ),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    stale_ledger = SimpleNamespace(
        **{**vars(ledger), "baseline_id": "REQ-BASELINE-M8-STALE"}
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(runtime_module, "load_evidence_ledger", lambda _path: stale_ledger)
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="Evidence Ledger candidate is stale",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                AcceptedResultStore(),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    def invalid_native_observation(_path: Path) -> object:
        raise ContractError("injected native observation failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(runtime_module, "load_evidence_ledger", invalid_native_observation)
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="failed its existing validator",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                AcceptedResultStore(),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    duplicate_observation_cases = (
        (
            "TSK-M8-EVIDENCE",
            (references["ledger"], references["ledger"]),
            "native observation is duplicated",
        ),
        (
            "TSK-M8-HANDOFF",
            (references["handoff"], references["handoff"]),
            "Handoff observation slot is duplicated",
        ),
        (
            "TSK-M8-INTEGRATION",
            (references["release"], references["release"]),
            "Release Candidate observation slot is duplicated",
        ),
        (
            "TSK-M8-INTEGRATION",
            (references["ui"], references["ui"]),
            "UI validation observation slot is duplicated",
        ),
        (
            "TSK-M8-INTEGRATION",
            (references["manifest"], references["manifest"]),
            "Project Manifest observation slot is duplicated",
        ),
    )
    for task_id, duplicate_references, expected_error in duplicate_observation_cases:
        with pytest.raises(runtime_module.WorkflowRuntimeError, match=expected_error):
            runtime_module._derive_native_observations(
                plan,
                native,
                accepted_store_with(
                    result_messages_with(task_id, duplicate_references)
                ),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    stale_handoff = SimpleNamespace(
        **{**vars(handoff), "baseline_id": "REQ-BASELINE-M8-STALE"}
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(
            runtime_module,
            "load_automated_handoff",
            lambda _path: stale_handoff,
        )
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="Handoff is stale or incomplete",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                AcceptedResultStore(),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    stale_ui_validation = SimpleNamespace(
        candidate=replace(plan.candidate, git_head="c" * 40)
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(
            runtime_module,
            "load_ui_validation",
            lambda _path: stale_ui_validation,
        )
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="UI validation candidate is stale",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                AcceptedResultStore(),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    stale_manifest = SimpleNamespace(
        project_id="PRJ-M8-STALE",
        source_spec_sha256=plan.candidate.source_spec_sha256,
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(runtime_module, "load_manifest_ui", lambda _path: stale_manifest)
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="Project manifest candidate is stale",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                AcceptedResultStore(),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    unsupported_integration = _write_observation(root, "integration-unsupported", {})
    with pytest.raises(
        runtime_module.WorkflowRuntimeError,
        match="Integration observation type is unsupported",
    ):
        runtime_module._derive_native_observations(
            plan,
            native,
            accepted_store_with(
                result_messages_with(
                    "TSK-M8-INTEGRATION",
                    (unsupported_integration,),
                )
            ),  # type: ignore[arg-type]
            root,
            publication_observation,
        )

    unsupported_solver_artifact = SimpleNamespace(
        artifact_id="M7-SOLVER-REQUEST-M8",
        artifact_type=SolverArtifactType.REQUEST,
        value=SimpleNamespace(),
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(
            runtime_module,
            "load_solver_artifact",
            lambda path: (
                unsupported_solver_artifact
                if path.stem.endswith("solver_result")
                else loaded_verification
            ),
        )
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="Solver evidence type is unsupported",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                AcceptedResultStore(),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    stale_verification = SimpleNamespace(
        adoption_allowed=False,
        candidate=plan.candidate,
        graph_id=plan.task_graph.artifact_id,
        task_id="TSK-M8-SOLVER",
        outcome=SimpleNamespace(value="verified"),
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(
            runtime_module,
            "load_solver_artifact",
            lambda path: (
                SimpleNamespace(
                    artifact_id=loaded_verification.artifact_id,
                    artifact_type=loaded_verification.artifact_type,
                    value=stale_verification,
                )
                if path.stem.endswith("solver_verification")
                else loaded_solver_result
            ),
        )
        with pytest.raises(
            runtime_module.WorkflowRuntimeError,
            match="M7 verification is stale or not adoptable",
        ):
            runtime_module._derive_native_observations(
                plan,
                native,
                AcceptedResultStore(),  # type: ignore[arg-type]
                root,
                publication_observation,
            )

    incomplete_solver_messages = tuple(
        SimpleNamespace(
            artifact_id=item.artifact_id,
            value=replace(
                item.value,
                payload={
                    "evidence_refs": [references["solver_result"].to_dict()],
                },
            ),
        )
        if item.value.task_id == "TSK-M8-SOLVER"
        else item
        for item in messages
    )
    with pytest.raises(
        runtime_module.WorkflowRuntimeError,
        match="must bind one Result and one Verification",
    ):
        runtime_module._derive_native_observations(
            plan,
            native,
            accepted_store_with(incomplete_solver_messages),  # type: ignore[arg-type]
            root,
            publication_observation,
        )

    tasks = tuple(
        WorkflowTaskProjection(task_id, TaskState.COMPLETED, TaskOutcome.SUCCEEDED, 1, 1, ())
        for task_id, _ in task_kinds
    )
    gates = runtime_module._derive_gates(
        plan,
        tasks,
        observations.evidence_ids,
        observations.review_ids,
        observations.handoff_status,
        observations.g4_result_ids,
        observations.g4_passed,
    )
    assert tuple(item.status for item in gates) == (GateStatus.PASS,) * 4


def _write_observation(
    root: Path,
    name: str,
    content: dict[str, object],
) -> ArtifactReference:
    relative = f"workflow/native-{name}.json"
    payload = json.dumps(content, sort_keys=True).encode("utf-8") + b"\n"
    (root / relative).write_bytes(payload)
    return ArtifactReference(relative, hashlib.sha256(payload).hexdigest().upper())
