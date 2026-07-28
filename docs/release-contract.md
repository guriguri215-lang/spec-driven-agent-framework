# Release Contract

M2 produces an inspected private-repository commit, not a public release.

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
python scripts/run_cli_smoke.py
python scripts/check_workspace_boundary.py --repo . --expected-origin-url https://github.com/guriguri215-lang/spec-driven-agent-framework.git
python scripts/audit_repository.py --root . --workspace-parent ..
python scripts/audit_dependencies.py --root .
python -m pip check
git diff --check
```

The complete pytest run is the schema/sample validation Gate. It also preserves
M0 and M1 CLI behavior, canonical specification ingestion, Requirements
Baseline counts and digest, and Gate G1. `scripts/run_cli_smoke.py` runs the
preserved `doctor`, `init`, `validate`, `status`, and `goal-template` commands;
the M1 `ingest`, `compare`, `roadmap`, `exec-plan`, `goal`, `prompt`, and
`gate requirements` commands; and the M2 `agents`, `skills`, `tools`, and
`checkpoint` primary paths. It performs the canonical ingest and Gate G1
offline in a temporary repository-local directory.

The repository audit is the secret, personal-path, English/CJK,
symlink/reparse, size, private-state, and project-license audit. The dependency
audit verifies the empty runtime dependency set, exact development pins,
documented license metadata, and absence of a project `LICENSE`. `pip check`
verifies the installed dependency set.

## Continuous integration parity

Every Windows/Linux and Python 3.12/3.13 matrix job runs pytest, Ruff, strict
mypy, total and M1/M2 critical branch coverage, both repository audits, the Git
workspace boundary, installed dependency consistency, and the exact CLI smoke
script. CI uses only immutable pinned GitHub Action commits and installs no
runtime dependency.

Windows is verified locally. Linux and Python 3.13 are verified by the matrix.
macOS remains `NOT VERIFIED`.

## Local commit gate

- Every required check passes without a threshold reduction or ignored
  failure.
- Independent read-only review returns GO with no unresolved Critical, High,
  or Medium finding.
- The staged names, status, stat, diff, and whitespace are reviewed
  explicitly.
- No secret, personal path, private state, link, generated cache, coverage
  output, temporary file, project license, or non-English GitHub-facing
  artifact is staged.
- Runtime approval-consumption records and locks under `.sdaqf/` remain
  repository-local ignored state and are never staged.
- The branch is `main`.
- The only remote is the approved `origin`; every fetch and push URL is the
  approved private repository.
- The commit message and repository-local author identity are non-personal
  English metadata.

## Private push and exact-SHA CI gate

Only an explicitly Owner-approved, inspected commit may be pushed normally to
the approved private `origin/main`. Force push, history rewrite, PRs, issues,
discussions, tags, releases, deployment, repository administration, secrets,
and runner changes remain prohibited.

After push, the observed workflow must have the exact local commit as its head
SHA and every required matrix job must succeed. A failure is diagnosed from
bounded logs before any retry. An in-scope fix receives focused tests, full
related Gates, read-only re-review, a new English commit, and a normal push.

## Public release gate

Publication is a separate future action. It requires Owner decisions for
visibility, description, license, default branch policy, initial tag, and
English outbound metadata. It also requires a fresh secret, personal-data,
dependency, license, language, advisory, and clean-environment audit.
