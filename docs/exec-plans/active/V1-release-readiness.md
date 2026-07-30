# V1.0 Release Readiness ExecPlan

## Status

`LOCAL_IMPLEMENTATION_VERIFIED_A3_PENDING`

This is a living plan. The Owner decision matrix was presented on 2026-07-30.
The Owner subsequently approved every recommended decision and selected the
exact public copyright-holder text `guriguri215-lang`. `B0` and `D1` through
`D7` are fully resolved. The Owner separately approved the exact local
implementation scope on 2026-07-30. That approval does not authorize staging,
commit, push, remote observation, tag, release, visibility, repository
settings, or any other external action.

Creating and maintaining this plan does not authorize a project license,
implementation, staging, commit, push, remote observation, tag, release,
visibility change, repository-setting change, or other external action.

## Objective

Use the immutable exact-SHA-green M4 Public Beta candidate as the evidence
baseline, resolve or explicitly defer every applicable Owner product and
publication decision, and reduce V1.0 readiness to one traceable and
verifiable scope. Preserve the offline-first, fail-closed, empty-runtime-
dependency, non-compensating Gate, exact-evidence, approval, security, and
publication boundaries established through M4.

Only an implementation scope that is rewritten to contain literal approved
decision values and separately approved by the Owner may proceed. Actual tag
creation, release creation or publication, and public visibility remain
separate external actions and are never performed automatically.

## Immutable baseline and starting snapshot

The M4 implementation subject remains the immutable behavioral baseline:

- subject commit:
  `452263c2bb2136a83cf8bf5c7252795ea4ce4190`;
- subject publication digest:
  `BEB2AD000FECE0E410046C6B0A870829650B129A834FA123FAD4D741C0184E58`;
- subject exact-SHA Actions run: `30548734324`, successful on Windows and
  Linux with Python 3.12 and 3.13;
- independent read-only review: `GO`, with no unresolved Critical, High,
  Medium, or Low finding;
- macOS: `NOT_VERIFIED`.

The later evidence-only attestation is the local planning start:

- branch: `main`;
- HEAD: `41d9071d10f97578e6da8786f69814b2c7ca954a`;
- parent: the immutable M4 subject above;
- worktree: clean at plan start;
- staged paths: zero at plan start;
- canonical specification SHA-256:
  `89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5`;
- publication digest:
  `A2C770680763BA1F6ED634E35230C7E1E3A6ADF19B250102CCF218DCA4543D34`;
- publication paths: 248;
- locally configured origin URL:
  `https://github.com/guriguri215-lang/spec-driven-agent-framework.git`;
- local tags: none.

The branch, HEAD, clean state, staged set, canonical digest, publication
digest, publication count, local tag set, and locally stored origin URL were
recalculated before this plan was created. No remote HEAD, GitHub metadata,
Actions state, repository setting, authentication state, or credential was
read during V1.0 startup.

The M4 subject is immutable evidence, not the eventual V1.0 candidate. A V1.0
candidate must receive a new exact identity and may not overwrite, relabel, or
retroactively extend the M4 claims.

## Owner decision register

| ID | Decision | Status | Approved value |
|---|---|---|---|
| `B0` | Project, repository, package, CLI, required CI matrix, and deferred extension identity | `APPROVED` | `SDAQF`; repository `spec-driven-agent-framework`; distribution/CLI `sdaqf`; Windows/Linux with Python 3.12/3.13 required; macOS optional and not verified; API/Agents SDK adapter and management UI deferred post-V1 |
| `D1` | Project license and exact public copyright-holder text | `APPROVED` | SPDX `Apache-2.0`; copyright holder `guriguri215-lang` |
| `D2` | Remain private or target a separately approved public-visibility change | `APPROVED` | remain private through local finalization; target public only at a separately approved Gate G5 boundary |
| `D3` | Public release level and target audience | `APPROVED` | release-candidate prerelease for framework evaluators and advanced Codex users; not for production use |
| `D4` | Python distribution version and exact Git tag | `APPROVED` | distribution `1.0.0rc1`; proposed tag `v1.0.0-rc.1`; final `1.0.0` requires a new candidate and approval |
| `D5` | Release title, notes, repository metadata, and artifact set | `APPROVED` | `SDAQF v1.0.0-rc.1`; prerelease true; latest false; approved description and notes outline; no attached assets or package-registry publication; GitHub tag archives only |
| `D6` | External contribution policy and Code of Conduct disposition | `APPROVED` | external pull requests not accepted during the release candidate; bug/documentation issues best effort; project Code of Conduct deferred until open contributions |
| `D7` | Support channel, security-disclosure channel, and maintenance commitment | `APPROVED` | GitHub Issues, best effort, no SLA, latest release only; private vulnerability reporting after separate setting approval when public; no prerelease backports; best-effort Critical fixes for final 1.0 for six months |

Every product decision is resolved. The Owner separately approved the exact
local implementation scope below on 2026-07-30. This does not authorize
staging, commit, push, remote observation, tag, release, visibility, repository
settings, or any other external action.

The private authoritative decision record is
`../state/V1_RELEASE_READINESS_DECISIONS.json`. It must never be copied,
staged, or committed.

## Applicable requirements and traceability

| Source | V1.0 readiness obligation | Planned evidence |
|---|---|---|
| V1.0 milestone baseline | Satisfy Must requirements, primary real-project flows, no known critical defects, and complete public installation, extension, security, and release operations | V1.0 completion matrix, full Gates, exact-candidate evidence, independent review |
| `FR-PLN-001` through `FR-PLN-010` | Maintain a separate living ExecPlan, exact criteria, approval stops, non-goals, and a next-session prompt | this plan, derived criteria, private handoff |
| `FR-QA-001` through `FR-QA-014` | Preserve exact claim/evidence identity, applicable tests, audits, truthful limits, and non-compensating blockers | unchanged G2/G3 behavior, V1.0 evidence records, negative tests |
| `FR-APR-001` through `FR-APR-016` | Bind every approval to one exact action, scope, lifetime, target, risk, and validation | decision record, approval sequence, action-by-action stop points |
| `FR-HOF-001` through `FR-HOF-008` | Record exact final state and create, but never execute, the next prompt | private progress, completion report, and next prompt |
| `FR-GIT-001` through `FR-GIT-020` | Preserve repository boundaries; approve metadata, license, default branch, tag, and English outbound content; audit disclosure before publication | local publication-readiness record, public documents, audit output, separately approved observations |
| `NFR-003`, `NFR-004`, `NFR-005` | Preserve platform truthfulness, offline core, and security boundaries | exact Windows/Linux matrix, truthful macOS status, no runtime network |
| `NFR-012`, `NFR-013`, `NFR-016` | Version compatibility and migrations; complete English public documentation | compatibility policy, migration statement, versioned schema and docs |
| `NFR-017`, `C-005`, `C-015` | Least privilege, offline planning, and Owner/technical approval separation | no network in local readiness; exact approval log |
| Release Contract | Preserve all local Gates, private candidate rules, exact-SHA CI, and a fresh public-release audit | unchanged commands plus decision-approved V1.0 additions |
| M4 evidence | Do not broaden authored evaluation, macOS, platform, or security claims beyond exact evidence | explicit known limitations and exact subject/candidate separation |

## Approved local implementation boundary

Authorized work is limited to the exact tracked paths and ignored
`.sdaqf/v1/` evidence listed below, plus private decision and handoff records
under `state/`. Stop before any newly required tracked path.

## Exact approved product values

- Project: `SDAQF`.
- Repository: `spec-driven-agent-framework`.
- Python distribution and CLI: `sdaqf`.
- Distribution/runtime prerelease version: `1.0.0rc1`.
- Target V1 public API line used by template compatibility: `1.0.0`.
- Proposed Git tag: `v1.0.0-rc.1`.
- Release title: `SDAQF v1.0.0-rc.1`.
- Release classification: prerelease true, latest false, not for production
  use.
- Audience: framework evaluators and advanced Codex users.
- Project license: `Apache-2.0`.
- Public copyright holder: `guriguri215-lang`.
- Repository description: `Offline-first specification-driven development
  and quality assurance for Codex-assisted projects.`
- Attached release assets: none.
- Package-registry publication: none.
- Source archives: GitHub-provided tag archives only.
- Required matrix: Windows and Linux with Python 3.12 and 3.13.
- macOS: optional and `NOT_VERIFIED` until actually run.
- External pull requests: not accepted during this release candidate.
- Bug and documentation issues: best effort.
- Project Code of Conduct: deferred until open contributions.
- Support: GitHub Issues, latest release only, best effort, no SLA.
- Security disclosure: GitHub private vulnerability reporting after a
  separately approved repository-setting change when the repository is
  public.
- Prerelease backports: none.
- Final 1.0 maintenance: best-effort Critical security and data-loss fixes for
  six months after final `1.0.0`; final `1.0.0` itself requires a new candidate
  and approval.
- OpenAI API or Agents SDK adapter and management UI: deferred post-V1.

## Exact approved local implementation scope

### New tracked paths

- `LICENSE`: the unmodified official Apache License 2.0 text.
- `NOTICE`: `SDAQF`, year 2026, and copyright holder
  `guriguri215-lang`, with no ASF attribution or implied affiliation.
- `SUPPORT.md`: the approved best-effort, no-SLA, latest-release-only support
  boundary.
- `docs/compatibility.md`: the target V1 public API, compatibility, schema,
  deprecation, and migration policy.
- `docs/releases/v1.0.0-rc.1.md`: the complete English prerelease notes source,
  initially truthful that publication and actual Gate G5 have not occurred.
- `schemas/release-candidate-v1.1.schema.json`: the selected-license local
  candidate contract.
- `schemas/public-release-candidate.schema.json`: the offline local
  publication-readiness contract.
- `tests/test_v1_license.py`.
- `tests/test_v1_release_readiness.py`.
- `tests/test_v1_public_contracts.py`.
- `tests/test_cli_v1.py`.

`CODE_OF_CONDUCT.md` is explicitly excluded.

### Exact existing paths to modify

- `pyproject.toml`;
- `src/sdaqf/__init__.py`;
- `src/sdaqf/domain/quality.py`;
- `src/sdaqf/application/release_qa.py`;
- `src/sdaqf/cli.py`;
- `scripts/audit_repository.py`;
- `scripts/audit_dependencies.py`;
- `scripts/run_cli_smoke.py`;
- `examples/m2-orchestration/template-registry.json`;
- `README.md`;
- `CHANGELOG.md`;
- `CONTRIBUTING.md`;
- `SECURITY.md`;
- `docs/architecture.md`;
- `docs/contributor-guide.md`;
- `docs/dependencies.md`;
- `docs/open-decisions.md`;
- `docs/release-contract.md`;
- `docs/roadmap.md`;
- `docs/schema-migrations.md`;
- `tests/test_audits.py`;
- `tests/test_cli_m2.py`;
- `tests/test_cli_m3.py`;
- `tests/test_m3_release_qa.py`;
- `tests/test_m4_public_contracts.py`;
- `tests/test_public_artifacts.py`;
- `tests/test_skills.py`.

No other tracked path is in the approved implementation scope. If a newly
discovered required path is outside this list, stop and present the exact path,
reason, test impact, and alternative before changing it.

### Version and public API behavior

- Set `[project].version` and `sdaqf.__version__` to `1.0.0rc1`.
- Set the default template compatibility input and the repository-authored
  template fixture to the target API line `1.0.0`; update only the directly
  related README command, smoke path, and tests.
- Define the target V1 public API as the documented CLI commands, exit and JSON
  contracts, published JSON schemas, and names exported through
  `sdaqf.__all__`. Internal modules remain unsupported implementation details.
- Preserve every existing schema version unless the new versioned
  release-candidate 1.1 contract explicitly supersedes it.
- Preserve `schemas/release-candidate.schema.json` version 1.0 unchanged and
  retain strict loading of its historical `not-selected` state.
- Document that `1.0.0rc1` is a prerelease of the target 1.0 API, not a stable
  or production-ready release.

### Apache-2.0 license behavior

- Add `[project].license = "Apache-2.0"` and exact license-file metadata for
  `LICENSE` and `NOTICE`; do not add a deprecated license classifier.
- Keep the official `LICENSE` text unmodified and validate its exact UTF-8 LF
  content digest.
- Validate the exact `NOTICE` product, year, and holder text and its content
  digest.
- Add release-candidate schema 1.1 with an exact selected-license object:
  SPDX expression `Apache-2.0`, paths and SHA-256 values for `LICENSE` and
  `NOTICE`, and holder `guriguri215-lang`.
- Continue to accept release-candidate schema 1.0 only for its historical
  unselected-license contract. It must fail against a repository that contains
  selected project-license material.
- Change repository and dependency audits from a blanket project-license
  rejection to an exact allowlist for this Apache-2.0 contract. Unknown,
  additional, conflicting, nested, linked, modified, or unapproved license
  material continues to fail closed.
- Do not relicense third-party dependencies, templates, Actions, or authored
  evaluation evidence. Preserve their original provenance and license records.

### Local publication readiness and actual Gate G5

Add the offline command:

```text
python -m sdaqf gate publication-readiness .sdaqf/v1/public-release-candidate.json --root . --baseline .sdaqf/v1/requirements-baseline.json --ledger .sdaqf/v1/claim-evidence-ledger.json --review .sdaqf/v1/independent-review.json --release-candidate .sdaqf/v1/release-candidate.json --specification docs/specification.md --json
```

The `.sdaqf/v1/` inputs and output are ignored private runtime evidence and
must never be staged. The command must not call GitHub, use credentials,
create a tag or release, or change visibility. Its terminal success state is
`LOCAL_READY`, not Gate G5 `PASS`.

The public-release-candidate schema and loader must bind:

- exact `main` branch, candidate HEAD, canonical specification digest,
  publication digest, and complete publication path set;
- project `SDAQF`, repository `spec-driven-agent-framework`, distribution and
  CLI `sdaqf`, version `1.0.0rc1`, and proposed tag `v1.0.0-rc.1`;
- desired public visibility and default branch `main`;
- Apache-2.0 expression, exact `LICENSE` and `NOTICE` digests, and holder
  `guriguri215-lang`;
- release-candidate prerelease level, approved audience, exact title,
  description, notes path and digest, prerelease/latest flags, no attached
  assets, no registry publication, and tag-source archives only;
- target V1 public API, compatibility, migration, rollback, support, security,
  six-month final maintenance, contribution, deferred Code of Conduct, and
  known-limitation dispositions;
- exact completed G1 through G4 results and independent-review identity;
- Windows/Linux Python 3.12/3.13 requirements and truthful macOS
  `NOT_VERIFIED`;
- explicit `publication_performed: false`.

Actual Gate G5 remains `NOT_RUN` until separately approved external actions
and separately approved read-only observations prove the public repository,
remote, default branch, exact commit, exact tag, release metadata, source-only
artifact set, visibility, private-vulnerability-reporting setting, and
outbound content. A local `LOCAL_READY` result may never be upgraded to Gate
G5 `PASS` by inference.

### Public documentation consistency

Reconcile the exact public documents listed above so they agree on version,
release level, audience, target public API, installation, compatibility,
migration, rollback, Apache-2.0 licensing, holder, contribution policy,
support, private security reporting, maintenance, source-only artifact set,
verified platforms, known limitations, and `NOT_PUBLISHED` status.

Do not modify `docs/specification.md`, any M0 through M4 verification evidence,
or the immutable M4 ExecPlan merely to rewrite history. The canonical
specification digest must remain unchanged. A later
`docs/evidence/V1-readiness.md` is permitted only in a separately approved
exact-SHA attestation phase after an immutable implementation subject and
successful required matrix exist.

Private state, approvals, runtime `.sdaqf/` evidence, personal paths,
credentials, authentication output, and raw logs remain excluded.

## Explicit non-goals

- Do not modify or relabel the immutable M4 subject or its exact-SHA evidence.
- Do not claim that the authored comparison is empirical, causal, blinded,
  randomized, independently replicated, statistically powered, or
  cost-comparable.
- Do not claim macOS verification without an actual exact-candidate run.
- Do not add a production dependency, paid API, OpenAI API, Agents SDK,
  network runtime, deployment, hosted service, management UI, or automatic
  browser.
- Do not weaken Gate G1 through G4, coverage thresholds, approval consumption,
  path/link checks, disclosure audits, or the empty runtime dependency set.
- Do not change a workflow, runner, secret, branch-protection rule,
  repository setting, credential, Git/Codex global setting, or user
  configuration.
- Do not create a tag, release, PR, issue, discussion, deployment, package
  publication, or visibility change as part of local finalization.
- Do not treat a plan, recommendation, local Gate, commit, private push, or
  remote read as authorization for a later external action.

## Derived completion criteria

- `AC-V1R-001`: Every applicable Owner decision is recorded individually as
  exact approved content or `DEFERRED`; no recommendation is recorded as an
  approval.
- `AC-V1R-002`: The implementation section contains only approved values,
  literal deliverables, exclusions, and public metadata before any product
  file is changed.
- `AC-V1R-003`: The immutable M4 subject identity and exact evidence remain
  unchanged and are distinguished from the V1.0 candidate.
- `AC-V1R-004`: Version, tag, release level, audience, public API,
  compatibility, migration, and changelog statements are mutually consistent.
- `AC-V1R-005`: License text, SPDX metadata, copyright-holder text, candidate
  record, audits, public documentation, and packaged material are either
  exactly consistent with the approved `D1` decision or remain in the
  fail-closed unselected state.
- `AC-V1R-006`: Runtime dependencies remain empty. Any proposed production
  dependency stops implementation until its exact package, version, license,
  reason, alternatives, and Owner approval are recorded.
- `AC-V1R-007`: G1 through G4, all historical behavior, canonical digest,
  approval/security invariants, platform truthfulness, and every existing
  threshold pass without weakening.
- `AC-V1R-008`: Local publication readiness is offline and side-effect-free,
  returns `LOCAL_READY` rather than Gate G5 `PASS`, and binds every approved
  outbound value to the exact candidate.
- `AC-V1R-009`: Negative tests reject decision, version, tag, license,
  visibility, metadata, artifact, documentation, support, security,
  contribution, approval, candidate-identity, and publication-state mismatch.
- `AC-V1R-010`: English public documents consistently cover installation,
  compatibility, migration, rollback, security, support, maintenance,
  contribution, license, verified platforms, artifact set, and known limits.
- `AC-V1R-011`: A local V1.0 candidate passes every Release Contract command,
  justified V1.0 additions, and independent read-only review with unresolved
  Critical/High/Medium findings equal to zero.
- `AC-V1R-012`: An exact candidate commit, private push, remote observation,
  visibility change, tag, release, and post-publication observation each
  remain separate approval boundaries.
- `AC-V1R-013`: Actual Gate G5 is `NOT_RUN` until approved external evidence
  proves the exact public state; failure or ambiguity never compensates or
  auto-retries.
- `AC-V1R-014`: Private state records exact results, unresolved work,
  approvals, publication status, and a next-session prompt that is created but
  never executed.

## Negative-test design before implementation

The approved implementation must add or adapt tests that fail closed for:

- any `UNDECIDED`, `DEFERRED`, missing, expired, reused, or wrong-scope
  decision or approval;
- distribution/runtime/changelog/tag/title/release-level disagreement;
- a stable `1.0.0` claim without an explicit public API and compatibility
  contract;
- prerelease metadata described as stable, latest, production-ready, or
  generally supported;
- absent, additional, nested, linked, modified, unknown, or conflicting
  project-license material;
- a license file or SPDX expression not bound to the exact Owner decision;
- any change to the empty runtime dependency set;
- missing migration or rollback guidance for a changed public contract;
- release notes containing CJK text, a private path, secret shape, credential,
  unsafe link, mutable local artifact, unsupported claim, or missing
  limitation;
- an artifact outside the exact approved allowlist;
- desired and observed visibility, default branch, repository, commit, tag,
  title, notes, or asset mismatch;
- an external observation that lacks exact target, command, timestamp,
  bounded output, approval, or candidate identity;
- a local readiness record that claims publication occurred or Gate G5
  passed;
- a publication record that treats local readiness as external proof;
- public contribution intake without the approved contribution and conduct
  disposition;
- public support or security instructions without the approved channel and
  maintenance statement;
- any regression in Gate G1 through G4, approval consumption, link/path
  boundaries, installation isolation, publication ordering, evidence
  provenance, or named non-compensating blockers.

Tests must preserve the existing negative assertions until an approved V1.0
contract replaces them with equally strict positive-and-negative behavior.
They may not simply delete M4 license or prerelease assertions to make a new
candidate pass.

## Verification sequence

After exact decisions and local implementation authorization:

1. Reconfirm the Git root, `main`, approved starting HEAD, worktree, staged
   set, canonical digest, publication digest, and locally stored origin URL.
2. Run focused version, license, publication-readiness, documentation,
   approval, security, CLI, and negative tests.
3. Reproduce canonical M1 behavior and every G1 through G4 negative boundary.
4. Run every local command in `docs/release-contract.md`, including total and
   M1/M2/M3/M4 critical coverage without threshold reduction.
5. Run any approved V1.0 critical coverage and public-contract additions.
6. Recompute the complete Git publication set, path count, canonical digest,
   repository digest, dependency state, and outbound-document digests.
7. Obtain a logically separate independent read-only review. Resolve all
   Critical, High, and Medium findings; do not self-approve.
8. Present the exact candidate identity, diff, staged set, results, known
   limits, and proposed next action to the Owner.
9. Stop. Commit, push, remote read, tag, release, and visibility remain
   unperformed unless each next action is separately approved.

## Approval sequence

Each boundary is independent and non-transitive:

1. `A0 PRODUCT DECISIONS`: exact `B0` and `D1` through `D7` values.
2. `A1 LOCAL IMPLEMENTATION`: literal path and behavior scope from the
   rewritten ExecPlan.
3. `A2 EXCEPTION`: exact dependency, workflow, runner, secret, or repository
   setting, only if unexpectedly required; otherwise prohibited.
4. `A3 LOCAL COMMIT`: exact reviewed staged paths, diff, author identity, and
   English message.
5. `A4 PRIVATE PUSH`: exact commit and private `origin/main`, normal
   fast-forward only.
6. `A5 REMOTE READ`: exact repository, command/API query, and metadata or
   Actions fields to observe.
7. `A6 EXACT-SHA ATTESTATION`: exact candidate run and required jobs; a retry
   after failure requires a diagnosed change and new candidate.
8. `A7 VISIBILITY CHANGE`: exact repository and `PRIVATE` to `PUBLIC`
   transition, only if `D2` approved it. This is an irreversible disclosure
   boundary even if visibility is later changed back.
9. `A8 TAG`: exact tag text, target SHA, annotation, local creation, and
   remote push. Local and remote tag actions must be stated explicitly.
10. `A9 RELEASE`: exact repository, tag, title, notes digest, prerelease/latest
    flags, and asset allowlist.
11. `A10 POST-PUBLICATION READ`: exact read-only verification of visibility,
    branch, commit, tag, release, notes, assets, and security/support state.

The final external ordering must be selected explicitly after `D2`, `D4`, and
`D5`. A private release that becomes public merely through a visibility change
is prohibited because it collapses the visibility and release approval
boundaries.

## Rollback and failure containment

### Before commit

Keep changes local and unstaged until reviewed. Roll back only the exact
V1.0-owned paths through an inspected reverse patch or removal of an exact
newly created path. Never use hard reset, destructive clean, broad checkout,
or deletion outside the declared scope. Recompute the starting identity after
rollback.

### After a local or private pushed commit

Do not rewrite history or force push. Correct an accepted defect through a new
focused commit after related Gates and read-only re-review. A pushed candidate
that fails exact-SHA CI remains recorded as failed and is never relabeled.

### Version and artifacts

The contents of a published version are immutable. Correct a released package
or artifact with a new version and new exact evidence; never replace an asset
silently. Because the decision-neutral recommendation attaches no custom
binary, any later approved asset addition must add its own build,
provenance, checksum, clean-install, and rollback criteria.

### License

License publication is not technically reversible: recipients may retain
rights already granted. A later license change is a new legal/product decision
and cannot retract prior distribution by a repository edit. Therefore an
incorrect or ambiguous license blocks visibility and release rather than
relying on rollback.

### Visibility

Changing a public repository back to private cannot retract clones, forks,
cached content, activity, or previously visible Actions information. Treat
the first public-visibility change as irreversible disclosure. Any audit
ambiguity stops before `A7`.

### Tag and release

Do not delete or move a published tag automatically. Do not delete, edit, or
replace a release automatically. Stop, preserve evidence, assess exposure,
and request an exact Owner decision for a corrective release, advisory,
deprecation notice, or exceptional removal. Security fixes follow coordinated
disclosure and must not be exposed through a public issue or premature patch.

## Stop conditions

Stop without repair, staging, commit, remote access, or external action for:

- any mismatch from the recorded branch, approved HEAD, clean/staged
  expectation, canonical digest, publication digest, or origin URL;
- an unresolved required Owner decision;
- a decision recommendation being treated as approval;
- private data, credential, personal path, unsafe link, generated artifact,
  unapproved license, or unsupported public claim;
- any need to weaken an existing Gate, negative test, invariant, or threshold;
- any production dependency, workflow, runner, secret, repository setting,
  license, or publication action without exact approval;
- an untruthful platform, comparison, security, compatibility, maintenance,
  or production-readiness claim;
- a failure that would require repeating a denied normal command unchanged;
- force push, history rewrite, broad staging, global configuration, admin
  shell, UAC bypass, full access, sandbox bypass, or `--yolo`;
- inability to keep local readiness distinct from actual Gate G5
  publication.

## Decision log

- 2026-07-30: Recalculated and matched the complete local starting snapshot
  without remote access.
- 2026-07-30: Presented an Owner decision matrix with recommendations and
  trade-offs before creating this plan.
- 2026-07-30: Created this decision-neutral plan with all values
  `UNDECIDED`; no recommendation was adopted as a decision.
- 2026-07-30: The Owner approved all recommended decisions and asked for a
  clarification of the public copyright-holder text. Recorded `B0` and `D2`
  through `D7` as approved, and recorded the Apache-2.0 part of `D1` as
  approved without inferring the remaining holder text.
- 2026-07-30: The Owner selected the exact public copyright-holder text
  `guriguri215-lang`. All product decisions are resolved. Rewrote the plan
  with literal approved values and an exact local implementation scope.
- 2026-07-30: The Owner separately approved the exact local implementation
  scope. This approval excludes staging, commit, push, remote observation,
  tag, release, visibility, and repository settings.
- 2026-07-31: Completed the approved local implementation and verification.
  No staging, commit, remote observation, or external action was performed.

## Progress log

- Read the complete required repository, specification, roadmap, Release
  Contract, architecture, open-decision, M4 evidence, M4 ExecPlan, and private
  M4 finalization sources.
- Confirmed that the current M4 contract deliberately rejects project-license
  files and accepts only `license_status: not-selected`; V1.0 license work
  therefore requires a fail-closed contract migration rather than a standalone
  file addition.
- Derived V1.0 traceability, conditional deliverables, non-goals, completion
  criteria, negative tests, verification, approval sequence, rollback, and
  publication separation.
- Added the exact Apache-2.0 license and NOTICE contract, Python distribution
  version `1.0.0rc1`, additive release-candidate schema `1.1`, offline
  publication-readiness declaration schema and CLI, approved public
  documentation, and fail-closed negative tests. Runtime dependencies remain
  empty and the historical release-candidate schema `1.0` remains unchanged.
- Bound every local G4 artifact to the candidate identity and require the
  exact eight non-compensating G4 checks, including `hard_blocker: true` for
  every check. Negative tests reject wrong identity, missing checks, additional
  checks, failed checks, and a compensating `hard_blocker: false` mutation.
- Passed the focused V1.0 suite with 18 tests, the full suite with 654 passed
  and three explicit Windows link-environment skips, Ruff, strict mypy across
  98 source files, CLI smoke, the three-project comparison with 14 named hard
  blockers and no aggregate score, repository publication audit,
  dependency/license audit, `pip check`, and `git diff --check`.
- Passed coverage without threshold reduction: total 91%, M1 94%, M2 90%,
  M3/V1 91%, and M4 92%.
- Rebuilt and clean-installed the `1.0.0rc1` wheel in ignored local evidence
  storage to verify package metadata, license inclusion, and import/version
  behavior. This local package is not a release asset and is not authorized
  for publication.
- Obtained a logically separate independent read-only review: `GO`, with
  unresolved Critical/High/Medium/Low findings `0/0/0/0`.
- The current worktree remains unstaged and is not an immutable exact-SHA V1
  candidate. The required Windows/Linux Python 3.12/3.13 exact-SHA matrix has
  not been observed for V1, macOS remains `NOT_VERIFIED`, and actual Gate G5
  remains `NOT_RUN`.
- Stop at the `A3 LOCAL COMMIT` boundary. A separately approved exact staged
  path set, reviewed diff, author identity, and English commit message are
  required before staging or committing.
