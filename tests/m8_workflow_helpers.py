"""Shared deterministic fixtures for M8 workflow tests and validation."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.adapters.context import (
    CanonicalUTF8ByteEstimator,
    LocalContextSourceReader,
)
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.context_contracts import (
    artifact_from_value as context_artifact_from_value,
)
from sdaqf.application.context_contracts import (
    load_context_artifact,
    serialize_context_artifact,
)
from sdaqf.application.scheduler import SchedulerService
from sdaqf.application.scheduler_contracts import (
    artifact_from_value as scheduler_artifact_from_value,
)
from sdaqf.application.scheduler_contracts import (
    load_scheduler_artifact,
    serialize_scheduler_artifact,
)
from sdaqf.application.workflow_contracts import (
    LoadedWorkflowArtifact,
    artifact_from_value,
    load_workflow_artifact,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_explanation import WorkflowExplainer
from sdaqf.application.workflow_outcome import WorkflowOutcomeService
from sdaqf.application.workflow_planning import IntegratedPlanner, artifact_reference_for
from sdaqf.application.workflow_recovery import WorkflowRecoveryService
from sdaqf.application.workflow_runtime import WorkflowRuntimeService
from sdaqf.domain.context import (
    ContextArtifactType,
    ContextGraph,
    ContextQuery,
    ContextSelection,
    ContextSnapshot,
    Sensitivity,
)
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity, GitObservation
from sdaqf.domain.scheduler import (
    EffectKind,
    SchedulerArtifactType,
    SchedulerBudget,
    TaskGraph,
)
from sdaqf.domain.workflow import (
    CompletionProfile,
    DevelopmentIntent,
    IntegratedPlan,
    IntentRisk,
    IntentTaskLink,
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowPublicationObservation,
)

ROOT = Path(__file__).resolve().parents[1]
FIXED_TIME = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
SOURCE_DIGEST = "050EA855693A9DD43303872934824E4B116A9210CECBD3CAA6F24F9EB9823FF4"
CANDIDATE = CandidateIdentity(
    source_spec_sha256=SOURCE_DIGEST,
    git_head="b" * 40,
    repository_digest="C" * 64,
)


@dataclass(slots=True)
class FixedClock:
    """Clock shared by M6 and M8 deterministic tests."""

    value: datetime = FIXED_TIME

    def now(self) -> datetime:
        return self.value


class FixtureCandidateVerifier:
    """Reobserve one explicit synthetic Candidate marker without Git."""

    def verify(
        self,
        repository_root: Path,
        expected: CandidateIdentity,
        *,
        scheduler_state: Path | None = None,
    ) -> None:
        del scheduler_state
        marker = repository_root / "workflow" / "candidate.json"
        observed = json.loads(marker.read_text(encoding="utf-8"))
        if observed != expected.to_dict():
            raise RuntimeError("Synthetic Candidate marker drifted.")

    def observe(
        self,
        repository_root: Path,
        expected: CandidateIdentity,
        *,
        scheduler_state: Path,
        plan_id: str | None = None,
    ) -> WorkflowPublicationObservation:
        self.verify(repository_root, expected, scheduler_state=scheduler_state)
        store = SQLiteSchedulerStore(scheduler_state, repository_root)
        store.validate()
        store.require_workflow_authority()
        snapshot = store.workflow_receipt_snapshot(plan_id)
        return WorkflowPublicationObservation(
            git=GitObservation(
                root_matches=True,
                branch="fixture",
                head=expected.git_head,
                clean=True,
                repository_digest=expected.repository_digest,
                changed_paths=(),
                publication_paths=(),
            ),
            scheduler_state_path=scheduler_state.relative_to(repository_root).as_posix(),
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
        marker = json.loads(
            (repository_root / "workflow" / "candidate.json").read_text(encoding="utf-8")
        )
        if (
            marker.get("git_head") != observation.git.head
            or marker.get("repository_digest") != observation.git.repository_digest
        ):
            raise RuntimeError("Synthetic Candidate marker drifted.")
        current = SQLiteSchedulerStore(
            scheduler_state, repository_root
        ).workflow_receipt_snapshot(observation.receipt_plan_id)
        if current != observation.receipts:
            raise RuntimeError("Synthetic M6 receipt snapshot drifted.")

    def preflight_outputs(
        self,
        repository_root: Path,
        artifacts: tuple[tuple[str, str, str, str], ...],
        *,
        scheduler_state: Path,
        plan_id: str,
    ) -> None:
        store = SQLiteSchedulerStore(scheduler_state, repository_root)
        head = store.workflow_head(plan_id)
        receipts = {} if head is None else {item.path: item for item in head.receipts}
        portable: set[str] = set()
        for relative, artifact_type, artifact_id, producer in artifacts:
            folded = relative.casefold()
            if folded in portable:
                raise RuntimeError("Synthetic output path collision.")
            portable.add(folded)
            target = repository_root / relative
            if target.exists():
                receipt = receipts.get(relative)
                if (
                    receipt is None
                    or receipt.artifact_type != artifact_type
                    or receipt.artifact_id != artifact_id
                    or receipt.producer != producer
                ):
                    raise RuntimeError("Synthetic output is foreign.")

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
        portable: set[str] = set()
        for relative in paths:
            folded = relative.casefold()
            if folded in portable:
                raise RuntimeError("Synthetic output path collision.")
            portable.add(folded)
            if (repository_root / relative).exists() and relative not in receipts:
                raise RuntimeError("Synthetic output is foreign.")

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
        self.verify(repository_root, expected, scheduler_state=scheduler_state)
        head = SQLiteSchedulerStore(scheduler_state, repository_root).workflow_head(plan_id)
        if head is None:
            raise RuntimeError("Synthetic terminal head disappeared.")
        receipts = {item.path: item for item in head.receipts}
        for relative, artifact_type, artifact_id, producer in artifacts:
            receipt = receipts.get(relative)
            if (
                receipt is None
                or receipt.artifact_type != artifact_type
                or receipt.artifact_id != artifact_id
                or receipt.producer != producer
                or receipt.status.value != "confirmed"
            ):
                raise RuntimeError("Synthetic terminal receipt is not confirmed.")


def create_planner() -> IntegratedPlanner:
    """Return the exact candidate-aware pure planner used by M8 fixtures."""

    return IntegratedPlanner(
        FixtureCandidateVerifier(),
        LocalContextSourceReader(),
        CanonicalUTF8ByteEstimator(),
    )


def create_runtime(clock: FixedClock | None = None) -> WorkflowRuntimeService:
    """Return a runtime wired to the candidate-aware fixture planner."""

    return WorkflowRuntimeService(
        FixedClock() if clock is None else clock,
        planner=create_planner(),
    )


def create_explainer() -> WorkflowExplainer:
    """Return an explainer wired to exact current-source replay."""

    return WorkflowExplainer(create_planner())


def create_recovery(clock: FixedClock | None = None) -> WorkflowRecoveryService:
    """Return recovery wired to current candidate and Context replay."""

    return WorkflowRecoveryService(
        FixedClock() if clock is None else clock,
        planner=create_planner(),
    )


def create_outcome(clock: FixedClock | None = None) -> WorkflowOutcomeService:
    """Return Outcome derivation wired to exact native replay."""

    return WorkflowOutcomeService(
        FixedClock() if clock is None else clock,
        planner=create_planner(),
    )


def create_workspace(tmp_path: Path) -> Path:
    """Copy only exact public native inputs and create one valid M1 baseline."""

    root = tmp_path / "workspace"
    required = (
        "examples/m2-orchestration/agent-registry.json",
        "examples/m2-orchestration/implementer-result.json",
        "examples/m2-orchestration/tool-registry.json",
        "examples/m2-orchestration/orchestration-request.json",
        "examples/m5-context/context-graph.json",
        "examples/m5-context/context-query.json",
        "examples/m5-context/context-selection.json",
        "examples/m5-context/context-snapshot.json",
        "examples/m5-context/sources/accepted-contract.md",
        "examples/m5-context/sources/specification.md",
        "examples/m5-context/sources/verified-evidence.txt",
        "examples/m6-scheduler/task-graph.json",
    )
    for relative in required:
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    baseline_path = root / "requirements" / "baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    source = root / "examples/m5-context/sources/specification.md"
    baseline = {
        "schema_version": "1.0",
        "baseline_id": f"RB-{SOURCE_DIGEST[:16]}",
        "source": {
            "filename": "specification.md",
            "path": "examples/m5-context/sources/specification.md",
            "sha256": SOURCE_DIGEST,
            "size_bytes": source.stat().st_size,
            "modified_at": "2026-08-01T00:00:00+00:00",
            "imported_at": "2026-08-01T00:00:00+00:00",
        },
        "requirements": [
            {
                "id": "FR-M8-DEMO",
                "title": "Validate one offline workflow",
                "type": "functional",
                "priority": "must",
                "status": "baselined",
                "source": {
                    "document": "specification.md",
                    "section": "Accepted Contract",
                    "line_start": 1,
                    "line_end": 1,
                    "excerpt": "The demo uses a deterministic accepted contract.",
                    "derivation_basis": "Preserved from the public synthetic fixture.",
                },
                "statement": "The workflow shall validate one offline deterministic plan.",
                "acceptance_criteria": [
                    {
                        "id": "AC-FR-M8-DEMO-01",
                        "statement": "The plan validates without a network or hosted adapter.",
                        "verification_methods": ["test"],
                    }
                ],
                "verification_methods": ["test"],
                "assumptions": [],
                "open_questions": [],
                "trace_links": {
                    "design": ["docs/integrated-vibe-coding-framework.md"],
                    "code": ["src/sdaqf/application/workflow_planning.py"],
                    "tests": ["tests/test_m8_workflow_planner.py"],
                    "evidence": [],
                    "releases": [],
                },
                "identifier_source": "explicit",
            }
        ],
        "source_acceptance_criteria": [],
        "diagnostics": [],
        "approval_state": {"required": [], "granted": []},
    }
    baseline_path.write_text(
        json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "workflow").mkdir()
    (root / "workflow" / "candidate.json").write_text(
        json.dumps(CANDIDATE.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return root


def create_intent(root: Path) -> tuple[LoadedWorkflowArtifact, Path]:
    """Create one complete untrusted Intent bound to public M5/M6 artifacts."""

    graph = _binding(root, "context-graph", "examples/m5-context/context-graph.json")
    query = _binding(root, "context-query", "examples/m5-context/context-query.json")
    selection = _binding(root, "context-selection", "examples/m5-context/context-selection.json")
    snapshot = _binding(root, "context-snapshot", "examples/m5-context/context-snapshot.json")
    task_graph = _binding(root, "task-graph", "examples/m6-scheduler/task-graph.json")
    snapshot_json = json.loads((root / snapshot.reference.path).read_text(encoding="utf-8"))
    node_id = str(snapshot_json["content"]["nodes"][0]["node_id"])
    specification = _reference(root, "examples/m5-context/sources/specification.md")
    baseline = _reference(root, "requirements/baseline.json")
    budget_json = json.loads((root / task_graph.reference.path).read_text(encoding="utf-8"))[
        "content"
    ]["budget"]
    cost = budget_json["cost"]
    budget = SchedulerBudget(
        max_agents=budget_json["max_agents"],
        max_concurrency=budget_json["max_concurrency"],
        max_reasoning_effort=budget_json["max_reasoning_effort"],
        max_dispatches=budget_json["max_dispatches"],
        max_retries=budget_json["max_retries"],
        max_wall_time_seconds=budget_json["max_wall_time_seconds"],
        max_tool_calls=budget_json["max_tool_calls"],
        max_context_bytes_per_dispatch=budget_json["max_context_bytes_per_dispatch"],
        max_context_bytes_total=budget_json["max_context_bytes_total"],
        max_solver_calls=budget_json["max_solver_calls"],
        max_solver_steps=budget_json["max_solver_steps"],
        cost_status=cost["status"],
        currency=cost["currency"],
        max_microunits=cost["max_microunits"],
    )
    intent = DevelopmentIntent(
        project_id="offline-config",
        candidate=CANDIDATE,
        objective="Validate one deterministic offline workflow.",
        completion_profile=CompletionProfile.PLAN_ONLY,
        specification=specification,
        requirement_baseline_id=f"RB-{SOURCE_DIGEST[:16]}",
        requirement_baseline=baseline,
        allowed_paths=("src/sdaqf",),
        prohibited_paths=("state",),
        required_requirement_ids=("FR-M8-DEMO",),
        required_acceptance_ids=("AC-FR-M8-DEMO-01",),
        requested_effects=(EffectKind.READ_ONLY,),
        risk=IntentRisk.LOW,
        clearance=Sensitivity.PUBLIC,
        sensitivity=Sensitivity.PUBLIC,
        budget=budget,
        capabilities=(),
        context_graph=graph,
        context_query=query,
        context_selection=selection,
        context_snapshot=snapshot,
        task_graph=task_graph,
        solver_registry=None,
        solver_requests=(),
        task_links=(
            IntentTaskLink(
                task_id="TSK-M6-DEMO",
                requirement_ids=("FR-M8-DEMO",),
                acceptance_ids=("AC-FR-M8-DEMO-01",),
                context_node_ids=(node_id,),
                solver_request_ids=(),
            ),
        ),
        required_gate_ids=("G1",),
        observation_slots=("evidence", "handoff", "review", "ui"),
        ui_required=False,
        predecessor_plan_id=None,
        predecessor_outcome_id=None,
    )
    artifact = artifact_from_value(WorkflowArtifactType.DEVELOPMENT_INTENT, intent)
    path = root / "workflow" / "intent.json"
    path.write_bytes(serialize_workflow_artifact(artifact))
    return artifact, path


def create_plan(root: Path) -> tuple[LoadedWorkflowArtifact, Path]:
    """Create a deterministic Plan and persist it for exact explainer replay."""

    intent, path = create_intent(root)
    scheduler = create_scheduler(root)
    plan_path = root / "workflow" / "plan.json"
    plan = create_planner().publish_plan(
        intent,
        artifact_reference_for(root, path),
        root,
        scheduler,
        plan_path,
        recorded_at=FIXED_TIME,
    )
    return plan, plan_path


def create_scheduler(root: Path, clock: FixedClock | None = None) -> Path:
    """Initialize the real M6 SQLite authority for the public Task Graph."""

    selected_clock = FixedClock() if clock is None else clock
    path = root / "workflow" / "scheduler.sqlite3"
    if path.exists():
        store = SQLiteSchedulerStore(path, root)
        store.validate()
        store.require_workflow_authority()
        return path
    SchedulerService(selected_clock).initialize(
        root / "examples/m6-scheduler/task-graph.json",
        root,
        path,
        workflow_authority=True,
    )
    return path


def load(path: Path, expected: WorkflowArtifactType) -> LoadedWorkflowArtifact:
    return load_workflow_artifact(path, expected_type=expected)


def workflow_binding(
    root: Path,
    path: Path,
    artifact: LoadedWorkflowArtifact,
) -> NativeArtifactBinding:
    """Bind one exact persisted M8 artifact for Event-chain authority."""

    return NativeArtifactBinding(
        artifact.artifact_type.value,
        artifact.artifact_id,
        artifact_reference_for(root, path),
        True,
    )


@dataclass(slots=True)
class SuccessorWorkflowFixture:
    """One real predecessor terminal epoch and its distinct successor epoch."""

    root: Path
    predecessor_plan: LoadedWorkflowArtifact
    predecessor_scheduler_state: Path
    stale_predecessor_scheduler_state: Path
    successor_intent: LoadedWorkflowArtifact
    successor_intent_path: Path
    successor_plan: LoadedWorkflowArtifact
    successor_plan_path: Path
    successor_scheduler_state: Path


def create_successor_workflow(tmp_path: Path) -> SuccessorWorkflowFixture:
    """Create a fully attested successor Plan for lifecycle compatibility tests."""

    root = create_workspace(tmp_path)
    predecessor_plan, predecessor_plan_path = create_plan(root)
    predecessor = predecessor_plan.value
    assert isinstance(predecessor, IntegratedPlan)
    predecessor_db = create_scheduler(root)
    source_path = root / "workflow/predecessor-source-state.json"
    source = create_runtime(FixedClock()).run(
        predecessor_plan,
        root,
        predecessor_db,
        source_path,
        root / "workflow/predecessor-source-event.json",
    )
    stale_predecessor_db = root / "workflow/stale-predecessor-scheduler.sqlite3"
    shutil.copy2(predecessor_db, stale_predecessor_db)
    old_intent_artifact = load_workflow_artifact(
        root / predecessor.intent.reference.path,
        expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
    )
    old_intent = old_intent_artifact.value
    assert isinstance(old_intent, DevelopmentIntent)
    successor_candidate = replace(predecessor.candidate, repository_digest="D" * 64)
    successor_proposal = artifact_from_value(
        WorkflowArtifactType.DEVELOPMENT_INTENT,
        replace(old_intent, candidate=successor_candidate),
    )
    proposal_path = root / "workflow/successor-proposal.json"
    proposal_path.write_bytes(serialize_workflow_artifact(successor_proposal))
    (root / "workflow/candidate.json").write_text(
        json.dumps(successor_candidate.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    superseded_state_path = root / "workflow/predecessor-superseded-state.json"
    superseded_outcome_path = root / "workflow/predecessor-superseded-outcome.json"
    superseded = create_runtime(FixedClock()).supersede(
        source.state,
        workflow_binding(root, source_path, source.state),
        predecessor_plan,
        successor_proposal,
        workflow_binding(root, proposal_path, successor_proposal),
        root,
        predecessor_db,
        superseded_state_path,
        root / "workflow/predecessor-superseded-event.json",
        superseded_outcome_path,
    )
    assert superseded.outcome is not None

    context_graph_loaded = load_context_artifact(
        root / old_intent.context_graph.reference.path,
        expected_type=ContextArtifactType.GRAPH,
    )
    context_query_loaded = load_context_artifact(
        root / old_intent.context_query.reference.path,
        expected_type=ContextArtifactType.QUERY,
    )
    context_selection_loaded = load_context_artifact(
        root / old_intent.context_selection.reference.path,
        expected_type=ContextArtifactType.SELECTION,
    )
    context_snapshot_loaded = load_context_artifact(
        root / old_intent.context_snapshot.reference.path,
        expected_type=ContextArtifactType.SNAPSHOT,
    )
    context_graph = context_graph_loaded.value
    context_query = context_query_loaded.value
    context_selection = context_selection_loaded.value
    context_snapshot = context_snapshot_loaded.value
    assert isinstance(context_graph, ContextGraph)
    assert isinstance(context_query, ContextQuery)
    assert isinstance(context_selection, ContextSelection)
    assert isinstance(context_snapshot, ContextSnapshot)
    successor_context_graph = context_artifact_from_value(
        ContextArtifactType.GRAPH,
        replace(context_graph, candidate=successor_candidate),
    )
    successor_context_query = context_artifact_from_value(
        ContextArtifactType.QUERY,
        replace(
            context_query,
            candidate=successor_candidate,
            graph_id=successor_context_graph.artifact_id,
        ),
    )
    successor_query = successor_context_query.value
    assert isinstance(successor_query, ContextQuery)
    successor_context_selection = context_artifact_from_value(
        ContextArtifactType.SELECTION,
        replace(
            context_selection,
            candidate=successor_candidate,
            graph_id=successor_context_graph.artifact_id,
            query_id=successor_context_query.artifact_id,
            query=successor_query,
        ),
    )
    successor_context_snapshot = context_artifact_from_value(
        ContextArtifactType.SNAPSHOT,
        replace(
            context_snapshot,
            candidate=successor_candidate,
            graph_id=successor_context_graph.artifact_id,
            query_id=successor_context_query.artifact_id,
            selection_id=successor_context_selection.artifact_id,
        ),
    )
    context_artifacts = (
        ("successor-context-graph.json", successor_context_graph),
        ("successor-context-query.json", successor_context_query),
        ("successor-context-selection.json", successor_context_selection),
        ("successor-context-snapshot.json", successor_context_snapshot),
    )
    context_paths: dict[ContextArtifactType, Path] = {}
    for name, artifact in context_artifacts:
        path = root / "workflow" / name
        path.write_bytes(serialize_context_artifact(artifact))
        context_paths[artifact.artifact_type] = path

    graph_loaded = load_scheduler_artifact(
        root / predecessor.task_graph.reference.path,
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    graph = graph_loaded.value
    assert isinstance(graph, TaskGraph)
    successor_graph = replace(
        graph,
        candidate=successor_candidate,
        contexts=tuple(
            replace(
                item,
                candidate=successor_candidate,
                artifact_id=successor_context_snapshot.artifact_id,
                reference=artifact_reference_for(
                    root,
                    context_paths[ContextArtifactType.SNAPSHOT],
                ),
            )
            for item in graph.contexts
        ),
        tasks=tuple(
            replace(
                item,
                context_snapshot_id=successor_context_snapshot.artifact_id,
            )
            for item in graph.tasks
        ),
    )
    successor_graph_artifact = scheduler_artifact_from_value(
        SchedulerArtifactType.TASK_GRAPH,
        successor_graph,
    )
    successor_graph_path = root / "workflow/successor-task-graph.json"
    successor_graph_path.write_bytes(serialize_scheduler_artifact(successor_graph_artifact))
    successor_db = root / "workflow/successor-scheduler.sqlite3"
    SchedulerService(FixedClock()).initialize(
        successor_graph_path,
        root,
        successor_db,
        workflow_authority=True,
    )
    successor_intent = artifact_from_value(
        WorkflowArtifactType.DEVELOPMENT_INTENT,
        replace(
            old_intent,
            candidate=successor_candidate,
            context_graph=NativeArtifactBinding(
                ContextArtifactType.GRAPH.value,
                successor_context_graph.artifact_id,
                artifact_reference_for(root, context_paths[ContextArtifactType.GRAPH]),
                True,
            ),
            context_query=NativeArtifactBinding(
                ContextArtifactType.QUERY.value,
                successor_context_query.artifact_id,
                artifact_reference_for(root, context_paths[ContextArtifactType.QUERY]),
                True,
            ),
            context_selection=NativeArtifactBinding(
                ContextArtifactType.SELECTION.value,
                successor_context_selection.artifact_id,
                artifact_reference_for(root, context_paths[ContextArtifactType.SELECTION]),
                True,
            ),
            context_snapshot=NativeArtifactBinding(
                ContextArtifactType.SNAPSHOT.value,
                successor_context_snapshot.artifact_id,
                artifact_reference_for(root, context_paths[ContextArtifactType.SNAPSHOT]),
                True,
            ),
            task_graph=NativeArtifactBinding(
                SchedulerArtifactType.TASK_GRAPH.value,
                successor_graph_artifact.artifact_id,
                artifact_reference_for(root, successor_graph_path),
                True,
            ),
            predecessor_plan_id=predecessor_plan.artifact_id,
            predecessor_state_id=superseded.state.artifact_id,
            predecessor_outcome_id=superseded.outcome.artifact_id,
            predecessor_plan=workflow_binding(root, predecessor_plan_path, predecessor_plan),
            predecessor_state=workflow_binding(root, superseded_state_path, superseded.state),
            predecessor_outcome=workflow_binding(
                root,
                superseded_outcome_path,
                superseded.outcome,
            ),
        ),
    )
    successor_intent_path = root / "workflow/successor-intent.json"
    successor_intent_path.write_bytes(serialize_workflow_artifact(successor_intent))
    successor_plan_path = root / "workflow/successor-plan.json"
    successor_plan = create_planner().publish_plan(
        successor_intent,
        artifact_reference_for(root, successor_intent_path),
        root,
        successor_db,
        successor_plan_path,
        predecessor_scheduler_state=predecessor_db,
        recorded_at=FixedClock().now(),
    )
    return SuccessorWorkflowFixture(
        root=root,
        predecessor_plan=predecessor_plan,
        predecessor_scheduler_state=predecessor_db,
        stale_predecessor_scheduler_state=stale_predecessor_db,
        successor_intent=successor_intent,
        successor_intent_path=successor_intent_path,
        successor_plan=successor_plan,
        successor_plan_path=successor_plan_path,
        successor_scheduler_state=successor_db,
    )


def _binding(root: Path, artifact_type: str, relative: str) -> NativeArtifactBinding:
    path = root / relative
    payload = json.loads(path.read_text(encoding="utf-8"))
    return NativeArtifactBinding(
        artifact_type=artifact_type,
        artifact_id=str(payload["artifact_id"]),
        reference=_reference(root, relative),
        required=True,
    )


def _reference(root: Path, relative: str) -> ArtifactReference:
    path = root / relative
    return ArtifactReference(
        relative,
        hashlib.sha256(path.read_bytes()).hexdigest().upper(),
    )
