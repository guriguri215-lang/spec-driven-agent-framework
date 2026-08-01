"""M5 deterministic required/graph/identifier/lexical selection tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sdaqf.adapters.context import CanonicalUTF8ByteEstimator
from sdaqf.application.context_contracts import (
    artifact_from_value,
    edge_identity,
    node_identity,
    source_identity,
)
from sdaqf.application.context_selection import (
    ContextSelectionError,
    ContextSelector,
    lexical_score,
    lexical_tokens,
)
from sdaqf.domain.context import (
    ContextArtifactType,
    ContextEdge,
    ContextGraph,
    ContextQuery,
    ContextSelection,
    EdgeType,
    Sensitivity,
)
from tests.m5_context_helpers import complete_artifacts


def test_selection_is_deterministic_and_required_context_is_present() -> None:
    artifacts = complete_artifacts()
    selector = ContextSelector(CanonicalUTF8ByteEstimator())
    first = selector.select(
        artifacts[ContextArtifactType.GRAPH],
        artifacts[ContextArtifactType.QUERY],
    )
    second = selector.select(
        artifacts[ContextArtifactType.GRAPH],
        artifacts[ContextArtifactType.QUERY],
    )
    assert first == second
    assert isinstance(first.value, ContextSelection)
    selected = {item.node_id for item in first.value.selected}
    graph = artifacts[ContextArtifactType.GRAPH].value
    assert isinstance(graph, ContextGraph)
    assert {item.node_id for item in graph.nodes if item.required} <= selected
    assert first.value.used_bytes <= first.value.budget_bytes
    assert first.value.used_bytes == (
        sum(item.cost_bytes for item in first.value.selected)
        + first.value.edge_cost_bytes
    )


def test_required_context_over_byte_budget_fails_closed() -> None:
    artifacts = complete_artifacts()
    query_artifact = artifacts[ContextArtifactType.QUERY]
    graph = artifacts[ContextArtifactType.GRAPH].value
    assert isinstance(query_artifact.value, ContextQuery)
    assert isinstance(graph, ContextGraph)
    query = replace(
        query_artifact.value,
        required_node_ids=tuple(node.node_id for node in graph.nodes),
        budget=replace(query_artifact.value.budget, budget_bytes=1024),
    )
    query_artifact = artifact_from_value(ContextArtifactType.QUERY, query)
    with pytest.raises(ContextSelectionError, match="Required context exceeds"):
        ContextSelector(CanonicalUTF8ByteEstimator()).select(
            artifacts[ContextArtifactType.GRAPH],
            query_artifact,
        )


def test_required_context_above_clearance_fails_closed() -> None:
    artifacts = complete_artifacts()
    graph_artifact = artifacts[ContextArtifactType.GRAPH]
    assert isinstance(graph_artifact.value, ContextGraph)
    required = next(node for node in graph_artifact.value.nodes if node.required)
    changed_node = replace(required, sensitivity=Sensitivity.OWNER_PRIVATE)
    changed_node = replace(
        changed_node,
        source_id=source_identity(changed_node.source_content_dict()),
    )
    changed_node = replace(
        changed_node,
        node_id=node_identity(changed_node.content_dict()),
    )
    nodes = tuple(
        sorted(
            (
                changed_node,
                *(node for node in graph_artifact.value.nodes if node is not required),
            ),
            key=lambda item: item.node_id,
        )
    )
    graph = replace(
        graph_artifact.value,
        sensitivity=Sensitivity.OWNER_PRIVATE,
        nodes=nodes,
        edges=(),
    )
    changed_graph = artifact_from_value(ContextArtifactType.GRAPH, graph)
    query_artifact = artifacts[ContextArtifactType.QUERY]
    assert isinstance(query_artifact.value, ContextQuery)
    query = replace(
        query_artifact.value,
        graph_id=changed_graph.artifact_id,
        required_node_ids=(changed_node.node_id,),
        seed_node_ids=(),
        clearance=Sensitivity.PUBLIC,
    )
    with pytest.raises(ContextSelectionError, match="sensitivity-clearance"):
        ContextSelector(CanonicalUTF8ByteEstimator()).select(
            changed_graph,
            artifact_from_value(ContextArtifactType.QUERY, query),
        )


def test_contradiction_forces_both_endpoints_and_edge() -> None:
    artifacts = complete_artifacts()
    graph_artifact = artifacts[ContextArtifactType.GRAPH]
    assert isinstance(graph_artifact.value, ContextGraph)
    first, second = graph_artifact.value.nodes[:2]
    source_id, target_id = sorted((first.node_id, second.node_id))
    edge = ContextEdge(
        edge_id="",
        edge_type=EdgeType.CONTRADICTS,
        source_node_id=source_id,
        target_node_id=target_id,
        provenance=first.provenance,
    )
    edge = replace(edge, edge_id=edge_identity(edge.content_dict()))
    graph = replace(graph_artifact.value, edges=(edge,))
    graph_artifact = artifact_from_value(ContextArtifactType.GRAPH, graph)
    query_artifact = artifacts[ContextArtifactType.QUERY]
    assert isinstance(query_artifact.value, ContextQuery)
    query = replace(
        query_artifact.value,
        graph_id=graph_artifact.artifact_id,
        required_node_ids=(first.node_id,),
        seed_node_ids=(),
        identifiers=(),
        terms=(),
        allowed_edge_types=(EdgeType.CONTRADICTS,),
    )
    selection = ContextSelector(CanonicalUTF8ByteEstimator()).select(
        graph_artifact,
        artifact_from_value(ContextArtifactType.QUERY, query),
    )
    assert isinstance(selection.value, ContextSelection)
    assert {
        first.node_id,
        second.node_id,
    } <= {item.node_id for item in selection.value.selected}
    assert selection.value.unresolved_contradiction_ids == (edge.edge_id,)


def test_optional_identifier_match_forces_atomic_contradiction_closure() -> None:
    artifacts = complete_artifacts()
    graph_artifact = artifacts[ContextArtifactType.GRAPH]
    query_artifact = artifacts[ContextArtifactType.QUERY]
    assert isinstance(graph_artifact.value, ContextGraph)
    assert isinstance(query_artifact.value, ContextQuery)
    required = next(node for node in graph_artifact.value.nodes if node.required)
    optional = [node for node in graph_artifact.value.nodes if not node.required]
    first, second = optional
    source_id, target_id = sorted((first.node_id, second.node_id))
    edge = ContextEdge(
        edge_id="",
        edge_type=EdgeType.CONTRADICTS,
        source_node_id=source_id,
        target_node_id=target_id,
        provenance=first.provenance,
    )
    edge = replace(edge, edge_id=edge_identity(edge.content_dict()))
    graph_artifact = artifact_from_value(
        ContextArtifactType.GRAPH,
        replace(graph_artifact.value, edges=(edge,)),
    )
    query = replace(
        query_artifact.value,
        graph_id=graph_artifact.artifact_id,
        required_node_ids=(required.node_id,),
        seed_node_ids=(),
        identifiers=(first.identifiers[0],),
        terms=(),
        allowed_edge_types=(EdgeType.REFERENCES,),
    )
    selection = ContextSelector(CanonicalUTF8ByteEstimator()).select(
        graph_artifact,
        artifact_from_value(ContextArtifactType.QUERY, query),
    )
    assert isinstance(selection.value, ContextSelection)
    selected = {item.node_id: item for item in selection.value.selected}
    assert {first.node_id, second.node_id} <= selected.keys()
    assert "contradiction-closure" in selected[second.node_id].reasons
    assert selection.value.unresolved_contradiction_ids == (edge.edge_id,)


def test_graph_depth_bound_is_a_blocker_not_silent_truncation() -> None:
    artifacts = complete_artifacts()
    graph_artifact = artifacts[ContextArtifactType.GRAPH]
    query_artifact = artifacts[ContextArtifactType.QUERY]
    assert isinstance(graph_artifact.value, ContextGraph)
    assert isinstance(query_artifact.value, ContextQuery)
    required = next(node for node in graph_artifact.value.nodes if node.required)
    optional = next(node for node in graph_artifact.value.nodes if not node.required)
    edge = ContextEdge(
        edge_id="",
        edge_type=EdgeType.REFERENCES,
        source_node_id=required.node_id,
        target_node_id=optional.node_id,
        provenance=required.provenance,
    )
    edge = replace(edge, edge_id=edge_identity(edge.content_dict()))
    graph_artifact = artifact_from_value(
        ContextArtifactType.GRAPH,
        replace(graph_artifact.value, edges=(edge,)),
    )
    query = replace(
        query_artifact.value,
        graph_id=graph_artifact.artifact_id,
        required_node_ids=(edge.source_node_id,),
        seed_node_ids=(),
        allowed_edge_types=(edge.edge_type,),
        budget=replace(query_artifact.value.budget, max_traversal_depth=0),
    )
    with pytest.raises(ContextSelectionError, match="depth bound"):
        ContextSelector(CanonicalUTF8ByteEstimator()).select(
            graph_artifact,
            artifact_from_value(ContextArtifactType.QUERY, query),
        )


def test_lexical_baseline_is_exact_and_unicode_database_independent() -> None:
    assert lexical_tokens("ABC_def-42 \u4ed5\u69d8") == (
        "abc",
        "def",
        "42",
        "\u4ed5",
        "\u69d8",
    )
    graph = complete_artifacts()[ContextArtifactType.GRAPH].value
    assert isinstance(graph, ContextGraph)
    specification = next(
        node for node in graph.nodes if "FR-M5-001" in node.identifiers
    )
    tokens = set(lexical_tokens("Context validate"))
    assert lexical_score(specification, tokens) == 14
