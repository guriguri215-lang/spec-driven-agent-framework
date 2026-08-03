import json
import tomllib
from pathlib import Path

import sdaqf
from sdaqf.cli import build_parser
from tests.schema_validation import LocalSchemaValidator
from tests.test_v1_release_readiness import (
    publication_payload,
    release_candidate_payload,
)


def test_v1_schemas_are_versioned_strict_public_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    historical = json.loads(
        (root / "schemas" / "release-candidate.schema.json").read_text(
            encoding="utf-8"
        )
    )
    selected = json.loads(
        (root / "schemas" / "release-candidate-v1.1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    publication = json.loads(
        (root / "schemas" / "public-release-candidate.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert historical["properties"]["schema_version"]["const"] == "1.0"
    assert historical["properties"]["license_status"]["const"] == "not-selected"
    assert selected["properties"]["schema_version"]["const"] == "1.1"
    assert selected["properties"]["license"]["additionalProperties"] is False
    assert publication["properties"]["publication_performed"]["const"] is False
    assert publication["properties"]["actual_gate_g5"]["const"] == "NOT_RUN"
    assert publication["additionalProperties"] is False
    validator = LocalSchemaValidator(root / "schemas")
    validator.validate(
        "release-candidate-v1.1.schema.json",
        release_candidate_payload(),
    )
    validator.validate(
        "public-release-candidate.schema.json",
        publication_payload(
            paths=("docs/releases/v1.0.0-rc.1.md",),
            notes_sha256="A" * 64,
        ),
    )


def test_v1_version_and_template_api_line_are_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    templates = json.loads(
        (root / "examples" / "m2-orchestration" / "template-registry.json").read_text(
            encoding="utf-8"
        )
    )
    args = build_parser().parse_args(
        [
            "skills",
            "validate",
            ".agents/skills",
            "--templates",
            "examples/m2-orchestration/template-registry.json",
        ]
    )

    assert project["project"]["version"] == "1.0.0rc1"
    assert sdaqf.__version__ == "1.0.0rc1"
    assert sdaqf.__all__ == ["GateCheck", "GateResult", "ToolCapability", "ToolStatus"]
    assert templates["templates"][0]["compatible_version"] == "1.0.0"
    assert args.framework_version == "1.0.0"


def test_v1_release_candidate_schema_1_0_remains_unchanged() -> None:
    root = Path(__file__).resolve().parents[1]
    digest = __import__("hashlib").sha256(
        (root / "schemas" / "release-candidate.schema.json").read_bytes()
    )

    assert digest.hexdigest().upper() == (
        "94DE55802C38460581985CC92451C9B73060EF61F93A31964AC14CE1B93D3FF5"
    )


def test_v1_public_documents_share_release_and_support_boundaries() -> None:
    root = Path(__file__).resolve().parents[1]
    documents = tuple(
        (root / relative).read_text(encoding="utf-8")
        for relative in (
            "README.md",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "SUPPORT.md",
            "docs/compatibility.md",
            "docs/contributor-guide.md",
            "docs/open-decisions.md",
            "docs/release-contract.md",
            "docs/roadmap.md",
            "docs/releases/v1.0.0-rc.1.md",
            "docs/exec-plans/active/V1-release-readiness.md",
        )
    )

    for text in documents:
        assert "1.0.0rc1" in text or "v1.0.0-rc.1" in text
    combined = "\n".join(documents)
    for required in (
        "Apache-2.0",
        "guriguri215-lang",
        "not for production use",
        "best effort",
        "no SLA",
        "macOS",
        "NOT_VERIFIED",
        "LOCAL_READY",
        "NOT_RUN",
        "External pull requests",
        "six months",
    ):
        assert required in combined
    assert not (root / "CODE_OF_CONDUCT.md").exists()


def test_v1_public_state_separates_candidate_snapshot_from_post_publication_roadmap() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = (
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "SUPPORT.md",
        "docs/contributor-guide.md",
        "docs/open-decisions.md",
        "docs/release-contract.md",
        "docs/roadmap.md",
        "docs/releases/v1.0.0-rc.1.md",
    )
    documents = {
        relative: " ".join((root / relative).read_text(encoding="utf-8").split())
        for relative in paths
    }
    required_by_path = {
        "README.md": (
            "Status: experimental reference implementation",
            "`v1.0.0-rc.1`",
            "current `main` branch adds the",
            "production-ready",
            "macOS is not verified",
        ),
        "CHANGELOG.md": (
            "was published on 2026-07-31",
            "repository is public",
            "private vulnerability reporting is enabled",
            "release body still contains its approved pre-publication snapshot",
        ),
        "CONTRIBUTING.md": (
            "This public project",
            "not open for external pull requests",
            "best-effort basis",
        ),
        "SECURITY.md": (
            "private vulnerability reporting is enabled",
            "Report a vulnerability",
            "Do not disclose suspected vulnerabilities in a public issue",
        ),
        "SUPPORT.md": (
            "repository is public",
            "private vulnerability reporting is enabled",
            "not intended for production use",
        ),
        "docs/contributor-guide.md": (
            "The public project",
            "Actual Gate G5 passed for the tagged `v1.0.0-rc.1` candidate only",
            "not open for external pull requests",
        ),
        "docs/open-decisions.md": (
            "public repository visibility",
            "private vulnerability reporting enabled",
            "Actual Gate G5 passed for that tagged candidate",
            "remote GitHub release body",
        ),
        "docs/release-contract.md": (
            "## Public push and exact-SHA CI gate",
            "The repository is public",
            "`9f14e2287da3afc078db787e823765320b1e23ac`",
            "actual Gate G5 passed for that candidate",
            "`30603953536`",
            "`30605092668`",
        ),
        "docs/roadmap.md": (
            "Status: `v1.0.0-rc.1` published; Actual Gate G5 passed.",
            "`9f14e2287da3afc078db787e823765320b1e23ac`",
            "annotated tag `v1.0.0-rc.1`",
            "private vulnerability reporting is enabled",
            "not production-ready",
            "macOS remains `NOT_VERIFIED`",
            "final `1.0.0` requires a new candidate and separate approval",
        ),
        "docs/releases/v1.0.0-rc.1.md": (
            "Release status: `PUBLISHED`",
            "`PUBLIC_OBSERVED`",
            "`9f14e2287da3afc078db787e823765320b1e23ac`",
            "private vulnerability reporting is enabled",
            "`30603953536`",
            "macOS remains `NOT_VERIFIED`",
            "not for production use",
            "authored comparison is not empirical, causal",
        ),
    }
    for relative, required_items in required_by_path.items():
        for required in required_items:
            assert required in documents[relative], f"{relative}: {required}"

    stale_by_path = {
        "README.md": (
            "tag `v1.0.0-rc.1` has not been created",
            "private vulnerability reporting has not been enabled",
        ),
        "CHANGELOG.md": ("release remains `NOT_PUBLISHED`",),
        "CONTRIBUTING.md": ("public availability is independently confirmed",),
        "SECURITY.md": ("private vulnerability reporting has not been enabled",),
        "SUPPORT.md": ("private vulnerability reporting has not been enabled",),
        "docs/contributor-guide.md": (
            "public availability is independently confirmed",
        ),
        "docs/open-decisions.md": (
            "current visibility has not been independently observed",
        ),
        "docs/release-contract.md": (
            "immutable private candidate",
            "approved private repository",
            "the approved private `origin/main`",
            "## Private push and exact-SHA CI gate",
            "## Candidate push and exact-SHA CI gate",
            "proposed tag and GitHub release have not been created",
        ),
        "docs/roadmap.md": (
            "post-A7 reconciliation locally verified",
            "no independent post-A7 remote read has observed",
            "tag and GitHub release have not been created",
            "private vulnerability reporting has not been enabled",
            "actual Gate G5 remains `NOT_RUN`",
        ),
        "docs/releases/v1.0.0-rc.1.md": (
            "Release status: `NOT_PUBLISHED`",
            "proposed tag and GitHub release have not been created",
        ),
    }
    for relative, stale_items in stale_by_path.items():
        for stale in stale_items:
            assert stale not in documents[relative], f"{relative}: {stale}"

    historical_plan = " ".join(
        (
            root / "docs" / "exec-plans" / "active" / "V1-release-readiness.md"
        ).read_text(encoding="utf-8").split()
    )
    for historical_fact in (
        "A7_RECONCILIATION_VERIFIED_A3_PENDING",
        "current visibility remains unobserved",
        "actual Gate G5 remains `NOT_RUN`",
    ):
        assert historical_fact in historical_plan
