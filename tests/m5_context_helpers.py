"""Deterministic M5 Context fixture builders."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from sdaqf.adapters.context import CanonicalUTF8ByteEstimator
from sdaqf.application.context_contracts import (
    LoadedContextArtifact,
    artifact_from_value,
    canonical_json_bytes,
    edge_identity,
    node_identity,
    source_identity,
)
from sdaqf.application.context_selection import ContextSelector
from sdaqf.domain.context import (
    AuthorityClass,
    ContextArtifactType,
    ContextBudget,
    ContextCompaction,
    ContextEdge,
    ContextExtract,
    ContextGraph,
    ContextManifest,
    ContextNode,
    ContextProvenance,
    ContextQualityReport,
    ContextQuery,
    ContextRelationship,
    ContextSelection,
    ContextSnapshot,
    ContextSource,
    EdgeType,
    Freshness,
    FreshnessKind,
    HostSummaryProposal,
    RootScope,
    Sensitivity,
    SourceKind,
    SourceLinkedClaim,
    SourceLocator,
)
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity

SPECIFICATION_TEXT = "# Specification\n\nThe framework must validate context.\n"
CONTRACT_TEXT = "# Accepted contract\n\nContext snapshots are exact.\n"
EVIDENCE_TEXT = "PASS: public fixture evidence is verified.\n"


def digest(content: bytes | str) -> str:
    """Return an uppercase SHA-256."""

    encoded = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(encoded).hexdigest().upper()


def candidate() -> CandidateIdentity:
    """Return one exact test candidate."""

    return CandidateIdentity(
        source_spec_sha256=digest(SPECIFICATION_TEXT),
        git_head="b" * 40,
        repository_digest="C" * 64,
    )


class PinnedContextCandidateVerifier:
    """Test-only verifier for one explicit synthetic candidate."""

    def __init__(self, expected: CandidateIdentity | None = None) -> None:
        self._expected = candidate() if expected is None else expected

    def verify(self, repository_root: Path, expected: CandidateIdentity) -> None:
        """Require the exact synthetic candidate without inspecting Git."""

        del repository_root
        if expected != self._expected:
            raise RuntimeError("Synthetic Context candidate does not match.")


def write_sources(root: Path) -> None:
    """Materialize the exact public source fixture under a temporary root."""

    source_root = root / "examples/m5-context/sources"
    source_root.mkdir(parents=True)
    (source_root / "specification.md").write_text(
        SPECIFICATION_TEXT,
        encoding="utf-8",
        newline="",
    )
    (source_root / "accepted-contract.md").write_text(
        CONTRACT_TEXT,
        encoding="utf-8",
        newline="",
    )
    (source_root / "verified-evidence.txt").write_text(
        EVIDENCE_TEXT,
        encoding="utf-8",
        newline="",
    )


def provenance(path: str, sha: str) -> ContextProvenance:
    """Return bounded fixture provenance."""

    return ContextProvenance(
        producer="repository",
        recorded_by="M5-CONTEXT-INTEGRITY",
        references=(ArtifactReference(path=path, sha256=sha),),
    )


def source(
    *,
    path: str,
    text: str,
    kind: SourceKind,
    title: str,
    authority: AuthorityClass,
    required: bool,
    identifiers: tuple[str, ...],
    labels: tuple[str, ...],
) -> ContextNode:
    """Build one source and its corresponding node."""

    locator = SourceLocator(
        root_scope=RootScope.REPOSITORY,
        path=path,
        sha256=digest(text),
        line_start=1,
        line_end=len(text.splitlines()),
    )
    source_content = {
        "kind": kind.value,
        "title": title,
        "locator": locator.to_dict(),
        "provenance": provenance(path, digest(text)).to_dict(),
        "authority": authority.value,
        "freshness": Freshness(FreshnessKind.CANDIDATE_BOUND).to_dict(),
        "sensitivity": Sensitivity.PUBLIC.value,
        "identifiers": list(identifiers),
        "labels": list(labels),
        "required": required,
    }
    source_id = source_identity(source_content)
    node = ContextNode(
        node_id="",
        source_id=source_id,
        kind=kind,
        title=title,
        text=text,
        text_sha256=digest(text),
        locator=locator,
        provenance=provenance(path, digest(text)),
        authority=authority,
        freshness=Freshness(FreshnessKind.CANDIDATE_BOUND),
        sensitivity=Sensitivity.PUBLIC,
        identifiers=identifiers,
        labels=labels,
        required=required,
    )
    return replace(node, node_id=node_identity(node.content_dict()))


def manifest_and_graph() -> tuple[LoadedContextArtifact, LoadedContextArtifact]:
    """Return exact Manifest and Graph artifacts."""

    nodes = [
        source(
            path="examples/m5-context/sources/specification.md",
            text=SPECIFICATION_TEXT,
            kind=SourceKind.SPECIFICATION,
            title="Canonical specification",
            authority=AuthorityClass.CANONICAL_SPECIFICATION,
            required=True,
            identifiers=("FR-M5-001",),
            labels=("context", "must"),
        ),
        source(
            path="examples/m5-context/sources/accepted-contract.md",
            text=CONTRACT_TEXT,
            kind=SourceKind.DECISION,
            title="Accepted Context contract",
            authority=AuthorityClass.ACCEPTED_PUBLIC_CONTRACT,
            required=False,
            identifiers=("M5-D1",),
            labels=("contract", "identity"),
        ),
        source(
            path="examples/m5-context/sources/verified-evidence.txt",
            text=EVIDENCE_TEXT,
            kind=SourceKind.EVIDENCE,
            title="Verified public evidence",
            authority=AuthorityClass.VERIFIED_EVIDENCE,
            required=False,
            identifiers=("EV-M5-PUBLIC",),
            labels=("evidence", "pass"),
        ),
    ]
    nodes.sort(key=lambda item: item.node_id)
    source_by_id = {item.source_id: item for item in nodes}
    manifest_sources = tuple(
        _manifest_source(source_by_id[source_id])
        for source_id in sorted(source_by_id)
    )
    first, second, third = manifest_sources
    relationships = [
        ContextRelationship(
            edge_type=EdgeType.REFERENCES,
            source_id=first.source_id,
            target_id=second.source_id,
            provenance=first.provenance,
        ),
        ContextRelationship(
            edge_type=EdgeType.VERIFIES,
            source_id=third.source_id,
            target_id=first.source_id,
            provenance=third.provenance,
        ),
    ]
    relationships.sort(
        key=lambda item: (item.edge_type.value, item.source_id, item.target_id)
    )
    manifest = ContextManifest(
        candidate=candidate(),
        sensitivity=Sensitivity.PUBLIC,
        sources=tuple(manifest_sources),
        relationships=tuple(relationships),
    )
    manifest_artifact = artifact_from_value(ContextArtifactType.MANIFEST, manifest)
    node_by_source = {item.source_id: item for item in nodes}
    edges: list[ContextEdge] = []
    for relation in relationships:
        edge = ContextEdge(
            edge_id="",
            edge_type=relation.edge_type,
            source_node_id=node_by_source[relation.source_id].node_id,
            target_node_id=node_by_source[relation.target_id].node_id,
            provenance=relation.provenance,
        )
        edges.append(replace(edge, edge_id=edge_identity(edge.content_dict())))
    edges.sort(key=lambda item: item.edge_id)
    graph = ContextGraph(
        candidate=candidate(),
        manifest_id=manifest_artifact.artifact_id,
        sensitivity=Sensitivity.PUBLIC,
        nodes=tuple(nodes),
        edges=tuple(edges),
        excluded_sources=(),
    )
    return manifest_artifact, artifact_from_value(ContextArtifactType.GRAPH, graph)


def complete_artifacts() -> dict[ContextArtifactType, LoadedContextArtifact]:
    """Return one valid artifact of every M5 public type."""

    manifest_artifact, graph_artifact = manifest_and_graph()
    graph = graph_artifact.value
    assert isinstance(graph, ContextGraph)
    query = ContextQuery(
        candidate=candidate(),
        graph_id=graph_artifact.artifact_id,
        as_of="2026-07-31T00:00:00Z",
        clearance=Sensitivity.PUBLIC,
        required_node_ids=tuple(
            sorted(node.node_id for node in graph.nodes if node.required)
        ),
        seed_node_ids=(),
        identifiers=("FR-M5-001",),
        terms=("context", "validate"),
        allowed_edge_types=tuple(sorted(EdgeType, key=lambda item: item.value)),
        budget=ContextBudget(
            budget_bytes=65536,
            max_nodes=64,
            max_edges=128,
            max_traversal_depth=4,
        ),
    )
    query_artifact = artifact_from_value(ContextArtifactType.QUERY, query)
    selection_artifact = ContextSelector(
        CanonicalUTF8ByteEstimator()
    ).select(
        graph_artifact,
        query_artifact,
    )
    selection = selection_artifact.value
    assert isinstance(selection, ContextSelection)
    snapshot = ContextSnapshot(
        candidate=candidate(),
        graph_id=graph_artifact.artifact_id,
        query_id=query_artifact.artifact_id,
        selection_id=selection_artifact.artifact_id,
        as_of=query.as_of,
        sensitivity=Sensitivity.PUBLIC,
        nodes=graph.nodes,
        edges=graph.edges,
        selected=selection.selected,
        excluded=selection.excluded,
        unresolved_contradiction_ids=(),
        context_bytes=selection.used_bytes,
        budget_bytes=selection.budget_bytes,
    )
    snapshot_artifact = artifact_from_value(ContextArtifactType.SNAPSHOT, snapshot)
    extracts = tuple(
        ContextExtract(
            node_id=node.node_id,
            source_id=node.source_id,
            text=node.text,
            text_sha256=node.text_sha256,
            authority=node.authority,
            sensitivity=node.sensitivity,
            required=node.required,
            contradiction_ids=(),
            cost_bytes=len(canonical_json_bytes(node.text)),
        )
        for node in graph.nodes
    )
    proposal = HostSummaryProposal(
        snapshot_id=snapshot_artifact.artifact_id,
        authority=AuthorityClass.UNTRUSTED_PROPOSAL,
        sensitivity=Sensitivity.PUBLIC,
        claims=(
            SourceLinkedClaim(
                claim="The public fixture proposes a source-linked summary.",
                source_node_ids=(graph.nodes[0].node_id,),
                extract_sha256s=(graph.nodes[0].text_sha256,),
            ),
        ),
    )
    proposal_artifact = artifact_from_value(
        ContextArtifactType.HOST_SUMMARY_PROPOSAL,
        proposal,
    )
    compaction = ContextCompaction(
        candidate=candidate(),
        snapshot_id=snapshot_artifact.artifact_id,
        sensitivity=Sensitivity.PUBLIC,
        budget_bytes=65536,
        used_bytes=sum(item.cost_bytes for item in extracts),
        extracts=extracts,
        omitted_node_ids=(),
        unresolved_contradiction_ids=(),
        host_summary_proposal_id=proposal_artifact.artifact_id,
    )
    quality = ContextQualityReport(
        candidate=candidate(),
        snapshot_id=snapshot_artifact.artifact_id,
        sensitivity=Sensitivity.PUBLIC,
        required_reference_recall=100,
        stale_required_count=0,
        provenance_complete_count=len(graph.nodes),
        provenance_missing_count=0,
        sensitivity_violation_count=0,
        selected_context_bytes=snapshot.context_bytes,
        budget_bytes=query.budget.budget_bytes,
        redundant_bytes=0,
        selected_node_count=len(graph.nodes),
        excluded_node_count=len(snapshot.excluded),
        unresolved_contradiction_count=0,
        traversal_truncated=False,
    )
    return {
        ContextArtifactType.MANIFEST: manifest_artifact,
        ContextArtifactType.GRAPH: graph_artifact,
        ContextArtifactType.QUERY: query_artifact,
        ContextArtifactType.SELECTION: selection_artifact,
        ContextArtifactType.SNAPSHOT: snapshot_artifact,
        ContextArtifactType.COMPACTION: artifact_from_value(
            ContextArtifactType.COMPACTION,
            compaction,
        ),
        ContextArtifactType.HOST_SUMMARY_PROPOSAL: proposal_artifact,
        ContextArtifactType.QUALITY_REPORT: artifact_from_value(
            ContextArtifactType.QUALITY_REPORT,
            quality,
        ),
    }


def _manifest_source(node: ContextNode) -> ContextSource:
    return ContextSource(
        source_id=node.source_id,
        kind=node.kind,
        title=node.title,
        locator=node.locator,
        provenance=node.provenance,
        authority=node.authority,
        freshness=node.freshness,
        sensitivity=node.sensitivity,
        identifiers=node.identifiers,
        labels=node.labels,
        required=node.required,
    )
