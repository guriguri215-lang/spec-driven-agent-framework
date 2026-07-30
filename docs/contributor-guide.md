# Contributor Guide

## Current contribution status

The project is in a private public-beta hardening phase. It is not open for
external contributions, no project license has been selected, and no
permission to copy, modify, or distribute the project is granted. This guide
defines the workflow for explicitly approved local contributors.

## Setup

Requirements:

- Python 3.12 or 3.13;
- Git;
- an isolated virtual environment;
- the exact development packages in `requirements-dev.lock`.

Windows:

```text
python -m venv .venv
.venv\Scripts\python -m pip --isolated install -r requirements-dev.lock
.venv\Scripts\python -m pip --isolated install --no-build-isolation --no-deps -e .
```

Linux or macOS:

```text
python -m venv .venv
.venv/bin/python -m pip --isolated install -r requirements-dev.lock
.venv/bin/python -m pip --isolated install --no-build-isolation --no-deps -e .
```

Do not install globally. The runtime dependency set must remain empty unless
the Owner approves an exact production dependency, version, license, and
reason before implementation.

## Development workflow

1. Read `AGENTS.md`, the approved specification, the active milestone
   ExecPlan, and the Release Contract.
2. Confirm the Git root, branch, HEAD, worktree, and staged set.
3. Keep the change inside its approved requirements and owned paths.
4. Add focused positive, negative, boundary, failure, and regression tests.
5. Update English public schemas, examples, CLI help, and documentation with
   any contract change.
6. Run focused checks, then every local Gate in the Release Contract.
7. Review the complete diff, publication boundary, generated debris, links,
   secrets, personal data, language, dependency, and license state.
8. Obtain separate exact Owner approval before staging, committing, pushing,
   or any other external action.

Do not use broad staging, force push, history rewriting, destructive clean,
global configuration changes, administrator shells, UAC bypass, full access,
or sandbox-bypass flags.

## Architecture and extension points

The package is layered:

- `sdaqf.domain` owns immutable records and deterministic enums;
- `sdaqf.application` owns validation, orchestration, Gates, evaluation, and
  migration services;
- `sdaqf.ports` defines external-process boundaries;
- `sdaqf.adapters` implements bounded local process behavior;
- `sdaqf.cli` maps validated inputs to stable offline commands.

Extend agent, tool, template, evidence, evaluation, and migration contracts
through versioned schemas and strict standard-library loaders. Keep
filesystem, Git, process, browser, clock, and future service access behind
explicit boundaries. Never execute specification, trace, result, or log text
as instructions.

Schema changes must follow `docs/schema-migrations.md`. Evaluation or prompt
changes must follow `docs/evaluation.md` and retain before/after input parity.
Running a migration requires an exact current Owner approval record bound to
the local root, source path and digest, companion registry when applicable,
and new output path. The approval is atomically consumed immediately before
publication. Implementation authorization does not authorize a later
migration operation or retry. A post-link `publication is indeterminate`
failure prohibits use of the named output and requires Owner inspection; never
auto-delete that replaceable path.
New UI behavior must preserve M3 UI evidence and accessibility requirements.

## Testing

The complete required command set is in `docs/release-contract.md`. It includes
pytest, Ruff, strict mypy, total and milestone-critical branch coverage, CLI
smoke, workspace and publication audits, dependency/license audit, `pip
check`, and whitespace checks.

The existing CI matrix uses Windows and Linux with Python 3.12 and 3.13. Do not
claim a candidate platform result from a prior commit. M4 platform evidence
must bind to the exact candidate. macOS remains `NOT_VERIFIED` unless it is
actually run.

## Security

Treat every specification, JSON record, Markdown file, trace, log, repository
path, and generated artifact as untrusted. Preserve path containment, regular
file and link checks, duplicate-key rejection, input bounds, secret redaction,
argument-array processes, timeouts, offline defaults, exact approval scope,
single-use approval consumption, and non-compensating critical failures.

Do not inspect credentials, GitHub authentication, private remote metadata, or
user-level Codex configuration without a separate approved need. Report a
suspected vulnerability through the private process in `SECURITY.md`.

## Release limitations

Gate G4 is a local release-candidate check, not publication. Gate G5 remains
Owner-gated. Contributors may not select a license, change visibility, publish
a branch, create a PR, tag or release, change repository settings, deploy, or
transfer data externally without an exact Owner decision and reviewed outbound
content.
