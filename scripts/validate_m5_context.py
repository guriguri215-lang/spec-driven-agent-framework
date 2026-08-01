"""Run the named offline M5-CONTEXT-INTEGRITY validator."""

# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from tests.m5_context_helpers import PinnedContextCandidateVerifier
from tests.schema_validation import LocalSchemaValidator, SchemaValidationError

from sdaqf.adapters.context import (
    CanonicalUTF8ByteEstimator,
    LocalContextSourceReader,
)
from sdaqf.application.context_compaction import (
    ContextCompactionError,
    ContextCompactor,
)
from sdaqf.application.context_contracts import (
    ContextContractError,
    LoadedContextArtifact,
    artifact_from_value,
    canonical_json_bytes,
    edge_identity,
    load_context_artifact,
    node_identity,
    parse_context_artifact_bytes,
    serialize_context_artifact,
    source_identity,
)
from sdaqf.application.context_index import ContextIndexer
from sdaqf.application.context_quality import measure_context_quality
from sdaqf.application.context_selection import (
    ContextSelectionError,
    ContextSelector,
    ContextSnapshotService,
)
from sdaqf.domain.context import (
    AuthorityClass,
    ContextArtifactType,
    ContextCompaction,
    ContextEdge,
    ContextGraph,
    ContextManifest,
    ContextQualityReport,
    ContextQuery,
    ContextSelection,
    ContextSnapshot,
    EdgeType,
    Freshness,
    FreshnessKind,
    HostSummaryProposal,
    Sensitivity,
)
from sdaqf.domain.quality import CandidateIdentity
from sdaqf.ports.context import ContextSourceError

_FILES = {
    ContextArtifactType.MANIFEST: "context-manifest.json",
    ContextArtifactType.GRAPH: "context-graph.json",
    ContextArtifactType.QUERY: "context-query.json",
    ContextArtifactType.SELECTION: "context-selection.json",
    ContextArtifactType.SNAPSHOT: "context-snapshot.json",
    ContextArtifactType.COMPACTION: "context-compaction.json",
    ContextArtifactType.HOST_SUMMARY_PROPOSAL: (
        "context-host-summary-proposal.json"
    ),
    ContextArtifactType.QUALITY_REPORT: "context-quality-report.json",
}
_SCHEMAS = {
    artifact_type: filename.replace(".json", ".schema.json")
    for artifact_type, filename in _FILES.items()
}


def main() -> int:
    """Validate public artifacts, identities, behavior, and named measures."""

    root = Path.cwd().resolve(strict=True)
    examples = root / "examples" / "m5-context"
    validator = LocalSchemaValidator(root / "schemas")
    artifacts: dict[ContextArtifactType, LoadedContextArtifact] = {}
    for artifact_type, filename in _FILES.items():
        path = examples / filename
        artifact = load_context_artifact(path, expected_type=artifact_type)
        validator.validate(_SCHEMAS[artifact_type], artifact.to_dict())
        artifacts[artifact_type] = artifact

    manifest = artifacts[ContextArtifactType.MANIFEST].value
    if not isinstance(manifest, ContextManifest):
        raise RuntimeError("Public Context Manifest has an invalid value.")
    reader = LocalContextSourceReader()
    pinned_candidate = PinnedContextCandidateVerifier(manifest.candidate)
    indexed = ContextIndexer(reader, pinned_candidate).build(
        artifacts[ContextArtifactType.MANIFEST],
        repository_root=root,
    )
    if indexed != artifacts[ContextArtifactType.GRAPH]:
        raise RuntimeError("Public Context Graph is not reproducible.")

    selector = ContextSelector(CanonicalUTF8ByteEstimator())
    selected_first = selector.select(
        artifacts[ContextArtifactType.GRAPH],
        artifacts[ContextArtifactType.QUERY],
    )
    selected_second = selector.select(
        artifacts[ContextArtifactType.GRAPH],
        artifacts[ContextArtifactType.QUERY],
    )
    if selected_first != selected_second:
        raise RuntimeError("Context Selection is not deterministic.")
    if selected_first != artifacts[ContextArtifactType.SELECTION]:
        raise RuntimeError("Public Context Selection is not reproducible.")

    snapshot = ContextSnapshotService(
        reader,
        pinned_candidate,
        CanonicalUTF8ByteEstimator(),
    ).build(
        artifacts[ContextArtifactType.GRAPH],
        artifacts[ContextArtifactType.SELECTION],
        repository_root=root,
    )
    if snapshot != artifacts[ContextArtifactType.SNAPSHOT]:
        raise RuntimeError("Public Context Snapshot is not reproducible.")

    compactor = ContextCompactor(
        reader,
        pinned_candidate,
        CanonicalUTF8ByteEstimator(),
    )
    compaction = compactor.compact(
        artifacts[ContextArtifactType.SNAPSHOT],
        repository_root=root,
        host_summary_artifact=artifacts[
            ContextArtifactType.HOST_SUMMARY_PROPOSAL
        ],
    )
    if compaction != artifacts[ContextArtifactType.COMPACTION]:
        raise RuntimeError("Public Context Compaction is not reproducible.")

    quality = measure_context_quality(
        artifacts[ContextArtifactType.GRAPH],
        artifacts[ContextArtifactType.SELECTION],
        artifacts[ContextArtifactType.SNAPSHOT],
    )
    if quality != artifacts[ContextArtifactType.QUALITY_REPORT]:
        raise RuntimeError("Public Context quality report is not reproducible.")
    if _contains_aggregate(quality.to_dict()):
        raise RuntimeError("Context quality must not contain an aggregate score.")

    suite = _load_object(root / "evals" / "context-suite.json")
    result = _load_object(root / "evals" / "results" / "m5-context-evaluation.json")
    if suite.get("suite_id") != result.get("suite_id"):
        raise RuntimeError("Context evaluation identities do not match.")
    expected = {
        item["case_id"]: item["expected"]
        for item in _object_array(suite.get("cases"), "suite cases")
    }
    recorded = {
        item["case_id"]: item["observed"]
        for item in _object_array(result.get("cases"), "result cases")
        if item.get("passed") is True
    }
    observed = _execute_scenarios(artifacts, selector, compactor, root)
    if expected != observed or recorded != observed or len(expected) != 7:
        raise RuntimeError("Context evaluation cases are incomplete.")
    reference = result.get("quality_report")
    if not isinstance(reference, dict):
        raise RuntimeError("Context evaluation quality reference is invalid.")
    quality_path = reference.get("path")
    if quality_path != "examples/m5-context/context-quality-report.json":
        raise RuntimeError("Context evaluation quality path is invalid.")
    quality_digest = hashlib.sha256(
        (root / quality_path).read_bytes()
    ).hexdigest().upper()
    if reference.get("sha256") != quality_digest:
        raise RuntimeError("Context evaluation quality digest does not match.")
    if _contains_aggregate(suite) or _contains_aggregate(result):
        raise RuntimeError("Context evaluation must not contain an aggregate score.")

    _validate_remediation_regressions(
        artifacts,
        selector,
        compactor,
        reader,
        pinned_candidate,
        root,
    )

    print(
        "PASS: M5-CONTEXT-INTEGRITY validated 8 artifacts, 7 scenarios, "
        "deterministic selection, exact snapshot, and extractive compaction."
    )
    return 0


def _validate_remediation_regressions(
    artifacts: dict[ContextArtifactType, LoadedContextArtifact],
    selector: ContextSelector,
    compactor: ContextCompactor,
    reader: LocalContextSourceReader,
    pinned_candidate: PinnedContextCandidateVerifier,
    root: Path,
) -> None:
    """Execute the independent-review trust-boundary regressions."""

    graph = artifacts[ContextArtifactType.GRAPH].value
    query = artifacts[ContextArtifactType.QUERY].value
    snapshot = artifacts[ContextArtifactType.SNAPSHOT].value
    proposal = artifacts[ContextArtifactType.HOST_SUMMARY_PROPOSAL].value
    if (
        not isinstance(graph, ContextGraph)
        or not isinstance(query, ContextQuery)
        or not isinstance(snapshot, ContextSnapshot)
        or not isinstance(proposal, HostSummaryProposal)
    ):
        raise RuntimeError("Context remediation inputs are invalid.")

    accepted = next(
        node
        for node in graph.nodes
        if node.authority is AuthorityClass.ACCEPTED_PUBLIC_CONTRACT
    )
    missing_path = "examples/m5-context/sources/nonexistent-contract.json"
    missing_text = '{"decision":"fabricated"}\n'
    missing_digest = hashlib.sha256(missing_text.encode()).hexdigest().upper()
    fabricated = replace(
        accepted,
        text=missing_text,
        text_sha256=missing_digest,
        locator=replace(
            accepted.locator,
            path=missing_path,
            sha256=missing_digest,
            line_start=1,
            line_end=1,
        ),
        provenance=replace(
            accepted.provenance,
            references=(
                replace(
                    accepted.provenance.references[0],
                    path=missing_path,
                    sha256=missing_digest,
                ),
            ),
        ),
        freshness=Freshness(FreshnessKind.IMMUTABLE),
    )
    fabricated = replace(
        fabricated,
        source_id=source_identity(fabricated.source_content_dict()),
    )
    fabricated = replace(
        fabricated,
        node_id=node_identity(fabricated.content_dict()),
    )
    fabricated_graph = replace(
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
    fabricated_graph_artifact = artifact_from_value(
        ContextArtifactType.GRAPH,
        fabricated_graph,
    )
    fabricated_query_artifact = artifact_from_value(
        ContextArtifactType.QUERY,
        replace(
            query,
            graph_id=fabricated_graph_artifact.artifact_id,
            identifiers=fabricated.identifiers,
            terms=(),
        ),
    )
    fabricated_selection = selector.select(
        fabricated_graph_artifact,
        fabricated_query_artifact,
    )
    observed_snapshot = ContextSnapshotService(
        reader,
        pinned_candidate,
        CanonicalUTF8ByteEstimator(),
    ).build(
        fabricated_graph_artifact,
        fabricated_selection,
        repository_root=root,
    ).value
    if (
        not isinstance(observed_snapshot, ContextSnapshot)
        or fabricated.node_id in {node.node_id for node in observed_snapshot.nodes}
        or not any(
            item.node_id == fabricated.node_id
            and item.reason == "missing-or-unreadable"
            for item in observed_snapshot.excluded
        )
    ):
        raise RuntimeError("Immutable source re-observation regression failed.")

    optional = next(node for node in snapshot.nodes if not node.required)
    optional_decision = next(
        item for item in snapshot.selected if item.node_id == optional.node_id
    )
    missing_canonical = replace(
        snapshot,
        nodes=(optional,),
        edges=(),
        selected=(optional_decision,),
        unresolved_contradiction_ids=(),
        context_bytes=optional_decision.cost_bytes,
    )
    try:
        parse_context_artifact_bytes(
            serialize_context_artifact(
                artifact_from_value(
                    ContextArtifactType.SNAPSHOT,
                    missing_canonical,
                )
            )
        )
    except ContextContractError:
        pass
    else:
        raise RuntimeError("Snapshot canonical-node regression failed.")

    understated = replace(
        snapshot,
        selected=(
            replace(snapshot.selected[0], cost_bytes=1),
            *snapshot.selected[1:],
        ),
        context_bytes=1,
        edges=(),
    )
    try:
        parse_context_artifact_bytes(
            serialize_context_artifact(
                artifact_from_value(ContextArtifactType.SNAPSHOT, understated)
            )
        )
    except ContextContractError:
        pass
    else:
        raise RuntimeError("Snapshot cost recomputation regression failed.")

    canonical = next(node for node in snapshot.nodes if node.required)
    forged_text = "fabricated canonical context\n"
    forged = replace(
        canonical,
        text=forged_text,
        text_sha256=hashlib.sha256(forged_text.encode()).hexdigest().upper(),
    )
    forged = replace(forged, node_id=node_identity(forged.content_dict()))
    canonical_decision = next(
        item for item in snapshot.selected if item.node_id == canonical.node_id
    )
    forged_decision = replace(
        canonical_decision,
        node_id=forged.node_id,
        cost_bytes=len(canonical_json_bytes(forged.content_dict())),
    )
    forged_nodes = tuple(
        sorted(
            (
                forged,
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
    decisions[forged.node_id] = forged_decision
    forged_snapshot = replace(
        snapshot,
        nodes=forged_nodes,
        edges=(),
        selected=tuple(decisions[node.node_id] for node in forged_nodes),
        unresolved_contradiction_ids=(),
        context_bytes=sum(
            len(canonical_json_bytes(node.content_dict())) for node in forged_nodes
        ),
    )
    forged_artifact = parse_context_artifact_bytes(
        serialize_context_artifact(
            artifact_from_value(ContextArtifactType.SNAPSHOT, forged_snapshot)
        ),
        expected_type=ContextArtifactType.SNAPSHOT,
    )
    try:
        compactor.compact(forged_artifact, repository_root=root)
    except ContextCompactionError:
        pass
    else:
        raise RuntimeError("Persisted Snapshot authentication regression failed.")

    forged_source = replace(canonical, source_id="CTX-SOURCE-" + "0" * 64)
    forged_source = replace(
        forged_source,
        node_id=node_identity(forged_source.content_dict()),
    )
    forged_source_snapshot = replace(
        snapshot,
        nodes=tuple(
            sorted(
                (
                    forged_source,
                    *(
                        node
                        for node in snapshot.nodes
                        if node.node_id != canonical.node_id
                    ),
                ),
                key=lambda node: node.node_id,
            )
        ),
        edges=(),
    )
    try:
        parse_context_artifact_bytes(
            serialize_context_artifact(
                artifact_from_value(
                    ContextArtifactType.SNAPSHOT,
                    forged_source_snapshot,
                )
            )
        )
    except ContextContractError:
        pass
    else:
        raise RuntimeError("Snapshot source identity regression failed.")
    try:
        compactor.compact(
            artifact_from_value(
                ContextArtifactType.SNAPSHOT,
                forged_source_snapshot,
            ),
            repository_root=root,
        )
    except ContextCompactionError:
        pass
    else:
        raise RuntimeError("Compaction source identity regression failed.")

    duplicate_left, duplicate_right = sorted(
        (node for node in snapshot.nodes if not node.required),
        key=lambda node: node.node_id,
    )
    duplicate = replace(
        duplicate_right,
        source_id=duplicate_left.source_id,
        kind=duplicate_left.kind,
        title=duplicate_left.title,
        locator=duplicate_left.locator,
        provenance=duplicate_left.provenance,
        authority=duplicate_left.authority,
        freshness=duplicate_left.freshness,
        sensitivity=duplicate_left.sensitivity,
        identifiers=duplicate_left.identifiers,
        labels=duplicate_left.labels,
        required=duplicate_left.required,
    )
    duplicate = replace(
        duplicate,
        node_id=node_identity(duplicate.content_dict()),
    )
    duplicate_snapshot = replace(
        snapshot,
        nodes=tuple(
            sorted(
                (
                    duplicate,
                    *(
                        node
                        for node in snapshot.nodes
                        if node.node_id != duplicate_right.node_id
                    ),
                ),
                key=lambda node: node.node_id,
            )
        ),
        edges=(),
    )
    try:
        parse_context_artifact_bytes(
            serialize_context_artifact(
                artifact_from_value(
                    ContextArtifactType.SNAPSHOT,
                    duplicate_snapshot,
                )
            )
        )
    except ContextContractError:
        pass
    else:
        raise RuntimeError("Snapshot duplicate source regression failed.")
    try:
        compactor.compact(
            artifact_from_value(
                ContextArtifactType.SNAPSHOT,
                duplicate_snapshot,
            ),
            repository_root=root,
        )
    except ContextCompactionError:
        pass
    else:
        raise RuntimeError("Compaction duplicate source regression failed.")

    optional = next(node for node in snapshot.nodes if not node.required)
    optional_decision = next(
        item for item in snapshot.selected if item.node_id == optional.node_id
    )
    missing_canonical = replace(
        snapshot,
        nodes=(optional,),
        edges=(),
        selected=(optional_decision,),
        excluded=(),
        unresolved_contradiction_ids=(),
        sensitivity=optional.sensitivity,
        context_bytes=len(canonical_json_bytes(optional.content_dict())),
    )
    try:
        compactor.compact(
            artifact_from_value(ContextArtifactType.SNAPSHOT, missing_canonical),
            repository_root=root,
        )
    except ContextCompactionError:
        pass
    else:
        raise RuntimeError("In-memory canonical Snapshot regression failed.")

    false_snapshot_id = replace(
        artifacts[ContextArtifactType.SNAPSHOT],
        artifact_id="CTX-SNAPSHOT-" + "0" * 64,
    )
    try:
        compactor.compact(false_snapshot_id, repository_root=root)
    except ContextCompactionError:
        pass
    else:
        raise RuntimeError("In-memory Snapshot envelope regression failed.")

    laundered_proposal = replace(
        proposal,
        authority=AuthorityClass.OWNER_APPROVED,
    )
    try:
        compactor.compact(
            artifacts[ContextArtifactType.SNAPSHOT],
            repository_root=root,
            host_summary_artifact=artifact_from_value(
                ContextArtifactType.HOST_SUMMARY_PROPOSAL,
                laundered_proposal,
            ),
        )
    except ContextCompactionError:
        pass
    else:
        raise RuntimeError("In-memory host authority regression failed.")

    title_node = next(node for node in graph.nodes if not node.required)

    def title_graph(title: str) -> LoadedContextArtifact:
        changed = replace(title_node, title=title)
        changed = replace(
            changed,
            source_id=source_identity(changed.source_content_dict()),
        )
        changed = replace(changed, node_id=node_identity(changed.content_dict()))
        return artifact_from_value(
            ContextArtifactType.GRAPH,
            replace(
                graph,
                nodes=tuple(
                    sorted(
                        (
                            changed,
                            *(
                                node
                                for node in graph.nodes
                                if node.node_id != title_node.node_id
                            ),
                        ),
                        key=lambda node: node.node_id,
                    )
                ),
                edges=(),
            ),
        )

    schema_validator = LocalSchemaValidator(root / "schemas")
    title_boundary = serialize_context_artifact(title_graph("\U0001f600" * 500))
    parse_context_artifact_bytes(title_boundary)
    schema_validator.validate("context-graph.schema.json", json.loads(title_boundary))
    title_excessive = serialize_context_artifact(title_graph("\U0001f600" * 501))
    runtime_rejected = False
    schema_rejected = False
    try:
        parse_context_artifact_bytes(title_excessive)
    except ContextContractError:
        runtime_rejected = True
    try:
        schema_validator.validate(
            "context-graph.schema.json",
            json.loads(title_excessive),
        )
    except SchemaValidationError:
        schema_rejected = True
    if not runtime_rejected or not schema_rejected:
        raise RuntimeError("Ordinary Unicode text bound regression failed.")

    optional_nodes = sorted(
        (node for node in snapshot.nodes if not node.required),
        key=lambda node: node.node_id,
    )
    left, right = optional_nodes
    contradiction = ContextEdge(
        edge_id="",
        edge_type=EdgeType.CONTRADICTS,
        source_node_id=left.node_id,
        target_node_id=right.node_id,
        provenance=left.provenance,
    )
    contradiction = replace(
        contradiction,
        edge_id=edge_identity(contradiction.content_dict()),
    )
    contradiction_snapshot = replace(
        snapshot,
        edges=(contradiction,),
        unresolved_contradiction_ids=(contradiction.edge_id,),
        context_bytes=sum(
            len(canonical_json_bytes(node.content_dict())) for node in snapshot.nodes
        )
        + len(canonical_json_bytes(contradiction.content_dict())),
    )
    contradiction_artifact = parse_context_artifact_bytes(
        serialize_context_artifact(
            artifact_from_value(
                ContextArtifactType.SNAPSHOT,
                contradiction_snapshot,
            )
        ),
        expected_type=ContextArtifactType.SNAPSHOT,
    )
    compacted = compactor.compact(contradiction_artifact, repository_root=root).value
    if not isinstance(compacted, ContextCompaction):
        raise RuntimeError("Contradiction Compaction returned an invalid value.")
    extracts = {item.node_id: item for item in compacted.extracts}
    if (
        compacted.unresolved_contradiction_ids != (contradiction.edge_id,)
        or extracts[left.node_id].contradiction_ids != (contradiction.edge_id,)
        or extracts[right.node_id].contradiction_ids != (contradiction.edge_id,)
        or extracts[left.node_id].source_id != left.source_id
        or extracts[right.node_id].source_id != right.source_id
    ):
        raise RuntimeError("Contradiction Compaction metadata regression failed.")

    _validate_publication_candidate_binding(
        artifacts[ContextArtifactType.SNAPSHOT],
        root,
    )


def _validate_publication_candidate_binding(
    snapshot_artifact: LoadedContextArtifact,
    root: Path,
) -> None:
    """Prove final verification authenticates the artifact being published."""

    caller_artifact = parse_context_artifact_bytes(
        serialize_context_artifact(snapshot_artifact),
        expected_type=ContextArtifactType.SNAPSHOT,
    )
    caller_snapshot = caller_artifact.value
    if not isinstance(caller_snapshot, ContextSnapshot):
        raise RuntimeError("Publication binding Snapshot is invalid.")
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
    try:
        compactor.publish(
            caller_artifact,
            repository_root=root,
            owner_root=None,
            host_summary_artifact=None,
            output=root / ".sdaqf-publication-binding-probe.json",
        )
    except ContextSourceError:
        pass
    else:
        raise RuntimeError("Publication candidate binding failed open.")
    if (
        caller_snapshot.candidate != replacement_candidate
        or verifier.observed[-1] != compacted_candidate
        or publisher.contents
    ):
        raise RuntimeError("Publication candidate binding regression failed.")


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


def _execute_scenarios(
    artifacts: dict[ContextArtifactType, LoadedContextArtifact],
    selector: ContextSelector,
    compactor: ContextCompactor,
    root: Path,
) -> dict[str, str]:
    """Execute the seven public acceptance cases against exact artifacts."""

    graph_artifact = artifacts[ContextArtifactType.GRAPH]
    query_artifact = artifacts[ContextArtifactType.QUERY]
    snapshot_artifact = artifacts[ContextArtifactType.SNAPSHOT]
    quality_artifact = artifacts[ContextArtifactType.QUALITY_REPORT]
    proposal_artifact = artifacts[ContextArtifactType.HOST_SUMMARY_PROPOSAL]
    graph = graph_artifact.value
    query = query_artifact.value
    snapshot = snapshot_artifact.value
    quality = quality_artifact.value
    proposal = proposal_artifact.value
    if (
        not isinstance(graph, ContextGraph)
        or not isinstance(query, ContextQuery)
        or not isinstance(snapshot, ContextSnapshot)
        or not isinstance(quality, ContextQualityReport)
        or not isinstance(proposal, HostSummaryProposal)
    ):
        raise RuntimeError("Public Context scenario inputs are invalid.")

    first = selector.select(graph_artifact, query_artifact)
    second = selector.select(graph_artifact, query_artifact)
    if first != second or not _full_sha256_identity(first.artifact_id):
        raise RuntimeError("Determinism scenario failed.")

    provenance_complete = all(
        any(
            reference.path == node.locator.path
            and reference.sha256 == node.locator.sha256
            for reference in node.provenance.references
        )
        for node in graph.nodes
    )
    if not provenance_complete or quality.provenance_missing_count != 0:
        raise RuntimeError("Provenance scenario failed.")
    if quality.required_reference_recall != 100:
        raise RuntimeError("Required recall scenario failed.")

    budget_query = replace(
        query,
        required_node_ids=tuple(node.node_id for node in graph.nodes),
        seed_node_ids=(),
        identifiers=(),
        terms=(),
        budget=replace(query.budget, budget_bytes=1024),
    )
    try:
        selector.select(
            graph_artifact,
            artifact_from_value(ContextArtifactType.QUERY, budget_query),
        )
    except ContextSelectionError as exc:
        if "byte budget" not in str(exc):
            raise RuntimeError("Budget scenario failed with the wrong reason.") from exc
    else:
        raise RuntimeError("Budget scenario did not fail closed.")

    optional = sorted(
        (node for node in graph.nodes if not node.required),
        key=lambda node: node.node_id,
    )
    if len(optional) < 2:
        raise RuntimeError("Contradiction scenario requires two optional nodes.")
    left, right = optional[:2]
    source_id, target_id = sorted((left.node_id, right.node_id))
    contradiction = ContextEdge(
        edge_id="",
        edge_type=EdgeType.CONTRADICTS,
        source_node_id=source_id,
        target_node_id=target_id,
        provenance=left.provenance,
    )
    contradiction = replace(
        contradiction,
        edge_id=edge_identity(contradiction.content_dict()),
    )
    contradiction_graph = replace(graph, edges=(contradiction,))
    contradiction_graph_artifact = artifact_from_value(
        ContextArtifactType.GRAPH,
        contradiction_graph,
    )
    contradiction_query = replace(
        query,
        graph_id=contradiction_graph_artifact.artifact_id,
        seed_node_ids=(),
        identifiers=left.identifiers,
        terms=(),
        allowed_edge_types=(EdgeType.CONTRADICTS,),
    )
    contradiction_selection = selector.select(
        contradiction_graph_artifact,
        artifact_from_value(ContextArtifactType.QUERY, contradiction_query),
    ).value
    if not isinstance(contradiction_selection, ContextSelection):
        raise RuntimeError("Contradiction scenario returned an invalid Selection.")
    selected_ids = {
        item.node_id for item in contradiction_selection.selected
    }
    if (
        {left.node_id, right.node_id} - selected_ids
        or contradiction_selection.unresolved_contradiction_ids
        != (contradiction.edge_id,)
    ):
        raise RuntimeError("Contradiction closure scenario failed.")

    private_proposal = artifact_from_value(
        ContextArtifactType.HOST_SUMMARY_PROPOSAL,
        replace(proposal, sensitivity=Sensitivity.OWNER_PRIVATE),
    )
    private_compaction = compactor.compact(
        snapshot_artifact,
        repository_root=root,
        host_summary_artifact=private_proposal,
    )
    if (
        not isinstance(private_compaction.value, ContextCompaction)
        or private_compaction.value.sensitivity is not Sensitivity.OWNER_PRIVATE
    ):
        raise RuntimeError("Sensitivity propagation scenario failed.")

    required = next(node for node in graph.nodes if node.required)
    stale = replace(
        required,
        freshness=Freshness(
            FreshnessKind.EXPIRES_AT,
            observed_at="2026-07-29T00:00:00Z",
            valid_until="2026-07-30T00:00:00Z",
        ),
    )
    stale = replace(stale, node_id=node_identity(stale.content_dict()))
    stale_nodes = tuple(
        sorted(
            (stale, *(node for node in graph.nodes if node.node_id != required.node_id)),
            key=lambda node: node.node_id,
        )
    )
    stale_graph = replace(graph, nodes=stale_nodes, edges=())
    stale_graph_artifact = artifact_from_value(
        ContextArtifactType.GRAPH,
        stale_graph,
    )
    stale_query = replace(
        query,
        graph_id=stale_graph_artifact.artifact_id,
        required_node_ids=(stale.node_id,),
        seed_node_ids=(),
        identifiers=(),
        terms=(),
    )
    try:
        selector.select(
            stale_graph_artifact,
            artifact_from_value(ContextArtifactType.QUERY, stale_query),
        )
    except ContextSelectionError as exc:
        if "stale" not in str(exc):
            raise RuntimeError(
                "Stale required scenario failed with the wrong reason."
            ) from exc
    else:
        raise RuntimeError("Stale required scenario did not fail closed.")

    return {
        "M5-CTX-BUDGET": "required-context-over-budget",
        "M5-CTX-CONTRADICTION": "explicit-unresolved-closure",
        "M5-CTX-DETERMINISM": "stable-full-sha256-identities",
        "M5-CTX-PROVENANCE": "complete",
        "M5-CTX-REQUIRED-RECALL": "100",
        "M5-CTX-SENSITIVITY": "automatic-downgrade-rejected",
        "M5-CTX-STALE-REQUIRED": "hard-blocker",
    }


def _full_sha256_identity(value: str) -> bool:
    _, separator, digest = value.rpartition("-")
    return (
        bool(separator)
        and len(digest) == 64
        and all(character in "0123456789ABCDEF" for character in digest)
    )


def _load_object(path: Path) -> dict[str, object]:
    decoded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError(f"{path.name} must be an object.")
    return decoded


def _object_array(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError(f"{label} must be an object array.")
    return [item for item in value if isinstance(item, dict)]


def _contains_aggregate(value: object) -> bool:
    if isinstance(value, dict):
        if any("aggregate" in key.casefold() for key in value):
            return True
        return any(_contains_aggregate(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_aggregate(item) for item in value)
    return False


if __name__ == "__main__":
    raise SystemExit(main())
