# M2 Agent, Skill, and Tool Orchestration ExecPlan

## Objective

Deliver one offline-first, deterministic, fail-closed M2 orchestration slice
that validates agent, Skill, template, tool, result, worktree, approval, and
checkpoint contracts; selects justified roles within explicit budgets; chooses
native Codex Subagents or a safe fallback; isolates parallel writes; and runs
only validated local tool probes with bounded evidence. Completion requires all
acceptance criteria below, M1 and Gate G1 regression protection, every local
Gate, an independent read-only review with no unresolved Critical, High, or
Medium finding, one reviewed M2 commit on `main`, and green GitHub Actions for
that exact commit.

## Scope

- Agent Registry contracts for role, responsibility, input, output, tool, and
  prohibited-action boundaries.
- Deterministic role selection by problem type, scale, risk, and parallelism.
- Native Codex Subagent planning plus independent-session and sequential
  fallback modes.
- Safe read-heavy parallelization and fail-closed write isolation.
- Explicit worktree owner, path scope, base commit, and integrator contracts.
- Logical separation of implementation and independent review.
- Structured agent summaries, bounded disagreements, and evidence-based
  resolution.
- Agent-count, reasoning-effort, and concurrency budgets.
- Repository Skill validation and versioned template metadata.
- Tool Registry validation, presence and version checks, bounded process
  execution, optional-tool isolation, and approval scope checks.
- Execution checkpoints, sandbox-denial classification, and bounded retry.
- M2 CLI, versioned schemas, representative samples, documentation, and tests.

## Non-goals

- M3 Claim-Evidence Ledger, generic Gate Engine, browser validation, release
  automation, automated handoff, or release-candidate automation.
- UI, paid APIs, production dependencies, global installation, or live web
  research.
- Automatic repository administration, branch protection, secrets, runners,
  PRs, issues, discussions, tags, releases, deployment, or license selection.
- Launching a nested Codex CLI process or pretending that a CLI process is a
  native in-product Subagent.
- Automatically creating, deleting, or integrating Git worktrees. M2 validates
  an explicit isolation plan; a caller remains responsible for approved Git
  operations.

## Reconciled starting state

- Original M2 starting commit:
  `0439176075e7509dc3874b329e40866c465af5fb`.
- Baseline repair commit:
  `eff9e3abfa6aff3e22d71b23140e838cd222832a`.
- Branch and upstream: `main`, `origin/main`.
- Worktree after baseline repair: clean.
- Remote: approved `origin` only; fetch and push URL both target
  `https://github.com/guriguri215-lang/spec-driven-agent-framework.git`.
- GitHub repository: `guriguri215-lang/spec-driven-agent-framework`,
  `PRIVATE`, default branch `main`.
- Baseline repair CI: workflow `Continuous integration`, run
  `30362714857`, exact repair SHA, all four Windows/Linux and Python 3.12/3.13
  matrix jobs successful.
- Public specification SHA-256:
  `89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5`.
- Authoritative source provenance SHA-256:
  `F28E02029768F80816001BD98DA43739F4BA33C1197710E02B1E20786EAD188B`.

## Source requirements

Primary M2 requirements are `FR-AGT-001` through `FR-AGT-012` and
`FR-TOL-001` through `FR-TOL-014`. Applicable execution requirements are
`FR-EXE-001` through `FR-EXE-013`, with implementation focused on checkpoints,
bounded command evidence, stop behavior, retry, sandbox denial, approval
separation, and declared scope. Applicable supporting requirements include
`FR-WKS-006` through `FR-WKS-010`, `FR-APR-001` through `FR-APR-016`,
`FR-QA-005` through `FR-QA-014`, `FR-GIT-001` through `FR-GIT-008`,
`NFR-001` through `NFR-013`, and `NFR-015` through `NFR-018`.

## Derived acceptance criteria

- `AC-M2-001`: A bounded regular JSON Agent Registry is adopted only when its
  schema version, unique safe roles, non-empty responsibilities, inputs,
  outputs, tools, and prohibited actions are valid.
- `AC-M2-002`: Role selection is deterministic, explains every selected role,
  rejects unsupported roles and unjustified requests, and cannot exceed agent,
  reasoning-effort, or concurrency budgets.
- `AC-M2-003`: Native Subagents are selected only when explicitly observed as
  available. Otherwise the plan deterministically selects an
  independent-session prompt or sequential fallback without launching a nested
  Codex process.
- `AC-M2-004`: Parallel execution is allowed initially for read-heavy
  discovery, test design, log analysis, and review. Same-worktree or same-file
  parallel writes are rejected.
- `AC-M2-005`: A parallel-write plan passes only with distinct worktrees,
  non-overlapping owned paths, one exact base commit, and one integrator that
  does not share an implementation scope.
- `AC-M2-006`: An implementer cannot approve its own result. Structured agent
  summaries are bounded and validated, and disagreements resolve by
  specification, counterexample, and evidence strength rather than agent vote.
- `AC-M2-007`: Every repository Skill has safe front matter, required lifecycle
  sections, a directory/name match, and a deterministic
  discovered/validated/compatible/blocked selection state. Every template
  record has version, dependency, provenance, license status, prohibited
  conditions, and validation date metadata.
- `AC-M2-008`: A Tool Registry is adopted only when every unique tool has a
  safe argument-array probe, supported platforms, scope, network destinations,
  risk, optionality, version policy, technical approval, and Owner approval
  contract.
- `AC-M2-009`: Tool presence and version are checked before use.
  `UNAVAILABLE`, `PERMISSION_DENIED`, `NOT_CHECKED`, timeout, unsupported
  version, and non-zero exit remain distinct results; an unavailable optional
  tool does not block the core.
- `AC-M2-010`: External processes always use argument arrays, no shell, a
  positive timeout, exit status, and separately bounded stdout and stderr.
- `AC-M2-011`: Unsafe executable, command argument, path, or network target and
  mismatched approval scope are rejected before process execution.
- `AC-M2-012`: Execution checkpoints use explicit states and bounded,
  secret-free evidence. They are written atomically with corruption recovery
  and reject resume mismatches in Git HEAD, worktree digest, specification
  digest, or plan version. Retry count and conditions are bounded, and an
  identical failed command is not retried without a classified, eligible state
  change.
- `AC-M2-013`: Sandbox denial is classified independently from missing-tool,
  authentication, network, test, workflow, and external-service failures.
  Technical approval never supplies missing Owner approval.
- `AC-M2-014`: M2 schemas and samples validate through the standard-library
  runtime, M2 primary CLI smoke passes offline, JSON output is bounded and
  machine-readable, and failures use non-zero exits without absolute-path or
  secret disclosure.
- `AC-M2-015`: Preserved M0/M1 CLI, canonical specification ingestion,
  Requirements Baseline, and Gate G1 all pass without semantic regression.
- `AC-M2-016`: Runtime dependencies remain empty, global install and production
  dependency requests are rejected by policy, optional adapters do not become
  core prerequisites, template/code provenance and license status remain
  explicit, no web research record is fabricated when no web research occurs,
  and tracked files and GitHub-facing metadata remain English.
- `AC-M2-017`: Windows boundary behavior is locally verified. Linux and Python
  3.13 behavior are verified only by the required GitHub Actions matrix. macOS
  behavior is explicitly `NOT VERIFIED`.
- `AC-M2-018`: Total branch coverage is at least 80 percent, M1 and M2 critical
  module branch coverage is at least 90 percent, publication audits pass, and
  independent review returns GO with no unresolved Critical, High, or Medium
  finding.

## Requirements-to-test-to-verification map

| Requirements | Acceptance criteria | Planned tests | Terminal verification |
|---|---|---|---|
| `FR-AGT-001` | `AC-M2-001` | `tests/test_agent_registry.py` | schema/sample and CLI validation |
| `FR-AGT-002`, `FR-AGT-011` | `AC-M2-002` | `tests/test_agent_selection.py` | deterministic plan JSON |
| `FR-AGT-003`–`FR-AGT-005` | `AC-M2-003`, `AC-M2-004` | selection and fallback tests | native/fallback CLI smoke |
| `FR-AGT-006`–`FR-AGT-008` | `AC-M2-004`–`AC-M2-006` | `tests/test_worktree_isolation.py` | fail-closed orchestration plan |
| `FR-AGT-009`–`FR-AGT-012` | `AC-M2-006` | `tests/test_agent_results.py` | structured result validation |
| `FR-TOL-001`–`FR-TOL-003`, `FR-TOL-011` | `AC-M2-007` | `tests/test_skills.py` | Skill/template CLI smoke |
| `FR-TOL-004`–`FR-TOL-005`, `FR-TOL-013`–`FR-TOL-014` | `AC-M2-008`, `AC-M2-009`, `AC-M2-013` | `tests/test_tool_registry.py` | registry and capability JSON |
| `FR-TOL-006`–`FR-TOL-010` | `AC-M2-009`–`AC-M2-011` | `tests/test_tool_execution.py` | bounded tool CLI smoke |
| `FR-EXE-001`–`FR-EXE-013` | `AC-M2-012`, `AC-M2-013` | `tests/test_execution_control.py` | checkpoint/retry and resume JSON |
| Applicable approval and security requirements | `AC-M2-011`–`AC-M2-014` | negative and failure-injection tests | publication and boundary audits |
| M1 primary slice and Gate G1 | `AC-M2-015` | complete existing test suite | canonical ingest and Gate G1 |
| `NFR-003`–`NFR-005`, `NFR-009`, `NFR-011`, `NFR-015`–`NFR-018` | `AC-M2-014`–`AC-M2-018` | cross-platform, determinism, coverage tests | local Gates and CI matrix |

## Architecture checkpoints

1. Add immutable M2 domain records and enums without changing M1 contracts.
2. Add bounded standard-library loaders for Agent Registry, orchestration
   request, worktree ownership, structured result, Tool Registry, Skill, and
   template contracts.
3. Add deterministic role selection, native/fallback mode selection,
   parallelization checks, result validation, and disagreement resolution.
4. Add tool capability/version checks and execution control around the existing
   no-shell process port, including checkpoint, retry, denial, approval, path,
   network, and output boundaries.
5. Add M2 CLI commands, schemas, samples, architecture and roadmap updates, and
   exact Release Contract/CI smoke commands.
6. Run negative, boundary, regression, failure-injection, and canonical tests;
   then all local Gates and independent read-only review.

## Git and worktree ownership

- Primary folder and only implementation worktree: `repo/` on `main`.
- The root agent is the only writer and integrator.
- Subagents may perform bounded read-only discovery, test design, log analysis,
  and review; they may not edit, stage, commit, push, or use network.
- No parallel command may write cache, temporary, coverage, or generated output
  into the same worktree.
- This milestone validates separate-worktree ownership contracts but does not
  create a second worktree.
- Stage only named reviewed paths; never use `git add .`.

## Agent and tool budget

- Maximum active agents including the integrator: four.
- Read-only discovery: at most two concurrent specialists.
- Independent review: one reviewer logically separate from implementation.
- Implementation writes: one integrator, concurrency one.
- Default selected-agent budget in the product contract: four agents and two
  concurrent roles unless a lower request applies.
- Supported reasoning effort values: `low`, `medium`, and `high`; the selected
  value may not exceed the request budget.
- Runtime tools: existing isolated Python, pytest, Ruff, mypy, coverage, Git,
  GitHub CLI for approved repository operations, and standard-library process
  execution. No new production dependency.

## Failure and retry policy

- Run each required command normally once. Classify failure before retry.
- Distinguish validation, unavailable tool, unsupported version, timeout,
  non-zero exit, sandbox denial, network denial, authentication,
  authorization, test, workflow, runner, and external-service failure.
- The product retry policy permits at most one retry and only after a recorded
  eligible state change; it rejects an identical unclassified retry.
- Local fixes must add a focused regression test and rerun the failed command
  plus the related full Gate.
- After the initial M2 push, allow at most three new corrective commits and
  pushes. Never amend a pushed commit or force push.
- Rerun the same workflow commit at most once and only for a logged transient
  GitHub runner, network, or service failure.

## Required local Gates

Run the exact commands in `docs/release-contract.md`. They must cover:

- pytest, Ruff, strict mypy, total branch coverage at 80 percent, and M1/M2
  critical branch coverage at 90 percent;
- preserved M0/M1 and primary M2 CLI smoke;
- canonical specification ingestion and Gate G1;
- Git workspace and exact-origin boundaries;
- secret, personal-path, symlink/reparse, dependency, license, English/CJK,
  installed-dependency, and patch-whitespace audits;
- schema and sample validation.

## GitHub Actions matrix and CI failure handling

- Required matrix: `ubuntu-latest` and `windows-latest`, Python 3.12 and 3.13,
  fail-fast disabled.
- Every matrix job runs the complete test, lint, type, coverage, audit, and CLI
  contract relevant to that runner.
- Push only after local Gates and review pass. Observe only the run whose head
  SHA equals the local M2 commit.
- On failure, retrieve the check, job, step, URL, and bounded log first;
  classify root cause and relationship to the diff; make only an in-scope,
  reversible fix; add regression coverage; rerun focused and full local Gates;
  obtain focused read-only re-review; create a new English commit; and normally
  push it.
- Do not skip, ignore, allow-failure, weaken coverage, remove matrix entries,
  or use `continue-on-error` to obtain green status.

## Technical sandbox handling

- A denial is not proof that a tool is absent.
- Do not repeat an identical denied normal command.
- A technical approval request must name the exact command, reason, paths,
  network destination, external effect, reversibility, and validation method.
- Approval must be limited to the already Owner-approved operation and exact
  repository. Never use administrator shells, UAC bypass, full access, sandbox
  bypass, `--yolo`, global permission changes, or credential inspection.

## Owner approval gates

The Goal already authorizes read-only GitHub metadata and Actions inspection,
normal push of inspected M2 commits to the approved private `origin/main`, up
to three corrective pushes, and one proven-transient workflow rerun. Stop for
any production dependency, Must reduction, non-goal or security-boundary
change, license decision, destructive Git, force push, history rewrite,
credential or secret operation, unrelated transfer, billing, repository or
visibility change, branch protection, PR, issue, discussion, tag, release,
deployment, Actions secret, or runner change.

## Stop conditions

Stop for a changed branch, unexpected HEAD or upstream, dirty pre-existing
worktree, non-private target, unexpected remote or push URL, specification
digest mismatch, unresolved Must ambiguity, required Gate weakening, production
dependency need, private-data exposure, approval-scope mismatch, unsafe Git
boundary, or mandatory evidence that remains unavailable after the allowed
technical approval path.

## Language and publication boundary

All tracked files, source, identifiers, comments, CLI output, schemas, samples,
tests, branches, commits, workflows, and GitHub metadata are English. Parent
workspace reports remain private and are not copied into the repository.

## Decision log

- 2026-07-28: Repair the failing M1 CI baseline before M2 in a separate commit.
- 2026-07-28: Preserve raw specification SHA-256 semantics and enforce LF
  checkout bytes instead of normalizing input inside the ingestor.
- 2026-07-28: Validate all `origin` fetch and push destinations against the
  approved repository rather than merely allowing a remote name.
- 2026-07-28: Represent native in-product Subagent availability explicitly;
  never launch or mislabel a nested Codex CLI process.
- 2026-07-28: Validate isolated-worktree ownership plans without automatically
  creating or deleting worktrees during M2.
- 2026-07-28: Treat registry version 2.0 as an execution contract, reject
  legacy 1.0 execution with an explicit migration-required result, and leave
  automated migration for a later milestone.
- 2026-07-28: Model Skill lifecycle as deterministic discovery, validation,
  compatibility, blocked, and selection states rather than claiming that
  static Markdown structure alone is a lifecycle.
- 2026-07-28: Treat derived M2 acceptance criteria as verifiable additions that
  preserve, and do not narrow, every applicable Must requirement.
- 2026-07-28: Treat native Subagent use as an explicit host-dispatch contract;
  use native read-only Subagents for milestone discovery and review, while the
  offline Python package never launches a nested Codex process.
- 2026-07-28: Limit M2 tool execution to safe registered version probes. Path
  and network scopes are validated and included in exact approvals; arbitrary
  tool actions remain outside this milestone.
- 2026-07-28: Record tool duration, execution mode, and applied approval
  identifiers in bounded observations and checkpoint evidence.
- 2026-07-28: Accept tool approvals only through a strict versioned loader
  that validates authority, timestamps, expiry, single-execution lifetime,
  exact command/path/network/risk conditions, and persistent atomic
  pre-execution consumption.
- 2026-07-28: Schedule isolated parallel writers in wave 1, their separate
  integrator in wave 2, and independent review in wave 3.

## Progress log

- 2026-07-28: Reconciled Git, specification digests, M0/M1 evidence, approved
  remote, private visibility, default branch, and starting GitHub Actions run.
- 2026-07-28: Diagnosed the failing starting run: Linux strict mypy rejected a
  Windows-only stat attribute and Windows checkout changed the canonical file
  digest through CRLF conversion.
- 2026-07-28: Added portable stat access, LF checkout enforcement, strict
  fetch/push remote validation, regression tests, and CI/Release Contract
  parity in baseline commit `eff9e3abfa6aff3e22d71b23140e838cd222832a`.
- 2026-07-28: Passed local baseline Gates, resolved one High independent review
  finding, pushed normally, and verified all four jobs in Actions run
  `30362714857` as successful.
- 2026-07-28: Started M2 read-only architecture and test-design discovery.
- 2026-07-28: Implemented strict Agent/Tool Registry, request, worktree,
  structured result, Skill/template, process, retry, checkpoint, schema,
  sample, and CLI contracts using only the standard library.
- 2026-07-28: The first focused M2 test pass completed with 79 passing tests.
  Expanded read-only test-design inspection found locator/execution mismatch,
  checkpoint validation and cleanup gaps, reviewer-selection and disagreement
  errors, Windows path gaps, URL/version exception leaks, and an unbounded
  process-reader join.
- 2026-07-28: Corrected every discovered defect and added negative, boundary,
  failure-injection, CRLF, and exact-approval regression tests. The focused M2
  suite then passed 178 tests.
- 2026-07-28: Full instrumented pytest passed 342 tests with one
  environment-limited symlink skip. Total branch coverage reached 92 percent
  and the M2 critical-module aggregate reached 91 percent.
- 2026-07-28: Added one cross-platform offline CLI smoke runner and explicit
  runtime/development dependency and license-record audit, then aligned the
  architecture, roadmap, README, Release Contract, and CI matrix.
- 2026-07-28: Initial final review found one High self-asserted tool-approval
  boundary and one Medium stale local-state evidence issue. Removed and ignored
  the generated local state without reading it, replaced caller-constructed
  approvals with strict expiring single-use records, and added focused
  lifecycle, authority, scope, retry, and CLI regressions.
- 2026-07-28: The post-fix full local Gate passed 362 tests with one
  environment-limited symlink skip, Ruff, strict mypy over 70 source files,
  92 percent total branch coverage, 94 percent M1 critical coverage, and
  90 percent M2 critical coverage. CLI, workspace, publication, dependency,
  installed-package, and whitespace checks also passed.
- 2026-07-28: Focused re-review confirmed the prior approval-provenance and
  local-state fixes but found that a single-execution approval could be reused
  across independent service or CLI invocations. Added a versioned
  repository-local consumption store, exclusive cross-process claim lock,
  atomic publication before process start, fail-closed corruption handling,
  and independent-instance, concurrent-claim, and repeated-CLI regressions.
- 2026-07-28: The persistent-claim candidate passed the complete local Gate:
  375 tests with one environment-limited symlink skip, Ruff, strict mypy,
  91 percent total branch coverage, 94 percent M1 critical coverage,
  90 percent M2 critical coverage, CLI smoke, all audits, `pip check`, and
  patch whitespace.
- 2026-07-28: A second focused review found that CLI consumption was anchored
  to the invocation working directory. Replaced that anchor with a
  deterministic boundary derived from the validated registry path and added a
  same-registry, same-approval, different-working-directory CLI regression.
- 2026-07-28: The cross-working-directory fix passed the complete local Gate
  again with 375 tests and one environment-limited skip, Ruff, strict mypy,
  91 percent total, 94 percent M1 critical, and 90 percent M2 critical branch
  coverage, CLI smoke, workspace/publication/dependency/package audits, and
  whitespace validation.
- 2026-07-28: Final independent read-only review returned GO with no unresolved
  Critical, High, or Medium finding after verifying registry-anchored
  cross-CWD consumption, atomic pre-process claims, concurrency, corrupt and
  locked state handling, prior safety fixes, ignored-state boundaries, and
  documentation accuracy.
