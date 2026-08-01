# Context Framework

M5 provides deterministic, provenance-bound context artifacts for offline
development workflows. It does not read ambient memory, crawl the web, execute
retrieved text, or give generated summaries authority.

## Artifact lifecycle

The public lifecycle is:

```text
Manifest -> Graph -> Query + Graph -> Selection -> Snapshot -> Compaction
                                      |              |
                                      |              +-> structural comparison
                                      +-> Quality Report with Graph and Snapshot
```

Every artifact is immutable JSON schema `1.0` with an `artifact_type`, full
content-addressed `artifact_id`, and identity-bearing `content`. IDs use the
uppercase SHA-256 of canonical content. Canonical JSON sorts ASCII keys, uses no
insignificant whitespace, escapes non-ASCII text, accepts finite integers only,
and rejects lone surrogates.

The eight schemas are:

- `context-manifest.schema.json`
- `context-graph.schema.json`
- `context-query.schema.json`
- `context-selection.schema.json`
- `context-snapshot.schema.json`
- `context-compaction.schema.json`
- `context-host-summary-proposal.schema.json`
- `context-quality-report.schema.json`

Existing schemas are unchanged. The top-level Python export list is unchanged.

## Sources and explicit roots

A Manifest names every source. Its locator contains:

- `root_scope`: `repository` or `owner`;
- a portable ASCII POSIX relative path;
- the SHA-256 of the complete source bytes;
- a 1-based inclusive line range.

Absolute roots are command arguments and are never serialized. `owner` sources
are read only when `--owner-root` is supplied. An unused owner root is rejected,
which prevents a command from appearing to consume a private scope that it did
not use.

Indexing accepts regular, unlinked strict UTF-8 files only. It checks the path
component by component, confines it under the explicit root, limits one source
to 256 KiB and all sources to 8 MiB, and compares stat data before and after the
read. Identity-bearing node and extract text is also capped at 65,536 Unicode
characters in both runtime contracts and JSON Schema; runtime retains the exact
256 KiB UTF-8 ceiling. Other JSON Schema `maxLength` and runtime text limits
both count Unicode characters, while the whole artifact byte ceilings remain
independent. Optional
sources that cannot be safely adopted are recorded in the
Graph's `excluded_sources`; the same failure on a required source blocks the
Graph. Output is created exclusively and never overwrites an existing path.

## Identity, provenance, and candidate binding

Node, edge, and artifact IDs contain the full 64-hex SHA-256. Graph, Query,
Selection, Snapshot, and Compaction bind the existing source-specification,
Git-HEAD, and repository-digest CandidateIdentity. Indexing and snapshot
construction re-observe the explicit repository root through the existing
bounded Git inspector and require an exact CandidateIdentity match. The
Manifest must contain exactly one repository-scoped canonical specification,
and its locator digest must equal `candidate.source_spec_sha256`. A valid Graph
must preserve that source as its one required canonical specification node.

Every source and node requires provenance references, an authority class,
freshness policy, sensitivity, kind, digest, and locator. Authority order is:

1. `owner-approved`
2. `canonical-specification`
3. `accepted-public-contract`
4. `verified-evidence`
5. `repository-record`
6. `untrusted-observation`
7. `untrusted-proposal`

Authority metadata is evidence to validate; writing a higher label does not
make generated content authoritative. Every provenance reference is reread as
a regular, unlinked, bounded file and its digest is checked. Authoritative
sources also require an exact reference to their own locator. Structural rules
limit `owner-approved` to explicit owner-root Owner records,
`canonical-specification` to the unique repository specification,
`accepted-public-contract` to repository requirements/decisions/designs, and
`verified-evidence` to repository evidence. Tool observations remain
`untrusted-observation`.

Repository outputs must be outside the publication candidate, or in a path
excluded from its repository digest. Writing an output into the candidate
changes that candidate, so a later candidate-bound operation fails closed
until the caller supplies a newly observed identity.

## Freshness

- `immutable` is limited to verified, self-linked JSON with an authoritative
  class. Index and Snapshot still reread the full strict JSON bytes, verify the
  declared digest and provenance, and reject duplicate keys, non-finite values,
  floats, surrogates, or excessive JSON structure.
- `candidate-bound` is reread for every snapshot and must retain its exact
  digest, selected line text, and candidate.
- `expires-at` requires an explicit UTC observation and validity interval. The
  identity-bearing Query/Selection `as_of` must be inside the interval.

Required stale, missing, changing, candidate-mismatched, provenance-invalid, or
inaccessible context blocks publication. Optional indexing failures receive an
exact Graph exclusion. Optional selected sources that fail re-observation are
recorded in the Snapshot's `excluded`; if they belong to a non-required
contradiction component, the whole component is excluded atomically. A failed
required source or required contradiction component still blocks publication.

## Sensitivity

Sensitivity increases from `public` to `repository-private` to `owner-private`
to `secret-or-prohibited`. Derived artifacts equal the highest included
sensitivity and cannot downgrade it. Selection embeds both its exact Query and
its derived sensitivity. Snapshot, Compaction, and Quality Report preserve the
candidate and highest sensitivity; Compaction also takes the maximum of the
Snapshot and an adopted host proposal. A missing source sensitivity is
canonicalized to `owner-private` before source identity verification. Active M5
artifacts reject `secret-or-prohibited` source text; they may report only the
bounded rejection reason.

The synthetic checked-in fixtures are `public`. Owner-root content, parent
state, runtime `.sdaqf/` content, credentials, and machine-absolute paths are
not public fixtures.

## Retrieval and ranking

Selection phases are:

1. required references;
2. breadth-first graph traversal;
3. exact identifiers;
4. lexical matches.

BFS visits once and orders neighbors by edge type, target node ID, then edge ID.
A frontier beyond the configured hard depth, node, or edge bound is a blocker,
not a silent partial result.

Lexical tokenization manually lowercases ASCII letters, emits maximal ASCII
alphanumeric runs, and treats each non-ASCII Unicode scalar as one exact token.
It has no locale, Unicode-category database, corpus, floating-point, tokenizer,
or model dependency. Each distinct query token scores binary presence in title
16, labels 8, path 4, and content 1. Term frequency adds nothing.

Ranking uses phase, authority, graph distance, descending lexical score,
sensitivity, and full node ID. Serialized selections remain portable and record
each rank component, selection reason, exclusion reason, and exact byte cost.
The Selection also embeds the complete identity-bearing Query. Snapshot
construction recreates that Query, reruns the production selector, and requires
the supplied Selection artifact to equal the deterministic output exactly.

## Contradictions

`contradicts` is the sole undirected edge and sorts its endpoint IDs. Selecting
one endpoint in any phase forces its complete contradiction-connected component
and contradiction edges into one atomic decision. A required component that is
stale, inaccessible, over clearance, or over budget blocks selection. An
optional component that cannot be adopted is excluded as a unit with an exact
reason. Otherwise the Snapshot records every unresolved contradiction. M5 never
chooses a winner.

## Budget and compaction

The normative unit is `canonical_utf8_bytes`. A selected node or edge costs the
UTF-8 length of its canonical content. Query limits are:

- 1,024 through 8,388,608 bytes;
- 1 through 4,096 nodes;
- 0 through 16,384 edges;
- traversal depth 0 through 8.

Required nodes, induced required edges, and contradiction closure allocate
first and cannot be evicted. Optional nodes are considered in deterministic
rank order.

Compaction is extractive. It preserves required and contradiction extracts,
node and source IDs, authority, sensitivity, exact contradiction IDs, text
digests, highest sensitivity, and exact byte use. Before a persisted Snapshot
is compacted, production Compaction strictly round-trips the complete in-memory
Snapshot and optional HostSummaryProposal envelope/value. It then recomputes
every canonical source identity and rejects duplicates in a pure preflight pass
before any candidate or source I/O, followed by candidate, source text,
freshness, and provenance re-observation through explicit roots. A merely
rehashed or parser-bypassing artifact cannot authenticate itself. Immediately
before exclusive publication, CandidateIdentity is verified again from the
validated Compaction that will be serialized, never by rereading the caller's
original Snapshot object. A host summary is always `untrusted-proposal`, must
link claims to selected nodes and exact extract digests, and is never used as
the sole authority for a Must, approval, security, disclosure, or data-loss
decision.

## CLI

```text
sdaqf context validate ARTIFACT --json
sdaqf context index MANIFEST --repository-root ROOT [--owner-root ROOT] --output GRAPH --json
sdaqf context select GRAPH QUERY --output SELECTION --json
sdaqf context snapshot GRAPH SELECTION --repository-root ROOT [--owner-root ROOT] --output SNAPSHOT --json
sdaqf context compare BASE_SNAPSHOT CURRENT_SNAPSHOT --json
sdaqf context compact SNAPSHOT --repository-root ROOT [--owner-root ROOT] --output COMPACTION [--host-summary-proposal PROPOSAL] --json
```

`validate` and `compare` are side-effect-free. The other commands publish one
fresh explicit output. Expected `--json` failures return nonzero with a bounded
JSON error on stdout and no partial output.

## Quality and local validation

The quality report names required-reference recall, stale required count,
provenance complete/missing counts, sensitivity violations, selected and budget
bytes, redundant bytes, selected/excluded nodes, unresolved contradictions, and
traversal truncation. It has no aggregate score.

Run:

```text
python scripts/validate_m5_context.py
```

Success starts with `PASS: M5-CONTEXT-INTEGRITY`. The validator checks all eight
schemas and artifacts, exact reindexing, deterministic selection, snapshot
re-observation, compaction, quality reproduction, seven named evaluation
scenarios, and the no-aggregate rule. The seven observations are produced by
executing the relevant success or fail-closed path; checked-in `passed` flags
are compared with those observations and are not accepted as evidence by
themselves.
