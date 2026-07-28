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
acceptance, diagnostic, traceability, Agent Registry, orchestration, tool,
approval, template, and checkpoint concepts.

`sdaqf.application` contains workspace validation, doctor orchestration, goal
rendering, project status, bounded specification ingestion, baseline contract
loading, requirement comparison, planning and prompt rendering, and Gate
evaluation. M2 adds strict registry and result loading, deterministic role
selection, worktree-plan validation, Skill and template lifecycle evaluation,
tool capability observation, retry control, and atomic checkpoint recovery.

`sdaqf.adapters` contains bounded subprocess and local filesystem behavior.

`sdaqf.cli` maps `argparse` commands to application services and stable English
output.

JSON schemas under `schemas/` define the interchange contracts. M1 adds
versioned requirement-record, requirement-baseline, and baseline-comparison
contracts. Runtime adoption uses small standard-library validators so the
offline core retains no production dependency. M2 adds versioned agent, tool,
tool-execution approval, orchestration request, worktree, structured result,
template, and checkpoint contracts.

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

## M2 orchestration pipeline

The M2 core validates an Agent Registry and its Tool Registry references before
selection. A request declares problem type, scale, risk, parallelism, native
Subagent availability, independent-session availability, requested roles, and
agent, concurrency, and reasoning budgets. Selection is stable by role
identifier, explains each assignment, blocks prohibited work, and schedules an
independent reviewer in a later logical wave for implementation or high-risk
work.

Native in-product Subagents are a host capability, not a child process. The
core emits a bounded dispatch prompt and selects `native_subagent` only when
the caller explicitly observes that capability. It selects
`independent_session` or `sequential` otherwise. The package never launches a
nested Codex CLI or treats one as a native Subagent.

Read parallelism is limited to discovery, test design, log analysis, and
review, and every selected role must be read-only. Write parallelism requires a
validated plan with at least two distinct worktrees, unique writer roles,
case-insensitively non-overlapping repository-relative ownership scopes, one
lowercase base commit, and a separate integrator. M2 validates this plan but
does not create, delete, or integrate Git worktrees.

Agent results are bounded structured summaries. Reviewers cannot change files,
review themselves, or omit reviewed agent identities; implementers cannot
self-approve. Disagreements use evidence strength, severity, and an explicit
counterexample. Equal-strength results remain unresolved, and agent count is
never treated as independent evidence.

Repository Skills move deterministically through discovered, validated,
compatible, blocked, and selected lifecycle states. Template metadata records
target, compatible framework version, dependencies, provenance, license
status, prohibited conditions, and validation date without choosing a project
license.

The Tool Registry permits only safe argument-array version probes. Registry
adoption rejects shells, inline code, global installation arguments,
destructive executables, unsafe paths, and non-canonical network origins.
Execution uses the executable returned by the locator, a sanitized environment,
no shell, a positive timeout, bounded concurrent stream drains, exit status,
duration, redaction, and exact approval scope. An approval is usable only after
the strict versioned loader verifies distinct Owner or technical sandbox
provenance, approval and expiry times, one-execution lifetime, and exact
command, path, network, risk, and execution conditions. Tool execution cannot
construct an approval directly. Before an approved process starts, a
store atomically claims every approval ID under an exclusive lock and publishes
a versioned consumption record with `os.replace`. CLI anchoring is derived from
the validated registry path: the nearest regular Git or SDAQF project boundary,
or the registry directory when neither marker exists. It never depends on the
invocation working directory. The claim persists across service instances,
working directories, and CLI invocations; missing, busy, corrupt, expired, or
previously consumed state fails closed. A sandbox-denied retry requires a new
exact technical approval when registry policy permits it. Optional absence
remains an observed capability state and does not break the offline core.

Execution checkpoints validate all identifiers and state/evidence invariants
before atomic publication. The previous checkpoint is retained as a recovery
backup, temporary artifacts are cleaned on failure, and resume rejects changes
to plan version, specification digest, Git HEAD, or worktree digest. A failed
command receives at most one retry, only for an eligible classified failure
and a new recorded state-change token.

## Trust boundaries

The repository root is the only Git boundary. Parent state, private inputs,
credentials, user settings, and GitHub authentication remain outside the
application boundary. Subprocess calls use argument arrays, a timeout, no
shell, a sanitized environment, resolved executables, bounded stream drains,
and output limits. Tool, source, log, and agent-result content is data and is
never executed as instructions.

## Doctor model

Tool checks distinguish:

- `AVAILABLE`: the safe probe succeeded.
- `UNAVAILABLE`: no executable was found.
- `PERMISSION_DENIED`: the executable or probe was denied.
- `NOT_CHECKED`: policy or safety intentionally skipped execution.

The active Codex session and a nested external Codex CLI process are separate
capabilities. M0 does not launch a nested Codex process.
