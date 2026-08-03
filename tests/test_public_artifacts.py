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
        "LICENSE",
        "NOTICE",
        "SUPPORT.md",
        "docs/specification.md",
        "docs/architecture.md",
        "docs/roadmap.md",
        "docs/release-contract.md",
        "docs/evidence/M1-verification.md",
        "docs/evidence/M2-verification.md",
        "docs/evidence/M3-verification.md",
        "docs/evidence/M4-verification.md",
        "docs/evidence/M4-platform-evidence.json",
        "docs/exec-plans/active/M1-requirements-planning.md",
        "docs/exec-plans/active/M2-agent-skill-tool-orchestration.md",
        "docs/exec-plans/active/M3-evidence-ui-release-qa.md",
        "docs/exec-plans/active/M4-public-beta-hardening.md",
        "docs/exec-plans/active/V1-release-readiness.md",
        "docs/compatibility.md",
        "docs/implementation-status.md",
        "docs/releases/v1.0.0-rc.1.md",
        "docs/contributor-guide.md",
        "docs/evaluation.md",
        "docs/schema-migrations.md",
        "docs/guides/codex-local-permissions.md",
        "docs/handoffs/M1-goal.md",
    )

    for filename in required:
        content = (root / filename).read_text(encoding="utf-8")
        assert content.strip(), filename

    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "Status: experimental reference implementation" in readme
    assert "## What it does" in readme
    assert "## What it does not do" in readme
    assert "## Quickstart" in readme
    assert "## Validation and evidence" in readme
    assert "docs/implementation-status.md" in readme
    assert (root / "LICENSE").exists()
    assert (root / "NOTICE").exists()


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


def test_m2_schema_and_sample_top_level_contracts_match() -> None:
    root = repository_root()
    pairs = (
        ("agent-registry-v2.schema.json", "agent-registry.json"),
        ("tool-registry-v2.schema.json", "tool-registry.json"),
        ("orchestration-request.schema.json", "orchestration-request.json"),
        ("worktree-plan.schema.json", "worktree-plan.json"),
        ("agent-result.schema.json", "reviewer-result.json"),
        ("template-registry.schema.json", "template-registry.json"),
        ("execution-checkpoint.schema.json", "execution-checkpoint.json"),
        ("execution-checkpoint.schema.json", "completed-checkpoint.json"),
    )

    for schema_name, sample_name in pairs:
        schema = json.loads(
            (root / "schemas" / schema_name).read_text(encoding="utf-8")
        )
        sample = json.loads(
            (root / "examples" / "m2-orchestration" / sample_name).read_text(
                encoding="utf-8"
            )
        )
        assert set(schema["required"]) <= set(sample), sample_name
        expected_version = schema["properties"]["schema_version"]["const"]
        assert sample["schema_version"] == expected_version, sample_name


def test_release_contract_and_ci_share_preserved_gate_commands() -> None:
    root = repository_root()
    release = (root / "docs" / "release-contract.md").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    for command in (
        "scripts/run_cli_smoke.py",
        "scripts/audit_dependencies.py --root .",
        "src/sdaqf/application/orchestration.py",
        "src/sdaqf/application/checkpoints.py",
        "--fail-under=90",
    ):
        assert command in release
        assert command in workflow
    assert 'branches: ["main"]' in workflow
    assert "ref: ${{ github.head_ref || github.ref_name }}" in workflow
    assert "--expected-branch" in workflow
    for command in (
        "src/sdaqf/application/quality_gates.py",
        "src/sdaqf/application/release_qa.py",
        "src/sdaqf/application/evaluation.py",
        "src/sdaqf/application/migrations.py",
        "evals/comparison-suite.json",
    ):
        assert command in release


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
