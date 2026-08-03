# Changelog

All notable changes will be documented in this file.

## Unreleased

SDAQF `1.0.0rc1` was published on 2026-07-31 as the annotated tag and GitHub
prerelease `v1.0.0-rc.1`, targeting commit
`9f14e2287da3afc078db787e823765320b1e23ac`. The repository is public, GitHub
private vulnerability reporting is enabled, and the release has no attached
assets or package-registry publication. The M5-M7 entries below are later,
unreleased changes on `main`; they are not part of the tagged prerelease.

The GitHub release body was reconciled with the tracked publication record on
2026-08-03. It now records the published state and exact tagged candidate.

### Added

- M7 content-addressed Solver Registry, Request, Result, and Verification
  schema `1.0` contracts with exact M5 candidate/Context and M6 graph/task/Lease
  identities, exact-zero tolerance, bounded resource policy, and strict
  runtime/schema validation.
- A dependency-free deterministic finite-domain reference adapter covering two
  problem kinds, three profiles, five typed constraints, exact integer
  feasibility and optimization, and ten truthful Result dispositions.
- Independent witness, objective, bound, exhaustive-proof, claim, resource,
  adapter, license, provenance, sensitivity, and current-or-historical Lease
  verification. Only a verified Result satisfying the requested claim is
  adoptable.
- Exact M6 solver capability tokens, call/step reservation and settlement,
  paired Result/Verification Task Result adoption, semantic SQLite validation,
  and fresh-output recovery replay.
- Structurally complete optional external-CLI Registry evidence with exact Tool
  Registry, executable, input format, version matcher/observation,
  license/provenance, no-network, and fresh single-use dual-approval
  requirements. M7 deliberately does not execute it.
- Additive `solver registry validate`, `solver request validate`, `solver run`,
  and `solver verify` CLI paths; synthetic public artifacts; ten production
  evaluation cases without an aggregate score; M0-through-M7 smoke; and
  `M7-SOLVER-EVIDENCE` with at least 90 percent M7 critical branch coverage.
- M6 content-addressed Task Graph, Scheduler State, Lease, Mailbox Message,
  Scheduler Event, Budget Ledger, and Worktree Lease schema 1.0 contracts.
- A transactional standard-library SQLite scheduler with fenced leases,
  stable idempotency, strict current-fence result adoption, typed causal
  mailboxes, hash-chained events, atomic budgets, approval consumption,
  deterministic wait reports, and evidence-preserving fresh-output recovery.
- Exact approval actors and atomic dual approval, periodic portable heartbeat
  leases, scheduler-authored cancellation/worktree intents, result evidence
  verification, full integer budget settlement, exact SQLite projection
  reconciliation, and projection rebuilding from immutable evidence.
- Persisted approval-proposal identities across ticks, closed evidence and
  terminal predicate vocabularies, enforced review-target completion,
  history-derived exact current Lease/Worktree row sets, attempt-scoped
  settlement, and matching schema/runtime enforcement that concurrency cannot
  exceed the agent limit.
- Closed causal and event-transition vocabularies, expire-before-ingest Lease
  authority, exact dispatch-parent phase checks, semantic recovery replay,
  per-host capability isolation, atomic delayed-dispatch approval consumption,
  complete Worktree Lease lifecycle/reuse, and one typed durable wait-for
  projection shared by production status, CLI, and simulation.
- Total cause-dispatched replay for all 24 Scheduler Event causes, exact
  immutable scheduler-egress reconstruction, budget-before-approval admission,
  expiry-bound cancellation, durable stall reporting in simulation/evaluation,
  and schema/runtime parity for safe text and capability identity.
- Exact result-to-verification semantic replay, complete scheduler-egress
  envelope/causal/observed-worktree authority, an event-derived Budget Ledger
  reducer with exact intermediate snapshots and retry deltas, and same-Lease
  delayed worktree admission that preserves and consumes the original approval
  exactly once. `M6-SCHEDULER-SAFETY` now also exercises deliberate rehashed
  result, egress, and budget-history corruption through no-output recovery.
- Exact non-result cause replay for acknowledgement, heartbeat, cancellation,
  Worktree, expiry, readiness, approval, blocker, and Lease-history authority;
  one compatible primary adoption event for every immutable mailbox row; and
  independently rederived dispatch reservations, result-usage ceilings,
  wall-time deltas, and admission blockers. Recovery now rejects self-consistent
  rehashed policy reversals, orphan authority rows, and forged budget causes
  before creating output.
- Initialization-bound immutable Lease policy; whole-object provisional and
  active Lease reconstruction; one complete cause-derived Worktree history row;
  current-phase, primary-adopted same-Lease cancellation parents; and
  initialization-anchored nondecreasing wall-time replay. Missing, extra,
  moved, smaller, larger, or creation-drifted wall evidence and recurrent
  Lease/Worktree/cancellation forgeries now fail before commit or recovery
  publication.
- One shared live/replay Worktree-observation authority reducer now binds the
  exact `not_dispatched` phase, task assignment, causal request, latest
  requested/observed Worktree, and latest active Lease. Fully rehashed foreign
  paths, post-dispatch observations, and old or released Lease observations
  fail before fresh recovery publication.
- Non-result replay now centrally classifies every cause's complete Lease-
  history output: a nonterminal Worktree observation must emit zero Lease rows,
  while its terminal form retains one exact release. Every Lease also proves
  `expires_at = heartbeat_at + ttl`; a content-addressed observation-linked
  current row that live execution never emitted fails before recovery.
- Portable Task Graph path and text parity for Windows reserved/trailing-dot
  components, single-line secret-safe strings, and pre-resolution symlink,
  junction, and reparse-ancestor rejection.
- Additive `agents schedule`, `agents mailbox`, `agents recover`, and
  `agents simulate` CLI paths, ten real-state-machine offline scenarios,
  synthetic public evidence, M0-through-M6 CLI smoke, and
  `M6-SCHEDULER-SAFETY` with negative contract parity, deliberate corruption
  recovery, durable scenario assertions, and 90 percent critical coverage
  enforcement.
- M5 immutable content-addressed Context Manifest, Graph, Query, Selection,
  Snapshot, Compaction, host-summary proposal, and named quality contracts.
- Additive `context validate`, `index`, `select`, `snapshot`, `compare`, and
  `compact` CLI commands with bounded explicit roots and exclusive outputs.
- Deterministic required/graph/identifier/lexical retrieval, contradiction
  closure, canonical byte budgets, extractive compaction, eight schema 1.0
  files, synthetic public fixtures, seven evaluation scenarios, and
  `M5-CONTEXT-INTEGRITY`.
- Persisted-Snapshot Compaction reauthentication through explicit roots,
  canonical node source-identity recomputation, duplicate-source rejection,
  complete pre-I/O in-memory Snapshot/HostProposal validation, and exact
  source/contradiction metadata preservation. Final pre-publication candidate
  verification is bound to the validated Compaction being serialized.
- M0 Bootstrap Foundation repository structure.
- Offline-first Python CLI vertical slice.
- Initial deterministic domain models, schemas, samples, tests, and audits.
- Public documentation, Codex skills, GitHub templates, and cross-platform CI.
- M1 bounded Markdown specification ingestion and deterministic normalization.
- Source and downstream traceability, diagnostics, and versioned requirement
  baseline contracts.
- Structured Owner-approval-aware baseline comparison and the Gate G1
  Requirements Gate.
- Product Roadmap, living ExecPlan, Goal prompt, and Standard prompt generation.
- M1 negative, boundary, regression, and primary CLI test coverage.
- M2 versioned Agent and Tool Registries, deterministic budgeted role
  selection, native Subagent host contracts, safe fallbacks, isolated-write
  plans, structured results, and evidence-based disagreement resolution.
- Skill and template lifecycle validation, safe bounded tool probes, strict
  versioned single-execution approvals with provenance, expiry, and exact
  conditions, persistent atomic consumption claims, retry control, atomic
  checkpoint recovery, M2 schemas, samples, CLI commands, audits, and
  cross-platform smoke coverage.
- M3 versioned Claim-Evidence Ledger, atomic evidence addition, Gates G2 through
  G4, independent-review and exact finding-acceptance contracts, UI
  classification and recorded browser validation, local release audits,
  deterministic automated handoffs, schemas, samples, CLI commands, and
  negative, boundary, failure-injection, and regression tests.
- M4 representative non-UI, UI, and security-sensitive sample projects with
  expected normalized projections.
- Strict paired structured and ordinary-unstructured evaluation records,
  parity validation, non-compensating metrics, repeated-failure analysis,
  tracked results, schemas, documentation, CLI commands, and tests.
- Explicit Agent and Tool Registry 1.0-to-2.0 migration with conservative
  defaults, exclusive validated output, atomic single-use approval
  consumption, failure rollback, public policy, fixtures, CLI commands, and
  negative tests.
- Public contributor setup, development, testing, architecture, extension,
  security, evaluation, migration, and release-limit documentation.
- V1 target public API and `1.0.0rc1` version metadata.
- Apache-2.0 `LICENSE`, `NOTICE`, exact project-license metadata, and
  fail-closed selected-license auditing.
- Release-candidate schema 1.1 and offline public-release-candidate schema.
- Local `gate publication-readiness` with `LOCAL_READY`, explicit
  `publication_performed: false`, and actual Gate G5 `NOT_RUN`.
- Compatibility, migration, prerelease notes, support, contribution,
  maintenance, platform, and source-only artifact policies.

### Changed

- Hardened the pre-release M5 candidate after independent review: Selection
  replay, atomic contradiction closure, actual CandidateIdentity and provenance
  verification, structural authority checks, exact optional exclusions,
  downstream identity/sensitivity propagation, schema/runtime parity, and
  executable evaluation cases now fail closed at their trust boundaries.
- Re-observe immutable JSON at Index and Snapshot time, require a canonical
  specification in standalone Snapshots, recompute Snapshot and Compaction
  byte costs, align JSON Schema/runtime Unicode bounds, and return bounded CLI
  errors when Git candidate inspection cannot start.
- Authenticate persisted Snapshot sources again before Compaction, retain
  source/authority/sensitivity and exact contradiction IDs in extracts, and
  align ordinary Unicode text limits with JSON Schema character semantics.
- Template compatibility defaults now target public API line `1.0.0`.
- Historical release-candidate schema 1.0 remains unchanged and continues to
  represent only the unselected project-license state.
