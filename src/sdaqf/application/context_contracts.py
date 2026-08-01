"""Strict content-addressed contracts for the M5 Context Framework."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sdaqf.application.contracts import (
    ContractError,
    array_value,
    boolean_value,
    enum_value,
    integer_value,
    object_value,
    only_keys,
    parse_artifact_reference,
    parse_candidate_identity,
    safe_relative_path,
    sha256,
    string_value,
)
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.context import (
    AUTHORITY_RANK,
    SENSITIVITY_RANK,
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
    ContextSourceExclusion,
    EdgeType,
    ExclusionDecision,
    Freshness,
    FreshnessKind,
    HostSummaryProposal,
    RootScope,
    SelectionDecision,
    Sensitivity,
    SourceKind,
    SourceLinkedClaim,
    SourceLocator,
)

SMALL_ARTIFACT_BYTES = 1 * 1024 * 1024
LARGE_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024
MAX_SOURCE_CHARACTERS = 64 * 1024
MAX_TOTAL_SOURCE_BYTES = 8 * 1024 * 1024
MAX_GRAPH_NODES = 4096
MAX_GRAPH_EDGES = 16384
MAX_JSON_NODES = 250_000

_ID_PREFIX: dict[ContextArtifactType, str] = {
    ContextArtifactType.MANIFEST: "CTX-MANIFEST-",
    ContextArtifactType.GRAPH: "CTX-GRAPH-",
    ContextArtifactType.QUERY: "CTX-QUERY-",
    ContextArtifactType.SELECTION: "CTX-SELECTION-",
    ContextArtifactType.SNAPSHOT: "CTX-SNAPSHOT-",
    ContextArtifactType.COMPACTION: "CTX-COMPACTION-",
    ContextArtifactType.HOST_SUMMARY_PROPOSAL: "CTX-HOST-SUMMARY-PROPOSAL-",
    ContextArtifactType.QUALITY_REPORT: "CTX-QUALITY-REPORT-",
}
_SMALL_TYPES = {
    ContextArtifactType.MANIFEST,
    ContextArtifactType.QUERY,
    ContextArtifactType.HOST_SUMMARY_PROPOSAL,
}
_RFC3339_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
_CONTEXT_ID = re.compile(r"^CTX-[A-Z-]+-[0-9A-F]{64}$")
_SECRET = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

type ContextValue = (
    ContextManifest
    | ContextGraph
    | ContextQuery
    | ContextSelection
    | ContextSnapshot
    | ContextCompaction
    | HostSummaryProposal
    | ContextQualityReport
)


class ContextContractError(ContractError):
    """One Context artifact violates its strict contract."""


@dataclass(frozen=True, slots=True)
class LoadedContextArtifact:
    """Validated content-addressed artifact."""

    artifact_type: ContextArtifactType
    artifact_id: str
    value: ContextValue

    def to_dict(self) -> dict[str, object]:
        """Return the exact public JSON envelope."""

        return {
            "schema_version": "1.0",
            "artifact_type": self.artifact_type.value,
            "artifact_id": self.artifact_id,
            "content": self.value.to_dict(),
        }


def canonical_json_bytes(value: object) -> bytes:
    """Serialize one strict canonical value for portable identity and budget."""

    _validate_canonical_value(value, "canonical content")
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ContextContractError("Canonical content cannot be serialized.") from exc


def validate_context_json_bytes(content: bytes) -> None:
    """Require bounded strict JSON suitable for immutable Context evidence."""

    if len(content) > MAX_SOURCE_BYTES:
        raise ContextContractError("Immutable Context JSON exceeds the size limit.")

    def strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ContextContractError(
                    "Immutable Context JSON contains a duplicate key."
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ContextContractError(
            f"Immutable Context JSON contains non-finite number {value}."
        )

    try:
        decoded: object = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=strict_object,
            parse_constant=reject_constant,
        )
    except ContextContractError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ContextContractError("Immutable Context evidence is not strict JSON.") from exc
    _validate_canonical_value(decoded, "Immutable Context JSON")


def context_identity(prefix: str, content: object) -> str:
    """Return a full content-addressed Context identity."""

    if not re.fullmatch(r"CTX-[A-Z-]+-", prefix):
        raise ValueError("Context identity prefix is invalid")
    digest = hashlib.sha256(canonical_json_bytes(content)).hexdigest().upper()
    return f"{prefix}{digest}"


def source_identity(content: object) -> str:
    """Return one source identity."""

    return context_identity("CTX-SOURCE-", content)


def node_identity(content: object) -> str:
    """Return one node identity."""

    return context_identity("CTX-NODE-", content)


def edge_identity(content: object) -> str:
    """Return one edge identity."""

    return context_identity("CTX-EDGE-", content)


def validate_context_authority(
    source: ContextSource | ContextNode,
) -> None:
    """Require authority metadata to match its structural trust boundary."""

    self_reference = any(
        reference.path == source.locator.path
        and reference.sha256 == source.locator.sha256
        for reference in source.provenance.references
    )
    if source.authority in {
        AuthorityClass.OWNER_APPROVED,
        AuthorityClass.CANONICAL_SPECIFICATION,
        AuthorityClass.ACCEPTED_PUBLIC_CONTRACT,
        AuthorityClass.VERIFIED_EVIDENCE,
    } and not self_reference:
        raise ContextContractError(
            "Authoritative Context source lacks exact self provenance."
        )
    if source.authority is AuthorityClass.OWNER_APPROVED and (
        source.locator.root_scope is not RootScope.OWNER
        or source.kind
        not in {
            SourceKind.REQUIREMENT,
            SourceKind.DECISION,
            SourceKind.DESIGN,
            SourceKind.HANDOFF,
        }
        or source.provenance.producer != "Owner"
        or source.provenance.recorded_by != "Owner"
    ):
        raise ContextContractError("Owner-approved Context authority is invalid.")
    if source.authority is AuthorityClass.CANONICAL_SPECIFICATION and (
        source.locator.root_scope is not RootScope.REPOSITORY
        or source.kind is not SourceKind.SPECIFICATION
    ):
        raise ContextContractError("Canonical specification authority is invalid.")
    if source.authority is AuthorityClass.ACCEPTED_PUBLIC_CONTRACT and (
        source.locator.root_scope is not RootScope.REPOSITORY
        or source.kind
        not in {
            SourceKind.REQUIREMENT,
            SourceKind.DECISION,
            SourceKind.DESIGN,
        }
    ):
        raise ContextContractError("Accepted public contract authority is invalid.")
    if source.authority is AuthorityClass.VERIFIED_EVIDENCE and (
        source.locator.root_scope is not RootScope.REPOSITORY
        or source.kind is not SourceKind.EVIDENCE
    ):
        raise ContextContractError("Verified evidence authority is invalid.")
    if (
        source.kind is SourceKind.TOOL_OBSERVATION
        and source.authority is not AuthorityClass.UNTRUSTED_OBSERVATION
    ):
        raise ContextContractError("Tool observation authority must be untrusted.")
    _validate_immutable_context(source, "Context source")


def _validate_immutable_context(
    source: ContextSource | ContextNode,
    where: str,
) -> None:
    if source.freshness.kind is not FreshnessKind.IMMUTABLE:
        return
    self_reference = any(
        reference.path == source.locator.path
        and reference.sha256 == source.locator.sha256
        for reference in source.provenance.references
    )
    if (
        not source.locator.path.casefold().endswith(".json")
        or source.authority
        not in {
            AuthorityClass.OWNER_APPROVED,
            AuthorityClass.CANONICAL_SPECIFICATION,
            AuthorityClass.ACCEPTED_PUBLIC_CONTRACT,
            AuthorityClass.VERIFIED_EVIDENCE,
        }
        or not self_reference
    ):
        raise ContextContractError(
            f"{where}.freshness immutable requires verified self-linked JSON."
        )


def artifact_from_value(
    artifact_type: ContextArtifactType,
    value: ContextValue,
) -> LoadedContextArtifact:
    """Create a validated identity envelope from a typed value."""

    content = value.to_dict()
    artifact_id = context_identity(_ID_PREFIX[artifact_type], content)
    return LoadedContextArtifact(artifact_type, artifact_id, value)


def serialize_context_artifact(artifact: LoadedContextArtifact) -> bytes:
    """Serialize one artifact as deterministic pretty public JSON."""

    expected = context_identity(
        _ID_PREFIX[artifact.artifact_type],
        artifact.value.to_dict(),
    )
    if artifact.artifact_id != expected:
        raise ContextContractError("Context artifact identity does not match content.")
    payload = artifact.to_dict()
    return (
        json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    ).encode("ascii")


def load_context_artifact(
    path: Path,
    *,
    expected_type: ContextArtifactType | None = None,
) -> LoadedContextArtifact:
    """Load a bounded regular unlinked Context JSON artifact."""

    if path.suffix.casefold() != ".json":
        raise ContextContractError("Context artifact must be a JSON file.")
    if path.is_symlink() or is_reparse_point(path) or not path.is_file():
        raise ContextContractError("Context artifact must be a regular unlinked file.")
    try:
        size = path.stat().st_size
        if size > LARGE_ARTIFACT_BYTES:
            raise ContextContractError("Context artifact exceeds the size limit.")
        content = path.read_bytes()
    except ContextContractError:
        raise
    except OSError as exc:
        raise ContextContractError("Context artifact could not be read.") from exc
    return parse_context_artifact_bytes(content, expected_type=expected_type)


def parse_context_artifact_bytes(
    content: bytes,
    *,
    expected_type: ContextArtifactType | None = None,
) -> LoadedContextArtifact:
    """Parse one immutable strict UTF-8 Context artifact snapshot."""

    if len(content) > LARGE_ARTIFACT_BYTES:
        raise ContextContractError("Context artifact exceeds the size limit.")

    def strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ContextContractError(
                    "Context artifact contains a duplicate JSON key."
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ContextContractError(
            f"Context artifact contains non-finite JSON number {value}."
        )

    try:
        raw: object = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=strict_object,
            parse_constant=reject_constant,
        )
    except ContextContractError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ContextContractError("Context artifact could not be read.") from exc
    _validate_canonical_value(raw, "Context artifact")
    root = object_value(raw, "Context artifact")
    only_keys(
        root,
        {"schema_version", "artifact_type", "artifact_id", "content"},
        "Context artifact",
    )
    if root.get("schema_version") != "1.0":
        raise ContextContractError("Context artifact schema_version must be 1.0.")
    artifact_type = enum_value(
        ContextArtifactType,
        root.get("artifact_type"),
        "artifact_type",
    )
    if expected_type is not None and artifact_type is not expected_type:
        raise ContextContractError("Context artifact type is not the expected type.")
    maximum = (
        SMALL_ARTIFACT_BYTES
        if artifact_type in _SMALL_TYPES
        else LARGE_ARTIFACT_BYTES
    )
    if len(content) > maximum:
        raise ContextContractError("Context artifact exceeds its type size limit.")
    content_object = object_value(root.get("content"), "content")
    value = _parse_value(artifact_type, content_object)
    artifact_id = context_id(
        root.get("artifact_id"),
        "artifact_id",
        prefix=_ID_PREFIX[artifact_type],
    )
    expected = context_identity(_ID_PREFIX[artifact_type], value.to_dict())
    if artifact_id != expected:
        raise ContextContractError("Context artifact identity does not match content.")
    return LoadedContextArtifact(artifact_type, artifact_id, value)


def context_id(value: object, where: str, *, prefix: str | None = None) -> str:
    """Require a full uppercase Context identity."""

    text = string_value(value, where, maximum=128)
    if not _CONTEXT_ID.fullmatch(text) or (
        prefix is not None and not text.startswith(prefix)
    ):
        raise ContextContractError(f"{where} must be a full Context identity.")
    return text


def _validate_canonical_value(value: object, label: str) -> None:
    """Reject floats, non-ASCII keys, surrogates, excessive depth, and size."""

    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > 64 or nodes > MAX_JSON_NODES:
            raise ContextContractError(f"{label} exceeds the JSON structure limit.")
        if isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ContextContractError(f"{label} contains a non-string key.")
                if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                    raise ContextContractError(f"{label} contains a surrogate.")
                if not key.isascii():
                    raise ContextContractError(f"{label} contains a non-ASCII key.")
                stack.append((item, depth + 1))
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in current):
                raise ContextContractError(f"{label} contains a surrogate.")
        elif current is None or isinstance(current, (bool, int)):
            continue
        else:
            raise ContextContractError(f"{label} contains unsupported JSON value.")


def _parse_value(
    artifact_type: ContextArtifactType,
    value: dict[str, object],
) -> ContextValue:
    if artifact_type is ContextArtifactType.MANIFEST:
        return _parse_manifest(value)
    if artifact_type is ContextArtifactType.GRAPH:
        return _parse_graph(value)
    if artifact_type is ContextArtifactType.QUERY:
        return _parse_query(value)
    if artifact_type is ContextArtifactType.SELECTION:
        return _parse_selection(value)
    if artifact_type is ContextArtifactType.SNAPSHOT:
        return _parse_snapshot(value)
    if artifact_type is ContextArtifactType.COMPACTION:
        return _parse_compaction(value)
    if artifact_type is ContextArtifactType.HOST_SUMMARY_PROPOSAL:
        return _parse_host_summary(value)
    return _parse_quality(value)


def _parse_manifest(value: dict[str, object]) -> ContextManifest:
    only_keys(
        value,
        {"candidate", "sensitivity", "sources", "relationships"},
        "content",
    )
    sources = tuple(
        _parse_source(item, f"content.sources[{index}]")
        for index, item in enumerate(
            array_value(value.get("sources"), "content.sources", maximum=MAX_GRAPH_NODES)
        )
    )
    if not sources:
        raise ContextContractError("content.sources must not be empty.")
    _ascending_unique(
        tuple(item.source_id for item in sources),
        "content.sources",
    )
    source_ids = {item.source_id for item in sources}
    relationships = tuple(
        _parse_relationship(item, f"content.relationships[{index}]", source_ids)
        for index, item in enumerate(
            array_value(
                value.get("relationships"),
                "content.relationships",
                maximum=MAX_GRAPH_EDGES,
            )
        )
    )
    relationship_order = tuple(
        (item.edge_type.value, item.source_id, item.target_id)
        for item in relationships
    )
    _ascending_unique(relationship_order, "content.relationships")
    sensitivity = enum_value(
        Sensitivity,
        value.get("sensitivity"),
        "content.sensitivity",
    )
    _reject_prohibited(sensitivity, "content.sensitivity")
    _require_derived_sensitivity(
        sensitivity,
        tuple(item.sensitivity for item in sources),
        "content.sensitivity",
    )
    return ContextManifest(
        candidate=parse_candidate_identity(value.get("candidate"), "content.candidate"),
        sensitivity=sensitivity,
        sources=sources,
        relationships=relationships,
    )


def _parse_source(value: object, where: str) -> ContextSource:
    item = object_value(value, where)
    if "sensitivity" not in item:
        item = {**item, "sensitivity": Sensitivity.OWNER_PRIVATE.value}
    only_keys(
        item,
        {
            "source_id",
            "kind",
            "title",
            "locator",
            "provenance",
            "authority",
            "freshness",
            "sensitivity",
            "identifiers",
            "labels",
            "required",
        },
        where,
    )
    sensitivity = enum_value(
        Sensitivity,
        item.get("sensitivity", Sensitivity.OWNER_PRIVATE.value),
        f"{where}.sensitivity",
    )
    _reject_prohibited(sensitivity, f"{where}.sensitivity")
    result = ContextSource(
        source_id=context_id(
            item.get("source_id"),
            f"{where}.source_id",
            prefix="CTX-SOURCE-",
        ),
        kind=enum_value(SourceKind, item.get("kind"), f"{where}.kind"),
        title=_context_text(item.get("title"), f"{where}.title", maximum=500),
        locator=_parse_locator(item.get("locator"), f"{where}.locator"),
        provenance=_parse_provenance(
            item.get("provenance"),
            f"{where}.provenance",
        ),
        authority=enum_value(
            AuthorityClass,
            item.get("authority"),
            f"{where}.authority",
        ),
        freshness=_parse_freshness(item.get("freshness"), f"{where}.freshness"),
        sensitivity=sensitivity,
        identifiers=_sorted_text_tuple(
            item.get("identifiers"),
            f"{where}.identifiers",
            maximum=128,
        ),
        labels=_sorted_text_tuple(
            item.get("labels"),
            f"{where}.labels",
            maximum=64,
        ),
        required=boolean_value(item.get("required"), f"{where}.required"),
    )
    if result.source_id != source_identity(result.content_dict()):
        raise ContextContractError(f"{where}.source_id does not match content.")
    if (
        result.kind is SourceKind.TOOL_OBSERVATION
        and result.freshness.kind is not FreshnessKind.EXPIRES_AT
    ):
        raise ContextContractError(
            f"{where}.freshness must expire for tool observations."
        )
    _validate_immutable_context(result, where)
    return result


def _parse_relationship(
    value: object,
    where: str,
    source_ids: set[str],
) -> ContextRelationship:
    item = object_value(value, where)
    only_keys(
        item,
        {"edge_type", "source_id", "target_id", "provenance"},
        where,
    )
    edge_type = enum_value(EdgeType, item.get("edge_type"), f"{where}.edge_type")
    source = context_id(
        item.get("source_id"),
        f"{where}.source_id",
        prefix="CTX-SOURCE-",
    )
    target = context_id(
        item.get("target_id"),
        f"{where}.target_id",
        prefix="CTX-SOURCE-",
    )
    if source == target:
        raise ContextContractError(f"{where} must not be a self relationship.")
    if source not in source_ids or target not in source_ids:
        raise ContextContractError(f"{where} references a missing source.")
    if edge_type is EdgeType.CONTRADICTS and source > target:
        raise ContextContractError(
            f"{where} contradiction endpoints must be ascending."
        )
    return ContextRelationship(
        edge_type=edge_type,
        source_id=source,
        target_id=target,
        provenance=_parse_provenance(item.get("provenance"), f"{where}.provenance"),
    )


def _parse_graph(value: dict[str, object]) -> ContextGraph:
    only_keys(
        value,
        {
            "candidate",
            "manifest_id",
            "sensitivity",
            "nodes",
            "edges",
            "excluded_sources",
        },
        "content",
    )
    nodes = tuple(
        _parse_node(item, f"content.nodes[{index}]")
        for index, item in enumerate(
            array_value(value.get("nodes"), "content.nodes", maximum=MAX_GRAPH_NODES)
        )
    )
    if not nodes:
        raise ContextContractError("content.nodes must not be empty.")
    if sum(len(item.text.encode("utf-8")) for item in nodes) > MAX_TOTAL_SOURCE_BYTES:
        raise ContextContractError("content.nodes exceed the aggregate text limit.")
    _ascending_unique(tuple(item.node_id for item in nodes), "content.nodes")
    if len({item.source_id for item in nodes}) != len(nodes):
        raise ContextContractError("content.nodes contains a duplicate source.")
    for node in nodes:
        validate_context_authority(node)
    candidate = parse_candidate_identity(
        value.get("candidate"),
        "content.candidate",
    )
    canonical = [
        node
        for node in nodes
        if node.authority is AuthorityClass.CANONICAL_SPECIFICATION
    ]
    if (
        len(canonical) != 1
        or not canonical[0].required
        or canonical[0].kind is not SourceKind.SPECIFICATION
        or canonical[0].locator.root_scope is not RootScope.REPOSITORY
        or canonical[0].locator.sha256 != candidate.source_spec_sha256
    ):
        raise ContextContractError(
            "Graph must contain one required candidate-bound canonical specification."
        )
    node_ids = {item.node_id for item in nodes}
    edges = tuple(
        _parse_edge(item, f"content.edges[{index}]", node_ids)
        for index, item in enumerate(
            array_value(value.get("edges"), "content.edges", maximum=MAX_GRAPH_EDGES)
        )
    )
    _ascending_unique(tuple(item.edge_id for item in edges), "content.edges")
    excluded_sources = tuple(
        _parse_source_exclusion(item, f"content.excluded_sources[{index}]")
        for index, item in enumerate(
            array_value(
                value.get("excluded_sources"),
                "content.excluded_sources",
                maximum=MAX_GRAPH_NODES,
            )
        )
    )
    _ascending_unique(
        tuple(item.source_id for item in excluded_sources),
        "content.excluded_sources",
    )
    if {item.source_id for item in nodes} & {
        item.source_id for item in excluded_sources
    }:
        raise ContextContractError("Graph nodes and source exclusions must be disjoint.")
    sensitivity = enum_value(
        Sensitivity,
        value.get("sensitivity"),
        "content.sensitivity",
    )
    _reject_prohibited(sensitivity, "content.sensitivity")
    _require_derived_sensitivity(
        sensitivity,
        tuple(item.sensitivity for item in nodes),
        "content.sensitivity",
    )
    return ContextGraph(
        candidate=candidate,
        manifest_id=context_id(
            value.get("manifest_id"),
            "content.manifest_id",
            prefix="CTX-MANIFEST-",
        ),
        sensitivity=sensitivity,
        nodes=nodes,
        edges=edges,
        excluded_sources=excluded_sources,
    )


def _parse_source_exclusion(
    value: object,
    where: str,
) -> ContextSourceExclusion:
    item = object_value(value, where)
    only_keys(item, {"source_id", "reason", "details"}, where)
    return ContextSourceExclusion(
        source_id=context_id(
            item.get("source_id"),
            f"{where}.source_id",
            prefix="CTX-SOURCE-",
        ),
        reason=_context_text(item.get("reason"), f"{where}.reason", maximum=100),
        details=_sorted_text_tuple(
            item.get("details"),
            f"{where}.details",
            maximum=16,
        ),
    )


def _parse_node(value: object, where: str) -> ContextNode:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "node_id",
            "source_id",
            "kind",
            "title",
            "text",
            "text_sha256",
            "locator",
            "provenance",
            "authority",
            "freshness",
            "sensitivity",
            "identifiers",
            "labels",
            "required",
        },
        where,
    )
    sensitivity = enum_value(
        Sensitivity,
        item.get("sensitivity"),
        f"{where}.sensitivity",
    )
    _reject_prohibited(sensitivity, f"{where}.sensitivity")
    text = _context_text(
        item.get("text"),
        f"{where}.text",
        maximum=MAX_SOURCE_BYTES,
        allow_empty=True,
    )
    text_digest = sha256(item.get("text_sha256"), f"{where}.text_sha256")
    if hashlib.sha256(text.encode("utf-8")).hexdigest().upper() != text_digest:
        raise ContextContractError(f"{where}.text_sha256 does not match text.")
    result = ContextNode(
        node_id=context_id(
            item.get("node_id"),
            f"{where}.node_id",
            prefix="CTX-NODE-",
        ),
        source_id=context_id(
            item.get("source_id"),
            f"{where}.source_id",
            prefix="CTX-SOURCE-",
        ),
        kind=enum_value(SourceKind, item.get("kind"), f"{where}.kind"),
        title=_context_text(item.get("title"), f"{where}.title", maximum=500),
        text=text,
        text_sha256=text_digest,
        locator=_parse_locator(item.get("locator"), f"{where}.locator"),
        provenance=_parse_provenance(
            item.get("provenance"),
            f"{where}.provenance",
        ),
        authority=enum_value(
            AuthorityClass,
            item.get("authority"),
            f"{where}.authority",
        ),
        freshness=_parse_freshness(item.get("freshness"), f"{where}.freshness"),
        sensitivity=sensitivity,
        identifiers=_sorted_text_tuple(
            item.get("identifiers"),
            f"{where}.identifiers",
            maximum=128,
        ),
        labels=_sorted_text_tuple(
            item.get("labels"),
            f"{where}.labels",
            maximum=64,
        ),
        required=boolean_value(item.get("required"), f"{where}.required"),
    )
    if result.node_id != node_identity(result.content_dict()):
        raise ContextContractError(f"{where}.node_id does not match content.")
    if result.source_id != source_identity(result.source_content_dict()):
        raise ContextContractError(f"{where}.source_id does not match content.")
    _validate_immutable_context(result, where)
    return result


def _parse_edge(value: object, where: str, node_ids: set[str]) -> ContextEdge:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "edge_id",
            "edge_type",
            "source_node_id",
            "target_node_id",
            "provenance",
        },
        where,
    )
    edge_type = enum_value(EdgeType, item.get("edge_type"), f"{where}.edge_type")
    source = context_id(
        item.get("source_node_id"),
        f"{where}.source_node_id",
        prefix="CTX-NODE-",
    )
    target = context_id(
        item.get("target_node_id"),
        f"{where}.target_node_id",
        prefix="CTX-NODE-",
    )
    if source == target:
        raise ContextContractError(f"{where} must not be a self edge.")
    if source not in node_ids or target not in node_ids:
        raise ContextContractError(f"{where} references a missing node.")
    if edge_type is EdgeType.CONTRADICTS and source > target:
        raise ContextContractError(
            f"{where} contradiction endpoints must be ascending."
        )
    result = ContextEdge(
        edge_id=context_id(
            item.get("edge_id"),
            f"{where}.edge_id",
            prefix="CTX-EDGE-",
        ),
        edge_type=edge_type,
        source_node_id=source,
        target_node_id=target,
        provenance=_parse_provenance(item.get("provenance"), f"{where}.provenance"),
    )
    if result.edge_id != edge_identity(result.content_dict()):
        raise ContextContractError(f"{where}.edge_id does not match content.")
    return result


def _parse_query(value: dict[str, object]) -> ContextQuery:
    only_keys(
        value,
        {
            "candidate",
            "graph_id",
            "as_of",
            "clearance",
            "required_node_ids",
            "seed_node_ids",
            "identifiers",
            "terms",
            "allowed_edge_types",
            "budget",
        },
        "content",
    )
    required = _sorted_id_tuple(
        value.get("required_node_ids"),
        "content.required_node_ids",
        prefix="CTX-NODE-",
    )
    seeds = _sorted_id_tuple(
        value.get("seed_node_ids"),
        "content.seed_node_ids",
        prefix="CTX-NODE-",
    )
    edge_types = tuple(
        enum_value(
            EdgeType,
            item,
            f"content.allowed_edge_types[{index}]",
        )
        for index, item in enumerate(
            array_value(
                value.get("allowed_edge_types"),
                "content.allowed_edge_types",
                maximum=len(EdgeType),
            )
        )
    )
    _ascending_unique(
        tuple(item.value for item in edge_types),
        "content.allowed_edge_types",
    )
    if not edge_types:
        raise ContextContractError("content.allowed_edge_types must not be empty.")
    return ContextQuery(
        candidate=parse_candidate_identity(value.get("candidate"), "content.candidate"),
        graph_id=context_id(
            value.get("graph_id"),
            "content.graph_id",
            prefix="CTX-GRAPH-",
        ),
        as_of=_utc_timestamp(value.get("as_of"), "content.as_of"),
        clearance=enum_value(
            Sensitivity,
            value.get("clearance"),
            "content.clearance",
        ),
        required_node_ids=required,
        seed_node_ids=seeds,
        identifiers=_sorted_text_tuple(
            value.get("identifiers"),
            "content.identifiers",
            maximum=128,
        ),
        terms=_sorted_text_tuple(
            value.get("terms"),
            "content.terms",
            maximum=128,
        ),
        allowed_edge_types=edge_types,
        budget=_parse_budget(value.get("budget"), "content.budget"),
    )


def _parse_selection(value: dict[str, object]) -> ContextSelection:
    only_keys(
        value,
        {
            "candidate",
            "graph_id",
            "query_id",
            "query",
            "as_of",
            "sensitivity",
            "selected",
            "excluded",
            "selected_edge_ids",
            "unresolved_contradiction_ids",
            "edge_cost_bytes",
            "used_bytes",
            "budget_bytes",
            "traversal_truncated",
        },
        "content",
    )
    query = _parse_query(object_value(value.get("query"), "content.query"))
    query_id = context_id(
        value.get("query_id"),
        "content.query_id",
        prefix="CTX-QUERY-",
    )
    if query_id != context_identity("CTX-QUERY-", query.to_dict()):
        raise ContextContractError("content.query_id does not match embedded Query.")
    candidate = parse_candidate_identity(value.get("candidate"), "content.candidate")
    graph_id = context_id(
        value.get("graph_id"),
        "content.graph_id",
        prefix="CTX-GRAPH-",
    )
    as_of = _utc_timestamp(value.get("as_of"), "content.as_of")
    if (
        query.candidate != candidate
        or query.graph_id != graph_id
        or query.as_of != as_of
    ):
        raise ContextContractError("Selection does not match its embedded Query.")
    sensitivity = enum_value(
        Sensitivity,
        value.get("sensitivity"),
        "content.sensitivity",
    )
    _reject_prohibited(sensitivity, "content.sensitivity")
    selected = tuple(
        _parse_selection_decision(item, f"content.selected[{index}]")
        for index, item in enumerate(
            array_value(value.get("selected"), "content.selected", maximum=MAX_GRAPH_NODES)
        )
    )
    if not selected:
        raise ContextContractError("content.selected must not be empty.")
    if len({item.node_id for item in selected}) != len(selected):
        raise ContextContractError("content.selected contains a duplicate node.")
    excluded = tuple(
        _parse_exclusion(item, f"content.excluded[{index}]")
        for index, item in enumerate(
            array_value(value.get("excluded"), "content.excluded", maximum=MAX_GRAPH_NODES)
        )
    )
    _ascending_unique(
        tuple(item.node_id for item in excluded),
        "content.excluded",
    )
    if {item.node_id for item in selected} & {item.node_id for item in excluded}:
        raise ContextContractError("Selected and excluded nodes must be disjoint.")
    budget_bytes = integer_value(
        value.get("budget_bytes"),
        "content.budget_bytes",
        minimum=1024,
        maximum=8_388_608,
    )
    used_bytes = integer_value(
        value.get("used_bytes"),
        "content.used_bytes",
        minimum=0,
        maximum=8_388_608,
    )
    edge_cost_bytes = integer_value(
        value.get("edge_cost_bytes"),
        "content.edge_cost_bytes",
        minimum=0,
        maximum=8_388_608,
    )
    if used_bytes > budget_bytes:
        raise ContextContractError("content.used_bytes exceeds its budget.")
    if budget_bytes != query.budget.budget_bytes:
        raise ContextContractError(
            "content.budget_bytes does not match embedded Query."
        )
    if used_bytes != sum(item.cost_bytes for item in selected) + edge_cost_bytes:
        raise ContextContractError("content.used_bytes does not match selected costs.")
    return ContextSelection(
        candidate=candidate,
        graph_id=graph_id,
        query_id=query_id,
        query=query,
        as_of=as_of,
        sensitivity=sensitivity,
        selected=selected,
        excluded=excluded,
        selected_edge_ids=_sorted_id_tuple(
            value.get("selected_edge_ids"),
            "content.selected_edge_ids",
            prefix="CTX-EDGE-",
            maximum=MAX_GRAPH_EDGES,
        ),
        unresolved_contradiction_ids=_sorted_id_tuple(
            value.get("unresolved_contradiction_ids"),
            "content.unresolved_contradiction_ids",
            prefix="CTX-EDGE-",
            maximum=MAX_GRAPH_EDGES,
        ),
        edge_cost_bytes=edge_cost_bytes,
        used_bytes=used_bytes,
        budget_bytes=budget_bytes,
        traversal_truncated=boolean_value(
            value.get("traversal_truncated"),
            "content.traversal_truncated",
        ),
    )


def _parse_snapshot(value: dict[str, object]) -> ContextSnapshot:
    only_keys(
        value,
        {
            "candidate",
            "graph_id",
            "query_id",
            "selection_id",
            "as_of",
            "sensitivity",
            "nodes",
            "edges",
            "selected",
            "excluded",
            "unresolved_contradiction_ids",
            "context_bytes",
            "budget_bytes",
        },
        "content",
    )
    nodes = tuple(
        _parse_node(item, f"content.nodes[{index}]")
        for index, item in enumerate(
            array_value(value.get("nodes"), "content.nodes", maximum=MAX_GRAPH_NODES)
        )
    )
    if not nodes:
        raise ContextContractError("Snapshot nodes must not be empty.")
    _ascending_unique(tuple(item.node_id for item in nodes), "content.nodes")
    if len({item.source_id for item in nodes}) != len(nodes):
        raise ContextContractError("content.nodes contains a duplicate source.")
    for node in nodes:
        validate_context_authority(node)
    candidate = parse_candidate_identity(
        value.get("candidate"),
        "content.candidate",
    )
    canonical = [
        node
        for node in nodes
        if node.authority is AuthorityClass.CANONICAL_SPECIFICATION
    ]
    if (
        len(canonical) != 1
        or not canonical[0].required
        or canonical[0].kind is not SourceKind.SPECIFICATION
        or canonical[0].locator.root_scope is not RootScope.REPOSITORY
        or canonical[0].locator.sha256 != candidate.source_spec_sha256
    ):
        raise ContextContractError(
            "Snapshot must contain one required candidate-bound canonical "
            "specification."
        )
    node_ids = {item.node_id for item in nodes}
    edges = tuple(
        _parse_edge(item, f"content.edges[{index}]", node_ids)
        for index, item in enumerate(
            array_value(value.get("edges"), "content.edges", maximum=MAX_GRAPH_EDGES)
        )
    )
    _ascending_unique(tuple(item.edge_id for item in edges), "content.edges")
    selected = tuple(
        _parse_selection_decision(item, f"content.selected[{index}]")
        for index, item in enumerate(
            array_value(value.get("selected"), "content.selected", maximum=MAX_GRAPH_NODES)
        )
    )
    if tuple(item.node_id for item in selected) != tuple(item.node_id for item in nodes):
        raise ContextContractError("Snapshot selected entries must match ordered nodes.")
    for node, decision in zip(nodes, selected, strict=True):
        expected_cost = len(canonical_json_bytes(node.content_dict()))
        if decision.cost_bytes != expected_cost:
            raise ContextContractError(
                "Snapshot selected cost does not match canonical node content."
            )
        if (
            decision.authority_rank != AUTHORITY_RANK[node.authority]
            or decision.sensitivity_rank != SENSITIVITY_RANK[node.sensitivity]
        ):
            raise ContextContractError(
                "Snapshot selected rank does not match node authority or sensitivity."
            )
    excluded = tuple(
        _parse_exclusion(item, f"content.excluded[{index}]")
        for index, item in enumerate(
            array_value(value.get("excluded"), "content.excluded", maximum=MAX_GRAPH_NODES)
        )
    )
    _ascending_unique(
        tuple(item.node_id for item in excluded),
        "content.excluded",
    )
    if node_ids & {item.node_id for item in excluded}:
        raise ContextContractError("Snapshot nodes and exclusions must be disjoint.")
    sensitivity = enum_value(
        Sensitivity,
        value.get("sensitivity"),
        "content.sensitivity",
    )
    _reject_prohibited(sensitivity, "content.sensitivity")
    _require_derived_sensitivity(
        sensitivity,
        tuple(item.sensitivity for item in nodes),
        "content.sensitivity",
    )
    context_bytes = integer_value(
        value.get("context_bytes"),
        "content.context_bytes",
        minimum=0,
        maximum=8_388_608,
    )
    budget_bytes = integer_value(
        value.get("budget_bytes"),
        "content.budget_bytes",
        minimum=1024,
        maximum=8_388_608,
    )
    if context_bytes > budget_bytes:
        raise ContextContractError("content.context_bytes exceeds its budget.")
    node_bytes = sum(len(canonical_json_bytes(item.content_dict())) for item in nodes)
    edge_bytes = sum(len(canonical_json_bytes(item.content_dict())) for item in edges)
    if context_bytes != node_bytes + edge_bytes:
        raise ContextContractError("content.context_bytes does not match selected costs.")
    contradiction_ids = _sorted_id_tuple(
        value.get("unresolved_contradiction_ids"),
        "content.unresolved_contradiction_ids",
        prefix="CTX-EDGE-",
        maximum=MAX_GRAPH_EDGES,
    )
    expected_contradictions = tuple(
        edge.edge_id for edge in edges if edge.edge_type is EdgeType.CONTRADICTS
    )
    if contradiction_ids != expected_contradictions:
        raise ContextContractError(
            "Snapshot unresolved contradictions must match contradiction edges."
        )
    return ContextSnapshot(
        candidate=candidate,
        graph_id=context_id(
            value.get("graph_id"),
            "content.graph_id",
            prefix="CTX-GRAPH-",
        ),
        query_id=context_id(
            value.get("query_id"),
            "content.query_id",
            prefix="CTX-QUERY-",
        ),
        selection_id=context_id(
            value.get("selection_id"),
            "content.selection_id",
            prefix="CTX-SELECTION-",
        ),
        as_of=_utc_timestamp(value.get("as_of"), "content.as_of"),
        sensitivity=sensitivity,
        nodes=nodes,
        edges=edges,
        selected=selected,
        excluded=excluded,
        unresolved_contradiction_ids=contradiction_ids,
        context_bytes=context_bytes,
        budget_bytes=budget_bytes,
    )


def _parse_compaction(value: dict[str, object]) -> ContextCompaction:
    only_keys(
        value,
        {
            "candidate",
            "snapshot_id",
            "sensitivity",
            "budget_bytes",
            "used_bytes",
            "extracts",
            "omitted_node_ids",
            "unresolved_contradiction_ids",
            "host_summary_proposal_id",
        },
        "content",
    )
    extracts = tuple(
        _parse_extract(item, f"content.extracts[{index}]")
        for index, item in enumerate(
            array_value(value.get("extracts"), "content.extracts", maximum=MAX_GRAPH_NODES)
        )
    )
    if not extracts:
        raise ContextContractError("content.extracts must not be empty.")
    if not any(item.required for item in extracts):
        raise ContextContractError(
            "content.extracts must preserve required context."
        )
    _ascending_unique(tuple(item.node_id for item in extracts), "content.extracts")
    contradiction_ids = _sorted_id_tuple(
        value.get("unresolved_contradiction_ids"),
        "content.unresolved_contradiction_ids",
        prefix="CTX-EDGE-",
        maximum=MAX_GRAPH_EDGES,
    )
    contradiction_counts: dict[str, int] = {}
    for extract in extracts:
        for edge_id in extract.contradiction_ids:
            contradiction_counts[edge_id] = contradiction_counts.get(edge_id, 0) + 1
    if tuple(sorted(contradiction_counts)) != contradiction_ids or any(
        count != 2 for count in contradiction_counts.values()
    ):
        raise ContextContractError(
            "Compaction contradiction markers are inconsistent."
        )
    used = integer_value(
        value.get("used_bytes"),
        "content.used_bytes",
        minimum=0,
        maximum=8_388_608,
    )
    budget = integer_value(
        value.get("budget_bytes"),
        "content.budget_bytes",
        minimum=1024,
        maximum=8_388_608,
    )
    if used > budget or used != sum(item.cost_bytes for item in extracts):
        raise ContextContractError("Compaction byte use is inconsistent.")
    raw_proposal = value.get("host_summary_proposal_id")
    proposal_id = (
        None
        if raw_proposal is None
        else context_id(
            raw_proposal,
            "content.host_summary_proposal_id",
            prefix="CTX-HOST-SUMMARY-PROPOSAL-",
        )
    )
    sensitivity = enum_value(
        Sensitivity,
        value.get("sensitivity"),
        "content.sensitivity",
    )
    _reject_prohibited(sensitivity, "content.sensitivity")
    if any(
        SENSITIVITY_RANK[extract.sensitivity] > SENSITIVITY_RANK[sensitivity]
        for extract in extracts
    ):
        raise ContextContractError("Compaction sensitivity understates an extract.")
    omitted_node_ids = _sorted_id_tuple(
        value.get("omitted_node_ids"),
        "content.omitted_node_ids",
        prefix="CTX-NODE-",
    )
    if {item.node_id for item in extracts} & set(omitted_node_ids):
        raise ContextContractError("Compaction extracts and omissions overlap.")
    return ContextCompaction(
        candidate=parse_candidate_identity(value.get("candidate"), "content.candidate"),
        snapshot_id=context_id(
            value.get("snapshot_id"),
            "content.snapshot_id",
            prefix="CTX-SNAPSHOT-",
        ),
        sensitivity=sensitivity,
        budget_bytes=budget,
        used_bytes=used,
        extracts=extracts,
        omitted_node_ids=omitted_node_ids,
        unresolved_contradiction_ids=contradiction_ids,
        host_summary_proposal_id=proposal_id,
    )


def _parse_host_summary(value: dict[str, object]) -> HostSummaryProposal:
    only_keys(
        value,
        {"snapshot_id", "authority", "sensitivity", "claims"},
        "content",
    )
    authority = enum_value(
        AuthorityClass,
        value.get("authority"),
        "content.authority",
    )
    if authority is not AuthorityClass.UNTRUSTED_PROPOSAL:
        raise ContextContractError("Host summary authority must be untrusted-proposal.")
    sensitivity = enum_value(
        Sensitivity,
        value.get("sensitivity"),
        "content.sensitivity",
    )
    _reject_prohibited(sensitivity, "content.sensitivity")
    claims = tuple(
        _parse_linked_claim(item, f"content.claims[{index}]")
        for index, item in enumerate(
            array_value(value.get("claims"), "content.claims", maximum=256)
        )
    )
    if not claims:
        raise ContextContractError("content.claims must not be empty.")
    return HostSummaryProposal(
        snapshot_id=context_id(
            value.get("snapshot_id"),
            "content.snapshot_id",
            prefix="CTX-SNAPSHOT-",
        ),
        authority=authority,
        sensitivity=sensitivity,
        claims=claims,
    )


def _parse_quality(value: dict[str, object]) -> ContextQualityReport:
    fields = {
        "candidate",
        "snapshot_id",
        "sensitivity",
        "required_reference_recall",
        "stale_required_count",
        "provenance_complete_count",
        "provenance_missing_count",
        "sensitivity_violation_count",
        "selected_context_bytes",
        "budget_bytes",
        "redundant_bytes",
        "selected_node_count",
        "excluded_node_count",
        "unresolved_contradiction_count",
        "traversal_truncated",
    }
    only_keys(value, fields, "content")
    count_fields = fields - {
        "candidate",
        "snapshot_id",
        "sensitivity",
        "required_reference_recall",
        "traversal_truncated",
    }
    counts = {
        field: integer_value(
            value.get(field),
            f"content.{field}",
            minimum=0,
            maximum=16_777_216,
        )
        for field in count_fields
    }
    recall = integer_value(
        value.get("required_reference_recall"),
        "content.required_reference_recall",
        minimum=0,
        maximum=100,
    )
    sensitivity = enum_value(
        Sensitivity,
        value.get("sensitivity"),
        "content.sensitivity",
    )
    _reject_prohibited(sensitivity, "content.sensitivity")
    return ContextQualityReport(
        candidate=parse_candidate_identity(value.get("candidate"), "content.candidate"),
        snapshot_id=context_id(
            value.get("snapshot_id"),
            "content.snapshot_id",
            prefix="CTX-SNAPSHOT-",
        ),
        sensitivity=sensitivity,
        required_reference_recall=recall,
        stale_required_count=counts["stale_required_count"],
        provenance_complete_count=counts["provenance_complete_count"],
        provenance_missing_count=counts["provenance_missing_count"],
        sensitivity_violation_count=counts["sensitivity_violation_count"],
        selected_context_bytes=counts["selected_context_bytes"],
        budget_bytes=counts["budget_bytes"],
        redundant_bytes=counts["redundant_bytes"],
        selected_node_count=counts["selected_node_count"],
        excluded_node_count=counts["excluded_node_count"],
        unresolved_contradiction_count=counts[
            "unresolved_contradiction_count"
        ],
        traversal_truncated=boolean_value(
            value.get("traversal_truncated"),
            "content.traversal_truncated",
        ),
    )


def _parse_locator(value: object, where: str) -> SourceLocator:
    item = object_value(value, where)
    only_keys(
        item,
        {"root_scope", "path", "sha256", "line_start", "line_end"},
        where,
    )
    start = integer_value(
        item.get("line_start"),
        f"{where}.line_start",
        minimum=1,
        maximum=1_000_000,
    )
    end = integer_value(
        item.get("line_end"),
        f"{where}.line_end",
        minimum=1,
        maximum=1_000_000,
    )
    if end < start:
        raise ContextContractError(f"{where}.line_end precedes line_start.")
    return SourceLocator(
        root_scope=enum_value(
            RootScope,
            item.get("root_scope"),
            f"{where}.root_scope",
        ),
        path=safe_relative_path(item.get("path"), f"{where}.path"),
        sha256=sha256(item.get("sha256"), f"{where}.sha256"),
        line_start=start,
        line_end=end,
    )


def _parse_provenance(value: object, where: str) -> ContextProvenance:
    item = object_value(value, where)
    only_keys(item, {"producer", "recorded_by", "references"}, where)
    references = tuple(
        parse_artifact_reference(reference, f"{where}.references[{index}]")
        for index, reference in enumerate(
            array_value(item.get("references"), f"{where}.references", maximum=64)
        )
    )
    if not references:
        raise ContextContractError(f"{where}.references must not be empty.")
    if tuple((ref.path, ref.sha256) for ref in references) != tuple(
        sorted((ref.path, ref.sha256) for ref in references)
    ):
        raise ContextContractError(f"{where}.references must be ascending.")
    if len({(ref.path, ref.sha256) for ref in references}) != len(references):
        raise ContextContractError(f"{where}.references must be unique.")
    return ContextProvenance(
        producer=_context_text(
            item.get("producer"),
            f"{where}.producer",
            maximum=100,
        ),
        recorded_by=_context_text(
            item.get("recorded_by"),
            f"{where}.recorded_by",
            maximum=100,
        ),
        references=references,
    )


def _parse_freshness(value: object, where: str) -> Freshness:
    item = object_value(value, where)
    only_keys(item, {"kind", "observed_at", "valid_until"}, where)
    kind = enum_value(FreshnessKind, item.get("kind"), f"{where}.kind")
    observed = (
        None
        if item.get("observed_at") is None
        else _utc_timestamp(item.get("observed_at"), f"{where}.observed_at")
    )
    valid = (
        None
        if item.get("valid_until") is None
        else _utc_timestamp(item.get("valid_until"), f"{where}.valid_until")
    )
    if kind is FreshnessKind.EXPIRES_AT:
        if observed is None or valid is None:
            raise ContextContractError(
                f"{where} requires observed_at and valid_until."
            )
        if _parse_utc(observed) > _parse_utc(valid):
            raise ContextContractError(f"{where} has an inverted validity window.")
    elif observed is not None or valid is not None:
        raise ContextContractError(
            f"{where} timestamps are allowed only for expires-at."
        )
    return Freshness(kind=kind, observed_at=observed, valid_until=valid)


def _parse_budget(value: object, where: str) -> ContextBudget:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "unit",
            "budget_bytes",
            "max_nodes",
            "max_edges",
            "max_traversal_depth",
        },
        where,
    )
    if item.get("unit") != "canonical_utf8_bytes":
        raise ContextContractError(f"{where}.unit is unsupported.")
    return ContextBudget(
        budget_bytes=integer_value(
            item.get("budget_bytes"),
            f"{where}.budget_bytes",
            minimum=1024,
            maximum=8_388_608,
        ),
        max_nodes=integer_value(
            item.get("max_nodes"),
            f"{where}.max_nodes",
            minimum=1,
            maximum=4096,
        ),
        max_edges=integer_value(
            item.get("max_edges"),
            f"{where}.max_edges",
            minimum=0,
            maximum=16384,
        ),
        max_traversal_depth=integer_value(
            item.get("max_traversal_depth"),
            f"{where}.max_traversal_depth",
            minimum=0,
            maximum=8,
        ),
    )


def _parse_selection_decision(value: object, where: str) -> SelectionDecision:
    item = object_value(value, where)
    only_keys(item, {"node_id", "reasons", "rank", "cost_bytes"}, where)
    node = context_id(
        item.get("node_id"),
        f"{where}.node_id",
        prefix="CTX-NODE-",
    )
    reasons = _sorted_text_tuple(
        item.get("reasons"),
        f"{where}.reasons",
        minimum=1,
        maximum=16,
    )
    rank = object_value(item.get("rank"), f"{where}.rank")
    only_keys(
        rank,
        {
            "phase",
            "authority_rank",
            "graph_distance",
            "lexical_score",
            "sensitivity_rank",
            "node_id",
        },
        f"{where}.rank",
    )
    if rank.get("node_id") != node:
        raise ContextContractError(f"{where}.rank.node_id must match node_id.")
    return SelectionDecision(
        node_id=node,
        reasons=reasons,
        phase=integer_value(
            rank.get("phase"),
            f"{where}.rank.phase",
            minimum=0,
            maximum=3,
        ),
        authority_rank=integer_value(
            rank.get("authority_rank"),
            f"{where}.rank.authority_rank",
            minimum=0,
            maximum=len(AuthorityClass) - 1,
        ),
        graph_distance=integer_value(
            rank.get("graph_distance"),
            f"{where}.rank.graph_distance",
            minimum=0,
            maximum=8,
        ),
        lexical_score=integer_value(
            rank.get("lexical_score"),
            f"{where}.rank.lexical_score",
            minimum=0,
            maximum=1_000_000,
        ),
        sensitivity_rank=integer_value(
            rank.get("sensitivity_rank"),
            f"{where}.rank.sensitivity_rank",
            minimum=0,
            maximum=len(Sensitivity) - 1,
        ),
        cost_bytes=integer_value(
            item.get("cost_bytes"),
            f"{where}.cost_bytes",
            minimum=1,
            maximum=8_388_608,
        ),
    )


def _parse_exclusion(value: object, where: str) -> ExclusionDecision:
    item = object_value(value, where)
    only_keys(item, {"node_id", "reason", "details"}, where)
    return ExclusionDecision(
        node_id=context_id(
            item.get("node_id"),
            f"{where}.node_id",
            prefix="CTX-NODE-",
        ),
        reason=_context_text(item.get("reason"), f"{where}.reason", maximum=100),
        details=_sorted_text_tuple(
            item.get("details"),
            f"{where}.details",
            maximum=16,
        ),
    )


def _parse_extract(value: object, where: str) -> ContextExtract:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "node_id",
            "source_id",
            "text",
            "text_sha256",
            "authority",
            "sensitivity",
            "required",
            "contradiction_ids",
            "cost_bytes",
        },
        where,
    )
    text = _context_text(
        item.get("text"),
        f"{where}.text",
        maximum=MAX_SOURCE_BYTES,
        allow_empty=True,
    )
    digest = sha256(item.get("text_sha256"), f"{where}.text_sha256")
    if hashlib.sha256(text.encode("utf-8")).hexdigest().upper() != digest:
        raise ContextContractError(f"{where}.text_sha256 does not match text.")
    cost_bytes = integer_value(
        item.get("cost_bytes"),
        f"{where}.cost_bytes",
        minimum=1,
        maximum=8_388_608,
    )
    if cost_bytes != len(canonical_json_bytes(text)):
        raise ContextContractError(f"{where}.cost_bytes does not match text.")
    extract_sensitivity = enum_value(
        Sensitivity,
        item.get("sensitivity"),
        f"{where}.sensitivity",
    )
    _reject_prohibited(extract_sensitivity, f"{where}.sensitivity")
    return ContextExtract(
        node_id=context_id(
            item.get("node_id"),
            f"{where}.node_id",
            prefix="CTX-NODE-",
        ),
        source_id=context_id(
            item.get("source_id"),
            f"{where}.source_id",
            prefix="CTX-SOURCE-",
        ),
        text=text,
        text_sha256=digest,
        authority=enum_value(
            AuthorityClass,
            item.get("authority"),
            f"{where}.authority",
        ),
        sensitivity=extract_sensitivity,
        required=boolean_value(item.get("required"), f"{where}.required"),
        contradiction_ids=_sorted_id_tuple(
            item.get("contradiction_ids"),
            f"{where}.contradiction_ids",
            prefix="CTX-EDGE-",
            maximum=MAX_GRAPH_EDGES,
        ),
        cost_bytes=cost_bytes,
    )


def _parse_linked_claim(value: object, where: str) -> SourceLinkedClaim:
    item = object_value(value, where)
    only_keys(item, {"claim", "source_node_ids", "extract_sha256s"}, where)
    node_ids = _sorted_id_tuple(
        item.get("source_node_ids"),
        f"{where}.source_node_ids",
        prefix="CTX-NODE-",
    )
    digests_raw = array_value(
        item.get("extract_sha256s"),
        f"{where}.extract_sha256s",
        maximum=64,
    )
    digests = tuple(
        sha256(value, f"{where}.extract_sha256s[{index}]")
        for index, value in enumerate(digests_raw)
    )
    _ascending_unique(digests, f"{where}.extract_sha256s")
    if not node_ids or not digests or len(node_ids) != len(digests):
        raise ContextContractError(f"{where} must link every claim to exact extracts.")
    return SourceLinkedClaim(
        claim=_context_text(item.get("claim"), f"{where}.claim", maximum=4000),
        source_node_ids=node_ids,
        extract_sha256s=digests,
    )


def _context_text(
    value: object,
    where: str,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ContextContractError(f"{where} must be text.")
    if len(value) > maximum:
        raise ContextContractError(f"{where} exceeds the text limit.")
    if maximum == MAX_SOURCE_BYTES and (
        len(value) > MAX_SOURCE_CHARACTERS
        or len(value.encode("utf-8")) > MAX_SOURCE_BYTES
    ):
        raise ContextContractError(f"{where} exceeds the source text limit.")
    if "\x00" in value or any(
        0xD800 <= ord(character) <= 0xDFFF for character in value
    ):
        raise ContextContractError(f"{where} contains unsupported text.")
    if any(pattern.search(value) for pattern in _SECRET):
        raise ContextContractError(f"{where} contains secret-shaped content.")
    return value


def _sorted_text_tuple(
    value: object,
    where: str,
    *,
    minimum: int = 0,
    maximum: int,
) -> tuple[str, ...]:
    raw = array_value(value, where, maximum=maximum)
    result = tuple(
        _context_text(item, f"{where}[{index}]", maximum=500)
        for index, item in enumerate(raw)
    )
    if len(result) < minimum:
        raise ContextContractError(f"{where} has too few items.")
    _ascending_unique(result, where)
    return result


def _sorted_id_tuple(
    value: object,
    where: str,
    *,
    prefix: str,
    maximum: int = MAX_GRAPH_NODES,
) -> tuple[str, ...]:
    result = tuple(
        context_id(item, f"{where}[{index}]", prefix=prefix)
        for index, item in enumerate(array_value(value, where, maximum=maximum))
    )
    _ascending_unique(result, where)
    return result


def _ascending_unique(values: tuple[Any, ...], where: str) -> None:
    if values != tuple(sorted(values)):
        raise ContextContractError(f"{where} must be ascending.")
    if len(values) != len(set(values)):
        raise ContextContractError(f"{where} must be unique.")


def _utc_timestamp(value: object, where: str) -> str:
    text = string_value(value, where, maximum=40)
    if not _RFC3339_UTC.fullmatch(text):
        raise ContextContractError(f"{where} must be RFC 3339 UTC.")
    _parse_utc(text)
    return text


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContextContractError("Timestamp is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ContextContractError("Timestamp must be UTC.")
    return parsed


def _reject_prohibited(value: Sensitivity, where: str) -> None:
    if value is Sensitivity.SECRET_OR_PROHIBITED:
        raise ContextContractError(f"{where} cannot adopt secret-or-prohibited data.")


def _require_derived_sensitivity(
    declared: Sensitivity,
    sources: tuple[Sensitivity, ...],
    where: str,
) -> None:
    if not sources:
        return
    required = max(sources, key=SENSITIVITY_RANK.__getitem__)
    if declared is not required:
        raise ContextContractError(f"{where} must equal highest source sensitivity.")
