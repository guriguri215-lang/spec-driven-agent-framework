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
tool capability observation, retry control, and atomic checkpoint recovery. M3
adds strict evidence, independent-review, UI-observation, release-candidate,
and handoff loading; atomic evidence addition; and Gates G2 through G4.
M4 adds strict sample-normalization, evaluation-suite, paired run,
deterministic metric, recorded-result, and explicit registry-migration
services.

`sdaqf.adapters` contains bounded subprocess and local filesystem behavior.

`sdaqf.cli` maps `argparse` commands to application services and stable English
output.

JSON schemas under `schemas/` define the interchange contracts. M1 adds
versioned requirement-record, requirement-baseline, and baseline-comparison
contracts. Runtime adoption uses small standard-library validators so the
offline core retains no production dependency. M2 adds versioned agent, tool,
tool-execution approval, orchestration request, worktree, structured result,
template, and checkpoint contracts. M3 adds separate versioned Claim-Evidence
Ledger, evidence-addition, review, finding-acceptance, UI validation,
release-candidate, handoff-input, and automated-handoff contracts without
changing the M1 or M2 versions. M4 preserves every existing version and adds
evaluation, migration-result, and platform-evidence contracts. Legacy Agent and
Tool Registry 1.0 inputs are transformed only through an explicit migration
boundary; runtime adoption remains strict version 2.0.

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

## M3 evidence and release-quality pipeline

The Claim-Evidence Ledger binds one requirement baseline and source digest to
sorted unique claims and evidence. Claims record requirement and acceptance
references, implementation state, criticality, and confidence. Evidence records
retain type, result, a structured argument array, non-empty environment, exact
commit and repository digest, content-hashed safe relative artifacts, and
timestamp. The loader rejects duplicate JSON keys, links,
oversized input, unsafe paths, secret-shaped content, unknown references,
unsupported versions, contradictory unverified state, and missing passing diff
review evidence. Evidence addition validates the complete old and new contract,
requires the same candidate identity, holds an exclusive repository-local lock,
and uses a repository-bounded atomic replacement.

Gate G2 checks baseline identity, traceability, complete Must-acceptance
mapping, applicable passing tests, explicit unverified evidence, and a separate
conformance source beyond tests and the named diff review. Critical Must,
security, data-loss, and disclosure failures are hard blockers. Gate G3
requires completed read-only review by a distinct identity, an immutable
baseline/source/HEAD/repository identity and reviewed path set, coverage of
regression, security, and maintainability, resolution of High and Medium
findings, and resolution or exact expiring Owner acceptance of a Critical
finding. Critical-finding acceptance also binds the exact finding digest and
candidate identity.

UI classification comes from the validated manifest. A non-UI project rejects
fabricated Design Brief or browser evidence. A UI project requires a bounded
Design Brief and no more than three ordered host observations. The offline core
does not install or launch a browser; it validates provenance, timestamp,
structured command, a supported real browser matched to its executable and
numeric version, target-platform flows, required states, devices, viewports,
keyboard, focus, readability, contrast, information structure, efficiency,
content-hashed regular PNG screenshots, a content-bound execution trace,
visual-regression disposition, offline behavior, recovery, and truthful
failure/retry state. PNG adoption checks dimensions, color layout, chunk type
and order, CRCs, bounded decompression, exact scanlines, and filter bytes.

Gate G4 composes passing G2, G3, and applicable UI results with exact-commit
installation evidence, verified Must claims, local repository and dependency
audits, explicit unselected project-license state, required non-empty UTF-8
documentation with installation and known-limitations sections, exact rollback
guidance, and a bounded read-only Git observation. Installation proof uses an
exact `python -I -m pip --isolated` command with no index, build isolation, or dependency
resolution. It copies only Git's cached-plus-untracked publication files into a
fresh owned `<install-target>-source` tree, installs only that tree, removes
owned build outputs, compares every source byte and path to the current
publication set, and runs an isolated installed-module execution probe.
Ignored worktree files, ambient imports, pre-existing targets, extra source
inputs, and missing publication documents fail closed. The publication audit
uses the same complete Git candidate set, so nested project-license names,
binary metadata disclosures, links, and reparse ancestors cannot hide inside
the candidate. Gate G4 does not perform or authorize Gate G5 publication.

Every M3 Gate, UI validation, and handoff command hashes the actual regular,
unlinked specification supplied on the command line and requires it to be in
the Git publication set. Automated handoff generation records exact Git,
baseline, source, and repository identity observed directly from the current
root, work state, ledger-backed evidence, decisions, problems, next work,
approval stops, and deterministic prompt context. Completed handoffs cannot
retain incomplete work, open decisions, or known problems. Resume rejects any
identity mismatch, and generated prompts are never executed automatically.

## M4 public-beta hardening pipeline

Three representative projects bind a regular UTF-8 specification and task to
an expected semantic normalization projection. The evaluator re-runs M1
ingestion, hashes the actual specification and task, and rejects expectation
drift. Paired structured-SDAQF and ordinary-unstructured-Codex records compare
only when project, specification, task, starting repository, model/client,
platform, Python, budget, and trial identity match exactly. The intervention
must be disclosed and differ by content. Every evidence entry binds its type,
status, observation time, review command, safe tracked path, and exact content
digest.

Metrics include missed requirements, scope additions, critical defects,
rework, approvals, failed handoffs, trace steps, decisions, evidence items, and
available or explicitly unverified cost. No aggregate quality score exists.
Missed Must requirements and unresolved Must, security, data-loss, or
disclosure defects remain named hard blockers. Repeated failure signatures
require an evidence-linked cause analysis that selects instruction, Skill,
schema, test, or implementation remediation; an open analysis remains a named
hard blocker.

Agent and Tool Registry migration is an explicit one-step 1.0-to-2.0 service.
It requires an exact current Owner approval, parses one immutable initial
source snapshot, preserves the source, inserts only documented conservative
defaults, serializes deterministically, validates a temporary regular JSON file
through the current strict 2.0 loader, and creates the named output
exclusively. Agent migration also requires a current Tool Registry and
validates every tool reference from one immutable byte snapshot whose path and
digest are part of the exact approval and result. Existing output, unsafe
command, external network capability, missing tool, ambiguous or colliding
identity, link, traversal, unsupported version, validation failure, or final
source-read or identity failure leaves no named output. Rollback removes only
the created output and retains the unchanged source.

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
