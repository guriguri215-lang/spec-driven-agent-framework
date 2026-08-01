# Roadmap

## M0: Bootstrap Foundation

Status: implemented.

Deliver a safe local repository, CLI vertical slice, schemas, samples, skills,
quality gates, publication audits, and handoff material.

## M1: Requirements and Planning MVP

Status: implemented by the current milestone.

Implement specification ingestion, requirement normalization, acceptance
criteria, source traceability, change comparison, roadmap generation, execution
plans, prompts, Goal suitability, and a requirements baseline Gate. The M1
normalization contract is deterministic and bounded; it does not claim general
natural-language understanding.

## M2: Agent, Skill, and Tool Orchestration

Status: implemented by the current milestone.

Provide strict agent and tool registries, deterministic budgeted role
selection, native Subagent host contracts and safe fallback prompts,
read-parallel and isolated-write planning boundaries, logically independent
review, structured result and disagreement contracts, Skill and template
lifecycle validation, safe local tool probes, bounded retry, and atomic
checkpoint recovery. Worktree creation and integration remain caller-owned Git
operations.

## M3: Evidence, UI/UX, and Release QA

Status: implemented by the current milestone.

Add a strict claim-evidence ledger, non-compensating Gates G2 through G4,
manifest-based UI classification, bounded recorded host-browser validation,
security/dependency/license and release-candidate audits, and deterministic
automated handoffs. Browser launch remains a host capability and publication
remains Gate G5.

## M4: Public Beta Hardening

Status: implemented by the current milestone.

Validate multiple sample projects, expand platform coverage, run comparative
evaluations, add explicit schema migrations, and harden contributor
documentation. Candidate-bound cross-platform verification remains recorded
separately from implementation and may not be inferred from a prior commit.

## V1.0: Release-candidate publication

Status: `v1.0.0-rc.1` published; Actual Gate G5 passed.

Candidate `9f14e2287da3afc078db787e823765320b1e23ac` passed the required
Windows/Linux Python 3.12/3.13 exact-SHA matrix and was published through
annotated tag `v1.0.0-rc.1` as prerelease `SDAQF v1.0.0-rc.1`. The release has
no attached assets or package-registry publication and uses only
GitHub-provided source archives. The repository is public, private
vulnerability reporting is enabled, and the tag, release metadata, policy
files, and source archives were verified through bounded post-publication
observation.

This release remains for framework evaluators and advanced Codex users. It is
not production-ready. macOS remains `NOT_VERIFIED`, the comparison remains
authored and noncausal, and final `1.0.0` requires a new candidate and separate
approval.

## Post-RC architecture policy

M5 through M8 extend the framework additively:

- new documented CLI namespaces and new schema `1.0` contracts;
- preservation of every current schema and V1 CLI behavior;
- no new `sdaqf.__all__` export until the relevant milestone contract is
  stable;
- no major version unless an approved breaking change requires one;
- no mandatory network, hosted runtime, OpenAI API, Agents SDK, management UI,
  embedding service, vector database, or external solver;
- immutable content-addressed JSON artifacts for portable evidence and
  standard-library SQLite only for transactional scheduler state;
- deterministic policy, identity, approval, Gate, and transition decisions;
- untrusted treatment of model, agent, retrieved, compacted, tool, browser,
  and solver output;
- preservation of lifecycle Gates G0 through G5. New milestone validators do
  not renumber or reinterpret those Gates.

## M5: Context Framework

Status: Owner-approved implementation candidate validated locally; exact-candidate independent review, Windows/Linux CI, and Git finalization pending.

### Objective

Create a typed, provenance-bound context manifest and graph that can produce
reproducible context snapshots with explicit selection and exclusion reasons.

### Scope

- Typed context nodes and edges for specifications, requirements, decisions,
  design, source, tests, evidence, findings, tasks, handoffs, tool
  observations, and solver artifacts.
- Source digest, provenance, authority, freshness, sensitivity, budget, and
  candidate binding.
- Deterministic required-reference, graph, identifier, and lexical retrieval.
- Deterministic extractive compaction and source-linked unverified host summary
  proposals.
- Four sensitivity levels: `public`, `repository-private`, `owner-private`,
  and `secret-or-prohibited`. Unlabelled imports default to `owner-private`;
  derived context takes the highest source sensitivity with no automatic
  downgrade.
- Context validation, indexing, selection, snapshot validation, and snapshot
  comparison CLI contracts.
- Named context-quality measurements without an aggregate score.

### Exclusions

- Autonomous web crawling, ambient user-memory import, secret ingestion, and
  execution of retrieved text.
- Mandatory embeddings, vector retrieval, hosted models, or third-party
  runtime dependencies. Embeddings remain a future optional adapter.
- Lossy summary text as the sole authority for a Must, approval, security,
  disclosure, or data-loss decision.

### Dependencies

- Existing requirement, candidate, evidence, approval, and handoff identities.
- Approved content-addressed JSON and sensitivity policies.
- Injected filesystem, clock, and token-or-byte estimation boundaries.

### Risks

- Stale or contradictory context, private-data disclosure, hidden provenance,
  non-reproducible ranking, and compaction loss.
- Platform-dependent path or lexical ordering.

### Completion criteria

- Context Manifest, Graph, Query, Snapshot, and Compaction schemas and strict
  loaders pass runtime/schema parity.
- Required references cannot be evicted by budget or ranking.
- Freshness, contradiction, sensitivity, traversal, link, changing-input,
  malformed-input, and compaction blockers fail closed.
- Snapshot identities reproduce across Windows and Linux.
- Representative evaluation reports required-reference recall, stale-required
  items, provenance completeness, sensitivity violations, budget use, and
  redundant bytes without an aggregate score.
- Named local validator `M5-CONTEXT-INTEGRITY` passes.

### Stop conditions

- A required source lacks provenance, exceeds clearance, is stale, changes
  during adoption, or cannot fit within the mandatory context budget.
- Retrieval or compaction would require an unapproved dependency, network
  service, private read scope, or authority downgrade.

## M6: Multi-Agent Control Framework

Status: planned; depends on M5.

### Objective

Extend deterministic role planning into durable, resumable, host-agnostic
multi-agent execution control.

### Scope

- Validated task dependency DAG, transactional scheduler state, typed mailbox,
  budget ledger, event trail, cancellation, deadlock detection, and recovery.
- Content-addressed JSON artifacts plus standard-library SQLite as the
  canonical transactional task, event, lease, and budget store, with bounded
  deterministic JSON audit exports.
- At-least-once dispatch with stable idempotency keys, fenced leases, one
  current owner, and duplicate or late-result rejection. Exactly-once
  execution is not claimed.
- Agent host, scheduler store, and worktree host ports.
- SDAQF-owned validation, policy, state, budgets, and audit; host-owned
  Subagent or session dispatch.
- Host-controlled worktree creation and integration during M6. Any later
  managed-worktree adapter requires separate approval and cannot delete
  ambiguous state automatically.
- Deterministic local simulation of success, crash, timeout, disagreement,
  deadlock, budget exhaustion, and missing capabilities.

### Exclusions

- Mandatory hosted orchestration, nested Codex CLI execution, agent
  self-approval, force push, history rewrite, automatic publication, or
  destructive worktree cleanup.
- Automatic retry after an ambiguous external outcome.

### Dependencies

- Exact M5 Context Snapshots and sensitivity labels.
- Existing Agent and Tool Registries, worktree plans, results, approvals,
  checkpoints, evidence, and reviewer-separation rules.
- Injected clock, host, filesystem, process, and identity boundaries.

### Risks

- Duplicate dispatch, stale leases, split ownership, late results, dependency
  deadlock, budget drift, mailbox injection, crash corruption, and ambiguous
  cancellation.
- SQLite schema migration or filesystem behavior that differs across
  platforms.

### Completion criteria

- Task Graph, Scheduler State, Lease, Mailbox Message, Scheduler Event, Budget
  Ledger, and Worktree Lease schemas and strict loaders pass.
- Concurrent lease acquisition, fencing, expiry, deduplication, crash/restart,
  event integrity, cancellation, deadlock, and budget behavior fail closed.
- Candidate, context, path ownership, role, approval, and reviewer identities
  are revalidated before every protected transition.
- Deterministic simulation covers every terminal and recovery state.
- Named local validator `M6-SCHEDULER-SAFETY` passes.

### Stop conditions

- Exactly-once behavior, automatic ambiguous retry, scheduler-created
  approval, hidden host authority, or unsafe worktree cleanup would be
  required.
- State cannot be recovered without discarding or rewriting its audit trail.

## M7: Mathematical Computation and Solver Framework

Status: planned; depends on M5 identity conventions and M6 budget/event
semantics.

### Objective

Add one typed solver contract and registry for bounded deterministic local
feasibility, SAT/SMT-style reasoning, discrete optimization, and scheduling
where a solver is justified.

### Scope

- One discriminated typed request/result envelope with exact problem,
  candidate, task, adapter, resource, and evidence identities.
- Solver Registry, Solver Request, Solver Result, and Solver Verification
  contracts.
- A bounded standard-library finite-domain reference adapter for small
  deterministic problems.
- An optional local Z3 command-line adapter through the existing Tool Registry,
  subject to fresh provenance, license, executable, version, input-format,
  security, and approval review.
- Witness, objective, bound, proof-or-audit artifact, resource, and
  verification records.
- Deterministic witness re-evaluation before adoption.

### Exclusions

- Mandatory solver packages, hosted solvers, GPU or cloud services, network,
  arbitrary callbacks, eval, shell expressions, or raw agent-authored solver
  language.
- Treating `UNKNOWN`, timeout, backend agreement, or a feasible witness as
  proof of unsatisfiability or optimality.
- Bundling every solver family named in the specification.

### Dependencies

- Existing Tool Registry process safety and approval consumption.
- M5 content, sensitivity, and artifact identities.
- M6 task, budget, event, lease, and recovery semantics.

### Risks

- Model injection, resource exhaustion, malformed or malicious output,
  floating-point ambiguity, invalid witness, unsupported theory, backend
  disagreement, license drift, and temporary-artifact races.

### Completion criteria

- Known satisfiable, unsatisfiable, feasible, infeasible, optimal, bounded,
  timeout, unavailable, and error fixtures behave truthfully.
- Typed serialization rejects arbitrary solver text and unsafe execution.
- Witness, objective, bound, tolerance, proof disposition, resource, version,
  license, and provenance checks fail closed.
- Reference and optional external adapters agree on bounded fixtures only as
  corroboration; deterministic verification remains authoritative.
- Solver tasks obey M6 leases, budgets, context identity, and approval stops.
- Named local validator `M7-SOLVER-EVIDENCE` passes.

### Stop conditions

- A hard requirement would depend on `UNKNOWN`, timeout, an unverified witness,
  an unavailable optional backend, or an unapproved dependency or license.
- Solver output would be allowed to grant approval, widen policy, or perform an
  external effect.

## M8: Integrated Vibe-Coding Framework

Status: planned; depends on completed M5 through M7 contracts.

### Objective

Provide one explainable planning and execution loop that composes validated
specification state, reproducible context, multi-agent control, optional
solver decisions, approvals, evidence, review, Gates, recovery, and handoff.

### Scope

- Development Intent, Integrated Plan, Workflow State, Workflow Event, and
  Workflow Outcome contracts.
- A side-effect-free planner, exact plan explanation, deterministic simulator,
  resumable workflow runtime, status, and handoff.
- Deterministic plan envelope, policy, identity, approval stops, and completion
  predicates.
- Host proposals for task decomposition, context queries, roles, solver
  formulations, implementation, and review that remain untrusted until
  validated.
- Revalidation of policy and approval immediately before every protected
  effect.
- Named end-to-end measurements for requirements, context, scheduling, solver,
  evidence, handoff, recovery, and available cost without an aggregate score.

### Exclusions

- Unconstrained autonomous agents, hidden memory, ambient machine control,
  silent network access, automatic credential use, destructive cleanup,
  publication, deployment, billing, or production release.
- Mandatory OpenAI API, Agents SDK, hosted service, management UI, vector
  database, or external solver. Ports are designed in M5-M8; optional
  separately packaged adapters may be considered only after M8 contracts are
  stable.
- Direct model authority over policy, approval, Gate, candidate identity,
  solver truth, or completion.

### Dependencies

- Approved and verified M5 Context Snapshot contracts.
- Approved and verified M6 scheduler, host, lease, mailbox, budget, and event
  contracts.
- Approved and verified M7 solver contracts and verification semantics.
- Existing requirements, approval, evidence, review, Gate, and handoff
  contracts.

### Risks

- Scope expansion hidden by convenient intent, stale cross-contract identity,
  policy bypass, partial external effects, misleading completion, opaque
  planner decisions, and unbounded autonomy.

### Completion criteria

- `workflow plan` is deterministic and side-effect-free; `workflow explain`
  reports every selection, exclusion, uncertainty, budget, and approval
  reason.
- Runtime advances only through validated transitions and blocks at every
  unapproved protected or external effect.
- Stale context, candidate, lease, solver, approval, evidence, or review state
  rejects resume.
- End-to-end offline non-UI, UI, and approval/security-sensitive projects pass
  plan, simulate, run, recovery, review, Gate, and handoff validation.
- Windows/Linux Python 3.12/3.13 exact-candidate evidence and independent
  review have no unresolved Critical, High, or Medium finding.
- Named local validator `M8-WORKFLOW-INTEGRATION` passes.

### Stop conditions

- Integration would bypass a subsystem validator, reinterpret an existing
  schema in place, infer approval from intent, or convert an ambiguous result
  into success.
- A mandatory hosted runtime, vendor SDK, management UI, network, dependency,
  credential, charge, or external publication is required without its own
  product and exact action approval.

## Sequencing and change control

M5 establishes shared context and artifact identities. M6 consumes exact M5
snapshots. M7 reuses M5 identities and M6 budgets and events. M8 composes the
three frameworks without merging their storage formats or bypassing their
validators.

Every milestone requires its own living ExecPlan, exact implementation scope,
negative tests, complete Release Contract regression, independent read-only
review, candidate identity, and separate Git or external-action approvals.
Roadmap approval does not authorize implementation, dependencies, schema
publication, staging, commit, push, release, deployment, hosted access, or
repository settings.
