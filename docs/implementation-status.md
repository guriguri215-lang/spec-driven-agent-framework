# Implementation Status

This document separates code that exists from code that is independently
verified, released, or planned. The current implementation is the source of
truth; milestone names and target architecture do not by themselves establish
working behavior.

## Status vocabulary

- **Implemented**: production code, public contracts, and automated tests exist.
- **Experimental**: implemented and tested within documented bounds, but not a
  stable or production-ready interface.
- **Planned**: roadmap scope without a current implementation.
- **Not verified**: implementation may exist, but the named environment or
  independent validation has not been observed for the current candidate.

## Milestone summary

| Milestone | State | Released in `v1.0.0-rc.1` | Current validation boundary |
|---|---|---:|---|
| M0 Bootstrap Foundation | Implemented | Yes | Automated tests and current CI |
| M1 Requirements and Planning | Implemented | Yes | Automated tests and current CI |
| M2 Agent, Skill, and Tool Orchestration | Implemented | Yes | Plans roles and tool calls; does not dispatch agents |
| M3 Evidence, UI, and Release QA | Implemented | Yes | Validates host observations; does not launch a browser or publish |
| M4 Public Beta Hardening | Implemented | Yes | Authored evaluation is nonempirical and noncausal |
| M5 Context Framework | Experimental | No | Latest disposition is GO for the reviewed repository state; historical NO-GO remains recorded; release remains separately gated |
| M6 Multi-Agent Control Framework | Experimental | No | Latest disposition is GO for the current status-publication candidate; historical NO-GO and later pre-publication stop remain recorded; exact PR CI remains separately gated |
| M7 Mathematical Solver Framework | Experimental | No | Bounded local reference adapter; independent milestone GO and current CI |
| M8 Integrated Workflow | Experimental | No | Latest successor lifecycle compatibility review is GO with F1-F11 maintained and zero unresolved scope findings; the reviewed M8 state was merged to `main`, whose exact-triggering-SHA Actions run `31497539609` passed; release remains separately gated |

## M0: bootstrap and repository safety

Implemented:

- Safe workspace and Git-boundary checks.
- A standard-library Python package with no runtime dependencies.
- `doctor`, `init`, `validate`, `status`, and `goal-template` commands.
- Separate capability states for available, unavailable, permission-denied,
  and intentionally untested tools.
- Project, requirement, evidence, approval, execution, handoff, tool, and agent
  schemas with examples.
- Cross-platform CI, linting, strict type checks, coverage thresholds, CLI
  smoke tests, and publication audits.

## M1: requirements and planning

Implemented:

- Bounded UTF-8 Markdown ingestion with content and source metadata.
- Deterministic requirement types, priorities, identifiers, acceptance
  criteria, verification methods, trace fields, and diagnostics.
- Explicit ambiguity, contradiction, duplicate, missing-assumption, and
  unverifiable-language reporting.
- Approval-aware baseline comparison and Gate G1 checks.
- Product roadmap, execution-plan, Goal-prompt, and Standard-prompt generation.

Limit: the normalizer is a deterministic bounded parser; it does not claim
general natural-language understanding.

## M2: orchestration contracts

Implemented:

- Strict versioned Agent and Tool Registries.
- Deterministic role selection by problem type, scale, risk, and parallelism.
- Read-only parallel plans and isolated-write plans with non-overlapping path
  ownership.
- Logical implementer/reviewer separation, structured results, and
  evidence-based disagreement resolution.
- Skill/template lifecycle validation, safe process probes, exact approvals,
  bounded retry, and atomic checkpoints.

Limit: the package returns assignments, prompts, and tool plans. It does not
launch a nested Codex process or create/integrate Git worktrees.

## M3: evidence and release quality

Implemented:

- A bounded Claim-Evidence Ledger and atomic evidence addition.
- Non-compensating implementation, independent-review, UI-observation, and
  local release-candidate gates.
- Candidate-bound installation and publication audits.
- Deterministic handoff creation and resume mismatch detection.

Limit: browser execution and publication are host responsibilities. Local
publication readiness is not authorization for a remote action.

## M4: public-beta hardening

Implemented:

- Representative non-UI, UI, and security-sensitive evaluation fixtures.
- Strict paired structured/unstructured evaluation records.
- Explicit Agent and Tool Registry 1.0-to-2.0 migration.
- Contributor, migration, architecture, security, testing, and release-limit
  documentation.

Limit: the tracked comparison is an authored scenario. It is not blinded,
randomized, independently replicated, statistically powered, cost-comparable,
or causal.

## M5: context framework

Experimentally implemented:

- Content-addressed Manifest, Graph, Query, Selection, Snapshot, Compaction,
  host-summary proposal, and quality-report contracts.
- Explicit provenance, authority, freshness, sensitivity, roots, source
  re-observation, contradiction closure, and byte budgets.
- Deterministic graph, identifier, and lexical retrieval plus extractive
  compaction.

Limits:

- No web crawling, ambient memory import, embeddings, vector database, or
  hosted model is required or implemented.
- Host summaries are untrusted proposals and cannot become sole authority for
  protected decisions.
- The historical 2026-08-10 final independent compatibility re-review remains recorded
  NO-GO. Snapshot publication now revalidates the CandidateIdentity on the
  validated Snapshot being serialized, and identifier-only ranking plus its
  published rank share one authoritative graph distance without changing
  ordering, budget, or replay.
- The two findings are remediated. The latest M5 disposition is GO for the
  reviewed repository state. The earlier 87 focused M5 tests and
  `M5-CONTEXT-INTEGRITY` pass remain separate supporting evidence; no validation
  count or review-evidence detail is added for the latest GO. The reviewed state
  was later merged to `main`, whose exact-triggering-SHA Actions run
  `31497539609` passed the full matrix.

See [Context Framework](context-framework.md).

## M6: multi-agent control framework

Experimentally implemented:

- Content-addressed task, state, lease, mailbox, event, budget, and worktree
  contracts.
- A standard-library SQLite scheduler with fencing, recovery, idempotent host
  intents, typed mailboxes, explicit budgets, and causal audit history.
- Ten deterministic offline simulations through the real state machine.

Limits:

- Dispatch, process execution, and worktree operations remain host-owned.
- Delivery is at-least-once; exactly-once execution is not claimed.
- The historical 2026-08-10 final independent compatibility review remains recorded
  NO-GO. Workflow Epoch Event Schema now enforces receipt type/ID-prefix and
  artifact-head ID/path-pair correlations already enforced by runtime parsing;
  SQLite live, replay, migration, and recovery meanings are unchanged.
- A later pre-publication review stopped with one separate Medium finding: eight
  pattern-constrained identifier and digest fields accepted non-string values
  in public Schema while runtime parsing rejected them. The five-file
  remediation makes every field explicitly string-only and adds matching
  32-case public-test and named-validator parity matrices. Runtime semantics,
  schema versions, samples, and evaluation fixtures remain unchanged.
- The 65-test public-contract selection, 145-test related M6 selection, and
  `M6-SCHEDULER-SAFETY` pass. Three fresh independent reviewers ACCEPT the
  remediated state with zero unresolved Critical, High, or Medium finding. The
  latest M6 disposition is GO for the current status-publication candidate.
  Base `main` exact-triggering-SHA CI passed as Actions run `31497539609`; exact
  PR CI for this change is enforced separately before Goal completion.

See [Multi-Agent Control Framework](multi-agent-control-framework.md).

## M7: mathematical solver framework

Experimentally implemented:

- Content-addressed Solver Registry, Request, Result, and Verification
  contracts.
- Two bounded finite-domain problem kinds, three profiles, five constraint
  kinds, exact integer arithmetic, and canonical ordering.
- A deterministic dependency-free reference adapter and independent witness,
  objective, bound, resource, provenance, and lease verification.
- M6 capability reservation and settlement integration.

Limits:

- The reference adapter uses bounded enumeration and is not a general SAT,
  SMT, continuous, or large-scale optimization engine.
- Optional external CLI adapters can be described but are not executed.
- A feasible witness, timeout, unknown result, or backend agreement is not
  treated as proof of optimality or unsatisfiability.

The sixth-remediation M7 candidate received an independent GO review with zero
findings before finalization. Current `main` also passes the cross-platform CI
matrix. See [Mathematical Solver Framework](mathematical-solver-framework.md).

## M8: integrated workflow

Experimentally implemented:

- Five strict content-addressed Development Intent, Integrated Plan, Workflow
  State, Workflow Event, and Workflow Outcome contracts.
- A side-effect-free deterministic planner and exact explainer that invoke
  native requirement, Context, Registry, scheduler, and solver validators.
- One-tick resumable runtime projections over the existing M6 SQLite store,
  immediate protected-effect revalidation, typed intents without dispatch,
  fresh-output recovery, ambiguity preservation, and truthful Outcomes.
- Four completion profiles composing existing G1-G4 and Automated Handoff,
  plus twelve fixed-clock offline simulations and nine separate measurement
  groups.

Limits:

- The core does not launch an agent, host, worktree, browser, real UI, process,
  network call, hosted adapter, or external solver.
- Workflow JSON is an immutable integration read model, not another scheduler,
  approval, evidence, review, Gate, solver, candidate, or handoff authority.
- The earlier round-three independent review accepted F1 through F11 but
  retained an overall NO-GO because successor Plans lost predecessor scheduler
  authority on resume, status, recovery, and Python terminal-observation
  finalization.
- The follow-up remediation propagates that exact optional authority without
  changing schema, artifact identity, or transaction boundaries. The latest
  independent successor lifecycle compatibility review returned GO for the
  current local candidate, maintained every F1-through-F11 ACCEPT result, and
  left zero unresolved findings within its scope.
- That review records PASS for the 28-test compatibility selection, 120-test
  complete M8 selection, round-three 9-test selection, Ruff, strict mypy,
  M5-through-M8 validators, and M0-through-M8 CLI smoke. It did not rerun full
  pytest or coverage.
- The latest GO supersedes the earlier M8 overall NO-GO for this local candidate
  only. M8 remains Experimental and unreleased; release GO, production
  readiness, commit, push, and exact-SHA remote CI are not claimed. That M8
  review did not decide M5 or M6. Their historical later final NO-GO reviews
  remain recorded; the latest M5 and M6 dispositions are now GO.
  None of these dispositions revises the M7 or M8 disposition.

The current dispositions are independent: M5 GO, M6 GO, M7 GO, and M8
successor lifecycle GO.

See [Integrated Vibe-Coding Framework](integrated-vibe-coding-framework.md).
