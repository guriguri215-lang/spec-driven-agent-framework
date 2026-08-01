# M5 Context Framework

This living ExecPlan follows `PLANS.md`. Keep `Progress`, `Surprises &
Discoveries`, `Decision Log`, and `Outcomes & Retrospective` current while the
work proceeds.

## Purpose / Big Picture

M5 adds an offline-first Context Framework that converts explicit,
provenance-bound sources into immutable Context Graphs and exact Context
Snapshots. A user can validate, index, select, snapshot, compare, and compact
context with deterministic results and complete inclusion/exclusion reasons.
M6 can consume a validated snapshot without rereading ambient host context.

The observable result is:

- the same inputs have the same full SHA-256 identities on Windows and Linux;
- required context cannot be silently omitted, evicted, downgraded, or replaced
  by generated summary text;
- stale, changing, unsafe, prohibited, contradictory-without-representation, or
  over-bound required context fails closed;
- all operations are bounded, offline, and dependency-free;
- `M5-CONTEXT-INTEGRITY` reports named measurements without an aggregate score.

## Progress

- [x] (2026-07-31) Completed offline discovery of the existing domain,
  application, CLI, schema, test, fixture, and release-contract surfaces.
- [x] (2026-07-31) Received Owner approval for material decisions M5-D1 through
  M5-D6 and the exact tracked implementation scope.
- [x] (2026-07-31) Checkpoint 1: contracts, canonical identities,
  ports/adapters, eight schemas, and runtime/schema parity; focused tests,
  Ruff, and strict mypy passed.
- [x] (2026-07-31) Checkpoint 2: safe indexing and deterministic selection;
  required, clearance, contradiction, traversal, lexical, and publication
  tests passed.
- [x] (2026-07-31) Checkpoint 3: snapshots, comparison, compaction, quality,
  CLI, fixtures, evaluation, and named validator; 45 focused tests and
  `M5-CONTEXT-INTEGRITY` passed.
- [x] (2026-07-31) Independent read-only review preserved the exact candidate
  and reported five High and three Medium findings: fabricated Selection
  acceptance, incomplete contradiction closure, synthetic candidate trust,
  authority laundering, downstream identity/sensitivity loss, optional-source
  ambiguity, schema/runtime drift, and non-executable evaluation evidence.
- [x] (2026-07-31) Implemented the Owner-approved M5-RF1 through M5-RF7
  remediation inside the existing tracked-path boundary. Focused adversarial
  tests, executable seven-case validation, Ruff, and strict mypy pass.
- [x] (2026-07-31) Checkpoint 4 local work: English documentation and complete
  offline regression passed with 719 tests and three explicit environment link
  skips; total/M1/M2/M3/M4/M5 branch coverage is 89/94/90/91/92/83 percent.
- [x] (2026-07-31) Independent re-review preserved the frozen candidate and
  returned NO-GO with two High and three Medium findings: immutable evidence
  was not reread, standalone Snapshot integrity was incomplete, Unicode bounds
  differed, invalid Git roots escaped the CLI envelope, and test prose was
  overstated.
- [x] (2026-07-31) Closed those findings inside the existing approved
  remediation boundary. The second local validation passes 71 focused tests,
  726 full tests with three explicit environment link skips, Ruff, strict mypy,
  all coverage Gates, CLI smoke, the strengthened validator, and all audits.
- [x] (2026-07-31) A second independent re-review preserved the newly frozen
  candidate and returned NO-GO with one High and two Medium findings: persisted
  Snapshot compaction trusted unauthenticated text, ordinary Unicode text bounds
  differed between schema and runtime, and Compaction discarded source and
  contradiction metadata.
- [x] (2026-07-31) Closed the second-review findings inside the existing
  approved remediation boundary. Production compaction now reauthenticates the
  candidate, source bytes, freshness, authority, and provenance before use;
  ordinary text bounds use schema-equivalent character counts while source
  limits retain their exact byte ceiling; and Compaction preserves source IDs,
  authority, sensitivity, and exact contradiction markers. The third local
  validation passes 75 focused tests, 730 full tests with three explicit
  environment link skips, Ruff, strict mypy, all coverage Gates, CLI smoke,
  the strengthened validator, and all audits.
- [x] (2026-07-31) A third independent read-only re-review preserved the exact
  candidate and returned NO-GO with one High and one Medium finding: a rehashed
  Snapshot could carry a fabricated source ID into Compaction, and the
  root-bearing `context compact` signature lacked a superseding Owner decision.
- [x] (2026-07-31) Owner approved M5-D5A, replacing only the Compaction command
  signature with explicit repository and optional owner roots so persisted
  Snapshot content can be reauthenticated without weakening the public trust
  boundary. The source-identity remediation recomputes canonical source IDs and
  rejects duplicates in Graph, Snapshot, and production Compaction.
- [x] (2026-07-31) The fourth local validation passes 81 focused tests, 736
  full tests with three explicit environment link skips, Ruff, strict mypy,
  total/M1/M2/M3/M4/M5 branch coverage of 89/94/90/91/92/83 percent, CLI
  smoke, the strengthened validator, and all local audits.
- [x] (2026-07-31) A fourth independent read-only re-review preserved the exact
  candidate and returned NO-GO with one High and one Medium finding: direct
  in-memory Compactor inputs bypassed complete Snapshot/HostProposal validation,
  and individual source-identity rejection could occur after earlier I/O.
- [x] (2026-07-31) Closed both findings inside the approved remediation
  boundary. Compactor now strictly round-trips all input envelopes and values,
  validates cross-artifact host links, and preflights every source identity in
  one pure pass before candidate verification or source reads. Zero-I/O spy
  regressions cover false artifact identity, missing canonical context,
  host-authority laundering, and incorrect or duplicate source identities.
- [x] (2026-07-31) The fifth local validation passes 84 focused tests, 739 full
  tests with three explicit environment link skips, Ruff, strict mypy,
  total/M1/M2/M3/M4/M5 branch coverage of 89/94/90/91/92/83 percent, CLI
  smoke, the strengthened validator, and all local audits.
- [x] (2026-07-31) A fifth independent read-only re-review preserved the exact
  candidate and returned NO-GO with one High finding: final publication
  verification could authenticate a caller-mutated Snapshot candidate while
  serializing the already-built Compaction for a different candidate.
- [x] (2026-07-31) Closed the finding inside the approved remediation boundary.
  Final verification now derives its expected CandidateIdentity from the
  validated Compaction being serialized. A reentrant mutation regression proves
  a candidate change fails closed before any publication.
- [x] (2026-07-31) The sixth local validation passes 85 focused tests, 740 full
  tests with three explicit environment link skips, Ruff, strict mypy over 115
  files, total/M1/M2/M3/M4/M5 branch coverage of 89/94/90/91/92/83 percent,
  CLI smoke, the strengthened validator, and all local audits.
- [ ] Checkpoint 4 review: freeze the remediated candidate and obtain the
  separate Owner boundary for independent read-only re-review.
- [ ] Check roadmap truth and prepare a separately approved patch only if the
  implementation evidence requires one.
- [ ] Update the private M6 handoff and present the separate Git boundary.

## Surprises & Discoveries

- Existing shared contracts already reject duplicate JSON keys, unsafe portable
  paths, links/reparse points, oversized inputs, excessive depth/nodes, and
  non-finite numbers. M5 extends these helpers instead of introducing a second
  permissive parser.
- Existing requirement ingestion provides a stat-before/read/stat-after pattern,
  and migration publication provides source-preserving exclusive publication.
- The top-level `context` namespace is unused. Existing uses of the word
  “context” are fields in checkpoint, tool, prompt, or handoff records and are
  not a public Context Framework contract.
- A content-addressed Selection is not proof that its decisions came from the
  selector. Embedding the exact Query and rerunning selection at Snapshot time
  closes that semantic gap.
- Candidate labels and provenance labels are declarations, not observations.
  The application must re-observe Git identity and referenced bytes and enforce
  structural authority rules before adoption.

## Decision Log

- **M5-D1 — identity and source locator.** Artifacts are envelopes containing
  `schema_version`, `artifact_type`, `artifact_id`, and `content`.
  `artifact_id` is `CTX-<TYPE>-` plus the full uppercase SHA-256 of canonical
  content. Nodes and edges use full digests. Source locators use an explicit
  `repository` or `owner` root scope, portable ASCII POSIX relative path,
  raw-byte SHA-256, and 1-based inclusive line range. Absolute roots are never
  serialized.
- **M5-D2 — freshness.** Freshness is `immutable`, `candidate-bound`, or
  `expires-at`. Query `as_of` is identity-bearing RFC 3339 UTC. Required stale,
  changing, missing, candidate-mismatched, or over-clearance sources block
  publication; optional sources receive explicit exclusion reasons.
- **M5-D3 — budget.** The normative unit is canonical UTF-8 bytes. Query bounds
  are 1,024–8,388,608 bytes, 1–4,096 nodes, 0–16,384 edges, and traversal depth
  0–8. Required/provenance/contradiction closure allocates first.
- **M5-D4 — retrieval.** Phases are required references, breadth-first graph,
  exact identifiers, then lexical. Lexical field weights are title 16, labels 8,
  path 4, content 1 with integer presence scoring and no term-frequency bonus.
  Authority, distance, score, sensitivity, and full node ID form the stable
  tie-break. Contradictions force both endpoints and never select a winner.
- **M5-D5 — public contracts.** Add `sdaqf context
  validate|index|select|snapshot|compare|compact` and eight new schema `1.0`
  files. Existing commands, schemas, and `sdaqf.__all__` remain unchanged.
- **M5-D5A — persisted-Snapshot Compaction authentication.** Supersede only the
  `context compact` signature: require an explicit repository root and accept
  an optional explicit owner root. No root is inferred. This enables source,
  freshness, authority, provenance, and CandidateIdentity reauthentication;
  existing pre-M5 commands, schemas, exports, and V1 behavior remain unchanged.
- **M5-D6 — evidence.** Commit only synthetic public fixtures, schemas, tests,
  evaluation results, named validator, and English product documentation.
  Private state, owner content, ambient runtime state, and aggregate scores are
  excluded.
- **M5-RF1 through M5-RF7 — independent-review remediation.** Selection embeds
  its Query and derived sensitivity; Snapshot reruns exact selection; every
  selection phase uses atomic contradiction closure; Index and Snapshot inject
  an actual Candidate verifier; provenance references and authority structure
  are verified; Compaction and Quality preserve candidate/sensitivity;
  optional failures become exact Graph/Snapshot exclusions while required
  failures block; immutable JSON is still byte-observed and parsed strictly;
  standalone Snapshots require canonical context and recomputed costs;
  schema/runtime bounds agree; Git inspection failure remains a bounded CLI
  error; and the named validator executes all seven scenarios plus the reviewed
  trust-boundary regressions rather than trusting recorded pass flags. Persisted
  Snapshot compaction also reobserves and authenticates every selected source,
  strictly validates complete in-memory inputs, recomputes canonical source
  identities in one pre-I/O pass, rejects duplicates, validates authority and
  provenance again, and preserves source IDs and exact contradiction markers
  in every extract.

## Context and Orientation

The repository uses a domain/application/ports/adapters architecture:

- `src/sdaqf/domain/` contains immutable values with no I/O;
- `src/sdaqf/application/` parses contracts and implements use cases;
- `src/sdaqf/ports/` declares injected boundaries;
- `src/sdaqf/adapters/` implements bounded local boundaries;
- `src/sdaqf/cli.py` is the public command dispatcher;
- `schemas/` contains additive strict JSON Schema contracts;
- `tests/schema_validation.py` is the dependency-free parity validator;
- `scripts/run_cli_smoke.py` exercises the offline public CLI.

Reuse `CandidateIdentity`, strict JSON helpers, portable paths, source
observation checks, and exclusive publication. Do not modify the meaning of any
existing contract.

## Scope

Add domain types for Context Manifest, Source, Node, Edge, Graph, Query,
Selection, Snapshot, Delta, Compaction, Host Summary Proposal, and named Context
Quality measurements. Add application services for strict contracts, indexing,
selection, snapshot comparison, compaction, and quality. Add injected source
reader, candidate verifier, and budget estimator ports with standard-library
local adapters.

Add these schemas:

1. `context-manifest.schema.json`
2. `context-graph.schema.json`
3. `context-query.schema.json`
4. `context-selection.schema.json`
5. `context-snapshot.schema.json`
6. `context-compaction.schema.json`
7. `context-host-summary-proposal.schema.json`
8. `context-quality-report.schema.json`

Add these commands:

    sdaqf context validate ARTIFACT --json
    sdaqf context index MANIFEST --repository-root ROOT [--owner-root ROOT] --output GRAPH --json
    sdaqf context select GRAPH QUERY --output SELECTION --json
    sdaqf context snapshot GRAPH SELECTION --repository-root ROOT [--owner-root ROOT] --output SNAPSHOT --json
    sdaqf context compare BASE_SNAPSHOT CURRENT_SNAPSHOT --json
    sdaqf context compact SNAPSHOT --repository-root ROOT [--owner-root ROOT] --output COMPACTION [--host-summary-proposal PROPOSAL] --json

`validate` and `compare` are side-effect-free. The other commands publish one
explicit fresh output exclusively and never overwrite an existing artifact.

## Non-goals

M5 does not add SQLite, scheduling, dispatch, agents, solvers, workflow
execution, web crawling, ambient memory import, secret ingestion, execution of
retrieved text, embeddings, vector search, hosted services, OpenAI APIs, Agents
SDK, a management UI, or a runtime dependency. It does not modify existing
schemas, top-level exports, Gates, or V1 command behavior.

`docs/roadmap.md` is not part of implementation scope. If verified
implementation changes roadmap truth, prepare an exact separate patch and wait
for Owner approval.

## Identity and canonicalization

Each artifact is:

    {
      "schema_version": "1.0",
      "artifact_type": "...",
      "artifact_id": "CTX-...-<64 uppercase hex>",
      "content": { ... }
    }

Canonical content JSON has sorted ASCII keys, no insignificant whitespace,
ASCII escaping, finite integers only, and no lone surrogates. The ID field is
outside the hashed content. Source bytes are strict UTF-8 and are not newline or
Unicode normalized.

Directed edge identity includes type, source, target, and provenance.
`contradicts` is the sole undirected edge and sorts its endpoints. All graph and
downstream artifacts bind the existing CandidateIdentity.

## Provenance, authority, freshness, and sensitivity

Every source and node has provenance, authority, freshness, sensitivity, kind,
locator, and candidate binding. Authority ranks:

1. `owner-approved`
2. `canonical-specification`
3. `accepted-public-contract`
4. `verified-evidence`
5. `repository-record`
6. `untrusted-observation`
7. `untrusted-proposal`

Authority is validated provenance metadata; a label alone does not turn
generated text into authority.

Freshness:

- `immutable`: allow only authoritative, self-linked strict JSON and reread its
  full bytes at Index and Snapshot boundaries;
- `candidate-bound`: reread exact source and candidate on every snapshot;
- `expires-at`: require `observed_at <= query.as_of <= valid_until`.

Sensitivity ranks:

1. `public`
2. `repository-private`
3. `owner-private`
4. `secret-or-prohibited`

Unlabelled imports become `owner-private`. Derived artifacts inherit the highest
included sensitivity. `secret-or-prohibited` source text is never adopted.

## Retrieval and compaction

Required nodes allocate first. BFS starts from required and seed nodes, visits
once, and orders neighbors by `(edge_type, target_node_id, edge_id)`. Exact
identifiers and then lexical matches follow.

Lexical tokenization manually folds ASCII letters, emits maximal ASCII
alphanumeric runs, and treats each non-ASCII Unicode scalar as an exact token.
It does not depend on locale or a Unicode category database. For each distinct
query token, binary presence weights are title 16, labels 8, source path 4, and
content 1.

Every selected node records all applicable reasons and its rank tuple. Every
unselected candidate records an exclusion reason. Traversal beyond a hard bound
is a named blocker, not a silent partial result.

Selecting one endpoint of a canonical contradiction in any phase forces the
complete connected contradiction component and its edges into one atomic
decision. M5 records every adopted unresolved conflict and never chooses a
winner.

Compaction is extractive and deterministic. It preserves required authority,
source IDs, exact extract digests, contradiction markers, and highest
sensitivity. Each extract carries the exact contradiction IDs that caused
atomic retention, and the top-level Compaction preserves their union. Persisted
Snapshots are reauthenticated against explicit roots before Compaction. A host
summary is always an `untrusted-proposal` with exact source
links and cannot be the only basis for a Must, approval, security, disclosure,
or data-loss decision.

## Bounds

- Manifest, Query, Host Summary Proposal: 1 MiB each.
- Graph, Selection, Snapshot, Compaction, Quality Report: 16 MiB each.
- One adopted source: 256 KiB.
- Identity-bearing node/extract text: at most 65,536 Unicode characters and
  256 KiB of strict UTF-8. Other schema/runtime text bounds count Unicode
  characters; whole-artifact byte ceilings remain separate.
- Total adopted source bytes: 8 MiB.
- Query budget: 1,024 through 8,388,608 canonical UTF-8 bytes.
- Nodes: 1 through 4,096.
- Edges: 0 through 16,384.
- Traversal depth: 0 through 8.

Required nodes, provenance edges, and contradiction closure must fit every
bound. Otherwise no output is published.

## Failure and stop semantics

Fail closed for malformed/duplicate/non-finite/deep/oversized JSON; unsafe,
missing, duplicate, or mismatched IDs/references; unsafe paths, root escape,
links/reparse points, changing input; stale/missing/candidate-mismatched or
over-clearance required sources; prohibited adoption; required context over
budget; malformed self/duplicate edges or over-bound traversal; missing
provenance/authority/freshness; hidden contradiction; automatic
downgrade; nondeterministic ordering; summary-only protected authority; output
collision; ambiguous publication; or a need for an unapproved dependency,
network, hosted service, embedding/vector backend, SQLite, scheduler, or solver.
An omitted source sensitivity is canonicalized to `owner-private`; it is not
silently treated as public.

Any path outside the approved tracked set requires an exact minimal scope
amendment and a stop. Roadmap edits, Git mutations, and external actions are
separate approval boundaries.

## Implementation Plan

### Checkpoint 1 — contracts and canonical identities

Implement frozen domain values, injected ports/adapters, canonical envelopes,
strict loaders, all eight schemas, and runtime/schema parity. Add golden identity
and negative contract tests.

### Checkpoint 2 — indexing and selection

Implement bounded source observation, graph construction, provenance/freshness
metadata, required closure, BFS, identifiers, lexical ranking, budgets,
exclusions, contradictions, and exclusive output.

### Checkpoint 3 — snapshot, compare, compact, quality, and CLI

Implement snapshot re-observation and identity, ordered delta, deterministic
extractive compaction, host proposal validation, named quality report, all six
commands, synthetic fixtures, evaluation, and `M5-CONTEXT-INTEGRITY`.

Quality fields, without an aggregate:

- `required_reference_recall`
- `stale_required_count`
- `provenance_complete_count`
- `provenance_missing_count`
- `sensitivity_violation_count`
- `selected_context_bytes`
- `budget_bytes`
- `redundant_bytes`
- `selected_node_count`
- `excluded_node_count`
- `unresolved_contradiction_count`
- `traversal_truncated`

### Checkpoint 4 — documentation, regression, and review

Update English product documentation and CLI smoke. Run pytest, Ruff, strict
mypy, total/milestone coverage, offline CLI smoke, named validator, publication
and dependency audits, `pip check`, `git diff --check`, and path/privacy audits.
Perform a read-only scope, traceability, security/privacy, compatibility, test
quality, documentation, and complexity review.

## Validation and Acceptance

Golden canonicalization and selection vectors must agree on Windows and Linux,
Python 3.12 and 3.13. Focused tests cover the implemented contract boundaries,
source and candidate changes, expiry, path confinement, deterministic ordering,
identifier and ASCII/non-ASCII lexical input, sensitivity, contradictions,
required budget failure, immutable JSON re-observation, standalone Snapshot
integrity, output collision, and summary authority. The complete suite covers
shared filesystem and publication behavior. No claim is made that the focused
suite exhausts every numeric boundary, graph topology, link/reparse variant, or
platform combination; the Windows/Linux Python matrix remains a separate Gate.

Examples are synthetic English `public` data. Publication audits must prove that
parent state, owner content, absolute machine paths, credentials, and `.sdaqf/`
artifacts are absent.

## Rollback and Recovery

Before Git mutation all changes remain unstaged and reviewable. Outputs are
created exclusively. A failed operation removes only its verified temporary
file; it does not overwrite or delete an existing or ambiguously published
target. Tracked rollback is an exact approved edit, never blanket reset,
restore, stash, force, or history rewrite.

## Git and External Boundaries

After local verification, report exact paths, hashes, tests, and review findings
before requesting separate stage/commit approval. Push/PR, remote observation,
merge, tag, release, deployment, and repository settings each require their own
exact proposal where needed.

## Outcomes & Retrospective

The approved implementation, M5-RF1 through M5-RF7 remediation, M5-D5A, and
five independent-review remediation rounds are complete and unstaged. The
fifth review's publication-binding finding is closed in code, tests, the named
validator, and documentation. The local Windows candidate passes 85 focused M5
tests, 740 full tests with three explicit environment link skips, Ruff, strict
mypy, every coverage threshold, the M0-through-M5 CLI smoke, the executable
`M5-CONTEXT-INTEGRITY` validator, workspace/publication/dependency audits,
`pip check`, and whitespace checks. Git and remote mutation remain excluded.

A sixth independent re-review of newly frozen bytes, exact-candidate Git
finalization, Windows/Linux CI, and the private M6 handoff remain pending at
their separate boundaries.
