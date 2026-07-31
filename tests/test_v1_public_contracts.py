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


def test_v1_public_state_separates_a7_from_release_publication() -> None:
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
        "docs/exec-plans/active/V1-release-readiness.md",
    )
    documents = {
        relative: " ".join((root / relative).read_text(encoding="utf-8").split())
        for relative in paths
    }
    required_by_path = {
        "README.md": (
            "A7 visibility-change command was accepted with exit code `0`",
            "No independent post-A7 remote read",
            "tag `v1.0.0-rc.1` has not been created",
            "GitHub release has not been created",
            "private vulnerability reporting has not been enabled",
            "actual Gate G5 remains `NOT_RUN`",
            "not for production use",
            "macOS `NOT_VERIFIED`",
            "comparison remains nonempirical and noncausal",
        ),
        "CHANGELOG.md": (
            "release remains `NOT_PUBLISHED`",
            "tag `v1.0.0-rc.1` and GitHub release have not been created",
            "A7 visibility-change command was accepted",
            "no independent post-A7 remote read",
            "private vulnerability reporting has not been enabled",
            "actual Gate G5 remains `NOT_RUN`",
        ),
        "CONTRIBUTING.md": (
            "A7 visibility-change command was accepted",
            "no independent post-A7 remote read has confirmed",
            "public availability is independently confirmed",
        ),
        "SECURITY.md": (
            "A7 visibility-change command was accepted",
            "no independent post-A7 remote read has observed",
            "private vulnerability reporting has not been enabled",
        ),
        "SUPPORT.md": (
            "A7 visibility-change command was accepted",
            "no independent post-A7 remote read has confirmed",
            "private vulnerability reporting has not been enabled",
            "not intended for production use",
        ),
        "docs/contributor-guide.md": (
            "A7 visibility-change command was accepted",
            "no independent post-A7 remote read has observed",
            "public availability is independently confirmed",
        ),
        "docs/open-decisions.md": (
            "without an independent post-A7 observation",
            "A7 proves successful command acceptance only",
            "proposed tag, GitHub release, and private vulnerability reporting "
            "remain uncreated or disabled",
            "actual Gate G5 remains `NOT_RUN`",
        ),
        "docs/release-contract.md": (
            "## Potentially public push and exact-SHA CI gate",
            "current repository visibility is unobserved",
            "treated as a potentially public external publication",
            "any future push must be treated as potentially public",
            "do not transfer exact-candidate evidence",
            "Do not repeat the visibility change by inference",
            "proposed tag and GitHub release have not been created",
            "private vulnerability reporting has not been enabled",
            "actual Gate G5 remains `NOT_RUN`",
        ),
        "docs/roadmap.md": (
            "post-A7 reconciliation locally verified",
            "no independent post-A7 remote read has observed",
            "tag and GitHub release have not been created",
            "private vulnerability reporting has not been enabled",
            "actual Gate G5 remains `NOT_RUN`",
        ),
        "docs/releases/v1.0.0-rc.1.md": (
            "`A7_COMMAND_ACCEPTED_POST_A7_NOT_OBSERVED`",
            "Those exact-SHA results do not verify a later candidate",
            "proposed tag and GitHub release have not been created",
            "private vulnerability reporting has not been enabled",
            "actual Gate G5 remains `NOT_RUN`",
            "macOS remains `NOT_VERIFIED`",
            "not for production use",
            "authored comparison is not empirical, causal",
        ),
        "docs/exec-plans/active/V1-release-readiness.md": (
            "A7_RECONCILIATION_VERIFIED_A3_PENDING",
            "30593521851",
            "91040762235",
            "91040762245",
            "91040762248",
            "91040762288",
            "A7 establishes successful command acceptance only",
            "current visibility remains unobserved",
            "did not create the proposed tag or GitHub release",
            "private vulnerability reporting remains disabled",
            "actual Gate G5 remains `NOT_RUN`",
        ),
    }
    for relative, required_items in required_by_path.items():
        for required in required_items:
            assert required in documents[relative], f"{relative}: {required}"

    stale_by_path = {
        "README.md": ("public visibility have not been created or changed",),
        "CONTRIBUTING.md": ("after the repository becomes public",),
        "SECURITY.md": ("is the intended channel only after it is enabled",),
        "SUPPORT.md": ("after the repository becomes public",),
        "docs/contributor-guide.md": (
            "private `1.0.0rc1` finalization phase",
        ),
        "docs/open-decisions.md": (
            "No commit, push, remote observation, visibility change",
        ),
        "docs/release-contract.md": (
            "immutable private candidate",
            "approved private repository",
            "the approved private `origin/main`",
            "## Private push and exact-SHA CI gate",
            "## Candidate push and exact-SHA CI gate",
            "It still requires separate exact approvals",
        ),
        "docs/roadmap.md": (
            "Status: local implementation in progress; publication not performed",
            "public visibility, tag, release, and repository settings remain",
        ),
        "docs/releases/v1.0.0-rc.1.md": (
            "that a tag, release, visibility change, or actual Gate G5 has occurred",
        ),
        "docs/exec-plans/active/V1-release-readiness.md": (
            "`LOCAL_IMPLEMENTATION_VERIFIED_A3_PENDING`",
            "`A7_RECONCILIATION_IMPLEMENTATION_IN_PROGRESS`",
            "`A4 PRIVATE PUSH`",
            "`A4 CANDIDATE PUSH`",
            "private candidate rules",
            "candidate-visibility rules",
            "exact candidate commit, private push",
            "After a local or private pushed commit",
            "The current worktree remains unstaged",
            "has not been observed for V1",
        ),
    }
    for relative, stale_items in stale_by_path.items():
        for stale in stale_items:
            assert stale not in documents[relative], f"{relative}: {stale}"
