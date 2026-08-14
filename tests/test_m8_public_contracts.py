"""Public M8 schemas, examples, evaluation, and stable-boundary tests."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from scripts.validate_m8_workflow import main

import sdaqf
from sdaqf.cli import build_parser
from tests.m8_workflow_helpers import ROOT
from tests.schema_validation import LocalSchemaValidator, SchemaValidationError

EXAMPLE_TO_SCHEMA = {
    "development-intent.json": "development-intent.schema.json",
    "integrated-plan.json": "integrated-plan.schema.json",
    "workflow-state.json": "workflow-state.schema.json",
    "workflow-event.json": "workflow-event.schema.json",
    "workflow-outcome.json": "workflow-outcome.schema.json",
}


def test_all_five_public_examples_validate_against_local_schemas() -> None:
    validator = LocalSchemaValidator(ROOT / "schemas")
    for example, schema in EXAMPLE_TO_SCHEMA.items():
        instance = json.loads((ROOT / "examples/m8-workflow" / example).read_text(encoding="utf-8"))
        validator.validate(schema, instance)


@pytest.mark.parametrize("example", ["workflow-state.json", "workflow-outcome.json"])
@pytest.mark.parametrize("mutation", ["missing", "foreign", "duplicate", "reordered"])
def test_terminal_schema_requires_exact_canonical_52_measurements(
    example: str,
    mutation: str,
) -> None:
    validator = LocalSchemaValidator(ROOT / "schemas")
    payload = json.loads(
        (ROOT / "examples" / "m8-workflow" / example).read_text(encoding="utf-8")
    )
    measurements = payload["content"]["measurements"]
    if mutation == "missing":
        measurements.pop()
    elif mutation == "foreign":
        measurements[0]["name"] = "foreign.measurement"
    elif mutation == "duplicate":
        measurements[1]["name"] = measurements[0]["name"]
        measurements[1]["value"] = 999
    else:
        measurements[0], measurements[1] = measurements[1], measurements[0]
    with pytest.raises(SchemaValidationError):
        validator.validate(example.replace(".json", ".schema.json"), payload)


def test_schema_rejects_optionalized_bindings_invalid_paths_and_dates() -> None:
    validator = LocalSchemaValidator(ROOT / "schemas")
    intent_path = ROOT / "examples/m8-workflow/development-intent.json"
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["content"]["context_graph"]["required"] = False
    with pytest.raises(SchemaValidationError):
        validator.validate("development-intent.schema.json", intent)

    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["content"]["specification"]["path"] = "CON/file.json"
    with pytest.raises(SchemaValidationError):
        validator.validate("development-intent.schema.json", intent)

    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["content"]["predecessor_plan_id"] = "M8-INTEGRATED-PLAN-" + "A" * 64
    with pytest.raises(SchemaValidationError):
        validator.validate("development-intent.schema.json", intent)

    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    binding = intent["content"]["context_graph"]
    intent["content"].update(
        {
            "predecessor_plan_id": "M8-INTEGRATED-PLAN-" + "A" * 64,
            "predecessor_state_id": "M8-WORKFLOW-STATE-" + "B" * 64,
            "predecessor_outcome_id": "M8-WORKFLOW-OUTCOME-" + "C" * 64,
            "predecessor_plan": binding,
            "predecessor_state": binding,
            "predecessor_outcome": binding,
        }
    )
    validator.validate("development-intent.schema.json", intent)

    event = json.loads(
        (ROOT / "examples/m8-workflow/workflow-event.json").read_text(encoding="utf-8")
    )
    event["content"]["recorded_at"] = "2026-02-30T00:00:00Z"
    with pytest.raises(SchemaValidationError):
        validator.validate("workflow-event.schema.json", event)

    event = json.loads(
        (ROOT / "examples/m8-workflow/workflow-event.json").read_text(encoding="utf-8")
    )
    event["content"]["sequence"] = 2
    with pytest.raises(SchemaValidationError):
        validator.validate("workflow-event.schema.json", event)


def test_evaluation_has_twelve_named_non_aggregate_cases() -> None:
    suite = json.loads((ROOT / "evals/m8-workflow-suite.json").read_text())
    result = json.loads((ROOT / "evals/results/m8-workflow-evaluation.json").read_text())
    assert len(suite["cases"]) == len(result["cases"]) == 12
    assert [item["scenario"] for item in suite["cases"]] == [
        item["scenario"] for item in result["cases"]
    ]
    assert all(item["passed"] is True for item in result["cases"])
    assert "aggregate_score" not in json.dumps(suite)
    assert "aggregate_score" not in json.dumps(result)


def test_m8_does_not_widen_stable_top_level_exports_or_dependencies() -> None:
    assert sdaqf.__all__ == ["GateCheck", "GateResult", "ToolCapability", "ToolStatus"]
    assert "dependencies = []" in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_workflow_cli_surface_matches_the_exact_owner_approved_amendment() -> None:
    parser = build_parser()
    root_commands = cast(
        Any,
        next(action for action in parser._actions if action.dest == "command"),
    ).choices
    workflow = root_commands["workflow"]
    workflow_commands = cast(
        Any,
        next(action for action in workflow._actions if action.dest == "workflow_command"),
    ).choices
    expected = {
        "validate": ("artifact", "json"),
        "plan": (
            "intent",
            "root",
            "scheduler_state",
            "predecessor_scheduler_state",
            "output",
            "json",
        ),
        "explain": (
            "plan",
            "root",
            "scheduler_state",
            "predecessor_scheduler_state",
            "json",
        ),
        "simulate": (
            "plan",
            "root",
            "scheduler_state",
            "predecessor_scheduler_state",
            "scenario",
            "json",
        ),
        "run": (
            "plan",
            "root",
            "scheduler_state",
            "predecessor_scheduler_state",
            "output_state",
            "output_event",
            "message",
            "host_outbox",
            "json",
        ),
        "resume": (
            "state",
            "plan",
            "root",
            "scheduler_state",
            "predecessor_scheduler_state",
            "output_state",
            "output_event",
            "message",
            "host_outbox",
            "json",
        ),
        "supersede": (
            "state",
            "plan",
            "successor_intent",
            "root",
            "scheduler_state",
            "output_state",
            "output_event",
            "output_outcome",
            "json",
        ),
        "status": (
            "state",
            "plan",
            "root",
            "scheduler_state",
            "predecessor_scheduler_state",
            "json",
        ),
        "recover": (
            "state",
            "plan",
            "root",
            "scheduler_state",
            "predecessor_scheduler_state",
            "event",
            "output_state",
            "output_event",
            "json",
        ),
        "outcome": (
            "state",
            "plan",
            "root",
            "scheduler_state",
            "output",
            "output_event",
            "output_state",
            "json",
        ),
        "report": (
            "outcome",
            "state",
            "plan",
            "root",
            "scheduler_state",
            "json",
        ),
    }
    assert set(workflow_commands) == set(expected)
    for command, destinations in expected.items():
        actions = tuple(
            action
            for action in workflow_commands[command]._actions
            if action.dest != "help"
        )
        assert tuple(action.dest for action in actions) == destinations
        for action in actions:
            if action.option_strings:
                assert tuple(action.option_strings) == (f"--{action.dest.replace('_', '-')}",)


def test_documentation_claims_only_the_closed_verified_m8_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    framework = (ROOT / "docs/integrated-vibe-coding-framework.md").read_text(encoding="utf-8")
    implementation_status = (ROOT / "docs/implementation-status.md").read_text(
        encoding="utf-8"
    )
    roadmap = (ROOT / "docs/roadmap.md").read_text(encoding="utf-8")
    compatibility = (ROOT / "docs/compatibility.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    active_plan = (
        ROOT / "docs/exec-plans/active/M8-integrated-vibe-coding-framework.md"
    ).read_text(encoding="utf-8")
    assert "excludes only the reserved `workflow/` runtime-private subtree" not in architecture
    assert "terminal State is the published closure State" in framework
    assert "Current review and remediation verification" in active_plan

    current_status_documents = (
        readme,
        implementation_status,
        framework,
        roadmap,
        compatibility,
        active_plan,
    )
    for document in current_status_documents:
        normalized = " ".join(document.split())
        normalized_lower = normalized.lower()
        assert "successor lifecycle compatibility review" in normalized
        assert "zero unresolved" in normalized
        assert "F1" in normalized and "F11" in normalized
        assert "release GO" in normalized
        assert "production readiness" in normalized
        assert "experimental" in normalized_lower
        assert "unreleased" in normalized_lower
        assert "commit" in normalized_lower and "push" in normalized_lower

    for document in current_status_documents:
        normalized = " ".join(document.split())
        assert "pull request #4" in normalized
        assert "31558960113" in normalized
        assert "31563987706" in normalized

    review_evidence_documents = (
        readme,
        implementation_status,
        framework,
        changelog,
        active_plan,
    )
    for document in review_evidence_documents:
        normalized = " ".join(document.split())
        assert "did not rerun full pytest" in normalized
        assert "28" in normalized and "120" in normalized and "9" in normalized
        assert "coverage" in normalized

    assert "NO-GO pending a fresh independent disposition" not in readme
    assert "needs fresh independent review" not in implementation_status
    m8_summary = next(
        line
        for line in implementation_status.splitlines()
        if line.startswith("| M8 Integrated Workflow |")
    )
    assert "release and exact-SHA remote CI remain unverified" not in m8_summary
    normalized_changelog = " ".join(changelog.split())
    assert "GO for the current local candidate" in normalized_changelog
    assert "No hash list or candidate fingerprint was created" in normalized_changelog
    assert "- [ ] Hand the successor lifecycle remediation" not in active_plan


def test_public_status_keeps_milestone_dispositions_independent() -> None:
    disposition = (
        "The current dispositions are independent: M5 GO, M6 GO, M7 GO, and M8 "
        "successor lifecycle GO."
    )
    for relative in (
        "README.md",
        "CHANGELOG.md",
        "docs/implementation-status.md",
        "docs/roadmap.md",
        "docs/compatibility.md",
    ):
        document = (ROOT / relative).read_text(encoding="utf-8")
        unquoted = "\n".join(
            line[2:] if line.startswith("> ") else line
            for line in document.splitlines()
        )
        assert disposition in " ".join(unquoted.split())

    compatibility = " ".join(
        (ROOT / "docs/compatibility.md").read_text(encoding="utf-8").split()
    )
    assert "latest M5 disposition is GO for the reviewed repository state" in compatibility
    assert (
        "latest M6 disposition is GO for the reviewed state merged by pull request #4"
        in compatibility
    )
    assert "later pre-publication stop remain recorded" in compatibility

    m5_plan = (
        ROOT / "docs/exec-plans/active/M5-context-framework.md"
    ).read_text(encoding="utf-8")
    m6_plan = (
        ROOT / "docs/exec-plans/active/M6-multi-agent-control-framework.md"
    ).read_text(encoding="utf-8")
    assert "final independent compatibility re-review returned NO-GO" in " ".join(
        m5_plan.split()
    )
    assert "final independent compatibility review returned NO-GO" in " ".join(
        m6_plan.split()
    )
    normalized_m6_plan = " ".join(m6_plan.split())
    assert "- [ ] Complete the full local Gate matrix" not in normalized_m6_plan
    assert "31558960113" in normalized_m6_plan
    assert "31563987706" in normalized_m6_plan

    changelog = " ".join((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split())
    historical_disposition = (
        "The dispositions are independent: M5 NO-GO, M6 NO-GO, M7 GO, "
        "and M8 successor lifecycle GO."
    )
    assert historical_disposition in changelog


def test_named_m8_validator_passes() -> None:
    assert main() == 0


def test_ci_enforces_m8_coverage_and_named_validation() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    normalized = " ".join(workflow.split())
    gate_runner = (ROOT / "scripts" / "run_local_gate.py").read_text(encoding="utf-8")
    assert "M1 through M8 critical branch coverage" in workflow
    assert "src/sdaqf/domain/workflow.py" in gate_runner
    assert "src/sdaqf/application/workflow_runtime.py" in gate_runner
    assert "90," in gate_runner
    assert "Validate M8 workflow integration" in workflow
    assert (
        "python scripts/run_local_gate.py script scripts/validate_m8_workflow.py"
        in normalized
    )
