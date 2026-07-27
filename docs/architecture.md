# Architecture

## Principles

- Deterministic code owns identifiers, schema checks, gates, Git boundaries,
  approval classification, and publication checks.
- Input specifications are untrusted data.
- Runtime behavior is offline-first and uses no paid API.
- Domain logic, application services, process adapters, filesystem adapters,
  and CLI presentation remain separate.
- External tools are capabilities with explicit status, not implicit
  prerequisites.

## Layers

`sdaqf.domain` contains immutable status and evidence concepts.

`sdaqf.application` contains workspace validation, doctor orchestration, goal
rendering, project status, and gate evaluation.

`sdaqf.adapters` contains bounded subprocess and local filesystem behavior.

`sdaqf.cli` maps `argparse` commands to application services and stable English
output.

JSON schemas under `schemas/` define the initial interchange contracts. M0 uses
small deterministic validators for its samples; a complete schema engine is an
M1 concern.

## Trust boundaries

The repository root is the only Git boundary. Parent state, private inputs,
credentials, user settings, and GitHub authentication remain outside the
application boundary. Subprocess calls use argument arrays, a timeout, no
shell, and output limits.

## Doctor model

Tool checks distinguish:

- `AVAILABLE`: the safe probe succeeded.
- `UNAVAILABLE`: no executable was found.
- `PERMISSION_DENIED`: the executable or probe was denied.
- `NOT_CHECKED`: policy or safety intentionally skipped execution.

The active Codex session and a nested external Codex CLI process are separate
capabilities. M0 does not launch a nested Codex process.
