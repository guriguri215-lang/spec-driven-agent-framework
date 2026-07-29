# M3 Evidence, UI/UX, and Release QA ExecPlan

## Objective

Deliver one offline-first, deterministic, fail-closed M3 slice that validates a
bounded Claim-Evidence Ledger, evaluates Gates G2 through G4, validates recorded
browser/UI observations when a manifest declares a UI, runs local
security/dependency/license release-candidate checks, and creates a bounded
session handoff. Completion requires the acceptance criteria below, preserved
M0 through M2 behavior, every local Gate, and read-only review with no unresolved
Critical, High, or Medium finding.

## Scope

- A versioned Claim-Evidence Ledger and strict standard-library loader.
- Evidence addition through an atomic, repository-bounded local write.
- Non-compensating Gate G2 implementation-evidence and Gate G3 independent
  review evaluation.
- UI classification, Design Brief and browser-observation contracts, including
  loading, empty, error, permission-denied, offline, primary-flow, viewport,
  keyboard, focus, readability, contrast, screenshot, and retry evidence.
- Offline release-candidate evaluation for Gate G4, including reproducibility,
  Must verification, security, dependency, license, documentation, rollback,
  and clean-Git observations.
- Deterministic automated handoff creation and resume-mismatch validation.
- M3 CLI, schemas, samples, documentation, negative/boundary/failure-injection
  tests, regression tests, and local Gate parity.

## Non-goals

- A management UI, browser installation, a bundled browser, live network use,
  paid APIs, production dependencies, or automatic deployment.
- M4 sample expansion, cross-platform proof, comparative evaluation, schema
  migration automation, or contributor-workflow hardening.
- Choosing a project license or creating a `LICENSE`.
- GitHub authentication or metadata inspection, remote-HEAD or Actions checks,
  commit, push, PR, issue, discussion, tag, release, visibility, branch
  protection, secret, runner, or repository-setting changes.
- Treating a recorded browser observation, test result, or self-assertion as
  proof when its required trace, artifact, review, or approval is absent.

## Source requirements

Primary requirements are `FR-QA-001` through `FR-QA-014`, `FR-UI-001` through
`FR-UI-012`, and `FR-HOF-001` through `FR-HOF-008`, plus Gates G2, G3, and G4.
Applicable supporting requirements are `FR-EXE-001` through `FR-EXE-013`,
`FR-APR-001` through `FR-APR-016`, `FR-GIT-001` through `FR-GIT-008`,
`FR-GIT-011` through `FR-GIT-014`, `FR-WKS-006` through `FR-WKS-010`, and
`NFR-001` through `NFR-018`. Gate G5 and all external publication remain out of
scope.

## Derived acceptance criteria

- `AC-M3-001`: A ledger is adopted only from one bounded, regular, unlinked
  UTF-8 JSON file with the exact supported version, unique stable claim and
  evidence identifiers, valid cross-references, bounded fields, safe relative
  artifacts, timezone-aware timestamps, and no secret-shaped content.
- `AC-M3-002`: Every evidence record preserves claim, environment, command,
  result, artifact, timestamp, and commit state; all required evidence types and
  explicit `NOT_VERIFIED` state are supported, and deterministic serialization
  is available.
- `AC-M3-003`: Evidence addition validates the old ledger and new record,
  rejects duplicates, traversal, candidate mismatch, and concurrent writers,
  and atomically replaces only the named repository-local ledger without
  leaving a lock or temporary output after failure.
- `AC-M3-004`: Gate G2 fails closed on missing Must/acceptance mapping, failed or
  absent applicable evidence, unsupported completion claims, missing diff
  review, or any critical Must/security/data-loss/disclosure failure. Passing
  tests alone cannot establish conformance.
- `AC-M3-005`: Gate G3 requires a completed, read-only, logically independent
  review covering regression, security, and maintainability. Unresolved
  Critical, High, or Medium findings fail; accepted critical findings require a
  validated exact Owner approval rather than a self-asserted flag.
- `AC-M3-006`: A project is deterministically classified as UI or non-UI from a
  validated manifest. Non-UI projects do not require a UI agent or fabricated
  browser evidence.
- `AC-M3-007`: A UI project passes only with a bounded Design Brief, users,
  primary flows, required states, target devices, and recorded real-browser or
  target-platform observations covering viewport, keyboard, focus,
  readability, contrast, offline behavior, screenshots, and recovery. Failed
  observations remain failed until a later bounded attempt passes.
- `AC-M3-008`: Gate G4 is non-compensating and requires Gates G2 and G3, the
  applicable UI Gate, reproducible-install evidence, verified Must claims,
  passing security/dependency/license/documentation audits, rollback guidance,
  and an explicitly clean local Git observation.
- `AC-M3-009`: Automated handoff records branch, HEAD, worktree state, source
  digest, milestone, completed/incomplete work, evidence, open decisions, known
  problems, next work, Primary folder, approval stops, and a non-executing next
  prompt; resume mismatches fail closed.
- `AC-M3-010`: M3 schema/sample pairs and primary CLI paths validate offline,
  produce bounded English JSON or human output, and return non-zero on invalid
  input without disclosing absolute paths or secrets.
- `AC-M3-011`: M0 through M2 CLI, schema/sample parity, canonical digest,
  Requirements Baseline, Gate G1, and approval-consumption security remain
  unchanged.
- `AC-M3-012`: Runtime dependencies remain empty, no project license appears,
  all required local Gates pass, and read-only review reports no unresolved
  Critical, High, or Medium finding.

## Dependencies, risks, and assumptions

- Use only Python 3.12+ standard-library runtime code and existing development
  dependencies.
- Browser execution is a host capability. The offline core validates bounded
  observations and artifacts but never installs or launches a browser.
- Release audit inputs are untrusted; absent or malformed observations fail
  closed. Gate G4 is not Gate G5 and does not authorize publication.
- Existing M1 and M2 versioned contracts remain accepted without migration.

## Checkpoints and validation

1. Add immutable M3 contracts and strict loaders/stores without changing M1/M2
   contracts.
2. Add G2/G3, UI validation, G4 release audit, and handoff services.
3. Add CLI, schemas, samples, smoke coverage, and documentation.
4. Run focused negative, boundary, failure-injection, security, determinism, and
   regression tests.
5. Run every exact command in `docs/release-contract.md`, including pytest,
   Ruff, strict mypy, total/M1/M2/M3 coverage, CLI smoke, workspace,
   publication, dependency/license, `pip check`, and whitespace checks.
6. Perform a logically separate read-only diff review and resolve every
   Critical, High, or Medium finding.

## Stop conditions

Stop for a changed branch or unexpected HEAD, dirty pre-existing worktree,
canonical specification digest mismatch, required Gate weakening, production
dependency or project-license need, private-data exposure, approval-scope
mismatch, unsafe Git boundary, or a mandatory result unavailable after the
allowed narrow technical sandbox path.

## Technical sandbox handling

Run each local command normally once. A denial is not proof that a tool is
absent. Classify it before requesting one exact, minimal technical approval; do
not use administrator shells, UAC bypass, full access, sandbox bypass, `--yolo`,
or global configuration changes.

## Owner approval gates

No GitHub, publication, license, production-dependency, deployment, credential,
repository-setting, destructive Git, commit, or push operation is authorized by
this plan. If one becomes necessary, stop and present the exact target, command,
scope, effect, reversibility, and validation before requesting Owner approval.

## Language and publication boundary

All tracked content is English. Parent state remains private and is not copied
into the repository. No external action occurs during M3 implementation.

## Decision log

- 2026-07-29: Preserve existing M1/M2 schemas and add separate M3 versioned
  contracts; schema migration remains M4.
- 2026-07-29: Treat browser use as a host capability and validate recorded
  browser/target-platform observations offline.
- 2026-07-29: Keep Gate G4 local and distinct from Owner-gated publication
  Gate G5.

## Progress log

- 2026-07-29: Read the approved specification, roadmap, release contract,
  architecture, M2 evidence, and complete M2 living ExecPlan.
- 2026-07-29: Confirmed `main`, exact starting HEAD
  `9421661343809d95affbcd5a97d0d7fca3b7f690`, clean worktree, safe parent/repo
  boundary, and passing M0 through M2 local Gates.
- 2026-07-29: Initial M3 implementation passed 449 tests and all local Gates,
  then independent read-only review returned NO-GO with four High and eight
  Medium findings.
- 2026-07-29: Bound G2/G3/UI/handoff/G4 to one immutable candidate identity;
  required structured commands, real content-hashed artifacts, full manifest
  validation, exact finding approvals, concurrent-writer exclusion, direct Git
  observation, stronger license/private-state audits, and a positive clean-Git
  G4 CLI smoke fixture.
- 2026-07-29: Hardened the candidate boundary to the actual source file and
  Git publication set; added strict JSON depth/number handling, portable schema
  parity, expiring finding acceptance, artifact-ancestor checks, truthful
  completed-handoff state, binary disclosure and nested-license scans, and
  regular non-empty documentation checks.
- 2026-07-29: Hardened UI proof with browser/executable/version binding and
  bounded PNG decoding, and hardened release proof with a fresh
  `python -I -m pip --isolated` target install, installed-module execution, exact rollback,
  generated-state exclusion, and host-independent temporary Git configuration.
- 2026-07-29: Focused M3 tests, Ruff, strict mypy, actual-install CLI smoke,
  publication audit, dependency/license audit, `pip check`, and whitespace
  checks pass. The first final re-review found one High candidate-binding
  bypass: ignored worktree input could affect an install from `"."`.
- 2026-07-29: Replaced worktree installation with a fresh owned source tree
  materialized only from Git publication files, added exact path-and-byte
  comparison and extra-input rejection, required documentation publication
  membership, and injected an ignored failing `setup.py` into the actual
  clean-G4 smoke.
- 2026-07-29: A later independent review found one High installer-shadow
  bypass before pip isolation. Added Python `-I` isolation, exact-root
  execution, ignored failing `pip.py` and `PYTHONPATH` injection, and actual
  isolated-install coverage.
- 2026-07-29: Final verification passed 523 tests with one Windows environment
  skip, Ruff, strict mypy across 87 files, 91 percent total, 94 percent M1,
  90 percent M2, and 91 percent M3 branch coverage, the complete M0 through M3
  actual-install CLI smoke, workspace, publication, dependency/license,
  `pip check`, and whitespace Gates.
- 2026-07-29: Final independent read-only review returned GO with zero
  unresolved Critical, High, or Medium finding. M3 evidence records the dirty
  uncommitted state and all external or host-browser verification limits.
