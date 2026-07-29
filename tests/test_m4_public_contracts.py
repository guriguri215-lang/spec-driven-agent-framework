from __future__ import annotations

import json
import tomllib
from pathlib import Path

from sdaqf.application.orchestration import load_agent_registry
from sdaqf.application.tooling import load_tool_registry
from tests.schema_validation import LocalSchemaValidator


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_m4_public_schemas_and_fixtures_match() -> None:
    root = repository_root()
    validator = LocalSchemaValidator(root / "schemas")
    evals = root / "evals"

    validator.validate(
        "evaluation-suite.schema.json",
        json.loads((evals / "comparison-suite.json").read_text(encoding="utf-8")),
    )
    validator.validate(
        "evaluation-result.schema.json",
        json.loads(
            (evals / "results" / "public-beta-comparison.json").read_text(
                encoding="utf-8"
            )
        ),
    )
    for project in ("offline-config", "secure-export", "ui-issue-tracker"):
        project_root = evals / "projects" / project
        validator.validate(
            "evaluation-expectation.schema.json",
            json.loads(
                (project_root / "expected-normalized.json").read_text(
                    encoding="utf-8"
                )
            ),
        )
        for run in ("structured-run.json", "unstructured-run.json"):
            validator.validate(
                "evaluation-run.schema.json",
                json.loads((project_root / run).read_text(encoding="utf-8")),
            )


def test_m4_migration_examples_preserve_legacy_and_current_contracts() -> None:
    root = repository_root()
    validator = LocalSchemaValidator(root / "schemas")
    examples = root / "examples" / "m4-migration"
    pairs = (
        ("agent-registry.schema.json", "agent-registry-v1.json"),
        ("agent-registry-v2.schema.json", "agent-registry-v2.json"),
        ("tool-registry.schema.json", "tool-registry-v1.json"),
        ("tool-registry-v2.schema.json", "tool-registry-v2.json"),
    )
    for schema, fixture in pairs:
        validator.validate(
            schema,
            json.loads((examples / fixture).read_text(encoding="utf-8")),
        )

    assert load_agent_registry(
        examples / "agent-registry-v2.json"
    ).schema_version == "2.0"
    assert load_tool_registry(
        examples / "tool-registry-v2.json"
    ).schema_version == "2.0"


def test_platform_evidence_is_complete_and_truthful_about_verification() -> None:
    root = repository_root()
    evidence = json.loads(
        (
            root / "docs" / "evidence" / "M4-platform-evidence.json"
        ).read_text(encoding="utf-8")
    )
    LocalSchemaValidator(root / "schemas").validate(
        "platform-evidence.schema.json",
        evidence,
    )

    matrix = evidence["matrix"]
    assert {
        (item["platform"], item["python"])
        for item in matrix
    } == {
        ("windows", "3.12"),
        ("windows", "3.13"),
        ("linux", "3.12"),
        ("linux", "3.13"),
    }
    candidate = evidence["candidate"]
    for item in matrix:
        if item["status"] == "PASS":
            assert candidate["git_head"] is not None
            assert candidate["repository_digest"] is not None
            assert item["source"] in {"local", "exact-sha-ci"}
            if item["source"] == "exact-sha-ci":
                assert item["run_id"] is not None
        else:
            assert item["source"] == "not-run"
            assert item["run_id"] is None
    assert evidence["macos"]["status"] in {"PASS", "NOT_VERIFIED"}


def test_m4_plan_traces_requirements_and_criteria() -> None:
    root = repository_root()
    plan = (
        root
        / "docs"
        / "exec-plans"
        / "active"
        / "M4-public-beta-hardening.md"
    ).read_text(encoding="utf-8")

    for number in range(1, 8):
        assert f"`FR-EVL-{number:03d}`" in plan
    for identifier in ("NFR-003", "NFR-012", "FR-GIT-011"):
        assert f"`{identifier}`" in plan
    for number in range(1, 17):
        assert f"`AC-M4-{number:03d}`" in plan
    for heading in (
        "## Objective",
        "## Scope",
        "## Non-goals",
        "## Dependencies, risks, and assumptions",
        "## Checkpoints and validation",
        "## Stop conditions",
        "## Owner approval gates",
    ):
        assert heading in plan


def test_m4_public_documentation_covers_contributor_and_release_boundaries() -> None:
    root = repository_root()
    contributor = (root / "docs" / "contributor-guide.md").read_text(
        encoding="utf-8"
    )
    evaluation = (root / "docs" / "evaluation.md").read_text(encoding="utf-8")
    migration = (root / "docs" / "schema-migrations.md").read_text(
        encoding="utf-8"
    )
    release = (root / "docs" / "release-contract.md").read_text(encoding="utf-8")

    for term in (
        "Setup",
        "Development workflow",
        "Architecture and extension points",
        "Testing",
        "Security",
        "Release limitations",
    ):
        assert term in contributor
    for term in (
        "Input parity",
        "missed requirements",
        "critical defects",
        "aggregate quality score",
        "NOT_VERIFIED",
        "not a statistically powered benchmark",
    ):
        assert term in evaluation
    for term in (
        "Compatibility policy",
        "Conservative defaults",
        "Validation and publication",
        "Failure and rollback",
        "never overwrites",
    ):
        assert term in migration
    for command in (
        "src/sdaqf/domain/evaluation.py",
        "src/sdaqf/application/migrations.py",
        "python -m sdaqf eval validate evals/comparison-suite.json",
        "--fail-under=90",
    ):
        assert command in release


def test_m4_keeps_runtime_dependencies_empty_and_project_license_unselected() -> None:
    root = repository_root()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["dependencies"] == []
    assert not (root / "LICENSE").exists()
    assert not (root / "LICENSE.md").exists()
    assert "No license has been selected" in (root / "README.md").read_text(
        encoding="utf-8"
    )
