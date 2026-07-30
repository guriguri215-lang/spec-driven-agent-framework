"""Offline repository audits and non-compensating release-candidate Gate G4."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tomllib
from datetime import datetime
from pathlib import Path, PurePosixPath

from sdaqf.application.contracts import (
    ContractError,
    array_value,
    boolean_value,
    integer_value,
    load_json_object,
    object_value,
    only_keys,
    parse_artifact_reference,
    parse_candidate_identity,
    safe_relative_path,
    string_tuple,
    string_value,
    verify_artifact,
)
from sdaqf.application.gates import GateEngine
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.models import GateCheck, GateResult
from sdaqf.domain.quality import (
    ArtifactReference,
    CandidateIdentity,
    ClaimState,
    EvidenceLedger,
    EvidenceStatus,
    EvidenceType,
    GitObservation,
    IndependentReview,
    ProjectLicense,
    PublicationReadinessInput,
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
    r"(?:licen[cs]e|copying|notice)(?:\.(?:md|rst|txt))?",
    re.IGNORECASE,
)
_PROJECT_LICENSE_DIRECTORIES = {"licenses", "licences"}
_APPROVED_PROJECT_LICENSES = {
    "LICENSE": "C71D239DF91726FC519C6EB72D318EC65820627232B2F796219E87DCF35D0AB4",
    "NOTICE": "2D2F956085982C50C8E1EC40DBADFAAF36E77FE2B3F3979BD2AFF3E29E1CD01D",
}
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
_REQUIRED_G4_CHECKS = {
    "G4-PRIOR-GATES",
    "G4-REPRODUCIBLE-INSTALL",
    "G4-MUST-VERIFIED",
    "G4-SECURITY-AUDIT",
    "G4-DEPENDENCY-LICENSE",
    "G4-DOCUMENTATION",
    "G4-ROLLBACK",
    "G4-GIT",
}


def _candidate_order_key(root: Path, path: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the historical Windows order with a portable collision tie-breaker."""

    parts = PurePosixPath(path.relative_to(root).as_posix()).parts
    return tuple(part.casefold() for part in parts), parts


def _portable_unique_candidates(
    root: Path,
    files: list[Path],
) -> tuple[Path, ...]:
    by_relative: dict[str, Path] = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        by_relative.setdefault(relative, path)
    return tuple(
        sorted(
            by_relative.values(),
            key=lambda path: _candidate_order_key(root, path),
        )
    )


def candidate_files(
    root: Path,
    publication_paths: tuple[str, ...] | None = None,
) -> tuple[Path, ...]:
    """Return the bounded publication set in portable relative-path order."""

    files: list[Path] = []
    if publication_paths is not None:
        for relative in publication_paths:
            normalized = safe_relative_path(relative, "publication path")
            files.append(root.joinpath(*Path(normalized).parts))
        return _portable_unique_candidates(root, files)
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if any(part in _EXCLUDED_PARTS for part in parts):
            continue
        if path.is_file() or path.is_symlink() or is_reparse_point(path):
            files.append(path)
    return _portable_unique_candidates(root, files)


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
    candidates = candidate_files(root, publication_paths)
    license_material: set[str] = set()
    for path in candidates:
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
            license_material.add(relative)
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
    if license_material:
        expected = set(_APPROVED_PROJECT_LICENSES)
        for relative in sorted(license_material - expected):
            errors.append(f"{relative}: project license material is not approved.")
        for relative in sorted(expected - license_material):
            errors.append(f"{relative}: approved project license material is missing.")
        for relative, expected_digest in _APPROVED_PROJECT_LICENSES.items():
            if relative not in license_material:
                continue
            path = root / relative
            try:
                actual_digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            except OSError:
                actual_digest = ""
            if actual_digest != expected_digest:
                errors.append(
                    f"{relative}: approved project license content does not match."
                )
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
    license_expression = project.get("license")
    license_files = project.get("license-files")
    project_license_paths = {
        path.relative_to(root).as_posix()
        for path in candidate_files(root)
        if _PROJECT_LICENSE_NAME.fullmatch(path.name)
        or any(
            part.casefold() in _PROJECT_LICENSE_DIRECTORIES
            for part in path.relative_to(root).parts[:-1]
        )
    }
    selected_license = bool(
        project_license_paths
        or license_expression is not None
        or license_files is not None
    )
    if selected_license:
        if license_expression != "Apache-2.0":
            errors.append("Project license expression must be Apache-2.0.")
        if license_files != ["LICENSE", "NOTICE"]:
            errors.append("Project license files must be exactly LICENSE and NOTICE.")
        if project_license_paths != set(_APPROVED_PROJECT_LICENSES):
            errors.append("Project license material must match the approved allowlist.")
        for relative, expected_digest in _APPROVED_PROJECT_LICENSES.items():
            path = root / relative
            if _path_or_parent_is_linked(root, path):
                errors.append(f"{relative} must be a regular, unlinked file.")
                continue
            try:
                actual_digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            except OSError:
                actual_digest = ""
            if actual_digest != expected_digest:
                errors.append(f"{relative} does not match the approved content.")
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


def _valid_project_license(root: Path, candidate: ReleaseCandidateInput) -> bool:
    """Require the historical unselected state or the exact selected contract."""

    material = {
        path.relative_to(root).as_posix()
        for path in candidate_files(root)
        if _PROJECT_LICENSE_NAME.fullmatch(path.name)
        or any(
            part.casefold() in _PROJECT_LICENSE_DIRECTORIES
            for part in path.relative_to(root).parts[:-1]
        )
    }
    if candidate.schema_version == "1.0":
        return candidate.license_status == "not-selected" and not material
    return (
        candidate.schema_version == "1.1"
        and candidate.license_status == "selected"
        and candidate.license is not None
        and material == set(_APPROVED_PROJECT_LICENSES)
        and verify_artifact(root, candidate.license.license_file)
        and verify_artifact(root, candidate.license.notice_file)
    )


def _valid_gate_result_artifact(
    root: Path,
    reference: ArtifactReference,
    gate_id: str,
    candidate: CandidateIdentity,
    expected: GateResult | None = None,
) -> bool:
    """Validate one exact, non-compensating serialized Gate result."""

    if not verify_artifact(root, reference, maximum_bytes=64 * 1024):
        return False
    try:
        payload = load_json_object(
            root.joinpath(*Path(reference.path).parts),
            f"{gate_id} result",
            maximum_bytes=64 * 1024,
        )
        only_keys(payload, {"schema_version", "candidate", "result"}, f"{gate_id}_artifact")
        if (
            string_value(payload.get("schema_version"), f"{gate_id}.schema_version")
            != "1.0"
            or parse_candidate_identity(
                payload.get("candidate"),
                f"{gate_id}.candidate",
            )
            != candidate
        ):
            return False
        result = object_value(payload.get("result"), f"{gate_id}.result")
        only_keys(
            result,
            {"gate_id", "passed", "hard_blockers", "checks"},
            f"{gate_id}_result",
        )
        if expected is not None:
            return result == expected.to_dict()
        if (
            string_value(result.get("gate_id"), f"{gate_id}.gate_id") != gate_id
            or not boolean_value(result.get("passed"), f"{gate_id}.passed")
            or array_value(result.get("hard_blockers"), f"{gate_id}.hard_blockers")
        ):
            return False
        checks = array_value(result.get("checks"), f"{gate_id}.checks", maximum=128)
        if not checks:
            return False
        check_ids: set[str] = set()
        for index, value in enumerate(checks):
            check = object_value(value, f"{gate_id}.checks[{index}]")
            only_keys(
                check,
                {"check_id", "passed", "hard_blocker", "evidence"},
                f"{gate_id}.checks[{index}]",
            )
            check_id = string_value(
                check.get("check_id"),
                f"{gate_id}.checks[{index}].check_id",
                maximum=100,
            )
            if (
                check_id in check_ids
                or not boolean_value(
                    check.get("passed"),
                    f"{gate_id}.checks[{index}].passed",
                )
            ):
                return False
            hard_blocker = boolean_value(
                check.get("hard_blocker"),
                f"{gate_id}.checks[{index}].hard_blocker",
            )
            if gate_id == "G4" and not hard_blocker:
                return False
            string_value(
                check.get("evidence"),
                f"{gate_id}.checks[{index}].evidence",
                maximum=4_000,
            )
            check_ids.add(check_id)
        if gate_id == "G4" and check_ids != _REQUIRED_G4_CHECKS:
            return False
    except ContractError:
        return False
    return True


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
    schema_version = string_value(
        root.get("schema_version"),
        "schema_version",
        maximum=10,
    )
    common_keys = {
        "schema_version",
        "install_evidence_id",
        "execution_module",
        "install_target",
        "rollback_guidance",
        "documentation_paths",
    }
    if schema_version == "1.0":
        only_keys(root, common_keys | {"license_status"}, "release_candidate")
    elif schema_version == "1.1":
        only_keys(root, common_keys | {"license"}, "release_candidate")
    else:
        raise ContractError("schema_version must be 1.0 or 1.1.")
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
    license: ProjectLicense | None = None
    if schema_version == "1.0":
        license_status = string_value(
            root.get("license_status"),
            "license_status",
            maximum=50,
        )
        if license_status != "not-selected":
            raise ContractError(
                "Release-candidate schema 1.0 supports only the explicit "
                "not-selected project license state."
            )
    else:
        license_status = "selected"
        license = _parse_project_license(root.get("license"))
    return ReleaseCandidateInput(
        install_evidence_id=evidence_id,
        execution_module=execution_module,
        install_target=install_target,
        rollback_guidance=rollback_guidance,
        documentation_paths=documentation,
        license_status=license_status,
        license=license,
        schema_version=schema_version,
    )


def _parse_project_license(value: object) -> ProjectLicense:
    """Parse the exact Apache-2.0 license decision for schema 1.1."""

    item = object_value(value, "license")
    only_keys(
        item,
        {
            "spdx_expression",
            "copyright_holder",
            "license_file",
            "notice_file",
        },
        "license",
    )
    spdx = string_value(item.get("spdx_expression"), "license.spdx_expression")
    holder = string_value(item.get("copyright_holder"), "license.copyright_holder")
    license_file = parse_artifact_reference(
        item.get("license_file"),
        "license.license_file",
    )
    notice_file = parse_artifact_reference(
        item.get("notice_file"),
        "license.notice_file",
    )
    if (
        spdx != "Apache-2.0"
        or holder != "guriguri215-lang"
        or license_file.path != "LICENSE"
        or license_file.sha256 != _APPROVED_PROJECT_LICENSES["LICENSE"]
        or notice_file.path != "NOTICE"
        or notice_file.sha256 != _APPROVED_PROJECT_LICENSES["NOTICE"]
    ):
        raise ContractError("license does not match the exact Owner-approved contract.")
    return ProjectLicense(
        spdx_expression=spdx,
        copyright_holder=holder,
        license_file=license_file,
        notice_file=notice_file,
    )


def load_publication_readiness(path: Path) -> PublicationReadinessInput:
    """Load one exact, offline-only V1 publication-readiness declaration."""

    root = load_json_object(path, "Public release candidate", maximum_bytes=256 * 1024)
    only_keys(
        root,
        {
            "schema_version",
            "candidate",
            "project",
            "license",
            "release",
            "policies",
            "verification",
            "publication_performed",
            "actual_gate_g5",
        },
        "public_release_candidate",
    )
    if string_value(root.get("schema_version"), "schema_version") != "1.0":
        raise ContractError("Public release candidate schema_version must be 1.0.")

    candidate_object = object_value(root.get("candidate"), "candidate")
    only_keys(
        candidate_object,
        {"identity", "branch", "publication_paths"},
        "candidate",
    )
    candidate = parse_candidate_identity(candidate_object.get("identity"), "candidate.identity")
    branch = _literal(candidate_object.get("branch"), "candidate.branch", "main")
    paths = tuple(
        safe_relative_path(item, f"candidate.publication_paths[{index}]")
        for index, item in enumerate(
            array_value(
                candidate_object.get("publication_paths"),
                "candidate.publication_paths",
                maximum=4_096,
            )
        )
    )
    if not paths or paths != tuple(sorted(set(paths))):
        raise ContractError("candidate.publication_paths must be sorted and unique.")

    project = object_value(root.get("project"), "project")
    only_keys(
        project,
        {
            "name",
            "repository",
            "distribution",
            "cli",
            "version",
            "proposed_tag",
            "desired_visibility",
            "default_branch",
            "target_public_api",
        },
        "project",
    )
    for field, expected in {
        "name": "SDAQF",
        "repository": "spec-driven-agent-framework",
        "distribution": "sdaqf",
        "cli": "sdaqf",
        "version": "1.0.0rc1",
        "proposed_tag": "v1.0.0-rc.1",
        "desired_visibility": "PUBLIC",
        "default_branch": "main",
        "target_public_api": "1.0.0",
    }.items():
        _literal(project.get(field), f"project.{field}", expected)

    _parse_project_license(root.get("license"))

    release = object_value(root.get("release"), "release")
    only_keys(
        release,
        {
            "level",
            "audience",
            "title",
            "description",
            "notes",
            "prerelease",
            "latest",
            "attached_assets",
            "package_registry_publication",
            "source_archives",
        },
        "release",
    )
    for field, expected in {
        "level": "release-candidate-prerelease",
        "title": "SDAQF v1.0.0-rc.1",
        "description": (
            "Offline-first specification-driven development and quality assurance "
            "for Codex-assisted projects."
        ),
        "source_archives": "GitHub-provided tag archives only",
    }.items():
        _literal(release.get(field), f"release.{field}", expected)
    if string_tuple(release.get("audience"), "release.audience", minimum=2) != (
        "framework evaluators",
        "advanced Codex users",
    ):
        raise ContractError("release.audience does not match the Owner decision.")
    if not boolean_value(release.get("prerelease"), "release.prerelease"):
        raise ContractError("release.prerelease must be true.")
    if boolean_value(release.get("latest"), "release.latest"):
        raise ContractError("release.latest must be false.")
    if array_value(release.get("attached_assets"), "release.attached_assets"):
        raise ContractError("release.attached_assets must be empty.")
    if boolean_value(
        release.get("package_registry_publication"),
        "release.package_registry_publication",
    ):
        raise ContractError("release.package_registry_publication must be false.")
    notes = parse_artifact_reference(release.get("notes"), "release.notes")
    if notes.path != "docs/releases/v1.0.0-rc.1.md":
        raise ContractError("release.notes.path does not match the approved release.")

    _validate_publication_policies(root.get("policies"))
    verification = object_value(root.get("verification"), "verification")
    only_keys(
        verification,
        {
            "gates",
            "independent_review",
            "required_matrix",
            "macos",
        },
        "verification",
    )
    gates = object_value(verification.get("gates"), "verification.gates")
    only_keys(gates, {"G1", "G2", "G3", "G4"}, "verification.gates")
    gate_results_list: list[tuple[str, str]] = []
    gate_evidence_list: list[tuple[str, ArtifactReference]] = []
    for gate_id in ("G1", "G2", "G3", "G4"):
        gate = object_value(gates.get(gate_id), f"verification.gates.{gate_id}")
        only_keys(gate, {"status", "evidence"}, f"verification.gates.{gate_id}")
        status = _literal(
            gate.get("status"),
            f"verification.gates.{gate_id}.status",
            "PASS",
        )
        evidence = parse_artifact_reference(
            gate.get("evidence"),
            f"verification.gates.{gate_id}.evidence",
        )
        expected_path = f".sdaqf/v1/gates/{gate_id}.json"
        if evidence.path != expected_path:
            raise ContractError(
                f"verification.gates.{gate_id}.evidence.path is not exact."
            )
        gate_results_list.append((gate_id, status))
        gate_evidence_list.append((gate_id, evidence))
    gate_results = tuple(gate_results_list)
    matrix = string_tuple(
        verification.get("required_matrix"),
        "verification.required_matrix",
        minimum=4,
    )
    if matrix != (
        "windows-python-3.12",
        "windows-python-3.13",
        "linux-python-3.12",
        "linux-python-3.13",
    ):
        raise ContractError("verification.required_matrix does not match the contract.")
    _literal(verification.get("macos"), "verification.macos", "NOT_VERIFIED")

    review = object_value(
        verification.get("independent_review"),
        "verification.independent_review",
    )
    only_keys(
        review,
        {"baseline_id", "candidate", "decision", "unresolved_findings"},
        "verification.independent_review",
    )
    review_baseline_id = string_value(
        review.get("baseline_id"),
        "verification.independent_review.baseline_id",
        maximum=100,
    )
    review_candidate = parse_candidate_identity(
        review.get("candidate"),
        "verification.independent_review.candidate",
    )
    review_decision = _literal(
        review.get("decision"),
        "verification.independent_review.decision",
        "GO",
    )
    unresolved = object_value(
        review.get("unresolved_findings"),
        "verification.independent_review.unresolved_findings",
    )
    only_keys(
        unresolved,
        {"Critical", "High", "Medium", "Low"},
        "verification.independent_review.unresolved_findings",
    )
    unresolved_findings = tuple(
        (
            severity,
            integer_value(
                unresolved.get(severity),
                f"verification.independent_review.unresolved_findings.{severity}",
                minimum=0,
                maximum=10_000,
            ),
        )
        for severity in ("Critical", "High", "Medium", "Low")
    )
    if any(count for _, count in unresolved_findings):
        raise ContractError("independent review must have no unresolved findings.")

    publication_performed = boolean_value(
        root.get("publication_performed"),
        "publication_performed",
    )
    if publication_performed:
        raise ContractError("Local readiness cannot claim publication was performed.")
    actual_gate_g5 = _literal(root.get("actual_gate_g5"), "actual_gate_g5", "NOT_RUN")
    return PublicationReadinessInput(
        candidate=candidate,
        branch=branch,
        publication_paths=paths,
        release_notes=notes,
        review_candidate=review_candidate,
        review_baseline_id=review_baseline_id,
        review_decision=review_decision,
        gate_results=gate_results,
        gate_evidence=tuple(gate_evidence_list),
        unresolved_findings=unresolved_findings,
        publication_performed=publication_performed,
        actual_gate_g5=actual_gate_g5,
    )


def _literal(value: object, where: str, expected: str) -> str:
    text = string_value(value, where, maximum=1_000)
    if text != expected:
        raise ContractError(f"{where} does not match the approved value.")
    return text


def _validate_publication_policies(value: object) -> None:
    policies = object_value(value, "policies")
    only_keys(
        policies,
        {
            "compatibility",
            "migration",
            "rollback",
            "support",
            "security",
            "maintenance",
            "contributions",
            "code_of_conduct",
            "known_limitations",
        },
        "policies",
    )
    expected_values = {
        "compatibility": (
            "Target V1 public API; prerelease compatibility is not guaranteed "
            "until 1.0.0."
        ),
        "migration": (
            "No migration is required from the M4 Public Beta CLI; validate "
            "versioned schemas before reuse."
        ),
        "rollback": (
            "Discard the unpublished local candidate; never delete or move a "
            "published tag automatically."
        ),
        "support": (
            "GitHub Issues for bugs and documentation; best effort, no SLA, "
            "latest release only."
        ),
        "security": (
            "Use GitHub private vulnerability reporting after separately approved "
            "enablement when public; do not disclose vulnerabilities in public issues."
        ),
        "maintenance": (
            "No prerelease backports; final 1.0.0 receives best-effort Critical "
            "security and data-loss fixes for six months."
        ),
        "contributions": (
            "External pull requests are not accepted during the release candidate; "
            "bug and documentation issues are best effort."
        ),
        "code_of_conduct": "DEFERRED_UNTIL_OPEN_CONTRIBUTIONS",
    }
    for field, expected in expected_values.items():
        _literal(policies.get(field), f"policies.{field}", expected)
    limitations = string_tuple(
        policies.get("known_limitations"),
        "policies.known_limitations",
        minimum=5,
    )
    if limitations != (
        "Release candidate; not for production use.",
        "macOS is not verified.",
        "OpenAI API or Agents SDK adapter is deferred post-V1.",
        "Management UI is deferred post-V1.",
        (
            "Authored comparison is not empirical, causal, blinded, randomized, "
            "independently replicated, statistically powered, or cost-comparable."
        ),
    ):
        raise ContractError("policies.known_limitations does not match the contract.")


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
        project_license_passed = _valid_project_license(root, candidate)
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
                and project_license_passed
                and not any("license" in item.casefold() for item in dependency_findings),
                True,
                (
                    "Runtime, dependency-license, and exact project-license state passed."
                    if not dependency_findings and project_license_passed
                    else (
                        f"{len(dependency_findings)} dependency findings exist."
                        if dependency_findings
                        else "Project-license state does not match the candidate."
                    )
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


class PublicationReadinessService:
    """Evaluate offline local readiness without performing or claiming Gate G5."""

    def evaluate(
        self,
        *,
        root: Path,
        baseline: RequirementBaseline,
        ledger: EvidenceLedger,
        review: IndependentReview,
        declaration: PublicationReadinessInput,
        release_candidate: ReleaseCandidateInput,
        g1: GateResult,
        g2: GateResult,
        g3: GateResult,
        git: GitObservation,
    ) -> GateResult:
        """Return a non-compensating local result whose success is LOCAL_READY."""

        identity = CandidateIdentity(
            source_spec_sha256=baseline.source.sha256,
            git_head=git.head,
            repository_digest=git.repository_digest,
        )
        recorded_gates = dict(declaration.gate_results)
        recorded_gate_evidence = dict(declaration.gate_evidence)
        actual_gates = {"G1": g1, "G2": g2, "G3": g3}
        identity_passed = (
            git.root_matches
            and git.branch == "main"
            and git.clean
            and declaration.branch == "main"
            and declaration.candidate == identity
            and declaration.review_candidate == identity
            and declaration.publication_paths == git.publication_paths
            and declaration.release_notes.path in git.publication_paths
        )
        evidence_passed = (
            ledger.baseline_id == baseline.baseline_id
            and ledger.source_spec_sha256 == baseline.source.sha256
            and ledger.git_head == git.head
            and ledger.repository_digest == git.repository_digest
            and review.baseline_id == baseline.baseline_id
            and review.candidate == identity
            and declaration.review_baseline_id == baseline.baseline_id
            and declaration.review_decision == "GO"
            and not any(dict(declaration.unresolved_findings).values())
        )
        gate_passed = (
            recorded_gates
            == {"G1": "PASS", "G2": "PASS", "G3": "PASS", "G4": "PASS"}
            and g1.gate_id == "G1"
            and g1.passed
            and g2.gate_id == "G2"
            and g2.passed
            and g3.gate_id == "G3"
            and g3.passed
            and set(recorded_gate_evidence) == {"G1", "G2", "G3", "G4"}
            and all(
                _valid_gate_result_artifact(
                    root,
                    recorded_gate_evidence[gate_id],
                    gate_id,
                    identity,
                    actual_gates.get(gate_id),
                )
                for gate_id in ("G1", "G2", "G3", "G4")
            )
        )
        license_passed = (
            release_candidate.schema_version == "1.1"
            and _valid_project_license(root, release_candidate)
            and not audit_dependencies(root)
            and not audit_repository(
                root,
                publication_paths=git.publication_paths or None,
            )
        )
        publication_boundary_passed = (
            declaration.publication_performed is False
            and declaration.actual_gate_g5 == "NOT_RUN"
        )
        checks = (
            GateCheck(
                "LOCAL-IDENTITY",
                identity_passed,
                True,
                "Branch, exact candidate identity, notes, and complete path set must match.",
            ),
            GateCheck(
                "LOCAL-EVIDENCE",
                evidence_passed,
                True,
                "Baseline, ledger, and independent-review identities must match.",
            ),
            GateCheck(
                "LOCAL-GATES-G1-G4",
                gate_passed,
                True,
                (
                    "G1 through G4 exact result artifacts must be recorded PASS; "
                    "G1 through G3 are re-evaluated."
                ),
            ),
            GateCheck(
                "LOCAL-LICENSE-PUBLICATION-AUDIT",
                license_passed,
                True,
                "Exact Apache-2.0 material and local publication audits must pass.",
            ),
            GateCheck(
                "LOCAL-RELEASE-NOTES",
                verify_artifact(root, declaration.release_notes),
                True,
                "The approved release-notes path and digest must match.",
            ),
            GateCheck(
                "LOCAL-NO-PUBLICATION",
                publication_boundary_passed,
                True,
                "Local readiness requires publication_performed=false and G5 NOT_RUN.",
            ),
        )
        return GateEngine().evaluate("G5-LOCAL-READINESS", checks)


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
