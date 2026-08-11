"""Exact recomputing explanations for deterministic M8 Integrated Plans."""

from __future__ import annotations

from pathlib import Path

from sdaqf.application.workflow_contracts import (
    LoadedWorkflowArtifact,
    WorkflowContractError,
    load_workflow_artifact,
    verify_workflow_reference,
)
from sdaqf.application.workflow_planning import IntegratedPlanner
from sdaqf.domain.workflow import (
    DevelopmentIntent,
    IntegratedPlan,
    WorkflowArtifactType,
    WorkflowDecisionKind,
    WorkflowPublicationObservation,
)


class WorkflowExplanationError(WorkflowContractError):
    """A Plan cannot be reproduced exactly from its native references."""


class WorkflowExplainer:
    """Recompute every Plan decision instead of trusting saved prose."""

    def __init__(self, planner: IntegratedPlanner) -> None:
        self._planner = planner

    def explain(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        *,
        predecessor_scheduler_state: Path | None = None,
    ) -> dict[str, object]:
        """Return exact JSON-ready selection, exclusion, and blocker reasons."""

        explanation, _observation = self.explain_with_observation(
            plan_artifact,
            root,
            scheduler_state,
            predecessor_scheduler_state=predecessor_scheduler_state,
        )
        return explanation

    def explain_with_observation(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        *,
        predecessor_scheduler_state: Path | None = None,
    ) -> tuple[dict[str, object], WorkflowPublicationObservation]:
        """Return the explanation and the single observation consumed to derive it."""

        if plan_artifact.artifact_type is not WorkflowArtifactType.INTEGRATED_PLAN:
            raise WorkflowExplanationError("Workflow explanation requires Integrated Plan.")
        plan = plan_artifact.value
        assert isinstance(plan, IntegratedPlan)
        if (plan.predecessor_plan_id is not None) != (
            predecessor_scheduler_state is not None
        ):
            raise WorkflowExplanationError(
                "Predecessor scheduler state is required exactly for a successor Plan."
            )
        intent_path = verify_workflow_reference(root, plan.intent)
        intent_artifact = load_workflow_artifact(
            intent_path,
            expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
        )
        if intent_artifact.artifact_id != plan.intent.artifact_id:
            raise WorkflowExplanationError("Plan Intent identity drifted.")
        intent = intent_artifact.value
        assert isinstance(intent, DevelopmentIntent)
        publication_scheduler_state = (
            scheduler_state
            if predecessor_scheduler_state is None
            else predecessor_scheduler_state
        )
        observation = self._planner._verify_candidate(
            root,
            intent,
            publication_scheduler_state,
            require_scheduler_candidate=predecessor_scheduler_state is None,
        )
        reproduced = self._planner.plan(
            intent_artifact,
            plan.intent.reference,
            root,
            scheduler_state,
            publication_observation=observation,
            predecessor_scheduler_state=predecessor_scheduler_state,
        )
        if reproduced.artifact_id != plan_artifact.artifact_id:
            raise WorkflowExplanationError("Integrated Plan does not reproduce exactly.")
        selected = tuple(
            item.to_dict() for item in plan.decisions if item.kind is WorkflowDecisionKind.SELECTED
        )
        excluded = tuple(
            item.to_dict() for item in plan.decisions if item.kind is WorkflowDecisionKind.EXCLUDED
        )
        uncertainties = tuple(
            item.to_dict()
            for item in plan.decisions
            if item.kind is WorkflowDecisionKind.UNCERTAINTY
        )
        approvals = tuple(
            {
                "effect_id": effect.effect_id,
                "task_id": effect.task_id,
                "approval_types": list(effect.approval_types),
                "fresh_native_revalidation_required": True,
                "intent_grants_authority": False,
            }
            for effect in plan.protected_effects
        )
        evidence = tuple(
            {
                "task_id": task.task_id,
                "predicates": list(task.evidence_predicates),
                "future_observation_only": True,
            }
            for task in plan.tasks
        )
        blocking = tuple(item.reason_code for item in plan.decisions if item.blocking)
        return {
            "plan_id": plan_artifact.artifact_id,
            "intent_id": intent_artifact.artifact_id,
            "deterministic": True,
            "side_effect_free": True,
            "selection": list(selected),
            "exclusion": list(excluded),
            "uncertainty": list(uncertainties),
            "budget": plan.budget.to_dict(),
            "approval": list(approvals),
            "evidence": list(evidence),
            "gates": list(plan.required_gate_ids),
            "completion": {
                "profile": plan.completion_profile.value,
                "blocking_reason_codes": list(blocking),
                "handoff_required": plan.completion_profile.value != "plan-only",
                "outcome_may_not_upgrade_native_status": True,
            },
        }, observation
