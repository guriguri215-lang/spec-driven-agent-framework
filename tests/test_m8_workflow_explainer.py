"""M8 exact explainer replay tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sdaqf.application.workflow_contracts import WorkflowContractError, artifact_from_value
from sdaqf.domain.workflow import IntegratedPlan, WorkflowArtifactType
from tests.m8_workflow_helpers import (
    create_explainer,
    create_intent,
    create_plan,
    create_scheduler,
    create_workspace,
)


def test_explainer_recomputes_every_reason_and_budget(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    explanation = create_explainer().explain(plan, root, scheduler)
    assert explanation["deterministic"] is True
    assert explanation["side_effect_free"] is True
    assert explanation["selection"]
    assert explanation["exclusion"]
    assert explanation["uncertainty"]
    value = plan.value
    assert isinstance(value, IntegratedPlan)
    assert explanation["budget"] == value.budget.to_dict()
    assert explanation["approval"] == []


def test_explainer_refuses_changed_intent_even_if_plan_bytes_are_unchanged(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    value = plan.value
    assert isinstance(value, IntegratedPlan)
    intent_path = root / value.intent.reference.path
    payload = json.loads(intent_path.read_text(encoding="utf-8"))
    payload["content"]["objective"] = "A changed untrusted objective."
    intent_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkflowContractError):
        create_explainer().explain(plan, root, scheduler)


def test_explainer_rejects_wrong_artifact_binding_and_nonreproducible_plan(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    intent, _ = create_intent(root)
    plan, _ = create_plan(root)
    scheduler = create_scheduler(root)
    with pytest.raises(WorkflowContractError, match="Integrated Plan"):
        create_explainer().explain(intent, root, scheduler)
    value = plan.value
    assert isinstance(value, IntegratedPlan)
    stale_binding = replace(
        value,
        intent=replace(
            value.intent,
            artifact_id="M8-DEVELOPMENT-INTENT-" + "A" * 64,
        ),
    )
    stale_artifact = artifact_from_value(WorkflowArtifactType.INTEGRATED_PLAN, stale_binding)
    with pytest.raises(WorkflowContractError, match="Intent identity drifted"):
        create_explainer().explain(stale_artifact, root, scheduler)
    changed_budget = replace(
        value,
        budget=replace(value.budget, max_dispatches=value.budget.max_dispatches - 1),
    )
    changed_artifact = artifact_from_value(WorkflowArtifactType.INTEGRATED_PLAN, changed_budget)
    with pytest.raises(WorkflowContractError, match="reproduce exactly"):
        create_explainer().explain(changed_artifact, root, scheduler)
