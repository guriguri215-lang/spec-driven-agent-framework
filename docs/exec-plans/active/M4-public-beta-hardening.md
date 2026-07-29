# M4 Public Beta Hardening ExecPlan

## Objective

Deliver one verifiable M4 Public Beta Hardening slice that preserves the
offline-first, fail-closed, no-runtime-dependency M0 through M3 boundary while
adding representative sample projects, deterministic comparative evaluation,
explicit cross-platform evidence, safe versioned schema migration, and a
complete public contributor workflow. Completion requires the derived
acceptance criteria below, every local Gate, exact candidate-bound platform
evidence, and read-only review with no unresolved Critical, High, or Medium
finding.

## Scope

- Three representative sample specifications and projects:
  - an offline non-UI command-line configuration validator;
  - a small UI issue-tracking workflow with accessibility and offline states;
  - a security-sensitive data-export workflow with approval and disclosure
    boundaries.
- An expected deterministic normalization projection for every sample,
  including source identity, stable requirement identifiers, types,
  priorities, statements, acceptance identifiers, verification methods, and
  diagnostics.
- Strict versioned evaluation-suite and run-record contracts, a
  standard-library loader, deterministic metrics, paired workflow comparison,
  non-compensating hard blockers, and an offline CLI path.
- Paired structured-SDAQF and ordinary-unstructured-Codex run records with
  exact input identity, intervention disclosure, measured outcomes, execution
  trace, decisions, evidence, cost availability, and limitations.
- Version 1.0 to 2.0 migration for the legacy Agent Registry and Tool Registry,
  with explicit compatibility policy, deterministic conservative defaults,
  validation of the migrated output, and non-destructive failure and rollback.
- Reproducible platform-evidence records for Windows and Linux on Python 3.12
  and 3.13. macOS remains explicitly `NOT_VERIFIED` unless it is actually run.
- Hardened English public documentation for setup, development, testing,
  architecture, extension, schema migration, evaluation, security,
  contribution boundaries, release limitations, and known limitations.
- M4 schemas, fixtures, CLI smoke paths, negative, boundary, determinism,
  migration, regression, and public-contract tests.

## Non-goals

- V1.0 release work, Gate G5 publication, public visibility, a tag, a release,
  deployment, or external contribution acceptance.
- Selecting a project license or creating a project-license file.
- Changing a GitHub workflow, runner, secret, branch-protection rule, or
  repository setting.
- Adding a production dependency, paid API, OpenAI API, Agents SDK, hosted
  evaluation service, or network requirement.
- Automatically executing Codex, launching nested Codex, or treating authored
  fixtures as statistically independent model evidence.
- Silent migration, in-place overwrite, downgrade, multi-hop migration, or
  inferred expansion of tool, agent, approval, network, write, or risk scope.
- Replacing the M1, M2, or M3 strict loaders or weakening Gates G1 through G4.

## Source requirements and traceability

| Requirement | Derived criteria | Primary deliverables | Verification |
|---|---|---|---|
| `FR-EVL-001` | `AC-M4-001`, `AC-M4-002` | three sample specifications, expected normalization projections, suite manifest | projection and schema parity tests |
| `FR-EVL-002` | `AC-M4-003` | run records and metric engine | exact metric tests for missed requirements, scope additions, critical defects, rework, approvals, and failed handoffs |
| `FR-EVL-003` | `AC-M4-004` | paired comparison protocol and input-identity validator | parity, mismatch, and intervention-disclosure tests |
| `FR-EVL-004` | `AC-M4-005` | non-compensating evaluation decision | Must, security, data-loss, and disclosure failure tests |
| `FR-EVL-005` | `AC-M4-006` | before/after fixture linkage | missing-side and changed-input rejection tests |
| `FR-EVL-006` | `AC-M4-007` | repeated-failure cause-analysis records | missing cause, owner, layer, or follow-up rejection tests |
| `FR-EVL-007` | `AC-M4-003`, `AC-M4-008` | trace, decision, evidence, and cost fields | strict loader and report tests |
| `NFR-003` | `AC-M4-009` | candidate-bound platform-evidence records | Windows/Linux and Python 3.12/3.13 matrix checks; truthful macOS state |
| `NFR-012` | `AC-M4-010`–`AC-M4-012` | migration service, CLI, policy, and fixtures | deterministic migration, compatibility, failure, and rollback tests |
| `FR-GIT-011` | `AC-M4-013` | hardened README, CONTRIBUTING, SECURITY, changelog, installation, and limitations | public-document contract and publication audit |
| `FR-QA-001`–`FR-QA-014` | `AC-M4-003`–`AC-M4-009`, `AC-M4-014` | evidence-bound results, explicit limits, full Gates, review | schema, candidate-binding, Gate, and review evidence |
| `FR-HOF-001`–`FR-HOF-008` | `AC-M4-015` | M4 evidence, private completion report, next-session prompt | exact final identity and prompt-content review |
| `FR-APR-001`–`FR-APR-016` | `AC-M4-012`, `AC-M4-016` | conservative migration and approval stops | negative approval-expansion and external-action review |
| `FR-GIT-001`–`FR-GIT-008`, `FR-GIT-012`–`FR-GIT-020` | `AC-M4-013`, `AC-M4-014`, `AC-M4-016` | local-only English candidate and publication audits | workspace, disclosure, language, license, and Git-boundary checks |

## Derived acceptance criteria

- `AC-M4-001`: At least three bounded regular UTF-8 sample specifications
  represent non-UI, UI, and security/approval-sensitive projects without
  private data, unsafe paths, secrets, or project-license content.
- `AC-M4-002`: Every sample has a versioned expected normalization projection
  that exactly matches deterministic M1 ingestion for source digest, baseline
  identity, sorted requirements, acceptance identifiers, verification
  methods, and diagnostics.
- `AC-M4-003`: The evaluator deterministically measures missed requirements,
  scope additions, critical defects, rework, approval count, and failed
  handoffs, and retains execution traces, decisions, evidence, and available or
  explicitly unavailable cost observations.
- `AC-M4-004`: Structured and ordinary-unstructured records are compared only
  when project, specification, task, starting repository, model/client,
  platform, budget, and trial identity are equal. The framework intervention
  and any non-blind, authored, replayed, or single-session limitation are
  explicit.
- `AC-M4-005`: A Must, security, data-loss, or disclosure failure is a named
  hard blocker and cannot be hidden by a total, average, improvement, or other
  aggregate score.
- `AC-M4-006`: Before/after evaluation for a Skill, template, or prompt change
  requires both sides, the same input identity, and a named changed artifact;
  absent or mismatched evidence fails closed.
- `AC-M4-007`: Repeated failures require a bounded cause analysis that selects
  one or more instruction, Skill, schema, test, or implementation layers,
  names a follow-up owner and action, and remains unresolved until verified.
- `AC-M4-008`: The published M4 comparison result is reproducible from the
  tracked suite and run records, reports every metric per project and workflow,
  states evidence limitations, and makes no causal or production-readiness
  claim beyond the evidence.
- `AC-M4-009`: Candidate-bound evidence records successful Windows and Linux
  execution on Python 3.12 and 3.13 with exact commands and commit identity.
  macOS is either actually verified or explicitly `NOT_VERIFIED` with a reason.
- `AC-M4-010`: Legacy Agent Registry 1.0 and Tool Registry 1.0 inputs migrate
  through explicit, deterministic, one-step 1.0-to-2.0 transformations; current
  strict 2.0 loaders validate every successful output.
- `AC-M4-011`: Migration never overwrites its source or an existing output,
  never mutates on validation failure, records all inserted conservative
  defaults and warnings, and provides rollback by retaining the unchanged
  source and removing only the newly created output.
- `AC-M4-012`: Unsupported versions, unsafe legacy commands, ambiguous or
  colliding identifiers, invalid networks, empty required collections, scope
  expansion, links, traversal, duplicate keys, and malformed output fail
  closed. Existing M1/M2/M3 version acceptance remains unchanged.
- `AC-M4-013`: Public English documentation consistently covers installation,
  contributor setup, development, testing, architecture, extension points,
  evaluation, migration, security, release limitations, and the unselected
  license and external-contribution policy.
- `AC-M4-014`: M0 through M3 behavior, schemas, canonical digest, empty runtime
  dependency set, Gates G1 through G4, approval consumption, security
  invariants, and all prior thresholds pass unchanged; M4 critical branch
  coverage is at least 90 percent.
- `AC-M4-015`: Public M4 evidence and private final state record exact branch,
  HEAD, worktree, staged set, canonical digest, publication digest, completed
  and incomplete work, platform limits, review result, approvals, and a next
  prompt that is created but never executed.
- `AC-M4-016`: No project license, production dependency, workflow, runner,
  secret, repository setting, commit, push, remote observation, tag, release,
  deployment, or external publication occurs without its exact Owner approval.

## Exact deliverables

### Sample and evaluation artifacts

- `evals/projects/offline-config/`
- `evals/projects/ui-issue-tracker/`
- `evals/projects/secure-export/`
- Each project contains `specification.md`,
  `expected-normalized.json`, `structured-run.json`, and
  `unstructured-run.json`.
- `evals/protocols/structured-instructions.md` and
  `evals/protocols/ordinary-instructions.md`
- `evals/comparison-suite.json`
- `evals/results/public-beta-comparison.json`
- `schemas/evaluation-expectation.schema.json`
- `schemas/evaluation-run.schema.json`
- `schemas/evaluation-suite.schema.json`
- `schemas/evaluation-result.schema.json`
- `src/sdaqf/domain/evaluation.py`
- `src/sdaqf/application/evaluation.py`
- `sdaqf eval validate` and `sdaqf eval compare`

### Migration artifacts

- `src/sdaqf/domain/migrations.py`
- `src/sdaqf/application/migrations.py`
- `schemas/migration-approval.schema.json`
- `schemas/migration-result.schema.json`
- legacy and expected migrated Agent/Tool Registry fixtures
- `sdaqf schema migrate --contract {agent-registry,tool-registry}
  --from-version 1.0 --to-version 2.0 INPUT --output NEW_FILE
  --approval APPROVAL` with `--tool-registry CURRENT_TOOLS` for Agent Registry
- `docs/schema-migrations.md`

### Platform and contributor artifacts

- `schemas/platform-evidence.schema.json`
- `docs/evidence/M4-platform-evidence.json`
- `docs/evidence/M4-verification.md`
- `docs/evaluation.md`
- `docs/contributor-guide.md`
- aligned updates to README, CONTRIBUTING, SECURITY, CHANGELOG, architecture,
  roadmap, Release Contract, dependency record, CLI smoke, and public-contract
  tests.

## Compatibility and negative-test design

- Keep all existing M1, M2, and M3 schemas and loader versions unchanged.
- Keep Agent Registry 2.0 and Tool Registry 2.0 as the only runtime-adopted
  versions; 1.0 is accepted only by the explicit migration command.
- Compare source bytes before and after every migration test and require an
  exclusively created output.
- Reject an existing output, source/output alias, link or reparse input,
  traversal, duplicate JSON key, oversized or deeply nested input, unsupported
  version or contract, unsafe command, unknown executable migration profile,
  role slug collision, missing tool reference, network ambiguity, and any
  default that would grant write, parallel, network, approval, retry, optional,
  or risk capability.
- Re-run canonical M1 counts and digest, legacy schema validation, M2 strict
  approval-consumption tests, M3 candidate/artifact/UI/install/handoff tests,
  and G1 through G4 negative tests without threshold or assertion changes.
- Reject evaluation pairs with unequal input identities, duplicate run IDs,
  missing workflow arm, undeclared scope addition, unknown requirement,
  hidden critical failure, inconsistent metric, fabricated cost, missing
  evidence, or unresolved repeated-failure analysis.

## Dependencies, risks, and assumptions

- Runtime code uses only Python 3.12+ standard-library modules. The runtime
  dependency list remains empty.
- Existing CI already executes full pytest and CLI smoke on Windows and Linux
  with Python 3.12 and 3.13. No workflow edit is required for M4 coverage.
- Exact-SHA M4 CI evidence requires separately approved commit, normal push,
  and read-only Actions observation. Prior M3 exact-SHA evidence proves only
  the inherited baseline.
- The comparison fixtures are small paired public-beta trials, not a
  statistically powered benchmark. A same-session or authored arm is disclosed
  and cannot support a causal claim.
- Conservative migration can reduce legacy capability to preserve safety, but
  it must never grant capability. Any semantic ambiguity is a warning or hard
  failure, never an implicit guess.
- Public contribution acceptance, license, visibility, and release metadata
  remain unresolved Owner decisions.

## Checkpoints and validation

1. Confirm the starting snapshot and create this living plan before
   implementation.
2. Add sample projects, expected normalization projections, evaluation
   contracts, loaders, metrics, CLI paths, and negative tests.
3. Add explicit Agent/Tool Registry migration, schemas, fixtures,
   documentation, rollback behavior, and failure-injection tests.
4. Harden contributor, extension, evaluation, migration, security, release,
   and known-limitations documentation.
5. Run focused M4 tests and produce the deterministic comparison result.
6. Run every exact local command in `docs/release-contract.md`, including the
   new M4 critical coverage and fixture-evidence checks.
7. Obtain exact Owner approvals if commit, push, or remote CI observation is
   needed; otherwise leave those items explicitly unverified.
8. Perform a logically separate read-only review and resolve every Critical,
   High, and Medium finding.
9. Record exact public evidence and private completion/handoff state without
   executing the next-session prompt.

## Stop conditions

Stop for a changed branch or starting HEAD, unexpected dirty or staged state,
canonical or publication digest mismatch, M4-external change, private data,
secret, personal path, unsafe link, generated debris, project-license content,
approval-scope mismatch, required Gate or threshold weakening, production
dependency, workflow/runner/repository-setting change, comparison input-parity
failure, dishonest or unsupported evaluation claim, silent migration data loss
or meaning expansion, denied-command repetition, force push, history rewrite,
broad staging, global configuration change, or a mandatory platform result
that cannot be truthfully established through the allowed approval boundary.

## Technical sandbox handling

Run each approved local command normally once. A denial is not proof that a
tool is absent. Classify the denial before requesting one exact minimal
technical approval. Do not use an administrator shell, UAC bypass, full access,
sandbox-bypass flags, `--yolo`, or global Git/Codex configuration changes. A
technical approval never authorizes an Owner-gated action.

## Owner approval gates

- No production dependency may be added without the exact package, version,
  license, purpose, and Owner approval.
- Do not change workflows, runners, secrets, branch protection, repository
  settings, project license, visibility, release level, tag, or public
  metadata without an exact Owner decision.
- Do not inspect private remote HEAD, GitHub metadata, authentication, or
  Actions without presenting the exact read-only target and command first.
- Do not stage, commit, push, open a PR, merge, tag, release, deploy, or post
  externally without separate exact approval for that action.

## Language and publication boundary

All tracked artifacts are English. Parent `state/` material remains private and
is never copied into the repository. Runtime `.sdaqf/` evidence, credentials,
authentication output, approvals, local paths, and raw logs are never
published.

## Decision log

- 2026-07-29: Use three bounded project classes to exercise non-UI, UI, and
  security/approval behavior.
- 2026-07-29: Migrate only legacy Agent and Tool Registry 1.0 contracts because
  their current 2.0 loaders already expose the explicit migration boundary.
- 2026-07-29: Use exclusively created outputs and conservative defaults; never
  perform an in-place migration or capability expansion.
- 2026-07-29: Reuse the existing immutable Windows/Linux Python 3.12/3.13 CI
  matrix without modifying the workflow.

## Progress log

- 2026-07-29: Read the complete repository instructions, approved
  specification, roadmap, Release Contract, architecture, M3 verification
  evidence, M3 living ExecPlan, and private M3 finalization records.
- 2026-07-29: Confirmed `main`, exact starting HEAD
  `889c4fab5ee56cc937385eb9d2080e6c5d35eeb8`, clean worktree, zero staged
  paths, canonical digest
  `89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5`,
  publication digest
  `FF6B50131C807DEF514726B5ACF238111C1102BBADBBAF4B53B5FF93275BAF67`
  across 193 paths, and the approved origin URL. No remote metadata was read.
- 2026-07-29: Added three representative sample specifications with exact
  normalization projections, parity-bound structured and ordinary run
  records, strict evaluation schemas, deterministic non-compensating metrics,
  tracked comparison evidence, offline evaluation CLI paths, and negative
  tests for identity, measurement, cost, intervention, and repeated failure.
- 2026-07-29: Added explicit Agent and Tool Registry 1.0-to-2.0 migration with
  conservative defaults, strict current-loader validation, source
  preservation, exclusive output, rollback guidance, path and link hardening,
  migration fixtures, an offline CLI path, and failure-injection tests.
- 2026-07-29: Hardened the English contributor, architecture, evaluation,
  migration, security, dependency, release, roadmap, and known-limitations
  documentation without adding a runtime dependency, project license,
  workflow, runner, or repository setting.
- 2026-07-29: The initial uncommitted candidate passed 610 tests with three
  explicit Windows link-creation environment skips, Ruff, strict mypy across
  94 source files, 91 percent total, 94 percent M1, 90 percent M2, 91 percent
  M3, and 95 percent M4 branch coverage, the complete M0 through M4 CLI smoke,
  comparison reproduction, workspace, publication, dependency/license,
  `pip check`, and whitespace Gates.
- 2026-07-29: The canonical digest remains unchanged, the branch and starting
  HEAD remain unchanged, and the staged set is empty. Exact candidate-bound
  Windows/Linux Python 3.12/3.13 evidence and final read-only review remain
  pending; prior M3 Actions evidence is not reused.
- 2026-07-29: The first independent read-only review returned NO-GO with zero
  Critical, three High, and four Medium findings: opaque comparison evidence,
  missing migration approval, incomplete failure cleanup, unresolved open
  cause analysis, absent Agent/tool cross-reference, byte-identical
  interventions, and an ABA source-identity race.
- 2026-07-29: Bound every comparison evidence item to a typed, timestamped,
  status-bearing tracked artifact and SHA-256; made authored-scenario and
  non-empirical limits explicit; required distinct intervention content; and
  made open cause analysis a named hard blocker.
- 2026-07-29: Added an exact time-bounded Owner migration-approval contract,
  current Tool Registry cross-reference for Agent migration, immutable initial
  byte-snapshot parsing, and cleanup after final source read or identity
  failure. Added negative and failure-injection tests for every review finding.
  Post-remediation verification passed 625 tests with three environment skips,
  Ruff, strict mypy, 91/94/90/91/93 percent total/M1/M2/M3/M4 coverage, CLI
  smoke, comparison reproduction, workspace, publication, dependency/license,
  `pip check`, and whitespace Gates.
- 2026-07-29: The first final re-review confirmed the prior seven findings
  were mechanically addressed but returned NO-GO with two new Medium findings:
  verified cause analysis did not require passing evidence, and migration
  approval did not bind the companion Tool Registry identity. Required PASS
  evidence for verified causes and bound the companion registry path and
  immutable snapshot digest into approval validation and migration results.
  Removed one duplicate schema member reported as a non-counted advisory.
- 2026-07-29: The second final re-review confirmed those two fixes but found
  one Medium runtime/schema parity issue: migration suffix handling and
  companion nullability were not identical across runtime and both public
  schemas. Required exact lowercase `.json` paths throughout, encoded Agent
  non-null and Tool null companion rules in both schemas, and added negative
  runtime and public-schema tests in both directions.
- 2026-07-29: The final independent read-only re-review returned GO with
  Critical/High/Medium = 0/0/0. The latest complete coverage run passed 625
  tests with three environment skips and retained 91/94/90/91/93 percent
  total/M1/M2/M3/M4 coverage. Exact candidate-bound Windows/Linux Python
  3.12/3.13 evidence remains pending and is the remaining milestone Gate.
- 2026-07-30: Owner-approved commit
  `92f26216a92124274bcdcb193b84db15639a5a10` was pushed normally to private
  `main`. Exact-SHA run `30464503453` found one test-only cross-platform
  expectation mismatch in the symlink/reparse-point negative test; all four
  jobs otherwise reached that same fail-closed rejection.
- 2026-07-30: Changed only the test expectation to assert the actual
  security-specific link/reparse rejection. Full local Gates passed again and
  independent read-only re-review returned GO with Critical/High/Medium =
  0/0/0. Fix commit `69468b201a7af110029285ac88efa663936deae5`
  was pushed normally.
- 2026-07-30: Exact-SHA Actions run `30465146945` completed successfully for
  Windows and Linux on Python 3.12 and 3.13. Every matrix job passed tests,
  lint, typing, coverage, audits, dependency consistency, and CLI smoke. The
  platform record now binds the exact verified subject commit and repository
  digest; macOS remains explicitly `NOT VERIFIED`.
