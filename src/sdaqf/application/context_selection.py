"""Deterministic bounded Context selection and snapshot construction."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from sdaqf.application.context_contracts import (
    ContextContractError,
    LoadedContextArtifact,
    artifact_from_value,
    parse_context_artifact_bytes,
    serialize_context_artifact,
    validate_context_authority,
    validate_context_json_bytes,
)
from sdaqf.domain.context import (
    AUTHORITY_RANK,
    SENSITIVITY_RANK,
    AuthorityClass,
    ContextArtifactType,
    ContextEdge,
    ContextGraph,
    ContextNode,
    ContextQuery,
    ContextSelection,
    ContextSnapshot,
    ContextSnapshotDelta,
    EdgeType,
    ExclusionDecision,
    FreshnessKind,
    RootScope,
    SelectionDecision,
    Sensitivity,
    SourceKind,
)
from sdaqf.ports.context import (
    BudgetEstimator,
    ContextCandidateVerifier,
    ContextSourceError,
    ContextSourceReader,
    ImmutableJSONPublisher,
)


class ContextSelectionError(ContextContractError):
    """A Context Query cannot produce a truthful bounded Selection."""


class ContextSelector:
    """Select Context nodes with exact retrieval and exclusion reasons."""

    def __init__(self, estimator: BudgetEstimator) -> None:
        self._estimator = estimator

    def select(
        self,
        graph_artifact: LoadedContextArtifact,
        query_artifact: LoadedContextArtifact,
    ) -> LoadedContextArtifact:
        """Return one deterministic validated Selection artifact."""

        if (
            graph_artifact.artifact_type is not ContextArtifactType.GRAPH
            or not isinstance(graph_artifact.value, ContextGraph)
        ):
            raise ContextSelectionError("Context selection requires a Graph.")
        if (
            query_artifact.artifact_type is not ContextArtifactType.QUERY
            or not isinstance(query_artifact.value, ContextQuery)
        ):
            raise ContextSelectionError("Context selection requires a Query.")
        graph = graph_artifact.value
        query = query_artifact.value
        if query.graph_id != graph_artifact.artifact_id:
            raise ContextSelectionError("Query graph identity does not match.")
        if query.candidate != graph.candidate:
            raise ContextSelectionError("Query candidate identity does not match.")

        nodes = {item.node_id: item for item in graph.nodes}
        required = {item.node_id for item in graph.nodes if item.required}
        required.update(query.required_node_ids)
        directly_required = set(required)
        seeds = set(query.seed_node_ids)
        missing = sorted((required | seeds) - nodes.keys())
        if missing:
            raise ContextSelectionError("Query references a missing graph node.")

        exclusions: dict[str, ExclusionDecision] = {}
        eligible: set[str] = set()
        for node in graph.nodes:
            problem = self._eligibility_problem(node, query)
            if problem is None:
                eligible.add(node.node_id)
            elif node.node_id in required:
                raise ContextSelectionError(
                    f"Required context is unavailable: {problem}."
                )
            else:
                exclusions[node.node_id] = ExclusionDecision(
                    node_id=node.node_id,
                    reason=problem,
                    details=(),
                )

        closure = set(required)
        contradiction_edges = [
            edge for edge in graph.edges if edge.edge_type is EdgeType.CONTRADICTS
        ]
        changed = True
        while changed:
            changed = False
            for edge in contradiction_edges:
                endpoints = {edge.source_node_id, edge.target_node_id}
                if closure & endpoints and not endpoints <= closure:
                    other = next(iter(endpoints - closure))
                    if other not in eligible:
                        raise ContextSelectionError(
                            "Required contradiction closure is unavailable."
                        )
                    closure.add(other)
                    changed = True
        required = closure

        distances, _ = self._traverse(
            graph,
            query,
            starts=required | (seeds & eligible),
        )
        phases: dict[str, int] = {node_id: 0 for node_id in required}
        reasons: dict[str, set[str]] = defaultdict(set)
        for node_id in required:
            reasons[node_id].add(
                "required-reference"
                if node_id in directly_required
                else "contradiction-closure"
            )
        for node_id in distances:
            if node_id in eligible and node_id not in required:
                phases[node_id] = 1
                reasons[node_id].add("graph")

        identifier_set = set(query.identifiers)
        for node in graph.nodes:
            if (
                node.node_id in eligible
                and identifier_set.intersection(node.identifiers)
            ):
                phases[node.node_id] = min(phases.get(node.node_id, 2), 2)
                reasons[node.node_id].add("identifier")

        query_tokens: set[str] = set()
        for term in query.terms:
            query_tokens.update(lexical_tokens(term))
        lexical_scores: dict[str, int] = {}
        for node in graph.nodes:
            score = lexical_score(node, query_tokens)
            lexical_scores[node.node_id] = score
            if node.node_id in eligible and score > 0:
                phases[node.node_id] = min(phases.get(node.node_id, 3), 3)
                reasons[node.node_id].add("lexical")

        candidate_ids = set(phases)
        for node_id in sorted(eligible - candidate_ids):
            exclusions[node_id] = ExclusionDecision(
                node_id=node_id,
                reason="not-retrieved",
                details=(),
            )

        if len(required) > query.budget.max_nodes:
            raise ContextSelectionError("Required nodes exceed the node budget.")
        selected_ids = set(required)
        required_edges = self._induced_edges(graph.edges, selected_ids)
        if len(required_edges) > query.budget.max_edges:
            raise ContextSelectionError("Required edges exceed the edge budget.")
        required_cost = sum(
            self._estimator.cost(nodes[node_id].content_dict())
            for node_id in selected_ids
        ) + sum(self._estimator.cost(edge.content_dict()) for edge in required_edges)
        if required_cost > query.budget.budget_bytes:
            raise ContextSelectionError("Required context exceeds the byte budget.")

        ranked_optional = sorted(
            candidate_ids - selected_ids,
            key=lambda node_id: self._rank(
                nodes[node_id],
                phase=phases[node_id],
                distance=distances.get(node_id, query.budget.max_traversal_depth),
                lexical=lexical_scores[node_id],
            ),
        )
        used = required_cost
        selected_edges = required_edges
        for node_id in ranked_optional:
            if node_id in selected_ids:
                continue
            closure_ids = self._contradiction_closure(
                {node_id},
                contradiction_edges,
            )
            added_ids = closure_ids - selected_ids
            if not added_ids <= eligible:
                exclusions[node_id] = ExclusionDecision(
                    node_id=node_id,
                    reason="contradiction-closure-unavailable",
                    details=tuple(sorted(added_ids - eligible)),
                )
                continue
            if len(selected_ids | added_ids) > query.budget.max_nodes:
                exclusions[node_id] = ExclusionDecision(
                    node_id=node_id,
                    reason="node-budget",
                    details=(),
                )
                continue
            proposed_ids = selected_ids | added_ids
            proposed_edges = self._induced_edges(graph.edges, proposed_ids)
            if len(proposed_edges) > query.budget.max_edges:
                exclusions[node_id] = ExclusionDecision(
                    node_id=node_id,
                    reason="edge-budget",
                    details=(),
                )
                continue
            added_edges = {
                edge.edge_id: edge for edge in proposed_edges
            }.keys() - {edge.edge_id for edge in selected_edges}
            edge_by_id = {edge.edge_id: edge for edge in proposed_edges}
            incremental = sum(
                self._estimator.cost(nodes[added_id].content_dict())
                for added_id in added_ids
            ) + sum(
                self._estimator.cost(edge_by_id[edge_id].content_dict())
                for edge_id in added_edges
            )
            if used + incremental > query.budget.budget_bytes:
                exclusions[node_id] = ExclusionDecision(
                    node_id=node_id,
                    reason="byte-budget",
                    details=(),
                )
                continue
            for added_id in added_ids:
                if added_id != node_id:
                    phases[added_id] = phases[node_id]
                    reasons[added_id].add("contradiction-closure")
                exclusions.pop(added_id, None)
            selected_ids.update(added_ids)
            selected_edges = proposed_edges
            used += incremental

        for node_id in sorted(candidate_ids - selected_ids):
            exclusions.setdefault(
                node_id,
                ExclusionDecision(node_id=node_id, reason="not-selected", details=()),
            )
        decisions = tuple(
            self._decision(
                nodes[node_id],
                reasons=reasons[node_id],
                phase=phases[node_id],
                distance=distances.get(node_id, 0),
                lexical=lexical_scores[node_id],
            )
            for node_id in sorted(selected_ids)
        )
        edge_cost = sum(
            self._estimator.cost(edge.content_dict()) for edge in selected_edges
        )
        used_exact = sum(item.cost_bytes for item in decisions) + edge_cost
        if used != used_exact:
            raise ContextSelectionError("Context budget accounting drifted.")
        contradiction_ids = tuple(
            sorted(
                edge.edge_id
                for edge in selected_edges
                if edge.edge_type is EdgeType.CONTRADICTS
            )
        )
        selection = ContextSelection(
            candidate=graph.candidate,
            graph_id=graph_artifact.artifact_id,
            query_id=query_artifact.artifact_id,
            query=query,
            as_of=query.as_of,
            sensitivity=max(
                (nodes[node_id].sensitivity for node_id in selected_ids),
                key=SENSITIVITY_RANK.__getitem__,
            ),
            selected=decisions,
            excluded=tuple(exclusions[node_id] for node_id in sorted(exclusions)),
            selected_edge_ids=tuple(
                sorted(edge.edge_id for edge in selected_edges)
            ),
            unresolved_contradiction_ids=contradiction_ids,
            edge_cost_bytes=edge_cost,
            used_bytes=used,
            budget_bytes=query.budget.budget_bytes,
            traversal_truncated=False,
        )
        return artifact_from_value(ContextArtifactType.SELECTION, selection)

    @staticmethod
    def _contradiction_closure(
        starts: set[str],
        contradiction_edges: list[ContextEdge],
    ) -> set[str]:
        closure = set(starts)
        changed = True
        while changed:
            changed = False
            for edge in contradiction_edges:
                endpoints = {edge.source_node_id, edge.target_node_id}
                if closure & endpoints and not endpoints <= closure:
                    closure.update(endpoints)
                    changed = True
        return closure

    def _eligibility_problem(
        self,
        node: ContextNode,
        query: ContextQuery,
    ) -> str | None:
        if SENSITIVITY_RANK[node.sensitivity] > SENSITIVITY_RANK[query.clearance]:
            return "sensitivity-clearance"
        if node.freshness.kind is FreshnessKind.EXPIRES_AT:
            assert node.freshness.observed_at is not None
            assert node.freshness.valid_until is not None
            as_of = _timestamp(query.as_of)
            if not (
                _timestamp(node.freshness.observed_at)
                <= as_of
                <= _timestamp(node.freshness.valid_until)
            ):
                return "stale"
        return None

    def _traverse(
        self,
        graph: ContextGraph,
        query: ContextQuery,
        *,
        starts: set[str],
    ) -> tuple[dict[str, int], set[str]]:
        allowed = set(query.allowed_edge_types)
        adjacency: dict[str, list[tuple[ContextEdge, str]]] = defaultdict(list)
        for edge in graph.edges:
            if edge.edge_type not in allowed:
                continue
            adjacency[edge.source_node_id].append((edge, edge.target_node_id))
            if edge.edge_type is EdgeType.CONTRADICTS:
                adjacency[edge.target_node_id].append((edge, edge.source_node_id))
        for values in adjacency.values():
            values.sort(
                key=lambda item: (
                    item[0].edge_type.value,
                    item[1],
                    item[0].edge_id,
                )
            )
        distances = {node_id: 0 for node_id in starts}
        queue = deque(sorted(starts))
        traversed_edges: set[str] = set()
        while queue:
            current = queue.popleft()
            distance = distances[current]
            neighbors = adjacency.get(current, [])
            if distance >= query.budget.max_traversal_depth:
                if any(target not in distances for _, target in neighbors):
                    raise ContextSelectionError(
                        "Graph traversal exceeds the depth bound."
                    )
                continue
            for edge, target in neighbors:
                traversed_edges.add(edge.edge_id)
                if len(traversed_edges) > query.budget.max_edges:
                    raise ContextSelectionError(
                        "Graph traversal exceeds the edge bound."
                    )
                if target in distances:
                    continue
                if len(distances) >= query.budget.max_nodes:
                    raise ContextSelectionError(
                        "Graph traversal exceeds the node bound."
                    )
                distances[target] = distance + 1
                queue.append(target)
        return distances, traversed_edges

    @staticmethod
    def _induced_edges(
        edges: tuple[ContextEdge, ...],
        selected_ids: set[str],
    ) -> tuple[ContextEdge, ...]:
        return tuple(
            edge
            for edge in edges
            if edge.source_node_id in selected_ids
            and edge.target_node_id in selected_ids
        )

    def _decision(
        self,
        node: ContextNode,
        *,
        reasons: set[str],
        phase: int,
        distance: int,
        lexical: int,
    ) -> SelectionDecision:
        return SelectionDecision(
            node_id=node.node_id,
            reasons=tuple(sorted(reasons)),
            phase=phase,
            authority_rank=AUTHORITY_RANK[node.authority],
            graph_distance=distance,
            lexical_score=lexical,
            sensitivity_rank=SENSITIVITY_RANK[node.sensitivity],
            cost_bytes=self._estimator.cost(node.content_dict()),
        )

    @staticmethod
    def _rank(
        node: ContextNode,
        *,
        phase: int,
        distance: int,
        lexical: int,
    ) -> tuple[int, int, int, int, int, str]:
        return (
            phase,
            AUTHORITY_RANK[node.authority],
            distance,
            -lexical,
            SENSITIVITY_RANK[node.sensitivity],
            node.node_id,
        )


def lexical_tokens(value: str) -> tuple[str, ...]:
    """Tokenize without locale or Unicode database dependencies."""

    tokens: list[str] = []
    ascii_run: list[str] = []

    def flush() -> None:
        if ascii_run:
            tokens.append("".join(ascii_run))
            ascii_run.clear()

    for character in value:
        codepoint = ord(character)
        if 65 <= codepoint <= 90:
            ascii_run.append(chr(codepoint + 32))
        elif 97 <= codepoint <= 122 or 48 <= codepoint <= 57:
            ascii_run.append(character)
        else:
            flush()
            if codepoint > 127:
                tokens.append(character)
    flush()
    return tuple(tokens)


def lexical_score(node: ContextNode, query_tokens: set[str]) -> int:
    """Return the exact binary field-presence lexical score."""

    if not query_tokens:
        return 0
    title = set(lexical_tokens(node.title))
    labels: set[str] = set()
    for label in node.labels:
        labels.update(lexical_tokens(label))
    path = set(lexical_tokens(node.locator.path))
    content = set(lexical_tokens(node.text))
    return sum(
        (16 if token in title else 0)
        + (8 if token in labels else 0)
        + (4 if token in path else 0)
        + (1 if token in content else 0)
        for token in query_tokens
    )


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class ContextSnapshotService:
    """Re-observe selected sources and build exact portable snapshots."""

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

    def build(
        self,
        graph_artifact: LoadedContextArtifact,
        selection_artifact: LoadedContextArtifact,
        *,
        repository_root: Path,
        owner_root: Path | None = None,
    ) -> LoadedContextArtifact:
        """Re-observe selected non-immutable sources and build a snapshot."""

        if (
            graph_artifact.artifact_type is not ContextArtifactType.GRAPH
            or not isinstance(graph_artifact.value, ContextGraph)
            or selection_artifact.artifact_type
            is not ContextArtifactType.SELECTION
            or not isinstance(selection_artifact.value, ContextSelection)
        ):
            raise ContextSelectionError(
                "Snapshot requires Graph and Selection artifacts."
            )
        graph = graph_artifact.value
        selection = selection_artifact.value
        if (
            selection.graph_id != graph_artifact.artifact_id
        ):
            raise ContextSelectionError("Snapshot input identities do not match.")
        if graph.candidate != selection.candidate:
            raise ContextSelectionError("Snapshot candidate identities do not match.")
        canonical = [
            node
            for node in graph.nodes
            if node.authority is AuthorityClass.CANONICAL_SPECIFICATION
        ]
        if (
            len(canonical) != 1
            or not canonical[0].required
            or canonical[0].kind is not SourceKind.SPECIFICATION
            or canonical[0].locator.root_scope is not RootScope.REPOSITORY
            or canonical[0].locator.sha256
            != graph.candidate.source_spec_sha256
        ):
            raise ContextSelectionError(
                "Graph lacks one required candidate-bound canonical specification."
            )
        self._candidate_verifier.verify(repository_root, graph.candidate)
        query_artifact = artifact_from_value(
            ContextArtifactType.QUERY,
            selection.query,
        )
        if query_artifact.artifact_id != selection.query_id:
            raise ContextSelectionError("Embedded Query identity does not match.")
        expected_selection = ContextSelector(self._estimator).select(
            graph_artifact,
            query_artifact,
        )
        if expected_selection != selection_artifact:
            raise ContextSelectionError(
                "Selection is not the exact deterministic result for Graph and Query."
            )
        node_by_id = {node.node_id: node for node in graph.nodes}
        edge_by_id = {edge.edge_id: edge for edge in graph.edges}
        selected_ids = tuple(item.node_id for item in selection.selected)
        try:
            nodes = tuple(node_by_id[node_id] for node_id in selected_ids)
            edges = tuple(
                edge_by_id[edge_id] for edge_id in selection.selected_edge_ids
            )
        except KeyError as exc:
            raise ContextSelectionError(
                "Selection references missing graph content."
            ) from exc
        owner_nodes = [
            node for node in nodes if node.locator.root_scope is RootScope.OWNER
        ]
        if owner_nodes and owner_root is None:
            raise ContextSelectionError(
                "Selected owner context requires an explicit owner root."
            )
        if not owner_nodes and owner_root is not None:
            raise ContextSelectionError("Unused owner root is not permitted.")
        required_ids = {
            node.node_id for node in graph.nodes if node.required
        } | set(selection.query.required_node_ids)
        failed_optional: dict[str, str] = {}
        for node in nodes:
            root = (
                repository_root
                if node.locator.root_scope is RootScope.REPOSITORY
                else owner_root
            )
            assert root is not None
            problem: str | None = None
            try:
                validate_context_authority(node)
            except ContextContractError:
                problem = "authority-invalid"
            if problem is None:
                try:
                    observation = self._reader.observe(root, node.locator)
                except ContextSourceError as exc:
                    problem = self._source_failure_reason(exc)
                else:
                    if node.freshness.kind is FreshnessKind.IMMUTABLE:
                        try:
                            validate_context_json_bytes(observation.content)
                        except ContextContractError:
                            problem = "invalid-json"
                    if problem is None and observation.selected_text != node.text:
                        problem = "changed"
                    elif (
                        problem is None
                        and node.freshness.kind is FreshnessKind.EXPIRES_AT
                    ):
                        assert node.freshness.observed_at is not None
                        assert node.freshness.valid_until is not None
                        as_of = _timestamp(selection.as_of)
                        if not (
                            _timestamp(node.freshness.observed_at)
                            <= as_of
                            <= _timestamp(node.freshness.valid_until)
                        ):
                            problem = "stale"
                if problem is None:
                    try:
                        for reference in node.provenance.references:
                            self._reader.verify_reference(root, reference)
                    except ContextSourceError:
                        problem = "provenance-unavailable"
            if problem is not None:
                if node.node_id in required_ids:
                    raise ContextSelectionError(
                        "Required context failed snapshot re-observation."
                    )
                failed_optional[node.node_id] = problem
        contradiction_edges = [
            edge for edge in edges if edge.edge_type is EdgeType.CONTRADICTS
        ]
        excluded_ids: set[str] = set()
        for failed_id in sorted(failed_optional):
            component = ContextSelector._contradiction_closure(
                {failed_id},
                contradiction_edges,
            )
            if component & required_ids:
                raise ContextSelectionError(
                    "Required contradiction closure failed re-observation."
                )
            excluded_ids.update(component)
        nodes = tuple(node for node in nodes if node.node_id not in excluded_ids)
        if not nodes:
            raise ContextSelectionError("Snapshot cannot adopt empty context.")
        selected_node_ids = {node.node_id for node in nodes}
        edges = tuple(
            edge
            for edge in edges
            if edge.source_node_id in selected_node_ids
            and edge.target_node_id in selected_node_ids
        )
        for edge in edges:
            for reference in edge.provenance.references:
                try:
                    self._reader.verify_reference(repository_root, reference)
                except ContextSourceError as exc:
                    raise ContextSelectionError(
                        "Selected edge provenance failed re-observation."
                    ) from exc
        self._candidate_verifier.verify(repository_root, graph.candidate)
        selected_decisions = tuple(
            item for item in selection.selected if item.node_id in selected_node_ids
        )
        exclusions = {item.node_id: item for item in selection.excluded}
        for node_id in sorted(excluded_ids):
            exclusions[node_id] = ExclusionDecision(
                node_id=node_id,
                reason=failed_optional.get(node_id, "contradiction-closure-unavailable"),
                details=(),
            )
        required_sensitivity = max(
            (node.sensitivity for node in nodes),
            key=SENSITIVITY_RANK.__getitem__,
        )
        if required_sensitivity is Sensitivity.SECRET_OR_PROHIBITED:
            raise ContextSelectionError("Snapshot cannot adopt prohibited context.")
        snapshot = ContextSnapshot(
            candidate=graph.candidate,
            graph_id=graph_artifact.artifact_id,
            query_id=selection.query_id,
            selection_id=selection_artifact.artifact_id,
            as_of=selection.as_of,
            sensitivity=required_sensitivity,
            nodes=nodes,
            edges=edges,
            selected=selected_decisions,
            excluded=tuple(exclusions[node_id] for node_id in sorted(exclusions)),
            unresolved_contradiction_ids=tuple(
                edge.edge_id
                for edge in edges
                if edge.edge_type is EdgeType.CONTRADICTS
            ),
            context_bytes=sum(
                self._estimator.cost(node.content_dict()) for node in nodes
            )
            + sum(self._estimator.cost(edge.content_dict()) for edge in edges),
            budget_bytes=selection.budget_bytes,
        )
        artifact = artifact_from_value(ContextArtifactType.SNAPSHOT, snapshot)
        return parse_context_artifact_bytes(
            serialize_context_artifact(artifact),
            expected_type=ContextArtifactType.SNAPSHOT,
        )

    @staticmethod
    def _source_failure_reason(exc: ContextSourceError) -> str:
        message = str(exc).casefold()
        if "digest" in message:
            return "digest-mismatch"
        if "changed" in message:
            return "changed"
        if "size" in message or "byte" in message:
            return "source-byte-limit"
        return "missing-or-unreadable"

    def publish(
        self,
        graph_artifact: LoadedContextArtifact,
        selection_artifact: LoadedContextArtifact,
        *,
        repository_root: Path,
        owner_root: Path | None,
        output: Path,
    ) -> LoadedContextArtifact:
        """Build and exclusively publish a snapshot."""

        if self._publisher is None:
            raise ContextSelectionError("Snapshot publisher is unavailable.")
        artifact = self.build(
            graph_artifact,
            selection_artifact,
            repository_root=repository_root,
            owner_root=owner_root,
        )
        self._publisher.publish(output, serialize_context_artifact(artifact))
        return artifact


def compare_context_snapshots(
    base: LoadedContextArtifact,
    current: LoadedContextArtifact,
) -> ContextSnapshotDelta:
    """Return one ordered structural snapshot delta."""

    if (
        base.artifact_type is not ContextArtifactType.SNAPSHOT
        or not isinstance(base.value, ContextSnapshot)
        or current.artifact_type is not ContextArtifactType.SNAPSHOT
        or not isinstance(current.value, ContextSnapshot)
    ):
        raise ContextSelectionError("Context comparison requires two Snapshots.")
    base_nodes = {node.node_id for node in base.value.nodes}
    current_nodes = {node.node_id for node in current.value.nodes}
    base_edges = {edge.edge_id for edge in base.value.edges}
    current_edges = {edge.edge_id for edge in current.value.edges}
    return ContextSnapshotDelta(
        base_snapshot_id=base.artifact_id,
        current_snapshot_id=current.artifact_id,
        added_node_ids=tuple(sorted(current_nodes - base_nodes)),
        removed_node_ids=tuple(sorted(base_nodes - current_nodes)),
        added_edge_ids=tuple(sorted(current_edges - base_edges)),
        removed_edge_ids=tuple(sorted(base_edges - current_edges)),
        sensitivity_changed=base.value.sensitivity is not current.value.sensitivity,
        candidate_changed=base.value.candidate != current.value.candidate,
    )
