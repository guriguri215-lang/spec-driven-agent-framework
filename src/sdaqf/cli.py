"""Command-line interface for the offline M0 through M4 framework."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from sdaqf.adapters.process import SubprocessRunner
from sdaqf.application.approvals import ApprovalContractError, ApprovalLoader
from sdaqf.application.baselines import BaselineContractError, load_baseline
from sdaqf.application.checkpoints import (
    CheckpointContractError,
    CheckpointStore,
    validate_resume,
)
from sdaqf.application.comparison import BaselineComparator, BaselineDiff
from sdaqf.application.contracts import ContractError
from sdaqf.application.doctor import DoctorService
from sdaqf.application.evaluation import EvaluationService
from sdaqf.application.evidence import (
    EvidenceLedgerStore,
    load_evidence_ledger,
    load_evidence_record,
)
from sdaqf.application.goals import GoalTemplateService
from sdaqf.application.handoffs import (
    HandoffService,
    inspect_specification,
    load_automated_handoff,
    validate_handoff_resume,
)
from sdaqf.application.migrations import MigrationService
from sdaqf.application.orchestration import (
    AgentOrchestrator,
    OrchestrationContractError,
    load_agent_registry,
    load_agent_result,
    load_orchestration_request,
    load_worktree_plan,
    validate_agent_tool_references,
)
from sdaqf.application.planning import PlanningService, PromptMode, PromptService
from sdaqf.application.quality_gates import (
    FindingAcceptanceLoader,
    ImplementationEvidenceGateService,
    IndependentReviewGateService,
    load_independent_review,
)
from sdaqf.application.release_qa import (
    GitInspector,
    ReleaseCandidateGateService,
    load_release_candidate,
)
from sdaqf.application.requirements import SpecificationError, SpecificationIngestor
from sdaqf.application.requirements_gate import RequirementsGateService
from sdaqf.application.skills import (
    SkillContractError,
    evaluate_templates,
    load_template_registry,
    validate_skills,
)
from sdaqf.application.status import StatusService
from sdaqf.application.tooling import (
    ExecutionApprovalConsumptionStore,
    ExecutionApprovalLoader,
    ToolContractError,
    ToolService,
    load_tool_registry,
)
from sdaqf.application.ui_validation import (
    UiValidationService,
    load_manifest_ui,
    load_ui_validation,
)
from sdaqf.application.validation import ProjectValidator
from sdaqf.application.workspace import WorkspaceInitializer, is_reparse_point
from sdaqf.domain.quality import CandidateIdentity, GitObservation
from sdaqf.domain.tooling import ExecutionContext, ToolObservationStatus


def build_parser() -> argparse.ArgumentParser:
    """Build the deterministic argument parser."""

    parser = argparse.ArgumentParser(
        prog="sdaqf",
        description="Specification-driven agent development foundation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Report local tool capabilities.")
    doctor.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    doctor.add_argument(
        "--current-session-active",
        action="store_true",
        help="Record that the caller observed an active Codex session.",
    )

    initialize = subparsers.add_parser("init", help="Initialize safe local project state.")
    initialize.add_argument("target", type=Path, help="Target project directory.")
    initialize.add_argument("--dry-run", action="store_true", help="Plan without writing.")
    initialize.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    validate = subparsers.add_parser("validate", help="Validate a sample project.")
    validate.add_argument("project", type=Path, help="Sample project directory.")
    validate.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    status = subparsers.add_parser("status", help="Show a project status.")
    status.add_argument("project", type=Path, help="Sample project directory.")
    status.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    goal = subparsers.add_parser("goal-template", help="Render a complete Codex Goal prompt.")
    goal.add_argument("milestone", help="Milestone identifier, such as M1.")
    goal.add_argument("--output", type=Path, help="Optional new output file.")

    ingest = subparsers.add_parser(
        "ingest", help="Ingest an untrusted Markdown specification."
    )
    ingest.add_argument("specification", type=Path, help="Markdown specification.")
    ingest.add_argument("--output", type=Path, help="Optional new baseline JSON file.")
    ingest.add_argument("--json", action="store_true", help="Emit the baseline as JSON.")

    compare = subparsers.add_parser(
        "compare", help="Compare two validated requirement baselines."
    )
    compare.add_argument("previous", type=Path, help="Previous baseline JSON.")
    compare.add_argument("current", type=Path, help="Current baseline JSON.")
    compare.add_argument(
        "--approval",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
        help="Validated structured Owner approval JSON; repeat as needed.",
    )
    compare.add_argument("--output", type=Path, help="Optional new comparison JSON file.")
    compare.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    roadmap = subparsers.add_parser("roadmap", help="Generate a Product Roadmap.")
    roadmap.add_argument("baseline", type=Path, help="Requirement baseline JSON.")
    roadmap.add_argument("milestone", help="Safe milestone identifier.")
    roadmap.add_argument("--output", type=Path, help="Optional new Markdown output file.")

    exec_plan = subparsers.add_parser("exec-plan", help="Generate a living ExecPlan.")
    exec_plan.add_argument("baseline", type=Path, help="Requirement baseline JSON.")
    exec_plan.add_argument("milestone", help="Safe milestone identifier.")
    exec_plan.add_argument("--output", type=Path, help="Optional new Markdown output file.")

    goal_prompt = subparsers.add_parser(
        "goal", help="Generate a Goal prompt or safely fall back to Standard mode."
    )
    goal_prompt.add_argument("baseline", type=Path, help="Requirement baseline JSON.")
    goal_prompt.add_argument("milestone", help="Safe milestone identifier.")
    goal_prompt.add_argument(
        "--objective",
        help="Optional requirement ID for a single-requirement Goal.",
    )
    goal_prompt.add_argument("--output", type=Path, help="Optional new Markdown output file.")
    goal_prompt.add_argument("--json", action="store_true", help="Emit mode metadata as JSON.")

    standard_prompt = subparsers.add_parser("prompt", help="Generate a Standard prompt.")
    standard_prompt.add_argument("baseline", type=Path, help="Requirement baseline JSON.")
    standard_prompt.add_argument("milestone", help="Safe milestone identifier.")
    standard_prompt.add_argument(
        "--mode",
        choices=[item.value for item in PromptMode],
        default=PromptMode.STANDARD.value,
        help="Requested execution mode.",
    )
    standard_prompt.add_argument(
        "--objective",
        action="append",
        default=[],
        help="Explicit objective identifier; repeat to assess multi-objective work.",
    )
    standard_prompt.add_argument(
        "--output", type=Path, help="Optional new Markdown output file."
    )
    standard_prompt.add_argument(
        "--json", action="store_true", help="Emit mode metadata as JSON."
    )

    gate = subparsers.add_parser("gate", help="Evaluate a deterministic quality Gate.")
    gate_subparsers = gate.add_subparsers(dest="gate_name", required=True)
    requirements_gate = gate_subparsers.add_parser(
        "requirements", help="Evaluate Gate G1 for a requirement baseline."
    )
    requirements_gate.add_argument("baseline", type=Path, help="Current baseline JSON.")
    requirements_gate.add_argument(
        "--previous", type=Path, help="Optional previous baseline for change approval checks."
    )
    requirements_gate.add_argument(
        "--approval",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
        help="Validated structured Owner approval JSON; repeat as needed.",
    )
    requirements_gate.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    implementation_gate = gate_subparsers.add_parser(
        "implementation",
        help="Evaluate Gate G2 for a requirement baseline and evidence ledger.",
    )
    implementation_gate.add_argument("baseline", type=Path)
    implementation_gate.add_argument("--ledger", type=Path, required=True)
    implementation_gate.add_argument("--specification", type=Path, required=True)
    implementation_gate.add_argument("--root", type=Path, default=Path("."))
    implementation_gate.add_argument("--json", action="store_true")
    review_gate = gate_subparsers.add_parser(
        "review",
        help="Evaluate Gate G3 for an independent read-only review.",
    )
    review_gate.add_argument("review", type=Path)
    review_gate.add_argument("--baseline", type=Path, required=True)
    review_gate.add_argument("--specification", type=Path, required=True)
    review_gate.add_argument("--root", type=Path, default=Path("."))
    review_gate.add_argument(
        "--approval",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
    )
    review_gate.add_argument("--json", action="store_true")

    evidence = subparsers.add_parser(
        "evidence",
        help="Validate or atomically add Claim-Evidence Ledger evidence.",
    )
    evidence_commands = evidence.add_subparsers(
        dest="evidence_command",
        required=True,
    )
    evidence_validate = evidence_commands.add_parser(
        "validate",
        help="Validate a Claim-Evidence Ledger.",
    )
    evidence_validate.add_argument("ledger", type=Path)
    evidence_validate.add_argument("--json", action="store_true")
    evidence_add = evidence_commands.add_parser(
        "add",
        help="Atomically add one validated evidence record.",
    )
    evidence_add.add_argument("ledger", type=Path)
    evidence_add.add_argument("record", type=Path)
    evidence_add.add_argument("--json", action="store_true")

    ui = subparsers.add_parser(
        "ui",
        help="Validate UI classification and recorded browser observations.",
    )
    ui_commands = ui.add_subparsers(dest="ui_command", required=True)
    ui_validate = ui_commands.add_parser(
        "validate",
        help="Evaluate the applicable UI/UX validation Gate.",
    )
    ui_validate.add_argument("manifest", type=Path)
    ui_validate.add_argument("validation", type=Path)
    ui_validate.add_argument("--specification", type=Path, required=True)
    ui_validate.add_argument("--root", type=Path, default=Path("."))
    ui_validate.add_argument("--json", action="store_true")

    audit = subparsers.add_parser(
        "audit",
        help="Evaluate local release quality without publication.",
    )
    audit_commands = audit.add_subparsers(dest="audit_command", required=True)
    release_audit = audit_commands.add_parser(
        "release-candidate",
        help="Evaluate local release-candidate Gate G4.",
    )
    release_audit.add_argument("candidate", type=Path)
    release_audit.add_argument("--root", type=Path, default=Path("."))
    release_audit.add_argument("--baseline", type=Path, required=True)
    release_audit.add_argument("--ledger", type=Path, required=True)
    release_audit.add_argument("--review", type=Path, required=True)
    release_audit.add_argument("--manifest", type=Path, required=True)
    release_audit.add_argument("--ui-validation", type=Path, required=True)
    release_audit.add_argument("--specification", type=Path, required=True)
    release_audit.add_argument(
        "--approval",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
    )
    release_audit.add_argument("--json", action="store_true")

    handoff = subparsers.add_parser(
        "handoff",
        help="Create or resume a deterministic session handoff.",
    )
    handoff_commands = handoff.add_subparsers(
        dest="handoff_command",
        required=True,
    )
    handoff_create = handoff_commands.add_parser(
        "create",
        help="Create a new automated handoff from explicit local state.",
    )
    handoff_create.add_argument("input", type=Path)
    handoff_create.add_argument("--root", type=Path, default=Path("."))
    handoff_create.add_argument("--baseline", type=Path, required=True)
    handoff_create.add_argument("--ledger", type=Path, required=True)
    handoff_create.add_argument("--specification", type=Path, required=True)
    handoff_create.add_argument("--output", type=Path, required=True)
    handoff_create.add_argument("--json", action="store_true")
    handoff_resume = handoff_commands.add_parser(
        "resume",
        help="Validate handoff identity before resuming.",
    )
    handoff_resume.add_argument("handoff", type=Path)
    handoff_resume.add_argument("--root", type=Path, default=Path("."))
    handoff_resume.add_argument("--baseline", type=Path, required=True)
    handoff_resume.add_argument("--ledger", type=Path, required=True)
    handoff_resume.add_argument("--specification", type=Path, required=True)
    handoff_resume.add_argument("--json", action="store_true")

    agents = subparsers.add_parser(
        "agents",
        help="Validate and plan bounded agent orchestration.",
    )
    agent_commands = agents.add_subparsers(dest="agent_command", required=True)
    agents_validate = agent_commands.add_parser(
        "validate",
        help="Validate Agent and Tool Registry references.",
    )
    agents_validate.add_argument("registry", type=Path)
    agents_validate.add_argument("--tools", type=Path, required=True)
    agents_validate.add_argument("--json", action="store_true")
    agents_plan = agent_commands.add_parser(
        "plan",
        help="Create a deterministic orchestration plan.",
    )
    agents_plan.add_argument("request", type=Path)
    agents_plan.add_argument("--registry", type=Path, required=True)
    agents_plan.add_argument("--tools", type=Path, required=True)
    agents_plan.add_argument("--worktree-plan", type=Path)
    agents_plan.add_argument("--json", action="store_true")
    agents_result = agent_commands.add_parser(
        "validate-result",
        help="Validate one structured agent result.",
    )
    agents_result.add_argument("result", type=Path)
    agents_result.add_argument("--registry", type=Path, required=True)
    agents_result.add_argument("--json", action="store_true")

    skills = subparsers.add_parser(
        "skills",
        help="Validate repository Skill and template lifecycle.",
    )
    skill_commands = skills.add_subparsers(dest="skill_command", required=True)
    skills_validate = skill_commands.add_parser(
        "validate",
        help="Validate Skills and template compatibility.",
    )
    skills_validate.add_argument("root", type=Path)
    skills_validate.add_argument("--templates", type=Path, required=True)
    skills_validate.add_argument("--framework-version", default="0.1.0")
    skills_validate.add_argument("--available", action="append", default=[])
    skills_validate.add_argument("--condition", action="append", default=[])
    skills_validate.add_argument("--select-skill", action="append", default=[])
    skills_validate.add_argument("--select-template", action="append", default=[])
    skills_validate.add_argument("--json", action="store_true")

    tools = subparsers.add_parser(
        "tools",
        help="Validate and safely probe registered local tools.",
    )
    tool_commands = tools.add_subparsers(dest="tool_command", required=True)
    tools_validate = tool_commands.add_parser(
        "validate",
        help="Validate a Tool Registry.",
    )
    tools_validate.add_argument("registry", type=Path)
    tools_validate.add_argument("--json", action="store_true")
    tools_check = tool_commands.add_parser(
        "check",
        help="Execute one registered bounded version probe.",
    )
    tools_check.add_argument("registry", type=Path)
    tools_check.add_argument("--name", required=True)
    tools_check.add_argument(
        "--approval",
        action="append",
        default=[],
        type=Path,
        metavar="FILE",
        help="Validated single-execution tool approval JSON; repeat as needed.",
    )
    tools_check.add_argument("--json", action="store_true")

    checkpoint = subparsers.add_parser(
        "checkpoint",
        help="Validate or resume an execution checkpoint.",
    )
    checkpoint_commands = checkpoint.add_subparsers(
        dest="checkpoint_command",
        required=True,
    )
    checkpoint_validate = checkpoint_commands.add_parser(
        "validate",
        help="Validate a checkpoint with backup recovery.",
    )
    checkpoint_validate.add_argument("file", type=Path)
    checkpoint_validate.add_argument("--json", action="store_true")
    checkpoint_resume = checkpoint_commands.add_parser(
        "resume",
        help="Validate exact resume context.",
    )
    checkpoint_resume.add_argument("file", type=Path)
    checkpoint_resume.add_argument("--plan-version", required=True)
    checkpoint_resume.add_argument("--specification-digest", required=True)
    checkpoint_resume.add_argument("--git-head", required=True)
    checkpoint_resume.add_argument("--worktree-digest", required=True)
    checkpoint_resume.add_argument("--json", action="store_true")

    evaluation = subparsers.add_parser(
        "eval",
        help="Validate and compare bounded public-beta evaluation records.",
    )
    evaluation_commands = evaluation.add_subparsers(
        dest="evaluation_command",
        required=True,
    )
    evaluation_validate = evaluation_commands.add_parser(
        "validate",
        help="Validate a suite and its optional recorded deterministic result.",
    )
    evaluation_validate.add_argument("suite", type=Path)
    evaluation_validate.add_argument("--result", type=Path)
    evaluation_validate.add_argument("--json", action="store_true")
    evaluation_compare = evaluation_commands.add_parser(
        "compare",
        help="Calculate paired workflow metrics without an aggregate score.",
    )
    evaluation_compare.add_argument("suite", type=Path)
    evaluation_compare.add_argument("--json", action="store_true")

    schema = subparsers.add_parser(
        "schema",
        help="Perform explicit non-destructive schema operations.",
    )
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    schema_migrate = schema_commands.add_parser(
        "migrate",
        help="Migrate one supported legacy registry to a new validated file.",
    )
    schema_migrate.add_argument(
        "--contract",
        required=True,
        choices=("agent-registry", "tool-registry"),
    )
    schema_migrate.add_argument("--from-version", required=True)
    schema_migrate.add_argument("--to-version", required=True)
    schema_migrate.add_argument("input", type=Path)
    schema_migrate.add_argument("--output", type=Path, required=True)
    schema_migrate.add_argument(
        "--approval",
        type=Path,
        required=True,
        help="Exact time-bounded Owner approval record for this migration.",
    )
    schema_migrate.add_argument(
        "--tool-registry",
        type=Path,
        help="Required current Tool Registry for Agent Registry cross-reference.",
    )
    schema_migrate.add_argument("--root", type=Path, default=Path("."))
    schema_migrate.add_argument("--json", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a stable exit code."""

    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        capabilities = DoctorService(SubprocessRunner()).inspect(
            current_session_active=args.current_session_active
        )
        doctor_payload: dict[str, object] = {
            "capabilities": [item.to_dict() for item in capabilities]
        }
        _emit(doctor_payload, as_json=args.json)
        return 0

    if args.command == "init":
        initializer = WorkspaceInitializer()
        try:
            plan = (
                initializer.plan(args.target)
                if args.dry_run
                else initializer.initialize(args.target)
            )
        except OSError:
            print("ERROR: initialization failed without changing existing files.", file=sys.stderr)
            return 2
        _emit(plan.to_dict(), as_json=args.json)
        return 0 if plan.safe else 2

    if args.command == "validate":
        report = ProjectValidator().validate(args.project)
        _emit(report.to_dict(), as_json=args.json)
        return 0 if report.valid else 2

    if args.command == "status":
        status_payload = StatusService(ProjectValidator()).describe(args.project)
        _emit(status_payload, as_json=args.json)
        return 0 if status_payload["state"] == "ready" else 2

    if args.command == "goal-template":
        try:
            rendered = GoalTemplateService().render(args.milestone)
        except ValueError:
            print("ERROR: milestone must be a safe ASCII identifier.", file=sys.stderr)
            return 2
        if args.output is not None:
            try:
                _write_new_file(args.output, rendered)
            except OSError:
                print("ERROR: output file was not created.", file=sys.stderr)
                return 2
            print(f"Goal template created: {args.output.name}")
        else:
            print(rendered, end="")
        return 0

    if args.command == "ingest":
        try:
            baseline = SpecificationIngestor().ingest(args.specification)
            if args.output is not None:
                _write_new_file(args.output, _json_text(baseline.to_dict()))
        except (SpecificationError, OSError):
            print("ERROR: specification ingestion failed without creating output.", file=sys.stderr)
            return 2
        if args.json:
            print(_json_text(baseline.to_dict()), end="")
        else:
            payload: dict[str, object] = {
                "baseline_id": baseline.baseline_id,
                "requirements": len(baseline.requirements),
                "diagnostics": len(baseline.diagnostics),
                "output": args.output.name if args.output is not None else "not-written",
            }
            _emit(payload, as_json=False)
        return 0

    if args.command == "compare":
        try:
            previous = load_baseline(args.previous)
            current = load_baseline(args.current)
            comparison = BaselineComparator().compare(
                previous,
                current,
                approvals=tuple(
                    ApprovalLoader().load(path) for path in args.approval
                ),
            )
            if args.output is not None:
                _write_new_file(args.output, _json_text(comparison.to_dict()))
        except (ApprovalContractError, BaselineContractError, OSError):
            print("ERROR: baseline comparison failed without creating output.", file=sys.stderr)
            return 2
        if args.json:
            print(_json_text(comparison.to_dict()), end="")
        else:
            _emit(
                {
                    "changes": len(comparison.changes),
                    "unresolved_approvals": len(comparison.unresolved_approvals),
                    "output": args.output.name if args.output is not None else "not-written",
                },
                as_json=False,
            )
        return 0

    if args.command in {"roadmap", "exec-plan"}:
        try:
            planning_baseline = load_baseline(args.baseline)
            planning = PlanningService()
            content = (
                planning.render_roadmap(planning_baseline, args.milestone)
                if args.command == "roadmap"
                else planning.render_exec_plan(planning_baseline, args.milestone)
            )
            if args.output is not None:
                _write_new_file(args.output, content)
        except (BaselineContractError, OSError, ValueError):
            print("ERROR: planning artifact was not created.", file=sys.stderr)
            return 2
        if args.output is None:
            print(content, end="")
        else:
            print(f"Planning artifact created: {args.output.name}")
        return 0

    if args.command in {"goal", "prompt"}:
        try:
            prompt_baseline = load_baseline(args.baseline)
            requested_mode = (
                PromptMode.GOAL
                if args.command == "goal"
                else PromptMode(args.mode)
            )
            if args.command == "goal" and args.objective is not None:
                explicit_objectives = (args.objective,)
            elif args.command == "prompt" and args.objective:
                explicit_objectives = tuple(args.objective)
            else:
                explicit_objectives = None
            artifact = PromptService().render(
                prompt_baseline,
                args.milestone,
                requested_mode=requested_mode,
                objective_ids=explicit_objectives,
            )
            if args.output is not None:
                _write_new_file(args.output, artifact.content)
        except (BaselineContractError, OSError, ValueError):
            print("ERROR: prompt was not created.", file=sys.stderr)
            return 2
        if args.json:
            print(_json_text(artifact.to_dict()), end="")
        elif args.output is None:
            print(artifact.content, end="")
        else:
            print(
                f"Prompt created: {args.output.name} "
                f"(selected mode: {artifact.selected_mode.value})"
            )
        return 0

    if args.command == "gate" and args.gate_name == "requirements":
        try:
            gate_baseline = load_baseline(args.baseline)
            gate_comparison: BaselineDiff | None = None
            if args.approval and args.previous is None:
                raise ApprovalContractError(
                    "Approval records require a previous baseline."
                )
            if args.previous is not None:
                gate_comparison = BaselineComparator().compare(
                    load_baseline(args.previous),
                    gate_baseline,
                    approvals=tuple(
                        ApprovalLoader().load(path) for path in args.approval
                    ),
                )
            result = RequirementsGateService().evaluate(
                gate_baseline, comparison=gate_comparison
            )
        except (ApprovalContractError, BaselineContractError):
            print("ERROR: requirements Gate input is invalid.", file=sys.stderr)
            return 2
        _emit(result.to_dict(), as_json=args.json)
        return 0 if result.passed else 2

    if args.command == "gate" and args.gate_name == "implementation":
        try:
            root = _exact_working_root(args.root)
            baseline = load_baseline(args.baseline)
            source_digest = inspect_specification(
                root,
                args.specification,
                expected_filename=baseline.source.filename,
            )
            if source_digest != baseline.source.sha256:
                raise ContractError("Specification does not match the baseline.")
            git = GitInspector(
                SubprocessRunner(timeout_seconds=5, output_limit=1_048_576)
            ).inspect(root)
            _require_specification_candidate(root, args.specification, git)
            result = ImplementationEvidenceGateService().evaluate(
                baseline,
                load_evidence_ledger(args.ledger),
                candidate=_candidate_identity(source_digest, git),
                root=root,
            )
        except (BaselineContractError, ContractError, OSError):
            print("ERROR: implementation Gate input is invalid.", file=sys.stderr)
            return 2
        _emit(result.to_dict(), as_json=args.json)
        return 0 if result.passed else 2

    if args.command == "gate" and args.gate_name == "review":
        try:
            root = _exact_working_root(args.root)
            baseline = load_baseline(args.baseline)
            source_digest = inspect_specification(
                root,
                args.specification,
                expected_filename=baseline.source.filename,
            )
            if source_digest != baseline.source.sha256:
                raise ContractError("Specification does not match the baseline.")
            git = GitInspector(
                SubprocessRunner(timeout_seconds=5, output_limit=1_048_576)
            ).inspect(root)
            _require_specification_candidate(root, args.specification, git)
            result = IndependentReviewGateService().evaluate(
                load_independent_review(args.review),
                baseline_id=baseline.baseline_id,
                candidate=_candidate_identity(source_digest, git),
                changed_paths=git.changed_paths,
                candidate_paths=git.publication_paths,
                approvals=tuple(
                    FindingAcceptanceLoader().load(path)
                    for path in args.approval
                ),
            )
        except (BaselineContractError, ContractError, OSError):
            print("ERROR: independent review Gate input is invalid.", file=sys.stderr)
            return 2
        _emit(result.to_dict(), as_json=args.json)
        return 0 if result.passed else 2

    if args.command == "evidence":
        try:
            if args.evidence_command == "validate":
                ledger = load_evidence_ledger(args.ledger)
            else:
                root = _exact_working_root(Path("."))
                ledger_path = _m3_state_path(
                    root,
                    args.ledger,
                    require_existing=True,
                )
                ledger = EvidenceLedgerStore(root / ".sdaqf").add(
                    ledger_path,
                    load_evidence_record(args.record),
                )
        except ContractError:
            print("ERROR: evidence contract is invalid.", file=sys.stderr)
            return 2
        _emit(
            {
                "schema_version": ledger.schema_version,
                "baseline_id": ledger.baseline_id,
                "claims": len(ledger.claims),
                "evidence": len(ledger.evidence),
            },
            as_json=args.json,
        )
        return 0

    if args.command == "ui" and args.ui_command == "validate":
        try:
            root = _exact_working_root(args.root)
            manifest = load_manifest_ui(args.manifest)
            source_digest = inspect_specification(
                root,
                args.specification,
                expected_filename=manifest.source_filename,
            )
            if source_digest != manifest.source_spec_sha256:
                raise ContractError("Specification does not match the manifest.")
            git = GitInspector(
                SubprocessRunner(timeout_seconds=5, output_limit=1_048_576)
            ).inspect(root)
            _require_specification_candidate(root, args.specification, git)
            candidate_identity = _candidate_identity(
                source_digest,
                git,
            )
            result = UiValidationService().evaluate(
                manifest=manifest,
                candidate=candidate_identity,
                validation=load_ui_validation(args.validation),
                root=root,
            )
        except (ContractError, OSError):
            print("ERROR: UI validation input is invalid.", file=sys.stderr)
            return 2
        _emit(result.to_dict(), as_json=args.json)
        return 0 if result.passed else 2

    if args.command == "audit" and args.audit_command == "release-candidate":
        try:
            root = _exact_working_root(args.root)
            baseline = load_baseline(args.baseline)
            ledger = load_evidence_ledger(args.ledger)
            review = load_independent_review(args.review)
            approvals = tuple(
                FindingAcceptanceLoader().load(path) for path in args.approval
            )
            manifest = load_manifest_ui(args.manifest)
            source_digest = inspect_specification(
                root,
                args.specification,
                expected_filename=baseline.source.filename,
            )
            if (
                source_digest != baseline.source.sha256
                or source_digest != manifest.source_spec_sha256
            ):
                raise ContractError("Specification identity is inconsistent.")
            git = GitInspector(
                SubprocessRunner(timeout_seconds=5, output_limit=1_048_576)
            ).inspect(root)
            _require_specification_candidate(root, args.specification, git)
            candidate_identity = _candidate_identity(source_digest, git)
            g2 = ImplementationEvidenceGateService().evaluate(
                baseline,
                ledger,
                candidate=candidate_identity,
                root=root,
            )
            g3 = IndependentReviewGateService().evaluate(
                review,
                baseline_id=baseline.baseline_id,
                candidate=candidate_identity,
                changed_paths=git.changed_paths,
                candidate_paths=git.publication_paths,
                approvals=approvals,
            )
            ui_result = UiValidationService().evaluate(
                manifest=manifest,
                candidate=candidate_identity,
                validation=load_ui_validation(args.ui_validation),
                root=root,
            )
            result = ReleaseCandidateGateService().evaluate(
                root=root,
                baseline=baseline,
                ledger=ledger,
                review=review,
                candidate=load_release_candidate(args.candidate),
                g2=g2,
                g3=g3,
                ui=ui_result,
                git=git,
            )
        except (BaselineContractError, ContractError, OSError):
            print("ERROR: release-candidate audit input is invalid.", file=sys.stderr)
            return 2
        _emit(result.to_dict(), as_json=args.json)
        return 0 if result.passed else 2

    if args.command == "handoff":
        try:
            root = _exact_working_root(args.root)
            baseline = load_baseline(args.baseline)
            ledger = load_evidence_ledger(args.ledger)
            source_digest = inspect_specification(
                root,
                args.specification,
                expected_filename=baseline.source.filename,
            )
            if source_digest != baseline.source.sha256:
                raise ContractError("Handoff specification does not match the baseline.")
            git = GitInspector(
                SubprocessRunner(timeout_seconds=5, output_limit=1_048_576)
            ).inspect(root)
            _require_specification_candidate(root, args.specification, git)
            candidate_identity = _candidate_identity(source_digest, git)
            if args.handoff_command == "create":
                output_path = _m3_state_path(
                    root,
                    args.output,
                    require_existing=False,
                )
                generated = HandoffService().create(
                    args.input,
                    baseline_id=baseline.baseline_id,
                    candidate=candidate_identity,
                    git=git,
                    ledger=ledger,
                )
                _write_new_file(output_path, _json_text(generated.to_dict()))
                if args.json:
                    print(_json_text(generated.to_dict()), end="")
                else:
                    print(f"Automated handoff created: {args.output.name}")
                return 0
            stored_handoff = load_automated_handoff(
                _m3_state_path(root, args.handoff, require_existing=True)
            )
            validate_handoff_resume(
                stored_handoff,
                baseline_id=baseline.baseline_id,
                candidate=candidate_identity,
                git=git,
                ledger=ledger,
            )
        except (BaselineContractError, ContractError, OSError):
            print("ERROR: automated handoff is invalid.", file=sys.stderr)
            return 2
        _emit(stored_handoff.to_dict(), as_json=args.json)
        return 0

    if args.command == "agents":
        try:
            agent_registry = load_agent_registry(args.registry)
            if args.agent_command in {"validate", "plan"}:
                tool_registry = load_tool_registry(args.tools)
                validate_agent_tool_references(agent_registry, tool_registry)
            if args.agent_command == "validate":
                _emit(
                    {
                        "schema_version": agent_registry.schema_version,
                        "agents": len(agent_registry.agents),
                        "tool_references": "valid",
                    },
                    as_json=args.json,
                )
                return 0
            if args.agent_command == "plan":
                request = load_orchestration_request(args.request)
                worktree = (
                    None
                    if args.worktree_plan is None
                    else load_worktree_plan(args.worktree_plan)
                )
                orchestration_plan = AgentOrchestrator().plan(
                    agent_registry,
                    request,
                    worktree_plan=worktree,
                )
                _emit(orchestration_plan.to_dict(), as_json=args.json)
                return 0
            agent_result = load_agent_result(args.result, agent_registry)
            _emit(
                {
                    "agent_id": agent_result.agent_id,
                    "role_id": agent_result.role_id,
                    "status": agent_result.status.value,
                    "findings": len(agent_result.findings),
                },
                as_json=args.json,
            )
            return 0
        except (OrchestrationContractError, ToolContractError):
            print("ERROR: agent orchestration input is invalid.", file=sys.stderr)
            return 2

    if args.command == "skills" and args.skill_command == "validate":
        try:
            skill_records = validate_skills(
                args.root,
                selected=tuple(args.select_skill),
            )
            templates = load_template_registry(args.templates)
            template_records = evaluate_templates(
                templates,
                framework_version=args.framework_version,
                available_dependencies=tuple(args.available),
                active_conditions=tuple(args.condition),
                selected=tuple(args.select_template),
            )
        except SkillContractError:
            print("ERROR: Skill or template lifecycle is invalid.", file=sys.stderr)
            return 2
        _emit(
            {
                "skills": [item.to_dict() for item in skill_records],
                "templates": [item.to_dict() for item in template_records],
            },
            as_json=args.json,
        )
        return 0

    if args.command == "tools":
        try:
            registry = load_tool_registry(args.registry)
            if args.tool_command == "validate":
                _emit(
                    {
                        "schema_version": registry.schema_version,
                        "tools": [item.name for item in registry.tools],
                    },
                    as_json=args.json,
                )
                return 0
            tool = registry.by_name(args.name)
            if tool is None:
                raise ToolContractError("Unknown tool.")
            observation = ToolService(
                SubprocessRunner(timeout_seconds=5, output_limit=4_096),
                consumption_store=ExecutionApprovalConsumptionStore.for_registry(
                    args.registry
                ),
            ).check(
                tool,
                approvals=tuple(
                    ExecutionApprovalLoader().load(path)
                    for path in args.approval
                ),
            )
        except ToolContractError:
            print("ERROR: Tool Registry or tool name is invalid.", file=sys.stderr)
            return 2
        _emit(observation.to_dict(), as_json=args.json)
        return (
            0
            if observation.status is ToolObservationStatus.AVAILABLE
            or (
                tool.optional
                and observation.status
                in {
                    ToolObservationStatus.UNAVAILABLE,
                    ToolObservationStatus.NOT_CHECKED,
                }
            )
            else 2
        )

    if args.command == "checkpoint":
        try:
            stored = CheckpointStore(Path.cwd()).load(args.file)
            if args.checkpoint_command == "resume":
                validate_resume(
                    stored,
                    ExecutionContext(
                        plan_version=args.plan_version,
                        specification_digest=args.specification_digest,
                        git_head=args.git_head,
                        worktree_digest=args.worktree_digest,
                    ),
                )
            _emit(stored.to_dict(), as_json=args.json)
            return 0
        except CheckpointContractError:
            print("ERROR: execution checkpoint is invalid.", file=sys.stderr)
            return 2

    if args.command == "eval":
        try:
            evaluation_result = EvaluationService().evaluate(args.suite)
            if args.evaluation_command == "validate" and args.result is not None:
                EvaluationService().validate_recorded_result(
                    args.result,
                    evaluation_result,
                )
        except (ContractError, OSError):
            print("ERROR: evaluation contract is invalid.", file=sys.stderr)
            return 2
        if args.evaluation_command == "compare":
            _emit(evaluation_result.to_dict(), as_json=args.json)
        else:
            _emit(
                {
                    "schema_version": evaluation_result.schema_version,
                    "suite_id": evaluation_result.suite_id,
                    "projects": len(evaluation_result.comparisons),
                    "hard_blockers": len(evaluation_result.hard_blockers),
                    "aggregate_score": None,
                },
                as_json=args.json,
            )
        return 0

    if args.command == "schema" and args.schema_command == "migrate":
        try:
            root = _exact_working_root(args.root)
            migration_result = MigrationService().migrate(
                root=root,
                contract=args.contract,
                source=args.input,
                output=args.output,
                approval=args.approval,
                tool_registry=args.tool_registry,
                source_version=args.from_version,
                target_version=args.to_version,
            )
        except (ContractError, OSError):
            print("ERROR: schema migration is invalid.", file=sys.stderr)
            return 2
        _emit(migration_result.to_dict(), as_json=args.json)
        return 0

    raise AssertionError("argparse accepted an unknown command")


def _emit(payload: Mapping[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def _exact_working_root(path: Path) -> Path:
    root = path.resolve(strict=True)
    if root != Path.cwd().resolve(strict=True):
        raise ContractError("M3 root must be the working directory.")
    return root


def _m3_state_path(
    root: Path,
    path: Path,
    *,
    require_existing: bool,
) -> Path:
    """Require an exact regular path below repository-local ignored M3 state."""

    state = root / ".sdaqf"
    if (
        not state.is_dir()
        or state.is_symlink()
        or is_reparse_point(state)
    ):
        raise ContractError("M3 state directory must be regular and repository-local.")
    candidate = path if path.is_absolute() else root / path
    try:
        resolved = candidate.resolve(strict=require_existing)
        resolved_state = state.resolve(strict=True)
    except OSError as exc:
        raise ContractError("M3 state path could not be resolved.") from exc
    if not resolved.is_relative_to(resolved_state):
        raise ContractError("Mutable M3 state must stay inside .sdaqf.")
    current = resolved_state
    for part in resolved.relative_to(resolved_state).parts[:-1]:
        current = current / part
        if not current.is_dir() or current.is_symlink() or is_reparse_point(current):
            raise ContractError("M3 state parents must be regular directories.")
    if require_existing and (
        not resolved.is_file()
        or resolved.is_symlink()
        or is_reparse_point(resolved)
    ):
        raise ContractError("M3 state input must be a regular file.")
    return resolved


def _candidate_identity(
    source_spec_sha256: str,
    git: GitObservation,
) -> CandidateIdentity:
    return CandidateIdentity(
        source_spec_sha256=source_spec_sha256,
        git_head=git.head,
        repository_digest=git.repository_digest,
    )


def _require_specification_candidate(
    root: Path,
    specification: Path,
    git: GitObservation,
) -> None:
    """Require the observed specification to be in Git's publication set."""

    try:
        relative = specification.resolve(strict=True).relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise ContractError("Specification is outside the publication candidate.") from exc
    if relative not in git.publication_paths:
        raise ContractError("Specification is absent from the Git publication candidate.")


def _write_new_file(path: Path, content: str) -> None:
    if not path.resolve(strict=False).is_relative_to(Path.cwd().resolve()):
        raise PermissionError("Output must stay within the working directory.")
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Refusing to overwrite {path.name}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            errors="strict",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _json_text(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
