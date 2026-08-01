"""Immutable M5 Context Framework domain contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sdaqf.domain.quality import ArtifactReference, CandidateIdentity


class ContextArtifactType(StrEnum):
    """Public Context artifact discriminator."""

    MANIFEST = "context-manifest"
    GRAPH = "context-graph"
    QUERY = "context-query"
    SELECTION = "context-selection"
    SNAPSHOT = "context-snapshot"
    COMPACTION = "context-compaction"
    HOST_SUMMARY_PROPOSAL = "context-host-summary-proposal"
    QUALITY_REPORT = "context-quality-report"


class RootScope(StrEnum):
    """Explicit filesystem root used by one source locator."""

    REPOSITORY = "repository"
    OWNER = "owner"


class SourceKind(StrEnum):
    """Supported typed context source classes."""

    SPECIFICATION = "specification"
    REQUIREMENT = "requirement"
    DECISION = "decision"
    DESIGN = "design"
    SOURCE = "source"
    TEST = "test"
    EVIDENCE = "evidence"
    FINDING = "finding"
    TASK = "task"
    HANDOFF = "handoff"
    TOOL_OBSERVATION = "tool-observation"
    SOLVER_ARTIFACT = "solver-artifact"


class EdgeType(StrEnum):
    """Supported graph relationship types."""

    REFERENCES = "references"
    IMPLEMENTS = "implements"
    VERIFIES = "verifies"
    DEPENDS_ON = "depends-on"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    DERIVED_FROM = "derived-from"


class AuthorityClass(StrEnum):
    """Ordered authority metadata; labels never create authority by themselves."""

    OWNER_APPROVED = "owner-approved"
    CANONICAL_SPECIFICATION = "canonical-specification"
    ACCEPTED_PUBLIC_CONTRACT = "accepted-public-contract"
    VERIFIED_EVIDENCE = "verified-evidence"
    REPOSITORY_RECORD = "repository-record"
    UNTRUSTED_OBSERVATION = "untrusted-observation"
    UNTRUSTED_PROPOSAL = "untrusted-proposal"


AUTHORITY_RANK: dict[AuthorityClass, int] = {
    value: rank for rank, value in enumerate(AuthorityClass)
}


class FreshnessKind(StrEnum):
    """Replayable freshness policy."""

    IMMUTABLE = "immutable"
    CANDIDATE_BOUND = "candidate-bound"
    EXPIRES_AT = "expires-at"


class Sensitivity(StrEnum):
    """Approved sensitivity levels in increasing order."""

    PUBLIC = "public"
    REPOSITORY_PRIVATE = "repository-private"
    OWNER_PRIVATE = "owner-private"
    SECRET_OR_PROHIBITED = "secret-or-prohibited"


SENSITIVITY_RANK: dict[Sensitivity, int] = {
    value: rank for rank, value in enumerate(Sensitivity)
}


@dataclass(frozen=True, slots=True)
class Freshness:
    """Freshness metadata carried by a source and node."""

    kind: FreshnessKind
    observed_at: str | None = None
    valid_until: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "kind": self.kind.value,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
        }


@dataclass(frozen=True, slots=True)
class ContextProvenance:
    """Bounded source-linked provenance."""

    producer: str
    recorded_by: str
    references: tuple[ArtifactReference, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "producer": self.producer,
            "recorded_by": self.recorded_by,
            "references": [item.to_dict() for item in self.references],
        }


@dataclass(frozen=True, slots=True)
class SourceLocator:
    """Portable source location under one explicit root."""

    root_scope: RootScope
    path: str
    sha256: str
    line_start: int
    line_end: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "root_scope": self.root_scope.value,
            "path": self.path,
            "sha256": self.sha256,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }


@dataclass(frozen=True, slots=True)
class ContextSource:
    """One manifest-declared source."""

    source_id: str
    kind: SourceKind
    title: str
    locator: SourceLocator
    provenance: ContextProvenance
    authority: AuthorityClass
    freshness: Freshness
    sensitivity: Sensitivity
    identifiers: tuple[str, ...]
    labels: tuple[str, ...]
    required: bool

    def content_dict(self) -> dict[str, object]:
        """Return the identity-bearing source content."""

        return {
            "kind": self.kind.value,
            "title": self.title,
            "locator": self.locator.to_dict(),
            "provenance": self.provenance.to_dict(),
            "authority": self.authority.value,
            "freshness": self.freshness.to_dict(),
            "sensitivity": self.sensitivity.value,
            "identifiers": list(self.identifiers),
            "labels": list(self.labels),
            "required": self.required,
        }

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {"source_id": self.source_id, **self.content_dict()}


@dataclass(frozen=True, slots=True)
class ContextRelationship:
    """Manifest relationship between source identities."""

    edge_type: EdgeType
    source_id: str
    target_id: str
    provenance: ContextProvenance

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "edge_type": self.edge_type.value,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ContextSourceExclusion:
    """Exact exclusion of one manifest source before graph adoption."""

    source_id: str
    reason: str
    details: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "source_id": self.source_id,
            "reason": self.reason,
            "details": list(self.details),
        }


@dataclass(frozen=True, slots=True)
class ContextManifest:
    """Explicit source declaration used to build one graph."""

    candidate: CandidateIdentity
    sensitivity: Sensitivity
    sources: tuple[ContextSource, ...]
    relationships: tuple[ContextRelationship, ...]

    def to_dict(self) -> dict[str, object]:
        """Return identity-bearing manifest content."""

        return {
            "candidate": self.candidate.to_dict(),
            "sensitivity": self.sensitivity.value,
            "sources": [item.to_dict() for item in self.sources],
            "relationships": [item.to_dict() for item in self.relationships],
        }


@dataclass(frozen=True, slots=True)
class ContextNode:
    """One immutable adopted source node."""

    node_id: str
    source_id: str
    kind: SourceKind
    title: str
    text: str
    text_sha256: str
    locator: SourceLocator
    provenance: ContextProvenance
    authority: AuthorityClass
    freshness: Freshness
    sensitivity: Sensitivity
    identifiers: tuple[str, ...]
    labels: tuple[str, ...]
    required: bool

    def source_content_dict(self) -> dict[str, object]:
        """Return the canonical source metadata represented by this node."""

        return {
            "kind": self.kind.value,
            "title": self.title,
            "locator": self.locator.to_dict(),
            "provenance": self.provenance.to_dict(),
            "authority": self.authority.value,
            "freshness": self.freshness.to_dict(),
            "sensitivity": self.sensitivity.value,
            "identifiers": list(self.identifiers),
            "labels": list(self.labels),
            "required": self.required,
        }

    def content_dict(self) -> dict[str, object]:
        """Return the identity-bearing node content."""

        return {
            "source_id": self.source_id,
            "kind": self.kind.value,
            "title": self.title,
            "text": self.text,
            "text_sha256": self.text_sha256,
            "locator": self.locator.to_dict(),
            "provenance": self.provenance.to_dict(),
            "authority": self.authority.value,
            "freshness": self.freshness.to_dict(),
            "sensitivity": self.sensitivity.value,
            "identifiers": list(self.identifiers),
            "labels": list(self.labels),
            "required": self.required,
        }

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {"node_id": self.node_id, **self.content_dict()}


@dataclass(frozen=True, slots=True)
class ContextEdge:
    """One immutable graph edge."""

    edge_id: str
    edge_type: EdgeType
    source_node_id: str
    target_node_id: str
    provenance: ContextProvenance

    def content_dict(self) -> dict[str, object]:
        """Return the identity-bearing edge content."""

        return {
            "edge_type": self.edge_type.value,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "provenance": self.provenance.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {"edge_id": self.edge_id, **self.content_dict()}


@dataclass(frozen=True, slots=True)
class ContextGraph:
    """Indexed graph content."""

    candidate: CandidateIdentity
    manifest_id: str
    sensitivity: Sensitivity
    nodes: tuple[ContextNode, ...]
    edges: tuple[ContextEdge, ...]
    excluded_sources: tuple[ContextSourceExclusion, ...]

    def to_dict(self) -> dict[str, object]:
        """Return identity-bearing graph content."""

        return {
            "candidate": self.candidate.to_dict(),
            "manifest_id": self.manifest_id,
            "sensitivity": self.sensitivity.value,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "excluded_sources": [item.to_dict() for item in self.excluded_sources],
        }


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Portable query and compaction bounds."""

    budget_bytes: int
    max_nodes: int
    max_edges: int
    max_traversal_depth: int

    def to_dict(self) -> dict[str, int | str]:
        """Return a JSON-compatible representation."""

        return {
            "unit": "canonical_utf8_bytes",
            "budget_bytes": self.budget_bytes,
            "max_nodes": self.max_nodes,
            "max_edges": self.max_edges,
            "max_traversal_depth": self.max_traversal_depth,
        }


@dataclass(frozen=True, slots=True)
class ContextQuery:
    """Deterministic context selection request."""

    candidate: CandidateIdentity
    graph_id: str
    as_of: str
    clearance: Sensitivity
    required_node_ids: tuple[str, ...]
    seed_node_ids: tuple[str, ...]
    identifiers: tuple[str, ...]
    terms: tuple[str, ...]
    allowed_edge_types: tuple[EdgeType, ...]
    budget: ContextBudget

    def to_dict(self) -> dict[str, object]:
        """Return identity-bearing query content."""

        return {
            "candidate": self.candidate.to_dict(),
            "graph_id": self.graph_id,
            "as_of": self.as_of,
            "clearance": self.clearance.value,
            "required_node_ids": list(self.required_node_ids),
            "seed_node_ids": list(self.seed_node_ids),
            "identifiers": list(self.identifiers),
            "terms": list(self.terms),
            "allowed_edge_types": [item.value for item in self.allowed_edge_types],
            "budget": self.budget.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    """Selected node with auditable ranking and cost."""

    node_id: str
    reasons: tuple[str, ...]
    phase: int
    authority_rank: int
    graph_distance: int
    lexical_score: int
    sensitivity_rank: int
    cost_bytes: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "node_id": self.node_id,
            "reasons": list(self.reasons),
            "rank": {
                "phase": self.phase,
                "authority_rank": self.authority_rank,
                "graph_distance": self.graph_distance,
                "lexical_score": self.lexical_score,
                "sensitivity_rank": self.sensitivity_rank,
                "node_id": self.node_id,
            },
            "cost_bytes": self.cost_bytes,
        }


@dataclass(frozen=True, slots=True)
class ExclusionDecision:
    """Explicit exclusion of one graph node."""

    node_id: str
    reason: str
    details: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "node_id": self.node_id,
            "reason": self.reason,
            "details": list(self.details),
        }


@dataclass(frozen=True, slots=True)
class ContextSelection:
    """Deterministic selected and excluded context identities."""

    candidate: CandidateIdentity
    graph_id: str
    query_id: str
    query: ContextQuery
    as_of: str
    sensitivity: Sensitivity
    selected: tuple[SelectionDecision, ...]
    excluded: tuple[ExclusionDecision, ...]
    selected_edge_ids: tuple[str, ...]
    unresolved_contradiction_ids: tuple[str, ...]
    edge_cost_bytes: int
    used_bytes: int
    budget_bytes: int
    traversal_truncated: bool

    def to_dict(self) -> dict[str, object]:
        """Return identity-bearing selection content."""

        return {
            "candidate": self.candidate.to_dict(),
            "graph_id": self.graph_id,
            "query_id": self.query_id,
            "query": self.query.to_dict(),
            "as_of": self.as_of,
            "sensitivity": self.sensitivity.value,
            "selected": [item.to_dict() for item in self.selected],
            "excluded": [item.to_dict() for item in self.excluded],
            "selected_edge_ids": list(self.selected_edge_ids),
            "unresolved_contradiction_ids": list(
                self.unresolved_contradiction_ids
            ),
            "edge_cost_bytes": self.edge_cost_bytes,
            "used_bytes": self.used_bytes,
            "budget_bytes": self.budget_bytes,
            "traversal_truncated": self.traversal_truncated,
        }


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Exact portable context consumed by a downstream milestone."""

    candidate: CandidateIdentity
    graph_id: str
    query_id: str
    selection_id: str
    as_of: str
    sensitivity: Sensitivity
    nodes: tuple[ContextNode, ...]
    edges: tuple[ContextEdge, ...]
    selected: tuple[SelectionDecision, ...]
    excluded: tuple[ExclusionDecision, ...]
    unresolved_contradiction_ids: tuple[str, ...]
    context_bytes: int
    budget_bytes: int

    def to_dict(self) -> dict[str, object]:
        """Return identity-bearing snapshot content."""

        return {
            "candidate": self.candidate.to_dict(),
            "graph_id": self.graph_id,
            "query_id": self.query_id,
            "selection_id": self.selection_id,
            "as_of": self.as_of,
            "sensitivity": self.sensitivity.value,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
            "selected": [item.to_dict() for item in self.selected],
            "excluded": [item.to_dict() for item in self.excluded],
            "unresolved_contradiction_ids": list(
                self.unresolved_contradiction_ids
            ),
            "context_bytes": self.context_bytes,
            "budget_bytes": self.budget_bytes,
        }


@dataclass(frozen=True, slots=True)
class ContextSnapshotDelta:
    """Ordered structural difference between exact snapshots."""

    base_snapshot_id: str
    current_snapshot_id: str
    added_node_ids: tuple[str, ...]
    removed_node_ids: tuple[str, ...]
    added_edge_ids: tuple[str, ...]
    removed_edge_ids: tuple[str, ...]
    sensitivity_changed: bool
    candidate_changed: bool

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible comparison."""

        return {
            "base_snapshot_id": self.base_snapshot_id,
            "current_snapshot_id": self.current_snapshot_id,
            "added_node_ids": list(self.added_node_ids),
            "removed_node_ids": list(self.removed_node_ids),
            "added_edge_ids": list(self.added_edge_ids),
            "removed_edge_ids": list(self.removed_edge_ids),
            "sensitivity_changed": self.sensitivity_changed,
            "candidate_changed": self.candidate_changed,
        }


@dataclass(frozen=True, slots=True)
class ContextExtract:
    """Source-linked deterministic extract."""

    node_id: str
    source_id: str
    text: str
    text_sha256: str
    authority: AuthorityClass
    sensitivity: Sensitivity
    required: bool
    contradiction_ids: tuple[str, ...]
    cost_bytes: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "node_id": self.node_id,
            "source_id": self.source_id,
            "text": self.text,
            "text_sha256": self.text_sha256,
            "authority": self.authority.value,
            "sensitivity": self.sensitivity.value,
            "required": self.required,
            "contradiction_ids": list(self.contradiction_ids),
            "cost_bytes": self.cost_bytes,
        }


@dataclass(frozen=True, slots=True)
class ContextCompaction:
    """Deterministic extractive compacted context."""

    candidate: CandidateIdentity
    snapshot_id: str
    sensitivity: Sensitivity
    budget_bytes: int
    used_bytes: int
    extracts: tuple[ContextExtract, ...]
    omitted_node_ids: tuple[str, ...]
    unresolved_contradiction_ids: tuple[str, ...]
    host_summary_proposal_id: str | None

    def to_dict(self) -> dict[str, object]:
        """Return identity-bearing compaction content."""

        return {
            "candidate": self.candidate.to_dict(),
            "snapshot_id": self.snapshot_id,
            "sensitivity": self.sensitivity.value,
            "budget_bytes": self.budget_bytes,
            "used_bytes": self.used_bytes,
            "extracts": [item.to_dict() for item in self.extracts],
            "omitted_node_ids": list(self.omitted_node_ids),
            "unresolved_contradiction_ids": list(
                self.unresolved_contradiction_ids
            ),
            "host_summary_proposal_id": self.host_summary_proposal_id,
        }


@dataclass(frozen=True, slots=True)
class SourceLinkedClaim:
    """One untrusted host claim with exact source links."""

    claim: str
    source_node_ids: tuple[str, ...]
    extract_sha256s: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""

        return {
            "claim": self.claim,
            "source_node_ids": list(self.source_node_ids),
            "extract_sha256s": list(self.extract_sha256s),
        }


@dataclass(frozen=True, slots=True)
class HostSummaryProposal:
    """Untrusted host-generated summary proposal."""

    snapshot_id: str
    authority: AuthorityClass
    sensitivity: Sensitivity
    claims: tuple[SourceLinkedClaim, ...]

    def to_dict(self) -> dict[str, object]:
        """Return identity-bearing proposal content."""

        return {
            "snapshot_id": self.snapshot_id,
            "authority": self.authority.value,
            "sensitivity": self.sensitivity.value,
            "claims": [item.to_dict() for item in self.claims],
        }


@dataclass(frozen=True, slots=True)
class ContextQualityReport:
    """Named quality measurements; no aggregate score exists."""

    candidate: CandidateIdentity
    snapshot_id: str
    sensitivity: Sensitivity
    required_reference_recall: int
    stale_required_count: int
    provenance_complete_count: int
    provenance_missing_count: int
    sensitivity_violation_count: int
    selected_context_bytes: int
    budget_bytes: int
    redundant_bytes: int
    selected_node_count: int
    excluded_node_count: int
    unresolved_contradiction_count: int
    traversal_truncated: bool

    def to_dict(self) -> dict[str, Any]:
        """Return identity-bearing quality content."""

        return {
            "candidate": self.candidate.to_dict(),
            "snapshot_id": self.snapshot_id,
            "sensitivity": self.sensitivity.value,
            "required_reference_recall": self.required_reference_recall,
            "stale_required_count": self.stale_required_count,
            "provenance_complete_count": self.provenance_complete_count,
            "provenance_missing_count": self.provenance_missing_count,
            "sensitivity_violation_count": self.sensitivity_violation_count,
            "selected_context_bytes": self.selected_context_bytes,
            "budget_bytes": self.budget_bytes,
            "redundant_bytes": self.redundant_bytes,
            "selected_node_count": self.selected_node_count,
            "excluded_node_count": self.excluded_node_count,
            "unresolved_contradiction_count": self.unresolved_contradiction_count,
            "traversal_truncated": self.traversal_truncated,
        }
