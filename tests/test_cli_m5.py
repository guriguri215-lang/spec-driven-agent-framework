"""M5 Context CLI contract tests."""

from __future__ import annotations

import contextlib
import io
import json
from dataclasses import replace
from pathlib import Path

from sdaqf.adapters.process import SubprocessRunner
from sdaqf.application.context_contracts import (
    artifact_from_value,
    load_context_artifact,
    serialize_context_artifact,
)
from sdaqf.application.release_qa import GitInspector
from sdaqf.cli import main
from sdaqf.domain.context import (
    ContextArtifactType,
    ContextGraph,
    ContextManifest,
    ContextQuery,
)
from sdaqf.domain.quality import CandidateIdentity
from tests.m5_context_helpers import complete_artifacts


def test_context_cli_end_to_end_is_offline_and_explicit(tmp_path: Path) -> None:
    artifacts = complete_artifacts()
    repository_root = Path(__file__).resolve().parents[1]
    observed = GitInspector(
        SubprocessRunner(timeout_seconds=5, output_limit=1_048_576)
    ).inspect(repository_root)
    manifest_value = artifacts[ContextArtifactType.MANIFEST].value
    assert isinstance(manifest_value, ContextManifest)
    live_candidate = CandidateIdentity(
        source_spec_sha256=manifest_value.candidate.source_spec_sha256,
        git_head=observed.head,
        repository_digest=observed.repository_digest,
    )
    manifest_artifact = artifact_from_value(
        ContextArtifactType.MANIFEST,
        replace(manifest_value, candidate=live_candidate),
    )
    manifest = _write_artifact(
        tmp_path / "manifest.json",
        manifest_artifact,
    )
    validate = _run(["context", "validate", str(manifest), "--json"])
    assert validate["valid"] is True

    graph = tmp_path / "graph.json"
    indexed = _run(
        [
            "context",
            "index",
            str(manifest),
                "--repository-root",
                str(repository_root),
            "--output",
            str(graph),
            "--json",
        ]
    )
    assert indexed["artifact_type"] == "context-graph"

    graph_artifact = load_context_artifact(graph)
    assert isinstance(graph_artifact.value, ContextGraph)
    query_value = artifacts[ContextArtifactType.QUERY].value
    assert isinstance(query_value, ContextQuery)
    query_artifact = artifact_from_value(
        ContextArtifactType.QUERY,
        replace(
            query_value,
            candidate=live_candidate,
            graph_id=graph_artifact.artifact_id,
        ),
    )
    query = _write_artifact(tmp_path / "query.json", query_artifact)
    selection = tmp_path / "selection.json"
    selected = _run(
        [
            "context",
            "select",
            str(graph),
            str(query),
            "--output",
            str(selection),
            "--json",
        ]
    )
    assert selected["artifact_type"] == "context-selection"

    snapshot = tmp_path / "snapshot.json"
    snapped = _run(
        [
            "context",
            "snapshot",
            str(graph),
            str(selection),
            "--repository-root",
            str(repository_root),
            "--output",
            str(snapshot),
            "--json",
        ]
    )
    assert snapped["artifact_type"] == "context-snapshot"
    compared = _run(
        [
            "context",
            "compare",
            str(snapshot),
            str(snapshot),
            "--json",
        ]
    )
    assert compared["added_node_ids"] == []
    assert compared["removed_node_ids"] == []

    compaction = tmp_path / "compaction.json"
    compacted = _run(
        [
            "context",
            "compact",
            str(snapshot),
            "--repository-root",
            str(repository_root),
            "--output",
            str(compaction),
            "--json",
        ]
    )
    assert compacted["artifact_type"] == "context-compaction"
    assert load_context_artifact(compaction).artifact_type is (
        ContextArtifactType.COMPACTION
    )


def test_context_json_failure_uses_stdout_and_preserves_existing_output(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    graph = _write_artifact(
        tmp_path / "graph.json",
        artifacts[ContextArtifactType.GRAPH],
    )
    query = _write_artifact(
        tmp_path / "query.json",
        artifacts[ContextArtifactType.QUERY],
    )
    output = tmp_path / "selection.json"
    output.write_text("owned\n", encoding="utf-8")
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main(
            [
                "context",
                "select",
                str(graph),
                str(query),
                "--output",
                str(output),
                "--json",
            ]
        )
    assert result == 2
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["error"] == "context-contract-invalid"
    assert output.read_text(encoding="utf-8") == "owned\n"


def test_context_index_non_git_root_returns_bounded_json_error(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    manifest = _write_artifact(
        tmp_path / "manifest.json",
        artifacts[ContextArtifactType.MANIFEST],
    )
    non_git_root = tmp_path / "not-a-repository"
    non_git_root.mkdir()
    output = tmp_path / "graph.json"
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main(
            [
                "context",
                "index",
                str(manifest),
                "--repository-root",
                str(non_git_root),
                "--output",
                str(output),
                "--json",
            ]
        )
    assert result == 2
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == {
        "error": "context-contract-invalid",
        "operation": "index",
    }
    assert str(non_git_root) not in stdout.getvalue()
    assert not output.exists()


def _write_artifact(path: Path, artifact: object) -> Path:
    from sdaqf.application.context_contracts import LoadedContextArtifact

    assert isinstance(artifact, LoadedContextArtifact)
    path.write_bytes(serialize_context_artifact(artifact))
    return path


def _run(arguments: list[str]) -> dict[str, object]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main(arguments)
    assert result == 0, stdout.getvalue() + stderr.getvalue()
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert isinstance(payload, dict)
    return payload
