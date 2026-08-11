"""M8 approval, path, stale-identity, and protected-effect safety tests."""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import sdaqf.adapters.workflow as workflow_module
from sdaqf.adapters.process import SubprocessRunner
from sdaqf.adapters.scheduler import SchedulerTick, SQLiteSchedulerStore
from sdaqf.adapters.workflow import (
    ExclusiveWorkflowArtifactStore,
    RuntimePrivateCandidateVerifier,
    SystemWorkflowClock,
    WorkflowAdapterError,
    publication_candidate_paths,
)
from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.contracts import ContractError
from sdaqf.application.release_qa import repository_digest
from sdaqf.application.scheduler_contracts import (
    artifact_from_value as scheduler_artifact_from_value,
)
from sdaqf.application.scheduler_contracts import (
    load_scheduler_artifact,
    serialize_scheduler_artifact,
)
from sdaqf.application.workflow_contracts import (
    WorkflowContractError,
    artifact_from_value,
    serialize_workflow_artifact,
)
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity, GitObservation
from sdaqf.domain.scheduler import (
    EffectKind,
    Lease,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerState,
    TaskGraph,
)
from sdaqf.domain.workflow import (
    DevelopmentIntent,
    IntegratedPlan,
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowEvent,
    WorkflowEventCause,
    WorkflowState,
)
from sdaqf.ports.process import ProcessResult
from tests.m8_workflow_helpers import (
    FixedClock,
    create_intent,
    create_outcome,
    create_plan,
    create_planner,
    create_runtime,
    create_scheduler,
    create_workspace,
    workflow_binding,
)


def test_runtime_verifier_accepts_exact_plan_and_terminal_confirmed_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    plan, plan_path = create_plan(root)
    scheduler = create_scheduler(root)
    verifier = RuntimePrivateCandidateVerifier(SubprocessRunner())
    monkeypatch.setattr(verifier, "_tracked_paths", lambda _root: ())
    monkeypatch.setattr(verifier, "_is_ignored", lambda _root, _path: False)
    plan_receipt = (
        plan_path.relative_to(root).as_posix(),
        WorkflowArtifactType.INTEGRATED_PLAN.value,
        plan.artifact_id,
        "workflow-plan",
    )
    verifier.preflight_outputs(
        root,
        (plan_receipt,),
        scheduler_state=scheduler,
        plan_id=plan.artifact_id,
    )
    verifier.classify_output_paths(
        root,
        (plan_receipt[0],),
        scheduler_state=scheduler,
        plan_id=plan.artifact_id,
    )

    source_path = root / "workflow/receipt-retry-source-state.json"
    source = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        source_path,
        root / "workflow/receipt-retry-source-event.json",
    )
    create_outcome(FixedClock()).publish(
        source.state,
        workflow_binding(root, source_path, source.state),
        plan,
        root,
        scheduler,
        root / "workflow/receipt-retry-outcome.json",
        root / "workflow/receipt-retry-terminal-event.json",
        root / "workflow/receipt-retry-terminal-state.json",
    )
    head = SQLiteSchedulerStore(scheduler, root).workflow_head(plan.artifact_id)
    assert head is not None and head.phase.value == "terminal-confirmed"
    terminal = tuple(
        (item.path, item.artifact_type, item.artifact_id, item.producer)
        for item in head.receipts
        if item.producer == "workflow-outcome"
    )
    assert len(terminal) == 3
    verifier.preflight_outputs(
        root,
        terminal,
        scheduler_state=scheduler,
        plan_id=plan.artifact_id,
    )
    verifier.classify_output_paths(
        root,
        tuple(item[0] for item in terminal),
        scheduler_state=scheduler,
        plan_id=plan.artifact_id,
    )


def test_store_refuses_overwrite_and_parent_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    store = ExclusiveWorkflowArtifactStore(root)
    store.publish(Path("first.json"), b"{}\n")
    with pytest.raises(WorkflowAdapterError, match="already exists"):
        store.publish(Path("first.json"), b"{}\n")
    with pytest.raises(WorkflowAdapterError, match="escapes"):
        store.publish(Path("../escape.json"), b"{}\n")
    assert not (tmp_path / "escape.json").exists()


def test_runtime_private_outputs_do_not_change_candidate_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    source = root / "source.txt"
    source.write_text("candidate\n", encoding="utf-8")
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/state.json",
        root / "workflow/event.json",
    )
    expected = CandidateIdentity(
        source_spec_sha256="A" * 64,
        git_head="b" * 40,
        repository_digest=repository_digest(root, ("source.txt",)),
    )
    observation = GitObservation(
        root_matches=True,
        branch="main",
        head=expected.git_head,
        clean=False,
        repository_digest="F" * 64,
        changed_paths=(
            "workflow/event.json",
            "workflow/plan.json",
            "workflow/scheduler.sqlite3",
            "workflow/state.json",
        ),
        publication_paths=(
            "source.txt",
            "workflow/event.json",
            "workflow/plan.json",
            "workflow/scheduler.sqlite3",
            "workflow/state.json",
        ),
    )

    class _Inspector:
        def inspect(self, _root: Path) -> GitObservation:
            return observation

    verifier = RuntimePrivateCandidateVerifier(SubprocessRunner())
    monkeypatch.setattr(verifier, "_inspector", _Inspector())
    monkeypatch.setattr(verifier, "_tracked_paths", lambda _root: ())
    verifier.verify(root, expected, scheduler_state=scheduler)

    source.write_text("candidate drift\n", encoding="utf-8")
    with pytest.raises(WorkflowAdapterError, match="does not match"):
        verifier.verify(root, expected, scheduler_state=scheduler)


def test_runtime_verifier_revalidates_preflights_and_confirms_exact_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    source = root / "source.txt"
    source.write_text("candidate\n", encoding="utf-8")
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/state.json",
        root / "workflow/event.json",
    )
    expected = CandidateIdentity(
        source_spec_sha256="A" * 64,
        git_head="b" * 40,
        repository_digest=repository_digest(root, ("source.txt",)),
    )
    publication_paths = (
        "source.txt",
        "workflow/event.json",
        "workflow/plan.json",
        "workflow/scheduler.sqlite3",
        "workflow/state.json",
    )
    observed = GitObservation(
        root_matches=True,
        branch="main",
        head=expected.git_head,
        clean=False,
        repository_digest="F" * 64,
        changed_paths=publication_paths[1:],
        publication_paths=publication_paths,
    )

    class _Inspector:
        current = observed

        def inspect(self, _root: Path) -> GitObservation:
            return self.current

    inspector = _Inspector()
    verifier = RuntimePrivateCandidateVerifier(SubprocessRunner())
    monkeypatch.setattr(verifier, "_inspector", inspector)
    monkeypatch.setattr(verifier, "_tracked_paths", lambda _root: ())
    monkeypatch.setattr(verifier, "_is_ignored", lambda _root, _path: False)
    pinned = verifier.observe(root, expected, scheduler_state=scheduler)
    verifier.revalidate(root, pinned, scheduler_state=scheduler)

    inspector.current = replace(observed, branch="drift")
    with pytest.raises(WorkflowAdapterError, match="observation changed"):
        verifier.revalidate(root, pinned, scheduler_state=scheduler)
    inspector.current = observed

    scoped = verifier.observe(
        root,
        expected,
        scheduler_state=scheduler,
        plan_id=plan.artifact_id,
    )
    assert pinned.receipt_plan_id is None
    assert scoped.receipt_plan_id == plan.artifact_id
    authority = SQLiteSchedulerStore(scheduler, root)
    native_artifact = authority.status()
    native = native_artifact.value
    assert isinstance(native, SchedulerState)
    other_plan_id = "M8-INTEGRATED-PLAN-" + "F" * 64
    authority.open_workflow_epoch(
        plan_id=other_plan_id,
        candidate=pinned.receipts.candidate,
        graph_id=pinned.receipts.graph_id,
        scheduler_state_id=native_artifact.artifact_id,
        scheduler_event_sequence=native.event_sequence,
        scheduler_event_head_id=authority.current_event_head_id,
        idempotency_key="M8-IDEM-" + "F" * 64,
        producer="workflow-plan",
        artifact_id=other_plan_id,
        artifact_type=WorkflowArtifactType.INTEGRATED_PLAN.value,
        path="workflow/other-plan.json",
        recorded_at=FixedClock().now(),
    )
    with pytest.raises(WorkflowAdapterError, match="receipt snapshot changed"):
        verifier.revalidate(root, pinned, scheduler_state=scheduler)
    verifier.revalidate(root, scoped, scheduler_state=scheduler)

    fresh = (
        (
            "workflow/fresh-event.json",
            WorkflowArtifactType.WORKFLOW_EVENT.value,
            "M8-WORKFLOW-EVENT-" + "A" * 64,
            "workflow-outcome",
        ),
    )
    verifier.preflight_outputs(
        root,
        fresh,
        scheduler_state=scheduler,
        plan_id=plan.artifact_id,
    )
    with pytest.raises(WorkflowAdapterError, match="not exact and unique"):
        verifier.preflight_outputs(
            root,
            (fresh[0], fresh[0]),
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )
    monkeypatch.setattr(verifier, "_tracked_paths", lambda _root: (fresh[0][0],))
    with pytest.raises(WorkflowAdapterError, match="tracked"):
        verifier.preflight_outputs(
            root,
            fresh,
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )
    monkeypatch.setattr(verifier, "_tracked_paths", lambda _root: ())
    monkeypatch.setattr(verifier, "_is_ignored", lambda _root, _path: True)
    with pytest.raises(WorkflowAdapterError, match="ignored"):
        verifier.preflight_outputs(
            root,
            fresh,
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )
    monkeypatch.setattr(verifier, "_is_ignored", lambda _root, _path: False)
    (root / fresh[0][0]).write_bytes(b"{}\n")
    with pytest.raises(WorkflowAdapterError, match="foreign"):
        verifier.preflight_outputs(
            root,
            fresh,
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )

    head = SQLiteSchedulerStore(scheduler, root).workflow_head(plan.artifact_id)
    assert head is not None
    artifacts = tuple(
        (
            receipt.path,
            receipt.artifact_type,
            receipt.artifact_id,
            receipt.producer,
        )
        for receipt in head.receipts
    )
    monkeypatch.setattr(verifier, "preflight_outputs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(verifier, "observe", lambda *_args, **_kwargs: pinned)
    verifier.confirm_outputs(
        root,
        pinned,
        expected,
        artifacts,
        scheduler_state=scheduler,
        plan_id=plan.artifact_id,
    )
    wrong = (artifacts[0][0], artifacts[0][1], artifacts[0][2], "wrong-producer")
    with pytest.raises(WorkflowAdapterError, match="not exact and confirmed"):
        verifier.confirm_outputs(
            root,
            pinned,
            expected,
            (wrong,),
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )
    monkeypatch.setattr(
        verifier,
        "observe",
        lambda *_args, **_kwargs: replace(
            pinned,
            git=replace(pinned.git, branch="drift"),
        ),
    )
    with pytest.raises(WorkflowAdapterError, match="changed the pinned Git authority"):
        verifier.confirm_outputs(
            root,
            pinned,
            expected,
            (),
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )
    monkeypatch.setattr(
        verifier,
        "observe",
        lambda *_args, **_kwargs: replace(
            pinned,
            receipts=replace(pinned.receipts, heads=()),
        ),
    )
    with pytest.raises(WorkflowAdapterError, match="head disappeared"):
        verifier.confirm_outputs(
            root,
            pinned,
            expected,
            (),
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )

    first_head = pinned.receipts.heads[0]
    first_receipt = first_head.receipts[0]
    ambiguous = replace(pinned.receipts, heads=(first_head, first_head))
    with pytest.raises(WorkflowAdapterError, match="ambiguously"):
        workflow_module._matching_receipt(ambiguous, first_receipt.path)
    graph_path = root / "examples/m6-scheduler/task-graph.json"
    graph = load_scheduler_artifact(
        graph_path,
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    assert (
        workflow_module._canonical_artifact_id(
            graph_path,
            SchedulerArtifactType.TASK_GRAPH.value,
        )
        == graph.artifact_id
    )


def test_runtime_verifier_git_classification_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(shutil, "which", lambda _name: os.__file__)

    class _Runner:
        ignored = False
        truncated = False

        def run(self, args: Sequence[str]) -> ProcessResult:
            text = tuple(args)
            if "check-ignore" in text:
                return ProcessResult(
                    0 if self.ignored else 1,
                    "",
                    "",
                    stdout_truncated=self.truncated,
                )
            return ProcessResult(
                0,
                "tracked.txt\0workflow/plan.json\0",
                "",
                stderr_truncated=self.truncated,
            )

    runner = _Runner()
    verifier = RuntimePrivateCandidateVerifier(runner)
    assert verifier._tracked_paths(root) == ("tracked.txt", "workflow/plan.json")
    assert not verifier._is_ignored(root, "candidate.json")
    runner.ignored = True
    assert verifier._is_ignored(root, "candidate.json")
    runner.truncated = True
    with pytest.raises(WorkflowAdapterError, match="ignore classification"):
        verifier._is_ignored(root, "candidate.json")
    with pytest.raises(WorkflowAdapterError, match="tracked-path enumeration"):
        verifier._tracked_paths(root)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(WorkflowAdapterError, match="Git is unavailable"):
        verifier._is_ignored(root, "candidate.json")
    with pytest.raises(WorkflowAdapterError, match="Git is unavailable"):
        verifier._tracked_paths(root)


def test_arbitrary_workflow_source_is_in_candidate_and_case_collisions_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    (root / "source.txt").write_text("candidate\n", encoding="utf-8")
    workflow = root / "workflow"
    (workflow / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
    _plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    expected = CandidateIdentity(
        source_spec_sha256="A" * 64,
        git_head="b" * 40,
        repository_digest=repository_digest(root, ("source.txt", "workflow/source.py")),
    )

    class _Inspector:
        def __init__(self, paths: tuple[str, ...]) -> None:
            self._paths = paths

        def inspect(self, _root: Path) -> GitObservation:
            return GitObservation(
                root_matches=True,
                branch="main",
                head=expected.git_head,
                clean=False,
                repository_digest="F" * 64,
                changed_paths=self._paths,
                publication_paths=self._paths,
            )

    verifier = RuntimePrivateCandidateVerifier(SubprocessRunner())
    monkeypatch.setattr(verifier, "_tracked_paths", lambda _root: ())
    monkeypatch.setattr(
        verifier,
        "_inspector",
        _Inspector(("source.txt", "workflow/source.py")),
    )
    verifier.verify(root, expected, scheduler_state=scheduler)

    monkeypatch.setattr(
        verifier,
        "_inspector",
        _Inspector(("source.txt", "workflow/source.py", "Workflow/source.py")),
    )
    with pytest.raises(WorkflowAdapterError, match="case collision"):
        verifier.verify(root, expected, scheduler_state=scheduler)


def test_output_classification_rejects_tracked_ignored_case_alias_reparse_and_foreign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    verifier = RuntimePrivateCandidateVerifier(SubprocessRunner())
    target = "workflow/terminal.json"
    monkeypatch.setattr(verifier, "_tracked_paths", lambda _root: (target,))
    monkeypatch.setattr(verifier, "_is_ignored", lambda _root, _path: False)
    with pytest.raises(WorkflowAdapterError, match="tracked"):
        verifier.classify_output_paths(
            root,
            (target,),
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )

    monkeypatch.setattr(verifier, "_tracked_paths", lambda _root: ())
    monkeypatch.setattr(verifier, "_is_ignored", lambda _root, _path: True)
    with pytest.raises(WorkflowAdapterError, match="ignored"):
        verifier.classify_output_paths(
            root,
            (target,),
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )

    monkeypatch.setattr(verifier, "_is_ignored", lambda _root, _path: False)
    with pytest.raises(WorkflowAdapterError, match="case alias"):
        verifier.classify_output_paths(
            root,
            ("Workflow/new.json",),
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )

    monkeypatch.setattr(
        workflow_module,
        "is_reparse_point",
        lambda path: Path(path).name == "reparse.json",
    )
    with pytest.raises(WorkflowAdapterError, match="link or reparse"):
        verifier.classify_output_paths(
            root,
            ("workflow/reparse.json",),
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )

    monkeypatch.setattr(workflow_module, "is_reparse_point", lambda _path: False)
    (root / target).write_bytes(b"{}\n")
    with pytest.raises(WorkflowAdapterError, match="foreign"):
        verifier.classify_output_paths(
            root,
            (target,),
            scheduler_state=scheduler,
            plan_id=plan.artifact_id,
        )


def test_idempotent_publication_rejects_hardlink_alias(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, plan_path = create_plan(root)
    alias = root / "workflow/plan-hardlink.json"
    try:
        os.link(plan_path, alias)
    except OSError:
        pytest.skip("hard links are unavailable")
    with pytest.raises(WorkflowAdapterError, match="linked"):
        ExclusiveWorkflowArtifactStore(root).publish_idempotent(
            alias,
            plan_path.read_bytes(),
            artifact_type=WorkflowArtifactType.INTEGRATED_PLAN.value,
            artifact_id=plan.artifact_id,
        )


def test_untrusted_intent_cannot_make_owner_approval_disappear(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    graph_path = root / "examples/m6-scheduler/task-graph.json"
    loaded = load_scheduler_artifact(
        graph_path,
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    graph = loaded.value
    assert isinstance(graph, TaskGraph)
    protected_task = replace(
        graph.tasks[0],
        effect_kind=EffectKind.EXTERNAL,
        approval_stops=("owner",),
    )
    protected_graph = replace(graph, tasks=(protected_task,))
    protected_artifact = scheduler_artifact_from_value(
        SchedulerArtifactType.TASK_GRAPH, protected_graph
    )
    graph_path.write_bytes(serialize_scheduler_artifact(protected_artifact))
    intent_artifact, intent_path = create_intent(root)
    assert isinstance(intent_artifact.value, DevelopmentIntent)
    intent = replace(
        intent_artifact.value,
        requested_effects=(EffectKind.EXTERNAL,),
    )
    intent_artifact = artifact_from_value(WorkflowArtifactType.DEVELOPMENT_INTENT, intent)
    intent_path.write_bytes(serialize_workflow_artifact(intent_artifact))
    from sdaqf.application.workflow_planning import artifact_reference_for

    scheduler = create_scheduler(root)
    plan = create_planner().publish_plan(
        intent_artifact,
        artifact_reference_for(root, intent_path),
        root,
        scheduler,
        root / "workflow/protected-plan.json",
        recorded_at=FixedClock().now(),
    )
    transition = create_runtime(FixedClock()).run(
        plan,
        root,
        scheduler,
        root / "workflow/protected-state.json",
        root / "workflow/protected-event.json",
    )
    event = transition.event.value
    state = transition.state.value
    assert isinstance(event, WorkflowEvent)
    assert isinstance(state, WorkflowState)
    assert event.cause is WorkflowEventCause.APPROVAL_BLOCKED
    assert not transition.outgoing_intent_ids
    assert not transition.protected_effect_ids
    assert any(item.code.startswith("approval-") for item in state.blockers)


def test_runtime_refuses_state_whose_latest_event_bytes_drifted(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    runtime = create_runtime(FixedClock())
    transition = runtime.run(
        plan,
        root,
        scheduler,
        root / "workflow/state.json",
        root / "workflow/event.json",
    )
    (root / "workflow/event.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(WorkflowContractError):
        runtime.status(transition.state, plan, root, scheduler)


def test_runtime_reobserves_candidate_and_context_before_transition(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    candidate_marker = root / "workflow/candidate.json"
    candidate_marker.write_text("{}\n", encoding="utf-8")
    with pytest.raises(WorkflowContractError, match="Candidate"):
        create_runtime(FixedClock()).run(
            plan,
            root,
            scheduler,
            root / "workflow/stale-candidate-state.json",
            root / "workflow/stale-candidate-event.json",
        )
    assert not (root / "workflow/stale-candidate-state.json").exists()

    context_case = tmp_path / "context"
    context_case.mkdir()
    root = create_workspace(context_case)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    (root / "examples/m5-context/sources/accepted-contract.md").write_text(
        "# Drifted context\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkflowContractError):
        create_runtime(FixedClock()).run(
            plan,
            root,
            scheduler,
            root / "workflow/stale-context-state.json",
            root / "workflow/stale-context-event.json",
        )
    assert not (root / "workflow/stale-context-state.json").exists()


def test_runtime_reads_every_event_in_state_chain(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    runtime = create_runtime(FixedClock())
    first = runtime.run(
        plan,
        root,
        scheduler,
        root / "workflow/chain-state-1.json",
        root / "workflow/chain-event-1.json",
    )
    second = runtime.resume(
        first.state,
        workflow_binding(root, root / "workflow/chain-state-1.json", first.state),
        plan,
        root,
        scheduler,
        root / "workflow/chain-state-2.json",
        root / "workflow/chain-event-2.json",
    )
    (root / "workflow/chain-event-1.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(WorkflowContractError):
        runtime.status(second.state, plan, root, scheduler)


def test_protected_dispatch_requires_exact_consumed_native_approval(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    graph_path = root / "examples/m6-scheduler/task-graph.json"
    loaded = load_scheduler_artifact(
        graph_path,
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    graph = loaded.value
    assert isinstance(graph, TaskGraph)
    task = replace(
        graph.tasks[0],
        effect_kind=EffectKind.EXTERNAL,
        approval_stops=("owner",),
    )
    protected_graph = replace(graph, tasks=(task,))
    graph_artifact = scheduler_artifact_from_value(
        SchedulerArtifactType.TASK_GRAPH, protected_graph
    )
    graph_path.write_bytes(serialize_scheduler_artifact(graph_artifact))
    intent_artifact, intent_path = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    intent = replace(intent, requested_effects=(EffectKind.EXTERNAL,))
    intent_artifact = artifact_from_value(WorkflowArtifactType.DEVELOPMENT_INTENT, intent)
    intent_path.write_bytes(serialize_workflow_artifact(intent_artifact))
    from sdaqf.application.workflow_planning import artifact_reference_for

    scheduler = create_scheduler(root)
    plan_artifact = create_planner().publish_plan(
        intent_artifact,
        artifact_reference_for(root, intent_path),
        root,
        scheduler,
        root / "workflow/approval-wait-plan.json",
        recorded_at=FixedClock().now(),
    )
    plan = plan_artifact.value
    assert isinstance(plan, IntegratedPlan)
    runtime = create_runtime(FixedClock())
    runtime.run(
        plan_artifact,
        root,
        scheduler,
        root / "workflow/approval-wait-state.json",
        root / "workflow/approval-wait-event.json",
    )
    store = SQLiteSchedulerStore(scheduler, root)
    proposal_artifact = store.export("leases")[-1]
    proposal = proposal_artifact.value
    assert isinstance(proposal, Lease)
    binding = protected_graph.contexts[0]
    recorded_at = FixedClock().now()
    stamp = recorded_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    expiry = (recorded_at + timedelta(hours=1)).isoformat(timespec="seconds").replace("+00:00", "Z")
    approval = scheduler_artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        MailboxMessage(
            message_type=MessageType.APPROVAL_DECISION,
            direction=MessageDirection.OWNER_TO_SCHEDULER,
            sender="HST-OWNER",
            recipient="HST-SCHEDULER",
            graph_id=graph_artifact.artifact_id,
            task_id=task.task_id,
            candidate=protected_graph.candidate,
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
                "approval_id": "APR-M8-OWNER-DISPATCH",
                "approval_type": "owner",
                "decision": "approved",
                "transition": "dispatch",
                "effect_digest": hashlib.sha256(canonical_json_bytes(task.to_dict()))
                .hexdigest()
                .upper(),
                "approved_at": stamp,
                "expires_at": expiry,
                "authority": "Owner",
                "supersedes_approval_id": None,
            },
        ),
    )
    tick = store.tick(
        root,
        "HST-M8-RUNTIME",
        (approval,),
        recorded_at,
    )
    assert len(tick.outgoing) == 1
    protected, approvals = runtime._revalidate_protected_effects(plan, tick, scheduler, root)
    assert protected == (plan.protected_effects[0].effect_id,)
    assert approvals == ("APR-M8-OWNER-DISPATCH",)

    message = tick.outgoing[0].value
    assert isinstance(message, MailboxMessage)
    assert message.fence is not None
    stale_message = scheduler_artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        replace(message, fence=message.fence + 1),
    )
    stale_tick = SchedulerTick(tick.state, (stale_message,), (), ())
    with pytest.raises(WorkflowContractError, match="fresh fenced Lease"):
        runtime._revalidate_protected_effects(plan, stale_tick, scheduler, root)


def test_local_workflow_adapters_fail_closed_on_every_publication_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = SystemWorkflowClock().now()
    offset = observed.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0
    missing = tmp_path / "missing"
    with pytest.raises(WorkflowAdapterError, match="unavailable"):
        ExclusiveWorkflowArtifactStore(missing)
    regular_file = tmp_path / "file"
    regular_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(WorkflowAdapterError, match="directory"):
        ExclusiveWorkflowArtifactStore(regular_file)

    root = tmp_path / "root"
    root.mkdir()
    store = ExclusiveWorkflowArtifactStore(root)
    payload = root / "payload.json"
    store.publish(payload, b"{}\n")
    valid_reference = ArtifactReference(
        "payload.json",
        hashlib.sha256(payload.read_bytes()).hexdigest().upper(),
    )
    assert store.load(valid_reference, 16) == b"{}\n"
    with pytest.raises(WorkflowAdapterError, match="positive"):
        store.load(valid_reference, 0)
    with pytest.raises(WorkflowAdapterError, match="byte bound"):
        store.load(valid_reference, 2)
    with pytest.raises(WorkflowAdapterError, match="digest"):
        store.load(replace(valid_reference, sha256="A" * 64), 16)
    with pytest.raises(WorkflowAdapterError, match="regular"):
        store.load(ArtifactReference("missing.json", "A" * 64), 16)
    with pytest.raises(WorkflowAdapterError, match="escapes"):
        store.load(ArtifactReference("../outside.json", "A" * 64), 16)
    with pytest.raises(WorkflowAdapterError, match="empty"):
        store.read_event_chain((), 1)
    invalid_event_binding = NativeArtifactBinding(
        WorkflowArtifactType.WORKFLOW_EVENT.value,
        "M8-WORKFLOW-EVENT-" + "A" * 64,
        valid_reference,
        False,
    )
    with pytest.raises(WorkflowAdapterError, match="exact"):
        store.read_event_chain((invalid_event_binding,), 1)
    with pytest.raises(WorkflowAdapterError, match="JSON"):
        store.publish(Path("output.txt"), b"{}\n")
    with pytest.raises(WorkflowAdapterError, match="escapes"):
        store.publish(Path("../output.json"), b"{}\n")
    with pytest.raises(WorkflowAdapterError, match="already exists"):
        store.publish(payload, b"{}\n")
    with pytest.raises(WorkflowAdapterError, match="unsuccessful"):
        store.publish(Path("missing/output.json"), b"{}\n")
    bad_parent = root / "bad-parent"
    bad_parent.write_text("not a directory", encoding="utf-8")
    with pytest.raises(WorkflowAdapterError, match="parent"):
        store.publish(Path("bad-parent/output.json"), b"{}\n")

    def fail_link(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic hard-link failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(WorkflowAdapterError, match="unsuccessful"):
        store.publish(Path("failed.json"), b"{}\n")
    assert not (root / "failed.json").exists()

    class _BrokenInspector:
        def inspect(self, _root: Path) -> GitObservation:
            raise ContractError("synthetic inspection failure")

    verifier = RuntimePrivateCandidateVerifier(SubprocessRunner())
    monkeypatch.setattr(verifier, "_inspector", _BrokenInspector())
    with pytest.raises(WorkflowAdapterError, match="could not be inspected"):
        verifier.verify(
            root,
            CandidateIdentity("A" * 64, "b" * 40, "C" * 64),
            scheduler_state=root / "workflow/missing.sqlite3",
        )


def test_runtime_classification_handles_sqlite_links_and_io_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    workflow = root / "workflow"
    workflow.mkdir(parents=True)
    invalid_database = workflow / "invalid.sqlite3"
    invalid_database.write_bytes(b"not sqlite")
    assert publication_candidate_paths(root, ("workflow/invalid.sqlite3",)) == (
        "workflow/invalid.sqlite3",
    )
    valid_header = bytearray(72)
    valid_header[:16] = b"SQLite format 3\x00"
    valid_header[68:72] = (0x53444151).to_bytes(4, "big")
    runtime_database = workflow / "runtime.sqlite3"
    runtime_database.write_bytes(valid_header)
    assert publication_candidate_paths(root, ("workflow/runtime.sqlite3",)) == (
        "workflow/runtime.sqlite3",
    )

    linked = workflow / "linked.json"
    linked.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        workflow_module,
        "is_reparse_point",
        lambda path: path.name == "linked.json",
    )
    with pytest.raises(WorkflowAdapterError, match="link or reparse"):
        publication_candidate_paths(root, ("workflow/linked.json",))
    monkeypatch.setattr(workflow_module, "is_reparse_point", lambda _path: False)

    broken = workflow / "broken.json"
    broken.write_text("{}\n", encoding="utf-8")
    assert publication_candidate_paths(root, ("workflow/broken.json",)) == (
        "workflow/broken.json",
    )
