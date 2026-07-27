"""Command-line interface for the M0 foundation and M1 requirements MVP."""

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
from sdaqf.application.comparison import BaselineComparator, BaselineDiff
from sdaqf.application.doctor import DoctorService
from sdaqf.application.goals import GoalTemplateService
from sdaqf.application.planning import PlanningService, PromptMode, PromptService
from sdaqf.application.requirements import SpecificationError, SpecificationIngestor
from sdaqf.application.requirements_gate import RequirementsGateService
from sdaqf.application.status import StatusService
from sdaqf.application.validation import ProjectValidator
from sdaqf.application.workspace import WorkspaceInitializer


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

    raise AssertionError("argparse accepted an unknown command")


def _emit(payload: Mapping[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


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
