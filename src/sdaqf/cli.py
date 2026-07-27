"""Command-line interface for the M0 vertical slice."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from sdaqf.adapters.process import SubprocessRunner
from sdaqf.application.doctor import DoctorService
from sdaqf.application.goals import GoalTemplateService
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

    validate = subparsers.add_parser("validate", help="Validate an M0 sample project.")
    validate.add_argument("project", type=Path, help="Sample project directory.")
    validate.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    status = subparsers.add_parser("status", help="Show an M0 project status.")
    status.add_argument("project", type=Path, help="Sample project directory.")
    status.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    goal = subparsers.add_parser("goal-template", help="Render a complete Codex Goal prompt.")
    goal.add_argument("milestone", help="Milestone identifier, such as M1.")
    goal.add_argument("--output", type=Path, help="Optional new output file.")

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
    with path.open("x", encoding="utf-8", errors="strict") as stream:
        stream.write(content)
