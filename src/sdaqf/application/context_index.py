"""Safe explicit source indexing for the M5 Context Framework."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from sdaqf.application.context_contracts import (
    MAX_TOTAL_SOURCE_BYTES,
    ContextContractError,
    LoadedContextArtifact,
    artifact_from_value,
    edge_identity,
    node_identity,
    parse_context_artifact_bytes,
    serialize_context_artifact,
    validate_context_authority,
    validate_context_json_bytes,
)
from sdaqf.domain.context import (
    SENSITIVITY_RANK,
    AuthorityClass,
    ContextArtifactType,
    ContextEdge,
    ContextGraph,
    ContextManifest,
    ContextNode,
    ContextSourceExclusion,
    EdgeType,
    FreshnessKind,
    RootScope,
    SourceKind,
)
from sdaqf.ports.context import (
    ContextCandidateVerifier,
    ContextSourceError,
    ContextSourceReader,
    ImmutableJSONPublisher,
)


class ContextIndexError(ContextContractError):
    """A Context Manifest cannot be indexed safely."""


class ContextIndexer:
    """Build one immutable graph from explicit manifest sources."""

    def __init__(
        self,
        reader: ContextSourceReader,
        candidate_verifier: ContextCandidateVerifier,
        publisher: ImmutableJSONPublisher | None = None,
    ) -> None:
        self._reader = reader
        self._candidate_verifier = candidate_verifier
        self._publisher = publisher

    def build(
        self,
        manifest_artifact: LoadedContextArtifact,
        *,
        repository_root: Path,
        owner_root: Path | None = None,
    ) -> LoadedContextArtifact:
        """Observe every source and return one validated graph artifact."""

        if (
            manifest_artifact.artifact_type is not ContextArtifactType.MANIFEST
            or not isinstance(manifest_artifact.value, ContextManifest)
        ):
            raise ContextIndexError("Context index requires a Manifest artifact.")
        manifest = manifest_artifact.value
        self._candidate_verifier.verify(repository_root, manifest.candidate)
        canonical = [
            source
            for source in manifest.sources
            if source.authority is AuthorityClass.CANONICAL_SPECIFICATION
        ]
        if (
            len(canonical) != 1
            or not canonical[0].required
            or canonical[0].kind is not SourceKind.SPECIFICATION
            or canonical[0].locator.root_scope is not RootScope.REPOSITORY
            or canonical[0].locator.sha256 != manifest.candidate.source_spec_sha256
        ):
            raise ContextIndexError(
                "Manifest must identify one candidate-bound canonical specification."
            )
        owner_sources = [
            source
            for source in manifest.sources
            if source.locator.root_scope is RootScope.OWNER
        ]
        if owner_sources and owner_root is None:
            raise ContextIndexError("Owner sources require an explicit owner root.")
        if not owner_sources and owner_root is not None:
            raise ContextIndexError("Unused owner root is not permitted.")
        locator_keys = [
            (
                source.locator.root_scope.value,
                source.locator.path,
                source.locator.line_start,
                source.locator.line_end,
            )
            for source in manifest.sources
        ]
        if len(locator_keys) != len(set(locator_keys)):
            raise ContextIndexError("Manifest contains duplicate source locators.")

        total_bytes = 0
        nodes: list[ContextNode] = []
        exclusions: list[ContextSourceExclusion] = []
        for source in manifest.sources:
            root = (
                repository_root
                if source.locator.root_scope is RootScope.REPOSITORY
                else owner_root
            )
            assert root is not None
            try:
                validate_context_authority(source)
                for reference in source.provenance.references:
                    self._reader.verify_reference(root, reference)
                observation = self._reader.observe(root, source.locator)
                if source.freshness.kind is FreshnessKind.IMMUTABLE:
                    validate_context_json_bytes(observation.content)
            except (ContextSourceError, ContextContractError) as exc:
                if source.required:
                    raise ContextIndexError(
                        "Required Context source could not be adopted."
                    ) from exc
                exclusions.append(
                    ContextSourceExclusion(
                        source_id=source.source_id,
                        reason=self._source_failure_reason(exc),
                        details=(),
                    )
                )
                continue
            total_bytes += len(observation.content)
            if total_bytes > MAX_TOTAL_SOURCE_BYTES:
                if source.required:
                    raise ContextIndexError(
                        "Required Context sources exceed the total byte limit."
                    )
                total_bytes -= len(observation.content)
                exclusions.append(
                    ContextSourceExclusion(
                        source_id=source.source_id,
                        reason="total-source-byte-limit",
                        details=(),
                    )
                )
                continue
            text_digest = hashlib.sha256(
                observation.selected_text.encode("utf-8")
            ).hexdigest().upper()
            node = ContextNode(
                node_id="",
                source_id=source.source_id,
                kind=source.kind,
                title=source.title,
                text=observation.selected_text,
                text_sha256=text_digest,
                locator=source.locator,
                provenance=source.provenance,
                authority=source.authority,
                freshness=source.freshness,
                sensitivity=source.sensitivity,
                identifiers=source.identifiers,
                labels=source.labels,
                required=source.required,
            )
            nodes.append(replace(node, node_id=node_identity(node.content_dict())))
        if not nodes:
            raise ContextIndexError("Context graph cannot be empty.")
        nodes.sort(key=lambda item: item.node_id)
        exclusions.sort(key=lambda item: item.source_id)
        node_by_source = {item.source_id: item for item in nodes}

        edges: list[ContextEdge] = []
        for relationship in manifest.relationships:
            if (
                relationship.source_id not in node_by_source
                or relationship.target_id not in node_by_source
            ):
                continue
            for reference in relationship.provenance.references:
                try:
                    self._reader.verify_reference(repository_root, reference)
                except ContextSourceError as exc:
                    raise ContextIndexError(
                        "Context relationship provenance is unavailable."
                    ) from exc
            source_node = node_by_source[relationship.source_id]
            target_node = node_by_source[relationship.target_id]
            source_id = source_node.node_id
            target_id = target_node.node_id
            if (
                relationship.edge_type is EdgeType.CONTRADICTS
                and source_id > target_id
            ):
                source_id, target_id = target_id, source_id
            edge = ContextEdge(
                edge_id="",
                edge_type=relationship.edge_type,
                source_node_id=source_id,
                target_node_id=target_id,
                provenance=relationship.provenance,
            )
            edges.append(replace(edge, edge_id=edge_identity(edge.content_dict())))
        edges.sort(key=lambda item: item.edge_id)
        if len({edge.edge_id for edge in edges}) != len(edges):
            raise ContextIndexError("Manifest relationships produce duplicate edges.")

        self._candidate_verifier.verify(repository_root, manifest.candidate)

        graph = ContextGraph(
            candidate=manifest.candidate,
            manifest_id=manifest_artifact.artifact_id,
            sensitivity=max(
                (node.sensitivity for node in nodes),
                key=SENSITIVITY_RANK.__getitem__,
            ),
            nodes=tuple(nodes),
            edges=tuple(edges),
            excluded_sources=tuple(exclusions),
        )
        artifact = artifact_from_value(ContextArtifactType.GRAPH, graph)
        encoded = serialize_context_artifact(artifact)
        return parse_context_artifact_bytes(
            encoded,
            expected_type=ContextArtifactType.GRAPH,
        )

    def publish(
        self,
        manifest_artifact: LoadedContextArtifact,
        *,
        repository_root: Path,
        owner_root: Path | None,
        output: Path,
    ) -> LoadedContextArtifact:
        """Build and exclusively publish one graph."""

        if self._publisher is None:
            raise ContextIndexError("Context index publisher is unavailable.")
        artifact = self.build(
            manifest_artifact,
            repository_root=repository_root,
            owner_root=owner_root,
        )
        self._publisher.publish(output, serialize_context_artifact(artifact))
        return artifact

    @staticmethod
    def _source_failure_reason(exc: Exception) -> str:
        message = str(exc).casefold()
        if "authority" in message:
            return "authority-invalid"
        if "provenance" in message:
            return "provenance-invalid"
        if "json" in message:
            return "invalid-json"
        if "digest" in message:
            return "digest-mismatch"
        if "changed" in message:
            return "changed"
        if "size" in message or "byte" in message:
            return "source-byte-limit"
        return "missing-or-unreadable"
