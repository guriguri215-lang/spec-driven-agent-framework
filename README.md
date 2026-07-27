# SDAQF

SDAQF is a specification-driven development and quality-assurance framework for
Codex-assisted projects. This repository contains the M0 Bootstrap Foundation:
a small, offline-first Python CLI, deterministic domain models, validation
schemas, safety guidance, reusable agent skills, and local quality gates.

The authoritative source for this bootstrap was a private Japanese
specification. The public English baseline records its source digest without
copying private workspace state.

## Implemented in M0

- Safe workspace and Git-boundary checks.
- A standard-library Python package with no runtime dependencies.
- `doctor`, `init`, `validate`, `status`, and `goal-template` commands.
- Tool-state separation for available, unavailable, permission-denied, and
  intentionally untested capabilities.
- Initial project, requirement, evidence, approval, execution, handoff, tool,
  and agent schemas with samples.
- Tests, linting, strict type checking, branch coverage, and Windows/Linux CI.
- Public documentation, GitHub templates, and reusable Codex skills.
- Repository audits for publication scope, language, secrets, personal paths,
  symlinks, and local-only Git state.

The pinned development dependency and license record is in
`docs/dependencies.md`.

## Not implemented in M0

- Full specification ingestion and requirement normalization.
- Multi-agent orchestration or worktree management.
- Automated UI/UX browser validation.
- Solver, OpenAI API, or Agents SDK integrations.
- GitHub repository creation, remotes, pushes, pull requests, issues, tags, or
  releases.
- Production deployment.

## Quick start

Use Python 3.12 or newer in an isolated environment:

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-build-isolation --no-deps -e .
.venv\Scripts\python -m pytest
.venv\Scripts\sdaqf --help
```

On POSIX systems, use `.venv/bin/python` instead.

Example commands:

```text
python -m sdaqf doctor --json
python -m sdaqf validate examples/sample-project
python -m sdaqf status examples/sample-project --json
python -m sdaqf goal-template M1
python -m sdaqf init scratch-project --dry-run
```

## Safety boundaries

The repository is local-only during M0. Do not add a remote or publish any
artifact without a separate Owner approval. A technical sandbox approval never
authorizes publication, destructive Git operations, credential access, or
machine-wide configuration changes.

## License status

No license has been selected. No `LICENSE` file is included, and no permission
is granted to copy, modify, or distribute this work until the Owner makes an
explicit license decision.
