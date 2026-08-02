# M7 Mathematical Solver Framework

This living ExecPlan follows `PLANS.md`. Keep Progress, Surprises &
Discoveries, Decision Log, and Outcomes & Retrospective current through local
validation, independent review, Git finalization, and exact-candidate CI.

## Purpose / Big Picture

M7 supplies one trustworthy offline computation boundary for small finite
integer feasibility and optimization problems. A validated M6 solver task can
reserve exact capacity, run the mandatory standard-library adapter, publish a
truthful Result, independently verify its evidence, and adopt it only when the
required claim is actually established.

Completion is measurable when four content-addressed public artifacts and
schemas round-trip exactly; ten closed statuses execute through production
services; Result and Verification evidence survives M6 validation and
fresh-output recovery; the named validator, smoke, full tests, audits, strict
typing, lint, and coverage Gates pass; and no external adapter, network,
dependency, staging, commit, push, or publication action has occurred.

## Scope and non-goals

The scope is the Owner-approved M7-D1 through M7-D8 contract and its exact
45-path tracked implementation allowlist. It includes strict domain values,
runtime contracts, schemas, a bounded finite-domain reference adapter,
independent verification, M5/M6 binding, additive CLI, public fixtures,
evaluation, tests, CI, and documentation.

It excludes mandatory third-party packages, executable external adapters,
network or hosted solvers, GPU services, arbitrary code or shell input,
floating-point proof claims, automatic approval, dependency changes, database
schema changes, existing contract reinterpretation, staging, commit, push,
remote observation, and publication.

## Source requirements and acceptance criteria

- Four schema `1.0` artifacts are strict, bounded, canonical, and
  content-addressed.
- Two problem kinds, three profiles, five constraint kinds, exact integer
  limits, and deterministic ordering are closed.
- `stdlib-finite-domain-v1` is mandatory, offline, deterministic, and
  dependency-free.
- Optional external CLI entries are structurally complete but never executed;
  they require exact tool/version/license/provenance and fresh single-use
  approvals.
- All ten Result statuses are truthful; timeout, unavailable, unknown, error,
  and insufficient verification remain non-adoptable.
- Verification reauthenticates identities, Lease evidence, resources, witness,
  objective, bound, proof, and required claim independently.
- M6 reserves and settles exact calls and solve-plus-verification steps and
  replays solver evidence during validation and recovery.
- `M7-SOLVER-EVIDENCE` executes the ten statuses through production services,
  checks public/schema parity and stable dependency/export boundaries, and
  contains no aggregate score.
- Total branch coverage remains at least 80 percent and M7 critical branch
  coverage is at least 90 percent without threshold reduction.

## Dependencies, risks, and assumptions

M7 depends on M5 Candidate, Context, sensitivity, artifact-reference, and
exclusive-publication semantics; M6 Task Graph, Lease, message, budget, event,
validation, and recovery semantics; and the existing M2 Tool Registry approval
model. The runtime dependency set remains empty.

Principal risks are false unsatisfiability or optimality, forged witnesses,
resource exhaustion, stale Lease authority, candidate or Context drift,
malicious structured input, optional-tool/license/version drift, and evidence
that passes live execution but fails recovery replay. Closed types, exact
integer budgets, independent enumeration, fail-closed identity checks, and
production recovery tests mitigate these risks.

## Plan of work

1. Freeze the four artifacts, problem union, adapter Registry, statuses,
   resource rules, and content identities.
2. Implement the reference adapter and independent verifier with pure typed
   ports and controlled error conversion.
3. Bind Requests and task results to M5/M6 identities, exact capability
   reservations, current or historical Lease evidence, validation, and
   recovery.
4. Add the exact CLI, schemas, public fixtures, ten-case evaluation, named
   validator, smoke, CI coverage Gate, and documentation.
5. Run the complete local Release Contract, audit the exact allowlist and Git
   state, freeze evidence, then stop for a separate independent-review
   approval boundary.

## Progress

- [x] (2026-08-02) Reverified the exact clean M6 baseline and bounded M7
  discovery evidence.
- [x] (2026-08-02) Obtained Owner approval for M7-D1 through M7-D8 and the
  exact 45-path tracked implementation allowlist.
- [x] (2026-08-02) Implemented strict typed contracts, four schemas, the
  reference adapter, independent verification, M5/M6 identity and budget
  integration, and additive CLI commands.
- [x] (2026-08-02) Implemented public examples, ten-status evaluation,
  production named validator, focused tests, smoke, CI coverage enforcement,
  and documentation.
- [x] (2026-08-02) Completed the full local Release Contract after final
  read-through hardening. The coverage run passed 1086 tests with four explicit
  link-capability skips. Total/M1/M2/M3/M4/M5/M6/M7 branch coverage was
  90/94/90/91/92/83/90/92 percent. Ruff and strict mypy passed 152 files; M5,
  M6, and M7 named validators, M0-through-M7 smoke, evaluation reproduction,
  workspace/publication/dependency audits, `pip check`, and whitespace checks
  passed. The exact changed set was all 45 approved paths, with zero outside
  the allowlist and zero staged paths.
- [x] (2026-08-02) Obtained separate Owner approval and completed a fresh
  independent read-only review against the frozen 45-path candidate. The
  review returned NO-GO with zero Critical, two High, five Medium, and one Low
  finding. The reviewed bytes and candidate fingerprint remained unchanged.
- [x] (2026-08-02) Obtained Owner approval to remediate all eight findings
  inside the original 45 paths, rerun the full Gate, and perform a fresh
  independent rereview. Implemented causal resource/termination replay,
  service-level external zero-use enforcement, complete adapter limits,
  zero-coefficient schema parity, exact M6 host grammar, lexical link/reparse
  confinement, bounded publisher failure handling, and the exact validator
  sentinel; regenerated the content-addressed public evidence and added
  regression tests.
- [x] (2026-08-02) Reran the complete local Release Contract for the remediated
  candidate. Coverage execution passed 1093 tests with the same four explicit
  link-capability skips. Total/M1/M2/M3/M4/M5/M6/M7 branch coverage was
  90/94/90/91/92/83/90/91 percent. Ruff and strict mypy passed 152 files; M5,
  M6, and exact-sentinel M7 validators, M0-through-M7 smoke,
  workspace/publication/dependency audits, `pip check`, and whitespace checks
  passed. The changed set remained exactly 45 approved paths, with zero outside
  the allowlist, zero missing, and zero staged paths. The final fingerprint is
  intentionally frozen outside this self-referential tracked document.
- [x] (2026-08-02) Completed the approved fresh independent read-only rereview.
  It returned NO-GO with zero Critical, two High, two Medium, and one Low
  finding. The reviewer confirmed seven of the original eight findings closed,
  but found hidden verification-prefix work and forgeable elapsed evidence in
  the resource remediation. The full contract sweep also found incorrect M5
  sensitivity schema labels, noncanonical table-variable ordering, and a
  widened M6 task-ID grammar. The ordinal pre/post fingerprint matched and no
  tracked byte changed during review.
- [x] (2026-08-02) Implemented the second remediation inside the same approved
  45 paths. Verification now performs one budget-capped causal replay and
  reports every evaluated assignment; non-timeout elapsed evidence is
  canonical zero in adapter, parser, and verifier; schemas reuse exact M5
  sensitivity; table variables are sorted; and task IDs reuse exact M6
  grammar. Added direct regression coverage; the M7 focused suite passes 88
  tests.
- [x] (2026-08-02) Reran the complete local Release Contract for the second
  remediation candidate. Coverage execution passed 1098 tests with the same
  four explicit link-capability skips. Total/M1/M2/M3/M4/M5/M6/M7 branch
  coverage was 90/94/90/91/92/83/90/91 percent. Ruff and strict mypy passed
  152 files; M5, M6, and exact-sentinel M7 validators, M0-through-M7 smoke,
  workspace/publication/dependency audits, `pip check`, and whitespace checks
  passed. Exact allowlist and ordinal fingerprint evidence is frozen outside
  this self-referential tracked document.
- [x] (2026-08-02) Obtained separate Owner approval and completed a fresh
  independent read-only rereview of the second remediation candidate. It
  returned NO-GO with zero Critical, High, or Medium findings and two Low
  findings: M7 still admitted the M6-invalid underscore in Task IDs, and an
  early-witness contradiction reported its declared replay target instead of
  the smaller number of assignments actually evaluated. The frozen ordinal
  fingerprint and exact 45-path scope matched before and after review.
- [x] (2026-08-02) Obtained Owner approval and remediated both residual Low
  findings inside the original 45 paths. M7 now uses the exact M6 Task ID
  grammar without underscores, and every verification return path reports the
  assignments actually evaluated by the single budget-capped replay. Added
  direct runtime/schema and rejected-path accounting regression coverage.
- [x] (2026-08-02) Reran the complete local Release Contract for the third
  remediation candidate. Both ordinary and coverage executions passed 1102
  tests with the same four explicit link-capability skips. Total and M1 through
  M7 critical branch coverage were 90/94/90/91/92/83/90/91 percent. Ruff and
  strict mypy passed 152 files; M5, M6, and exact-sentinel M7 validators,
  M0-through-M7 smoke, workspace/publication/dependency audits, `pip check`,
  and whitespace checks passed. Exact allowlist and ordinal fingerprint
  evidence is frozen outside this self-referential tracked document.
- [x] (2026-08-02) Obtained separate Owner approval and completed a fresh
  independent read-only review of the third remediation candidate. It returned
  NO-GO with zero Critical or Medium/Low findings and two High findings. The
  scheduler could settle otherwise valid evidence for another Graph and
  operational contract because current task capability authority was not
  passed into M7 evidence validation; separately, replay did not reject Result
  work above `max_solve_steps` when combined solve and Verification use still
  fit the total reservation. The exact 45-path scope and ordinal fingerprint
  matched before and after review.
- [x] (2026-08-02) Obtained Owner approval and implemented the fourth
  remediation inside the original 45 paths. Task Result validation now binds
  the recomputed current Task Graph identity, current task ID, unique M7
  capability token, Request, and Lease. Result parsing and Verification both
  enforce the separate solve-step cap. Added direct cross-Graph/contract
  scheduler rejection and over-cap parser/verifier regression coverage; the
  focused M7 suite passes 94 tests.
- [x] (2026-08-02) Reran the complete local Release Contract for the fourth
  remediation candidate. Both ordinary and coverage executions passed 1104
  tests with the same four explicit link-capability skips. Total and M1 through
  M7 critical branch coverage were 90/94/90/91/92/83/90/92 percent. Ruff and
  strict mypy passed 152 files; M5, M6, and exact-sentinel M7 validators,
  M0-through-M7 smoke, evaluation reproduction, workspace/publication/
  dependency audits, `pip check`, and whitespace checks passed. Exact
  allowlist and ordinal fingerprint evidence is frozen outside this
  self-referential tracked document.
- [x] (2026-08-02) Obtained separate Owner approval and completed a fresh
  independent read-only review of the fourth remediation candidate. It
  returned NO-GO with zero Critical, one High, two Medium, and zero Low
  findings. Verification and scheduler replay did not enforce the Request
  Result-byte cap; the Registry safe-path schema omitted exact M6 portability
  exclusions; and M7 runtime accepted a noncanonical M6 Lease UTC offset
  alias. The reviewer confirmed every prior finding closed. The exact 45-path
  scope and ordinal fingerprint matched before and after review.
- [x] (2026-08-02) Obtained Owner approval and implemented the fifth
  remediation inside the original 45 paths. Verification now measures the
  exact hash-bound raw Result bytes and enforces `max_result_bytes` before
  replay across current adoption, immutable-history validation, and recovery.
  The Registry safe-path schema copies the authoritative M6 exclusions and
  Lease parsing reuses exact M6 RFC 3339 UTC validation. Added symmetric
  runtime/schema and live/history/recovery regression coverage. The focused M7
  suite passes 100 tests; targeted Ruff and strict mypy, M6 and exact-sentinel
  M7 validators, M0-through-M7 smoke, publication/workspace audits, and
  whitespace checks pass.
- [x] (2026-08-02) Reran the complete local Release Contract for the fifth
  remediation candidate. Both ordinary and coverage executions passed 1110
  tests with the same four explicit link-capability skips. Total and M1 through
  M7 critical branch coverage were 90/94/90/91/92/83/90/91 percent. Ruff and
  strict mypy passed 152 files; M5, M6, and exact-sentinel M7 validators,
  M0-through-M7 smoke, evaluation reproduction, workspace/publication/
  dependency audits, `pip check`, and whitespace checks passed. Exact
  allowlist and ordinal fingerprint evidence is frozen outside this
  self-referential tracked document.
- [x] (2026-08-02) Completed the Owner-preauthorized fresh independent
  read-only review of the fifth remediation candidate. It returned NO-GO with
  zero Critical or High findings, one Medium finding, and zero Low findings.
  Exact raw Result byte measurement was correct, but a failed Task Result could
  durably accept and recover a `rejected` Verification because only successful
  outcomes required adoption authority. All older findings were confirmed
  closed. The exact 45-path scope and ordinal fingerprint matched before and
  after review.
- [x] (2026-08-02) Implemented the sixth remediation inside the original 45
  paths under the Owner's standing nonfatal-remediation approval. Every
  `rejected` Verification is now excluded from Task Result evidence regardless
  of successful or failed outcome, while truthful `inconclusive` failed-task
  evidence remains admissible and recoverable. Added live/history/recovery
  regression coverage and a production named-validator adversarial case; the
  focused M7 suite passes 101 tests and targeted strict mypy passes.
- [x] (2026-08-02) Reran the complete local Release Contract for the sixth
  remediation candidate. Both ordinary and coverage executions passed 1111
  tests with the same four explicit link-capability skips. Total and M1 through
  M7 critical branch coverage were 90/94/90/91/92/83/90/91 percent. Ruff and
  strict mypy passed 152 files; M5, M6, and exact-sentinel M7 validators,
  M0-through-M7 smoke, evaluation reproduction, workspace/publication/
  dependency audits, `pip check`, and whitespace checks passed. Exact
  allowlist and ordinal fingerprint evidence is frozen outside this
  self-referential tracked document.
- [x] (2026-08-02) Completed the Owner-preauthorized fresh independent
  read-only review of the sixth remediation candidate. It returned GO with
  zero Critical, High, Medium, or Low findings. The reviewer independently
  confirmed unconditional rejection of `rejected` Verification evidence
  before live settlement, immutable-history validation, and recovery; it also
  confirmed that truthful `inconclusive` and verified-but-claim-unsatisfied
  evidence can settle only failed tasks. The focused M7 suite passed 101 tests,
  every historical finding was confirmed closed, and the exact 45-path scope
  and ordinal fingerprint matched before and after review.
- [ ] Present a separate exact stage/commit proposal. Push and exact-SHA CI
  observation remain later separate approval boundaries.

## Checkpoints and validation

Run from the repository root in the isolated development environment:

```text
python -m pytest
python -m ruff check src tests scripts
python -m mypy src tests scripts
python -m coverage run -m pytest
python -m coverage report --fail-under=80
python -m coverage report --include="src/sdaqf/domain/solver.py,src/sdaqf/ports/solver.py,src/sdaqf/adapters/solver.py,src/sdaqf/application/solver_contracts.py,src/sdaqf/application/solver.py,src/sdaqf/application/solver_verification.py" --fail-under=90
python scripts/run_cli_smoke.py
python scripts/validate_m5_context.py
python scripts/validate_m6_scheduler.py
python scripts/validate_m7_solver.py
python scripts/check_workspace_boundary.py --repo . --expected-origin-url https://github.com/guriguri215-lang/spec-driven-agent-framework.git
python scripts/audit_repository.py --root . --workspace-parent ..
python scripts/audit_dependencies.py --root .
python -m pip check
git diff --check
```

## Stop conditions

Stop if truthful status would require guessing, if incomplete or unverified
evidence could become adoptable, if solver text or output could grant approval
or external effect, if an external executable or dependency becomes necessary,
if M5/M6 history would need rewriting, if work leaves the approved allowlist,
or before any independent-review, Git, remote, or publication boundary lacking
separate Owner approval.

## Technical sandbox and Owner approval gates

A technical sandbox approval may only permit an exact local validation command
that the managed Windows environment otherwise blocks. It cannot authorize an
external solver, network, dependency installation, credential access,
destructive cleanup, staging, commit, push, or publication.

Tracked implementation was authorized only for the approved 45 paths. A fresh
independent review, any remediation outside that set, staging/commit, push,
exact-SHA remote CI observation, tag, release, visibility, or other external
action is a new Owner approval boundary.

## Language and publication boundary

All tracked documentation, schemas, examples, evaluation evidence, CLI text,
tests, and GitHub workflow material are English and contain no private
discovery record. Local approval evidence remains outside the publication
tree. This plan claims only the completed local independent reviews described
above; it does not claim remote CI or publication.

## Surprises & Discoveries

- Independent proof replay has its own step budget. Exhaustive Result evidence
  with insufficient verification capacity is `inconclusive`, not `rejected`.
- Verification needs historical as well as current Lease evidence because
  durable scheduler adoption releases current authority while retaining the
  immutable proof chain.
- A structurally representable external adapter needs explicit version matcher,
  observation state, and fresh single-use approval requirements even when the
  executable is deliberately not observed or run.
- A content-addressed envelope is not strict if its raw JSON parser accepts
  duplicate keys. M7 now reuses the existing bounded duplicate/non-finite/depth
  rejecting parser rather than relying on decoded-object equality alone.
- A digest-correct Tool Registry reference is necessary but not sufficient.
  External adapter validation also binds its declared tool, executable, version
  matcher, optionality, and no-network policy to the parsed Registry entry.
- Independent review demonstrated that upper-bound checks do not authenticate
  resource evidence. Verification must reproduce the canonical visited prefix
  and bind calls, steps, checks, termination, status, proof, witness, and
  objective as one causal record.
- An injected adapter port can bypass a boundary that exists only in the
  default adapter. The application service now converts every selected
  `external-cli` adapter directly to deterministic `unavailable` zero-use
  evidence, and Verification independently requires that disposition.
- Path confinement must inspect lexical ancestors before resolution. Checking
  only a resolved target or immediate parent loses evidence that traversal
  crossed a symbolic link or Windows reparse point.
- Independent verification work is itself reserved resource use. Causal solve
  replay and mathematical proof replay must be the same budget-capped
  enumeration, not two passes or an unreported pre-check.
- Reused authority vocabularies and identifier grammars must be copied from
  the authoritative M5/M6 contracts exactly. Plausible aliases or widened
  lengths create schema/runtime drift even when current cross-artifact binding
  blocks some downstream adoption paths.
- A content hash authenticates bytes but does not prove that their raw length
  satisfies a Request-specific byte policy. Every adoption and recovery reader
  must measure the exact hash-bound Result representation rather than trusting
  the normal writer or a typed reserialization.
- Reusing M6 authority also includes representation rules such as portable
  paths and canonical UTC `Z` timestamps, not only semantic IDs and values.
- Reproducing a Verification exactly is not sufficient if downstream outcome
  logic admits `rejected` evidence for a failed task. Evidence validity and
  mathematical adoption are separate predicates: rejection invalidates every
  Task Result, while truthful inconclusive evidence can still settle failure.

## Decision Log

- Use complete-assignment enumeration with lexicographic tie-breaking as the
  only executable M7 adapter. This is simple enough to reproduce independently
  and honest about finite limits.
- Keep tolerance exactly zero and all arithmetic integer. Approximate numeric
  proof semantics require a future version.
- Convert controlled adapter failures to typed `error` Results so scheduler
  accounting remains explicit; malformed contracts and authority failures
  still fail closed without publishing output.
- Treat the optional CLI Registry entry as descriptive evidence only. Selection
  returns `unavailable` at the application-service boundary and performs no
  injected adapter call, process, or version probe.
- Represent the exact integer numeric domain and every D2 hard limit in each
  adapter definition, then validate the actual selected Request against those
  limits. Global parser bounds alone are not adapter capability evidence.
- Enforce `max_result_bytes` from the exact referenced raw bytes at both
  Verification entry points and fold it into causal resource accounting before
  mathematical replay, so normal generation, live adoption, history audit, and
  recovery share one fail-closed policy.
- Reject `SolverVerificationOutcome.REJECTED` before all Task Result settlement;
  reserve the successful/adoptable comparison for claim authority and allow
  failed tasks only when their reproduced evidence is verified but nonadoptable
  or truthful `inconclusive`.

## Outcomes & Retrospective

The six-times-remediated local implementation has a complete dependency-free
vertical slice from typed Request through M6-authorized solve, independent
Verification, scheduler adoption, immutable replay, recovery, CLI, schemas,
and public evaluation. Each preceding NO-GO disposition superseded that
candidate's local Gate result. The sixth remediation closes the final Medium
failed-outcome gap, passes the complete local Release Contract, and has now
received an independent GO review with zero findings. Git finalization and
remote CI remain later approval boundaries and must be recorded here only after
they occur.
