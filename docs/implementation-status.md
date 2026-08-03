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
| M5 Context Framework | Experimental | No | Current CI passes; final independent re-review is not recorded |
| M6 Multi-Agent Control Framework | Experimental | No | Current CI passes; final independent GO review is not recorded |
| M7 Mathematical Solver Framework | Experimental | No | Bounded local reference adapter; independent milestone GO and current CI |
| M8 Integrated Workflow | Planned | No | No implementation |

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
- The active M5 execution plan records its final independent re-review as
  pending.

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
- The active M6 execution plan records a tenth independent review as pending.

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

Planned only. The roadmap proposes a workflow that composes validated
requirements, context, scheduling, solver evidence, approvals, reviews,
quality gates, recovery, and handoff. No `workflow` CLI namespace or M8 runtime
is present today.

See [Roadmap](roadmap.md).
