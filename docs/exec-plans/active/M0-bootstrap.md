# M0 Bootstrap Foundation ExecPlan

## Objective

Create a safe, local-only, executable, tested repository foundation that
satisfies `AC-M0-001` through `AC-M0-023`.

## Scope

Repository structure, English public documentation, standard-library Python
CLI, initial schemas and samples, Codex skills, tests, static checks, coverage,
CI, publication audits, evidence, a local `main` commit, and an M1 handoff.

## Non-goals

No GitHub remote, push, post, tag, release, license selection, user-setting
change, credential access, paid API, deployment, full orchestration, or full UI
automation.

## Checkpoints

1. Verify the authoritative digest and parent/repository safety.
2. Record the prior block and Owner override.
3. Implement the minimum architecture and public artifacts.
4. Create an isolated development environment and install pinned tools.
5. Run tests, lint, type checks, coverage, CLI smoke, boundary, and publication
   audits.
6. Perform an independent read-only review.
7. Stage reviewed files explicitly, create an English local commit, and verify
   a clean worktree with no remote.

## Stop conditions

Stop for unsafe Git ancestry, reparse targets, destructive overwrite, secrets,
unapproved external effects, an unavailable mandatory command after a narrow
approval attempt, weakened quality gates, or an unresolved Must-requirement
conflict.

## Approval gates

Narrow technical sandbox approvals may support already authorized local M0
commands. Publication, destructive changes, production dependencies, license
selection, credentials, machine settings, and external data transfer require
separate Owner approval and are outside this plan.

## Progress and decisions

- 2026-07-27: Source digest matched the authoritative value.
- 2026-07-27: Owner reclassified the nested external Codex CLI denial as
  nonblocking; the current session is active and the nested probe will not be
  rerun.
- 2026-07-27: Selected a zero-runtime-dependency architecture with pinned
  development tools.

## Validation

Use the commands in `docs/release-contract.md`, run all CLI commands on the
sample project, inspect the staged diff, and record evidence before commit.
