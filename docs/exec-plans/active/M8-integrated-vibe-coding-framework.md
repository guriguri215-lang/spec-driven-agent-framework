# M8 Integrated Vibe-Coding Framework

This living ExecPlan follows `PLANS.md`. It records the approved local M8
implementation against baseline
`9d41ca0c71947a060d9a900c3abc9a0be11d057a`. The accepted M7 commit
`82611e9909bded39291465b8c6101259c3d4200c` remains an ancestor through the M7
handoff. This plan does not authorize dependency, hosted-adapter, network, Git,
review-dispatch, publication, credential, charge, deployment, cleanup, or
repository-setting actions.

## Purpose and big picture

M8 provides an offline, deterministic integration boundary for a vibe-coding
request without making a model or prompt authoritative. A user supplies a
strict Development Intent. SDAQF validates its exact native references, creates
a side-effect-free Integrated Plan, explains every deterministic decision,
advances the existing M6 scheduler by at most one tick, records immutable
Workflow Events and States, supports evidence-preserving recovery, and derives
a truthful Workflow Outcome.

The observable result is an additive `workflow` CLI, five schema `1.0`
contracts and examples, a fixed-clock twelve-scenario simulator, the named
`M8-WORKFLOW-INTEGRATION` validator, focused regression coverage, CI coverage
enforcement, and truthful documentation. It never dispatches a host or
executes its own generated action.

## Exact contract

The five artifacts are Development Intent, Integrated Plan, Workflow State,
Workflow Event, and Workflow Outcome. Each has a strict four-field envelope,
full content SHA-256 identity, M5 canonical JSON, bounded size, exact schema
version `1.0`, and highest-level M5 sensitivity propagation. Development
Intent is untrusted scope input and contains no approval grant.

The Plan references and revalidates M1 requirements, M5 Context, M2 Registry
and orchestration inputs through M6, M6 Task Graph, optional M7 Solver Requests,
and existing evidence/review/Gate/handoff observation slots. It never embeds a
replacement authority. Candidate or reference drift rejects planning or
resume; candidate changes require a predecessor-linked new epoch.

Plan derivation is pure; the public Plan command authenticates M6 v2 and
reserves/confirms the exclusive Plan publication. Explanation independently recomputes selection, exclusion,
uncertainty, budget, approval, evidence, Gate, and completion reasons from a
closed vocabulary. Runtime publishes Event then State exclusively and returns
typed host intents without dispatch. Recovery creates fresh artifacts and
never edits its sources. Protected effects require immediate native policy,
Lease, fence, idempotency, budget, actor, and exact approval revalidation.
Ambiguous effects remain blocked and are never automatically retried.

Completion profiles are plan-only, implementation-verified,
independent-review-accepted, and release-candidate-ready. They compose G1-G4
and Automated Handoff. Outcome can report
completed, blocked, rejected, or superseded, but cannot upgrade any native
truth. Simulation reports exactly 52 measurements under requirements, context,
scheduling, solver, evidence, handoff, recovery, approval, and
`available_cost` and has no aggregate score. The validator re-resolves them
independently from native evidence.

## Dependencies, risks, and assumptions

M8 depends on the completed M1-M7 public contracts and their strict loaders.
The M6 standard-library SQLite v2 database stays the sole mutable workflow
epoch authority. M6-only v1 remains supported and explicit migration is
copy-on-write. The runtime dependency list stays empty and the stable top-level
`sdaqf.__all__` stays unchanged.

Principal risks are authority laundering from intent or model prose, stale
cross-contract identity, Context or candidate drift, duplicated or ambiguous
protected effects, a false cross-store transaction claim, false completion,
UI or hosted-runtime overclaim, secret leakage, and allowlist expansion. Exact
reference replay, fail-closed validation, Event-first/State-second publication,
no ambiguous-effect retry, native Gate/handoff predicates, public synthetic
fixtures, and exact changed-path audit mitigate these risks.

The implementation baseline was independently rechecked before the first
tracked edit: local HEAD and local `origin/main` matched, the index and
worktree were clean, M7 remained the exact 45-path ancestor, and all six
private M7 report hashes matched. No network observation was performed.

## Plan of work

1. Reverify the approved M8-D1 through M8-D8 record, the Owner-approved
   remediation record and exact 74-path union, baseline, and public contracts.
2. Freeze the five artifact types, identities, bounds, references, statuses,
   reason codes, protected-effect rules, completion profiles, and schemas.
3. Implement strict domain values, loaders, native reference validation,
   injected clock and immutable-store ports, and standard-library adapters.
4. Implement pure deterministic planning and independently recomputed
   explanation.
5. Implement one-tick transitions, Event/State publication, resume, protected
   effect revalidation, ambiguity, recovery, Outcome, Gate, and handoff
   composition while preserving native stores and identities.
6. Add the fixed-clock twelve-scenario simulator, five public examples,
   evaluation evidence, CLI namespace, named validator, focused tests, smoke,
   CI coverage Gate, and truthful documentation.
7. Run focused and full local validation, freeze the exact candidate evidence,
   and stop before a separately approved independent review.
8. After a later accepted review, stop again before separately approved Git
   and external actions.

## Progress

- [x] (2026-08-04) Completed bounded offline discovery and recorded the exact
  M8-D1 through M8-D8 decision proposal and 51-path allowlist privately.
- [x] (2026-08-04) Received explicit Owner approval for all recommended M8-D1
  through M8-D8 values and tracked implementation within only the 51 paths.
- [x] (2026-08-04) Reverified the local baseline, M7 ancestry/delta, clean
  index/worktree, local tracking ref, and six exact private M7 evidence hashes.
- [x] (2026-08-04) Implemented five typed immutable contracts and schemas,
  native reference validation, pure planning/explanation, runtime, resume,
  recovery, Outcome, simulation, ports, local adapters, and the additive CLI.
- [x] (2026-08-04) Added five public examples, twelve evaluation cases, focused
  tests, M0-through-M8 smoke coverage, CI enforcement, and the named validator.
- [x] (2026-08-04) Passed 48 focused M8 tests for the initial candidate, strict typing over 175 files,
  Ruff, and `M8-WORKFLOW-INTEGRATION`, including the M5, M6, and M7 named
  validators.
- [x] (2026-08-04) Completed the full local Release Contract after recovery
  hardening. Ordinary and coverage runs each passed 1,160 tests with four
  explicit Windows link-capability skips. Total/M1/M2/M3/M4/M5/M6/M7/M8
  branch coverage was 90/94/90/91/92/83/90/91/93 percent. M0-through-M8 CLI
  smoke, evaluation reproduction, workspace/publication/dependency audits,
  `pip check`, and the exact 51-path scope check passed with zero staged paths.
- [x] (2026-08-04) Froze the initial exact allowlist hashes and ordinal candidate
  fingerprint in the private local implementation report.
- [x] (2026-08-05) Completed the separately approved independent read-only
  review of the initial candidate. It returned NO-GO with one Critical, seven
  High, four Medium, and three Low findings.
- [x] (2026-08-05) Completed the separately approved local remediation within
  the same 51 paths. Focused M8 tests now pass 55 tests; ordinary and coverage
  runs each pass 1,167 tests with the same four explicit link-capability skips.
  Total/M1/M2/M3/M4/M5/M6/M7/M8 branch coverage is
  90/94/90/91/92/83/90/91/90 percent. Ruff, strict mypy over 175 files, all
  four named validators, M0-through-M8 CLI smoke, audits, and `pip check` pass.
- [x] (2026-08-08) Completed the Owner-approved local remediation of the later
  independent read-only review's five High and three Medium findings, still
  within the same 51 paths. Event/State semantic replay, exact predecessor
  adoption and supersession, independent G3 scope, native UI-backed G4,
  Event-first Outcome closure, real-contract simulation, native measurement
  derivation, and the `workflow/` runtime-private boundary now have direct
  positive and negative regressions.
- [x] (2026-08-08) Revalidated the latest candidate: 65 focused M8 tests and
  1,177 full tests pass with four explicit Windows link-capability skips;
  total and M8 critical branch coverage are 90.02 and 90.08 percent. The 28
  changed Python files pass formatter and Ruff checks, strict mypy passes over
  175 files, all four named validators pass, M0-through-M8 CLI smoke passes,
  and the exact scope remains 51/51 with zero staged or outside paths.
- [x] (2026-08-08) The next independent read-only review superseded the prior
  validation claim by reporting Critical 1, High 4, Medium 1, and Low 1. Those
  counts and the seven findings are the authority for the current remediation;
  earlier passing logs are supporting evidence only.
- [x] (2026-08-09) A later independent read-only acceptance review superseded
  that disposition and returned NO-GO with 1 Critical, 8 High, and 2 Medium
  findings. Those eleven findings are the current review authority; all prior
  passing logs remain supporting evidence only.
- [x] (2026-08-09) Owner approved the second remediation round for F1 through
  F11, the pre-release 1.0 schema corrections, no grandfathering, and the
  bounded path scope. Local implementation does not constitute independent
  acceptance.
- [x] (2026-08-08) Added RED-first regressions for forged closure, terminal
  resume/recovery/supersession/republication, arbitrary workflow source, path
  case differences and collisions, contradictory reviews, invalid orphan
  recovery, disconnected simulation execution, and unavailable measurement.
- [x] (2026-08-08) Implemented native Event/State replay and predecessor-history
  binding, non-circular closure-terminal Outcome publication, terminal-state
  enforcement, one case-normalized Candidate/G3/G4 publication set, closed
  generated-runtime classification, non-compensating observation aggregation,
  same-execution simulation, null unavailable measurements, and source/trace
  validator checks within the approved paths.
- [x] (2026-08-09) Completed the third local remediation round for the six
  still-open findings F1, F2, F3, F5, F8, and F11. Publication now preserves a
  store-wide observation through the final pre-open revalidation, exact Plan
  and terminal retries reuse confirmed receipts, terminal retries preserve the
  reservation timestamp, predecessor scheduler state reaches plan, explain,
  simulate, and run, and independent measurements replay M6 authority.
- [x] (2026-08-10) Recorded the independent round-three review: F1 through F11
  are ACCEPT, but the overall disposition remains NO-GO because successor
  resume, status, recovery, and Python terminal-observation finalization could
  not receive the predecessor scheduler database after the first run.
- [x] (2026-08-10) Implemented the bounded lifecycle compatibility remediation.
  Runtime resume, status, recovery, and terminal-observation finalization now
  accept and propagate the same optional predecessor authority as Plan replay;
  CLI resume, status, and recover expose the matching flag. Existing Planner
  exact-presence, database-identity, receipt, attestation, Candidate, terminal,
  and recovery boundaries are unchanged.
- [x] (2026-08-10) Completed the independent successor lifecycle compatibility
  review. It returned GO for the current local candidate, maintained every
  F1-through-F11 ACCEPT result, confirmed predecessor scheduler state
  propagation after the first successor run, and left zero unresolved findings
  within scope. This supersedes the earlier overall NO-GO for this candidate
  only; it is not release GO or production readiness.

### Current review and remediation verification

This section preserves the earlier round-three NO-GO and records the later
successor lifecycle remediation and independent review. The latest independent
review returned GO for the current local candidate, maintained F1 through F11,
and left zero unresolved findings within its scope. It supersedes the earlier
overall NO-GO for this candidate only. It does not claim release GO, production
readiness, commit, push, exact-SHA remote CI, or other Git publication. Earlier
results remain historical or supporting evidence for their exact candidates.

- [x] (2026-08-09) Reconfirmed unconditional approval of OD-1 through OD-8,
  the no-external-consumer compatibility decision, and the exact 74-path union
  before implementation. Existing Owner records and parent `state/` remained
  unchanged.
- [x] (2026-08-09) Implemented M6 v2 epoch/replay/receipt authority,
  terminal reserve/confirm and same-request recovery, one pinned Git-plus-M6
  publication observation, complete predecessor Outcome re-derivation, the
  exact CLI amendment, and real Outcome-backed D7 simulation.
- [x] (2026-08-09) The primary focused M6/M8 selection passes 246 tests with
  one explicit Windows directory-symlink capability skip in 484.07 seconds.
  The M6-owned selection passes 161 with the same skip; the M8 core-owned
  selection passes 59; and the D7-owned selection passes 9.
- [x] (2026-08-09) `M8-WORKFLOW-INTEGRATION` exits zero and reports PASS for
  M5, M6 SQLite v1/v2, M7, and M8. Its independent resolver reproduces all
  twelve exact Outcome/terminal-State dispositions and blockers, all three
  fixture bundles, and all nine groups/52 measurements.
- [x] (2026-08-09) Ruff and strict mypy pass the 43 approved Python targets.
  The final scope audit finds 64 changed paths, all inside the exact 74-path
  union, with zero parent `state/` changes.
- [x] (2026-08-09) The round-three regression selection passes 9 tests. Ruff
  passes, strict mypy passes 177 source files, all M5 through M8 named
  validators pass, and the M0-through-M8 CLI smoke passes.
- [x] (2026-08-09) The final full pytest run passes 1,241 tests with four
  explicit Windows link-capability skips in 865.60 seconds. Total and
  M1/M2/M3/M4/M5/M6/M7/M8 coverage are
  90/94/90/91/92/83/90/91/90 percent and every configured threshold passes.
  The Windows validation process used an ignored task-local Git wrapper only
  to reconcile sandbox ownership with hard-link publication; it changed no
  global, local, or repository Git configuration.
- [x] (2026-08-10) The successor lifecycle focused suite, CLI propagation, and
  public parser-contract selection pass 28 tests. Each real successor positive
  path has an old-code-killing regression, and the negative selection covers
  missing/extra authority, foreign, same, alias, and stale databases.
- [x] (2026-08-10) The complete M8 selection passes 120 tests with the exact
  project-default short ignored basetemp; the round-three transaction, retry,
  attestation, measurement, and receipt selection passes 9 tests. The first
  non-default longer basetemp run passed 114 tests and hit six Windows
  path-length setup failures; the exact-default rerun supersedes that
  non-evidentiary result.
- [x] (2026-08-10) Whole-project Ruff passes and strict mypy passes 178 source
  files. M5, M6, M7, and M8 named validators pass, and offline M0-through-M8
  CLI smoke passes. The smoke used an ignored task-local Git wrapper with an
  invocation-local exact `safe.directory` override only; no global, local, or
  repository Git configuration changed.
- [x] (2026-08-10) The independent successor lifecycle review did not rerun full
  pytest or coverage. The 28-test focused selection, 120-test complete M8
  selection, 9-test round-three selection, Ruff, strict mypy, M5-through-M8
  validators, and M0-through-M8 CLI smoke are PASS. The 2026-08-09 full and
  coverage run remains supporting evidence for its predecessor candidate.
- [x] (2026-08-10) No hash list or candidate fingerprint was created for this
  remediation. Publication audits and remote CI were not requested and are not
  claimed.
- [x] (2026-08-10) The fresh independent read-only successor lifecycle review
  returned GO with zero unresolved scope findings and superseded the earlier
  round-three overall NO-GO for the current local candidate.
- [ ] Obtain separate approvals before staging, commit, push, PR, merge, tag,
  release, exact-SHA remote observation, or any other external action.

## Exact additive public interfaces

The CLI commands are `workflow validate`, `plan`, `explain`, `simulate`, `run`,
`resume`, `supersede`, `status`, `recover`, and `outcome` with the signatures
documented in `docs/integrated-vibe-coding-framework.md`. The public schemas are
`development-intent.schema.json`, `integrated-plan.schema.json`,
`workflow-state.schema.json`, `workflow-event.schema.json`, and
`workflow-outcome.schema.json`.

New ports are limited to `WorkflowClock` and `WorkflowArtifactStorePort`. The
only new adapters are a system clock and an exclusive bounded immutable JSON
store. M6 retains host/worktree and scheduler ownership; M7 retains solver
ownership; M3 retains evidence, review, Gate, and handoff ownership.

## Checkpoints and validation

Run from the repository root without dependency or network operations:

```text
python scripts/run_local_gate.py pytest tests/test_m8_successor_lifecycle.py tests/test_m8_workflow_contracts.py tests/test_m8_workflow_planner.py tests/test_m8_workflow_explainer.py tests/test_m8_workflow_runtime.py tests/test_m8_workflow_recovery.py tests/test_m8_workflow_simulation.py tests/test_m8_workflow_security.py tests/test_m8_workflow_gates.py tests/test_m8_workflow_outcome.py tests/test_m8_public_contracts.py tests/test_m8_cli.py
python scripts/run_local_gate.py pytest
python scripts/run_local_gate.py coverage
python scripts/run_local_gate.py ruff
python scripts/run_local_gate.py mypy
python scripts/run_local_gate.py script scripts/validate_m5_context.py
python scripts/run_local_gate.py script scripts/validate_m6_scheduler.py
python scripts/run_local_gate.py script scripts/validate_m7_solver.py
python scripts/run_local_gate.py script scripts/validate_m8_workflow.py
python scripts/run_local_gate.py script scripts/run_cli_smoke.py
python scripts/run_local_gate.py evaluation
python scripts/run_local_gate.py workspace
python scripts/run_local_gate.py publication
python scripts/run_local_gate.py dependencies
python scripts/run_local_gate.py pip-check
git diff --check
```

The final local report must record test counts and skips, strict typing and
lint, all requested validators and CLI smoke, changed paths, unresolved
findings, and the before/after HEAD, worktree, and index. This remediation does
not create a hash list or candidate fingerprint. Local evidence is not remote
exact-SHA CI evidence.

## Stop conditions

Stop if any path outside the approved exact 74-path union is needed; an existing M1-M7
authority, store, identity, migration, approval, Gate, candidate, evidence,
review, completion, or handoff meaning would need replacement; a dependency,
network, hosted adapter, external solver, real UI, credential, charge,
deployment, publication, or host/worktree action becomes necessary; native
evidence cannot be reproduced; or a protected effect is stale or ambiguous.

Also stop before independent-review dispatch, destructive cleanup, staging,
commit, push, PR, merge, tag, release, remote CI observation, deployment,
publication, charge, credential use, or repository-setting change unless that
exact later action has separate Owner approval.

## Surprises and discoveries

- The correct M8 baseline includes five later M7 publication/CI documentation
  commits. M7 is therefore an exact accepted ancestor, not current HEAD.
- M6 already provides the mutable scheduler, dispatch-intent, approval,
  fencing, recovery, and ambiguity-safe rules. M8 needs an immutable
  integration projection, not another database.
- Event-first/State-second exclusive publication makes cross-store crash state
  visible without falsely claiming atomicity or exactly-once execution.
- Existing public fixture families cover offline non-UI, unavailable-UI, and
  security-sensitive projects. UI validation must block honestly when no real
  observation exists.

## Decision log

- M8-D1: five strict content-addressed JSON artifacts, exact bounds, and
  highest-level sensitivity propagation.
- M8-D2: compose native artifacts by exact reference and use M6 v2 as the sole
  mutable authority for explicit predecessor-linked candidate epochs.
- M8-D3: pure deterministic planning and closed, independently recomputed
  explanation reasons.
- M8-D4: immutable native-truth projections plus M6 terminal reserve/confirm,
  exact at-least-once finalization, one M6 tick per transition, and
  evidence-preserving v2 recovery.
- M8-D5: existing approval authority, immediate protected-effect revalidation,
  typed intent without dispatch, and no ambiguous-effect retry.
- M8-D6: four completion profiles and four Outcome dispositions composing
  existing Gates and Automated Handoff without status upgrade.
- M8-D7: twelve fixed-clock real-Outcome scenarios over three exact fixture
  bundles and nine exact non-aggregate groups with 52 independently resolved
  names.
- M8-D8: the exact amended workflow signatures, M6 v2 initialization and
  migration signatures, additive schemas, ports, local adapters, fixtures,
  validator, tests, docs, and CI within the exact 74-path union, with no
  dependency or stable export change.

## Outcomes and retrospective

The round-three review accepted F1 through F11 but found the successor lifecycle
compatibility blocker that kept its historical overall disposition at NO-GO.
The follow-up carries exact predecessor scheduler authority through resume,
status, recovery, and Python terminal-observation finalization while retaining
the accepted transaction and replay boundaries. The latest independent review
confirmed that boundary and returned GO with every F1-through-F11 ACCEPT result
maintained and zero unresolved findings within scope. It supersedes the earlier
overall NO-GO for the reviewed M8 state only. At review time, the candidate
remained local, uncommitted, Experimental, and unreleased; release GO,
production readiness, Git publication, and remote exact-SHA CI were separate
human decisions. That state was later merged to `main`, whose exact-triggering-
SHA Actions run `31497539609` passed the full matrix. The later M6 status-
publication state then passed exact pull-request head Actions run `31558960113`,
merged through pull request #4, and passed post-merge `main` exact-triggering-
SHA run `31563987706`. No new hash list or candidate fingerprint is part of the
M8 remediation.
