import json
import re
from pathlib import Path


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_required_public_documents_exist_and_are_nonempty() -> None:
    root = repository_root()
    required = (
        "README.md",
        "AGENTS.md",
        "PLANS.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "docs/specification.md",
        "docs/architecture.md",
        "docs/roadmap.md",
        "docs/release-contract.md",
        "docs/evidence/M1-verification.md",
        "docs/exec-plans/active/M1-requirements-planning.md",
        "docs/guides/codex-local-permissions.md",
        "docs/handoffs/M1-goal.md",
    )

    for filename in required:
        content = (root / filename).read_text(encoding="utf-8")
        assert content.strip(), filename

    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "Implemented in M0" in readme
    assert "Implemented in M1" in readme
    assert "Not implemented through M1" in readme
    assert not (root / "LICENSE").exists()


def test_git_checkout_preserves_canonical_lf_bytes() -> None:
    attributes = (repository_root() / ".gitattributes").read_text(encoding="utf-8")

    assert attributes == "* text=auto eol=lf\n"


def test_repository_skills_have_required_structure() -> None:
    skills = sorted((repository_root() / ".agents" / "skills").glob("*/SKILL.md"))

    assert len(skills) >= 3
    for skill in skills:
        content = skill.read_text(encoding="utf-8")
        assert content.startswith("---\nname:")
        for heading in (
            "## Trigger",
            "## Do not use",
            "## Procedure",
            "## Output",
            "## Verification",
            "## Risks",
        ):
            assert heading in content, f"{skill.name}: {heading}"


def test_every_json_schema_and_sample_is_valid_json() -> None:
    root = repository_root()
    json_files = tuple((root / "schemas").glob("*.json")) + tuple(
        (root / "examples").rglob("*.json")
    )

    assert json_files
    for path in json_files:
        assert json.loads(path.read_text(encoding="utf-8")) is not None


def test_requirement_schema_rejects_unsafe_source_documents() -> None:
    schema = json.loads(
        (repository_root() / "schemas" / "requirement-record.schema.json").read_text(
            encoding="utf-8"
        )
    )
    pattern = schema["properties"]["source"]["properties"]["document"]["pattern"]

    assert re.fullmatch(pattern, "specification.md")
    for unsafe in (
        "C:\\" + "Users\\person\\spec.md",
        "../spec.md",
        "..",
        "line\nbreak.md",
        "nul\0name.md",
    ):
        assert re.fullmatch(pattern, unsafe) is None


def test_project_codex_config_contains_no_machine_policy() -> None:
    config = (repository_root() / ".codex" / "config.toml").read_text(encoding="utf-8")
    compact = config.casefold()

    for prohibited in (
        "approval_policy =",
        "sandbox_mode =",
        "windows.sandbox",
        "danger-full-access",
        "network_access",
    ):
        assert prohibited not in compact


def test_m1_handoff_preserves_primary_folder_and_safety_gates() -> None:
    handoff = (repository_root() / "docs" / "handoffs" / "M1-goal.md").read_text(
        encoding="utf-8"
    )

    assert "repository root as the Primary folder" in handoff
    assert "parent `state/`" in handoff
    assert "Technical sandbox approval" in handoff
    assert "Owner approval" in handoff
    assert "full access" in handoff
    assert "English" in handoff


def test_public_specification_preserves_every_source_identifier() -> None:
    specification = (repository_root() / "docs" / "specification.md").read_text(
        encoding="utf-8"
    )
    ranges = {
        "G": 10,
        "NG": 7,
        "C": 16,
        "WKS": 16,
        "FR-WKS": 14,
        "FR-REQ": 12,
        "FR-PLN": 10,
        "FR-AGT": 12,
        "FR-TOL": 14,
        "FR-EXE": 13,
        "FR-QA": 14,
        "FR-UI": 12,
        "FR-APR": 16,
        "FR-HOF": 8,
        "FR-GIT": 20,
        "FR-EVL": 7,
        "NFR": 18,
        "AC-M0": 23,
    }

    for prefix, maximum in ranges.items():
        for number in range(1, maximum + 1):
            assert f"`{prefix}-{number:03d}" in specification
    assert "`AC-FR-REQ-001-01`" in specification
