# M0 Verification Evidence

## Scope and source

- Milestone: M0 Bootstrap Foundation.
- Source SHA-256:
  `F28E02029768F80816001BD98DA43739F4BA33C1197710E02B1E20786EAD188B`.
- Environment: Windows, Python 3.12.13, Git 2.54.0.
- Current Codex session: `CURRENT_SESSION_ACTIVE`.
- External Codex CLI: previous
  `PERMISSION_DENIED_NONBLOCKING`; current `NOT_CHECKED_NONBLOCKING`.
- Codex client version: `NOT VERIFIED`.

The external Codex CLI was not executed during this resumed run. Goal mode and
read-only subagents were observed in use.

## Command evidence

| Check | Command summary | Result |
|---|---|---|
| Python selection | Owner-specified launcher sequence, then bundled Python version | PATH launchers unavailable; safe bundled Python 3.12.13 selected |
| Development environment | Create `repo/.venv` from selected Python | PASS |
| Pinned tools | Install `requirements-dev.lock` into `repo/.venv` | PASS after narrow PyPI network approval |
| Dependency consistency | `python -m pip check` | PASS |
| Editable package build | Offline, no-isolation, no-dependency editable install | PASS |
| Installed CLI help | Isolated-environment `sdaqf --help` | PASS |
| Tests | `python -m pytest` | PASS, 60 tests |
| Lint | `python -m ruff check src tests scripts` | PASS |
| Type check | `python -m mypy src tests scripts` | PASS, 30 source files |
| Total coverage | Coverage branch report with `--fail-under=80` | PASS, 94 percent |
| Core coverage | Domain and gate report with `--fail-under=90` | PASS, 100 percent |
| CLI doctor | `python -m sdaqf doctor --current-session-active --json` | PASS |
| CLI init | Dry-run initialization in a repository-local target | PASS |
| CLI validate | Validate the complete sample project | PASS |
| CLI status | Report the sample project state | PASS |
| CLI goal template | Render M1 | PASS, all nine required sections |
| Git boundary | `scripts/check_workspace_boundary.py` | PASS |
| Publication audit | `scripts/audit_repository.py` | PASS |

The first normal pytest attempt reached 25 passing tests, then its default
user-profile temporary directory was denied by the sandbox. The denial was
classified as `PERMISSION_DENIED`, not as a missing Python or pytest
installation. The configuration was made portable by moving pytest temporary
files to ignored repository-local `.pytest-tmp/`; the unchanged
`python -m pytest` command then passed. No broad approval was requested.

Installing and synchronizing the pinned development-only dependencies used two
narrow executions under the same approved project-virtual-environment pip
prefix: the initial quality tools and the subsequently pinned build backend.
Their scope was the exact pip command family, the lockfile, writes under
`repo/.venv`, and PyPI package hosts. Installation is reversible by removing
the ignored virtual environment. It did not authorize any GitHub or
product-level external action.

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| AC-M0-001 | PASS | Parent `.git` absent before and after bootstrap |
| AC-M0-002 | PASS | Repository Git root initialized on `main` |
| AC-M0-003 | PASS | Boundary script and index review |
| AC-M0-004 | PASS | 60 pytest tests |
| AC-M0-005 | PASS | Ruff and strict mypy |
| AC-M0-006 | PASS | 94 percent total, 100 percent core branch coverage |
| AC-M0-007 | PASS | Safe sample smoke checks for all five M0 commands |
| AC-M0-008 | PASS | Deterministic nine-section goal-template test |
| AC-M0-009 | PASS | English public documents and complete 243-ID specification baseline |
| AC-M0-010 | PASS | Five structured repository skills |
| AC-M0-011 | PASS | README separates implemented and unimplemented scope |
| AC-M0-012 | PASS | No remote or GitHub publication action |
| AC-M0-013 | PENDING | Pre-commit evidence; final local commit, hash, and clean tree must be recorded after commit |
| AC-M0-014 | PASS | Complete M1 Goal prompt and handoff |
| AC-M0-015 | PASS | Nine open Owner decisions recorded |
| AC-M0-016 | PASS | Python, Git, test, lint, type, coverage, and CLI command evidence |
| AC-M0-017 | PASS | Synthetic missing-tool and permission-denied tests |
| AC-M0-018 | PASS | Only the narrow project-venv pinned-install prefix needed technical approval |
| AC-M0-019 | PASS | No administrator shell, UAC bypass, full access, or bypass flag |
| AC-M0-020 | PASS | No user Codex setting, global instruction, auth, or credential access |
| AC-M0-021 | PASS | Publication and tracked-language audits |
| AC-M0-022 | PASS | Agent instructions and M1 prompt preserve all boundaries |
| AC-M0-023 | PASS | M1 prompt selects `repo/` as Primary folder |

## Prior block and Owner decision

The prior execution stopped before creating the repository after treating a
nested external Codex CLI probe as mandatory. The Owner clarified that
`AC-M0-016` requires Python, Git, tests, lint, and type checking, not a second
Codex process. This override changed only that classification. All other M0
quality, safety, language, Git, and publication boundaries remained unchanged.

## Independent review

Read-only requirements and QA reviewers challenged the candidate before
commit. Their findings led to a complete 243-ID public baseline, idempotent
recognized-state initialization, generic operating-system error
classification, stronger publication scanning, immutable CI action pins, and
exclusive file creation. The revised candidate received a requirements-review
GO; the final Git index and clean commit remain deliberately pending here.

## Residual limitations

- Dependency vulnerability scanning against a live advisory service was not
  performed; external advisory state is `NOT VERIFIED`.
- Linux behavior is configured in CI but was not executed locally.
- M1 functions such as full ingestion and traceability remain intentionally
  unimplemented.
- Final Git hash and clean-worktree evidence are recorded in the private local
  completion report to avoid a self-referential commit hash.
