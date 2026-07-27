# Release Contract

M0 produces a local bootstrap commit, not a public release.

## Required local gates

```text
python -m pytest
python -m ruff check src tests scripts
python -m mypy src tests scripts
python -m coverage run -m pytest
python -m coverage report --fail-under=80
python -m coverage report --include=src/sdaqf/domain/*,src/sdaqf/application/gates.py --fail-under=90
python scripts/check_workspace_boundary.py --repo .
python scripts/audit_repository.py --root . --workspace-parent ..
```

Run CLI smoke checks for `doctor`, `init`, `validate`, `status`, and
`goal-template`.

## Local commit gate

- Every required check passes.
- The staged diff is reviewed explicitly.
- No secret, personal path, private state, symlink, generated cache, or
  non-English GitHub-facing artifact is staged.
- The branch is `main`.
- No remote exists.
- The commit message and repository-local author identity are non-personal
  English metadata.

## Public release gate

Publication is a separate future action. It requires Owner decisions for the
repository name, visibility, description, license, default branch, initial tag,
and English outbound metadata. It also requires a fresh secret, personal-data,
dependency, license, language, and clean-environment audit.
