"""Named non-aggregate M5 Context quality measurements."""

from __future__ import annotations

from sdaqf.application.context_contracts import (
    ContextContractError,
    LoadedContextArtifact,
    artifact_from_value,
    parse_context_artifact_bytes,
    serialize_context_artifact,
)
from sdaqf.domain.context import (
    SENSITIVITY_RANK,
    ContextArtifactType,
    ContextGraph,
    ContextQualityReport,
    ContextSelection,
    ContextSnapshot,
)


class ContextQualityError(ContextContractError):
    """Quality inputs are not identity-compatible."""


def measure_context_quality(
    graph_artifact: LoadedContextArtifact,
    selection_artifact: LoadedContextArtifact,
    snapshot_artifact: LoadedContextArtifact,
) -> LoadedContextArtifact:
    """Return exact named Context quality measurements without an aggregate."""

    if (
        graph_artifact.artifact_type is not ContextArtifactType.GRAPH
        or not isinstance(graph_artifact.value, ContextGraph)
        or selection_artifact.artifact_type
        is not ContextArtifactType.SELECTION
        or not isinstance(selection_artifact.value, ContextSelection)
        or snapshot_artifact.artifact_type is not ContextArtifactType.SNAPSHOT
        or not isinstance(snapshot_artifact.value, ContextSnapshot)
    ):
        raise ContextQualityError(
            "Context quality requires Graph, Selection, and Snapshot."
        )
    graph = graph_artifact.value
    selection = selection_artifact.value
    snapshot = snapshot_artifact.value
    if (
        selection.graph_id != graph_artifact.artifact_id
        or snapshot.graph_id != graph_artifact.artifact_id
        or snapshot.selection_id != selection_artifact.artifact_id
        or snapshot.query_id != selection.query_id
        or graph.candidate != selection.candidate
        or graph.candidate != snapshot.candidate
    ):
        raise ContextQualityError("Context quality input identities do not match.")
    required = {
        node.node_id for node in graph.nodes if node.required
    } | set(selection.query.required_node_ids)
    selected = {node.node_id for node in snapshot.nodes}
    recall = 100 if not required else (100 * len(required & selected)) // len(required)
    provenance_complete = sum(
        bool(node.provenance.references) for node in snapshot.nodes
    )
    sensitivity_violations = sum(
        SENSITIVITY_RANK[node.sensitivity] > SENSITIVITY_RANK[snapshot.sensitivity]
        for node in snapshot.nodes
    )
    seen_text: set[bytes] = set()
    redundant = 0
    for node in snapshot.nodes:
        encoded = node.text.encode("utf-8")
        if encoded in seen_text:
            redundant += len(encoded)
        else:
            seen_text.add(encoded)
    report = ContextQualityReport(
        candidate=snapshot.candidate,
        snapshot_id=snapshot_artifact.artifact_id,
        sensitivity=snapshot.sensitivity,
        required_reference_recall=recall,
        stale_required_count=0,
        provenance_complete_count=provenance_complete,
        provenance_missing_count=len(snapshot.nodes) - provenance_complete,
        sensitivity_violation_count=sensitivity_violations,
        selected_context_bytes=snapshot.context_bytes,
        budget_bytes=selection.budget_bytes,
        redundant_bytes=redundant,
        selected_node_count=len(snapshot.nodes),
        excluded_node_count=len(snapshot.excluded),
        unresolved_contradiction_count=len(
            snapshot.unresolved_contradiction_ids
        ),
        traversal_truncated=selection.traversal_truncated,
    )
    artifact = artifact_from_value(ContextArtifactType.QUALITY_REPORT, report)
    return parse_context_artifact_bytes(
        serialize_context_artifact(artifact),
        expected_type=ContextArtifactType.QUALITY_REPORT,
    )
