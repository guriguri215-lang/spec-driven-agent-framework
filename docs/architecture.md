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

`sdaqf.domain` contains immutable capability, Gate, requirement, source,
acceptance, diagnostic, and traceability concepts.

`sdaqf.application` contains workspace validation, doctor orchestration, goal
rendering, project status, bounded specification ingestion, baseline contract
loading, requirement comparison, planning and prompt rendering, and Gate
evaluation.

`sdaqf.adapters` contains bounded subprocess and local filesystem behavior.

`sdaqf.cli` maps `argparse` commands to application services and stable English
output.

JSON schemas under `schemas/` define the interchange contracts. M1 adds
versioned requirement-record, requirement-baseline, and baseline-comparison
contracts. Runtime adoption uses small standard-library validators so the
offline core retains no production dependency.

## M1 requirements pipeline

The ingestor accepts one bounded, regular, unlinked UTF-8 Markdown file. It
records safe source metadata and parses explicit identifier records plus
unlabelled records only inside known requirement sections. Generated
identifiers use a normalized statement digest and are stable across reordering.

Normalization preserves the exact source excerpt and line range, creates
traceable acceptance and verification contracts, records diagnostic findings,
and leaves downstream trace links empty. The comparison service ignores import
timestamps, reports semantic field changes, and requires a validated structured
Owner approval record for a removal or potentially weakening change. A bare
change identifier cannot assert approval.

Planning and prompt services consume validated domain records and stable IDs.
They do not copy source statements into executable prompts. Gate G1 is
non-compensating: unresolved blocking diagnostics, missing Must acceptance,
unsafe traceability, unverified completion claims, or unresolved approvals
fail the Gate.

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
