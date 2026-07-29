"""Run the exact offline M0 through M3 CLI smoke contract."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.adapters.process import SubprocessRunner
from sdaqf.application.release_qa import GitInspector, source_target_for
from sdaqf.application.workspace import is_reparse_point
from sdaqf.cli import main


def _run(label: str, args: Sequence[str], *, json_output: bool = False) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = main(args)
        except SystemExit as exc:
            result = exc.code if isinstance(exc.code, int) else 1
    if result != 0:
        raise RuntimeError(
            f"{label} failed with exit {result}: "
            f"{stderr.getvalue().strip() or stdout.getvalue()[:2_000].strip()}"
        )
    if stderr.getvalue():
        raise RuntimeError(f"{label} emitted unexpected stderr.")
    if json_output:
        json.loads(stdout.getvalue())


def _run_expected_gate_failure(
    label: str,
    args: Sequence[str],
    *,
    expected_blockers: set[str],
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main(args)
    if result == 0:
        raise RuntimeError(f"{label} unexpectedly passed.")
    if stderr.getvalue():
        raise RuntimeError(f"{label} emitted unexpected stderr.")
    payload = json.loads(stdout.getvalue())
    if payload.get("passed") is not False:
        raise RuntimeError(f"{label} did not return a failed Gate.")
    blockers = set(payload.get("hard_blockers", []))
    if not expected_blockers <= blockers:
        raise RuntimeError(f"{label} did not return the expected blockers.")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _artifact(path: str, content: bytes) -> dict[str, str]:
    return {
        "path": path,
        "sha256": hashlib.sha256(content).hexdigest().upper(),
    }


def _git(root: Path, *arguments: str) -> None:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("Git is unavailable for the temporary fixture.")
    safety = root / ".sdaqf" / "git-safety"
    safety.mkdir(parents=True, exist_ok=True)
    result = SubprocessRunner(timeout_seconds=10, output_limit=16 * 1024).run(
        [
            str(Path(executable).resolve()),
            "-c",
            f"init.templateDir={safety}",
            "-c",
            f"core.hooksPath={safety}",
            "-c",
            f"core.attributesFile={safety / 'attributes'}",
            "-c",
            f"core.excludesFile={safety / 'excludes'}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "tag.gpgSign=false",
            "-C",
            str(root.resolve()),
            *arguments,
        ]
    )
    if result.returncode != 0 or result.stdout_truncated or result.stderr_truncated:
        raise RuntimeError("temporary Git fixture command failed.")


def _prepare_smoke_state(root: Path) -> Path:
    """Create or validate the regular repository-local smoke state directory."""

    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("smoke repository root is invalid.") from exc
    if root.is_symlink() or is_reparse_point(root) or not resolved_root.is_dir():
        raise RuntimeError("smoke repository root must be a regular directory.")
    state = root / ".sdaqf"
    if state.is_symlink() or is_reparse_point(state):
        raise RuntimeError("smoke state must not be a link or reparse point.")
    with contextlib.suppress(FileExistsError):
        state.mkdir(exist_ok=False)
    try:
        resolved_state = state.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("smoke state is invalid.") from exc
    if (
        not state.is_dir()
        or state.is_symlink()
        or is_reparse_point(state)
        or resolved_state.parent != resolved_root
    ):
        raise RuntimeError("smoke state must be a regular repository-local directory.")
    return state


def _create_m3_smoke_specification(root: Path) -> Path:
    """Exclusively create one randomized, owned publication-candidate source."""

    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("M3 smoke specification root is invalid.") from exc
    if root.is_symlink() or is_reparse_point(root) or not resolved_root.is_dir():
        raise RuntimeError("M3 smoke specification root must be regular.")
    descriptor = -1
    path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix="m3-smoke-specification-",
            suffix=".md",
            dir=root,
        )
        path = Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = -1
            stream.write(
                "# M3 Smoke\n\n## Functional requirements\n\n"
                "- `FR-SMOKE-001`: The command must validate input.\n"
            )
        if (
            path.parent.resolve(strict=True) != resolved_root
            or path.is_symlink()
            or is_reparse_point(path)
            or not path.is_file()
        ):
            raise RuntimeError("M3 smoke specification is not a regular owned file.")
        return path
    except (OSError, RuntimeError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if path is not None and path.parent == root and not path.is_dir():
            path.unlink(missing_ok=True)
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError("M3 smoke specification could not be created.") from exc


def _record_install_trace(
    root: Path,
    *,
    command: list[str],
    execution_module: str,
    target_relative: str,
    git_head: str,
    repository_digest: str,
    publication_paths: tuple[str, ...],
) -> dict[str, object]:
    target = root.joinpath(*Path(target_relative).parts)
    source_relative = source_target_for(target_relative)
    source = root.joinpath(*Path(source_relative).parts)
    target_preexisting = target.exists()
    source_preexisting = source.exists()
    try:
        resolved_root = root.resolve(strict=True)
        resolved_parent = target.parent.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("install target parent is invalid.") from exc
    if (
        target_preexisting
        or source_preexisting
        or target.is_symlink()
        or is_reparse_point(target)
        or source.is_symlink()
        or is_reparse_point(source)
        or not resolved_parent.is_relative_to(resolved_root)
        or resolved_parent.is_symlink()
        or is_reparse_point(resolved_parent)
        or command[-2] != target_relative
        or command[-1] != source_relative
    ):
        raise RuntimeError("install paths are not fresh owned smoke paths.")
    _materialize_publication_source(
        root,
        source_relative=source_relative,
        publication_paths=publication_paths,
    )
    if Path.cwd().resolve() != resolved_root:
        raise RuntimeError("installation smoke must run from its exact repository root.")
    started = datetime.now(UTC)
    result = SubprocessRunner(
        timeout_seconds=90,
        output_limit=64 * 1024,
    ).run([sys.executable, *command[1:]])
    finished = datetime.now(UTC)
    if (
        result.returncode != 0
        or result.stdout_truncated
        or result.stderr_truncated
        or not target.is_dir()
    ):
        raise RuntimeError("bounded offline installation smoke failed.")
    _clean_materialization_outputs(source, publication_paths)
    execution_command = [
        "python",
        "-I",
        "-S",
        "-c",
        (
            "import importlib.util,pathlib,runpy,sys;"
            f"t=pathlib.Path('{target_relative}').resolve();"
            "sys.path.insert(0,str(t));"
            f"s=importlib.util.find_spec('{execution_module}');"
            "assert s is not None and s.origin is not None "
            "and pathlib.Path(s.origin).resolve().is_relative_to(t);"
            f"sys.argv=['{execution_module}','--help'];"
            f"runpy.run_module('{execution_module}',run_name='__main__')"
        ),
    ]
    execution = SubprocessRunner(
        timeout_seconds=60,
        output_limit=64 * 1024,
    ).run([sys.executable, *execution_command[1:]])
    if (
        execution.returncode != 0
        or execution.stdout_truncated
        or execution.stderr_truncated
    ):
        raise RuntimeError("installed-module execution smoke failed.")
    return {
        "schema_version": "1.0",
        "trace_type": "bounded-subprocess-v1",
        "command": command,
        "returncode": result.returncode,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_ms": result.duration_ms,
        "executable_sha256": hashlib.sha256(
            Path(sys.executable).read_bytes()
        ).hexdigest().upper(),
        "python_version": platform.python_version(),
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest().upper(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest().upper(),
        "network_mode": "offline",
        "target": target_relative,
        "target_preexisting": target_preexisting,
        "source": source_relative,
        "source_preexisting": source_preexisting,
        "source_repository_digest": repository_digest,
        "execution_command": execution_command,
        "execution_returncode": execution.returncode,
        "execution_duration_ms": execution.duration_ms,
        "execution_stdout_sha256": hashlib.sha256(
            execution.stdout.encode()
        ).hexdigest().upper(),
        "execution_stderr_sha256": hashlib.sha256(
            execution.stderr.encode()
        ).hexdigest().upper(),
        "git_head": git_head,
        "repository_digest": repository_digest,
    }


def _materialize_publication_source(
    root: Path,
    *,
    source_relative: str,
    publication_paths: tuple[str, ...],
) -> Path:
    """Copy only regular Git publication inputs into one fresh owned tree."""

    source_root = root.joinpath(*Path(source_relative).parts)
    if (
        not publication_paths
        or tuple(sorted(set(publication_paths))) != publication_paths
        or source_root.exists()
        or source_root.is_symlink()
        or is_reparse_point(source_root)
    ):
        raise RuntimeError("materialized source must be fresh and publication-bound.")
    try:
        resolved_root = root.resolve(strict=True)
        resolved_parent = source_root.parent.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("materialized source parent is invalid.") from exc
    if (
        not resolved_parent.is_relative_to(resolved_root)
        or resolved_parent.is_symlink()
        or is_reparse_point(resolved_parent)
    ):
        raise RuntimeError("materialized source parent is outside the repository.")
    source_root.mkdir()
    try:
        for relative in publication_paths:
            parts = Path(relative).parts
            if (
                not parts
                or Path(relative).is_absolute()
                or any(part in {"", ".", ".."} for part in parts)
            ):
                raise RuntimeError("Git returned an unsafe publication path.")
            original = root.joinpath(*parts)
            current = root
            for part in parts:
                current = current / part
                if current.is_symlink() or is_reparse_point(current):
                    raise RuntimeError("Publication source contains a link.")
            if not original.is_file() or original.stat().st_size > 1_000_000:
                raise RuntimeError("Publication source is missing or oversized.")
            destination = source_root.joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
    except (OSError, RuntimeError):
        shutil.rmtree(source_root)
        raise
    return source_root


def _clean_materialization_outputs(
    source_root: Path,
    publication_paths: tuple[str, ...],
) -> None:
    """Remove only generated outputs from the owned source snapshot."""

    if (
        not source_root.is_dir()
        or source_root.is_symlink()
        or is_reparse_point(source_root)
    ):
        raise RuntimeError("materialized source changed identity during installation.")
    generated: list[Path] = []
    for path in source_root.rglob("*"):
        if path.is_symlink() or is_reparse_point(path):
            raise RuntimeError("installation created a link in materialized source.")
        if not path.is_dir():
            continue
        relative = path.relative_to(source_root).as_posix()
        if (
            path.name in {".eggs", "__pycache__", "build", "dist"}
            or path.name.casefold().endswith(".egg-info")
        ) and not any(
            item == relative or item.startswith(f"{relative}/")
            for item in publication_paths
        ):
            generated.append(path)
    for path in sorted(generated, key=lambda item: len(item.parts), reverse=True):
        if path.exists():
            shutil.rmtree(path)


def _run_positive_g4_smoke(parent: Path) -> None:
    release_root = parent / "clean-release"
    release_root.mkdir()
    docs = release_root / "docs"
    docs.mkdir()
    for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md"):
        (release_root / name).write_text(f"# {name}\n", encoding="utf-8")
    (release_root / "README.md").write_text(
        "# Smoke release\n\n## Installation\n\nOffline.\n\n"
        "## Known limitations\n\nFixture only.\n",
        encoding="utf-8",
    )
    (docs / "release-contract.md").write_text(
        "# Release Contract\n",
        encoding="utf-8",
    )
    (docs / "dependencies.md").write_text(
        "# Dependency license\n\npytest license: MIT\n",
        encoding="utf-8",
    )
    (release_root / "pyproject.toml").write_text(
        "[build-system]\n"
        "requires = [\"setuptools==83.0.0\"]\n"
        "build-backend = \"setuptools.build_meta\"\n\n"
        "[project]\n"
        "name = \"smoke\"\n"
        "version = \"0.0.0\"\n"
        "dependencies = []\n",
        encoding="utf-8",
    )
    package = release_root / "smoke"
    package.mkdir()
    (package / "__init__.py").write_text('"""Smoke package."""\n', encoding="utf-8")
    (package / "__main__.py").write_text(
        '"""Installed smoke entry point."""\n',
        encoding="utf-8",
    )
    specification = release_root / "spec.md"
    specification.write_text(
        "# Release Smoke\n\n## Functional requirements\n\n"
        "- `FR-SMOKE-001`: The command must validate input.\n",
        encoding="utf-8",
    )
    (release_root / "requirements-dev.lock").write_text(
        "pytest==1\n",
        encoding="utf-8",
    )
    (release_root / ".gitignore").write_text(
        ".sdaqf/\nbuild/\ndist/\n*.egg-info/\n/setup.py\n/pip.py\n",
        encoding="utf-8",
    )
    (release_root / "setup.py").write_text(
        "raise SystemExit('ignored build input executed')\n",
        encoding="utf-8",
    )
    (release_root / "pip.py").write_text(
        "raise SystemExit('ignored pip shadow executed')\n",
        encoding="utf-8",
    )
    _git(release_root, "init", "-b", "main")
    _git(release_root, "add", ".")
    _git(
        release_root,
        "-c",
        "user.name=Smoke",
        "-c",
        "user.email=sdaqf-smoke.invalid",
        "commit",
        "-m",
        "fixture",
    )

    state = _prepare_smoke_state(release_root)
    baseline_path = state / "baseline.json"
    previous = Path.cwd()
    os.chdir(release_root)
    try:
        _run(
            "clean G4 baseline ingest",
            [
                "ingest",
                str(specification),
                "--output",
                str(baseline_path),
                "--json",
            ],
            json_output=True,
        )
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        criterion_id = baseline["requirements"][0]["acceptance_criteria"][0]["id"]
        git = GitInspector(
            SubprocessRunner(timeout_seconds=5, output_limit=1_048_576)
        ).inspect(release_root)
        identity = {
            "source_spec_sha256": baseline["source"]["sha256"],
            "git_head": git.head,
            "repository_digest": git.repository_digest,
        }
        install_command = [
            "python",
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--no-index",
            "--no-build-isolation",
            "--no-deps",
            "--target",
            ".sdaqf/install-target",
            source_target_for(".sdaqf/install-target"),
        ]
        artifacts = {
            "diff.txt": b"diff review passed\n",
            "conformance.txt": b"conformance review passed\n",
        }
        for name, content in artifacts.items():
            (state / name).write_bytes(content)
        trace_path = state / "install-trace.json"
        _write_json(
            trace_path,
            _record_install_trace(
                release_root,
                command=install_command,
                execution_module="smoke",
                target_relative=".sdaqf/install-target",
                git_head=git.head,
                repository_digest=git.repository_digest,
                publication_paths=git.publication_paths,
            ),
        )
        claim_id = "CLM-FR-SMOKE-001"
        ledger_path = state / "ledger.json"
        evidence_common = {
            "claim_ids": [claim_id],
            "environment": {"os": "smoke", "python": "3.12"},
            "commit": git.head,
            "repository_digest": git.repository_digest,
        }
        _write_json(
            ledger_path,
            {
                "schema_version": "1.0",
                "baseline_id": baseline["baseline_id"],
                "source_spec_sha256": baseline["source"]["sha256"],
                "git_head": git.head,
                "repository_digest": git.repository_digest,
                "claims": [
                    {
                        "claim_id": claim_id,
                        "statement": "The release smoke requirement is verified.",
                        "requirement_ids": ["FR-SMOKE-001"],
                        "acceptance_criteria": [criterion_id],
                        "state": "verified",
                        "criticality": "must",
                        "confidence": "A",
                    }
                ],
                "evidence": [
                    {
                        **evidence_common,
                        "evidence_id": "EV-DIFF-SMOKE",
                        "type": "SOURCE_REVIEW",
                        "status": "PASS",
                        "command": ["git", "diff", "--check"],
                        "artifacts": [
                            _artifact(".sdaqf/diff.txt", artifacts["diff.txt"])
                        ],
                        "recorded_at": "2026-07-29T00:00:00+00:00",
                    },
                    {
                        **evidence_common,
                        "evidence_id": "EV-INSTALL-SMOKE",
                        "type": "TEST",
                        "status": "PASS",
                        "command": install_command,
                        "artifacts": [
                            _artifact(
                                ".sdaqf/install-trace.json",
                                trace_path.read_bytes(),
                            )
                        ],
                        "recorded_at": "2026-07-29T00:01:00+00:00",
                    },
                    {
                        **evidence_common,
                        "evidence_id": "EV-REVIEW-SMOKE",
                        "type": "MANUAL_REVIEW",
                        "status": "PASS",
                        "command": ["python", "-m", "sdaqf", "gate", "implementation"],
                        "artifacts": [
                            _artifact(
                                ".sdaqf/conformance.txt",
                                artifacts["conformance.txt"],
                            )
                        ],
                        "recorded_at": "2026-07-29T00:02:00+00:00",
                    },
                ],
                "diff_review_evidence_id": "EV-DIFF-SMOKE",
            },
        )
        review_path = state / "review.json"
        _write_json(
            review_path,
            {
                "schema_version": "1.0",
                "review_id": "REV-SMOKE-0001",
                "baseline_id": baseline["baseline_id"],
                "candidate": identity,
                "reviewed_at": "2026-07-29T00:03:00+00:00",
                "reviewer_id": "AGT-REVIEWER-1",
                "reviewed_agent_ids": ["AGT-IMPLEMENTER-1"],
                "status": "completed",
                "read_only": True,
                "areas": ["regression", "security", "maintainability"],
                "findings": [],
                "reviewed_paths": list(git.changed_paths or git.publication_paths),
                "changed_paths": [],
            },
        )
        manifest_path = state / "manifest.json"
        _write_json(
            manifest_path,
            {
                "schema_version": "1.0",
                "project_id": "clean-release-smoke",
                "title": "Clean Release Smoke",
                "release_level": "prototype",
                "source_spec": {
                    "filename": "spec.md",
                    "sha256": baseline["source"]["sha256"],
                    "imported_at": "2026-07-29T00:00:00+00:00",
                },
                "platforms": {"required": ["windows"], "optional": []},
                "ui": {"present": False},
                "network_policy": "default-deny",
                "api_required": False,
            },
        )
        ui_path = state / "ui.json"
        _write_json(
            ui_path,
            {
                "schema_version": "1.0",
                "project_id": "clean-release-smoke",
                "ui_present": False,
                "candidate": identity,
                "design_brief": None,
                "observations": [],
            },
        )
        release_path = state / "release.json"
        _write_json(
            release_path,
            {
                "schema_version": "1.0",
                "install_evidence_id": "EV-INSTALL-SMOKE",
                "execution_module": "smoke",
                "install_target": ".sdaqf/install-target",
                "rollback_guidance": (
                    "Remove only the owned .sdaqf/install-target and "
                    ".sdaqf/install-target-source directories."
                ),
                "documentation_paths": [
                    "CHANGELOG.md",
                    "CONTRIBUTING.md",
                    "README.md",
                    "SECURITY.md",
                    "docs/release-contract.md",
                ],
                "license_status": "not-selected",
            },
        )
        g4_args = [
            "audit",
            "release-candidate",
            str(release_path),
            "--root",
            ".",
            "--baseline",
            str(baseline_path),
            "--ledger",
            str(ledger_path),
            "--review",
            str(review_path),
            "--manifest",
            str(manifest_path),
            "--ui-validation",
            str(ui_path),
            "--specification",
            str(specification),
            "--json",
        ]
        _run("Gate G4 clean positive", g4_args, json_output=True)
        (release_root / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        _run_expected_gate_failure(
            "Gate G4 dirty negative",
            g4_args,
            expected_blockers={"G4-GIT"},
        )
    finally:
        os.chdir(previous)


def main_smoke() -> int:
    """Execute every preserved and primary CLI path in one temporary directory."""

    root = Path(__file__).resolve().parents[1]
    examples = root / "examples"
    m2 = examples / "m2-orchestration"
    previous = Path.cwd()
    smoke_state = _prepare_smoke_state(root)
    with tempfile.TemporaryDirectory(prefix="cli-smoke-", dir=smoke_state) as raw_temp:
        temporary = Path(raw_temp)
        baseline = temporary / "baseline.json"
        m3_spec: Path | None = None
        os.chdir(root)
        try:
            _run("help", ["--help"])
            _run(
                "doctor",
                ["doctor", "--current-session-active", "--json"],
                json_output=True,
            )
            _run(
                "init dry run",
                ["init", str(temporary / "project"), "--dry-run", "--json"],
                json_output=True,
            )
            _run(
                "validate",
                ["validate", str(examples / "sample-project"), "--json"],
                json_output=True,
            )
            _run(
                "status",
                ["status", str(examples / "sample-project"), "--json"],
                json_output=True,
            )
            _run("goal template", ["goal-template", "M1"])
            _run(
                "canonical ingest",
                [
                    "ingest",
                    str(root / "docs" / "specification.md"),
                    "--output",
                    str(baseline),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "compare",
                ["compare", str(baseline), str(baseline), "--json"],
                json_output=True,
            )
            for command, filename in (
                ("roadmap", "roadmap.md"),
                ("exec-plan", "exec-plan.md"),
            ):
                _run(
                    command,
                    [
                        command,
                        str(baseline),
                        "M1",
                        "--output",
                        str(temporary / filename),
                    ],
                )
            for command, filename in (
                ("goal", "goal.md"),
                ("prompt", "prompt.md"),
            ):
                _run(
                    command,
                    [
                        command,
                        str(baseline),
                        "M1",
                        "--output",
                        str(temporary / filename),
                        "--json",
                    ],
                    json_output=True,
                )
            _run(
                "Gate G1",
                ["gate", "requirements", str(baseline), "--json"],
                json_output=True,
            )
            agent_registry = m2 / "agent-registry.json"
            tool_registry = m2 / "tool-registry.json"
            _run(
                "Agent Registry",
                [
                    "agents",
                    "validate",
                    str(agent_registry),
                    "--tools",
                    str(tool_registry),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "agent fallback plan",
                [
                    "agents",
                    "plan",
                    str(m2 / "orchestration-request.json"),
                    "--registry",
                    str(agent_registry),
                    "--tools",
                    str(tool_registry),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "isolated write plan",
                [
                    "agents",
                    "plan",
                    str(m2 / "write-request.json"),
                    "--registry",
                    str(agent_registry),
                    "--tools",
                    str(tool_registry),
                    "--worktree-plan",
                    str(m2 / "worktree-plan.json"),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "structured agent result",
                [
                    "agents",
                    "validate-result",
                    str(m2 / "reviewer-result.json"),
                    "--registry",
                    str(agent_registry),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "Skill and template lifecycle",
                [
                    "skills",
                    "validate",
                    str(root / ".agents" / "skills"),
                    "--templates",
                    str(m2 / "template-registry.json"),
                    "--framework-version",
                    "0.1.0",
                    "--available",
                    "independent-review",
                    "--select-skill",
                    "independent-review",
                    "--select-template",
                    "m2-agent-result",
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "Tool Registry",
                ["tools", "validate", str(tool_registry), "--json"],
                json_output=True,
            )
            _run(
                "registered Git probe",
                [
                    "tools",
                    "check",
                    str(tool_registry),
                    "--name",
                    "git",
                    "--json",
                ],
                json_output=True,
            )
            checkpoint = m2 / "execution-checkpoint.json"
            _run(
                "checkpoint",
                ["checkpoint", "validate", str(checkpoint), "--json"],
                json_output=True,
            )
            _run(
                "checkpoint resume",
                [
                    "checkpoint",
                    "resume",
                    str(checkpoint),
                    "--plan-version",
                    "1.0",
                    "--specification-digest",
                    "89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5",
                    "--git-head",
                    "eff9e3abfa6aff3e22d71b23140e838cd222832a",
                    "--worktree-digest",
                    "A" * 64,
                    "--json",
                ],
                json_output=True,
            )
            m3_spec = _create_m3_smoke_specification(root)
            m3_baseline = temporary / "m3-baseline.json"
            _run(
                "M3 baseline ingest",
                [
                    "ingest",
                    str(m3_spec),
                    "--output",
                    str(m3_baseline),
                    "--json",
                ],
                json_output=True,
            )
            baseline_payload = json.loads(m3_baseline.read_text(encoding="utf-8"))
            requirement = baseline_payload["requirements"][0]
            criterion_id = requirement["acceptance_criteria"][0]["id"]
            m3_ledger = temporary / "m3-ledger.json"
            git = GitInspector(
                SubprocessRunner(timeout_seconds=5, output_limit=1_048_576)
            ).inspect(root)
            head = git.head
            repo_digest = git.repository_digest
            claim_id = "CLM-FR-SMOKE-001"
            relative_temp = temporary.relative_to(root).as_posix()
            diff_content = b"diff review passed\n"
            conformance_content = b"conformance review passed\n"
            install_command = [
                "python",
                "-I",
                "-m",
                "pip",
                "--isolated",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "--no-index",
                "--no-build-isolation",
                "--no-deps",
                "--target",
                f"{relative_temp}/install-target",
                source_target_for(f"{relative_temp}/install-target"),
            ]
            diff_path = temporary / "diff.txt"
            conformance_path = temporary / "conformance.txt"
            trace_path = temporary / "install-trace.json"
            diff_path.write_bytes(diff_content)
            conformance_path.write_bytes(conformance_content)
            _write_json(
                trace_path,
                _record_install_trace(
                    root,
                    command=install_command,
                    execution_module="sdaqf",
                    target_relative=f"{relative_temp}/install-target",
                    git_head=head,
                    repository_digest=repo_digest,
                    publication_paths=git.publication_paths,
                ),
            )
            trace_content = trace_path.read_bytes()
            _write_json(
                m3_ledger,
                {
                    "schema_version": "1.0",
                    "baseline_id": baseline_payload["baseline_id"],
                    "source_spec_sha256": baseline_payload["source"]["sha256"],
                    "git_head": head,
                    "repository_digest": repo_digest,
                    "claims": [
                        {
                            "claim_id": claim_id,
                            "statement": "The smoke requirement is verified.",
                            "requirement_ids": ["FR-SMOKE-001"],
                            "acceptance_criteria": [criterion_id],
                            "state": "verified",
                            "criticality": "must",
                            "confidence": "A",
                        }
                    ],
                    "evidence": [
                        {
                            "evidence_id": "EV-DIFF-SMOKE",
                            "claim_ids": [claim_id],
                            "type": "SOURCE_REVIEW",
                            "status": "PASS",
                            "command": ["git", "diff", "--check"],
                            "environment": {"os": "smoke"},
                            "commit": head,
                            "repository_digest": repo_digest,
                            "artifacts": [
                                _artifact(f"{relative_temp}/diff.txt", diff_content)
                            ],
                            "recorded_at": "2026-07-29T00:00:00+00:00",
                        },
                        {
                            "evidence_id": "EV-INSTALL-SMOKE",
                            "claim_ids": [claim_id],
                            "type": "TEST",
                            "status": "PASS",
                            "command": install_command,
                            "environment": {"os": "smoke", "python": "3.12"},
                            "commit": head,
                            "repository_digest": repo_digest,
                            "artifacts": [
                                _artifact(
                                    f"{relative_temp}/install-trace.json",
                                    trace_content,
                                )
                            ],
                            "recorded_at": "2026-07-29T00:01:00+00:00",
                        },
                        {
                            "evidence_id": "EV-REVIEW-SMOKE",
                            "claim_ids": [claim_id],
                            "type": "MANUAL_REVIEW",
                            "status": "PASS",
                            "command": [
                                "python",
                                "-m",
                                "sdaqf",
                                "gate",
                                "implementation",
                            ],
                            "environment": {"os": "smoke"},
                            "commit": head,
                            "repository_digest": repo_digest,
                            "artifacts": [
                                _artifact(
                                    f"{relative_temp}/conformance.txt",
                                    conformance_content,
                                )
                            ],
                            "recorded_at": "2026-07-29T00:02:00+00:00",
                        },
                    ],
                    "diff_review_evidence_id": "EV-DIFF-SMOKE",
                },
            )
            candidate_identity = {
                "source_spec_sha256": baseline_payload["source"]["sha256"],
                "git_head": head,
                "repository_digest": repo_digest,
            }
            m3_review = temporary / "review.json"
            _write_json(
                m3_review,
                {
                    "schema_version": "1.0",
                    "review_id": "REV-SMOKE-0001",
                    "baseline_id": baseline_payload["baseline_id"],
                    "candidate": candidate_identity,
                    "reviewed_at": "2026-07-29T00:03:00+00:00",
                    "reviewer_id": "AGT-REVIEWER-1",
                    "reviewed_agent_ids": ["AGT-IMPLEMENTER-1"],
                    "status": "completed",
                    "read_only": True,
                    "areas": ["regression", "security", "maintainability"],
                    "findings": [],
                    "reviewed_paths": list(
                        git.changed_paths or git.publication_paths
                    ),
                    "changed_paths": [],
                },
            )
            m3_manifest = temporary / "manifest.json"
            _write_json(
                m3_manifest,
                {
                    "schema_version": "1.0",
                    "project_id": "smoke-project",
                    "title": "Smoke Project",
                    "release_level": "prototype",
                    "source_spec": {
                        "filename": m3_spec.name,
                        "sha256": baseline_payload["source"]["sha256"],
                        "imported_at": "2026-07-29T00:00:00+00:00",
                    },
                    "platforms": {"required": ["windows"], "optional": []},
                    "ui": {"present": False},
                    "network_policy": "default-deny",
                    "api_required": False,
                },
            )
            m3_ui = temporary / "ui.json"
            _write_json(
                m3_ui,
                {
                    "schema_version": "1.0",
                    "project_id": "smoke-project",
                    "ui_present": False,
                    "candidate": candidate_identity,
                    "design_brief": None,
                    "observations": [],
                },
            )
            _run(
                "Claim-Evidence Ledger",
                ["evidence", "validate", str(m3_ledger), "--json"],
                json_output=True,
            )
            _run(
                "Gate G2",
                [
                    "gate",
                    "implementation",
                    str(m3_baseline),
                    "--ledger",
                    str(m3_ledger),
                    "--specification",
                    str(m3_spec),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "Gate G3",
                [
                    "gate",
                    "review",
                    str(m3_review),
                    "--baseline",
                    str(m3_baseline),
                    "--specification",
                    str(m3_spec),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "non-UI validation",
                [
                    "ui",
                    "validate",
                    str(m3_manifest),
                    str(m3_ui),
                    "--specification",
                    str(m3_spec),
                    "--json",
                ],
                json_output=True,
            )
            handoff = temporary / "handoff.json"
            handoff_input = temporary / "handoff-input.json"
            _write_json(
                handoff_input,
                {
                    "schema_version": "1.0",
                    "milestone": "M3",
                    "status": "verification",
                    "completed": ["M3 smoke"],
                    "incomplete": [],
                    "evidence_ids": ["EV-DIFF-SMOKE", "EV-INSTALL-SMOKE"],
                    "open_decisions": ["Project license"],
                    "known_problems": [],
                    "recommended_next": "Review the local candidate.",
                    "primary_folder": "repo/",
                    "approval_stops": ["Stop before external action."],
                    "next_prompt_context": {
                        "role": "Repository reviewer",
                        "references": ["docs/specification.md"],
                        "change_scope": ["Review M3."],
                        "exclusions": ["Do not publish."],
                        "completion_criteria": ["Report findings."],
                        "stop_conditions": ["Stop for approval."],
                    },
                },
            )
            _run(
                "automated handoff",
                [
                    "handoff",
                    "create",
                    str(handoff_input),
                    "--baseline",
                    str(m3_baseline),
                    "--ledger",
                    str(m3_ledger),
                    "--specification",
                    str(m3_spec),
                    "--output",
                    str(handoff),
                    "--json",
                ],
                json_output=True,
            )
            _run(
                "handoff resume",
                [
                    "handoff",
                    "resume",
                    str(handoff),
                    "--baseline",
                    str(m3_baseline),
                    "--ledger",
                    str(m3_ledger),
                    "--specification",
                    str(m3_spec),
                    "--json",
                ],
                json_output=True,
            )
            release_input = temporary / "release-candidate.json"
            _write_json(
                release_input,
                {
                    "schema_version": "1.0",
                    "install_evidence_id": "EV-INSTALL-SMOKE",
                    "execution_module": "sdaqf",
                    "install_target": f"{relative_temp}/install-target",
                    "rollback_guidance": (
                        f"Remove only the owned {relative_temp}/install-target and "
                        f"{relative_temp}/install-target-source directories."
                    ),
                    "documentation_paths": [
                        "CHANGELOG.md",
                        "CONTRIBUTING.md",
                        "README.md",
                        "SECURITY.md",
                        "docs/release-contract.md",
                    ],
                    "license_status": "not-selected",
                },
            )
            _run_expected_gate_failure(
                "Gate G4 dirty or exact-commit fail closed",
                [
                    "audit",
                    "release-candidate",
                    str(release_input),
                    "--root",
                    ".",
                    "--baseline",
                    str(m3_baseline),
                    "--ledger",
                    str(m3_ledger),
                    "--review",
                    str(m3_review),
                    "--manifest",
                    str(m3_manifest),
                    "--ui-validation",
                    str(m3_ui),
                    "--specification",
                    str(m3_spec),
                    "--json",
                ],
                expected_blockers={"G4-GIT"},
            )
            _run_positive_g4_smoke(temporary)
        finally:
            os.chdir(previous)
            if (
                m3_spec is not None
                and m3_spec.is_file()
                and not m3_spec.is_symlink()
                and not is_reparse_point(m3_spec)
            ):
                m3_spec.unlink()
    print("PASS: offline M0 through M3 CLI smoke checks succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_smoke())
