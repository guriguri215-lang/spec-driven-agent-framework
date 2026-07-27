# M1 Verification Evidence

## Scope and reconciled source

- Milestone: M1 Requirements and Planning MVP.
- Primary folder and Git root: `repo/`.
- Starting branch: `main`.
- Starting HEAD: `75dcc31a837c2456bec3d70bcdd2da45af42d111`.
- Starting worktree: clean.
- Remote: none.
- Public specification file SHA-256:
  `89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5`.
- Authoritative source provenance SHA-256:
  `F28E02029768F80816001BD98DA43739F4BA33C1197710E02B1E20786EAD188B`.

The public specification file digest differs by design from the private source
digest recorded in its Provenance section. The embedded source digest matches
the M0 evidence and M1 handoff. The branch, starting commit, clean worktree,
absence of remotes, and intended M1 scope also matched the handoff. Parent
`state/` was neither read nor written.

## Delivered behavior

M1 provides bounded UTF-8 Markdown ingestion, deterministic requirement
normalization, acceptance criteria, verification methods, source and downstream
trace fields, diagnostics, strict baseline loading, structured Owner approvals,
baseline comparison, four planning and prompt artifacts, Goal suitability, and
Gate G1. The canonical public specification produces baseline
`RB-89340E628F631CEE`, 228 normalized records, 23 source acceptance criteria,
21 recorded non-blocking diagnostics, and nine open decisions. Gate G1 passes
with 217 Must requirements.

The implementation uses the Python standard library at runtime. It does not add
agent orchestration, worktree automation, release automation, UI validation,
GitHub publication, remote operations, tags, releases, or deployment.

## Command evidence

| Check | Command | Result |
|---|---|---|
| Unit, negative, boundary, and regression tests | `python -m pytest` | PASS, 167 passed and one environment skip |
| Lint | `python -m ruff check src tests scripts` | PASS |
| Strict typing | `python -m mypy src tests scripts` | PASS, 50 source files |
| Instrumented tests | `python -m coverage run -m pytest` | PASS, 167 passed and one environment skip |
| Total branch coverage | `python -m coverage report --fail-under=80` | PASS, 93 percent |
| Critical M1 branch coverage | Release Contract `coverage report --include=... --fail-under=90` command | PASS, 94 percent |
| Preserved CLI smoke | `doctor`, `init --dry-run`, `validate`, `status`, and `goal-template` | PASS |
| M1 CLI smoke | `ingest`, `compare`, `roadmap`, `exec-plan`, `goal`, `prompt`, and `gate requirements` | PASS |
| Canonical primary path | Ingest `docs/specification.md`, generate all artifacts, and evaluate Gate G1 | PASS |
| Git boundary | `python scripts/check_workspace_boundary.py --repo .` | PASS |
| Publication audit | `python scripts/audit_repository.py --root . --workspace-parent ..` | PASS |
| Installed dependency consistency | `python -m pip check` | PASS |
| Patch whitespace | `git diff --check` | PASS |

The skipped test attempts to create a real symbolic link, which this Windows
environment does not permit. Link rejection remains covered by the ingestion
implementation, and simulated Windows reparse-point rejection passes in the
publication audit tests. This skip does not weaken a threshold or convert a
failed assertion into a pass.

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| AC-M1-001 | PASS | Bounded safe-ingestion tests cover missing, linked, non-Markdown, oversized, invalid UTF-8, NUL, and changing input |
| AC-M1-002 | PASS | Determinism and explicit/generated identifier regression tests |
| AC-M1-003 | PASS | Six requirement types and case-insensitive Must, Should, and Could normalization tests |
| AC-M1-004 | PASS | Runtime, loader, schema, and direct Gate checks require linked acceptance and verification for every record |
| AC-M1-005 | PASS | Exact source trace and explicit empty-or-populated downstream trace contracts |
| AC-M1-006 | PASS | Deterministic ambiguity, contradiction, duplicate, assumption, and unverifiable-language diagnostics |
| AC-M1-007 | PASS | Eight comparison categories and baseline-pair-scoped structured Owner approval tests |
| AC-M1-008 | PASS | Roadmap generation tests preserve scope and Release Contract separation |
| AC-M1-009 | PASS | Living ExecPlan contract and generated-section tests |
| AC-M1-010 | PASS | Inert-source and English Goal and Standard prompt tests |
| AC-M1-011 | PASS | Single-objective suitability and fail-closed Standard fallback tests |
| AC-M1-012 | PASS | Gate G1 negative and canonical passing-path tests |
| AC-M1-013 | PASS | Machine-readable CLI, bounded errors, exclusive atomic output, and disclosure tests |
| AC-M1-014 | PASS | Empty runtime dependency set, offline execution, preserved M0 commands, and M2/M3 exclusion tests |
| AC-M1-015 | PASS | Full test, lint, type, coverage, CLI, boundary, and publication command set |

## Independent review

An independent read-only reviewer inspected the candidate without editing,
running tests, staging, committing, accessing parent state, or using the
network. The initial review found no Critical issue and identified approval,
identifier, acceptance-link, priority, scope, prompt, atomic-output, schema,
and validation hardening opportunities. Each finding received a focused
regression test and implementation correction. The final re-review returned
GO with no remaining Critical, High, or Medium finding.

## Sandbox and approval evidence

No mandatory M1 command encountered a sandbox, permission, or network denial.
No Technical sandbox approval was requested. One early CLI smoke attempt failed
because a test cleanup had removed its ignored temporary input baseline; this
was classified as missing test input, regenerated under the ignored
repository-local temporary directory, and passed. Initial lint, typing, test,
and coverage findings were classified as quality failures and corrected
without reducing any threshold.

No Owner approval was consumed. M1 did not add a production dependency, weaken
a Must requirement, choose a license, perform a destructive operation, access
credentials, transfer data externally, incur a charge, create a remote, push,
post to GitHub, publish a tag or release, or deploy.

## Residual limitations

- Live dependency-advisory state is `NOT VERIFIED` because no network scan was
  authorized or needed for the empty runtime dependency set.
- Linux behavior is represented by repository CI configuration but was not
  executed locally.
- Real symbolic-link creation was unavailable in the local Windows test
  environment; deterministic simulated reparse-point coverage passed.
- M2 orchestration and M3 evidence, UI, and release automation remain
  intentionally unimplemented.
- The final commit identity and clean-worktree result are reported after commit
  outside this document to avoid a self-referential commit hash.
