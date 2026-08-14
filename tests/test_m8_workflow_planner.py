"""Deterministic M8 planner and native-composition tests."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

import sdaqf.application.workflow_planning as planning_module
import tests.m7_solver_helpers as solver_helpers
from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.baselines import load_baseline
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
    WorkflowContractError,
    artifact_from_value,
    load_workflow_artifact,
    serialize_workflow_artifact,
)
from sdaqf.application.workflow_planning import (
    IntegratedPlanner,
    WorkflowPlanningError,
    artifact_reference_for,
)
from sdaqf.application.workflow_simulation import WorkflowSimulationService
from sdaqf.domain.context import (
    ContextArtifactType,
    ContextGraph,
    ContextQuery,
    ContextSelection,
    ContextSnapshot,
    ExclusionDecision,
    Sensitivity,
)
from sdaqf.domain.models import GateCheck, GateResult
from sdaqf.domain.requirements import RequirementBaseline
from sdaqf.domain.scheduler import (
    EffectKind,
    SchedulerArtifactType,
    SchedulerBudget,
    TaskGraph,
    TaskKind,
)
from sdaqf.domain.workflow import (
    CompletionProfile,
    DevelopmentIntent,
    IntegratedPlan,
    NativeArtifactBinding,
    WorkflowArtifactType,
)
from tests.m7_solver_helpers import build_fixture
from tests.m8_workflow_helpers import (
    REQUIREMENT_ID,
    FixedClock,
    create_explainer,
    create_intent,
    create_plan,
    create_planner,
    create_runtime,
    create_scheduler,
    create_workspace,
    workflow_binding,
)


def test_plan_publication_exact_retry_reuses_confirmed_receipt(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    intent, intent_path = create_intent(root)
    scheduler = create_scheduler(root)
    output = root / "workflow/retry-plan.json"
    planner = create_planner()
    first = planner.publish_plan(
        intent,
        artifact_reference_for(root, intent_path),
        root,
        scheduler,
        output,
        recorded_at=FixedClock().now(),
    )
    second = planner.publish_plan(
        intent,
        artifact_reference_for(root, intent_path),
        root,
        scheduler,
        output,
        recorded_at=FixedClock().now(),
    )
    assert second == first
    head = SQLiteSchedulerStore(scheduler, root).workflow_head(first.artifact_id)
    assert head is not None
    assert len(head.receipts) == 1


def test_plan_revalidates_same_observation_after_preflight_before_epoch_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    intent, intent_path = create_intent(root)
    scheduler = create_scheduler(root)
    planner = create_planner()
    verifier = planner._candidate_verifier
    original_preflight = verifier.preflight_outputs  # type: ignore[attr-defined]

    def drift_after_preflight(*args: object, **kwargs: object) -> None:
        original_preflight(*args, **kwargs)
        (root / "workflow/candidate.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(verifier, "preflight_outputs", drift_after_preflight)
    output = root / "workflow/raced-plan.json"
    with pytest.raises(WorkflowPlanningError, match="Candidate"):
        planner.publish_plan(
            intent,
            artifact_reference_for(root, intent_path),
            root,
            scheduler,
            output,
            recorded_at=FixedClock().now(),
        )
    assert not output.exists()
    assert SQLiteSchedulerStore(scheduler, root).workflow_receipt_snapshot().heads == ()


def test_planner_is_deterministic_and_references_native_authorities(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    scheduler = create_scheduler(root)
    first, path = create_intent(root)
    reference = artifact_reference_for(root, path)
    one = create_planner().plan(first, reference, root, scheduler)
    two = create_planner().plan(first, reference, root, scheduler)
    assert one == two
    assert one.artifact_type is WorkflowArtifactType.INTEGRATED_PLAN
    plan = one.value
    assert isinstance(plan, IntegratedPlan)
    assert plan.intent.artifact_id == first.artifact_id
    assert plan.task_graph.artifact_type == "task-graph"
    assert plan.tasks[0].requirement_ids == (REQUIREMENT_ID,)
    assert not plan.protected_effects


def test_planner_rejects_reference_drift_without_publishing(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    scheduler = create_scheduler(root)
    intent, path = create_intent(root)
    target = root / "examples/m5-context/sources/specification.md"
    target.write_text("changed\n", encoding="utf-8")
    with pytest.raises(WorkflowContractError, match="digest"):
        create_planner().plan(intent, artifact_reference_for(root, path), root, scheduler)
    assert not (root / "workflow/plan.json").exists()


def test_planner_rejects_unbound_predecessor_ids(tmp_path: Path) -> None:
    """A predecessor ID pair alone is not candidate-epoch authority."""

    root = create_workspace(tmp_path)
    intent_artifact, _ = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    forged = replace(
        intent,
        predecessor_plan_id="M8-INTEGRATED-PLAN-" + "A" * 64,
        predecessor_outcome_id="M8-WORKFLOW-OUTCOME-" + "B" * 64,
    )
    with pytest.raises(WorkflowContractError, match=r"predecessor.*bindings"):
        artifact_from_value(
            WorkflowArtifactType.DEVELOPMENT_INTENT,
            forged,
        )


def test_successor_plan_requires_two_distinct_databases_and_attests_direct_predecessor(
    tmp_path: Path,
) -> None:
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
    old_intent = load_workflow_artifact(
        root / predecessor.intent.reference.path,
        expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
    ).value
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
    successor_query_value = successor_context_query.value
    assert isinstance(successor_query_value, ContextQuery)
    successor_context_selection = context_artifact_from_value(
        ContextArtifactType.SELECTION,
        replace(
            context_selection,
            candidate=successor_candidate,
            graph_id=successor_context_graph.artifact_id,
            query_id=successor_context_query.artifact_id,
            query=successor_query_value,
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
    successor_graph_path.write_bytes(
        serialize_scheduler_artifact(successor_graph_artifact)
    )
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
                artifact_reference_for(
                    root,
                    context_paths[ContextArtifactType.SELECTION],
                ),
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
            predecessor_plan=workflow_binding(
                root,
                predecessor_plan_path,
                predecessor_plan,
            ),
            predecessor_state=workflow_binding(
                root,
                superseded_state_path,
                superseded.state,
            ),
            predecessor_outcome=workflow_binding(
                root,
                superseded_outcome_path,
                superseded.outcome,
            ),
        ),
    )
    successor_intent_path = root / "workflow/successor-intent.json"
    successor_intent_path.write_bytes(serialize_workflow_artifact(successor_intent))
    successor_plan = create_planner().publish_plan(
        successor_intent,
        artifact_reference_for(root, successor_intent_path),
        root,
        successor_db,
        root / "workflow/successor-plan.json",
        predecessor_scheduler_state=predecessor_db,
        recorded_at=FixedClock().now(),
    )
    successor_head = SQLiteSchedulerStore(successor_db, root).workflow_head(
        successor_plan.artifact_id
    )
    predecessor_head = SQLiteSchedulerStore(predecessor_db, root).workflow_head(
        predecessor_plan.artifact_id
    )
    assert successor_head is not None and predecessor_head is not None
    assert successor_head.predecessor_plan_id == predecessor_plan.artifact_id
    assert (
        successor_head.predecessor_terminal_event_head_id
        == predecessor_head.current_event_head_id
    )
    assert successor_head.predecessor_state_id == superseded.state.artifact_id
    assert successor_head.predecessor_outcome_id == superseded.outcome.artifact_id

    with pytest.raises(WorkflowContractError, match="required exactly"):
        create_explainer().explain(successor_plan, root, successor_db)
    explanation = create_explainer().explain(
        successor_plan,
        root,
        successor_db,
        predecessor_scheduler_state=predecessor_db,
    )
    assert explanation["plan_id"] == successor_plan.artifact_id
    simulated = WorkflowSimulationService(create_planner()).run(
        successor_plan,
        root,
        successor_db,
        "ui-observation-unavailable",
        predecessor_scheduler_state=predecessor_db,
    )
    assert simulated.blockers == ("ui-evidence-unavailable",)
    started = create_runtime(FixedClock()).run(
        successor_plan,
        root,
        successor_db,
        root / "workflow/successor-state.json",
        root / "workflow/successor-event.json",
        predecessor_scheduler_state=predecessor_db,
    )
    assert started.state.value is not None

    with pytest.raises(WorkflowPlanningError, match="required exactly"):
        create_planner().plan(
            successor_intent,
            artifact_reference_for(root, successor_intent_path),
            root,
            successor_db,
        )
    genesis_intent, genesis_path = create_intent(root)
    with pytest.raises(WorkflowPlanningError, match="required exactly"):
        create_planner().plan(
            genesis_intent,
            artifact_reference_for(root, genesis_path),
            root,
            successor_db,
            predecessor_scheduler_state=predecessor_db,
        )
    with pytest.raises(WorkflowPlanningError, match="distinct databases"):
        create_planner().plan(
            successor_intent,
            artifact_reference_for(root, successor_intent_path),
            root,
            predecessor_db,
            predecessor_scheduler_state=predecessor_db,
        )
    alias = root / "workflow/predecessor-scheduler-alias.sqlite3"
    try:
        os.link(predecessor_db, alias)
    except OSError:
        return
    with pytest.raises(WorkflowPlanningError, match="distinct databases"):
        create_planner().plan(
            successor_intent,
            artifact_reference_for(root, successor_intent_path),
            root,
            alias,
            predecessor_scheduler_state=predecessor_db,
        )


def test_planner_rejects_unmapped_requirement_and_unrequested_effect(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    scheduler = create_scheduler(root)
    intent_artifact, path = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    broken_link = replace(intent.task_links[0], requirement_ids=())
    broken = replace(intent, task_links=(broken_link,))
    broken_artifact = artifact_from_value(WorkflowArtifactType.DEVELOPMENT_INTENT, broken)
    path.write_bytes(serialize_workflow_artifact(broken_artifact))
    with pytest.raises(WorkflowContractError, match="not mapped"):
        create_planner().plan(
            broken_artifact,
            artifact_reference_for(root, path),
            root,
            scheduler,
        )


def test_planner_output_contains_no_aggregate_score_or_authority_grant(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    text = json.dumps(plan.to_dict(), sort_keys=True)
    assert "aggregate_score" not in text
    assert '"approval"' not in text
    assert "hosted" not in text


def test_native_validation_rejects_wrong_types_and_candidate_links(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    intent_artifact, intent_path = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    plan_artifact, _ = create_plan(root)
    scheduler = create_scheduler(root)
    with pytest.raises(WorkflowPlanningError, match="Development Intent"):
        create_planner().plan(
            plan_artifact,
            artifact_reference_for(root, intent_path),
            root,
            scheduler,
        )
    changed = replace(intent, objective="A different validated objective.")
    changed_artifact = artifact_from_value(WorkflowArtifactType.DEVELOPMENT_INTENT, changed)
    changed_path = root / "workflow/changed-intent.json"
    changed_path.write_bytes(serialize_workflow_artifact(changed_artifact))
    with pytest.raises(WorkflowPlanningError, match="reference drifted"):
        create_planner().plan(
            intent_artifact,
            artifact_reference_for(root, changed_path),
            root,
            scheduler,
        )
    with pytest.raises(WorkflowPlanningError, match="Specification digest"):
        IntegratedPlanner._validate_baseline(
            replace(intent, specification=replace(intent.specification, sha256="A" * 64)),
            root,
        )
    with pytest.raises(WorkflowPlanningError, match="Context binding type"):
        create_planner()._validate_context(
            replace(
                intent,
                context_graph=replace(intent.context_graph, artifact_type="context-query"),
            ),
            root,
            None,
        )
    with pytest.raises(WorkflowPlanningError, match="Task Graph binding type"):
        IntegratedPlanner._validate_task_graph(
            replace(intent, task_graph=replace(intent.task_graph, artifact_type="scheduler-state")),
            root,
        )
    with pytest.raises(WorkflowPlanningError, match="Solver Registry binding type"):
        IntegratedPlanner._validate_solver(
            replace(
                intent,
                solver_registry=replace(intent.context_graph, artifact_type="solver-request"),
            ),
            root,
        )


def test_link_scope_and_budget_rejections_cover_every_policy_axis(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    intent_artifact, _ = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    baseline = load_baseline(root / "requirements/baseline.json")
    assert isinstance(baseline, RequirementBaseline)
    context_artifact = load_context_artifact(
        root / "examples/m5-context/context-graph.json",
        expected_type=ContextArtifactType.GRAPH,
    )
    context = context_artifact.value
    assert isinstance(context, ContextGraph)
    task_artifact = load_scheduler_artifact(
        root / "examples/m6-scheduler/task-graph.json",
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    graph = task_artifact.value
    assert isinstance(graph, TaskGraph)
    link = intent.task_links[0]
    link_cases = (
        replace(intent, required_requirement_ids=("FR-UNKNOWN",)),
        replace(intent, required_acceptance_ids=("AC-UNKNOWN",)),
        replace(intent, task_links=(replace(link, requirement_ids=("FR-UNKNOWN",)),)),
        replace(intent, task_links=(replace(link, acceptance_ids=("AC-UNKNOWN",)),)),
        replace(intent, task_links=(replace(link, context_node_ids=("CTX-NODE-UNKNOWN",)),)),
        replace(intent, task_links=(replace(link, solver_request_ids=("SOLVER-UNKNOWN",)),)),
        replace(intent, task_links=(replace(link, requirement_ids=()),)),
        replace(intent, task_links=(replace(link, acceptance_ids=()),)),
    )
    for candidate in link_cases:
        with pytest.raises(WorkflowPlanningError):
            IntegratedPlanner._validate_links(candidate, baseline, context, graph, ())
    solver_graph = replace(
        graph,
        tasks=(replace(graph.tasks[0], kind=TaskKind.SOLVER),),
    )
    with pytest.raises(WorkflowPlanningError, match="Solver task"):
        IntegratedPlanner._validate_links(intent, baseline, context, solver_graph, ())

    ceiling = intent.budget
    hard_excess = replace(ceiling, max_dispatches=ceiling.max_dispatches + 1)
    effort_excess = replace(ceiling, max_reasoning_effort="high")
    low_ceiling = replace(ceiling, max_reasoning_effort="low")
    available = replace(
        ceiling,
        cost_status="available",
        currency="USD",
        max_microunits=10,
    )
    budget_cases: tuple[tuple[SchedulerBudget, SchedulerBudget], ...] = (
        (ceiling, hard_excess),
        (low_ceiling, effort_excess),
        (available, ceiling),
        (available, replace(available, max_microunits=11)),
    )
    for budget_ceiling, selected in budget_cases:
        with pytest.raises(WorkflowPlanningError):
            IntegratedPlanner._validate_budget(budget_ceiling, selected)
    IntegratedPlanner._validate_budget(available, replace(available, max_microunits=5))

    base_task = graph.tasks[0]
    scope_cases = (
        replace(graph, tasks=(replace(base_task, effect_kind=EffectKind.EXTERNAL),)),
        replace(graph, tasks=(replace(base_task, required_capabilities=("host-cap",)),)),
        replace(graph, tasks=(replace(base_task, owned_paths=("state/private",)),)),
        replace(graph, tasks=(replace(base_task, owned_paths=("tests/outside",)),)),
    )
    intents = (
        intent,
        intent,
        replace(intent, prohibited_paths=("state",)),
        intent,
    )
    for candidate_intent, candidate_graph in zip(intents, scope_cases, strict=True):
        with pytest.raises(WorkflowPlanningError):
            IntegratedPlanner._validate_scope_and_capabilities(candidate_intent, candidate_graph)

    with pytest.raises(WorkflowPlanningError, match="prohibited path"):
        IntegratedPlanner._validate_scope_and_capabilities(
            replace(intent, prohibited_paths=("SRC/SDAQF",)),
            replace(graph, tasks=(replace(base_task, owned_paths=("src/sdaqf",)),)),
        )


def test_task_order_protected_effects_and_decision_vocabulary(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    intent_artifact, _ = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    baseline = load_baseline(root / "requirements/baseline.json")
    graph_artifact = load_context_artifact(
        root / "examples/m5-context/context-graph.json",
        expected_type=ContextArtifactType.GRAPH,
    )
    selection_artifact = load_context_artifact(
        root / "examples/m5-context/context-selection.json",
        expected_type=ContextArtifactType.SELECTION,
    )
    task_artifact = load_scheduler_artifact(
        root / "examples/m6-scheduler/task-graph.json",
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=root,
    )
    context = graph_artifact.value
    selection = selection_artifact.value
    graph = task_artifact.value
    assert isinstance(context, ContextGraph)
    assert isinstance(selection, ContextSelection)
    assert isinstance(graph, TaskGraph)
    first = graph.tasks[0]
    second = replace(
        first,
        task_id="TSK-M6-REVIEW",
        kind=TaskKind.REVIEW,
        dependencies=(first.task_id,),
        review_targets=(first.task_id,),
        effect_kind=EffectKind.EXTERNAL,
        approval_stops=("owner",),
        wave=first.wave + 1,
    )
    graph = replace(graph, tasks=(first, second))
    links = {
        intent.task_links[0].task_id: intent.task_links[0],
        second.task_id: replace(intent.task_links[0], task_id=second.task_id),
    }
    planned = IntegratedPlanner._plan_tasks(graph, links)
    assert [item.task_id for item in planned] == [first.task_id, second.task_id]
    assert planned[1].topological_rank == 1
    effects = IntegratedPlanner._protected_effects(graph, root, task_artifact.artifact_id)
    assert len(effects) == 1 and effects[0].task_id == second.task_id

    expanded_intent = replace(
        intent,
        completion_profile=CompletionProfile.IMPLEMENTATION_VERIFIED,
        required_gate_ids=("G1", "G2"),
        task_links=tuple(links[key] for key in sorted(links)),
    )
    expanded_selection = replace(
        selection,
        unresolved_contradiction_ids=("CTX-CONTRADICTION-M8",),
        excluded=(ExclusionDecision(context.nodes[0].node_id, "not-selected", ()),),
    )
    failed_gate = GateResult(
        "G1",
        (GateCheck("requirements", False, True, "synthetic failure"),),
    )
    decisions = IntegratedPlanner._decisions(
        expanded_intent,
        baseline,
        context,
        expanded_selection,
        graph,
        (),
        effects,
        failed_gate,
    )
    reasons = {item.reason_code for item in decisions}
    assert {
        "blocking-diagnostic",
        "review-separation",
        "handoff-required",
        "approval-not-authority",
        "unresolved-contradiction",
        "optional-context-not-selected",
    } <= reasons
    bad_selection = replace(
        selection,
        excluded=(ExclusionDecision("CTX-NODE-UNKNOWN", "not-selected", ()),),
    )
    with pytest.raises(WorkflowPlanningError, match="unknown node"):
        IntegratedPlanner._decisions(
            intent,
            baseline,
            context,
            bad_selection,
            graph,
            (),
            (),
            GateResult("G1", (GateCheck("requirements", True, True, "ok"),)),
        )


def test_artifact_reference_rejects_outside_and_non_file(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    with pytest.raises(WorkflowPlanningError, match="outside"):
        artifact_reference_for(root, outside)


def test_solver_composition_uses_exact_m7_validator_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = create_workspace(tmp_path)
    scheduler = create_scheduler(root)
    intent_artifact, _ = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    repository_root = Path(__file__).resolve().parents[1]
    for name in ("LICENSE", "pyproject.toml"):
        shutil.copy2(repository_root / name, tmp_path / name)
    monkeypatch.setattr(solver_helpers, "ROOT", tmp_path)
    fixture = build_fixture(tmp_path / "m7-native")
    registry_binding = NativeArtifactBinding(
        "solver-registry",
        fixture.registry.artifact_id,
        intent.context_graph.reference,
        True,
    )
    request_binding = NativeArtifactBinding(
        "solver-request",
        fixture.request.artifact_id,
        intent.context_query.reference,
        True,
    )
    solver_intent = replace(
        intent,
        solver_registry=registry_binding,
        solver_requests=(request_binding,),
    )

    class FakeSolverService:
        def validate_request(self, *_args: object) -> tuple[object, object, object]:
            return fixture.request, fixture.registry, fixture.graph

    monkeypatch.setattr(
        planning_module,
        "load_solver_artifact",
        lambda *_args, **_kwargs: fixture.registry,
    )
    monkeypatch.setattr(planning_module, "SolverService", FakeSolverService)
    validated_registry, validated_requests = IntegratedPlanner._validate_solver(solver_intent, root)
    assert validated_registry == fixture.registry
    assert validated_requests == (fixture.request,)
    solver_graph = fixture.graph.value
    assert isinstance(solver_graph, TaskGraph)
    IntegratedPlanner._validate_scope_and_capabilities(
        solver_intent,
        solver_graph,
        validated_requests,
    )
    with pytest.raises(WorkflowPlanningError, match="unrequested capability"):
        IntegratedPlanner._validate_scope_and_capabilities(
            solver_intent,
            solver_graph,
            (),
        )

    restricted_registry = replace(
        fixture.registry,
        value=replace(
            fixture.registry.value,
            sensitivity=Sensitivity.OWNER_PRIVATE,
        ),
    )
    restricted_request = replace(
        fixture.request,
        value=replace(
            fixture.request.value,
            sensitivity=Sensitivity.OWNER_PRIVATE,
        ),
    )

    class RestrictedSolverService:
        def validate_request(self, *_args: object) -> tuple[object, object, object]:
            return restricted_request, restricted_registry, fixture.graph

    monkeypatch.setattr(
        planning_module,
        "load_solver_artifact",
        lambda *_args, **_kwargs: restricted_registry,
    )
    monkeypatch.setattr(planning_module, "SolverService", RestrictedSolverService)
    owner_private_intent = replace(
        solver_intent,
        clearance=Sensitivity.OWNER_PRIVATE,
    )
    owner_private_artifact = artifact_from_value(
        WorkflowArtifactType.DEVELOPMENT_INTENT,
        owner_private_intent,
    )
    owner_private_path = root / "workflow/owner-private-intent.json"
    owner_private_path.write_bytes(serialize_workflow_artifact(owner_private_artifact))
    propagated = create_planner().plan(
        owner_private_artifact,
        artifact_reference_for(root, owner_private_path),
        root,
        scheduler,
    )
    assert isinstance(propagated.value, IntegratedPlan)
    assert propagated.value.sensitivity is Sensitivity.OWNER_PRIVATE

    public_artifact = artifact_from_value(
        WorkflowArtifactType.DEVELOPMENT_INTENT,
        solver_intent,
    )
    public_path = root / "workflow/public-intent.json"
    public_path.write_bytes(serialize_workflow_artifact(public_artifact))
    with pytest.raises(WorkflowPlanningError, match="exceeds Intent clearance"):
        create_planner().plan(
            public_artifact,
            artifact_reference_for(root, public_path),
            root,
            scheduler,
        )

    wrong_request_type = replace(
        solver_intent,
        solver_requests=(replace(request_binding, artifact_type="solver-result"),),
    )
    with pytest.raises(WorkflowPlanningError, match="Request binding type"):
        IntegratedPlanner._validate_solver(wrong_request_type, root)

    stale_registry = replace(
        solver_intent,
        solver_registry=replace(registry_binding, artifact_id="M7-SOLVER-REGISTRY-STALE"),
    )
    with pytest.raises(WorkflowPlanningError, match="Registry identity drifted"):
        IntegratedPlanner._validate_solver(stale_registry, root)

    stale_request = replace(
        solver_intent,
        solver_requests=(replace(request_binding, artifact_id="M7-SOLVER-REQUEST-STALE"),),
    )
    with pytest.raises(WorkflowPlanningError, match="Request identity drifted"):
        IntegratedPlanner._validate_solver(stale_request, root)

    class FailingSolverService:
        def validate_request(self, *_args: object) -> tuple[object, object, object]:
            raise ValueError("synthetic validator rejection")

    monkeypatch.setattr(planning_module, "SolverService", FailingSolverService)
    with pytest.raises(WorkflowPlanningError, match="Request is invalid"):
        IntegratedPlanner._validate_solver(solver_intent, root)
