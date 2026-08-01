"""M5 strict Context contract and canonical identity tests."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import sdaqf
from sdaqf.application.context_contracts import (
    ContextContractError,
    LoadedContextArtifact,
    artifact_from_value,
    canonical_json_bytes,
    context_identity,
    node_identity,
    parse_context_artifact_bytes,
    serialize_context_artifact,
    source_identity,
)
from sdaqf.domain.context import (
    AuthorityClass,
    ContextArtifactType,
    ContextCompaction,
    ContextGraph,
    ContextManifest,
    ContextSnapshot,
    Freshness,
    FreshnessKind,
    Sensitivity,
)
from tests.m5_context_helpers import complete_artifacts
from tests.schema_validation import LocalSchemaValidator, SchemaValidationError

SCHEMA_NAMES = {
    ContextArtifactType.MANIFEST: "context-manifest.schema.json",
    ContextArtifactType.GRAPH: "context-graph.schema.json",
    ContextArtifactType.QUERY: "context-query.schema.json",
    ContextArtifactType.SELECTION: "context-selection.schema.json",
    ContextArtifactType.SNAPSHOT: "context-snapshot.schema.json",
    ContextArtifactType.COMPACTION: "context-compaction.schema.json",
    ContextArtifactType.HOST_SUMMARY_PROPOSAL: (
        "context-host-summary-proposal.schema.json"
    ),
    ContextArtifactType.QUALITY_REPORT: "context-quality-report.schema.json",
}


@pytest.mark.parametrize("artifact_type", list(ContextArtifactType))
def test_each_context_artifact_round_trips_and_matches_schema(
    artifact_type: ContextArtifactType,
) -> None:
    artifact = complete_artifacts()[artifact_type]
    encoded = serialize_context_artifact(artifact)
    loaded = parse_context_artifact_bytes(encoded, expected_type=artifact_type)
    assert loaded == artifact
    root = Path(__file__).resolve().parents[1]
    LocalSchemaValidator(root / "schemas").validate(
        SCHEMA_NAMES[artifact_type],
        json.loads(encoded),
    )


def test_canonical_json_and_identity_ignore_mapping_insertion_order() -> None:
    first = {"z": [3, 2, 1], "a": {"two": 2, "one": 1}}
    second = {"a": {"one": 1, "two": 2}, "z": [3, 2, 1]}
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert context_identity("CTX-TEST-", first) == context_identity(
        "CTX-TEST-",
        second,
    )
    assert context_identity("CTX-TEST-", first).startswith("CTX-TEST-")
    assert len(context_identity("CTX-TEST-", first)) == len("CTX-TEST-") + 64


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            b'{"schema_version":"1.0","schema_version":"1.0"}',
            "duplicate JSON key",
        ),
        (b'{"value":NaN}', "non-finite"),
        (b'{"value":1.5}', "unsupported JSON value"),
        (b'{"\\ud800":"value"}', "surrogate"),
    ],
)
def test_context_json_rejects_noncanonical_values(
    payload: bytes,
    message: str,
) -> None:
    with pytest.raises(ContextContractError, match=message):
        parse_context_artifact_bytes(payload)


def test_artifact_identity_mismatch_fails_closed() -> None:
    artifact = complete_artifacts()[ContextArtifactType.MANIFEST]
    payload = artifact.to_dict()
    payload["artifact_id"] = "CTX-MANIFEST-" + "0" * 64
    with pytest.raises(ContextContractError, match="identity"):
        parse_context_artifact_bytes(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "artifact_type",
    [ContextArtifactType.GRAPH, ContextArtifactType.SNAPSHOT],
)
def test_graph_and_snapshot_reject_fabricated_source_identity(
    artifact_type: ContextArtifactType,
) -> None:
    artifact = complete_artifacts()[artifact_type]
    value = artifact.value
    assert isinstance(value, (ContextGraph, ContextSnapshot))
    target = next(node for node in value.nodes if not node.required)
    fabricated = replace(target, source_id="CTX-SOURCE-" + "0" * 64)
    fabricated = replace(
        fabricated,
        node_id=node_identity(fabricated.content_dict()),
    )
    changed = replace(
        value,
        nodes=tuple(
            sorted(
                (
                    fabricated,
                    *(node for node in value.nodes if node.node_id != target.node_id),
                ),
                key=lambda node: node.node_id,
            )
        ),
        edges=(),
    )

    with pytest.raises(ContextContractError, match="source_id does not match"):
        parse_context_artifact_bytes(
            serialize_context_artifact(artifact_from_value(artifact_type, changed))
        )


@pytest.mark.parametrize(
    "artifact_type",
    [ContextArtifactType.GRAPH, ContextArtifactType.SNAPSHOT],
)
def test_graph_and_snapshot_reject_duplicate_source_identity(
    artifact_type: ContextArtifactType,
) -> None:
    artifact = complete_artifacts()[artifact_type]
    value = artifact.value
    assert isinstance(value, (ContextGraph, ContextSnapshot))
    first, second = sorted(
        (node for node in value.nodes if not node.required),
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
        value,
        nodes=tuple(
            sorted(
                (
                    duplicate,
                    *(node for node in value.nodes if node.node_id != second.node_id),
                ),
                key=lambda node: node.node_id,
            )
        ),
        edges=(),
    )

    with pytest.raises(ContextContractError, match="duplicate source"):
        parse_context_artifact_bytes(
            serialize_context_artifact(artifact_from_value(artifact_type, changed))
        )


def test_manifest_rejects_sensitivity_downgrade() -> None:
    artifact = complete_artifacts()[ContextArtifactType.MANIFEST]
    assert isinstance(artifact.value, ContextManifest)
    source = artifact.value.sources[0]
    changed_source = replace(source, sensitivity=Sensitivity.OWNER_PRIVATE)
    changed_source = replace(
        changed_source,
        source_id=context_identity("CTX-SOURCE-", changed_source.content_dict()),
    )
    changed = replace(
        artifact.value,
        sources=tuple(
            sorted(
                (changed_source, *artifact.value.sources[1:]),
                key=lambda item: item.source_id,
            )
        ),
        relationships=(),
    )
    changed_artifact = artifact_from_value(ContextArtifactType.MANIFEST, changed)
    with pytest.raises(ContextContractError, match="highest source sensitivity"):
        parse_context_artifact_bytes(serialize_context_artifact(changed_artifact))


def test_expires_at_requires_both_utc_timestamps() -> None:
    artifact = complete_artifacts()[ContextArtifactType.MANIFEST]
    payload = copy.deepcopy(artifact.to_dict())
    content = payload["content"]
    assert isinstance(content, dict)
    sources = content["sources"]
    assert isinstance(sources, list)
    source = sources[0]
    assert isinstance(source, dict)
    source["freshness"] = {
        "kind": FreshnessKind.EXPIRES_AT.value,
        "observed_at": "2026-07-31T00:00:00Z",
        "valid_until": None,
    }
    with pytest.raises(ContextContractError, match="requires observed_at"):
        _rehash_source_and_manifest(payload)


def test_missing_source_sensitivity_defaults_to_owner_private() -> None:
    artifact = complete_artifacts()[ContextArtifactType.MANIFEST]
    payload = copy.deepcopy(artifact.to_dict())
    content = payload["content"]
    assert isinstance(content, dict)
    content["sensitivity"] = Sensitivity.OWNER_PRIVATE.value
    sources = content["sources"]
    assert isinstance(sources, list)
    source = sources[0]
    assert isinstance(source, dict)
    source.pop("sensitivity")
    normalized_source = {
        key: value for key, value in source.items() if key != "source_id"
    }
    normalized_source["sensitivity"] = Sensitivity.OWNER_PRIVATE.value
    source["source_id"] = context_identity("CTX-SOURCE-", normalized_source)
    sources.sort(key=lambda item: item["source_id"])
    content["relationships"] = []
    normalized_content = copy.deepcopy(content)
    normalized_sources = normalized_content["sources"]
    assert isinstance(normalized_sources, list)
    normalized_defaulted = next(
        item
        for item in normalized_sources
        if isinstance(item, dict) and "sensitivity" not in item
    )
    normalized_defaulted["sensitivity"] = Sensitivity.OWNER_PRIVATE.value
    payload["artifact_id"] = context_identity(
        "CTX-MANIFEST-",
        normalized_content,
    )

    loaded = parse_context_artifact_bytes(json.dumps(payload).encode())
    assert isinstance(loaded.value, ContextManifest)
    defaulted = next(
        item
        for item in loaded.value.sources
        if item.sensitivity is Sensitivity.OWNER_PRIVATE
    )
    assert defaulted.sensitivity is Sensitivity.OWNER_PRIVATE


def test_immutable_markdown_source_is_rejected() -> None:
    artifact = complete_artifacts()[ContextArtifactType.MANIFEST]
    payload = copy.deepcopy(artifact.to_dict())
    content = payload["content"]
    assert isinstance(content, dict)
    sources = content["sources"]
    assert isinstance(sources, list)
    source = sources[0]
    assert isinstance(source, dict)
    source["freshness"] = {
        "kind": FreshnessKind.IMMUTABLE.value,
        "observed_at": None,
        "valid_until": None,
    }
    with pytest.raises(ContextContractError, match="self-linked JSON"):
        _rehash_source_and_manifest(payload)


def test_graph_rejects_immutable_markdown_node() -> None:
    artifact = complete_artifacts()[ContextArtifactType.GRAPH]
    assert isinstance(artifact.value, ContextGraph)
    optional = next(node for node in artifact.value.nodes if not node.required)
    changed = replace(
        optional,
        freshness=Freshness(FreshnessKind.IMMUTABLE),
    )
    changed = replace(
        changed,
        source_id=source_identity(changed.source_content_dict()),
    )
    changed = replace(changed, node_id=node_identity(changed.content_dict()))
    nodes = tuple(
        sorted(
            (
                changed,
                *(
                    node
                    for node in artifact.value.nodes
                    if node.node_id != optional.node_id
                ),
            ),
            key=lambda node: node.node_id,
        )
    )
    graph = replace(artifact.value, nodes=nodes, edges=())
    with pytest.raises(ContextContractError, match="self-linked JSON"):
        parse_context_artifact_bytes(
            serialize_context_artifact(
                artifact_from_value(ContextArtifactType.GRAPH, graph)
            )
        )


def test_graph_requires_candidate_bound_canonical_specification() -> None:
    artifact = complete_artifacts()[ContextArtifactType.GRAPH]
    assert isinstance(artifact.value, ContextGraph)
    changed = replace(
        artifact.value,
        candidate=replace(
            artifact.value.candidate,
            source_spec_sha256="D" * 64,
        ),
    )
    with pytest.raises(ContextContractError, match="canonical specification"):
        parse_context_artifact_bytes(
            serialize_context_artifact(
                artifact_from_value(ContextArtifactType.GRAPH, changed)
            )
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda source: source["locator"].update(path="../secret"), "pattern"),
        (lambda source: source.update(labels=["x"] * 65), "maxItems"),
        (
            lambda source: source.update(
                freshness={
                    "kind": FreshnessKind.IMMUTABLE.value,
                    "observed_at": "2026-07-31T00:00:00Z",
                    "valid_until": "2026-07-31T01:00:00Z",
                }
            ),
            "type",
        ),
    ],
)
def test_manifest_schema_rejects_path_label_and_freshness_boundaries(
    mutation: Callable[[dict[str, Any]], object],
    message: str,
) -> None:
    artifact = complete_artifacts()[ContextArtifactType.MANIFEST]
    payload = copy.deepcopy(artifact.to_dict())
    content = payload["content"]
    assert isinstance(content, dict)
    sources = content["sources"]
    assert isinstance(sources, list)
    source = sources[0]
    assert isinstance(source, dict)
    mutation(source)
    root = Path(__file__).resolve().parents[1]
    with pytest.raises(SchemaValidationError, match=message):
        LocalSchemaValidator(root / "schemas").validate(
            "context-manifest.schema.json",
            payload,
        )


def test_graph_rejects_aggregate_text_above_eight_mib() -> None:
    artifact = complete_artifacts()[ContextArtifactType.GRAPH]
    assert isinstance(artifact.value, ContextGraph)
    original = artifact.value.nodes[0]
    nodes = []
    for index in range(129):
        text = f"{index:03d}:" + ("x" * (64 * 1024 - 4))
        changed = replace(
            original,
            text=text,
            text_sha256=hashlib.sha256(text.encode()).hexdigest().upper(),
        )
        nodes.append(replace(changed, node_id=node_identity(changed.content_dict())))
    changed_graph = replace(
        artifact.value,
        nodes=tuple(sorted(nodes, key=lambda item: item.node_id)),
        edges=(),
    )
    changed_artifact = artifact_from_value(
        ContextArtifactType.GRAPH,
        changed_graph,
    )
    with pytest.raises(ContextContractError, match="aggregate text limit"):
        parse_context_artifact_bytes(serialize_context_artifact(changed_artifact))


def test_snapshot_requires_canonical_node_even_as_standalone_artifact() -> None:
    artifact = complete_artifacts()[ContextArtifactType.SNAPSHOT]
    assert isinstance(artifact.value, ContextSnapshot)
    optional = next(node for node in artifact.value.nodes if not node.required)
    decision = next(
        item for item in artifact.value.selected if item.node_id == optional.node_id
    )
    changed = replace(
        artifact.value,
        nodes=(optional,),
        edges=(),
        selected=(decision,),
        context_bytes=decision.cost_bytes,
        unresolved_contradiction_ids=(),
    )
    with pytest.raises(ContextContractError, match="canonical specification"):
        parse_context_artifact_bytes(
            serialize_context_artifact(
                artifact_from_value(ContextArtifactType.SNAPSHOT, changed)
            )
        )


def test_snapshot_recomputes_selected_cost_from_canonical_node_content() -> None:
    artifact = complete_artifacts()[ContextArtifactType.SNAPSHOT]
    assert isinstance(artifact.value, ContextSnapshot)
    first = artifact.value.selected[0]
    changed = replace(
        artifact.value,
        selected=(replace(first, cost_bytes=1), *artifact.value.selected[1:]),
    )
    with pytest.raises(ContextContractError, match="selected cost"):
        parse_context_artifact_bytes(
            serialize_context_artifact(
                artifact_from_value(ContextArtifactType.SNAPSHOT, changed)
            )
        )


def test_snapshot_rejects_structurally_invalid_authority_node() -> None:
    artifact = complete_artifacts()[ContextArtifactType.SNAPSHOT]
    assert isinstance(artifact.value, ContextSnapshot)
    canonical = next(node for node in artifact.value.nodes if node.required)
    changed = replace(
        canonical,
        authority=AuthorityClass.VERIFIED_EVIDENCE,
    )
    changed = replace(
        changed,
        source_id=source_identity(changed.source_content_dict()),
    )
    changed = replace(changed, node_id=node_identity(changed.content_dict()))
    snapshot = replace(
        artifact.value,
        nodes=tuple(
            sorted(
                (
                    changed,
                    *(
                        node
                        for node in artifact.value.nodes
                        if node.node_id != canonical.node_id
                    ),
                ),
                key=lambda node: node.node_id,
            )
        ),
        edges=(),
    )
    with pytest.raises(ContextContractError, match="Verified evidence authority"):
        parse_context_artifact_bytes(
            serialize_context_artifact(
                artifact_from_value(ContextArtifactType.SNAPSHOT, snapshot)
            )
        )


def test_compaction_requires_at_least_one_required_extract() -> None:
    artifact = complete_artifacts()[ContextArtifactType.COMPACTION]
    assert isinstance(artifact.value, ContextCompaction)
    optional = tuple(item for item in artifact.value.extracts if not item.required)
    changed = replace(
        artifact.value,
        extracts=optional,
        used_bytes=sum(item.cost_bytes for item in optional),
    )
    with pytest.raises(ContextContractError, match="preserve required context"):
        parse_context_artifact_bytes(
            serialize_context_artifact(
                artifact_from_value(ContextArtifactType.COMPACTION, changed)
            )
        )


def test_graph_schema_and_runtime_share_conservative_unicode_character_bound() -> None:
    artifact = complete_artifacts()[ContextArtifactType.GRAPH]
    assert isinstance(artifact.value, ContextGraph)
    original_graph = artifact.value
    original = next(node for node in original_graph.nodes if not node.required)
    root = Path(__file__).resolve().parents[1]

    def changed_artifact(text: str) -> LoadedContextArtifact:
        changed = replace(
            original,
            text=text,
            text_sha256=hashlib.sha256(text.encode()).hexdigest().upper(),
        )
        changed = replace(changed, node_id=node_identity(changed.content_dict()))
        graph = replace(
            original_graph,
            nodes=tuple(
                sorted(
                    (
                        changed,
                        *(
                            node
                            for node in original_graph.nodes
                            if node.node_id != original.node_id
                        ),
                    ),
                    key=lambda node: node.node_id,
                )
            ),
            edges=(),
        )
        return artifact_from_value(ContextArtifactType.GRAPH, graph)

    boundary = changed_artifact("\U0001f600" * (64 * 1024))
    encoded = serialize_context_artifact(boundary)
    parse_context_artifact_bytes(encoded)
    LocalSchemaValidator(root / "schemas").validate(
        "context-graph.schema.json",
        json.loads(encoded),
    )

    excessive = changed_artifact("\u20ac" * (64 * 1024 + 1))
    encoded = serialize_context_artifact(excessive)
    with pytest.raises(ContextContractError, match="source text limit"):
        parse_context_artifact_bytes(encoded)
    with pytest.raises(SchemaValidationError, match="maxLength"):
        LocalSchemaValidator(root / "schemas").validate(
            "context-graph.schema.json",
            json.loads(encoded),
        )


def test_graph_schema_and_runtime_share_ordinary_text_character_bounds() -> None:
    artifact = complete_artifacts()[ContextArtifactType.GRAPH]
    assert isinstance(artifact.value, ContextGraph)
    graph = artifact.value
    original = next(node for node in graph.nodes if not node.required)
    root = Path(__file__).resolve().parents[1]

    def encoded_with_title(title: str) -> bytes:
        changed = replace(original, title=title)
        changed = replace(
            changed,
            source_id=source_identity(changed.source_content_dict()),
        )
        changed = replace(changed, node_id=node_identity(changed.content_dict()))
        value = replace(
            graph,
            nodes=tuple(
                sorted(
                    (
                        changed,
                        *(node for node in graph.nodes if node.node_id != original.node_id),
                    ),
                    key=lambda node: node.node_id,
                )
            ),
            edges=(),
        )
        return serialize_context_artifact(
            artifact_from_value(ContextArtifactType.GRAPH, value)
        )

    boundary = encoded_with_title("\U0001f600" * 500)
    parse_context_artifact_bytes(boundary)
    LocalSchemaValidator(root / "schemas").validate(
        "context-graph.schema.json",
        json.loads(boundary),
    )

    excessive = encoded_with_title("\U0001f600" * 501)
    with pytest.raises(ContextContractError, match="text limit"):
        parse_context_artifact_bytes(excessive)
    with pytest.raises(SchemaValidationError, match="maxLength"):
        LocalSchemaValidator(root / "schemas").validate(
            "context-graph.schema.json",
            json.loads(excessive),
        )


def test_context_top_level_public_exports_remain_unchanged() -> None:
    assert sdaqf.__all__ == [
        "GateCheck",
        "GateResult",
        "ToolCapability",
        "ToolStatus",
    ]


def test_frozen_domain_values_reject_mutation() -> None:
    freshness = Freshness(FreshnessKind.IMMUTABLE)
    with pytest.raises((AttributeError, TypeError)):
        freshness.kind = FreshnessKind.CANDIDATE_BOUND  # type: ignore[misc]


def _rehash_source_and_manifest(payload: dict[str, object]) -> None:
    content = payload["content"]
    assert isinstance(content, dict)
    sources = content["sources"]
    assert isinstance(sources, list)
    source = sources[0]
    assert isinstance(source, dict)
    source_content = {key: value for key, value in source.items() if key != "source_id"}
    source["source_id"] = context_identity("CTX-SOURCE-", source_content)
    sources.sort(key=lambda item: item["source_id"])
    payload["artifact_id"] = context_identity("CTX-MANIFEST-", content)
    parse_context_artifact_bytes(json.dumps(payload).encode())
