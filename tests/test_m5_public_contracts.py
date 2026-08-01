"""M5 public CLI, schema, fixture, evaluation, and export contracts."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_m5_context import main as validate_m5

import sdaqf
from sdaqf.application.context_contracts import load_context_artifact
from sdaqf.cli import build_parser
from sdaqf.domain.context import ContextArtifactType
from tests.m5_context_helpers import complete_artifacts

FILES = {
    ContextArtifactType.MANIFEST: "context-manifest.json",
    ContextArtifactType.GRAPH: "context-graph.json",
    ContextArtifactType.QUERY: "context-query.json",
    ContextArtifactType.SELECTION: "context-selection.json",
    ContextArtifactType.SNAPSHOT: "context-snapshot.json",
    ContextArtifactType.COMPACTION: "context-compaction.json",
    ContextArtifactType.HOST_SUMMARY_PROPOSAL: (
        "context-host-summary-proposal.json"
    ),
    ContextArtifactType.QUALITY_REPORT: "context-quality-report.json",
}
SCHEMAS = {
    artifact_type: filename.replace(".json", ".schema.json")
    for artifact_type, filename in FILES.items()
}


def test_public_context_examples_are_exact_golden_artifacts() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = complete_artifacts()
    for artifact_type, filename in FILES.items():
        assert load_context_artifact(
            root / "examples" / "m5-context" / filename,
            expected_type=artifact_type,
        ) == expected[artifact_type]
        schema = json.loads(
            (root / "schemas" / SCHEMAS[artifact_type]).read_text(encoding="utf-8")
        )
        assert schema["properties"]["schema_version"]["const"] == "1.0"
        assert schema["additionalProperties"] is False


def test_context_namespace_has_exact_additive_subcommands() -> None:
    parser = build_parser()
    arguments = {
        "validate": ["context", "validate", "artifact.json"],
        "index": [
            "context",
            "index",
            "manifest.json",
            "--repository-root",
            ".",
            "--output",
            "graph.json",
        ],
        "select": [
            "context",
            "select",
            "graph.json",
            "query.json",
            "--output",
            "selection.json",
        ],
        "snapshot": [
            "context",
            "snapshot",
            "graph.json",
            "selection.json",
            "--repository-root",
            ".",
            "--output",
            "snapshot.json",
        ],
        "compare": ["context", "compare", "base.json", "current.json"],
        "compact": [
            "context",
            "compact",
            "snapshot.json",
            "--repository-root",
            ".",
            "--output",
            "compaction.json",
        ],
    }
    assert {
        parser.parse_args(values).context_command for values in arguments.values()
    } == set(arguments)


def test_public_context_data_contains_no_private_runtime_material() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in (root / "examples" / "m5-context").glob("*.json"):
        content = path.read_text(encoding="utf-8")
        assert "owner-private" not in content
        assert "secret-or-prohibited" not in content
        assert ".sdaqf/" not in content
        assert "state/" not in content
        assert "C:\\\\" not in content


def test_context_evaluation_has_named_cases_and_no_aggregate() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "evals/context-suite.json",
        "evals/results/m5-context-evaluation.json",
    ):
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
        assert len(payload["cases"]) == 7
        assert "aggregate_score" not in payload
        assert "score" not in payload


def test_named_context_validator_passes_from_repository_root() -> None:
    root = Path(__file__).resolve().parents[1]
    import os

    previous = Path.cwd()
    os.chdir(root)
    try:
        assert validate_m5() == 0
    finally:
        os.chdir(previous)


def test_m5_does_not_expand_stable_top_level_exports() -> None:
    assert sdaqf.__all__ == [
        "GateCheck",
        "GateResult",
        "ToolCapability",
        "ToolStatus",
    ]
