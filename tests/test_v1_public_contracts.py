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
            "docs/release-contract.md",
            "docs/releases/v1.0.0-rc.1.md",
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
