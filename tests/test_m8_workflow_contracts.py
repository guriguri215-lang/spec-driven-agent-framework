"""Strict M8 artifact identity, parsing, and envelope tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import sdaqf.application.workflow_contracts as contracts
from sdaqf.application.contracts import ContractError
from sdaqf.application.workflow_contracts import (
    WorkflowContractError,
    artifact_from_value,
    parse_workflow_artifact_bytes,
    serialize_workflow_artifact,
)
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.scheduler import EffectKind
from sdaqf.domain.workflow import (
    DevelopmentIntent,
    IntegratedPlan,
    WorkflowArtifactType,
    WorkflowOutcome,
    WorkflowState,
)
from tests.m8_workflow_helpers import ROOT, create_intent, create_plan, create_workspace


def test_development_intent_round_trips_canonically(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    artifact, _ = create_intent(root)
    raw = serialize_workflow_artifact(artifact)
    assert parse_workflow_artifact_bytes(raw) == artifact
    assert raw.endswith(b"\n")
    assert artifact.artifact_id.startswith("M8-DEVELOPMENT-INTENT-")


@pytest.mark.parametrize(
    ("filename", "artifact_type", "value_type"),
    [
        ("workflow-state.json", WorkflowArtifactType.WORKFLOW_STATE, WorkflowState),
        ("workflow-outcome.json", WorkflowArtifactType.WORKFLOW_OUTCOME, WorkflowOutcome),
    ],
)
@pytest.mark.parametrize("mutation", ["missing", "foreign", "duplicate", "reordered"])
def test_terminal_runtime_requires_exact_canonical_52_measurements(
    filename: str,
    artifact_type: WorkflowArtifactType,
    value_type: type[WorkflowState] | type[WorkflowOutcome],
    mutation: str,
) -> None:
    loaded = parse_workflow_artifact_bytes(
        (ROOT / "examples" / "m8-workflow" / filename).read_bytes(),
        expected_type=artifact_type,
    )
    value = loaded.value
    assert isinstance(value, value_type)
    measurements = list(value.measurements)
    if mutation == "missing":
        measurements.pop()
    elif mutation == "foreign":
        measurements[0] = replace(measurements[0], name="foreign.measurement")
    elif mutation == "duplicate":
        measurements[1] = replace(
            measurements[1],
            name=measurements[0].name,
            value=999,
        )
    else:
        measurements[0], measurements[1] = measurements[1], measurements[0]
    with pytest.raises(
        WorkflowContractError,
        match=r"exact 52 measurements|unsupported",
    ):
        artifact_from_value(
            artifact_type,
            replace(value, measurements=tuple(measurements)),
        )


def test_duplicate_json_key_is_rejected(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    artifact, _ = create_intent(root)
    raw = serialize_workflow_artifact(artifact).replace(
        b'"artifact_type": "development-intent",',
        b'"artifact_type": "development-intent", "artifact_type": "development-intent",',
        1,
    )
    with pytest.raises(WorkflowContractError, match="duplicate"):
        parse_workflow_artifact_bytes(raw)


def test_stale_identity_and_unknown_field_are_rejected(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    artifact, _ = create_intent(root)
    payload: dict[str, Any] = json.loads(serialize_workflow_artifact(artifact))
    payload["artifact_id"] = "M8-DEVELOPMENT-INTENT-" + "0" * 64
    with pytest.raises(WorkflowContractError, match="identity"):
        parse_workflow_artifact_bytes(json.dumps(payload).encode())
    payload = artifact.to_dict()
    content = payload["content"]
    assert isinstance(content, dict)
    content["approval"] = True
    with pytest.raises(WorkflowContractError, match="unsupported field"):
        parse_workflow_artifact_bytes(json.dumps(payload).encode())


def test_required_bindings_invalid_paths_and_impossible_dates_are_rejected() -> None:
    intent_path = ROOT / "examples/m8-workflow/development-intent.json"
    intent: dict[str, Any] = json.loads(intent_path.read_text(encoding="utf-8"))
    content = intent["content"]
    assert isinstance(content, dict)

    context_graph = content["context_graph"]
    assert isinstance(context_graph, dict)
    context_graph["required"] = False
    with pytest.raises(WorkflowContractError, match="required binding"):
        parse_workflow_artifact_bytes(json.dumps(intent).encode())

    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    content = intent["content"]
    assert isinstance(content, dict)
    specification = content["specification"]
    assert isinstance(specification, dict)
    specification["path"] = "CON/file.json"
    with pytest.raises(WorkflowContractError, match="portable"):
        parse_workflow_artifact_bytes(json.dumps(intent).encode())

    event: dict[str, Any] = json.loads(
        (ROOT / "examples/m8-workflow/workflow-event.json").read_text(encoding="utf-8")
    )
    event_content = event["content"]
    assert isinstance(event_content, dict)
    event_content["recorded_at"] = "2026-02-30T00:00:00Z"
    with pytest.raises(WorkflowContractError, match="real UTC instant"):
        parse_workflow_artifact_bytes(json.dumps(event).encode())


def test_secret_shaped_objective_and_sensitivity_downgrade_are_rejected(
    tmp_path: Path,
) -> None:
    root = create_workspace(tmp_path)
    artifact, _ = create_intent(root)
    intent = artifact.value
    assert isinstance(intent, DevelopmentIntent)
    secret = replace(intent, objective="ghp_" + "A" * 24)
    with pytest.raises(WorkflowContractError, match="secret-shaped"):
        artifact_from_value(WorkflowArtifactType.DEVELOPMENT_INTENT, secret)
    downgraded = replace(
        intent,
        sensitivity=Sensitivity.SECRET_OR_PROHIBITED,
        clearance=Sensitivity.PUBLIC,
    )
    with pytest.raises(WorkflowContractError, match="clearance"):
        artifact_from_value(WorkflowArtifactType.DEVELOPMENT_INTENT, downgraded)


def test_envelope_json_loader_and_reference_fail_closed(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    artifact, path = create_intent(root)
    payload = artifact.to_dict()
    invalid_payloads: list[bytes] = [
        b"\xff",
        b'{"x": NaN}',
        json.dumps({**payload, "schema_version": "2.0"}).encode(),
        json.dumps({**payload, "artifact_type": "workflow-event"}).encode(),
    ]
    for raw in invalid_payloads:
        with pytest.raises(WorkflowContractError):
            parse_workflow_artifact_bytes(raw)
    with pytest.raises(WorkflowContractError, match="unexpected"):
        parse_workflow_artifact_bytes(
            serialize_workflow_artifact(artifact),
            expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
        )
    with pytest.raises(WorkflowContractError, match="size"):
        parse_workflow_artifact_bytes(b"0" * (contracts.LARGE_ARTIFACT_BYTES + 1))
    wrong_suffix = path.with_suffix(".txt")
    wrong_suffix.write_bytes(path.read_bytes())
    with pytest.raises(WorkflowContractError, match="JSON"):
        contracts.load_workflow_artifact(wrong_suffix)
    with pytest.raises(WorkflowContractError, match="regular"):
        contracts.load_workflow_artifact(root / "missing.json")
    intent = artifact.value
    assert isinstance(intent, DevelopmentIntent)
    binding = intent.context_graph
    drifted = replace(
        binding,
        reference=replace(binding.reference, sha256="0" * 64),
    )
    with pytest.raises(WorkflowContractError, match="digest"):
        contracts.verify_workflow_reference(root, drifted)
    with pytest.raises(WorkflowContractError):
        contracts.workflow_id("bad", "id")
    with pytest.raises(WorkflowContractError, match="type"):
        contracts.workflow_id(
            artifact.artifact_id,
            "id",
            expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
        )


def test_canonical_and_scalar_contract_helpers_cover_every_closed_vocabulary() -> None:
    deep: object = None
    for _ in range(66):
        deep = [deep]
    actions: list[Callable[[], object]] = [
        lambda: contracts._validate_canonical_value({"é": 1}),
        lambda: contracts._validate_canonical_value("\ud800"),
        lambda: contracts._validate_canonical_value(1.5),
        lambda: contracts._validate_canonical_value(deep),
        lambda: contracts._parse_binding(
            {
                "artifact_type": "BAD_TYPE",
                "artifact_id": "NATIVE-ID",
                "reference": {"path": "a.json", "sha256": "A" * 64},
                "required": True,
            },
            "binding",
        ),
        lambda: contracts._native_id("bad space", "id"),
        lambda: contracts._native_or_workflow_id("bad space", "id"),
        lambda: contracts._optional_pattern_id("bad", "task", contracts._TASK_ID),
        lambda: contracts._code("UPPER", "code"),
        lambda: contracts._task_id("TSK_bad", "task"),
        lambda: contracts._baseline_id("RB-bad", "baseline"),
        lambda: contracts._gate_id("G5", "gate"),
        lambda: contracts._gate_ids(["G2", "G1"], "gates"),
        lambda: contracts._sorted_paths(["b", "a"], "paths"),
        lambda: contracts._sorted_pattern_ids(["bad"], "ids"),
        lambda: contracts._sorted_task_ids(["TSK-B", "TSK-A"], "tasks"),
        lambda: contracts._sorted_codes(["b", "a"], "codes"),
        lambda: contracts._sorted_native_ids(["B-ID", "A-ID"], "ids"),
        lambda: contracts._sorted_native_or_workflow_ids(["bad space"], "ids"),
        lambda: contracts._sorted_workflow_ids(
            ["M8-INTEGRATED-PLAN-" + "A" * 64, "M8-INTEGRATED-PLAN-" + "A" * 64],
            "plans",
            WorkflowArtifactType.INTEGRATED_PLAN,
        ),
        lambda: contracts._sorted_enums(
            EffectKind,
            ["read_only", "read_only"],
            "effects",
            maximum=4,
        ),
        lambda: contracts._utc_timestamp("2026-08-01T00:00:00+00:00", "time"),
    ]
    for action in actions:
        with pytest.raises((WorkflowContractError, ContractError)):
            action()
    assert contracts._optional_binding(None, "binding") is None
    assert contracts._optional_native_id(None, "id") is None
    assert contracts._optional_code(None, "code") is None


def test_collection_budget_and_profile_invariants_are_rejected(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    intent_artifact, _ = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    plan_artifact, _ = create_plan(root)
    plan = plan_artifact.value
    assert isinstance(plan, IntegratedPlan)
    binding = intent.context_graph.to_dict()
    link = intent.task_links[0].to_dict()
    task = plan.tasks[0].to_dict()
    decision = plan.decisions[0].to_dict()
    budget = intent.budget.to_dict()
    measurement = {
        "name": "available_cost.test",
        "status": "observed",
        "value": 1,
        "unit": "count",
        "source_ids": ["NATIVE-ID"],
    }
    blocker = {"code": "blocked", "references": ["NATIVE-ID"]}
    gate = {
        "gate_id": "G1",
        "status": "PASS",
        "evidence_ids": [],
        "blocker_codes": [],
    }
    projection = {
        "task_id": "TSK-A",
        "state": "planned",
        "outcome": "none",
        "attempt": 0,
        "fence": 0,
        "blocker_codes": [],
    }
    effect = {
        "effect_id": "M8-EFFECT-A",
        "task_id": "TSK-A",
        "effect_kind": "external",
        "approval_types": ["owner"],
        "idempotency_scope": "native-m6-lease",
    }
    invalid_actions: list[Callable[[], object]] = [
        lambda: contracts._bindings([binding, binding], "bindings"),
        lambda: contracts._task_links([link, link], "links"),
        lambda: contracts._plan_tasks([task, task], "tasks"),
        lambda: contracts._plan_tasks([{**task, "dependencies": ["TSK-UNKNOWN"]}], "tasks"),
        lambda: contracts._plan_tasks([{**task, "task_kind": "BAD"}], "tasks"),
        lambda: contracts._protected_effects([effect, effect], "effects"),
        lambda: contracts._decisions([{**decision, "reason_code": "budget-exceeded"}], "decisions"),
        lambda: contracts._decisions([{**decision, "blocking": True}], "decisions"),
        lambda: contracts._decisions([decision, decision], "decisions"),
        lambda: contracts._workflow_tasks([projection, projection], "tasks"),
        lambda: contracts._gates([gate, gate], "gates"),
        lambda: contracts._blockers([blocker, blocker], "blockers"),
        lambda: contracts._measurements([{**measurement, "name": "unsupported"}], "measurements"),
        lambda: contracts._measurements([{**measurement, "value": True}], "measurements"),
        lambda: contracts._measurements(
            [{**measurement, "status": "not-available"}], "measurements"
        ),
        lambda: contracts._measurements([{**measurement, "value": None}], "measurements"),
        lambda: contracts._measurements([measurement, measurement], "measurements"),
        lambda: contracts._parse_budget(
            {**budget, "max_agents": 1, "max_concurrency": 2}, "budget"
        ),
        lambda: contracts._parse_budget({**budget, "max_reasoning_effort": "ultra"}, "budget"),
        lambda: contracts._parse_budget(
            {**budget, "cost": {"status": "unknown", "currency": None, "max_microunits": None}},
            "budget",
        ),
        lambda: contracts._parse_budget(
            {**budget, "cost": {"status": "available", "currency": None, "max_microunits": None}},
            "budget",
        ),
        lambda: contracts._parse_budget(
            {**budget, "cost": {"status": "not_available", "currency": "USD", "max_microunits": 1}},
            "budget",
        ),
        lambda: contracts._validate_intent_profile(replace(intent, required_gate_ids=("G1", "G2"))),
        lambda: contracts._validate_intent_profile(replace(intent, ui_required=True)),
        lambda: contracts._validate_plan_profile(replace(plan, required_gate_ids=("G1", "G2"))),
        lambda: contracts._validate_plan_profile(replace(plan, ui_required=True)),
    ]
    for action in invalid_actions:
        with pytest.raises((WorkflowContractError, ContractError)):
            action()


def test_ordering_and_nested_contract_failures_reach_exact_invariants(tmp_path: Path) -> None:
    root = create_workspace(tmp_path)
    intent_artifact, _ = create_intent(root)
    intent = intent_artifact.value
    assert isinstance(intent, DevelopmentIntent)
    plan_artifact, _ = create_plan(root)
    plan = plan_artifact.value
    assert isinstance(plan, IntegratedPlan)
    task_a = plan.tasks[0].to_dict()
    task_z = {**task_a, "task_id": "TSK-Z"}
    with pytest.raises(WorkflowContractError, match="deterministic Plan order"):
        contracts._plan_tasks([task_z, task_a], "tasks")

    digest_a = "A" * 64
    digest_b = "B" * 64
    effect_a = {
        "effect_id": f"M8-EFFECT-{digest_a}",
        "task_id": "TSK-A",
        "effect_kind": "external",
        "target_paths": ["a.json"],
        "network_destinations": [],
        "reversible": False,
        "ambiguous_on_failure": True,
        "approval_types": ["owner"],
        "idempotency_scope": "native-m6-lease",
        "effect_digest": digest_a,
    }
    effect_b = {**effect_a, "effect_id": f"M8-EFFECT-{digest_b}", "effect_digest": digest_b}
    with pytest.raises(WorkflowContractError, match="effect identity order"):
        contracts._protected_effects([effect_b, effect_a], "effects")
    with pytest.raises(WorkflowContractError, match="duplicate effect"):
        contracts._protected_effects([effect_a, effect_a], "effects")

    decision_a = plan.decisions[0].to_dict()
    decision_z = {**decision_a, "subject_id": "TSK-Z"}
    with pytest.raises(WorkflowContractError, match="reason order"):
        contracts._decisions([decision_z, decision_a], "decisions")

    projection_a = {
        "task_id": "TSK-A",
        "state": "planned",
        "outcome": "none",
        "attempt": 0,
        "fence": 0,
        "blocker_codes": [],
    }
    projection_z = {**projection_a, "task_id": "TSK-Z"}
    with pytest.raises(WorkflowContractError, match="Task ID order"):
        contracts._workflow_tasks([projection_z, projection_a], "tasks")

    gate_one = {
        "gate_id": "G1",
        "status": "PASS",
        "evidence_ids": ["NATIVE-ID"],
        "blocker_codes": [],
    }
    gate_two = {**gate_one, "gate_id": "G2"}
    with pytest.raises(WorkflowContractError, match="Gate ID order"):
        contracts._gates([gate_two, gate_one], "gates")
    with pytest.raises(WorkflowContractError, match="duplicate Gates"):
        contracts._gates([gate_one, gate_one], "gates")

    budget = plan.budget.to_dict()
    with pytest.raises(WorkflowContractError, match="currency is invalid"):
        contracts._parse_budget(
            {
                **budget,
                "cost": {
                    "status": "available",
                    "currency": "12!",
                    "max_microunits": 1,
                },
            },
            "budget",
        )

    intent_content = intent.to_dict()
    for mutation, message in (
        ({**intent_content, "project_id": "bad project"}, "project_id"),
        (
            {
                **intent_content,
                "allowed_paths": ["same.json"],
                "prohibited_paths": ["same.json"],
            },
            "overlap",
        ),
        (
            {
                **intent_content,
                "solver_registry": None,
                "solver_requests": [intent.context_graph.to_dict()],
            },
            "Solver Requests",
        ),
    ):
        with pytest.raises(WorkflowContractError, match=message):
            contracts._parse_intent(mutation)

    plan_content = plan.to_dict()
    with pytest.raises(WorkflowContractError, match="project_id"):
        contracts._parse_plan({**plan_content, "project_id": "bad project"})
    with pytest.raises(WorkflowContractError, match="provided together"):
        contracts._parse_plan(
            {
                **plan_content,
                "predecessor_plan_id": "M8-INTEGRATED-PLAN-" + "A" * 64,
            }
        )
    with pytest.raises(WorkflowContractError, match="unknown Plan task"):
        contracts._parse_plan(
            {
                **plan_content,
                "protected_effects": [{**effect_a, "task_id": "TSK-Z"}],
            }
        )
    with pytest.raises(WorkflowContractError, match="Development Intent"):
        contracts._parse_plan({**plan_content, "intent": plan.task_graph.to_dict()})
    with pytest.raises(WorkflowContractError, match="Secret-or-prohibited"):
        contracts._parse_plan(
            {**plan_content, "sensitivity": Sensitivity.SECRET_OR_PROHIBITED.value}
        )

    state_artifact = parse_workflow_artifact_bytes(
        (ROOT / "examples/m8-workflow/workflow-state.json").read_bytes(),
        expected_type=WorkflowArtifactType.WORKFLOW_STATE,
    )
    state = state_artifact.value
    assert isinstance(state, WorkflowState)
    state_content = state.to_dict()
    with pytest.raises(WorkflowContractError, match="handoff identity"):
        contracts._parse_state({**state_content, "handoff_id": "HANDOFF-M8-ONLY"})
    wrong_latest = {**state.latest_event.to_dict(), "artifact_type": "integrated-plan"}
    with pytest.raises(WorkflowContractError, match="latest_event has the wrong type"):
        contracts._parse_state({**state_content, "latest_event": wrong_latest})
    with pytest.raises(WorkflowContractError, match="Event chain is incomplete"):
        contracts._parse_state({**state_content, "transition_count": state.transition_count + 1})

    event_artifact = parse_workflow_artifact_bytes(
        (ROOT / "examples/m8-workflow/workflow-event.json").read_bytes(),
        expected_type=WorkflowArtifactType.WORKFLOW_EVENT,
    )
    event = event_artifact.value
    event_content = event.to_dict()
    with pytest.raises(WorkflowContractError, match="First Workflow Event"):
        contracts._parse_event(
            {
                **event_content,
                "sequence": 1,
                "previous_event_id": "M8-WORKFLOW-EVENT-" + "A" * 64,
            }
        )
    with pytest.raises(WorkflowContractError, match="Later Workflow Event"):
        contracts._parse_event(
            {
                **event_content,
                "sequence": 2,
                "previous_event_id": None,
                "prior_state_id": None,
                "prior_state": None,
            }
        )
    with pytest.raises(WorkflowContractError, match="idempotency key"):
        contracts._parse_event({**event_content, "idempotency_key": "bad"})

    outcome_artifact = parse_workflow_artifact_bytes(
        (ROOT / "examples/m8-workflow/workflow-outcome.json").read_bytes(),
        expected_type=WorkflowArtifactType.WORKFLOW_OUTCOME,
    )
    outcome = outcome_artifact.value
    assert isinstance(outcome, WorkflowOutcome)
    outcome_content = outcome.to_dict()
    with pytest.raises(WorkflowContractError, match="lineage omits"):
        contracts._parse_outcome(
            {
                **outcome_content,
                "lineage_plan_ids": ["M8-INTEGRATED-PLAN-" + "F" * 64],
            }
        )
    with pytest.raises(WorkflowContractError, match="handoff fields"):
        contracts._parse_outcome(
            {**outcome_content, "handoff_id": "HANDOFF-M8-ONLY", "handoff_status": None}
        )

    bindings = sorted(
        (plan.intent.to_dict(), plan.task_graph.to_dict()),
        key=lambda item: str(item["artifact_id"]),
    )
    with pytest.raises(WorkflowContractError, match="artifact identity order"):
        contracts._bindings(list(reversed(bindings)), "bindings")
    with pytest.raises(WorkflowContractError, match="too few required bindings"):
        contracts._required_bindings([], "bindings", minimum=1)
    with pytest.raises(WorkflowContractError, match="artifact identity order"):
        contracts._required_bindings(list(reversed(bindings)), "bindings")
    with pytest.raises(WorkflowContractError, match="duplicate artifact identities"):
        contracts._required_bindings([bindings[0], bindings[0]], "bindings")
    with pytest.raises(WorkflowContractError, match="too few required bindings"):
        contracts._ordered_required_bindings([], "bindings", minimum=1)
    with pytest.raises(WorkflowContractError, match="duplicate artifact identities"):
        contracts._ordered_required_bindings([bindings[0], bindings[0]], "bindings")
