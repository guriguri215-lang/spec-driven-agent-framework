# Release Contract

V1 local implementation and validation do not themselves authorize staging,
commit, push, remote observation, a tag, a release, a visibility change, or a
repository-setting change. Separately Owner-approved finalization may create
an inspected immutable local candidate. Because current repository visibility
is unobserved after A7, any future push must be treated as potentially public.
Public release and every other external action remain separately Owner-gated.

## Required local gates

Run these commands from the repository root with the isolated development
environment active:

```text
python -m pytest
python -m ruff check src tests scripts
python -m mypy src tests scripts
python -m coverage run -m pytest
python -m coverage report --fail-under=80
python -m coverage report --include="src/sdaqf/domain/models.py,src/sdaqf/domain/requirements.py,src/sdaqf/application/gates.py,src/sdaqf/application/approvals.py,src/sdaqf/application/baselines.py,src/sdaqf/application/comparison.py,src/sdaqf/application/planning.py,src/sdaqf/application/requirements.py,src/sdaqf/application/requirements_gate.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/orchestration.py,src/sdaqf/domain/tooling.py,src/sdaqf/adapters/process.py,src/sdaqf/application/orchestration.py,src/sdaqf/application/skills.py,src/sdaqf/application/tooling.py,src/sdaqf/application/checkpoints.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/quality.py,src/sdaqf/application/contracts.py,src/sdaqf/application/evidence.py,src/sdaqf/application/quality_gates.py,src/sdaqf/application/ui_validation.py,src/sdaqf/application/release_qa.py,src/sdaqf/application/handoffs.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/evaluation.py,src/sdaqf/domain/migrations.py,src/sdaqf/application/evaluation.py,src/sdaqf/application/migrations.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/context.py,src/sdaqf/ports/context.py,src/sdaqf/adapters/context.py,src/sdaqf/application/context_contracts.py,src/sdaqf/application/context_index.py,src/sdaqf/application/context_selection.py,src/sdaqf/application/context_compaction.py,src/sdaqf/application/context_quality.py" --fail-under=80
python -m coverage report --include="src/sdaqf/domain/scheduler.py,src/sdaqf/ports/scheduler.py,src/sdaqf/adapters/scheduler.py,src/sdaqf/application/scheduler_contracts.py,src/sdaqf/application/scheduler.py,src/sdaqf/application/scheduler_recovery.py,src/sdaqf/application/scheduler_simulation.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/solver.py,src/sdaqf/ports/solver.py,src/sdaqf/adapters/solver.py,src/sdaqf/application/solver_contracts.py,src/sdaqf/application/solver.py,src/sdaqf/application/solver_verification.py" --fail-under=90
python scripts/run_cli_smoke.py
python scripts/validate_m5_context.py
python scripts/validate_m6_scheduler.py
python scripts/validate_m7_solver.py
python -m sdaqf eval validate evals/comparison-suite.json --result evals/results/public-beta-comparison.json --json
python scripts/check_workspace_boundary.py --repo . --expected-origin-url https://github.com/guriguri215-lang/spec-driven-agent-framework.git
python scripts/audit_repository.py --root . --workspace-parent ..
python scripts/audit_dependencies.py --root .
python -m pip check
git diff --check
```

The complete pytest run is the schema/sample validation Gate. It also preserves
M0 and M1 CLI behavior, canonical specification ingestion, Requirements
Baseline counts and digest, and Gate G1. It validates M4 sample normalization,
paired comparison, non-compensating metrics, migrations, compatibility, and
public documentation. `scripts/run_cli_smoke.py` runs the
preserved `doctor`, `init`, `validate`, `status`, and `goal-template` commands;
the M1 `ingest`, `compare`, `roadmap`, `exec-plan`, `goal`, `prompt`, and
`gate requirements` commands; and the M2 `agents`, `skills`, `tools`, and
`checkpoint` primary paths. It also exercises M3 evidence validation, Gates G2
and G3, non-UI classification, handoff create/resume, a positive G4 path in a
temporary clean Git repository, and an explicit dirty-candidate negative path.
It also validates the tracked M4 evaluation result, calculates the comparison,
migrates a legacy Agent Registry to a new file, and validates the migrated
output through the current strict loader and companion Tool Registry. The
smoke supplies an exact generated single-use Owner migration-approval record
and exercises its atomic repository-local consumption claim; production
migration remains approval-bound.
It additionally runs M5 Context validation, indexing, selection, Snapshot
re-observation, structural comparison, and extractive compaction against the
synthetic public fixture.
It also validates and initializes an M6 Task Graph, advances and inspects the
SQLite state, exports events, inspects the mailbox, recovers to a fresh state,
and runs a deterministic real-state-machine simulation without dispatching a
host effect.
It additionally validates the M7 Solver Registry and Request, executes the
bounded reference adapter under an exact M6 Lease, and independently verifies
the fresh Result without a process or network effect.
The positive G4 fixture performs an actual `python -I -m pip --isolated`,
no-index, no-build-isolation, no-dependency target installation and executes
the installed module from that fresh target. It materializes only Git
publication files into a fresh owned source tree and includes ignored failing
`setup.py` and `pip.py` injections to prove that ignored worktree input is
neither built nor allowed to shadow the installer. Host
Git hooks, signing, attributes, excludes, file monitoring, and template input
are disabled for the owned fixture. The smoke also performs the canonical
ingest and Gate G1 offline in a temporary repository-local directory.

The repository audit uses Git's complete cached-plus-untracked publication set.
It checks secrets, email and personal paths in text and binary metadata,
English/CJK content, links and reparse ancestors, size, private/generated
state, and project-license material. The dependency audit verifies the empty
runtime dependency set, exact development pins, documented dependency-license
metadata, and the exact Apache-2.0 project expression, `LICENSE`, and `NOTICE`
allowlist. Unknown, additional, nested, linked, modified, or conflicting
project-license material fails closed. `pip check`
verifies the installed dependency set. Gate G4 additionally requires all
declared release documents to be regular, unlinked, non-empty UTF-8 files and
members of the Git publication set, and requires README installation and
known-limitations sections.

## Continuous integration parity

Every Windows/Linux and Python 3.12/3.13 matrix job runs pytest, Ruff, strict
mypy, total and M1/M2/M6/M7 critical branch coverage, both repository audits, the Git
workspace boundary, installed dependency consistency, and the exact CLI smoke
script. Full pytest and smoke therefore exercise M4 on every existing matrix
job. The matrix also runs `M6-SCHEDULER-SAFETY` and
`M7-SOLVER-EVIDENCE`. The M3, M4, and M5 critical thresholds are additional
local Gates. CI uses only immutable pinned GitHub Action commits and installs no
runtime dependency.

Platform claims must come from `docs/evidence/M4-platform-evidence.json` and
bind to the exact M4 candidate. A prior M3 matrix does not verify M4. A remote
matrix claim requires a separately Owner-approved commit, normal push, and
exact-SHA Actions observation. macOS remains `NOT_VERIFIED` unless it is
actually run.

## Local commit gate

- `python scripts/validate_m7_solver.py` prints
  `PASS: M7-SOLVER-EVIDENCE` and validates all four positive runtime/schema
  artifact pairs, negative schema/runtime parity, exact M5/M6 and operational
  identities, independent optimal proof replay, current and historical Lease
  semantics, paired Result/Verification adoption and recovery, the read-only
  Agent Result, all ten production status paths, recorded public evaluation
  parity, stable top-level exports, and the empty runtime dependency set.
- M7 focused tests cover strict envelopes and content identities; exact integer,
  profile, constraint, ordering, result-shape, adapter, version-observation,
  approval, complete adapter limits, lexical link/reparse confinement, timeout,
  bounded publication failure, error, causal resource/termination replay,
  separate solve/verification caps, exact raw Result byte caps across live,
  historical, and recovery replay, all-outcome rejected-evidence exclusion,
  truthful failed-task inconclusive evidence, verification-step accounting, canonical
  non-timeout elapsed evidence, current Graph/task/capability authority binding,
  external zero-use enforcement, proof, witness, objective, exact M5
  sensitivity, sorted table columns, M6 task/host/path/UTC grammars, and claim
  boundaries; M6 capability reservations, fencing, historical Lease evidence,
  Task Result replay and recovery; CLI confinement/collision; public schemas;
  and ten truthful statuses. M7 critical branch coverage is at least 90
  percent.
- The optional external-CLI adapter is never executed. `unavailable` reports
  zero solver use, and no validation command performs network access, version
  probing, fresh approval consumption, or dependency installation.

- `python scripts/validate_m6_scheduler.py` prints
  `PASS: M6-SCHEDULER-SAFETY` and validates all seven positive runtime/schema
  artifact pairs, positive and negative structural runtime/schema parity,
  authoritative cross-field time safety, exact SQLite identity and schema
  shape, one-owner concurrent claiming, deliberate mutable projection
  corruption followed by immutable-evidence reconstruction, all ten durable-
  state-backed deterministic scenarios, recorded evaluation parity, and the
  unchanged stable top-level exports.
- M6 focused tests cover strict envelopes, exact M2/M5 binding, DAG and path
  invariants, protected-transition revalidation, Agent Result/evidence
  consistency, transactional state, exact schema/projection reconciliation,
  fencing, periodic heartbeat/expiry, idempotent and conflicting messages,
  exact approval actors, persisted approval-proposal identity across real clock
  gaps, and atomic dual consumption; closed evidence/result/review completion
  predicates; sensitivity parity; deep artifact immutability; agent/concurrency
  ordering parity; attempt-scoped integer reservation settlement;
  exact current Lease/Worktree set reconciliation; causal cancellation and
  worktree intents; immutable initialization-bound Lease policy; exact
  cause-derived Worktree history cardinality; initialization-anchored wall-time
  observation; old-attempt cancellation rejection; exact Worktree-observation
  phase, assignment, prior-request, and current-Lease authority under fully
  rehashed foreign-path, post-dispatch, and old-Lease corruption; exact
  non-result Lease-history output cardinality and heartbeat-plus-TTL expiry
  derivation under a content-addressed extra-current-row corruption; ambiguity
  and late-result rejection; corruption recovery;
  CLI confinement/collision; and real-state-machine simulation. M6 critical
  branch coverage is at least 90 percent.
- `python scripts/validate_m5_context.py` prints
  `PASS: M5-CONTEXT-INTEGRITY` and reproduces all eight public Context
  artifacts, seven named scenarios, the exact Snapshot, extractive Compaction,
  and named non-aggregate quality report. Each scenario is executed locally;
  checked-in `passed` fields are compared with generated observations and are
  not treated as self-authenticating evidence.
- M5 focused tests cover strict/runtime-schema parity, source/link/change
  handling, identity chains, freshness, sensitivity, required budget and
  selection ordering, contradictions, output collision, Snapshot
  re-observation (including immutable JSON), fabricated Selection and
  standalone Snapshot rejection, actual candidate verification, provenance
  authority, persisted-Snapshot reauthentication, optional exclusions,
  source/contradiction-preserving Compaction, host-summary authority, bounded
  non-Git CLI failure, and public/private boundaries. The focused suite does not claim an
  exhaustive cross-product of every numeric, filesystem, graph-topology, and
  platform boundary; the complete suite and platform matrix remain separate
  required gates.
- The complete offline CLI smoke executes Context validate, index, select,
  snapshot, compare, and compact without network or implicit private reads.
- Every required check passes without a threshold reduction or ignored
  failure.
- Independent read-only review returns GO with no unresolved Critical, High,
  or Medium finding.
- The staged names, status, stat, diff, and whitespace are reviewed
  explicitly.
- No secret, personal path, private state, link, generated cache, coverage
  output, temporary file, unapproved license material, or non-English GitHub-facing
  artifact is staged.
- The tracked evaluation result exactly reproduces from the suite and run
  records, retains its limits, and contains no aggregate score.
- Migration fixtures preserve their source and validate through the existing
  current-version loaders, the Agent/tool cross-reference, and an exact,
  time-bounded, atomically consumed single-use Owner approval.
- A post-link input-identity race returns a distinct indeterminate-publication
  failure, prohibits output use, and never auto-deletes the replaceable name.
- Runtime approval-consumption, M3 evidence, review, UI, trace, and handoff
  records under `.sdaqf/` remain repository-local ignored state and are never
  staged.
- The branch is `main`.
- The only remote is the approved `origin`; every configured fetch and push
  URL exactly matches the approved public repository URL.
- The commit message and repository-local author identity are non-personal
  English metadata.

## Public push and exact-SHA CI gate

The repository is public. Any future push is an external publication and
requires a new exact Owner approval naming the commit, repository, ref, and
reviewed outbound diff.

Force push, history rewrite, PRs, issues, discussions, tags, releases,
deployment, repository administration, secrets, and runner changes remain
prohibited.

After push, the observed workflow must have the exact local commit as its head
SHA and every required matrix job must succeed. A failure is diagnosed from
bounded logs before any retry. An in-scope fix receives focused tests, full
related Gates, read-only re-review, a new English commit, and a normal push.

## Local publication-readiness gate

After an immutable exact candidate, candidate-bound G1 through G4 evidence,
and independent review exist, run:

```text
python -m sdaqf gate publication-readiness .sdaqf/v1/public-release-candidate.json --root . --baseline .sdaqf/v1/requirements-baseline.json --ledger .sdaqf/v1/claim-evidence-ledger.json --review .sdaqf/v1/independent-review.json --release-candidate .sdaqf/v1/release-candidate.json --specification docs/specification.md --json
```

The command is offline and side-effect-free. It binds the exact branch, HEAD,
specification digest, repository digest, complete publication path set,
release metadata, Apache-2.0 material, policies, exact SHA-256-bound
`.sdaqf/v1/gates/G1.json` through `G4.json` result artifacts whose wrappers
bind the current specification, HEAD, and repository digest, independent
review, platform matrix, notes digest, and explicit non-publication state. Its
terminal success state is `LOCAL_READY`; its gate identifier is
`G5-LOCAL-READINESS`, `publication_performed` remains false, and actual Gate
G5 remains `NOT_RUN`.

## Public release gate

Candidate `9f14e2287da3afc078db787e823765320b1e23ac` was published as the
annotated tag and GitHub prerelease `v1.0.0-rc.1`, titled
`SDAQF v1.0.0-rc.1`. It has no attached assets or package-registry publication
and uses only GitHub-provided source archives. The repository is public,
private vulnerability reporting is enabled, and actual Gate G5 passed for that
candidate.

The required Windows/Linux Python 3.12/3.13 branch run for the tagged commit
succeeded as Actions run `30603953536`. A duplicate tag-triggered run
`30605092668` later failed the workspace boundary because a tag checkout is a
detached HEAD rather than branch `main`; all four jobs failed at that same
branch-only audit step. This does not replace the successful exact-SHA branch
evidence. The current workflow prevents tag-push jobs and validates an explicit
head branch for pull requests; PR #1 verified that correction in all four
Windows/Linux Python 3.12/3.13 jobs as Actions run `30822231420`.

Every future tag, release, repository-setting change, and post-publication
observation remains separately Owner-gated. A fresh secret, personal-data,
dependency, license, language, advisory, clean-environment, and exact-SHA audit
is required. Local readiness can never substitute for external evidence.
