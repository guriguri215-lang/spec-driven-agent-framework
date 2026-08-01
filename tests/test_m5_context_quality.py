"""M5 named non-aggregate Context quality tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sdaqf.application.context_contracts import artifact_from_value
from sdaqf.application.context_quality import (
    ContextQualityError,
    measure_context_quality,
)
from sdaqf.domain.context import (
    ContextArtifactType,
    ContextGraph,
    ContextQualityReport,
    ContextSelection,
    ContextSnapshot,
)
from tests.m5_context_helpers import complete_artifacts


def test_quality_report_has_named_measurements_and_no_aggregate() -> None:
    artifacts = complete_artifacts()
    report = measure_context_quality(
        artifacts[ContextArtifactType.GRAPH],
        artifacts[ContextArtifactType.SELECTION],
        artifacts[ContextArtifactType.SNAPSHOT],
    )
    assert isinstance(report.value, ContextQualityReport)
    payload = report.to_dict()["content"]
    assert isinstance(payload, dict)
    assert payload["required_reference_recall"] == 100
    assert payload["provenance_missing_count"] == 0
    assert "aggregate_score" not in payload
    assert "score" not in payload
    snapshot = artifacts[ContextArtifactType.SNAPSHOT].value
    assert isinstance(snapshot, ContextSnapshot)
    assert report.value.candidate == snapshot.candidate
    assert report.value.sensitivity == snapshot.sensitivity


def test_quality_rejects_mismatched_selection_identity() -> None:
    artifacts = complete_artifacts()
    selection_artifact = artifacts[ContextArtifactType.SELECTION]
    assert isinstance(selection_artifact.value, ContextSelection)
    changed = replace(
        selection_artifact.value,
        graph_id="CTX-GRAPH-" + "0" * 64,
    )
    with pytest.raises(ContextQualityError, match="identities"):
        measure_context_quality(
            artifacts[ContextArtifactType.GRAPH],
            artifact_from_value(ContextArtifactType.SELECTION, changed),
            artifacts[ContextArtifactType.SNAPSHOT],
        )


def test_quality_rejects_candidate_mismatch_across_inputs() -> None:
    artifacts = complete_artifacts()
    graph_artifact = artifacts[ContextArtifactType.GRAPH]
    assert isinstance(graph_artifact.value, ContextGraph)
    changed_graph = artifact_from_value(
        ContextArtifactType.GRAPH,
        replace(
            graph_artifact.value,
            candidate=replace(
                graph_artifact.value.candidate,
                repository_digest="D" * 64,
            ),
        ),
    )
    selection_artifact = artifacts[ContextArtifactType.SELECTION]
    assert isinstance(selection_artifact.value, ContextSelection)
    changed_selection = artifact_from_value(
        ContextArtifactType.SELECTION,
        replace(
            selection_artifact.value,
            graph_id=changed_graph.artifact_id,
            query=replace(
                selection_artifact.value.query,
                graph_id=changed_graph.artifact_id,
            ),
        ),
    )
    snapshot_artifact = artifacts[ContextArtifactType.SNAPSHOT]
    assert isinstance(snapshot_artifact.value, ContextSnapshot)
    changed_snapshot = artifact_from_value(
        ContextArtifactType.SNAPSHOT,
        replace(
            snapshot_artifact.value,
            graph_id=changed_graph.artifact_id,
            selection_id=changed_selection.artifact_id,
        ),
    )
    with pytest.raises(ContextQualityError, match="identities"):
        measure_context_quality(
            changed_graph,
            changed_selection,
            changed_snapshot,
        )
