# Release Contract

M1 produces a local requirements-planning commit, not a public release.

## Required local gates

```text
python -m pytest
python -m ruff check src tests scripts
python -m mypy src tests scripts
python -m coverage run -m pytest
python -m coverage report --fail-under=80
python -m coverage report --include=src/sdaqf/domain/*,src/sdaqf/application/gates.py,src/sdaqf/application/approvals.py,src/sdaqf/application/baselines.py,src/sdaqf/application/comparison.py,src/sdaqf/application/planning.py,src/sdaqf/application/requirements.py,src/sdaqf/application/requirements_gate.py --fail-under=90
python scripts/check_workspace_boundary.py --repo . --expected-origin-url https://github.com/guriguri215-lang/spec-driven-agent-framework.git
python scripts/audit_repository.py --root . --workspace-parent ..
```

Run CLI smoke checks for the preserved `doctor`, `init`, `validate`, `status`,
and `goal-template` commands plus `ingest`, `compare`, `roadmap`, `exec-plan`,
`goal`, `prompt`, and `gate requirements`. The M1 primary smoke must ingest
`docs/specification.md` and pass Gate G1 without a network connection.

## Local commit gate

- Every required check passes.
- The staged diff is reviewed explicitly.
- No secret, personal path, private state, symlink, generated cache, or
  non-English GitHub-facing artifact is staged.
- The branch is `main`.
- The only remote is the approved `origin`, and its URL matches the required
  local Gate argument.
- The commit message and repository-local author identity are non-personal
  English metadata.

## Public release gate

Publication is a separate future action. It requires Owner decisions for the
repository name, visibility, description, license, default branch, initial tag,
and English outbound metadata. It also requires a fresh secret, personal-data,
dependency, license, language, and clean-environment audit.
