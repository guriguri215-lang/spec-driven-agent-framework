# M4 Verification Evidence

## Scope

M4 Public Beta Hardening adds representative sample projects, comparative
evaluation, explicit registry migration, cross-platform evidence contracts,
and hardened contributor documentation. V1.0 and Gate G5 publication remain
out of scope.

## Starting identity

- Branch: `main`.
- Starting HEAD: `889c4fab5ee56cc937385eb9d2080e6c5d35eeb8`.
- Starting worktree: clean with zero staged paths.
- Canonical specification SHA-256:
  `89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5`.
- Starting publication digest:
  `FF6B50131C807DEF514726B5ACF238111C1102BBADBBAF4B53B5FF93275BAF67`
  across 193 paths.

The local branch, HEAD, worktree, staged set, canonical digest, publication
digest, and approved origin URL matched the private M3 handoff. No remote HEAD,
GitHub metadata, authentication, or Actions state was read during M4 startup.

## Delivered behavior

- Three sample project classes with exact normalization projections.
- Parity-bound structured and ordinary-unstructured evaluation records.
- Deterministic missed-requirement, scope-addition, critical-defect, rework,
  approval, handoff, trace, decision, evidence, and cost-availability metrics.
- Non-compensating Must, security, data-loss, and disclosure blockers and no
  aggregate score.
- Explicit Agent and Tool Registry 1.0-to-2.0 migration with conservative
  defaults, strict current-loader validation, exclusive output, and rollback.
- Public setup, contribution, evaluation, migration, extension, architecture,
  testing, security, and release-limit documentation.

## Evaluation evidence

`evals/results/public-beta-comparison.json` is reproduced from
`evals/comparison-suite.json`. Each run evidence item is bound to a typed,
status-bearing, timestamped tracked artifact by safe relative path and exact
SHA-256. The tracked comparison is an authored scenario fixture, not an
independently executed Codex session or a blind, randomized, independently
replicated, cost-comparable, empirical, or causal benchmark. See
`docs/evaluation.md`.

## Local command evidence

| Check | Exact command or contract | Result |
|---|---|---|
| Negative, boundary, migration, evaluation, and regression tests | `python -m pytest` | PASS, 625 passed and three Windows environment skips |
| Lint | `python -m ruff check src tests scripts` | PASS |
| Strict typing | `python -m mypy src tests scripts` | PASS, 94 source files |
| Total branch coverage | `python -m coverage report --fail-under=80` | PASS, 91 percent |
| Critical M1 branch coverage | Release Contract M1 include command | PASS, 94 percent |
| Critical M2 branch coverage | Release Contract M2 include command | PASS, 90 percent |
| Critical M3 branch coverage | Release Contract M3 include command | PASS, 91 percent |
| Critical M4 branch coverage | Release Contract M4 include command | PASS, 93 percent |
| M0 through M4 CLI smoke | `python scripts/run_cli_smoke.py` | PASS |
| Tracked comparison reproduction | `python -m sdaqf eval validate evals/comparison-suite.json --result evals/results/public-beta-comparison.json --json` | PASS, three projects and ten named ordinary-arm hard blockers |
| Workspace boundary | `python scripts/check_workspace_boundary.py --repo . --expected-origin-url https://github.com/guriguri215-lang/spec-driven-agent-framework.git` | PASS |
| Publication audit | `python scripts/audit_repository.py --root . --workspace-parent ..` | PASS |
| Dependency and license audit | `python scripts/audit_dependencies.py --root .` | PASS; runtime dependency set remains empty |
| Installed dependency consistency | `python -m pip check` | PASS |
| Whitespace | `git diff --check` | PASS |

The three skips are explicit fail-closed link-boundary tests: symbolic-link
creation was unavailable for the existing ingest test and the new migration
file-link and directory-link tests. Equivalent rejection logic remains covered
through deterministic injected and lexical-boundary tests. No test failure was
ignored.

## Verification status

Every local Release Contract Gate passes for the current uncommitted
publication candidate. The canonical specification digest remains unchanged,
the branch remains `main`, the starting HEAD remains checked out, and the
staged set remains empty.

Candidate-bound Windows/Linux Python 3.12/3.13 evidence is pending. The
successful M3 matrix is not reused as M4 evidence. The milestone must not be
reported complete until the platform record binds all required successful
jobs to an exact M4 commit. Independent read-only review is `GO`, with no
unresolved Critical, High, or Medium finding.

macOS is `NOT VERIFIED` because no macOS execution environment is available.
No production dependency, project license, workflow, runner, repository
setting, commit, push, or external publication has been added or performed.

The first independent read-only review returned `NO-GO`, with
Critical/High/Medium = 0/3/4. Its findings covered comparison evidence
provenance, migration Owner approval, failure cleanup, open cause analysis,
Agent/tool cross-reference, intervention identity, and immutable source
identity. All seven findings were accepted and remediated in the candidate;
focused verification passed. The first final re-review confirmed those seven
mechanical remediations but returned `NO-GO`, with 0/0/2 new findings: verified
cause analysis could cite non-passing evidence, and the exact migration
approval did not bind its companion Tool Registry. Both findings were accepted
and remediated by PASS-evidence validation and companion snapshot path/digest
binding. The second final re-review found one Medium runtime/schema parity issue:
migration path suffix handling and companion nullability were not expressed
identically by runtime and both public schemas. Runtime and schemas now require
lowercase `.json` paths, Agent migrations require a non-null companion path and
digest, and Tool migrations require both values to be null. Bidirectional
negative tests cover these rules. The final independent read-only re-review is
`GO`, with Critical/High/Medium = 0/0/0.
