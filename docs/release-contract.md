# Release Contract

V1 local implementation and validation do not themselves authorize staging,
commit, push, remote observation, a tag, a release, a visibility change, or a
repository-setting change. Separately Owner-approved finalization may create
an inspected immutable local candidate. The tracked publication record says
the repository is public; this local validation does not re-observe remote
state, and every future push must therefore be treated as public.
Public release and every other external action remain separately Owner-gated.

## Required local gates

Run these commands from the repository root with the isolated development
environment active:

```text
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

`scripts/run_local_gate.py` creates a fresh owned fixture below the operating
system temp directory for each invocation. It routes pytest basetemp and cache,
coverage data, mypy and Ruff caches, Python bytecode, pip cache, and nested
validator/smoke temporary files below that fixture, then removes it. It also
copies the current cached-plus-untracked Git publication set into a clean
temporary Git repository, with Git safety configuration held inside the owned
fixture. The temporary repository preserves the source branch and exact remote
URL sets for the bounded workspace check. Every subcommand compares both the
repository and its non-repository workspace-parent path names before and after
execution, and fails if any path was added or removed. The coverage
subcommand runs the full suite with project branch coverage at least 80 percent
and preserves the existing M1/M2/M3/M4/M6/M7/M8 critical 90 percent thresholds
and the M5 critical 80 percent threshold.
The retained M4 selection includes `src/sdaqf/domain/evaluation.py` and
`src/sdaqf/application/migrations.py` and continues to use `--fail-under=90`;
the runner contains the complete exact M1-through-M8 file selections.

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
It also validates and initializes M6 v1 and v2 Task Graph stores, migrates one
validated v1 store copy-on-write under an exact synthetic Owner approval,
advances and inspects SQLite state, exports events, inspects the mailbox,
authenticates workflow epoch receipts, recovers to a fresh same-version state,
and runs a deterministic real-state-machine simulation without dispatching a
host effect.
It additionally validates the M7 Solver Registry and Request, executes the
bounded reference adapter under an exact M6 Lease, and independently verifies
the fresh Result without a process or network effect.
It also validates and plans an M8 Development Intent through an explicit M6 v2
authority, reproduces the exact explanation from the same pinned observation,
performs one bounded runtime transition, reads status, and reserves, publishes,
and confirms a typed terminal Outcome without dispatching a host effect.
The positive G4 fixture performs an actual `python -I -m pip --isolated`,
no-index, no-build-isolation, no-dependency target installation and executes
the installed module from that fresh target. It materializes only Git
publication files into a fresh owned source tree and includes ignored failing
`setup.py` and `pip.py` injections to prove that ignored worktree input is
neither built nor allowed to shadow the installer. Host
Git hooks, signing, attributes, excludes, file monitoring, and template input
are disabled for the owned fixture. The smoke materializes the current Git
publication set as a clean temporary Git repository below system temp, then
performs the canonical ingest and Gate G1 offline inside that owned fixture.

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
mypy, total and M1-through-M8 critical branch coverage, evaluation
reproduction, both repository audits, the Git workspace boundary, installed
dependency consistency, and the exact CLI smoke script through the same
system-temp candidate runner. Full pytest and smoke therefore exercise M4 on
every existing matrix job. The matrix also runs `M5-CONTEXT-INTEGRITY`, `M6-SCHEDULER-SAFETY`,
`M7-SOLVER-EVIDENCE`, and `M8-WORKFLOW-INTEGRATION`. CI uses only immutable
pinned GitHub Action commits and installs no runtime dependency.

The named branch checkout required by the workspace Gate is followed, before
any installation or Gate command, by a fail-closed comparison of the checked-
out `git rev-parse HEAD` with the triggering pull-request head SHA, or with
`github.sha` for a push. A queued workflow therefore cannot silently validate
a newer commit that reached the same mutable branch after the run was
triggered.

Platform claims must come from `docs/evidence/M4-platform-evidence.json` and
bind to the exact M4 candidate. A prior M3 matrix does not verify M4. A remote
matrix claim requires a separately Owner-approved commit, normal push, and
exact-SHA Actions observation. macOS remains `NOT_VERIFIED` unless it is
actually run.

## Local commit gate

- `python scripts/run_local_gate.py script scripts/validate_m8_workflow.py` prints
  `PASS: M8-WORKFLOW-INTEGRATION`; validates all five public artifacts and
  schemas plus negative parity; re-runs M5-M7 validators; reproduces Plan,
  explanation, runtime, status, supersession, recovery, terminal-reserved
  Event/State/Outcome finalization, twelve real-Outcome simulations over three
  exact fixture bundles, and nine independently re-resolved 52-name measurement
  groups; and confirms unchanged stable exports and
  runtime dependencies. M8 critical branch coverage is at least 90 percent.
- M8 focused tests cover strict identities, duplicate keys, bounds,
  sensitivity, reference drift, deterministic planning and explanation,
  protected approval stops, semantic Event forgery rejection, one-tick
  transition, resume, exact predecessor epochs, immutable recovery, ambiguity,
  one pinned Git-plus-M6 Candidate/G3/G4 observation, M3 UI-backed G4,
  receipt-bound runtime-private output identity, store-wide receipt-scope
  retention, post-preflight pre-epoch Candidate revalidation, exact
  confirmed-artifact retry, terminal timestamp identity, predecessor-aware
  explain/simulate/run,
  completion profiles, Gate/handoff composition, public schemas,
  all scenarios, stable boundaries, and CLI collision behavior.

- `python scripts/run_local_gate.py script scripts/validate_m7_solver.py` prints
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

- `python scripts/run_local_gate.py script scripts/validate_m6_scheduler.py` prints
  `PASS: M6-SCHEDULER-SAFETY` and validates all ten positive runtime/schema
  artifact pairs, positive and negative structural runtime/schema parity,
  authoritative cross-field time safety, exact SQLite v1/v2 identity and schema
  shape, copy-on-write v1-to-v2 migration, epoch/receipt replay and recovery,
  one-owner concurrent claiming, deliberate mutable projection
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
- `python scripts/run_local_gate.py script scripts/validate_m5_context.py` prints
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
SHA, its checkout assertion must confirm that same immutable triggering SHA,
and every required matrix job must succeed. A failure is diagnosed from bounded
logs before any retry. An in-scope fix receives focused tests, full related
Gates, read-only re-review, a new English commit, and a normal push.

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
