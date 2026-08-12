# Python 3.12/3.13 Support Contract ExecPlan

## Status

`LOCAL_GATES_COMPLETE_FINAL_REVIEW_PENDING`

This living ExecPlan follows `PLANS.md`. It is a separately approved
prerelease prerequisite and cross-references the
[next-prerelease readiness plan](V1-next-prerelease-readiness.md) without
selecting any `NP-D1` through `NP-D10` value.

## Objective and measurable completion state

Align the public package contract with the required CPython 3.12/3.13 matrix,
reconcile the live status documents after pull request #5, and preserve the
published `v1.0.0-rc.1` and all historical review and Gate records.

This plan completes only when the exact implementation passes every required
local Gate, offline wheel metadata read-back, and three independent read-only
final-diff reviews, and the resulting pull request exact head passes all four
Windows/Linux and Python 3.12/3.13 CI jobs. The exact-head GitHub record closes
the final condition without a post-CI tracked edit. This plan intentionally has
no future-merge completion checkbox.

## Starting state and source requirements

- Repository boundary: `repo/` only.
- Branch baseline: post-pull-request-#5 `main` at
  `068522fb90b4b6ce4c09120ae9f9f06ce91f6203`.
- Baseline README blob: `ce926326b8b1bf2db005668649c841aaf541aba2`.
- Pull request #5 exact-head run `31586128196` passed all four required jobs.
- Pull request #5 merged normally; post-merge `main` run `31594557932` passed
  the same exact-state matrix.
- Local `main` and `origin/main` matched, and the worktree and index were clean
  before `agent/fix-python-support-contract` was created.
- The public support matrix is CPython 3.12 and 3.13. Later versions require an
  explicit support-contract update, primary-matrix addition, validation, and
  approval.
- The distribution version remains `1.0.0rc1`.

## Scope and non-goals

The intended path allowlist is:

- `README.md`;
- `pyproject.toml`;
- `docs/dependencies.md`;
- `docs/specification.md`;
- `docs/decisions/0001-m0-technology.md`;
- `docs/roadmap.md`;
- `docs/exec-plans/active/M8-integrated-vibe-coding-framework.md`;
- `docs/exec-plans/active/V1-next-prerelease-readiness.md`;
- `docs/exec-plans/active/V1-python-support-contract.md`;
- `examples/m7-solver/solver-registry.json`;
- `examples/m7-solver/solver-request.json`;
- `examples/m7-solver/solver-result.json`;
- `examples/m7-solver/solver-verification.json`;
- `examples/m7-solver/task-graph.json`;
- `evals/results/m7-solver-evaluation.json`;
- `src/sdaqf/application/planning.py`;
- `tests/test_canonical_m1.py`;
- `tests/test_planning.py`; and
- `tests/test_v1_public_contracts.py`.

This work must not:

- change version `1.0.0rc1`, `src/sdaqf/__init__.py`, the
  `v1.0.0-rc.1` tag, rc1 notes, release QA, schemas, loaders, or the published
  Release;
- add a dependency or a Python 3.14 CI row or support claim;
- change runtime agent, solver, scheduler, or workflow behavior;
- create an artifact upload, package publication, deployment, candidate
  fingerprint, or hash list;
- decide or modify `NP-D1` through `NP-D10`; or
- rewrite a historical candidate, NO-GO, review caveat, finding count, or Gate
  result.

`CHANGELOG.md`, `docs/compatibility.md`, `docs/implementation-status.md`,
`docs/integrated-vibe-coding-framework.md`, and the active M6 ExecPlan remain
unchanged because the post-merge audit found no new live-state drift there.

## Dependencies, risks, and assumptions

- Existing pinned local tooling is sufficient; no network access or install is
  required.
- `requires-python = ">=3.12,<3.14"` expresses the validated public contract.
  The upper bound is not a technical incompatibility claim about Python 3.14.
- Editing `docs/specification.md` changes its canonical SHA-256 and baseline ID.
  Only the current assertions in `tests/test_canonical_m1.py` may change;
  historical evidence and synthetic fixture digests remain untouched.
- Editing `pyproject.toml` changes a live M7 public-artifact reference. Update
  only the transitive Registry, Task Graph, Request, Result, Verification, and
  evaluation-evidence references required by the named validator; these are
  not a candidate fingerprint or historical hash list.
- The new ExecPlan is untracked before staging, so ordinary `git diff` checks
  must be supplemented by untracked-path and no-index whitespace checks.
- The workspace Gate defaults to branch `main`; this approved branch must pass
  it with `--expected-branch agent/fix-python-support-contract`.
- Wheel building may leave setuptools output if run in the repository. Build
  and inspect only a disposable copied candidate under owned system temp.
- macOS remains unverified.

## Checkpoints and validation commands

### Checkpoint 0 - fresh post-merge baseline

- [x] Confirm pull request #5 exact-head CI passed.
- [x] Confirm pull request #5 merged normally.
- [x] Confirm exact post-merge `main` CI passed all four jobs.
- [x] Fetch origin, fast-forward local `main`, and confirm local/remote identity.
- [x] Confirm a clean worktree and index before creating the support branch.

### Checkpoint 1 - independent preimplementation audit

- [x] Obtain three independent read-only audits for status/history boundaries,
  Python metadata/tests/wheel evidence, and release/Git/PR Gates.
- [x] Classify live drift separately from historical evidence.
- [x] Freeze the intended path allowlist and protected paths above.

### Checkpoint 2 - minimal implementation

- [x] Bound `requires-python` to CPython 3.12/3.13 and align live documentation.
- [x] Add direct planning-output and package-contract regression assertions.
- [x] Update only the measured current canonical specification digest and
  baseline ID.
- [x] Update only the live M7 public-artifact reference chain invalidated by
  the package-metadata byte change.
- [x] Reconcile the concise README status and exact-state CI evidence, roadmap
  summary, pull request #5 planning record, and ambiguous historical M8
  approval checkpoint.
- [x] Preserve the version, rc1 publication records, dependencies, runtime
  behavior, historical findings, and Owner decisions.

### Checkpoint 3 - complete local Gate

- [x] Run all commands below successfully.
- [x] Classify every requested search hit as live state or historical evidence.
- [x] Build and read back one disposable offline wheel: require version
  `1.0.0rc1` and a semantically equivalent Python specifier to
  `>=3.12,<3.14`.
- [x] Confirm the repository and parent path sets are unchanged by validation.

Run from the repository root with existing tooling only:

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
python scripts/run_local_gate.py workspace --expected-branch agent/fix-python-support-contract
python scripts/run_local_gate.py publication
python scripts/run_local_gate.py dependencies
python scripts/run_local_gate.py pip-check
rg -n "current status-publication candidate|exact PR CI.*separate|before Goal completion|before Git finalization" README.md CHANGELOG.md docs
rg -n "Python 3\\.12 or newer|Python 3\\.12-or-newer|requires-python" README.md pyproject.toml docs src tests
git diff --check
git status --short
git diff --stat
```

Before staging, also inspect untracked paths and run a no-index whitespace check
for this plan. After explicit staging, run `git diff --cached --name-only` and
`git diff --cached --check`.

### Checkpoint 4 - independent final review and exact PR CI

- [ ] Obtain three independent read-only final-diff reviews.
- [ ] Require all three reviewers to ACCEPT with zero unresolved Critical,
  High, or Medium finding.
- [ ] Explicitly stage only the reviewed allowlisted paths, create an English
  commit, normally push, and open an English draft pull request.

The pull request exact head must remain unchanged, be mergeable, have no
unresolved review, and pass all four Windows/Linux and Python 3.12/3.13 jobs.
That exact-head result is the plan's terminal external Gate. Ready-for-review,
normal merge, and exact post-merge `main` CI are separately authorized execution
steps and are recorded in GitHub and the final task report, not as a future
tracked checkbox that would change the tested head.

## Stop conditions

Stop before staging, commit, push, or pull-request creation if any local Gate or
wheel read-back is failed or unknown, any unintended path is changed, any
Critical/High/Medium finding remains, or any reviewer does not ACCEPT.

Stop before Ready or merge if the exact head moves, CI is pending or failed,
mergeability is unknown or false, or a review thread remains unresolved. Do not
bypass branch protection or a required human review. Stop after merge if the
exact merge-commit `main` CI is incomplete or failed.

## Technical sandbox handling

Use `scripts/run_local_gate.py` so generated caches and test state stay in owned
system temp and are removed. If sandbox execution is denied, request the
minimum command-specific technical approval. For repository network Git
operations, use only an invocation-local `safe.directory` override if Windows
ownership requires it; do not change global, local, or repository Git config.
A technical approval never expands the Owner-approved product or publication
scope.

## Owner approval gates

The Owner has approved this branch, explicit staging of the reviewed allowlist,
an English commit, normal push, English draft pull request, Ready transition,
and normal merge only after the stated Gates pass. The Owner has not approved a
version change, tag, GitHub Release, artifact upload, package publication,
deployment, repository-setting change, history rewrite, force push, credential
inspection, or action outside this repository.

## Language and publication boundary

All tracked text, source, tests, branch names, commit messages, and GitHub-facing
metadata are English. No private parent-workspace report, credential, personal
data, or unrelated external-system content enters the repository. GitHub access
is limited to this repository's pull requests, Actions, and the explicitly
approved writes.

## Decision log

- 2026-08-12: Selected `>=3.12,<3.14` as the public metadata contract matching
  the required CPython 3.12/3.13 matrix.
- 2026-08-12: Preserved the historical ADR wording and added a current-contract
  addendum that makes no Python 3.14 incompatibility claim.
- 2026-08-12: Kept PR #4 run records as exact-state evidence and replaced the
  README's moving “current main” label with exact PR #5 merged-state evidence.
- 2026-08-12: Kept the next-prerelease plan separate; this prerequisite chooses
  no release metadata and authorizes no release action.
- 2026-08-12: Expanded the path allowlist only after the focused Gate proved
  that the live M7 public-artifact chain references `pyproject.toml` by content
  hash. Historical evidence and synthetic fixture hashes remain unchanged.

## Progress log

- 2026-08-12: Merged green pull request #5 normally and observed all four jobs
  pass on its exact post-merge `main` state.
- 2026-08-12: Refreshed clean local `main`, created the approved support branch,
  and obtained three independent read-only preimplementation audits.
- 2026-08-12: Implemented the minimal status and Python support-contract diff
  within the intended path allowlist. A focused Gate exposed and then verified
  the required live M7 reference-chain reconciliation.
- 2026-08-12: Passed full pytest with 1,317 tests and four explicit platform-
  capability skips, total and M1-through-M8 critical coverage thresholds,
  Ruff, strict mypy over 180 files, all four named validators, offline CLI
  smoke, evaluation, workspace, publication, dependency, installed-dependency,
  and whitespace checks. Disposable offline wheel read-back reported version
  `1.0.0rc1` and semantically equivalent Requires-Python
  `<3.14,>=3.12`. Search hits were classified as historical M6/M0 records or
  current contract evidence. Final independent review remains pending.
