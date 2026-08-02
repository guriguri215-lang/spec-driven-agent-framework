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
audits, either the historical schema 1.0 unselected-license state or the exact
schema 1.1 Apache-2.0 `LICENSE` and `NOTICE` contract, required non-empty UTF-8
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
the candidate. Unknown, additional, nested, linked, modified, or conflicting
project-license material fails closed. Gate G4 does not perform or authorize
Gate G5 publication.

The V1 publication-readiness service is a separate offline composition layer.
It binds exact local candidate identity, complete Git publication paths,
approved release metadata and policy, selected license material, G1 through G4
records, and independent review. It re-evaluates G1 through G3 from supplied
local evidence and audits the exact candidate. Success is
`G5-LOCAL-READINESS` with status `LOCAL_READY`; the result always records
`publication_performed: false` and actual Gate G5 `NOT_RUN`. The service has
no GitHub, credential, tag, release, visibility, or repository-setting port.

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
Missed Must requirements, recorded Must, security, data-loss, or disclosure
defects, and failed or unverified evaluation evidence remain named hard
blockers. A bare defect-resolution assertion cannot remove a blocker because
evaluation schema 1.0 has no evidence-bound critical-resolution contract.
Repeated failure signatures require an evidence-linked cause analysis that
selects instruction, Skill, schema, test, or implementation remediation; an
open analysis remains a named hard blocker. Before/after change records bind
the declared artifact type to the exact before and after intervention digests.

Agent and Tool Registry migration is an explicit one-step 1.0-to-2.0 service.
It requires an exact current Owner approval, parses one immutable initial
source snapshot, preserves the source, inserts only documented conservative
defaults, serializes deterministically, validates a temporary regular JSON file
through the current strict 2.0 loader, and creates the named output
exclusively after a final pre-publication source check. Approval and result
schema 1.1 bind a non-disclosing local-root identity plus the exact source path
and digest; approval schema 1.0 is not reusable authorization. Agent migration
also requires a current Tool Registry and validates every tool reference from
one immutable byte snapshot whose path and digest are part of the exact
approval and result, then rechecks that companion immediately before
publication. Each approval is single-use and is atomically claimed in ignored
repository-local state after a fresh expiry check and before the exclusive
output link. Source and companion identities are checked both immediately
before and immediately after that link. Existing or concurrently created
output, unsafe command, external network capability, missing tool, ambiguous
or colliding identity, link, traversal, unsupported version, validation
failure, final source-read or identity failure, or consumption-state failure
leaves no confirmed usable named output. A post-link identity failure is
reported as indeterminate: portable path deletion cannot close the final
replacement race, so the service never deletes the name and explicitly
prohibits its use until Owner inspection. A foreign concurrent replacement is
never deleted. A consumed approval is not restored after a later publication
failure. Successful rollback guidance removes only the confirmed created
output and retains the unchanged source; it does not authorize automatic
cleanup of an indeterminate name.

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

## M5 Context Framework

M5 preserves the domain/application/ports/adapters boundary. Frozen Context
types live in `domain/context.py`. Strict canonical envelopes and use cases live
in `application/context_*.py`. Source reader, candidate verifier, byte
estimator, and immutable publisher protocols live in `ports/context.py`;
standard-library local implementations live in `adapters/context.py`.

The application receives explicit repository or owner roots. It has no ambient
home, parent-state, credential, network, model, or hosted-service read. Source
bytes and provenance references are regular, unlinked, bounded, strict UTF-8
snapshots. The injected production verifier observes Git HEAD, repository
publication digest, root identity, and canonical specification digest before
Index and Snapshot adoption. Every selected source, including structurally
immutable JSON, is re-observed before Snapshot publication; immutable content
also passes the strict canonical-JSON value checks.

Artifacts are immutable content-addressed JSON. Full SHA-256 identities and
canonical integer-only ranking remove filesystem, locale, floating-point, and
model-tokenizer ordering from the baseline. Selection embeds its exact Query,
and Snapshot construction reruns the selector before re-observation. Required
and contradiction-connected context allocates atomically under a canonical
UTF-8 byte budget. Optional source failures remain exact Graph or Snapshot
exclusions. Snapshot parsing independently requires the candidate-bound
canonical specification and recomputes every selected node cost. Host summaries
are source-linked untrusted proposals; policy and
decision authority remain outside retrieved or generated data.

Persisted Snapshot identity is content integrity, not ambient source
authentication. The production Compaction boundary therefore requires explicit
repository/owner roots and re-observes CandidateIdentity, every extract source,
freshness, and provenance before use. Parsed Graph and Snapshot nodes recompute
their canonical source identity from source metadata and reject duplicate
source identities. Compaction first strictly round-trips complete in-memory
Snapshot and HostSummaryProposal inputs, then repeats all source-identity checks
in one pure pass before candidate or source I/O. Compaction retains node/source
identity, authority, sensitivity, and per-extract contradiction IDs so
downstream code does not have to infer conflict state from a promoted required
flag. The final pre-publication CandidateIdentity check takes its expected value
from the validated Compaction being serialized, so a mutable caller cannot
authenticate a different candidate after compaction.

M5 adds no runtime dependency, SQLite state, scheduler, agent dispatch, solver,
embedding/vector backend, OpenAI API, Agents SDK, or management UI. M6 consumes
the exact validated Snapshot rather than sharing M5 storage internals.

## M6 Multi-Agent Control Framework

M6 preserves the existing layered boundary. Frozen scheduler values and enums
live in `domain/scheduler.py`; five host/store/clock/artifact protocols live in
`ports/scheduler.py`; strict contracts and deterministic services live in
`application/scheduler*.py`; and `adapters/scheduler.py` supplies the local
SQLite store, UTC clock, exclusive JSON publisher, and explicitly unsupported
real-host adapters.

The Task Graph binds full digests for the current M2 Agent Registry, Tool
Registry, Orchestration Request, optional Worktree Plan, and one or more exact
M5 Context Snapshots. Validation repeats the M2 plan and candidate, role,
tool, reviewer, integrator, path-ownership, sensitivity, and Context identity
checks. The scheduler never receives authority from agent-authored text.

SQLite is the single mutable projection and uses application ID `0x53444151`,
`user_version=1`, metadata schema `1.0`, rollback journaling, synchronous FULL,
foreign keys, trusted schema off, zero busy wait, and explicit
`BEGIN IMMEDIATE`. Portable messages, events, leases, budget snapshots, and
worktree observations remain immutable content-addressed JSON. Events form a
complete SHA-256 chain. Every task-bound event contains the full post-event task
projection. Recovery validates immutable evidence, rebuilds every mutable
projection in a fresh exact schema, and publishes only an evidence-equivalent
database.

Dispatch is at least once. Each attempt has one current owner, a monotonically
increasing fence, an exact Context identity, and a stable idempotency key.
The bounded TTL/heartbeat policy is selected once at database initialization,
bound to the initialization event and recovery identity, and then reproduced
independently for every Lease and dispatch payload.
An approval-bound attempt first persists a provisional Lease and exposes its
exact identity for external approval. Later ticks reuse its owner, attempt,
fence, Lease ID, and idempotency key; an expired unactivated proposal rotates
without consuming an execution attempt or concurrency reservation.
Periodic heartbeats refresh a new portable Lease projection without changing
the stable authority ID. Worktree dispatch and cooperative cancellation use
explicit scheduler-to-host request messages and exact causal observations.
Cancellation selects only a primary-adopted same-Lease intent for the current
phase. Worktree observation live ingress and immutable replay share one exact
authority derivation over the `not_dispatched` phase, task assignment, prior
request, latest requested/observed Worktree, and latest active Lease. Every
non-result cause is also checked against its complete Lease-history output:
nonterminal observation emits none, terminal observation emits one exact
release, and every Lease expiry equals its heartbeat plus the immutable TTL.
Every
operation that advances whole-second elapsed time first records
one exact wall observation anchored to the initialization event.
Only safe unambiguous read-only work may retry automatically. Foreign, stale,
late, conflicting, sensitivity-downgraded, or causally incomplete messages are
retained only as rejection events. Cancellation or an external effect that
cannot be proven is `blocked/unknown`, never inferred as success.

Task completion uses a closed contract: optional
`evidence-reference-present`, required `agent-result-valid`, and completion of
every declared review target. Unknown predicate text is rejected before
initialization, and an unsatisfied predicate blocks verification. Mutable
current Lease and Worktree row sets are compared with the exact sets implied
by immutable histories, including missing-row detection. Budget reservations
are reconstructed and settled per Lease attempt from immutable scheduler
events, so acknowledgement, result, rejection, cancellation, and expiry are
at most once and cannot debit another concurrent task. Effective concurrency
is bounded by `max_concurrency`, which schema and runtime both require not to
exceed `max_agents`.

Public Lease and Mailbox schemas express all structurally representable
constraints. Cross-field time ordering is rechecked at the authoritative
scheduler boundary, where the related fields and transition clock are
available, without weakening Lease TTL, heartbeat, or approval-window safety.

The package emits typed host intents and consumes typed observations. It does
not launch Codex, execute a process, create or integrate a worktree, access a
network, or delete ambiguous state. Ten fixed-clock simulations exercise the
real SQLite state machine offline.

## M7 Mathematical Solver Framework

M7 follows the same dependency direction. Frozen problem, adapter, Result,
resource, proof, and Verification values live in `domain/solver.py`;
clock/adapter/Lease-evidence protocols live in `ports/solver.py`; strict
content-addressed contracts, orchestration, and independent verification live
in `application/solver*.py`; and `adapters/solver.py` supplies only the
standard-library enumerator, system clock, and read-only M6 Lease observer.
The CLI depends on the application services, never on solver internals.

The Solver Request joins four existing trust domains without sharing their
storage internals: an exact Solver Registry and operational contract, the M5
Candidate and Context Snapshot, and the M6 Task Graph/task. The capability
token carries the contract ID plus exact solve and verification reservations.
The scheduler grants execution authority through one current fenced Lease and
reserves one solver call and the exact combined step count.

The reference adapter is deterministic complete-assignment enumeration over a
closed finite integer model. It publishes typed evidence only. A second
application service independently reloads and reauthenticates Registry,
Request, Graph, Result, and current or historical Lease evidence, then
re-evaluates witness, objective, bound, resource, proof, and required-claim
semantics. `verified` is not automatically adoptable: every check must pass and
the verified status must meet the requested claim.

M6 Task Result ingestion treats the Result and Verification as a paired
evidence unit. It reproduces verification, exact budget usage, no-effect
semantics, and adoption authority during both live validation and fresh-output
recovery. Agent text, backend agreement, timeout, `unknown`, and optional-tool
availability cannot grant scheduler authority.

The optional external-CLI type is intentionally non-executable. Its Registry
shape records exact Tool Registry identity, tool/executable, input format,
version matcher and observation, license/provenance, network prohibition, and
fresh single-use Owner plus technical-sandbox approval requirements. Selecting
it produces `unavailable` without process or network access. An executable
adapter would be a future separately approved architecture change.
