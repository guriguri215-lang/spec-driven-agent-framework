# M2 Verification Evidence

## Scope and reconciled source

- Milestone: M2 Agent, Skill, and Tool Orchestration.
- Primary folder and Git root: `repo/`.
- Original starting branch and HEAD:
  `main` at `0439176075e7509dc3874b329e40866c465af5fb`.
- Original starting worktree: clean.
- Approved remote: `origin` only, with fetch and push URL
  `https://github.com/guriguri215-lang/spec-driven-agent-framework.git`.
- GitHub target: private repository
  `guriguri215-lang/spec-driven-agent-framework`, default branch `main`.
- Public specification SHA-256:
  `89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5`.
- Authoritative source provenance SHA-256:
  `F28E02029768F80816001BD98DA43739F4BA33C1197710E02B1E20786EAD188B`.

The starting GitHub Actions run `30313165027` failed all four matrix jobs.
Linux strict mypy rejected a Windows-only stat attribute, and Windows checkout
line-ending conversion changed the canonical specification digest. The
separate baseline commit
`eff9e3abfa6aff3e22d71b23140e838cd222832a` fixed portable stat access,
enforced LF checkout bytes, and strengthened exact fetch/push remote
validation. Workflow run `30362714857` succeeded for that exact baseline SHA
on Windows and Linux with Python 3.12 and 3.13.

## Delivered behavior

M2 provides strict Agent and Tool Registries, cross-reference validation,
deterministic budgeted role selection, explicit native Subagent host planning,
independent-session and sequential fallback prompts, safe read-parallel
selection, isolated-write ownership plans, logical implementation/review
separation, structured agent summaries, and evidence-based disagreement
resolution.

It also provides repository Skill and template lifecycle validation, safe
registered version probes, strict versioned single-execution approvals with
distinct authority, expiry, exact conditions, and persistent atomic
pre-execution consumption, resolved executable use, sanitized process
environments, bounded concurrent stdout/stderr drains, timeout and denial
classification, optional-tool isolation, bounded retry, atomic checkpoints,
backup recovery, strict resume identity, M2 CLI commands, schemas, samples,
documentation, audits, and CI parity.

The runtime uses only the Python standard library. M2 does not add a production
dependency, launch a nested Codex process, automatically create or integrate a
Git worktree, perform live web research, implement the M3 Claim-Evidence
Ledger, select a license, publish a release, or deploy.

## Local command evidence

| Check | Exact command or contract | Result |
|---|---|---|
| Unit, negative, boundary, failure-injection, and regression tests | `python -m pytest` | PASS, 375 passed and one environment skip |
| Lint | `python -m ruff check src tests scripts` | PASS |
| Strict typing | `python -m mypy src tests scripts` | PASS, 70 source files |
| Instrumented tests | `python -m coverage run -m pytest` | PASS, 375 passed and one environment skip |
| Total branch coverage | `python -m coverage report --fail-under=80` | PASS, 91 percent |
| Critical M1 branch coverage | Release Contract M1 include command | PASS, 94 percent |
| Critical M2 branch coverage | Release Contract M2 include command | PASS, 90 percent |
| Preserved and primary CLI smoke | `python scripts/run_cli_smoke.py` | PASS |
| Canonical M1 and Gate G1 | canonical ingest and `gate requirements` inside CLI smoke | PASS |
| Schema and sample parity | complete pytest public-artifact and runtime-loader tests | PASS |
| Git boundary | Release Contract exact-origin boundary command | PASS |
| Secret, personal path, language, link, and project-license audit | `python scripts/audit_repository.py --root . --workspace-parent ..` | PASS |
| Runtime, lock, dependency-license audit | `python scripts/audit_dependencies.py --root .` | PASS |
| Installed dependency consistency | `python -m pip check` | PASS |
| Patch whitespace | `git diff --check` | PASS |

The skipped test attempts to create a real symbolic link, which is unavailable
in this Windows environment. Simulated Windows reparse-point rejection and all
link checks pass. No threshold, assertion, matrix entry, or security Gate was
weakened.

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| `AC-M2-001` | PASS | strict bounded Agent Registry, unique role, cross-reference, schema, and sample tests |
| `AC-M2-002` | PASS | deterministic role, risk, scale, parallelism, agent, concurrency, and reasoning-budget tests |
| `AC-M2-003` | PASS | native host mode, independent-session mode, sequential fallback, and no nested process contract |
| `AC-M2-004` | PASS | read-heavy allowlist and writable-role/same-worktree rejection tests |
| `AC-M2-005` | PASS | distinct worktree, owner, path, base, and separate integrator tests |
| `AC-M2-006` | PASS | bounded results, self-review rejection, later review wave, and equal-evidence unresolved tests |
| `AC-M2-007` | PASS | CRLF-safe Skill validation and template lifecycle, provenance, license, and blocker tests |
| `AC-M2-008` | PASS | strict Tool Registry command, platform, scope, network, risk, optionality, and approval tests |
| `AC-M2-009` | PASS | presence, version, optional absence, unsupported platform/version, timeout, permission, and exit-state tests |
| `AC-M2-010` | PASS | argument array, resolved executable, no shell, sanitized environment, timeout, duration, and bounded-reader tests |
| `AC-M2-011` | PASS | shell, inline code, global install, destructive executable, path, origin, strict approval provenance/lifetime/expiry, exact-scope, atomic claim, concurrent claim, and cross-CWD/cross-invocation reuse rejection tests |
| `AC-M2-012` | PASS | state, atomic publish, backup cleanup/recovery, invariant, resume mismatch, and bounded-retry tests |
| `AC-M2-013` | PASS | sandbox, permission, network, authentication, authorization, test, workflow, and service classifications |
| `AC-M2-014` | PASS | runtime/schema/sample parity and bounded machine-readable M2 CLI tests |
| `AC-M2-015` | PASS | full M0/M1 suite, canonical digest and counts, CLI smoke, and Gate G1 |
| `AC-M2-016` | PASS | empty runtime dependencies, exact development lock, explicit license/provenance, no web claim |
| `AC-M2-017` | PARTIAL | Windows and Python 3.12 local PASS; Linux/Python 3.13 require exact-SHA CI; macOS NOT VERIFIED |
| `AC-M2-018` | PASS | coverage thresholds passed; independent review returned GO with no unresolved Critical, High, or Medium finding |

## Independent review

Status: `GO`, with no unresolved Critical, High, or Medium finding. Read-only
review covered requirement and architecture boundaries, M1 regression,
worktree races, command injection, traversal, bounded output, timeout/retry,
approval provenance and reuse, secret/personal-data exposure, optional
isolation, cross-platform and workflow parity, maintainability, dead code, and
scope drift. The review found and verified fixes for direct approval assertion,
stale generated-state evidence, cross-execution approval reuse, and
working-directory-dependent consumption. The final focused review confirmed
registry-anchored cross-CWD consumption, atomic pre-process claims, safe
concurrency, fail-closed corruption and lock handling, and truthful evidence.

## Sandbox, network, and approval evidence

The Owner authorized read-only inspection of the existing GitHub
authentication state, approved private repository metadata, remote HEAD, and
Actions runs, plus normal pushes of inspected commits to the exact private
`origin/main`. No credential or token content was read, displayed, stored, or
changed; no login or GitHub setting was changed.

Technical sandbox elevation was used only for the approved read-only GitHub
queries and normal baseline push when the Windows execution environment
required it. Git's per-command `safe.directory` option was used after a
dubious-ownership denial; no global configuration was changed. No M2 local
quality command required technical elevation. An untracked generated
`.local/state/gh/device-id` was detected without reading its content, excluded
through `.gitignore`, and removed again after host tooling regenerated it
during the final Gate run. The final candidate check confirmed `.local/` was
absent.

## Residual and external verification

- Windows with Python 3.12: verified locally.
- Linux and Python 3.13: pending the exact M2 commit GitHub Actions matrix.
- macOS: `NOT VERIFIED`.
- Real symbolic-link creation on this Windows host: `NOT VERIFIED`; simulated
  reparse and deterministic rejection tests pass.
- Current network-backed vulnerability advisory state: `NOT VERIFIED`; the
  runtime dependency set is empty.
- The final M2 commit identity, clean worktree, private visibility,
  `origin/main`, and exact-SHA CI result are reported outside this document to
  avoid self-referential commit content.
- M3 evidence/UI/release automation, release, tag, PR, issue, discussion, and
  deployment remain intentionally unimplemented.
