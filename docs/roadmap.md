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

## V1.0: Release-candidate readiness

Status: post-A7 reconciliation locally verified; new candidate awaiting commit
approval.

Set version `1.0.0rc1`, adopt Apache-2.0, define the target V1 public API and
compatibility/migration policy, preserve historical schemas, add the selected
license schema 1.1, and evaluate an exact offline publication-readiness
declaration. A successful local result is `LOCAL_READY`, not actual Gate G5.

Pre-reconciliation candidate
`97082edc6ccbfcea5dfcd745681f7db435515074` completed A6 through successful run
`30593521851` and all four required Windows/Linux Python 3.12/3.13 jobs. The
Owner-approved A7 visibility-change command was accepted with exit code `0`
and no output, but no independent post-A7 remote read has observed current
repository visibility.

The proposed public tag remains `v1.0.0-rc.1`. The tag and GitHub release have
not been created, private vulnerability reporting has not been enabled, and
actual Gate G5 remains `NOT_RUN`. Final `1.0.0` is a future new candidate.
