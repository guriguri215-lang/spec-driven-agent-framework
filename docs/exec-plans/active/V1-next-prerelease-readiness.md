# Next SDAQF Prerelease Release Readiness ExecPlan

## Status

`PLANNING_DIFF_ACCEPTED_GIT_PUBLICATION_PENDING_OWNER_RELEASE_METADATA_PENDING`

This is a living ExecPlan under `PLANS.md`. It plans a possible next SDAQF
prerelease after pull request #4; it does not authorize or perform a version
change, tag, release, deployment, or repository-setting change.

## Objective and measurable completion state

Prepare an evidence-backed readiness path for the next SDAQF prerelease from
the post-merge `main` state while preserving the published
`v1.0.0-rc.1` release and every historical review and Gate record.

This planning stage is complete when:

- post-merge current-status documentation states that pull request #4 and its
  exact pull-request CI completed, and that the resulting `main` merge commit
  passed its exact-triggering-SHA CI matrix;
- release direction, recommended milestone scope, compatibility boundaries,
  unresolved Owner decisions, future Gates, and stop conditions are explicit;
- documentation and public-contract tests, Ruff, the necessary strict type
  check, and `git diff --check` pass;
- three independent read-only reviewers ACCEPT the final planning diff with no
  unresolved Critical, High, or Medium finding; and
- the planning branch is published only through an explicitly staged English
  commit, normal push, English draft pull request, and successful exact pull-
  request CI.

The release-readiness stage remains open after this planning pull request. It
cannot complete until the Owner decides every release-metadata item below and a
later exact release candidate passes the full candidate-bound Gate sequence.

## Starting state and source requirements

- Repository boundary: `repo/` only; the parent workspace is local-only.
- Baseline branch: `main`.
- Baseline commit: `a6195e1aafcbcdd288b465cc9d8572df6d4e33ee`, the merge commit for
  pull request #4.
- Pull request #4 exact head CI: run `31558960113`, completed successfully for
  Windows and Linux on Python 3.12 and 3.13.
- Post-merge `main` exact-triggering-SHA CI: run `31563987706`, completed
  successfully for the same four required jobs.
- Worktree and index: clean before the planning branch was created.
- Published baseline: distribution version `1.0.0rc1`, annotated tag
  `v1.0.0-rc.1`, release title `SDAQF v1.0.0-rc.1`, prerelease true, no attached
  assets, no package-registry publication, and GitHub-provided source archives.

Repository implementation, tests, schemas, examples, milestone ExecPlans,
release contracts, and tracked publication records are the allowed evidence.
No credentials, personal data, private workspace reports, external-system
investigation, or network diagnostics belong in this plan.

## Release direction

The recommended direction is **prepare the next prerelease**, not **release
now** and not **prepare stable 1.0**.

M5 through M8 are implemented and independently have current GO dispositions,
but they remain Experimental and unreleased. They introduce a large linked
public surface after `v1.0.0-rc.1`, while macOS, independent production
deployment, hosted-agent operation, and third-party solver integration remain
unverified. A prerelease gives that surface an explicit evaluation boundary
before any stable compatibility commitment.

The recommended release scope is M5, M6, M7, and M8 together. M6 consumes M5
identity, M7 reuses M5 and M6 authority, and M8 composes all three. A source
archive from current `main` contains the complete linked implementation, so a
notes-only partial scope would not match the delivered source. Excluding a
milestone requires a separately designed code candidate and is outside this
planning change.

## Compatibility boundaries

- M5 publishes strict context schemas and additive `context` CLI behavior
  without widening the stable top-level Python exports.
- M6 keeps M6-only scheduler schema 1 as the default. M8 requires scheduler
  schema 2; movement from schema 1 to 2 is explicit, Owner-approved,
  copy-on-write, and never an automatic in-place migration or downgrade.
- M7 remains a bounded, exact finite-domain reference solver. Approximate
  semantics, new result states, or executable external adapters require a new
  contract decision.
- M8 preserves existing genesis call shapes and adds predecessor scheduler
  authority only for successor lineage.
- Documented CLI behavior, published JSON schemas, and `sdaqf.__all__` are the
  intended public surface. Other Python modules remain prerelease
  implementation details unless the Owner explicitly broadens that boundary.

The historical M5 and M6 NO-GO records, the later M6 review stop, M8 review
caveats, finding severities and counts, past candidate records, and past Gate
results remain immutable historical evidence. Current GO dispositions do not
rewrite those checkpoints and do not establish release GO or production
readiness.

## Owner decision register

No row below is implicitly approved by this plan.

| ID | Decision | Recommendation | Status |
|---|---|---|---|
| `NP-D1` | Release direction | Prepare another prerelease; do not promote directly to stable 1.0 | `OWNER_DECISION_REQUIRED` |
| `NP-D2` | Included scope | Include M5 through M8 together | `OWNER_DECISION_REQUIRED` |
| `NP-D3` | Distribution version | Select a new unused PEP 440 prerelease version in the target 1.0 line; do not assume `1.0.0rc2` | `OWNER_DECISION_REQUIRED` |
| `NP-D4` | Git tag | Select a new unused tag that maps exactly to the approved version | `OWNER_DECISION_REQUIRED` |
| `NP-D5` | Release title | Select a title consistent with the approved tag and SDAQF naming | `OWNER_DECISION_REQUIRED` |
| `NP-D6` | Release notes | Approve a new notes path and content covering M5-M8, compatibility, migrations, limits, evidence, and rollback; do not edit the rc1 notes | `OWNER_DECISION_REQUIRED` |
| `NP-D7` | GitHub release flags | `prerelease: true`, `latest: false` | `OWNER_DECISION_REQUIRED` |
| `NP-D8` | Artifact composition | GitHub source archives only, no attached assets, and no package-registry publication | `OWNER_DECISION_REQUIRED` |
| `NP-D9` | Release QA contract | Add a new versioned candidate contract after metadata approval; do not mutate the rc1-literal schema or loader behavior | `OWNER_DECISION_REQUIRED` |
| `NP-D10` | Stable 1.0 exit criteria | Reassess only after the new prerelease has release-specific evidence and observed feedback | `OWNER_DECISION_REQUIRED` |

Before `NP-D3` through `NP-D5` are approved, confirm only availability and
consistency of the proposed version, tag, and title. Availability checking does
not reserve or create a tag or release.

## Scope of this planning change

This planning change may:

- add this living ExecPlan;
- reconcile only current-status statements made stale by pull request #4;
- update public-contract assertions that protect the reconciled facts; and
- record validation and independent final-review results in this plan.

It must not:

- change `pyproject.toml`, `src/sdaqf/__init__.py`, runtime code, schemas,
  examples, evaluation fixtures, or release QA behavior;
- edit `docs/releases/v1.0.0-rc.1.md`, the published release, the
  `v1.0.0-rc.1` tag, or rc1-specific metadata and Gate evidence;
- create a candidate fingerprint or hash list;
- merge a pull request, select or change a version, create a tag or release,
  upload an artifact, publish a package, or deploy anything; or
- rewrite historical NO-GO, review caveat, finding-count, or Gate-result text.

## Checkpoints and validation

### Checkpoint 0 - post-merge preflight

- [x] Confirm pull request #4 is merged.
- [x] Confirm remote `main` resolves to its merge commit.
- [x] Confirm exact pull-request CI run `31558960113` passed all four required
  jobs.
- [x] Confirm exact post-merge `main` CI run `31563987706` passed all four
  required jobs.
- [x] Confirm the starting worktree and index are clean.

### Checkpoint 1 - independent readiness assessment

- [x] Obtain three independent read-only assessments for M5-M8 scope and
  compatibility, release metadata and Gates, and historical/document/test
  consistency.
- [x] Record the shared recommendation to prepare the next prerelease and the
  shared rejection of direct stable 1.0 preparation.
- [x] Identify post-merge current-status drift and the missing next-prerelease
  living plan as the required planning remediations.

### Checkpoint 2 - minimal planning implementation

- [x] Reconcile the M6 active ExecPlan and current-status documents without
  altering historical checkpoints.
- [x] Add public-contract assertions for the post-merge facts and this plan.
- [x] Confirm the diff does not modify rc1 metadata, notes, release QA, schemas,
  runtime behavior, or published-release records.
- [x] Pass 106 focused documentation and public-contract tests, the publication
  audit, Ruff, strict mypy over 180 source files, and whitespace checks.

Run from the repository root:

```text
python scripts/run_local_gate.py pytest tests/test_public_artifacts.py tests/test_v1_public_contracts.py tests/test_v1_release_readiness.py tests/test_m6_public_contracts.py tests/test_m8_public_contracts.py
python scripts/run_local_gate.py publication
python scripts/run_local_gate.py ruff
python scripts/run_local_gate.py mypy
git diff --check
```

### Checkpoint 3 - final planning review and pull request

- [x] Obtain three fresh independent read-only final-diff reviews.
- [x] Require all three reviewers to ACCEPT with zero unresolved Critical,
  High, or Medium finding.
- [ ] Explicitly stage only the reviewed planning paths, create an English
  commit, normally push the branch, and open an English draft pull request.
- [ ] Confirm the draft pull request's exact head SHA passes every required CI
  job.

### Checkpoint 4 - Owner-approved candidate design

This later checkpoint begins only after `NP-D1` through `NP-D10` are explicit.
Implement the chosen version and metadata as a new candidate. Preserve rc1
contracts and records; add versioned release QA behavior where needed. Add or
update release notes, changelog current entries, compatibility guidance,
package metadata, and contract tests only inside a separately approved scope.

### Checkpoint 5 - exact candidate readiness

Run the complete Release Contract without lowering any threshold: full pytest,
coverage, Ruff, strict mypy, M5-M8 named validators, offline CLI smoke,
evaluation reproduction, workspace/publication/dependency audits, `pip check`,
and `git diff --check`. Require a clean exact Git candidate, candidate-bound
G1-G4 evidence, three independent ACCEPT reviews, and successful exact-SHA CI
for the approved Windows/Linux Python 3.12/3.13 matrix. macOS remains
`NOT_VERIFIED` unless actually observed for that exact candidate.

No fingerprint or hash list is part of this planning work. A later release may
refer to its exact Git commit and contract-required evidence only after the
Owner approves that candidate workflow.

### Checkpoint 6 - separately authorized publication

Tag creation, release creation, flags, notes, artifact upload, package
publication, repository settings, and post-publication observation are separate
Owner approval boundaries. A failure or ambiguity stops the sequence; no prior
success compensates for a failed Gate.

## Risks and assumptions

- The next prerelease exposes M5-M8 for the first time, so compatibility risk is
  materially higher than the planning-only diff.
- The current rc1-specific release QA schema and loader intentionally contain
  rc1 literals. Mutating them would destroy historical contract meaning;
  additive versioning is required for a new candidate.
- Source-only delivery is the lowest-complexity artifact recommendation. Any
  wheel, sdist, package-registry, or attached-asset decision adds build,
  provenance, installation, checksum, allowlist, and rollback Gates.
- Exact-SHA CI supports only the commit and matrix observed. It is not evidence
  for macOS, production deployment, hosted agents, or third-party solvers.
- The plan assumes no runtime or schema change is needed merely to describe the
  next candidate. A contrary finding stops this scope and requires a new plan.

## Stop conditions

Stop before staging, commit, push, or pull-request creation if any requested
Gate fails, any Critical, High, or Medium finding remains, any reviewer does not
ACCEPT, or the diff touches an unintended or protected path.

Stop and request Owner direction before any scope, version, tag, title, notes,
flag, artifact, compatibility, dependency, license, security-policy, stable-API,
or release-QA decision. Also stop before merge, tag, release, deployment,
package publication, asset upload, repository-setting change, destructive
cleanup, history rewrite, force push, credential access, or paid action.

## Technical sandbox handling

Use `scripts/run_local_gate.py` so caches, bytecode, pytest state, coverage data,
and other temporary outputs remain in an owned system-temp fixture and are
removed after each command. If a required command is denied by the sandbox,
classify the denial before requesting one minimum technical approval for the
exact command. A technical approval never replaces an Owner decision or
external-action approval.

## Language and publication boundaries

Tracked text, branch names, commits, and GitHub-facing metadata are English.
No private parent-workspace report or personal information may be copied into
the repository. This plan may publish only a draft planning pull request after
its Gates; it cannot publish a SDAQF release.

## Decision log

- 2026-08-12: Selected **prepare the next prerelease** as the evidence-backed
  recommendation. Direct stable 1.0 preparation is not supported while M5-M8
  are Experimental and first-release evidence remains outstanding.
- 2026-08-12: Recommended M5-M8 as one source candidate because their contracts
  form a dependency chain and current `main` delivers them together.
- 2026-08-12: Kept version, tag, title, notes, GitHub flags, and artifacts as
  explicit Owner decisions. In particular, no `rc2` value is assumed.
- 2026-08-12: Protected all rc1 metadata, notes, release QA, tags, and published
  release facts; a future candidate must use additive versioned release QA.

## Progress log

- 2026-08-12: Verified pull request #4 merge, exact pull-request CI, post-merge
  `main` exact-SHA CI, and a clean starting worktree.
- 2026-08-12: Three independent read-only assessments found no Critical or High
  blocker. They converged on the next-prerelease recommendation and identified
  the same post-merge documentation drift; the document/test reviewer also
  identified the absence of this living plan.
- 2026-08-12: Added this plan, reconciled only the post-merge current-status
  boundary, added focused public-contract assertions, and confirmed that no rc1
  metadata, notes, release QA, schema, runtime, or published-release path is in
  the diff.
- 2026-08-12: Passed 106 focused tests, the publication audit, Ruff, strict
  mypy over 180 source files, tracked `git diff --check`, and the equivalent
  no-index whitespace check for this then-untracked plan.
- 2026-08-12: Three independent read-only final-diff reviewers each returned
  ACCEPT. No reviewer reported a finding, and unresolved Critical, High, and
  Medium findings are zero.
