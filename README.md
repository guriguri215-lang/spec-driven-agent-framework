# SDAQF

SDAQF is a specification-driven development and quality-assurance framework for
Codex-assisted projects. This repository contains the M0 Bootstrap Foundation
and M1 Requirements and Planning MVP: an offline-first Python CLI,
deterministic requirement contracts, safety guidance, reusable agent skills,
and local quality gates.

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

## Implemented in M1

- Bounded UTF-8 Markdown ingestion with SHA-256, size, modification time, safe
  source path, and import-time metadata.
- Deterministic requirement types, priorities, stable explicit or generated
  identifiers, acceptance criteria, verification methods, and source excerpts.
- Explicit ambiguity, contradiction, duplicate, missing-assumption, and
  unverifiable-language diagnostics.
- Design, code, test, evidence, and release trace fields that remain empty until
  supported records are supplied.
- Approval-aware baseline comparison for additions, removals, statement,
  priority, type, acceptance, verification, and interpretation changes. A
  removal or potentially weakening change can be approved only through a
  structured Owner approval record scoped to both baselines and named change
  IDs.
- Product Roadmap, living ExecPlan, Goal prompt, and Standard prompt generation
  with Goal suitability and safe Standard fallback.
- Gate G1 enforcement for a complete, non-implemented requirements baseline.
- `ingest`, `compare`, `roadmap`, `exec-plan`, `goal`, `prompt`, and
  `gate requirements` CLI commands.

The pinned development dependency and license record is in
`docs/dependencies.md`.

## Not implemented through M1

- Multi-agent orchestration or worktree management.
- Automated UI/UX browser validation.
- Full evidence-ledger or release automation.
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
python -m sdaqf ingest examples/sample-specification.md --output baseline.json
python -m sdaqf gate requirements baseline.json --json
python -m sdaqf roadmap baseline.json M1 --output roadmap.md
python -m sdaqf exec-plan baseline.json M1 --output exec-plan.md
python -m sdaqf goal baseline.json M1 --output goal.md
python -m sdaqf prompt baseline.json M1 --output prompt.md
```

## Safety boundaries

The repository remains local-only through M1. Do not add a remote or publish
any artifact without a separate Owner approval. A technical sandbox approval
never authorizes publication, destructive Git operations, credential access,
or machine-wide configuration changes.

## License status

No license has been selected. No `LICENSE` file is included, and no permission
is granted to copy, modify, or distribute this work until the Owner makes an
explicit license decision.
