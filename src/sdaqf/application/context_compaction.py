"""Deterministic extractive compaction for exact Context Snapshots."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sdaqf.application.context_contracts import (
    ContextContractError,
    LoadedContextArtifact,
    artifact_from_value,
    parse_context_artifact_bytes,
    serialize_context_artifact,
    source_identity,
    validate_context_authority,
    validate_context_json_bytes,
)
from sdaqf.domain.context import (
    SENSITIVITY_RANK,
    ContextArtifactType,
    ContextCompaction,
    ContextExtract,
    ContextSnapshot,
    EdgeType,
    FreshnessKind,
    HostSummaryProposal,
    RootScope,
)
from sdaqf.ports.context import (
    BudgetEstimator,
    ContextCandidateVerifier,
    ContextSourceError,
    ContextSourceReader,
    ImmutableJSONPublisher,
)


class ContextCompactionError(ContextContractError):
    """A snapshot cannot be compacted without losing mandatory context."""


class ContextCompactor:
    """Build deterministic source-linked extracts from one exact snapshot."""

    def __init__(
        self,
        reader: ContextSourceReader,
        candidate_verifier: ContextCandidateVerifier,
        estimator: BudgetEstimator,
        publisher: ImmutableJSONPublisher | None = None,
    ) -> None:
        self._reader = reader
        self._candidate_verifier = candidate_verifier
        self._estimator = estimator
        self._publisher = publisher

    def compact(
        self,
        snapshot_artifact: LoadedContextArtifact,
        *,
        repository_root: Path,
        owner_root: Path | None = None,
        host_summary_artifact: LoadedContextArtifact | None = None,
    ) -> LoadedContextArtifact:
        """Return one validated deterministic extractive compaction."""

        if (
            snapshot_artifact.artifact_type is not ContextArtifactType.SNAPSHOT
            or not isinstance(snapshot_artifact.value, ContextSnapshot)
        ):
            raise ContextCompactionError("Compaction requires a Context Snapshot.")
        snapshot_artifact = self._strictly_validate_input(
            snapshot_artifact,
            expected_type=ContextArtifactType.SNAPSHOT,
            label="Snapshot",
        )
        snapshot = snapshot_artifact.value
        assert isinstance(snapshot, ContextSnapshot)
        proposal_id: str | None = None
        sensitivity = snapshot.sensitivity
        if host_summary_artifact is not None:
            if (
                host_summary_artifact.artifact_type
                is not ContextArtifactType.HOST_SUMMARY_PROPOSAL
                or not isinstance(host_summary_artifact.value, HostSummaryProposal)
            ):
                raise ContextCompactionError(
                    "Host summary input must be an untrusted proposal artifact."
                )
            host_summary_artifact = self._strictly_validate_input(
                host_summary_artifact,
                expected_type=ContextArtifactType.HOST_SUMMARY_PROPOSAL,
                label="Host summary proposal",
            )
            proposal_id = self._validate_host_proposal(
                snapshot_artifact,
                host_summary_artifact,
            )
            proposal = host_summary_artifact.value
            assert isinstance(proposal, HostSummaryProposal)
            sensitivity = max(
                (snapshot.sensitivity, proposal.sensitivity),
                key=SENSITIVITY_RANK.__getitem__,
            )
        self._verify_snapshot_sources(
            snapshot,
            repository_root=repository_root,
            owner_root=owner_root,
        )
        node_by_id = {node.node_id: node for node in snapshot.nodes}
        mandatory = {node.node_id for node in snapshot.nodes if node.required}
        contradiction_ids_by_node: dict[str, set[str]] = {
            node.node_id: set() for node in snapshot.nodes
        }
        for edge in snapshot.edges:
            if edge.edge_type is EdgeType.CONTRADICTS:
                mandatory.update((edge.source_node_id, edge.target_node_id))
                contradiction_ids_by_node[edge.source_node_id].add(edge.edge_id)
                contradiction_ids_by_node[edge.target_node_id].add(edge.edge_id)
        rank_by_id = {
            decision.node_id: (
                decision.phase,
                decision.authority_rank,
                decision.graph_distance,
                -decision.lexical_score,
                decision.sensitivity_rank,
                decision.node_id,
            )
            for decision in snapshot.selected
        }
        ordered = sorted(
            node_by_id,
            key=lambda node_id: (
                0 if node_id in mandatory else 1,
                rank_by_id[node_id],
            ),
        )
        extracts: list[ContextExtract] = []
        omitted: list[str] = []
        used = 0
        for node_id in ordered:
            node = node_by_id[node_id]
            cost = self._estimator.cost(node.text)
            if used + cost > snapshot.budget_bytes:
                if node_id in mandatory:
                    raise ContextCompactionError(
                        "Required extracts exceed the compaction budget."
                    )
                omitted.append(node_id)
                continue
            extracts.append(
                ContextExtract(
                    node_id=node.node_id,
                    source_id=node.source_id,
                    text=node.text,
                    text_sha256=node.text_sha256,
                    authority=node.authority,
                    sensitivity=node.sensitivity,
                    required=node.required,
                    contradiction_ids=tuple(
                        sorted(contradiction_ids_by_node[node_id])
                    ),
                    cost_bytes=cost,
                )
            )
            used += cost
        if not extracts:
            raise ContextCompactionError("Compaction cannot produce an empty context.")
        extracts.sort(key=lambda item: item.node_id)
        compaction = ContextCompaction(
            candidate=snapshot.candidate,
            snapshot_id=snapshot_artifact.artifact_id,
            sensitivity=sensitivity,
            budget_bytes=snapshot.budget_bytes,
            used_bytes=used,
            extracts=tuple(extracts),
            omitted_node_ids=tuple(sorted(omitted)),
            unresolved_contradiction_ids=snapshot.unresolved_contradiction_ids,
            host_summary_proposal_id=proposal_id,
        )
        artifact = artifact_from_value(ContextArtifactType.COMPACTION, compaction)
        return parse_context_artifact_bytes(
            serialize_context_artifact(artifact),
            expected_type=ContextArtifactType.COMPACTION,
        )

    def publish(
        self,
        snapshot_artifact: LoadedContextArtifact,
        *,
        repository_root: Path,
        owner_root: Path | None,
        host_summary_artifact: LoadedContextArtifact | None,
        output: Path,
    ) -> LoadedContextArtifact:
        """Compact and exclusively publish a fresh artifact."""

        if self._publisher is None:
            raise ContextCompactionError("Compaction publisher is unavailable.")
        artifact = self.compact(
            snapshot_artifact,
            repository_root=repository_root,
            owner_root=owner_root,
            host_summary_artifact=host_summary_artifact,
        )
        compaction = artifact.value
        assert isinstance(compaction, ContextCompaction)
        self._candidate_verifier.verify(repository_root, compaction.candidate)
        self._publisher.publish(output, serialize_context_artifact(artifact))
        return artifact

    def _verify_snapshot_sources(
        self,
        snapshot: ContextSnapshot,
        *,
        repository_root: Path,
        owner_root: Path | None,
    ) -> None:
        owner_nodes = [
            node
            for node in snapshot.nodes
            if node.locator.root_scope is RootScope.OWNER
        ]
        if owner_nodes and owner_root is None:
            raise ContextCompactionError(
                "Snapshot owner context requires an explicit owner root."
            )
        if not owner_nodes and owner_root is not None:
            raise ContextCompactionError("Unused owner root is not permitted.")
        try:
            if len({node.source_id for node in snapshot.nodes}) != len(snapshot.nodes):
                raise ContextContractError(
                    "Snapshot contains duplicate source identities."
                )
            for node in snapshot.nodes:
                validate_context_authority(node)
                if node.source_id != source_identity(node.source_content_dict()):
                    raise ContextContractError(
                        "Snapshot node source identity does not match its metadata."
                    )
            self._candidate_verifier.verify(repository_root, snapshot.candidate)
            for node in snapshot.nodes:
                root = (
                    repository_root
                    if node.locator.root_scope is RootScope.REPOSITORY
                    else owner_root
                )
                assert root is not None
                observation = self._reader.observe(root, node.locator)
                if node.freshness.kind is FreshnessKind.IMMUTABLE:
                    validate_context_json_bytes(observation.content)
                if observation.selected_text != node.text:
                    raise ContextCompactionError(
                        "Snapshot text does not match its observed source."
                    )
                if node.freshness.kind is FreshnessKind.EXPIRES_AT:
                    assert node.freshness.observed_at is not None
                    assert node.freshness.valid_until is not None
                    as_of = _timestamp(snapshot.as_of)
                    if not (
                        _timestamp(node.freshness.observed_at)
                        <= as_of
                        <= _timestamp(node.freshness.valid_until)
                    ):
                        raise ContextCompactionError(
                            "Snapshot contains stale source context."
                        )
                for reference in node.provenance.references:
                    self._reader.verify_reference(root, reference)
            for edge in snapshot.edges:
                for reference in edge.provenance.references:
                    self._reader.verify_reference(repository_root, reference)
            self._candidate_verifier.verify(repository_root, snapshot.candidate)
        except (ContextContractError, ContextSourceError) as exc:
            raise ContextCompactionError(
                "Snapshot source authentication failed before compaction."
            ) from exc

    @staticmethod
    def _strictly_validate_input(
        artifact: LoadedContextArtifact,
        *,
        expected_type: ContextArtifactType,
        label: str,
    ) -> LoadedContextArtifact:
        """Purely revalidate one in-memory envelope and all value invariants."""

        try:
            return parse_context_artifact_bytes(
                serialize_context_artifact(artifact),
                expected_type=expected_type,
            )
        except ContextContractError as exc:
            raise ContextCompactionError(
                f"{label} failed strict validation before compaction."
            ) from exc

    @staticmethod
    def _validate_host_proposal(
        snapshot_artifact: LoadedContextArtifact,
        proposal_artifact: LoadedContextArtifact,
    ) -> str:
        if (
            proposal_artifact.artifact_type
            is not ContextArtifactType.HOST_SUMMARY_PROPOSAL
            or not isinstance(proposal_artifact.value, HostSummaryProposal)
        ):
            raise ContextCompactionError(
                "Host summary input must be an untrusted proposal artifact."
            )
        snapshot = snapshot_artifact.value
        assert isinstance(snapshot, ContextSnapshot)
        proposal = proposal_artifact.value
        if proposal.snapshot_id != snapshot_artifact.artifact_id:
            raise ContextCompactionError("Host proposal snapshot identity does not match.")
        if (
            SENSITIVITY_RANK[proposal.sensitivity]
            < SENSITIVITY_RANK[snapshot.sensitivity]
        ):
            raise ContextCompactionError(
                "Host proposal cannot downgrade snapshot sensitivity."
            )
        nodes = {node.node_id: node for node in snapshot.nodes}
        for claim in proposal.claims:
            if any(node_id not in nodes for node_id in claim.source_node_ids):
                raise ContextCompactionError(
                    "Host proposal references a missing snapshot node."
                )
            expected = sorted(
                nodes[node_id].text_sha256 for node_id in claim.source_node_ids
            )
            if list(claim.extract_sha256s) != expected:
                raise ContextCompactionError(
                    "Host proposal extract digests do not match its source nodes."
                )
        return proposal_artifact.artifact_id


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
