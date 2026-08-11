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
from sdaqf.application.scheduler_contracts import parse_scheduler_artifact_bytes
from sdaqf.application.workflow_outcome import completion_disposition
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.quality import ArtifactReference, GitObservation, HandoffStatus
from sdaqf.domain.scheduler import (
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerEvent,
    TaskGraph,
    TaskKind,
    TaskOutcome,
    TaskState,
)
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
            replace(base, task_id=task_id, kind=kind, dependencies=())
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
        "solver": {},
    }
    references = {
        name: _write_observation(root, name, content)
        for name, content in observation_contents.items()
    }
    message_references = {
        "TSK-M8-EVIDENCE": (references["ledger"],),
        "TSK-M8-REVIEW": (references["review"],),
        "TSK-M8-HANDOFF": (references["handoff"],),
        "TSK-M8-INTEGRATION": (
            references["manifest"],
            references["release"],
            references["ui"],
        ),
        "TSK-M8-SOLVER": (references["solver"],),
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
        reviewed_paths=(
            "docs/decoy-authored-by-review.json",
            "examples/m2-orchestration/implementer-result.json",
        ),
    )
    failing_review = SimpleNamespace(
        candidate=plan.candidate,
        review_id="REV-M8-FAIL",
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
        value=verification,
    )

    monkeypatch.setattr(runtime_module, "SolverVerification", type(verification))
    monkeypatch.setattr(
        runtime_module,
        "load_solver_artifact",
        lambda *_args, **_kwargs: loaded_verification,
    )
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

    observations = runtime_module._derive_native_observations(
        plan,
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
    assert len(observations.bindings) == 7
    assert observations.claim_count == 3
    assert observations.verified_claim_count == 1
    assert observations.unverified_claim_count == 1
    assert observations.evidence_known_problem_count == 1
    assert observations.missing_evidence_count == 2

    contradictory_messages = tuple(
        SimpleNamespace(
            artifact_id=item.artifact_id,
            value=replace(
                item.value,
                payload={
                    "evidence_refs": [
                        references["review_fail"].to_dict(),
                        references["review"].to_dict(),
                    ]
                },
            ),
        )
        if item.value.task_id == "TSK-M8-REVIEW"
        else item
        for item in messages
    )

    class ContradictoryReviewStore(AcceptedResultStore):
        def export(self, kind: str) -> tuple[Any, ...]:
            if kind == "messages":
                return contradictory_messages
            return super().export(kind)

    contradictory = runtime_module._derive_native_observations(
        plan,
        ContradictoryReviewStore(),  # type: ignore[arg-type]
        root,
        publication_observation,
    )
    assert contradictory.review_ids == ("REV-M8-FAIL", "REV-M8-NATIVE")
    assert contradictory.g3_passed is False

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
