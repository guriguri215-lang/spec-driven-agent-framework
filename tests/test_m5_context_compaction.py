"""M5 snapshot, comparison, and deterministic compaction tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

from sdaqf.adapters.context import (
    CanonicalUTF8ByteEstimator,
    LocalContextSourceReader,
)
from sdaqf.application.context_compaction import (
    ContextCompactionError,
    ContextCompactor,
)
from sdaqf.application.context_contracts import (
    artifact_from_value,
    canonical_json_bytes,
    edge_identity,
    node_identity,
    parse_context_artifact_bytes,
    serialize_context_artifact,
)
from sdaqf.application.context_selection import (
    ContextSelectionError,
    ContextSelector,
    ContextSnapshotService,
    compare_context_snapshots,
)
from sdaqf.domain.context import (
    AuthorityClass,
    ContextArtifactType,
    ContextCompaction,
    ContextEdge,
    ContextGraph,
    ContextQuery,
    ContextSelection,
    ContextSnapshot,
    EdgeType,
    ExclusionDecision,
    Freshness,
    FreshnessKind,
    HostSummaryProposal,
    Sensitivity,
    SourceLinkedClaim,
)
from sdaqf.domain.quality import CandidateIdentity
from sdaqf.ports.context import (
    ContextCandidateVerifier,
    ContextSourceError,
    ContextSourceReader,
)
from tests.m5_context_helpers import (
    PinnedContextCandidateVerifier,
    complete_artifacts,
    write_sources,
)


def test_snapshot_reobserves_sources_and_comparison_is_exact(tmp_path: Path) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    snapshot = ContextSnapshotService(
        LocalContextSourceReader(),
        PinnedContextCandidateVerifier(),
        CanonicalUTF8ByteEstimator(),
    ).build(
        artifacts[ContextArtifactType.GRAPH],
        artifacts[ContextArtifactType.SELECTION],
        repository_root=tmp_path,
    )
    assert snapshot == artifacts[ContextArtifactType.SNAPSHOT]
    delta = compare_context_snapshots(snapshot, snapshot)
    assert delta.added_node_ids == ()
    assert delta.removed_node_ids == ()
    assert delta.candidate_changed is False


def test_snapshot_rejects_source_change_after_index(tmp_path: Path) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    source = tmp_path / "examples/m5-context/sources/specification.md"
    source.write_text("changed after indexing\n", encoding="utf-8")
    with pytest.raises(
        (ContextSelectionError, RuntimeError),
        match=r"re-observation|digest|changed",
    ):
        ContextSnapshotService(
            LocalContextSourceReader(),
            PinnedContextCandidateVerifier(),
            CanonicalUTF8ByteEstimator(),
        ).build(
            artifacts[ContextArtifactType.GRAPH],
            artifacts[ContextArtifactType.SELECTION],
            repository_root=tmp_path,
        )


def test_snapshot_rejects_fabricated_but_content_addressed_selection(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    selection_artifact = artifacts[ContextArtifactType.SELECTION]
    graph_artifact = artifacts[ContextArtifactType.GRAPH]
    assert isinstance(selection_artifact.value, ContextSelection)
    assert isinstance(graph_artifact.value, ContextGraph)
    optional = next(node for node in graph_artifact.value.nodes if not node.required)
    decision = next(
        item
        for item in selection_artifact.value.selected
        if item.node_id == optional.node_id
    )
    fabricated = replace(
        selection_artifact.value,
        selected=(decision,),
        excluded=tuple(
            ExclusionDecision(
                node_id=node.node_id,
                reason="not-selected",
                details=(),
            )
            for node in graph_artifact.value.nodes
            if node.node_id != optional.node_id
        ),
        selected_edge_ids=(),
        unresolved_contradiction_ids=(),
        edge_cost_bytes=0,
        used_bytes=decision.cost_bytes,
        sensitivity=optional.sensitivity,
    )
    with pytest.raises(ContextSelectionError, match="exact deterministic result"):
        ContextSnapshotService(
            LocalContextSourceReader(),
            PinnedContextCandidateVerifier(),
            CanonicalUTF8ByteEstimator(),
        ).build(
            graph_artifact,
            artifact_from_value(ContextArtifactType.SELECTION, fabricated),
            repository_root=tmp_path,
        )


def test_snapshot_excludes_changed_optional_source_with_exact_reason(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    graph = artifacts[ContextArtifactType.GRAPH].value
    assert isinstance(graph, ContextGraph)
    optional = next(node for node in graph.nodes if not node.required)
    target = tmp_path.joinpath(*Path(optional.locator.path).parts)
    target.write_text("changed optional context\n", encoding="utf-8")
    snapshot = ContextSnapshotService(
        LocalContextSourceReader(),
        PinnedContextCandidateVerifier(),
        CanonicalUTF8ByteEstimator(),
    ).build(
        artifacts[ContextArtifactType.GRAPH],
        artifacts[ContextArtifactType.SELECTION],
        repository_root=tmp_path,
    )
    assert isinstance(snapshot.value, ContextSnapshot)
    assert optional.node_id not in {node.node_id for node in snapshot.value.nodes}
    exclusion = next(
        item for item in snapshot.value.excluded if item.node_id == optional.node_id
    )
    assert exclusion.reason == "digest-mismatch"


@pytest.mark.parametrize(
    ("materialize", "expected_reason"),
    [
        (False, "missing-or-unreadable"),
        (True, "invalid-json"),
    ],
)
def test_snapshot_never_adopts_unobserved_or_invalid_immutable_json(
    tmp_path: Path,
    *,
    materialize: bool,
    expected_reason: str,
) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    graph = artifacts[ContextArtifactType.GRAPH].value
    query = artifacts[ContextArtifactType.QUERY].value
    assert isinstance(graph, ContextGraph)
    assert isinstance(query, ContextQuery)
    accepted = next(
        node
        for node in graph.nodes
        if node.authority is AuthorityClass.ACCEPTED_PUBLIC_CONTRACT
    )
    path = "evidence/nonexistent-contract.json"
    text = '{"decision":1,"decision":2}\n'
    digest = hashlib.sha256(text.encode()).hexdigest().upper()
    locator = replace(
        accepted.locator,
        path=path,
        sha256=digest,
        line_start=1,
        line_end=1,
    )
    provenance = replace(
        accepted.provenance,
        references=(
            replace(accepted.provenance.references[0], path=path, sha256=digest),
        ),
    )
    fabricated = replace(
        accepted,
        text=text,
        text_sha256=digest,
        locator=locator,
        provenance=provenance,
        freshness=Freshness(FreshnessKind.IMMUTABLE),
    )
    fabricated = replace(
        fabricated,
        node_id=node_identity(fabricated.content_dict()),
    )
    changed_graph = replace(
        graph,
        nodes=tuple(
            sorted(
                (
                    fabricated,
                    *(node for node in graph.nodes if node.node_id != accepted.node_id),
                ),
                key=lambda node: node.node_id,
            )
        ),
        edges=(),
    )
    graph_artifact = artifact_from_value(ContextArtifactType.GRAPH, changed_graph)
    query_artifact = artifact_from_value(
        ContextArtifactType.QUERY,
        replace(query, graph_id=graph_artifact.artifact_id),
    )
    selection_artifact = ContextSelector(CanonicalUTF8ByteEstimator()).select(
        graph_artifact,
        query_artifact,
    )
    if materialize:
        target = tmp_path.joinpath(*Path(path).parts)
        target.parent.mkdir(parents=True)
        target.write_text(text, encoding="utf-8", newline="")

    snapshot_artifact = ContextSnapshotService(
        LocalContextSourceReader(),
        PinnedContextCandidateVerifier(),
        CanonicalUTF8ByteEstimator(),
    ).build(
        graph_artifact,
        selection_artifact,
        repository_root=tmp_path,
    )
    assert isinstance(snapshot_artifact.value, ContextSnapshot)
    assert fabricated.node_id not in {
        node.node_id for node in snapshot_artifact.value.nodes
    }
    exclusion = next(
        item
        for item in snapshot_artifact.value.excluded
        if item.node_id == fabricated.node_id
    )
    assert exclusion.reason == expected_reason


def test_compaction_is_deterministic_and_preserves_required_extracts(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    compactor = _compactor()
    first = compactor.compact(
        artifacts[ContextArtifactType.SNAPSHOT],
        repository_root=tmp_path,
        host_summary_artifact=artifacts[
            ContextArtifactType.HOST_SUMMARY_PROPOSAL
        ],
    )
    second = compactor.compact(
        artifacts[ContextArtifactType.SNAPSHOT],
        repository_root=tmp_path,
        host_summary_artifact=artifacts[
            ContextArtifactType.HOST_SUMMARY_PROPOSAL
        ],
    )
    assert first == second
    assert isinstance(first.value, ContextCompaction)
    snapshot = artifacts[ContextArtifactType.SNAPSHOT].value
    assert isinstance(snapshot, ContextSnapshot)
    required = {node.node_id for node in snapshot.nodes if node.required}
    assert required <= {
        extract.node_id for extract in first.value.extracts if extract.required
    }
    assert first.value.used_bytes <= first.value.budget_bytes


def test_compaction_propagates_candidate_and_highest_proposal_sensitivity(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    proposal_artifact = artifacts[ContextArtifactType.HOST_SUMMARY_PROPOSAL]
    snapshot = artifacts[ContextArtifactType.SNAPSHOT].value
    assert isinstance(proposal_artifact.value, HostSummaryProposal)
    assert isinstance(snapshot, ContextSnapshot)
    proposal = artifact_from_value(
        ContextArtifactType.HOST_SUMMARY_PROPOSAL,
        replace(
            proposal_artifact.value,
            sensitivity=Sensitivity.OWNER_PRIVATE,
        ),
    )
    compaction = _compactor().compact(
        artifacts[ContextArtifactType.SNAPSHOT],
        repository_root=tmp_path,
        host_summary_artifact=proposal,
    )
    assert isinstance(compaction.value, ContextCompaction)
    assert compaction.value.candidate == snapshot.candidate
    assert compaction.value.sensitivity is Sensitivity.OWNER_PRIVATE


def test_host_summary_digest_mismatch_is_untrusted_and_rejected(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    proposal_artifact = artifacts[ContextArtifactType.HOST_SUMMARY_PROPOSAL]
    assert isinstance(proposal_artifact.value, HostSummaryProposal)
    claim = proposal_artifact.value.claims[0]
    changed_claim = replace(claim, extract_sha256s=("0" * 64,))
    changed = replace(proposal_artifact.value, claims=(changed_claim,))
    with pytest.raises(ContextCompactionError, match="digests"):
        _compactor().compact(
            artifacts[ContextArtifactType.SNAPSHOT],
            repository_root=tmp_path,
            host_summary_artifact=artifact_from_value(
                ContextArtifactType.HOST_SUMMARY_PROPOSAL,
                changed,
            ),
        )


def test_host_summary_cannot_reference_absent_source_node(tmp_path: Path) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    proposal_artifact = artifacts[ContextArtifactType.HOST_SUMMARY_PROPOSAL]
    assert isinstance(proposal_artifact.value, HostSummaryProposal)
    claim = proposal_artifact.value.claims[0]
    changed_claim = SourceLinkedClaim(
        claim=claim.claim,
        source_node_ids=("CTX-NODE-" + "0" * 64,),
        extract_sha256s=claim.extract_sha256s,
    )
    changed = replace(proposal_artifact.value, claims=(changed_claim,))
    with pytest.raises(ContextCompactionError, match="missing snapshot node"):
        _compactor().compact(
            artifacts[ContextArtifactType.SNAPSHOT],
            repository_root=tmp_path,
            host_summary_artifact=artifact_from_value(
                ContextArtifactType.HOST_SUMMARY_PROPOSAL,
                changed,
            ),
        )


def test_compaction_reauthenticates_fabricated_snapshot_text(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    snapshot = artifacts[ContextArtifactType.SNAPSHOT].value
    assert isinstance(snapshot, ContextSnapshot)
    canonical = next(node for node in snapshot.nodes if node.required)
    text = "fabricated canonical context\n"
    fabricated = replace(
        canonical,
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest().upper(),
    )
    fabricated = replace(
        fabricated,
        node_id=node_identity(fabricated.content_dict()),
    )
    decision = next(
        item for item in snapshot.selected if item.node_id == canonical.node_id
    )
    fabricated_decision = replace(
        decision,
        node_id=fabricated.node_id,
        cost_bytes=len(canonical_json_bytes(fabricated.content_dict())),
    )
    nodes = tuple(
        sorted(
            (
                fabricated,
                *(node for node in snapshot.nodes if node.node_id != canonical.node_id),
            ),
            key=lambda node: node.node_id,
        )
    )
    decisions = {
        item.node_id: item
        for item in snapshot.selected
        if item.node_id != canonical.node_id
    }
    decisions[fabricated.node_id] = fabricated_decision
    changed = replace(
        snapshot,
        nodes=nodes,
        edges=(),
        selected=tuple(decisions[node.node_id] for node in nodes),
        unresolved_contradiction_ids=(),
        context_bytes=sum(len(canonical_json_bytes(node.content_dict())) for node in nodes),
    )
    fabricated_artifact = parse_context_artifact_bytes(
        serialize_context_artifact(
            artifact_from_value(ContextArtifactType.SNAPSHOT, changed)
        ),
        expected_type=ContextArtifactType.SNAPSHOT,
    )

    with pytest.raises(ContextCompactionError, match="authentication"):
        _compactor().compact(
            fabricated_artifact,
            repository_root=tmp_path,
        )


def test_compaction_rejects_fabricated_source_identity(tmp_path: Path) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    snapshot = artifacts[ContextArtifactType.SNAPSHOT].value
    assert isinstance(snapshot, ContextSnapshot)
    target = next(node for node in snapshot.nodes if not node.required)
    fabricated = replace(target, source_id="CTX-SOURCE-" + "0" * 64)
    fabricated = replace(
        fabricated,
        node_id=node_identity(fabricated.content_dict()),
    )
    changed = replace(
        snapshot,
        nodes=tuple(
            sorted(
                (
                    fabricated,
                    *(node for node in snapshot.nodes if node.node_id != target.node_id),
                ),
                key=lambda node: node.node_id,
            )
        ),
        edges=(),
    )

    compactor, reader, verifier = _no_io_compactor()
    with pytest.raises(ContextCompactionError, match="strict validation"):
        compactor.compact(
            artifact_from_value(ContextArtifactType.SNAPSHOT, changed),
            repository_root=tmp_path,
        )
    assert reader.method_calls == []
    assert verifier.method_calls == []


def test_compaction_rejects_duplicate_source_identity(tmp_path: Path) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    snapshot = artifacts[ContextArtifactType.SNAPSHOT].value
    assert isinstance(snapshot, ContextSnapshot)
    first, second = sorted(
        (node for node in snapshot.nodes if not node.required),
        key=lambda node: node.node_id,
    )
    duplicate = replace(
        second,
        source_id=first.source_id,
        kind=first.kind,
        title=first.title,
        locator=first.locator,
        provenance=first.provenance,
        authority=first.authority,
        freshness=first.freshness,
        sensitivity=first.sensitivity,
        identifiers=first.identifiers,
        labels=first.labels,
        required=first.required,
    )
    duplicate = replace(
        duplicate,
        node_id=node_identity(duplicate.content_dict()),
    )
    changed = replace(
        snapshot,
        nodes=tuple(
            sorted(
                (
                    duplicate,
                    *(node for node in snapshot.nodes if node.node_id != second.node_id),
                ),
                key=lambda node: node.node_id,
            )
        ),
        edges=(),
    )

    compactor, reader, verifier = _no_io_compactor()
    with pytest.raises(ContextCompactionError, match="strict validation"):
        compactor.compact(
            artifact_from_value(ContextArtifactType.SNAPSHOT, changed),
            repository_root=tmp_path,
        )
    assert reader.method_calls == []
    assert verifier.method_calls == []


def test_compaction_revalidates_complete_in_memory_snapshot_before_io(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    snapshot = artifacts[ContextArtifactType.SNAPSHOT].value
    assert isinstance(snapshot, ContextSnapshot)
    optional = next(node for node in snapshot.nodes if not node.required)
    decision = next(
        item for item in snapshot.selected if item.node_id == optional.node_id
    )
    missing_canonical = replace(
        snapshot,
        nodes=(optional,),
        edges=(),
        selected=(decision,),
        excluded=(),
        unresolved_contradiction_ids=(),
        sensitivity=optional.sensitivity,
        context_bytes=len(canonical_json_bytes(optional.content_dict())),
    )
    compactor, reader, verifier = _no_io_compactor()

    with pytest.raises(ContextCompactionError, match="strict validation"):
        compactor.compact(
            artifact_from_value(ContextArtifactType.SNAPSHOT, missing_canonical),
            repository_root=tmp_path,
        )
    assert reader.method_calls == []
    assert verifier.method_calls == []


def test_compaction_rejects_false_snapshot_envelope_identity_before_io(
    tmp_path: Path,
) -> None:
    artifact = complete_artifacts()[ContextArtifactType.SNAPSHOT]
    fabricated = replace(artifact, artifact_id="CTX-SNAPSHOT-" + "0" * 64)
    compactor, reader, verifier = _no_io_compactor()

    with pytest.raises(ContextCompactionError, match="strict validation"):
        compactor.compact(fabricated, repository_root=tmp_path)
    assert reader.method_calls == []
    assert verifier.method_calls == []


def test_compaction_rejects_host_authority_laundering_before_io(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    proposal = artifacts[ContextArtifactType.HOST_SUMMARY_PROPOSAL].value
    assert isinstance(proposal, HostSummaryProposal)
    laundered = replace(proposal, authority=AuthorityClass.OWNER_APPROVED)
    compactor, reader, verifier = _no_io_compactor()

    with pytest.raises(ContextCompactionError, match="strict validation"):
        compactor.compact(
            artifacts[ContextArtifactType.SNAPSHOT],
            repository_root=tmp_path,
            host_summary_artifact=artifact_from_value(
                ContextArtifactType.HOST_SUMMARY_PROPOSAL,
                laundered,
            ),
        )
    assert reader.method_calls == []
    assert verifier.method_calls == []


def test_compaction_preserves_source_and_contradiction_metadata(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    snapshot = artifacts[ContextArtifactType.SNAPSHOT].value
    assert isinstance(snapshot, ContextSnapshot)
    optional = sorted(
        (node for node in snapshot.nodes if not node.required),
        key=lambda node: node.node_id,
    )
    left, right = optional
    edge = ContextEdge(
        edge_id="",
        edge_type=EdgeType.CONTRADICTS,
        source_node_id=left.node_id,
        target_node_id=right.node_id,
        provenance=left.provenance,
    )
    edge = replace(edge, edge_id=edge_identity(edge.content_dict()))
    changed = replace(
        snapshot,
        edges=(edge,),
        unresolved_contradiction_ids=(edge.edge_id,),
        context_bytes=sum(
            len(canonical_json_bytes(node.content_dict())) for node in snapshot.nodes
        )
        + len(canonical_json_bytes(edge.content_dict())),
    )
    changed_artifact = parse_context_artifact_bytes(
        serialize_context_artifact(
            artifact_from_value(ContextArtifactType.SNAPSHOT, changed)
        ),
        expected_type=ContextArtifactType.SNAPSHOT,
    )
    compacted = _compactor().compact(
        changed_artifact,
        repository_root=tmp_path,
    )
    assert isinstance(compacted.value, ContextCompaction)
    assert compacted.value.unresolved_contradiction_ids == (edge.edge_id,)
    extracts = {item.node_id: item for item in compacted.value.extracts}
    for node in (left, right):
        assert extracts[node.node_id].source_id == node.source_id
        assert extracts[node.node_id].authority is node.authority
        assert extracts[node.node_id].sensitivity is node.sensitivity
        assert extracts[node.node_id].contradiction_ids == (edge.edge_id,)
        assert extracts[node.node_id].required is False


def test_publication_verifies_the_candidate_serialized_in_compaction(
    tmp_path: Path,
) -> None:
    artifacts = complete_artifacts()
    write_sources(tmp_path)
    caller_artifact = parse_context_artifact_bytes(
        serialize_context_artifact(artifacts[ContextArtifactType.SNAPSHOT]),
        expected_type=ContextArtifactType.SNAPSHOT,
    )
    caller_snapshot = caller_artifact.value
    assert isinstance(caller_snapshot, ContextSnapshot)
    compacted_candidate = caller_snapshot.candidate
    replacement_candidate = replace(
        compacted_candidate,
        repository_digest="F" * 64,
    )
    verifier = _MutableCandidateVerifier(compacted_candidate)
    publisher = _MemoryPublisher()
    compactor = ContextCompactor(
        LocalContextSourceReader(),
        verifier,
        _MutatingEstimator(
            caller_snapshot,
            verifier,
            replacement_candidate,
        ),
        publisher,
    )

    with pytest.raises(ContextSourceError, match="candidate changed"):
        compactor.publish(
            caller_artifact,
            repository_root=tmp_path,
            owner_root=None,
            host_summary_artifact=None,
            output=tmp_path / "context-compaction.json",
        )

    assert caller_snapshot.candidate == replacement_candidate
    assert verifier.observed[-1] == compacted_candidate
    assert publisher.contents == []


class _MutableCandidateVerifier:
    def __init__(self, current: CandidateIdentity) -> None:
        self.current = current
        self.observed: list[CandidateIdentity] = []

    def verify(self, repository_root: Path, expected: CandidateIdentity) -> None:
        del repository_root
        self.observed.append(expected)
        if expected != self.current:
            raise ContextSourceError("The publication candidate changed.")


class _MutatingEstimator:
    def __init__(
        self,
        caller_snapshot: ContextSnapshot,
        verifier: _MutableCandidateVerifier,
        replacement: CandidateIdentity,
    ) -> None:
        self._caller_snapshot = caller_snapshot
        self._verifier = verifier
        self._replacement = replacement
        self._mutated = False

    def cost(self, content: object) -> int:
        if not self._mutated:
            object.__setattr__(
                self._caller_snapshot,
                "candidate",
                self._replacement,
            )
            self._verifier.current = self._replacement
            self._mutated = True
        return CanonicalUTF8ByteEstimator().cost(content)


class _MemoryPublisher:
    def __init__(self) -> None:
        self.contents: list[bytes] = []

    def publish(self, target: Path, content: bytes) -> None:
        del target
        self.contents.append(content)


def _compactor() -> ContextCompactor:
    return ContextCompactor(
        LocalContextSourceReader(),
        PinnedContextCandidateVerifier(),
        CanonicalUTF8ByteEstimator(),
    )


def _no_io_compactor() -> tuple[ContextCompactor, Mock, Mock]:
    reader = Mock()
    verifier = Mock()
    return (
        ContextCompactor(
            cast(ContextSourceReader, reader),
            cast(ContextCandidateVerifier, verifier),
            CanonicalUTF8ByteEstimator(),
        ),
        reader,
        verifier,
    )
