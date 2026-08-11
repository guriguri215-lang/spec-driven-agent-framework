"""Run repository quality Gates with every generated artifact in system temp."""

from __future__ import annotations

import argparse
import errno
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_EXPECTED_ORIGIN_URL = (
    "https://github.com/guriguri215-lang/spec-driven-agent-framework.git"
)
_GIT_COMMAND_TIMEOUT_SECONDS = 10
_CANDIDATE_GIT_ADD_TIMEOUT_SECONDS = 60
_CLEANUP_RETRY_DELAYS_SECONDS = (0.05, 0.2, 1.0)
_PYTHON_SCRIPTS = {
    "scripts/run_cli_smoke.py",
    "scripts/validate_m5_context.py",
    "scripts/validate_m6_scheduler.py",
    "scripts/validate_m7_solver.py",
    "scripts/validate_m8_workflow.py",
}
_COVERAGE_THRESHOLDS = (
    (
        90,
        "src/sdaqf/domain/models.py,src/sdaqf/domain/requirements.py,"
        "src/sdaqf/application/gates.py,src/sdaqf/application/approvals.py,"
        "src/sdaqf/application/baselines.py,src/sdaqf/application/comparison.py,"
        "src/sdaqf/application/planning.py,src/sdaqf/application/requirements.py,"
        "src/sdaqf/application/requirements_gate.py",
    ),
    (
        90,
        "src/sdaqf/domain/orchestration.py,src/sdaqf/domain/tooling.py,"
        "src/sdaqf/adapters/process.py,src/sdaqf/application/orchestration.py,"
        "src/sdaqf/application/skills.py,src/sdaqf/application/tooling.py,"
        "src/sdaqf/application/checkpoints.py",
    ),
    (
        90,
        "src/sdaqf/domain/quality.py,src/sdaqf/application/contracts.py,"
        "src/sdaqf/application/evidence.py,src/sdaqf/application/quality_gates.py,"
        "src/sdaqf/application/ui_validation.py,src/sdaqf/application/release_qa.py,"
        "src/sdaqf/application/handoffs.py",
    ),
    (
        90,
        "src/sdaqf/domain/evaluation.py,src/sdaqf/domain/migrations.py,"
        "src/sdaqf/application/evaluation.py,src/sdaqf/application/migrations.py",
    ),
    (
        80,
        "src/sdaqf/domain/context.py,src/sdaqf/ports/context.py,"
        "src/sdaqf/adapters/context.py,src/sdaqf/application/context_contracts.py,"
        "src/sdaqf/application/context_index.py,"
        "src/sdaqf/application/context_selection.py,"
        "src/sdaqf/application/context_compaction.py,"
        "src/sdaqf/application/context_quality.py",
    ),
    (
        90,
        "src/sdaqf/domain/scheduler.py,src/sdaqf/ports/scheduler.py,"
        "src/sdaqf/adapters/scheduler.py,"
        "src/sdaqf/application/scheduler_contracts.py,"
        "src/sdaqf/application/scheduler.py,"
        "src/sdaqf/application/scheduler_migrations.py,"
        "src/sdaqf/application/scheduler_recovery.py,"
        "src/sdaqf/application/scheduler_simulation.py",
    ),
    (
        90,
        "src/sdaqf/domain/solver.py,src/sdaqf/ports/solver.py,"
        "src/sdaqf/adapters/solver.py,src/sdaqf/application/solver_contracts.py,"
        "src/sdaqf/application/solver.py,"
        "src/sdaqf/application/solver_verification.py",
    ),
    (
        90,
        "src/sdaqf/domain/workflow.py,src/sdaqf/ports/workflow.py,"
        "src/sdaqf/adapters/workflow.py,src/sdaqf/application/workflow_contracts.py,"
        "src/sdaqf/application/workflow_explanation.py,"
        "src/sdaqf/application/workflow_outcome.py,"
        "src/sdaqf/application/workflow_planning.py,"
        "src/sdaqf/application/workflow_recovery.py,"
        "src/sdaqf/application/workflow_runtime.py,"
        "src/sdaqf/application/workflow_simulation.py",
    ),
)


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & _REPARSE_POINT)


def _cleanup_owned_system_temp(
    path: Path,
    cleanup: Callable[[], None],
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Remove one owned fixture, retrying only transient non-empty directories."""

    for attempt in range(len(_CLEANUP_RETRY_DELAYS_SECONDS) + 1):
        try:
            cleanup()
        except OSError as exc:
            if (
                exc.errno != errno.ENOTEMPTY
                or attempt == len(_CLEANUP_RETRY_DELAYS_SECONDS)
            ):
                raise
            sleeper(_CLEANUP_RETRY_DELAYS_SECONDS[attempt])
        else:
            if os.path.lexists(path):
                raise RuntimeError("The local Gate temp fixture was not removed.")
            return


@contextmanager
def owned_system_temp(repository_root: Path) -> Iterator[Path]:
    """Yield one regular owned directory below the configured system temp root."""

    repository = repository_root.resolve(strict=True)
    workspace_parent = repository.parent
    configured_temp = os.environ.get("SDAQF_SYSTEM_TEMP_ROOT")
    system_temp = Path(
        tempfile.gettempdir() if configured_temp is None else configured_temp
    ).resolve(strict=True)
    if (
        not system_temp.is_dir()
        or _is_link_or_reparse(system_temp)
        or system_temp in (repository, workspace_parent)
        or system_temp.is_relative_to(repository)
        or system_temp.is_relative_to(workspace_parent)
    ):
        raise RuntimeError(
            "System temp must be a regular directory outside the repository workspace."
        )
    temporary = tempfile.TemporaryDirectory(prefix="sg-", dir=system_temp)
    owned = Path(temporary.name)
    try:
        resolved = owned.resolve(strict=True)
        if (
            resolved.parent != system_temp
            or not resolved.is_dir()
            or _is_link_or_reparse(owned)
        ):
            raise RuntimeError("The local Gate temp fixture is not an owned system-temp child.")
        yield resolved
    finally:
        _cleanup_owned_system_temp(owned, temporary.cleanup)


def repository_entries(repository_root: Path) -> frozenset[str]:
    """Return repository path names, excluding Git internals, without hashing content."""

    entries: set[str] = set()
    for current, directories, files in os.walk(repository_root, topdown=True):
        current_path = Path(current)
        if current_path == repository_root:
            directories[:] = [name for name in directories if name != ".git"]
        relative_parent = current_path.relative_to(repository_root)
        for name in directories:
            entries.add((relative_parent / name).as_posix() + "/")
        for name in files:
            entries.add((relative_parent / name).as_posix())
    return frozenset(entries)


def workspace_entries(repository_root: Path) -> frozenset[str]:
    """Return workspace-parent path names outside the repository itself."""

    repository = repository_root.resolve(strict=True)
    workspace_parent = repository.parent
    entries: set[str] = set()
    for current, directories, files in os.walk(workspace_parent, topdown=True):
        current_path = Path(current)
        if current_path == workspace_parent:
            directories[:] = [
                name for name in directories if workspace_parent / name != repository
            ]
        relative_parent = current_path.relative_to(workspace_parent)
        for name in directories:
            entries.add((relative_parent / name).as_posix() + "/")
        for name in files:
            entries.add((relative_parent / name).as_posix())
    return frozenset(entries)


def repository_changes(
    before: frozenset[str], after: frozenset[str]
) -> tuple[list[str], list[str]]:
    """Return added and removed repository path names in stable order."""

    return sorted(after - before), sorted(before - after)


def _git_command(
    root: Path,
    safety: Path,
    *arguments: str,
    timeout_seconds: int = _GIT_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[bytes]:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("Git is unavailable for the system-temp candidate fixture.")
    safety.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            str(Path(executable).resolve(strict=True)),
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
            str(root),
            *arguments,
        ],
        check=False,
        shell=False,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Temporary Git candidate command failed: {arguments[0]}")
    return completed


def _git_text(root: Path, safety: Path, *arguments: str) -> str:
    """Return strict UTF-8 text from one bounded Git query."""

    completed = _git_command(root, safety, *arguments)
    try:
        return completed.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeError as exc:
        raise RuntimeError("Temporary Git output is not valid UTF-8.") from exc


def _publication_paths(repository_root: Path, safety: Path) -> tuple[str, ...]:
    completed = _git_command(
        repository_root,
        safety,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    )
    try:
        values = completed.stdout.decode("utf-8", errors="strict").split("\0")
    except UnicodeError as exc:
        raise RuntimeError("Git publication paths are not valid UTF-8.") from exc
    paths = tuple(sorted({value for value in values if value}))
    if not paths:
        raise RuntimeError("The current publication candidate is empty.")
    return paths


def _source_git_metadata(
    repository_root: Path,
    safety: Path,
) -> tuple[str, tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]]:
    """Return the checked-out branch and exact fetch/push remote URL sets."""

    branch = _git_text(repository_root, safety, "branch", "--show-current")
    if not branch:
        raise RuntimeError("The publication candidate must be on a branch.")
    remote_names = tuple(
        value
        for value in _git_text(repository_root, safety, "remote").splitlines()
        if value
    )
    remotes: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for name in remote_names:
        fetch_urls = tuple(
            value
            for value in _git_text(
                repository_root,
                safety,
                "remote",
                "get-url",
                "--all",
                name,
            ).splitlines()
            if value
        )
        push_urls = tuple(
            value
            for value in _git_text(
                repository_root,
                safety,
                "remote",
                "get-url",
                "--push",
                "--all",
                name,
            ).splitlines()
            if value
        )
        if not fetch_urls or not push_urls:
            raise RuntimeError("The publication candidate has an incomplete Git remote.")
        remotes.append((name, fetch_urls, push_urls))
    return branch, tuple(remotes)


def materialize_candidate_repository(source_root: Path, owned: Path) -> Path:
    """Copy the current Git publication set into one clean system-temp repository."""

    source = source_root.resolve(strict=True)
    safety = owned / "gs"
    branch, remotes = _source_git_metadata(source, safety)
    candidate = owned / "r"
    candidate.mkdir()
    for relative in _publication_paths(source, safety):
        parts = Path(relative).parts
        if (
            not parts
            or Path(relative).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise RuntimeError("Git returned an unsafe publication path.")
        original = source.joinpath(*parts)
        current = source
        for part in parts:
            current = current / part
            if _is_link_or_reparse(current):
                raise RuntimeError("The publication candidate contains a link.")
        if not original.is_file() or original.stat().st_size > 1_000_000:
            raise RuntimeError("A publication candidate file is missing or oversized.")
        destination = candidate.joinpath(*parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
    _git_command(candidate, safety, "init", "-b", branch)
    _git_command(
        candidate,
        safety,
        "add",
        "--force",
        ".",
        timeout_seconds=_CANDIDATE_GIT_ADD_TIMEOUT_SECONDS,
    )
    _git_command(
        candidate,
        safety,
        "-c",
        "user.name=Local Gate",
        "-c",
        "user.email=local-gate.invalid",
        "commit",
        "-m",
        "candidate fixture",
    )
    for name, fetch_urls, push_urls in remotes:
        _git_command(candidate, safety, "remote", "add", name, fetch_urls[0])
        for url in fetch_urls[1:]:
            _git_command(
                candidate,
                safety,
                "remote",
                "set-url",
                "--add",
                name,
                url,
            )
        for url in push_urls:
            _git_command(
                candidate,
                safety,
                "remote",
                "set-url",
                "--add",
                "--push",
                name,
                url,
            )
    return candidate


def gate_environment(owned: Path, candidate: Path) -> tuple[dict[str, str], Path]:
    """Return a child environment that routes all supported caches to owned temp."""

    # Keep pytest's own fixture tree under a generated path that the repository
    # audit already excludes.  Some security tests intentionally leave a live
    # link in basetemp until pytest teardown; placing that tree under .sdaqf
    # would make a later in-process repository audit inspect test-only state.
    gate_state = candidate / ".pytest-tmp"
    runtime_temp = gate_state / "t"
    runtime_temp.mkdir(parents=True)
    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    environment.update(
        {
            "TMP": str(runtime_temp),
            "TEMP": str(runtime_temp),
            "TMPDIR": str(runtime_temp),
            "PYTHONPATH": os.pathsep.join((str(candidate / "src"), str(candidate))),
            "PYTHONPYCACHEPREFIX": str(gate_state / "p"),
            "COVERAGE_FILE": str(gate_state / "c" / ".coverage"),
            "MYPY_CACHE_DIR": str(gate_state / "m"),
            "RUFF_CACHE_DIR": str(gate_state / "r"),
            "PIP_CACHE_DIR": str(gate_state / "i"),
            "XDG_CACHE_HOME": str(gate_state / "x"),
            "SDAQF_SYSTEM_TEMP_ROOT": str(owned.parent),
        }
    )
    return environment, gate_state


def _pytest_arguments(owned: Path, arguments: Sequence[str]) -> list[str]:
    prohibited = ("--basetemp", "cache_dir")
    if any(any(token in argument for token in prohibited) for argument in arguments):
        raise ValueError("pytest temp and cache locations are controlled by the Gate runner.")
    return [
        "--basetemp",
        str(owned / "pt"),
        "-o",
        f"cache_dir={owned / 'pc'}",
        *arguments,
    ]


def _run(command: Sequence[str], environment: dict[str, str], candidate: Path) -> int:
    completed = subprocess.run(
        list(command),
        cwd=candidate,
        env=environment,
        check=False,
        shell=False,
    )
    return completed.returncode


def _run_coverage(
    gate_state: Path,
    environment: dict[str, str],
    candidate: Path,
) -> int:
    coverage_parent = Path(environment["COVERAGE_FILE"]).parent
    coverage_parent.mkdir()
    pytest_arguments = _pytest_arguments(gate_state, ())
    if _run(
        [sys.executable, "-m", "coverage", "run", "-m", "pytest", *pytest_arguments],
        environment,
        candidate,
    ):
        return 1
    if _run(
        [sys.executable, "-m", "coverage", "report", "--fail-under=80"],
        environment,
        candidate,
    ):
        return 1
    for threshold, include in _COVERAGE_THRESHOLDS:
        if _run(
            [
                sys.executable,
                "-m",
                "coverage",
                "report",
                f"--include={include}",
                f"--fail-under={threshold}",
            ],
            environment,
            candidate,
        ):
            return 1
    return 0


def _workspace_arguments(arguments: Sequence[str]) -> list[str]:
    """Return the one optional, bounded workspace-branch argument."""

    if not arguments:
        return ["--expected-branch", "main"]
    if (
        len(arguments) != 2
        or arguments[0] != "--expected-branch"
        or not arguments[1]
        or arguments[1].startswith("-")
        or any(character in arguments[1] for character in ("\0", "\n", "\r"))
    ):
        raise ValueError("The workspace Gate accepts only one expected branch.")
    return list(arguments)


def _report_path_changes(
    label: str,
    before: frozenset[str],
    after: frozenset[str],
) -> bool:
    """Report path-set drift and return whether the audit failed."""

    added, removed = repository_changes(before, after)
    for path in added:
        print(f"FAIL: local Gate left a new {label} path: {path}", file=sys.stderr)
    for path in removed:
        print(f"FAIL: local Gate removed a {label} path: {path}", file=sys.stderr)
    return bool(added or removed)


def run_gate(gate: str, arguments: Sequence[str]) -> int:
    """Run one bounded Gate and fail if it leaves any repository path behind."""

    if Path.cwd().resolve(strict=True) != _REPOSITORY_ROOT.resolve(strict=True):
        raise RuntimeError("Local Gates must run from the repository root.")
    with owned_system_temp(_REPOSITORY_ROOT) as owned:
        before_repository = repository_entries(_REPOSITORY_ROOT)
        before_workspace = workspace_entries(_REPOSITORY_ROOT)
        candidate = materialize_candidate_repository(_REPOSITORY_ROOT, owned)
        environment, gate_state = gate_environment(owned, candidate)
        if gate == "pytest":
            returncode = _run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *_pytest_arguments(gate_state, arguments),
                ],
                environment,
                candidate,
            )
        elif gate == "coverage":
            if arguments:
                raise ValueError("The coverage Gate does not accept additional arguments.")
            returncode = _run_coverage(gate_state, environment, candidate)
        elif gate == "ruff":
            if arguments:
                raise ValueError("The Ruff Gate does not accept additional arguments.")
            returncode = _run(
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "--cache-dir",
                    str(gate_state / "r"),
                    "src",
                    "tests",
                    "scripts",
                ],
                environment,
                candidate,
            )
        elif gate == "mypy":
            if arguments:
                raise ValueError("The mypy Gate does not accept additional arguments.")
            returncode = _run(
                [
                    sys.executable,
                    "-m",
                    "mypy",
                    "--cache-dir",
                    str(gate_state / "m"),
                    "src",
                    "tests",
                    "scripts",
                ],
                environment,
                candidate,
            )
        elif gate == "script":
            if len(arguments) != 1 or arguments[0] not in _PYTHON_SCRIPTS:
                raise ValueError("The script Gate target is not approved.")
            returncode = _run([sys.executable, arguments[0]], environment, candidate)
        elif gate == "evaluation":
            if arguments:
                raise ValueError("The evaluation Gate does not accept arguments.")
            returncode = _run(
                [
                    sys.executable,
                    "-m",
                    "sdaqf",
                    "eval",
                    "validate",
                    "evals/comparison-suite.json",
                    "--result",
                    "evals/results/public-beta-comparison.json",
                    "--json",
                ],
                environment,
                candidate,
            )
        elif gate == "workspace":
            returncode = _run(
                [
                    sys.executable,
                    "scripts/check_workspace_boundary.py",
                    "--repo",
                    ".",
                    "--workspace-parent",
                    str(candidate.parent),
                    "--expected-origin-url",
                    _EXPECTED_ORIGIN_URL,
                    *_workspace_arguments(arguments),
                ],
                environment,
                candidate,
            )
        elif gate == "publication":
            if arguments:
                raise ValueError("The publication Gate does not accept arguments.")
            returncode = _run(
                [
                    sys.executable,
                    "scripts/audit_repository.py",
                    "--root",
                    ".",
                    "--workspace-parent",
                    str(candidate.parent),
                ],
                environment,
                candidate,
            )
        elif gate == "dependencies":
            if arguments:
                raise ValueError("The dependency Gate does not accept arguments.")
            returncode = _run(
                [sys.executable, "scripts/audit_dependencies.py", "--root", "."],
                environment,
                candidate,
            )
        elif gate == "pip-check":
            if arguments:
                raise ValueError("The pip check Gate does not accept arguments.")
            returncode = _run(
                [sys.executable, "-m", "pip", "check"],
                environment,
                candidate,
            )
        else:
            raise ValueError(f"Unknown local Gate: {gate}")
        repository_failed = _report_path_changes(
            "repository",
            before_repository,
            repository_entries(_REPOSITORY_ROOT),
        )
        workspace_failed = _report_path_changes(
            "workspace-parent",
            before_workspace,
            workspace_entries(_REPOSITORY_ROOT),
        )
        if repository_failed or workspace_failed:
            return 1
        return returncode


def main(argv: Sequence[str] | None = None) -> int:
    """Parse and run one system-temp-only local Gate."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "gate",
        choices=(
            "pytest",
            "coverage",
            "ruff",
            "mypy",
            "script",
            "evaluation",
            "workspace",
            "publication",
            "dependencies",
            "pip-check",
        ),
    )
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        return run_gate(args.gate, args.arguments)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
