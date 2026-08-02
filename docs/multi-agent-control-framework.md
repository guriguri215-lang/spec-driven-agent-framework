# Multi-Agent Control Framework

M6 provides offline, durable, host-agnostic execution control for a validated
task graph. SDAQF owns validation, policy, transactional state, budgets, and
audit evidence. A separately supplied host owns real agent/session dispatch
and Git worktree effects.

The framework deliberately promises at-least-once intent delivery, not
exactly-once execution. Every adopted observation must match the current task,
candidate, Context Snapshot, attempt, lease, fence, owner, idempotency key,
sensitivity, and causal history.

## Public artifacts

All M6 JSON artifacts use schema version `1.0`, strict bounded JSON, M5
canonical content, and a full uppercase SHA-256 content identity:

- Task Graph binds exact M2 registries/request/worktree plan, exact M5 Context
  Snapshots, task dependencies, roles, paths, effects, approvals, evidence,
  terminal predicates, and hard budgets. Evidence predicates are empty or the
  exact `evidence-reference-present` value; the terminal predicate is exactly
  `agent-result-valid`. Arbitrary predicate text is not executable policy.
- Scheduler State is a bounded deterministic projection. It is not the source
  of truth and cannot replace the SQLite event history.
- Lease records one owner, attempt, fence, stable idempotency key, heartbeat,
  expiry, status, and release outcome.
- Mailbox Message has ten exact variants for dispatch, acknowledgement,
  heartbeat, result, cancellation, worktree, approval, and capability traffic.
- Scheduler Event is one immutable link in the complete hash chain.
- Budget Ledger records exact integer limits, reservations, use,
  availability, and named blockers without an aggregate score.
- Worktree Lease records only a host-observed worktree state. It grants no Git
  mutation authority.

Unknown fields, duplicate keys, floats/non-finite values, unsafe paths,
unsupported versions, invalid ordering, identity mismatch, and messages over
64 KiB fail closed. Portable paths also reject Windows reserved components,
trailing-dot components, links, junctions, and reparse ancestors before
resolution. Contract strings are single-line, control-free, and reject known
secret shapes in both runtime and JSON Schema validation. Public fixtures use
only synthetic `public` data.

## Task and transition model

Task kinds are `discovery`, `implementation`, `test`, `tool`, `review`,
`integration`, `solver`, and `handoff`. The normative execution states remain
`planned`, `ready`, `running`, `blocked`, `verification`, `completed`,
`rejected`, and `superseded`.

Dispatch phase and outcome are orthogonal. This prevents a task from being
reported as completed merely because a dispatch was acknowledged or a
cancellation was requested. Ready ordering is deterministic by wave,
topological rank, and task ID. Dependency cycles, missing nodes, overlapping
path ownership, self-review, wrong tools/roles/worktrees, candidate drift, and
Context identity or sensitivity drift are rejected before initialization.

Successful results enter verification before completion. Required evidence is
checked separately, the wrapped Agent Result must already have passed strict
validation, and every declared review target must be completed. Any
unsatisfied predicate leaves the task `blocked/unknown`. A safe, explicit
read-only failure may use a new attempt when both task and global retry limits
allow it. An external, destructive, or otherwise ambiguous effect becomes
`blocked/unknown` and is never retried automatically.

Immutable replay reopens the exact accepted `task_result`. Only a succeeded,
non-ambiguous result may produce the exact
`verification/accepted/succeeded` projection and then the exact
`completed/accepted/succeeded` projection. Failed, unknown, or ambiguous
results instead reproduce their exact rejected, retry-ready, or
`blocked/unknown` terminal policy; they cannot be relabelled into the
verification-success chain by rehashing events or projections.

## SQLite authority and recovery

The canonical mutable store has SQLite application ID `0x53444151`,
`user_version=1`, and metadata schema `1.0`. It uses foreign keys, rollback
journaling, synchronous FULL, trusted schema off, zero busy wait, and explicit
`BEGIN IMMEDIATE`. Initialization and JSON export use exclusive fresh-name
publication.

The schema has exactly thirteen tables for metadata, graph/tasks/dependencies,
events/messages, current and historical leases, current and historical
worktree leases, budgets, and single-use approval consumption. Opening a store
validates database identity, integrity, exact schema shape, metadata, the
complete event chain, immutable artifact identities, and mutable projection
invariants. The exact current Lease set is derived from each task's latest
immutable Lease history status. Current Worktree authority is likewise derived
from the latest immutable per-task Worktree Lease status, with only `requested`
and `observed` remaining current. Missing or extra rows therefore fail
validation rather than disappearing from a row-by-row check. Each non-result
cause is centrally classified by its complete Lease-history output. A
nonterminal Worktree observation produces no Lease row; a terminal observation
produces exactly its cause-derived release row. Every Lease additionally proves
`expires_at = heartbeat_at + ttl`, so an observation-linked current row cannot
act as an implicit heartbeat. Every Worktree
history-producing cause must have exactly one complete artifact reconstructed
from that cause; no other event may carry a Worktree history row. Scheduler Event
causes use a closed 24-value vocabulary. Validation dispatches every cause
through an exact policy for graph/task scope, actor, transition, mutable
projection fields, attempt/fence deltas, causal message, approval, budget,
reason, result, and Lease authority. Scheduler-authored dispatch, worktree, and
cancellation egress is reconstructed from its immutable message payload and
current or historical Lease evidence rather than trusting a correctly rehashed
row. Replay requires the exact scheduler sender and direction, Context
sensitivity and provenance, recorded time, earlier ordered causal parents, and
Lease identity. Worktree observation uses the same normalized authority
reducer as live ingress: the prior phase must be `not_dispatched`, its path must
be the task's exact assignment and prior request, and its event, message, and
latest requested/observed Worktree must share the latest active Lease. Worktree
dispatch additionally requires the exact accepted observation and latest prior
`observed` Worktree Lease; cancellation requires the latest active dispatch or
worktree intent for the same Lease. A future, foreign, missing, additional,
post-dispatch, old-Lease, or released-Lease parent grants no authority.

Immutable replay also derives an exact mailbox-adoption ledger. Every stored
message has exactly one cause-compatible primary adoption event; causal parents
must be earlier in both mailbox and event order. Duplicate audits may refer only
to an already adopted message, and approval consumption may refer only once to
the same earlier adopted approval decision. Scheduler egress, Worktree
observations, approvals, and per-host capabilities are selected and rebuilt
only from this ledger. An orphan, multiply adopted, late, or incompatible row
therefore grants no causal or scheduling authority even when its content
identity and surrounding chains are correctly rehashed.

For every state-changing non-result cause, replay derives the exact live-policy
projection and authority artifacts from the prior immutable state. This
includes acknowledgement acceptance or rejection, safe-retry decisions,
heartbeat time and expiry, cancellation outcomes, Worktree observations from
the exact shared live/replay reducer,
Lease and approval-proposal expiry, readiness, dispatch blockers, and Lease or
Worktree acquisition and release. Causes that are not permitted to produce
Lease history must have zero rows at that event sequence. A broadly allowed
state pair or projection field subset is not sufficient evidence.

`agents recover` validates the exact schema and immutable graph, event,
message, lease-history, budget-history, and worktree-history evidence. It then
copies only that evidence into a fresh schema and rebuilds tasks, dependencies,
current leases, budget totals, current worktrees, approval consumption, and
per-host capabilities. Recovery performs the same semantic event replay before
copying evidence. The rebuilt database must match the source evidence and
validate completely before exclusive publication. The source is never
modified. Damaged immutable evidence, an existing output, a publication race,
or an evidence mismatch fails closed.

## Lease, mailbox, and budget safety

Lease TTL is 30 through 3600 seconds. Heartbeat interval is 5 seconds through
half the TTL, capped at 300 seconds. One policy pair is selected at database
initialization, recorded in metadata and the initialization event, included in
recovery identity, and immutable for that store. Every later tick, Lease, and
dispatch payload must reproduce that pair exactly. Activated fences and attempts start at 1
and increase monotonically. Before an approval-bound activation, the scheduler
persists a provisional current Lease so external decisions can name its exact
owner, attempt, fence, Lease ID, and idempotency key. Later ticks reuse that
identity even if their timestamp or invoking host differs. An unactivated
proposal may expire and rotate without reserving concurrency or consuming an
execution attempt. A late or foreign message cannot release, complete, cancel,
or otherwise change the current projection. Each tick expires authoritative
Leases before ingest, and every Lease-bound host message requires
`now < expires_at`; equality is expired.

Duplicate message identity is idempotent and retained once. Heartbeats,
approval decisions, and worktree observations may carry distinct periodic or
multi-authority content under the stable attempt key; every other different
message that reuses the same type/direction/idempotency identity is rejected as
a conflict. Each accepted heartbeat publishes a new current Lease artifact
while retaining the original lease ID as authority. Missing causal parents,
unknown tasks, wrong recipients, lower sensitivity, stale leases, invalid
result wrappers, and unexpected worktree observations produce rejection
events. A closed causal phase table requires exactly one matching scheduler
dispatch parent for acknowledgements, heartbeats, and results. A provisional
approval Lease therefore grants no execution traffic authority before dispatch.
Host identity is strict: Lease-bound traffic must come from both the current
owner and the host invoking the tick. Capability observations are stored by
host and readiness uses only the current Lease owner's latest observation, or
the invoking host when no Lease exists.

Dispatch, retry, concurrency, context-byte, tool, solver, wall-time, and
optional cost limits are exact nonnegative integers. Reservations and usage
change in the same transaction as the protected state transition. Missing
capability and exhausted budget are named blockers; unavailable cost is not
fabricated. Dispatch reserves exact Context bytes, required-tool calls, solver
capacity, and available cost capacity. A typed result reports bounded integer
usage. Outstanding reservations are reconstructed for the exact Lease from
immutable dispatch and settlement events. Acknowledgement, result, rejection,
cancellation, and expiry therefore settle or release each resource at most
once and cannot borrow another attempt's aggregate reservation. Effective
concurrency is `max_concurrency`; both schema and runtime require it not to
exceed `max_agents`.

Budget history is independently reduced from the zero initial state and exact
configured availability. Every cause-specific reservation, settlement,
release, conservative charge, retry, dispatch, concurrency change, and wall-
time observation must have the exact event delta. The initial Budget Ledger
plus every and only budget-changing event must have one exact snapshot; each
intermediate Ledger and the mutable final totals must equal the reducer. A
rehashed lowered Ledger, matching corrupted totals, omitted retry delta, or
added, removed, or moved snapshot therefore cannot authorize recovery.
Dispatch reservation is rederived from the exact graph and task, verified
Context byte size, required tools, solver kind, cost availability, and prior
replayed totals; neither the message nor event supplies that authority. Result
usage cannot exceed that Lease's original rederived reservation, and wall time
is the exact whole-second elapsed value from store creation to event time minus
the prior replayed total. Metadata creation time must equal the sequence-1
initialization event. Event times never decrease, and any operation whose
whole-second elapsed value advances must first emit exactly one wall-time
observation; missing, extra, moved, smaller, or larger observations fail before
recovery publication. A dispatch-budget blocker must reproduce a real
admission failure, just as an approval blocker must reproduce a missing exact
approval.

The durable wait-for projection uses typed nodes and edges for dependencies,
review targets, Lease phases, worktree ownership and observation, approvals,
capabilities, and budget blockers. Application status, CLI status, and the
simulator derive deterministic stall/deadlock reports from this same production
projection; none invents an unavailable provider or resource.

Owner and technical-sandbox approvals arrive only as externally authored,
time-bounded `approval_decision` messages. The exact approval must match the
persisted provisional dispatch identity, effect digest, attempt, lease, fence,
and idempotency key and is consumed once. An approval with no matching current
proposal or an invalid time window is rejected. The scheduler never creates
approval or reuses one for a later attempt. Owner approval is accepted only from
`HST-OWNER` with authority `Owner`; technical-sandbox approval is accepted only
from `HST-TECHNICAL-SANDBOX` with authority `Technical sandbox reviewer`.
Multiple required approvals are selected and consumed atomically immediately
before the protected dispatch and only after budget admission succeeds. The
delayed worktree path revalidates freshness and exact identity at activation;
an expired earlier decision cannot authorize dispatch after a later worktree
observation. A budget-blocked observed-worktree activation preserves the same
current Lease, attempt, fence, idempotency key, Worktree Lease, concurrency
reservation, and unconsumed approvals. After another attempt releases the
required capacity, a later tick reuses the exact earlier observation and Lease,
then consumes the same still-current approval exactly once when dispatch is
admitted.

Tasks with a worktree assignment emit `worktree_request`, require an exact
causal `worktree_observation` while the same current Lease remains in the
`not_dispatched` phase, and emit `dispatch_intent` only after a non-ambiguous
observation of the assigned path. An ambiguous observation
releases task authority and remains `blocked/unknown`. Requested, observed,
integrated, blocked, and released lifecycle evidence remains immutable; only
active states retain current authority, so a released worktree may be acquired
by a later sequential task. Cooperative cancellation uses a durable
scheduler-authored `cancel_request`; an acknowledgement without that exact
causal request is rejected. A cancellation request at or after Lease expiry
first commits the normal expiry transition and is not admitted or replayed as
current authority. Cancellation creation itself first accounts for wall time
and accepts only the latest primary-adopted dispatch or Worktree intent for the
exact current Lease and live task phase; raw, old-attempt, or provisional-only
mailbox history is not a parent authority.

## Host boundary

The packaged `AgentHostPort` and `WorktreeHostPort` have no real implementation.
Their default adapters raise an unsupported-operation error. `schedule tick`
commits state and returns outbound typed intents; it does not invoke a process,
Codex CLI, API, network, or Git command.

A host that adopts these ports must deduplicate idempotency keys, preserve
message size and sensitivity, return typed observations, and treat the current
fence as the only authority. Host success text is never equivalent to SDAQF
verification, Gate G3 review, publication authority, or Owner approval.

## CLI

The additive commands are:

```text
sdaqf agents schedule validate TASK_GRAPH --root ROOT --json
sdaqf agents schedule init TASK_GRAPH --root ROOT --state STATE --json
sdaqf agents schedule tick STATE --root ROOT --host-id HOST [--message MESSAGE]... --json
sdaqf agents schedule status STATE --root ROOT --json
sdaqf agents schedule export STATE --root ROOT --kind KIND --output FILE [--after-sequence N] [--limit N] --json
sdaqf agents mailbox inspect STATE --root ROOT [--task TASK] [--direction DIRECTION] [--limit N] --json
sdaqf agents recover STATE --root ROOT --output NEW_STATE --json
sdaqf agents simulate TASK_GRAPH --root ROOT --scenario SCENARIO --json
```

Inputs and outputs are explicit, root-confined, regular, bounded, and never
overwritten. JSON failures are bounded and do not disclose absolute paths.

## Simulation and validation

The ten scenarios are `success`, `worker-crash-after-dispatch`, `host-timeout`,
`result-disagreement`, `wait-for-deadlock`, `budget-exhaustion`,
`missing-capability`, `duplicate-and-late-result`, `cancellation-unknown`, and
`ambiguous-external-effect`. Every run uses a fixed clock and a fresh real
SQLite store with no host or network effect.

Run the named Gate from the repository root:

```text
python scripts/validate_m6_scheduler.py
```

`PASS: M6-SCHEDULER-SAFETY` establishes positive and negative runtime/schema
parity for structurally representable contracts, authoritative cross-field
time validation, exact SQLite identity and schema, one-owner claiming,
reconstruction after deliberate projection corruption, rejection and
no-output recovery for deliberate rehashed result, scheduler-egress, and
budget-history corruption, exact ten-scenario reproduction, and stable top-
level exports. Runtime and schema share the same
single-line, path-free safe-text boundary and capability-observation identity
shape. Scenario assertions, evaluation records, and validator checks use the
durable production wait report; the crash case reopens the store, cancellation
uses a real request, and stalls as well as deadlocks retain their typed blocker
edges. It does not establish independent review, remote CI, publication, or
production readiness.

## Non-goals and limits

M6 does not implement a real subagent host, nested Codex execution, automatic
Git worktree lifecycle, solver, hosted workflow runtime, OpenAI API, Agents
SDK, management UI, external publication, destructive cleanup, or in-place
database migration. macOS remains `NOT_VERIFIED`; Windows/Linux exact-candidate
CI remains required before a platform claim.
