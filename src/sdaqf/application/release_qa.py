"""Offline repository audits and non-compensating release-candidate Gate G4."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tomllib
from datetime import datetime
from pathlib import Path

from sdaqf.application.contracts import (
    ContractError,
    array_value,
    load_json_object,
    only_keys,
    safe_relative_path,
    string_value,
    verify_artifact,
)
from sdaqf.application.gates import GateEngine
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.models import GateCheck, GateResult
from sdaqf.domain.quality import (
    CandidateIdentity,
    ClaimState,
    EvidenceLedger,
    EvidenceStatus,
    EvidenceType,
    GitObservation,
    IndependentReview,
    ReleaseCandidateInput,
)
from sdaqf.domain.requirements import RequirementBaseline, RequirementPriority
from sdaqf.ports.process import ProcessRunner

_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".coverage",
    "__pycache__",
    ".pytest_cache",
    ".pytest-tmp",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".eggs",
    "build",
    "dist",
    "htmlcov",
    ".local",
    ".sdaqf",
}
_FORBIDDEN_STATE_PARTS = {"private", "scratch", "state"}
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
_PERSONAL_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]\x55sers[\\/]|/\x55sers/|/\x68ome/[^/\s]+/)",
    re.IGNORECASE,
)
_PERSONAL_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}"
    r"(?![A-Za-z0-9.-])",
)
_PROJECT_LICENSE_NAME = re.compile(
    r"(?:licen[cs]e|copying)(?:\.(?:md|rst|txt))?",
    re.IGNORECASE,
)
_PROJECT_LICENSE_DIRECTORIES = {"licenses", "licences"}
_SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+-]*)$")
_EVIDENCE_ID = re.compile(r"^EV-[A-Z0-9][A-Z0-9-]{0,63}$")
_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_HEAD = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_DOCUMENTS = {
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "docs/release-contract.md",
}


def candidate_files(
    root: Path,
    publication_paths: tuple[str, ...] | None = None,
) -> tuple[Path, ...]:
    """Return the bounded publication set, preferring Git-observed paths."""

    files: list[Path] = []
    if publication_paths is not None:
        for relative in publication_paths:
            normalized = safe_relative_path(relative, "publication path")
            files.append(root.joinpath(*Path(normalized).parts))
        return tuple(sorted(set(files)))
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if any(part in _EXCLUDED_PARTS for part in parts):
            continue
        if path.is_file() or path.is_symlink() or is_reparse_point(path):
            files.append(path)
    return tuple(sorted(files))


def repository_digest(
    root: Path,
    publication_paths: tuple[str, ...] | None = None,
) -> str:
    """Hash the bounded publication-candidate file set deterministically."""

    digest = hashlib.sha256()
    total_bytes = 0
    files = candidate_files(root, publication_paths)
    if len(files) > 4_096:
        raise ContractError("Repository candidate exceeds the file-count limit.")
    for path in files:
        if _path_or_parent_is_linked(root, path):
            raise ContractError("Repository candidate contains a link.")
        try:
            relative = path.relative_to(root).as_posix()
            size = path.stat().st_size
            if size > 1_000_000:
                raise ContractError("Repository candidate contains an oversized file.")
            total_bytes += size
            if total_bytes > 64_000_000:
                raise ContractError("Repository candidate exceeds the byte limit.")
            content = path.read_bytes()
        except OSError as exc:
            raise ContractError("Repository candidate could not be hashed.") from exc
        digest.update(relative.encode("utf-8", errors="strict"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest().upper()


def is_link_or_reparse(path: Path) -> bool:
    """Return true for a symbolic link or Windows reparse point."""

    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & _REPARSE_POINT)


def audit_repository(
    root: Path,
    workspace_parent: Path | None = None,
    publication_paths: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Return secret, path, language, link, size, and license findings."""

    errors: list[str] = []
    if not root.is_dir() or is_link_or_reparse(root):
        return ("Repository root must be a regular directory.",)
    parent = root.resolve().parent
    if workspace_parent is not None and workspace_parent.resolve() != parent:
        errors.append("Workspace parent must be derived from the repository root.")
    if (parent / ".git").exists():
        errors.append("The parent workspace must not contain .git.")
    for linked_directory in _reparse_directories(root):
        relative = linked_directory.relative_to(root).as_posix()
        errors.append(f"{relative}: directory links and reparse points are not allowed.")
    for path in candidate_files(root, publication_paths):
        relative = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        if publication_paths is not None and any(
            part in _EXCLUDED_PARTS or part.casefold().endswith(".egg-info")
            for part in parts
        ):
            errors.append(f"{relative}: generated or local state is not publishable.")
        if any(part.casefold() in _FORBIDDEN_STATE_PARTS for part in parts):
            errors.append(f"{relative}: private state directories are not publishable.")
        if (
            _PROJECT_LICENSE_NAME.fullmatch(parts[-1])
            or any(
                part.casefold() in _PROJECT_LICENSE_DIRECTORIES
                for part in parts[:-1]
            )
        ):
            errors.append(f"{relative}: project license requires an Owner decision.")
        if _path_or_parent_is_linked(root, path):
            errors.append(f"{relative}: links and reparse points are not allowed.")
            continue
        try:
            content = path.read_bytes()
        except OSError:
            errors.append(f"{relative}: candidate file is missing or unreadable.")
            continue
        if len(content) > 1_000_000:
            errors.append(f"{relative}: file exceeds the M0 size limit.")
            continue
        latin = content.decode("latin-1")
        if any(pattern.search(latin) for pattern in _SECRET_PATTERNS):
            errors.append(f"{relative}: contains a possible secret.")
        if _PERSONAL_PATH.search(latin):
            errors.append(f"{relative}: contains a personal absolute path.")
        if _PERSONAL_EMAIL.search(latin):
            errors.append(f"{relative}: contains a personal email address.")
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeError:
            if _looks_like_text(content):
                errors.append(f"{relative}: text file is not valid UTF-8.")
            continue
        if _CJK.search(text):
            errors.append(f"{relative}: contains non-English CJK text.")
    return tuple(errors)


def _path_or_parent_is_linked(root: Path, path: Path) -> bool:
    """Reject a link or reparse point at every candidate path component."""

    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if is_link_or_reparse(current):
            return True
    return False


def _looks_like_text(content: bytes) -> bool:
    """Conservatively classify malformed byte content for UTF-8 findings."""

    if not content:
        return True
    if b"\0" in content:
        return False
    controls = sum(
        value < 32 and value not in {9, 10, 13}
        for value in content[:8_192]
    )
    return controls * 20 <= min(len(content), 8_192)


def _reparse_directories(root: Path) -> tuple[Path, ...]:
    """Find candidate-tree directory links without traversing their targets."""

    findings: list[Path] = []
    pending = [root]
    generated = _EXCLUDED_PARTS - {".local", ".sdaqf"}
    while pending:
        directory = pending.pop()
        try:
            entries = tuple(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            if entry.name in generated:
                continue
            if entry.is_symlink() or is_link_or_reparse(path):
                if entry.is_dir(follow_symlinks=False) or entry.is_symlink():
                    findings.append(path)
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
            except OSError:
                continue
    return tuple(sorted(findings))


def audit_dependencies(root: Path) -> tuple[str, ...]:
    """Return runtime, development-pin, and license-record findings."""

    errors: list[str] = []
    pyproject_path = root / "pyproject.toml"
    lock_path = root / "requirements-dev.lock"
    record_path = root / "docs" / "dependencies.md"
    if not pyproject_path.is_file() or not lock_path.is_file() or not record_path.is_file():
        return ("Dependency contract files are missing.",)
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        lock_lines = tuple(
            line.strip()
            for line in lock_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        record = record_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return ("Dependency contract files are unreadable or invalid.",)
    if not isinstance(pyproject, dict):
        return ("pyproject.toml root must be a table.",)
    project_value = pyproject.get("project")
    if not isinstance(project_value, dict) or not all(
        isinstance(key, str) for key in project_value
    ):
        return ("pyproject.toml project must be a table.",)
    project = project_value
    if project.get("dependencies") != []:
        errors.append("Runtime dependencies must remain empty.")
    if "license" in project or "license-files" in project:
        errors.append("Project license metadata requires an explicit Owner decision.")
    classifiers = project.get("classifiers", [])
    if not isinstance(classifiers, list) or not all(
        isinstance(item, str) for item in classifiers
    ):
        errors.append("Project classifiers must be a string array.")
    elif any("license ::" in item.casefold() for item in classifiers):
        errors.append("Project license classifiers require an Owner decision.")
    if not lock_lines:
        errors.append("The development lock must not be empty.")
    packages: list[str] = []
    for line in lock_lines:
        match = _PIN.fullmatch(line)
        if match is None:
            errors.append("Every development dependency must use an exact version pin.")
            continue
        packages.append(match.group(1).casefold().replace("_", "-"))
    if len(packages) != len(set(packages)):
        errors.append("Development dependency names must be unique.")
    folded_record = record.casefold().replace("_", "-")
    for package in sorted(set(packages)):
        if package not in folded_record:
            errors.append(f"Dependency license record is missing: {package}.")
    if "license" not in folded_record:
        errors.append("Dependency documentation must record licenses.")
    if any(
        _PROJECT_LICENSE_NAME.fullmatch(path.name)
        or any(
            part.casefold() in _PROJECT_LICENSE_DIRECTORIES
            for part in path.relative_to(root).parts[:-1]
        )
        for path in candidate_files(root)
    ):
        errors.append("A project license requires an explicit Owner decision.")
    return tuple(errors)


def _valid_release_documentation(
    root: Path,
    documentation_paths: tuple[str, ...],
    publication_paths: tuple[str, ...],
) -> bool:
    """Require complete, regular, non-empty UTF-8 release documentation."""

    if (
        not set(documentation_paths) >= _REQUIRED_DOCUMENTS
        or not set(documentation_paths) <= set(publication_paths)
    ):
        return False
    decoded: dict[str, str] = {}
    for relative in documentation_paths:
        path = root.joinpath(*Path(relative).parts)
        if _path_or_parent_is_linked(root, path) or not path.is_file():
            return False
        try:
            content = path.read_bytes()
            if not content or len(content) > 1_000_000:
                return False
            decoded[relative] = content.decode("utf-8", errors="strict")
        except (OSError, UnicodeError):
            return False
        if not decoded[relative].strip():
            return False
    readme = decoded.get("README.md", "")
    return (
        re.search(r"^## Installation\s*$", readme, re.MULTILINE) is not None
        and re.search(r"^## Known limitations\s*$", readme, re.MULTILINE) is not None
    )


def source_target_for(install_target: str) -> str:
    """Derive the owned materialized-source path for one install target."""

    source_target = safe_relative_path(
        f"{install_target}-source",
        "materialized source target",
    )
    if not source_target.startswith(".sdaqf/"):
        raise ContractError("Materialized source target must stay inside M3 state.")
    return source_target


def _valid_materialized_source(
    root: Path,
    source_target: str,
    publication_paths: tuple[str, ...],
) -> bool:
    """Require an owned source tree containing exactly the Git candidate inputs."""

    if not publication_paths:
        return False
    source_root = root.joinpath(*Path(source_target).parts)
    if (
        not source_root.is_dir()
        or source_root.is_symlink()
        or is_link_or_reparse(source_root)
        or _path_or_parent_is_linked(root, source_root)
    ):
        return False
    publication = set(publication_paths)
    expected_directories = {
        Path(*parts[:index]).as_posix()
        for relative in publication_paths
        for parts in (Path(relative).parts,)
        for index in range(1, len(parts))
    }
    try:
        for relative in publication_paths:
            original = root.joinpath(*Path(relative).parts)
            copied = source_root.joinpath(*Path(relative).parts)
            if (
                _path_or_parent_is_linked(root, original)
                or _path_or_parent_is_linked(source_root, copied)
                or not original.is_file()
                or not copied.is_file()
                or original.stat().st_size > 1_000_000
                or copied.stat().st_size != original.stat().st_size
                or copied.read_bytes() != original.read_bytes()
            ):
                return False
        for path in source_root.rglob("*"):
            if _path_or_parent_is_linked(source_root, path):
                return False
            relative_parts = path.relative_to(source_root).parts
            relative = Path(*relative_parts).as_posix()
            if path.is_dir():
                if relative not in expected_directories:
                    return False
                continue
            if relative not in publication:
                return False
    except OSError:
        return False
    return True


def load_release_candidate(path: Path) -> ReleaseCandidateInput:
    """Load one bounded local release-candidate input."""

    root = load_json_object(path, "Release candidate", maximum_bytes=64 * 1024)
    only_keys(
        root,
        {
            "schema_version",
            "install_evidence_id",
            "execution_module",
            "install_target",
            "rollback_guidance",
            "documentation_paths",
            "license_status",
        },
        "release_candidate",
    )
    if string_value(root.get("schema_version"), "schema_version", maximum=10) != "1.0":
        raise ContractError("schema_version must be 1.0.")
    evidence_id = string_value(
        root.get("install_evidence_id"),
        "install_evidence_id",
        maximum=100,
    )
    if not _EVIDENCE_ID.fullmatch(evidence_id):
        raise ContractError("install_evidence_id is not a stable identifier.")
    execution_module = string_value(
        root.get("execution_module"),
        "execution_module",
        maximum=200,
    )
    if not _MODULE.fullmatch(execution_module):
        raise ContractError("execution_module is not a safe Python module name.")
    install_target = safe_relative_path(
        root.get("install_target"),
        "install_target",
    )
    if not install_target.startswith(".sdaqf/"):
        raise ContractError("install_target must be inside repository-local M3 state.")
    rollback_guidance = string_value(
        root.get("rollback_guidance"),
        "rollback_guidance",
        maximum=1_000,
    )
    source_target = source_target_for(install_target)
    expected_rollback = (
        f"Remove only the owned {install_target} and {source_target} directories."
    )
    if rollback_guidance != expected_rollback:
        raise ContractError("rollback_guidance must name the exact safe removal action.")
    documentation = tuple(
        safe_relative_path(value, f"documentation_paths[{index}]")
        for index, value in enumerate(
            array_value(
                root.get("documentation_paths"),
                "documentation_paths",
                maximum=64,
            )
        )
    )
    if len(documentation) != len(set(documentation)):
        raise ContractError("documentation_paths must contain unique paths.")
    license_status = string_value(
        root.get("license_status"),
        "license_status",
        maximum=50,
    )
    if license_status != "not-selected":
        raise ContractError(
            "M3 supports only the explicit not-selected project license state."
        )
    return ReleaseCandidateInput(
        install_evidence_id=evidence_id,
        execution_module=execution_module,
        install_target=install_target,
        rollback_guidance=rollback_guidance,
        documentation_paths=documentation,
        license_status=license_status,
    )


class GitInspector:
    """Inspect local Git identity and cleanliness through a bounded process port."""

    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner

    def inspect(self, root: Path) -> GitObservation:
        """Return one read-only local Git observation."""

        if root.is_symlink() or is_reparse_point(root):
            raise ContractError("Git root must be a regular directory.")
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir() or is_reparse_point(resolved_root):
            raise ContractError("Git root must be a regular directory.")
        located = shutil.which("git")
        if located is None:
            raise ContractError("Git is unavailable.")
        executable = str(Path(located).resolve(strict=True))
        top = self._output(executable, resolved_root, "rev-parse", "--show-toplevel")
        branch = self._output(executable, resolved_root, "branch", "--show-current")
        head = self._output(executable, resolved_root, "rev-parse", "HEAD")
        status = self._output(executable, resolved_root, "status", "--porcelain")
        tracked_changes = self._output(
            executable,
            resolved_root,
            "diff",
            "--name-only",
            "--no-renames",
            "HEAD",
        )
        untracked_changes = self._output(
            executable,
            resolved_root,
            "ls-files",
            "--others",
            "--exclude-standard",
        )
        publication_output = self._output(
            executable,
            resolved_root,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        )
        if not _BRANCH.fullmatch(branch):
            raise ContractError("Git branch output is invalid.")
        if not _HEAD.fullmatch(head):
            raise ContractError("Git HEAD output is invalid.")
        try:
            root_matches = Path(top).resolve(strict=True) == resolved_root
        except OSError as exc:
            raise ContractError("Git root output is invalid.") from exc
        changed_paths = tuple(
            sorted(
                {
                    safe_relative_path(value, "Git changed path")
                    for value in (
                        *tracked_changes.splitlines(),
                        *untracked_changes.splitlines(),
                    )
                    if value
                }
            )
        )
        publication_paths = tuple(
            sorted(
                {
                    safe_relative_path(value, "Git publication path")
                    for value in publication_output.split("\0")
                    if value
                }
            )
        )
        return GitObservation(
            root_matches=root_matches,
            branch=branch,
            head=head,
            clean=not status,
            repository_digest=repository_digest(
                resolved_root,
                publication_paths or None,
            ),
            changed_paths=changed_paths,
            publication_paths=publication_paths,
        )

    def _output(self, executable: str, root: Path, *arguments: str) -> str:
        result = self._runner.run(
            [executable, "-C", str(root), *arguments],
        )
        if (
            result.returncode != 0
            or result.stdout_truncated
            or result.stderr_truncated
            or bool(result.stderr)
        ):
            raise ContractError("Bounded Git inspection failed.")
        return result.stdout.strip()


class ReleaseCandidateGateService:
    """Evaluate local non-public release-candidate Gate G4."""

    def evaluate(
        self,
        *,
        root: Path,
        baseline: RequirementBaseline,
        ledger: EvidenceLedger,
        review: IndependentReview,
        candidate: ReleaseCandidateInput,
        g2: GateResult,
        g3: GateResult,
        ui: GateResult,
        git: GitObservation,
    ) -> GateResult:
        """Run local audits and evaluate non-compensating Gate G4."""

        repository_findings = audit_repository(
            root,
            publication_paths=git.publication_paths or None,
        )
        dependency_findings = audit_dependencies(root)
        evidence = next(
            (
                item
                for item in ledger.evidence
                if item.evidence_id == candidate.install_evidence_id
            ),
            None,
        )
        expected_install = (
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
            candidate.install_target,
            source_target_for(candidate.install_target),
        )
        reproducible_install = (
            evidence is not None
            and evidence.evidence_type is EvidenceType.TEST
            and evidence.status is EvidenceStatus.PASS
            and evidence.commit == git.head
            and evidence.repository_digest == git.repository_digest
            and evidence.command == expected_install
            and bool(evidence.environment)
            and len(evidence.artifacts) == 1
            and verify_artifact(root, evidence.artifacts[0])
            and _valid_materialized_source(
                root,
                source_target_for(candidate.install_target),
                git.publication_paths,
            )
            and _valid_install_trace(
                root,
                evidence.artifacts[0].path,
                expected_install,
                git,
                candidate.execution_module,
                candidate.install_target,
            )
        )
        must_ids = {
            item.requirement_id
            for item in baseline.requirements
            if item.priority is RequirementPriority.MUST
        }
        verified_must = all(
            any(
                claim.state is ClaimState.VERIFIED
                and requirement_id in claim.requirement_ids
                for claim in ledger.claims
            )
            for requirement_id in must_ids
        )
        documentation_passed = _valid_release_documentation(
            root,
            candidate.documentation_paths,
            git.publication_paths,
        )
        checks = (
            GateCheck(
                "G4-PRIOR-GATES",
                g2.gate_id == "G2"
                and g2.passed
                and g3.gate_id == "G3"
                and g3.passed
                and ui.gate_id == "UI"
                and ui.passed,
                True,
                (
                    "Gates G2, G3, and the applicable UI Gate passed."
                    if (
                        g2.gate_id == "G2"
                        and g2.passed
                        and g3.gate_id == "G3"
                        and g3.passed
                        and ui.gate_id == "UI"
                        and ui.passed
                    )
                    else (
                        f"Observed prior Gates: {g2.gate_id}={g2.passed}, "
                        f"{g3.gate_id}={g3.passed}, {ui.gate_id}={ui.passed}."
                    )
                ),
            ),
            GateCheck(
                "G4-REPRODUCIBLE-INSTALL",
                reproducible_install,
                True,
                "A passing exact-commit installation test is required.",
            ),
            GateCheck(
                "G4-MUST-VERIFIED",
                bool(must_ids) and verified_must,
                True,
                "Every Must requirement requires a verified claim.",
            ),
            GateCheck(
                "G4-SECURITY-AUDIT",
                not repository_findings,
                True,
                (
                    "Repository secret, disclosure, path, language, and link audit passed."
                    if not repository_findings
                    else "; ".join(repository_findings[:3])
                ),
            ),
            GateCheck(
                "G4-DEPENDENCY-LICENSE",
                not dependency_findings
                and candidate.license_status == "not-selected"
                and not any("license" in item.casefold() for item in dependency_findings),
                True,
                (
                    "Runtime, dependency-license, and unselected project-license state passed."
                    if not dependency_findings
                    else f"{len(dependency_findings)} dependency findings exist."
                ),
            ),
            GateCheck(
                "G4-DOCUMENTATION",
                documentation_passed,
                True,
                "Required English release documentation was checked.",
            ),
            GateCheck(
                "G4-ROLLBACK",
                candidate.rollback_guidance
                == (
                    f"Remove only the owned {candidate.install_target} and "
                    f"{source_target_for(candidate.install_target)} directories."
                ),
                True,
                "Rollback guidance names the exact isolated install target.",
            ),
            GateCheck(
                "G4-GIT",
                git.root_matches
                and git.branch == "main"
                and git.clean
                and ledger.git_head == git.head
                and ledger.repository_digest == git.repository_digest
                and review.baseline_id == baseline.baseline_id
                and review.candidate
                == CandidateIdentity(
                    source_spec_sha256=baseline.source.sha256,
                    git_head=git.head,
                    repository_digest=git.repository_digest,
                ),
                True,
                (
                    "Local Git, ledger, review, and repository identities matched."
                    if (
                        git.root_matches
                        and git.branch == "main"
                        and git.clean
                        and ledger.git_head == git.head
                        and ledger.repository_digest == git.repository_digest
                        and review.baseline_id == baseline.baseline_id
                        and review.candidate
                        == CandidateIdentity(
                            source_spec_sha256=baseline.source.sha256,
                            git_head=git.head,
                            repository_digest=git.repository_digest,
                        )
                    )
                    else (
                        f"Git observation: root={git.root_matches}, "
                        f"branch={git.branch}, clean={git.clean}."
                    )
                ),
            ),
        )
        return GateEngine().evaluate("G4", checks)


def _valid_install_trace(
    root: Path,
    path: str,
    expected_command: tuple[str, ...],
    git: GitObservation,
    execution_module: str,
    install_target: str,
) -> bool:
    try:
        payload = load_json_object(
            root.joinpath(*Path(path).parts),
            "Install execution trace",
            maximum_bytes=64 * 1024,
        )
    except ContractError:
        return False
    if set(payload) != {
        "schema_version",
        "trace_type",
        "command",
        "returncode",
        "started_at",
        "finished_at",
        "duration_ms",
        "executable_sha256",
        "python_version",
        "stdout_sha256",
        "stderr_sha256",
        "network_mode",
        "target",
        "target_preexisting",
        "source",
        "source_preexisting",
        "source_repository_digest",
        "execution_command",
        "execution_returncode",
        "execution_duration_ms",
        "execution_stdout_sha256",
        "execution_stderr_sha256",
        "git_head",
        "repository_digest",
    }:
        return False
    started = payload.get("started_at")
    finished = payload.get("finished_at")
    try:
        if not isinstance(started, str) or not isinstance(finished, str):
            return False
        started_at = datetime.fromisoformat(started.replace("Z", "+00:00"))
        finished_at = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        return False
    duration = payload.get("duration_ms")
    execution_duration = payload.get("execution_duration_ms")
    executable_sha256 = payload.get("executable_sha256")
    python_version = payload.get("python_version")
    stdout_sha256 = payload.get("stdout_sha256")
    stderr_sha256 = payload.get("stderr_sha256")
    execution_stdout_sha256 = payload.get("execution_stdout_sha256")
    execution_stderr_sha256 = payload.get("execution_stderr_sha256")
    expected_execution = _execution_probe(execution_module, install_target)
    expected_source = source_target_for(install_target)
    return (
        payload.get("schema_version") == "1.0"
        and payload.get("trace_type") == "bounded-subprocess-v1"
        and payload.get("command") == list(expected_command)
        and payload.get("returncode") == 0
        and started_at.tzinfo is not None
        and finished_at.tzinfo is not None
        and finished_at >= started_at
        and isinstance(duration, int)
        and not isinstance(duration, bool)
        and 0 <= duration <= 300_000
        and isinstance(executable_sha256, str)
        and re.fullmatch(r"[0-9A-F]{64}", executable_sha256) is not None
        and isinstance(python_version, str)
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", python_version) is not None
        and isinstance(stdout_sha256, str)
        and re.fullmatch(r"[0-9A-F]{64}", stdout_sha256) is not None
        and isinstance(stderr_sha256, str)
        and re.fullmatch(r"[0-9A-F]{64}", stderr_sha256) is not None
        and payload.get("network_mode") == "offline"
        and payload.get("target") == install_target
        and payload.get("target_preexisting") is False
        and payload.get("source") == expected_source
        and payload.get("source_preexisting") is False
        and payload.get("source_repository_digest") == git.repository_digest
        and payload.get("execution_command") == list(expected_execution)
        and payload.get("execution_returncode") == 0
        and isinstance(execution_duration, int)
        and not isinstance(execution_duration, bool)
        and 0 <= execution_duration <= 60_000
        and isinstance(execution_stdout_sha256, str)
        and re.fullmatch(r"[0-9A-F]{64}", execution_stdout_sha256) is not None
        and isinstance(execution_stderr_sha256, str)
        and re.fullmatch(r"[0-9A-F]{64}", execution_stderr_sha256) is not None
        and payload.get("git_head") == git.head
        and payload.get("repository_digest") == git.repository_digest
    )


def _execution_probe(module: str, install_target: str) -> tuple[str, ...]:
    """Return the shell-free installed-module execution probe."""

    if (
        not _MODULE.fullmatch(module)
        or safe_relative_path(install_target, "install_target") != install_target
        or not install_target.startswith(".sdaqf/")
    ):
        raise ContractError("Installed execution probe identity is invalid.")
    code = (
        "import importlib.util,pathlib,runpy,sys;"
        f"t=pathlib.Path('{install_target}').resolve();"
        "sys.path.insert(0,str(t));"
        f"s=importlib.util.find_spec('{module}');"
        "assert s is not None and s.origin is not None "
        "and pathlib.Path(s.origin).resolve().is_relative_to(t);"
        f"sys.argv=['{module}','--help'];"
        f"runpy.run_module('{module}',run_name='__main__')"
    )
    return ("python", "-I", "-S", "-c", code)
