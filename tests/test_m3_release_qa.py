from __future__ import annotations

import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from scripts.run_cli_smoke import (
    _create_m3_smoke_specification,
    _prepare_smoke_state,
    _record_install_trace,
)

from sdaqf.adapters.process import SubprocessRunner
from sdaqf.application.contracts import ContractError
from sdaqf.application.gates import GateEngine
from sdaqf.application.quality_gates import parse_independent_review
from sdaqf.application.release_qa import (
    GitInspector,
    ReleaseCandidateGateService,
    _execution_probe,
    _valid_install_trace,
    audit_dependencies,
    audit_repository,
    candidate_files,
    is_link_or_reparse,
    load_release_candidate,
    repository_digest,
)
from sdaqf.domain.models import GateCheck, GateResult
from sdaqf.domain.quality import GitObservation
from sdaqf.ports.process import ProcessResult
from tests.m3_helpers import (
    HEAD,
    RELEASE_PUBLICATION_PATHS,
    REPOSITORY_DIGEST,
    baseline,
    install_command,
    ledger,
    materialize_release_source,
    review_payload,
    write_evidence_artifacts,
    write_json,
)


def test_repository_digest_uses_portable_relative_path_order(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "PLANS.md"
    architecture = tmp_path / "docs" / "architecture.md"
    architecture.parent.mkdir()
    plans.write_bytes(b"plans\n")
    architecture.write_bytes(b"architecture\n")
    relative_paths = ("docs/architecture.md", "PLANS.md")

    expected = hashlib.sha256()
    for relative in relative_paths:
        content = (tmp_path / relative).read_bytes()
        expected.update(relative.encode("utf-8"))
        expected.update(b"\0")
        expected.update(str(len(content)).encode("ascii"))
        expected.update(b"\0")
        expected.update(content)
        expected.update(b"\0")

    assert tuple(
        path.relative_to(tmp_path).as_posix()
        for path in candidate_files(tmp_path, tuple(reversed(relative_paths)))
    ) == relative_paths
    assert repository_digest(tmp_path, tuple(reversed(relative_paths))) == (
        expected.hexdigest().upper()
    )
    assert tuple(
        path.relative_to(tmp_path).as_posix()
        for path in candidate_files(
            tmp_path,
            ("case.json", "Case.json", "case.json"),
        )
    ) == ("Case.json", "case.json")


class FakeRunner:
    def __init__(
        self,
        *,
        status: str = "",
        branch: str = "main",
        head: str = HEAD,
        truncated: bool = False,
        publication: str = "",
    ) -> None:
        self.status = status
        self.branch = branch
        self.head = head
        self.truncated = truncated
        self.publication = publication
        self.calls: list[list[str]] = []

    def run(self, args: Sequence[str]) -> ProcessResult:
        self.calls.append(list(args))
        command = tuple(args[3:])
        responses: dict[tuple[str, ...], str] = {
            ("rev-parse", "--show-toplevel"): args[2],
            ("branch", "--show-current"): self.branch,
            ("rev-parse", "HEAD"): self.head,
            ("status", "--porcelain"): self.status,
            ("diff", "--name-only", "--no-renames", "HEAD"): "",
            ("ls-files", "--others", "--exclude-standard"): "",
            (
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ): self.publication,
        }
        output = responses[command]
        return ProcessResult(
            0,
            output,
            "",
            stdout_truncated=self.truncated,
        )


def test_git_inspector_uses_resolved_bounded_read_only_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "git"
    executable.write_text("placeholder", encoding="utf-8")
    runner = FakeRunner()
    monkeypatch.setattr("sdaqf.application.release_qa.shutil.which", lambda _: str(executable))

    observation = GitInspector(runner).inspect(tmp_path)

    assert observation == GitObservation(
        True,
        "main",
        HEAD,
        True,
        repository_digest(tmp_path),
    )
    assert len(runner.calls) == 7
    assert all(call[0] == str(executable.resolve()) for call in runner.calls)
    assert all(call[1:3] == ["-C", str(tmp_path.resolve())] for call in runner.calls)


def test_git_inspector_fails_closed_on_missing_truncated_or_invalid_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sdaqf.application.release_qa.shutil.which", lambda _: None)
    with pytest.raises(ContractError, match="unavailable"):
        GitInspector(FakeRunner()).inspect(tmp_path)

    executable = tmp_path / "git"
    executable.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr("sdaqf.application.release_qa.shutil.which", lambda _: str(executable))
    with pytest.raises(ContractError, match="failed"):
        GitInspector(FakeRunner(truncated=True)).inspect(tmp_path)
    with pytest.raises(ContractError, match="branch"):
        GitInspector(FakeRunner(branch="bad branch")).inspect(tmp_path)
    with pytest.raises(ContractError, match="HEAD"):
        GitInspector(FakeRunner(head="bad")).inspect(tmp_path)


def test_git_inspector_accepts_bounded_publication_listing_over_four_kib(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "git"
    executable.write_text("placeholder", encoding="utf-8")
    paths = tuple(
        f"docs/{index:03d}-{'a' * 90}.md"
        for index in range(50)
    )
    for relative in paths:
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text("English\n", encoding="utf-8")
    runner = FakeRunner(publication="\0".join(paths) + "\0")
    monkeypatch.setattr(
        "sdaqf.application.release_qa.shutil.which",
        lambda _: str(executable),
    )

    observation = GitInspector(runner).inspect(tmp_path)

    assert observation.publication_paths == paths
    assert len(runner.publication) > 4_096


def test_release_candidate_gate_passes_complete_local_candidate(
    tmp_path: Path,
) -> None:
    root = _release_root(tmp_path)
    candidate = load_release_candidate(
        write_json(root / "candidate.json", _candidate_payload())
    )

    result = ReleaseCandidateGateService().evaluate(
        root=root,
        baseline=baseline(),
        ledger=ledger(),
        review=parse_independent_review(review_payload()),
        candidate=candidate,
        g2=_passing_gate("G2"),
        g3=_passing_gate("G3"),
        ui=_passing_gate("UI"),
        git=_release_git(),
    )

    assert result.passed
    assert audit_repository(root, tmp_path) == ()
    assert audit_dependencies(root) == ()


def test_release_gate_rejects_prior_gate_dirty_git_and_install_mismatch(
    tmp_path: Path,
) -> None:
    root = _release_root(tmp_path)
    candidate = load_release_candidate(
        write_json(root / "candidate.json", _candidate_payload())
    )
    result = ReleaseCandidateGateService().evaluate(
        root=root,
        baseline=baseline(),
        ledger=ledger(),
        review=parse_independent_review(review_payload()),
        candidate=candidate,
        g2=_failing_gate("G2"),
        g3=_passing_gate("G3"),
        ui=_passing_gate("UI"),
        git=_release_git(
            branch="topic",
            head="2" * 40,
            clean=False,
            digest="E" * 64,
        ),
    )

    assert "G4-PRIOR-GATES" in result.hard_blockers
    assert "G4-REPRODUCIBLE-INSTALL" in result.hard_blockers
    assert "G4-GIT" in result.hard_blockers


def test_release_gate_rejects_passing_results_with_wrong_gate_identity(
    tmp_path: Path,
) -> None:
    root = _release_root(tmp_path)
    candidate = load_release_candidate(
        write_json(root / "candidate.json", _candidate_payload())
    )

    result = ReleaseCandidateGateService().evaluate(
        root=root,
        baseline=baseline(),
        ledger=ledger(),
        review=parse_independent_review(review_payload()),
        candidate=candidate,
        g2=_passing_gate("G1"),
        g3=_passing_gate("OTHER"),
        ui=_passing_gate("G2"),
        git=_release_git(),
    )

    assert "G4-PRIOR-GATES" in result.hard_blockers


def test_install_trace_rejects_duplicate_keys_and_unrecorded_target(
    tmp_path: Path,
) -> None:
    root = _release_root(tmp_path)
    trace = root / "evidence" / "install-trace.json"
    original = trace.read_text(encoding="utf-8")
    duplicate = original.replace('"returncode": 0', '"returncode": 1, "returncode": 0')
    trace.write_text(duplicate, encoding="utf-8")
    git = GitObservation(True, "main", HEAD, True, REPOSITORY_DIGEST)

    assert not _valid_install_trace(
        root,
        "evidence/install-trace.json",
        tuple(install_command()),
        git,
        "sdaqf",
        ".sdaqf/install-target",
    )
    trace.write_text(
        original.replace(
            '".sdaqf/install-target"',
            '"outside-target"',
        ),
        encoding="utf-8",
    )
    assert not _valid_install_trace(
        root,
        "evidence/install-trace.json",
        tuple(install_command()),
        git,
        "sdaqf",
        ".sdaqf/install-target",
    )


def test_install_smoke_preserves_preexisting_target_sentinel(tmp_path: Path) -> None:
    target = tmp_path / ".sdaqf" / "install-target"
    target.mkdir(parents=True)
    sentinel = target / "owner-data.txt"
    sentinel.write_bytes(b"preserve exactly\n")

    with pytest.raises(RuntimeError, match="fresh owned"):
        _record_install_trace(
            tmp_path,
            command=install_command(),
            execution_module="sdaqf",
            target_relative=".sdaqf/install-target",
            git_head=HEAD,
            repository_digest=REPOSITORY_DIGEST,
            publication_paths=("pyproject.toml",),
        )

    assert sentinel.read_bytes() == b"preserve exactly\n"


def test_install_smoke_preserves_preexisting_source_sentinel(tmp_path: Path) -> None:
    source = tmp_path / ".sdaqf" / "install-target-source"
    source.mkdir(parents=True)
    sentinel = source / "owner-data.txt"
    sentinel.write_bytes(b"preserve source exactly\n")

    with pytest.raises(RuntimeError, match="fresh owned"):
        _record_install_trace(
            tmp_path,
            command=install_command(),
            execution_module="sdaqf",
            target_relative=".sdaqf/install-target",
            git_head=HEAD,
            repository_digest=REPOSITORY_DIGEST,
            publication_paths=("pyproject.toml",),
        )

    assert sentinel.read_bytes() == b"preserve source exactly\n"


def test_smoke_state_rejects_reparse_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / ".sdaqf"
    state.mkdir()
    monkeypatch.setattr(
        "scripts.run_cli_smoke.is_reparse_point",
        lambda path: path == state,
    )

    with pytest.raises(RuntimeError, match="reparse"):
        _prepare_smoke_state(tmp_path)


def test_smoke_specification_uses_exclusive_random_owned_path(tmp_path: Path) -> None:
    fixed = tmp_path / "m3-smoke-specification.md"
    fixed.write_bytes(b"owner sentinel\n")

    created = _create_m3_smoke_specification(tmp_path)
    try:
        assert created.parent == tmp_path
        assert created.name.startswith("m3-smoke-specification-")
        assert created != fixed
        assert fixed.read_bytes() == b"owner sentinel\n"
        assert created.is_file()
        assert not created.is_symlink()
    finally:
        created.unlink()


def test_smoke_specification_rejects_simulated_reparse_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "scripts.run_cli_smoke.is_reparse_point",
        lambda path: path.name.startswith("m3-smoke-specification-"),
    )

    with pytest.raises(RuntimeError, match="regular owned"):
        _create_m3_smoke_specification(tmp_path)

    assert not tuple(tmp_path.glob("m3-smoke-specification-*.md"))


def test_installed_execution_probe_rejects_ambient_standard_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / ".sdaqf" / "empty-target"
    state.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    command = _execution_probe("json", ".sdaqf/empty-target")

    result = SubprocessRunner(timeout_seconds=5, output_limit=4_096).run(
        [sys.executable, *command[1:]]
    )

    assert result.returncode != 0


def test_actual_install_ignores_pip_shadow_and_pythonpath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".sdaqf").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["setuptools==83.0.0"]\n'
        'build-backend = "setuptools.build_meta"\n\n'
        "[project]\n"
        'name = "isolated-install-smoke"\n'
        'version = "0.0.0"\n'
        "dependencies = []\n",
        encoding="utf-8",
    )
    package = tmp_path / "isolated_install_smoke"
    package.mkdir()
    (package / "__init__.py").write_text(
        '"""Isolated install smoke."""\n',
        encoding="utf-8",
    )
    (package / "__main__.py").write_text(
        '"""Executable smoke module."""\n',
        encoding="utf-8",
    )
    (tmp_path / "pip.py").write_text(
        "raise SystemExit('ambient pip shadow executed')\n",
        encoding="utf-8",
    )
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    (ambient / "pip.py").write_text(
        "raise SystemExit('PYTHONPATH pip shadow executed')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(ambient))
    monkeypatch.chdir(tmp_path)
    legacy = SubprocessRunner(timeout_seconds=5, output_limit=4_096).run(
        [sys.executable, "-m", "pip", "--version"]
    )
    assert legacy.returncode != 0
    assert "ambient pip shadow executed" in legacy.stderr

    command = [
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
        ".sdaqf/install-target-source",
    ]
    trace = _record_install_trace(
        tmp_path,
        command=command,
        execution_module="isolated_install_smoke",
        target_relative=".sdaqf/install-target",
        git_head=HEAD,
        repository_digest=REPOSITORY_DIGEST,
        publication_paths=(
            "isolated_install_smoke/__init__.py",
            "isolated_install_smoke/__main__.py",
            "pyproject.toml",
        ),
    )

    assert trace["command"] == command
    assert trace["returncode"] == 0
    assert trace["execution_returncode"] == 0
    assert (tmp_path / ".sdaqf" / "install-target").is_dir()


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("bad.md", "ghp_" + ("a" * 24), "G4-SECURITY-AUDIT"),
        ("LICENSE", "unapproved", "G4-DEPENDENCY-LICENSE"),
    ],
)
def test_release_gate_rejects_security_or_license_finding(
    tmp_path: Path,
    filename: str,
    content: str,
    expected: str,
) -> None:
    root = _release_root(tmp_path)
    (root / filename).write_text(content, encoding="utf-8")
    candidate = load_release_candidate(
        write_json(root / "candidate.json", _candidate_payload())
    )

    result = ReleaseCandidateGateService().evaluate(
        root=root,
        baseline=baseline(),
        ledger=ledger(),
        review=parse_independent_review(review_payload()),
        candidate=candidate,
        g2=_passing_gate("G2"),
        g3=_passing_gate("G3"),
        ui=_passing_gate("UI"),
        git=_release_git(
            publication_paths=tuple(
                sorted((*RELEASE_PUBLICATION_PATHS, filename))
            )
        ),
    )

    assert expected in result.hard_blockers


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        ("README.md", b"# Missing required sections\n"),
        ("CONTRIBUTING.md", b""),
    ],
)
def test_release_gate_rejects_incomplete_or_empty_documentation(
    tmp_path: Path,
    relative: str,
    content: bytes,
) -> None:
    root = _release_root(tmp_path)
    (root / relative).write_bytes(content)
    candidate = load_release_candidate(
        write_json(root / "candidate.json", _candidate_payload())
    )

    result = ReleaseCandidateGateService().evaluate(
        root=root,
        baseline=baseline(),
        ledger=ledger(),
        review=parse_independent_review(review_payload()),
        candidate=candidate,
        g2=_passing_gate("G2"),
        g3=_passing_gate("G3"),
        ui=_passing_gate("UI"),
        git=_release_git(),
    )

    assert "G4-DOCUMENTATION" in result.hard_blockers


def test_ignored_build_input_cannot_enter_materialized_candidate(
    tmp_path: Path,
) -> None:
    root = _release_root(tmp_path)
    (root / "setup.py").write_text("raise SystemExit('ignored')\n", encoding="utf-8")
    source = root / ".sdaqf" / "install-target-source"
    assert not (source / "setup.py").exists()
    candidate = load_release_candidate(
        write_json(root / "candidate.json", _candidate_payload())
    )
    service = ReleaseCandidateGateService()

    def evaluate() -> GateResult:
        return service.evaluate(
            root=root,
            baseline=baseline(),
            ledger=ledger(),
            review=parse_independent_review(review_payload()),
            candidate=candidate,
            g2=_passing_gate("G2"),
            g3=_passing_gate("G3"),
            ui=_passing_gate("UI"),
            git=_release_git(),
        )

    assert evaluate().passed

    (source / "setup.py").write_text("raise SystemExit('injected')\n", encoding="utf-8")
    injected = evaluate()
    assert "G4-REPRODUCIBLE-INSTALL" in injected.hard_blockers


def test_release_documentation_must_belong_to_git_publication_set(
    tmp_path: Path,
) -> None:
    root = _release_root(tmp_path)
    candidate = load_release_candidate(
        write_json(root / "candidate.json", _candidate_payload())
    )
    without_readme = tuple(
        path for path in RELEASE_PUBLICATION_PATHS if path != "README.md"
    )

    result = ReleaseCandidateGateService().evaluate(
        root=root,
        baseline=baseline(),
        ledger=ledger(),
        review=parse_independent_review(review_payload()),
        candidate=candidate,
        g2=_passing_gate("G2"),
        g3=_passing_gate("G3"),
        ui=_passing_gate("UI"),
        git=_release_git(publication_paths=without_readme),
    )

    assert "G4-DOCUMENTATION" in result.hard_blockers


def test_release_input_rejects_license_assertion_and_unsafe_document(
    tmp_path: Path,
) -> None:
    licensed = _candidate_payload()
    licensed["license_status"] = "owner-approved"
    with pytest.raises(ContractError, match="not-selected"):
        load_release_candidate(write_json(tmp_path / "licensed.json", licensed))

    unsafe = _candidate_payload()
    unsafe["documentation_paths"] = ["../README.md"]
    with pytest.raises(ContractError, match="relative"):
        load_release_candidate(write_json(tmp_path / "unsafe.json", unsafe))

    version = _candidate_payload()
    version["schema_version"] = "2.0"
    with pytest.raises(ContractError, match="schema_version"):
        load_release_candidate(write_json(tmp_path / "version.json", version))

    identifier = _candidate_payload()
    identifier["install_evidence_id"] = "bad"
    with pytest.raises(ContractError, match="identifier"):
        load_release_candidate(write_json(tmp_path / "identifier.json", identifier))

    duplicate = _candidate_payload()
    duplicate["documentation_paths"] = ["README.md", "README.md"]
    with pytest.raises(ContractError, match="unique"):
        load_release_candidate(write_json(tmp_path / "duplicate.json", duplicate))


def test_dependency_audit_rejects_missing_and_duplicate_contracts(
    tmp_path: Path,
) -> None:
    assert audit_dependencies(tmp_path) == ("Dependency contract files are missing.",)

    root = _release_root(tmp_path)
    (root / "requirements-dev.lock").write_text(
        "pytest==1\npytest==1\ninvalid>=2\n",
        encoding="utf-8",
    )
    findings = audit_dependencies(root)

    assert any("unique" in item for item in findings)
    assert any("exact version pin" in item for item in findings)


@pytest.mark.parametrize(
    "relative",
    [
        "LICENSE.md",
        "docs/LICENCE",
        "legal/COPYING.txt",
        "LICENSES/MIT.txt",
        "docs/LICENCES/MIT.txt",
    ],
)
def test_repository_audit_rejects_license_variants(
    tmp_path: Path,
    relative: str,
) -> None:
    root = _release_root(tmp_path)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("unapproved\n", encoding="utf-8")

    assert any("license" in item.casefold() for item in audit_repository(root))
    assert any("license" in item.casefold() for item in audit_dependencies(root))


def test_repository_audit_scans_personal_data_in_binary_metadata(
    tmp_path: Path,
) -> None:
    root = _release_root(tmp_path)
    image = root / "evidence.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"author=C:\\"
        + b"Users\\Alice\\project;"
        + b"contact=alice"
        + b"@company.dev"
    )

    findings = audit_repository(root)

    assert any("personal absolute path" in item for item in findings)
    assert any("personal email address" in item for item in findings)


@pytest.mark.parametrize("name", ["private", "state", "scratch"])
def test_repository_audit_rejects_private_state_directories(
    tmp_path: Path,
    name: str,
) -> None:
    root = _release_root(tmp_path)
    folder = root / name
    folder.mkdir()
    (folder / "notes.md").write_text("local notes\n", encoding="utf-8")

    assert any("private state" in item for item in audit_repository(root))


def test_dependency_audit_fails_closed_for_toml_type_and_license_metadata(
    tmp_path: Path,
) -> None:
    root = _release_root(tmp_path)
    (root / "pyproject.toml").write_text('project = "bad"\n', encoding="utf-8")
    assert audit_dependencies(root) == ("pyproject.toml project must be a table.",)

    (root / "pyproject.toml").write_text(
        "[project]\ndependencies = []\nlicense = \"MIT\"\n",
        encoding="utf-8",
    )
    assert any("Apache-2.0" in item for item in audit_dependencies(root))

    (root / "pyproject.toml").write_text(
        "[project]\ndependencies = []\nclassifiers = \"bad\"\n",
        encoding="utf-8",
    )
    assert any("classifiers" in item for item in audit_dependencies(root))

    (root / "pyproject.toml").write_text(
        "[project]\ndependencies = []\n"
        "classifiers = [\"License :: OSI Approved\"]\n",
        encoding="utf-8",
    )
    assert any("Owner" in item for item in audit_dependencies(root))


def test_audits_reject_invalid_root_utf8_and_empty_lock(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert audit_repository(missing) == (
        "Repository root must be a regular directory.",
    )

    root = _release_root(tmp_path)
    (root / "bad.md").write_bytes(b"\xff")
    assert any("UTF-8" in item for item in audit_repository(root))
    (root / "requirements-dev.lock").write_text("", encoding="utf-8")
    assert any("must not be empty" in item for item in audit_dependencies(root))


def test_repository_audit_rejects_workspace_parent_override(
    tmp_path: Path,
) -> None:
    root = _release_root(tmp_path)
    other = tmp_path / "other"
    other.mkdir()

    assert any(
        "derived" in item for item in audit_repository(root, other)
    )


def test_repository_audit_scans_all_candidate_suffixes_and_tracked_state(
    tmp_path: Path,
) -> None:
    root = _release_root(tmp_path)
    svg = root / "token.svg"
    svg.write_text("ghp_" + ("a" * 24), encoding="utf-8")
    state = root / ".sdaqf"
    state.mkdir(exist_ok=True)
    hidden = state / "tracked.txt"
    hidden.write_text("tracked candidate\n", encoding="utf-8")

    findings = audit_repository(
        root,
        publication_paths=("token.svg", ".sdaqf/tracked.txt"),
    )

    assert any("possible secret" in item for item in findings)
    assert any("local state" in item for item in findings)
    assert hidden in candidate_files(
        root,
        ("token.svg", ".sdaqf/tracked.txt"),
    )


def test_repository_audit_rejects_reparse_parent_in_candidate_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _release_root(tmp_path)
    nested = root / "linked" / "file.md"
    nested.parent.mkdir()
    nested.write_text("English\n", encoding="utf-8")
    monkeypatch.setattr(
        "sdaqf.application.release_qa.is_link_or_reparse",
        lambda path: path == nested.parent or is_link_or_reparse(path),
    )

    findings = audit_repository(
        root,
        publication_paths=("linked/file.md",),
    )

    assert any("reparse" in item for item in findings)


def _release_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    docs = root / "docs"
    docs.mkdir()
    for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md"):
        (root / name).write_text(f"# {name}\n", encoding="utf-8")
    (root / "README.md").write_text(
        "# Test release\n\n## Installation\n\nOffline.\n\n"
        "## Known limitations\n\nFixture only.\n",
        encoding="utf-8",
    )
    (docs / "release-contract.md").write_text(
        "# Release Contract\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        "[project]\ndependencies = []\n",
        encoding="utf-8",
    )
    (root / "requirements-dev.lock").write_text(
        "pytest==1\n",
        encoding="utf-8",
    )
    (docs / "dependencies.md").write_text(
        "# Dependency license\n\npytest license: MIT\n",
        encoding="utf-8",
    )
    write_evidence_artifacts(root)
    materialize_release_source(root)
    return root


def _candidate_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "install_evidence_id": "EV-INSTALL-0001",
        "execution_module": "sdaqf",
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
    }


def _passing_gate(gate_id: str) -> GateResult:
    return GateEngine().evaluate(
        gate_id,
        (GateCheck("PASS", True, True, "passed"),),
    )


def _failing_gate(gate_id: str) -> GateResult:
    return GateEngine().evaluate(
        gate_id,
        (GateCheck("FAIL", False, True, "failed"),),
    )


def _release_git(
    *,
    branch: str = "main",
    head: str = HEAD,
    clean: bool = True,
    digest: str = REPOSITORY_DIGEST,
    publication_paths: tuple[str, ...] = RELEASE_PUBLICATION_PATHS,
) -> GitObservation:
    return GitObservation(
        True,
        branch,
        head,
        clean,
        digest,
        publication_paths=publication_paths,
    )
