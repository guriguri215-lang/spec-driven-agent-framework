"""Regression coverage for system-temp-only local Gate execution."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import scripts.run_cli_smoke as smoke
import scripts.run_local_gate as gates

ROOT = Path(__file__).resolve().parents[1]


def test_pytest_config_has_no_repository_local_basetemp() -> None:
    configuration = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "--basetemp=.pytest-tmp" not in configuration
    assert "--basetemp" not in configuration


def test_owned_gate_fixture_is_system_temp_and_is_removed() -> None:
    with gates.owned_system_temp(ROOT) as owned:
        configured = os.environ.get("SDAQF_SYSTEM_TEMP_ROOT")
        system_temp = Path(
            tempfile.gettempdir() if configured is None else configured
        ).resolve(strict=True)
        assert owned.parent == system_temp
        assert not owned.is_relative_to(ROOT.resolve(strict=True))
        assert not owned.is_relative_to(ROOT.parent.resolve(strict=True))
        assert owned.is_dir()
        retained_name = owned

    assert not retained_name.exists()


def test_owned_temp_cleanup_retries_only_transient_enotempty(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    adjacent = tmp_path / "adjacent"
    adjacent.mkdir()
    calls = 0
    sleeps: list[float] = []

    def cleanup() -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise OSError(errno.ENOTEMPTY, "directory not empty", owned)
        owned.rmdir()

    gates._cleanup_owned_system_temp(owned, cleanup, sleeper=sleeps.append)

    assert calls == 3
    assert sleeps == list(gates._CLEANUP_RETRY_DELAYS_SECONDS[:2])
    assert not owned.exists()
    assert adjacent.is_dir()


def test_owned_temp_cleanup_fails_closed_after_persistent_enotempty(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    error = OSError(errno.ENOTEMPTY, "directory not empty", owned)
    calls = 0
    sleeps: list[float] = []

    def cleanup() -> None:
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(OSError) as raised:
        gates._cleanup_owned_system_temp(owned, cleanup, sleeper=sleeps.append)

    assert raised.value is error
    assert calls == len(gates._CLEANUP_RETRY_DELAYS_SECONDS) + 1
    assert sleeps == list(gates._CLEANUP_RETRY_DELAYS_SECONDS)


def test_owned_temp_cleanup_propagates_other_os_errors_without_retry(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    error = OSError(errno.EACCES, "access denied", owned)
    calls = 0
    sleeps: list[float] = []

    def cleanup() -> None:
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(OSError) as raised:
        gates._cleanup_owned_system_temp(owned, cleanup, sleeper=sleeps.append)

    assert raised.value is error
    assert calls == 1
    assert sleeps == []


def test_owned_temp_cleanup_requires_final_absence(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()

    with pytest.raises(RuntimeError, match="was not removed"):
        gates._cleanup_owned_system_temp(owned, lambda: None)


def test_gate_environment_routes_every_generated_cache_to_owned_temp(
    tmp_path: Path,
) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()
    candidate = owned / "candidate"
    candidate.mkdir()

    environment, gate_state = gates.gate_environment(owned, candidate)

    for name in (
        "TMP",
        "TEMP",
        "TMPDIR",
        "PYTHONPYCACHEPREFIX",
        "COVERAGE_FILE",
        "MYPY_CACHE_DIR",
        "RUFF_CACHE_DIR",
        "PIP_CACHE_DIR",
        "XDG_CACHE_HOME",
    ):
        assert Path(environment[name]).resolve().is_relative_to(owned.resolve())
    assert gate_state.is_relative_to(candidate)
    assert gate_state == candidate / ".pytest-tmp"
    assert gate_state.resolve().is_relative_to(owned.resolve())
    assert "PYTEST_ADDOPTS" not in environment


def test_pytest_locations_are_enforced_by_the_runner(tmp_path: Path) -> None:
    arguments = gates._pytest_arguments(tmp_path, ("tests/test_status.py", "-q"))

    assert arguments[:2] == ["--basetemp", str(tmp_path / "pt")]
    assert f"cache_dir={tmp_path / 'pc'}" in arguments
    with pytest.raises(ValueError, match="controlled"):
        gates._pytest_arguments(tmp_path, ("--basetemp=repository-temp",))
    with pytest.raises(ValueError, match="controlled"):
        gates._pytest_arguments(tmp_path, ("-o", "cache_dir=.pytest_cache"))


def test_gate_runner_fails_closed_on_new_repository_residue(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    before = gates.repository_entries(repository)
    cache = repository / ".pytest_cache"
    marker = cache / "system-temp-regression-probe"
    cache.mkdir()
    marker.write_text("probe\n", encoding="utf-8")

    added, removed = gates.repository_changes(
        before,
        gates.repository_entries(repository),
    )

    assert added == [".pytest_cache/", ".pytest_cache/system-temp-regression-probe"]
    assert removed == []


def test_pytest_subcommand_leaves_repository_path_set_unchanged(tmp_path: Path) -> None:
    probe = tmp_path / "test_system_temp_probe.py"
    probe.write_text("def test_probe():\n    assert True\n", encoding="utf-8")
    before = gates.repository_entries(ROOT)

    environment = os.environ.copy()
    system_temp = environment.get("SDAQF_SYSTEM_TEMP_ROOT")
    if system_temp is not None:
        environment.update({"TMP": system_temp, "TEMP": system_temp, "TMPDIR": system_temp})
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_local_gate.py",
            "pytest",
            str(probe),
            "-q",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert gates.repository_entries(ROOT) == before


def test_real_publication_set_git_safety_stays_in_owned_system_temp() -> None:
    before = gates.workspace_entries(ROOT)

    with gates.owned_system_temp(ROOT) as owned:
        safety = owned / "git-safety"
        publication_paths = gates._publication_paths(ROOT, safety)

        assert publication_paths
        assert safety.is_dir()
        assert safety.resolve(strict=True).is_relative_to(owned.resolve(strict=True))
        assert gates.workspace_entries(ROOT) == before

    assert gates.workspace_entries(ROOT) == before


def _current_branch() -> str:
    completed = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip()
    return completed.stdout.strip()


@pytest.mark.parametrize(
    ("gate", "arguments"),
    (
        ("evaluation", ()),
        ("workspace", ("--expected-branch", _current_branch())),
        ("publication", ()),
        ("dependencies", ()),
        ("pip-check", ()),
    ),
)
def test_remaining_release_gate_subcommands_leave_no_workspace_residue(
    gate: str,
    arguments: tuple[str, ...],
) -> None:
    before_repository = gates.repository_entries(ROOT)
    before_workspace = gates.workspace_entries(ROOT)
    completed = subprocess.run(
        [sys.executable, "scripts/run_local_gate.py", gate, *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
        timeout=180,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert gates.repository_entries(ROOT) == before_repository
    assert gates.workspace_entries(ROOT) == before_workspace


def test_remaining_release_gate_arguments_fail_closed() -> None:
    assert gates._workspace_arguments(()) == ["--expected-branch", "main"]
    assert gates._workspace_arguments(("--expected-branch", "agent/example")) == [
        "--expected-branch",
        "agent/example",
    ]
    with pytest.raises(ValueError, match="expected branch"):
        gates._workspace_arguments(("--expected-origin-url", "unapproved"))


def test_named_validators_and_smoke_do_not_request_repository_temp() -> None:
    for relative in (
        "scripts/validate_m5_context.py",
        "scripts/validate_m6_scheduler.py",
        "scripts/validate_m7_solver.py",
        "scripts/validate_m8_workflow.py",
        "scripts/run_cli_smoke.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "TemporaryDirectory(" in source
        assert "dir=root" not in source
    smoke = (ROOT / "scripts/run_cli_smoke.py").read_text(encoding="utf-8")
    assert "_materialize_candidate_repository" in smoke
    assert 'm3_candidate = root / "m3-smoke-candidate"' in smoke
    assert "m3_spec = _create_m3_smoke_specification(m3_candidate)" in smoke
    assert "m3_spec.unlink()" in smoke
    assert "m3_candidate.rmdir()" in smoke
    assert "M3 smoke cleanup did not restore the clean candidate." in smoke
    assert 'build_fixture(temporary / "m7-solver", root=root)' in smoke
    assert "start_solver_lease(m7_fixture, root=root)" in smoke
    assert smoke.count('"commit",\n        "--quiet",') == 2


def test_gate_runner_materializes_a_clean_system_temp_git_candidate(tmp_path: Path) -> None:
    with gates.owned_system_temp(ROOT) as owned:
        candidate = gates.materialize_candidate_repository(ROOT, owned)
        completed = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=candidate,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10,
        )

        assert candidate.parent == owned
        assert completed.returncode == 0
        assert completed.stdout.strip() == f"## {_current_branch()}"


def test_candidate_git_add_uses_a_platform_tolerant_bounded_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    owned = tmp_path / "owned"
    owned.mkdir()
    calls: list[tuple[tuple[str, ...], int]] = []

    def record_git_command(
        root: Path,
        safety: Path,
        *arguments: str,
        timeout_seconds: int = gates._GIT_COMMAND_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[bytes]:
        del root, safety
        calls.append((arguments, timeout_seconds))
        return subprocess.CompletedProcess(list(arguments), 0, b"", b"")

    monkeypatch.setattr(
        gates,
        "_source_git_metadata",
        lambda source_root, safety: ("agent/example", ()),
    )
    monkeypatch.setattr(gates, "_publication_paths", lambda source_root, safety: ())
    monkeypatch.setattr(gates, "_git_command", record_git_command)

    gates.materialize_candidate_repository(source, owned)

    candidate_add = ("add", "--force", ".")
    assert [call for call in calls if call[0] == candidate_add] == [
        (candidate_add, gates._CANDIDATE_GIT_ADD_TIMEOUT_SECONDS)
    ]
    assert gates._CANDIDATE_GIT_ADD_TIMEOUT_SECONDS == 60
    assert all(
        timeout_seconds == gates._GIT_COMMAND_TIMEOUT_SECONDS
        for arguments, timeout_seconds in calls
        if arguments != candidate_add
    )


def test_cli_smoke_candidate_git_add_uses_a_platform_tolerant_bounded_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    calls: list[tuple[tuple[str, ...], int]] = []

    class EmptyObservation:
        publication_paths: tuple[str, ...] = ()

    class EmptyInspector:
        def __init__(self, runner: object) -> None:
            del runner

        def inspect(self, root: Path) -> EmptyObservation:
            del root
            return EmptyObservation()

    def record_git_command(
        root: Path,
        *arguments: str,
        timeout_seconds: int = smoke._GIT_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        del root
        calls.append((arguments, timeout_seconds))

    monkeypatch.setattr(smoke, "GitInspector", EmptyInspector)
    monkeypatch.setattr(smoke, "_git", record_git_command)

    candidate = smoke._materialize_candidate_repository(source, fixture)

    candidate_add = ("add", ".")
    assert candidate == fixture / "candidate"
    assert [call for call in calls if call[0] == candidate_add] == [
        (candidate_add, smoke._CANDIDATE_GIT_ADD_TIMEOUT_SECONDS)
    ]
    assert smoke._GIT_COMMAND_TIMEOUT_SECONDS == 10
    assert smoke._CANDIDATE_GIT_ADD_TIMEOUT_SECONDS == 60
    assert all(
        timeout_seconds == smoke._GIT_COMMAND_TIMEOUT_SECONDS
        for arguments, timeout_seconds in calls
        if arguments != candidate_add
    )


def test_coverage_gate_keeps_all_existing_m1_through_m8_thresholds() -> None:
    assert [threshold for threshold, _ in gates._COVERAGE_THRESHOLDS] == [
        90,
        90,
        90,
        90,
        80,
        90,
        90,
        90,
    ]
    included = ",".join(include for _, include in gates._COVERAGE_THRESHOLDS)
    for milestone in (
        "domain/models.py",
        "domain/orchestration.py",
        "domain/quality.py",
        "domain/evaluation.py",
        "domain/context.py",
        "domain/scheduler.py",
        "domain/solver.py",
        "domain/workflow.py",
    ):
        assert milestone in included
