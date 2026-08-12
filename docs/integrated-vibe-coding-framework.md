# Integrated Vibe-Coding Framework

M8 is an experimental, offline integration layer over the existing SDAQF
requirements, Context, scheduler, solver, evidence, review, Gate, and handoff
contracts. It accepts a Development Intent as untrusted scope input, creates a
deterministic Integrated Plan, projects native runtime truth into immutable
Workflow Events and States, and derives a bounded Workflow Outcome. It is not
an autonomous coding runtime and does not turn intent or model text into
authority.

## Authority and trust boundaries

The existing subsystems remain authoritative:

- M1 owns Requirement Baselines and G1 requirements validation.
- M5 owns Context Graph, Query, Selection, Snapshot, compaction, provenance,
  sensitivity, and artifact identities.
- M6 standard-library SQLite v2 is the sole mutable authority for the current
  workflow epoch head and owns tasks, leases, fences, idempotency, budgets,
  approval consumption, events, mailboxes, workflow publication receipts,
  recovery, and typed host intents. Immutable M8 artifacts are evidence and
  read models, never mutable-head authority.
- M7 owns Solver Registry, Request, Result, Verification, bounded reference
  solving, and solver evidence.
- M3 owns evidence, independent review, G2 through G4, candidate observations,
  and Automated Handoff semantics.

M8 invokes or composes those validators and stores by exact reference. It does
not define a second Context, scheduler, solver, Approval, Gate, Candidate,
evidence, review, completion, or handoff authority. Development Intent and
host-authored task links, context choices, roles, solver formulations,
implementation text, and review text are untrusted data until deterministic
validation accepts them.

The core has no OpenAI API, Agents SDK, hosted service, management UI, vector
database, external solver, network, credential, charge, deployment, or
publication dependency. Host adapters may dispatch typed intents or perform
host-controlled worktree operations only outside this core and only under a
separately approved contract.

## Five immutable artifacts

Every M8 artifact uses schema version `1.0` and the envelope
`schema_version`, `artifact_type`, `artifact_id`, and `content`. The ID is the
type prefix plus the full uppercase SHA-256 of M5 canonical JSON content. The
ID itself is outside the hashed content.

| Artifact | ID prefix | Maximum bytes | Purpose |
|---|---|---:|---|
| Development Intent | `M8-DEVELOPMENT-INTENT-` | 1,048,576 | Untrusted project scope, references, budget ceiling, and proposed bindings |
| Integrated Plan | `M8-INTEGRATED-PLAN-` | 16,777,216 | Validated deterministic selections, exclusions, uncertainty, policy, and native references |
| Workflow State | `M8-WORKFLOW-STATE-` | 16,777,216 | Immutable read model of one exact Plan and current native truth |
| Workflow Event | `M8-WORKFLOW-EVENT-` | 1,048,576 | Hash-addressed integration transition record linked to the prior State and Event |
| Workflow Outcome | `M8-WORKFLOW-OUTCOME-` | 16,777,216 | Truthful disposition, blockers, ambiguity, measurements, and next action |

Canonical JSON has sorted ASCII keys, no insignificant whitespace,
`ensure_ascii=true`, finite integers only, and no lone surrogates. Safe relative
paths are at most 240 characters. Single-line reasons are at most 4,000
characters. Plans allow at most 4,096 tasks, 4,096 artifact references, and
16,384 decisions; States and Outcomes allow at most 256 blockers and 256
protected effects; each protected effect has at most two approval
requirements; event sequence is at most 2,147,483,647.

Sensitivity is exactly `public`, `repository-private`, `owner-private`, or
`secret-or-prohibited`. Derived artifacts take the highest referenced level
and never downgrade automatically. Raw secret-shaped or prohibited content is
rejected. A secret-or-prohibited Intent may retain only the literal redaction
marker and digest metadata; the local planner refuses to produce a secret Plan.

## Development Intent and Integrated Plan

Development Intent binds one exact CandidateIdentity, canonical specification,
Requirement Baseline, allowed and prohibited paths, required requirement and
acceptance-criterion IDs, requested effect kinds, risk, clearance, an M6-shaped
hard budget ceiling, optional capability requests, exact M5 and M6 artifacts,
optional M7 requests, proposed task links, required Gates, observation slots,
and any explicit predecessor Plan, superseded State, and Outcome.

Planning validates the M1 baseline and G1, M5 Graph/Query/Selection/Snapshot,
M2 Registry and orchestration references carried by the M6 Task Graph, the M6
Task Graph itself, and every selected M7 Request. Every path must be regular,
unlinked, root-confined, bounded, digest-matched, and validator-approved.
Structural JSON validity alone is insufficient.

`IntegratedPlanner` is side-effect-free. It performs no filesystem write,
scheduler tick, host dispatch, solver run, approval consumption, Git mutation,
or network action. The local adapter may perform the existing bounded,
read-only Candidate observation before and after planning. Plan publication
retains that same store-wide observation, revalidates it after output preflight,
and only then opens the M6 epoch; a one-head snapshot never silently narrows to
one Plan. Subjects are ordered by phase, M6
topological rank, wave, subject kind, and full identifier; sets use ordinal
ordering. Locale, floating-point scores, model rankings, and filesystem
iteration order are never authoritative.

Selection reasons are closed to `required-by-intent`,
`required-by-requirement`, `required-dependency`, `required-context`,
`review-separation`, `gate-prerequisite`, `solver-justified`, and
`handoff-required`. Exclusion reasons are closed to
`outside-allowed-scope`, `inside-prohibited-scope`,
`unsupported-capability`, `budget-exceeded`, `approval-not-authority`,
`evidence-unavailable`, `solver-not-justified`, `ui-not-applicable`, and
`optional-context-not-selected`. Uncertainty reasons are closed to
`open-decision`, `blocking-diagnostic`, `unresolved-contradiction`,
`stale-context`, `cost-not-available`, `capability-not-observed`, and
`external-effect-ambiguous`.

`WorkflowExplainer` reloads all referenced bytes and recomputes the exact Plan.
It reports selection, exclusion, uncertainty, budget, approval, evidence,
Gate, and completion reasons in deterministic JSON or English. Stored prose is
not a reason authority.

One Plan ID is one M6 workflow epoch and binds one candidate and one M6 Task
Graph. Specification, Git
HEAD, repository digest, Context, graph, or solver-contract drift makes it
stale. A new candidate requires exact predecessor Plan, superseded State, and
superseded Outcome bindings. Old artifacts, approvals, evidence, and ambiguity
remain immutable; supersession never migrates authority or makes an ambiguous
effect retryable.

## Runtime, resume, and recovery

Workflow statuses are `planned`, `ready`, `running`, `blocked`,
`verification`, `completed`, `rejected`, and `superseded`. Event causes are
`plan-adopted`, `runtime-started`, `context-revalidated`,
`scheduler-advanced`, `approval-blocked`, `approval-revalidated`,
`solver-revalidated`, `evidence-revalidated`, `review-revalidated`,
`gate-evaluated`, `ambiguity-recorded`, `recovery-observed`,
`plan-superseded`, `handoff-revalidated`, and `outcome-produced`.

One `run` or `resume` call performs at most one M6 scheduler tick and one M8
transition. It returns typed outgoing intent identities but does not dispatch
them. Each Event records a one-based sequence, previous Event ID, exact prior
State binding, Plan and candidate, actor, cause, before/after status, M6 event heads,
referenced artifacts, reason codes, effect disposition, and UTC time. It omits
the new State ID to avoid circular identity.

M6 v2 records an append-only workflow epoch chain and a replay-checked current
head. Ordinary transitions reserve their exact Event and State publication;
terminal Outcome and supersession first commit `terminal-reserved`, which is
the terminal linearization point. Event, closure State, and Outcome are then
published exclusively and their exact canonical artifact IDs and paths are
confirmed in M6 before `terminal-confirmed`. Both terminal phases reject
resume, ordinary recovery, supersession, and a different Outcome. A crash may
be finalized at least once only by the same source authority, idempotency key,
canonical artifact IDs, and output paths. A foreign collision is never
overwritten, deleted, repaired, released, or redirected automatically.
The terminal reservation, confirmation, and exact confirmation retry share one
`recorded_at`. Confirmed Plan and terminal artifacts are accepted only as
canonical receipt-matched retries.
The terminal State is the published closure State; it is not a caller-selected
historical State or a second mutable head.

Candidate, G3, and G4 consume one immutable publication observation built from
one bounded Git enumeration and one validated, pinned M6 receipt snapshot.
Tracked files are always publication inputs. An immutable runtime output is
excluded only when it is untracked and non-ignored and its normalized path,
canonical artifact ID, producer, Plan/epoch, Candidate, graph, reservation,
and existing bytes agree with M6. Content shape, SQLite headers, names,
directories, sibling discovery, and caller assertions grant no private
provenance. The explicitly supplied active database is private only after its
v2 schema, integrity, history, projection, graph, path binding, and current
epoch head validate. Case collisions, symbolic links, junctions, and reparse
points fail closed.

Recovery never edits the source State, Event, or M6 database. M6 recovery
copies and semantically replays the epoch chain and receipts into a fresh v2
database before M8 may use it. Missing, added, reordered, or inconsistent
epoch evidence publishes no recovered database. Nonterminal M8 recovery then
replays supplied orphan Events and native evidence before publishing a fresh
Event and State. A terminal-reserved epoch permits only exact pending
finalization, not ordinary recovery. There is no cross-store transaction or
exactly-once claim.

## Protected effects and ambiguity

External or destructive effects, approval-stopped M6 tasks, protected paths,
and Tool Registry approval requirements are protected. Git/worktree changes,
publication, deployment, credentials, charges, network access, repository
settings, and requirement weakening remain protected under their existing
policies.

Before an M6 tick, M8 replays Plan, candidate, Context, graph, task, effect
identity, and Tool policy. M6 then owns transactional budget, actor, Lease,
fence, idempotency, and single-use approval checks. M8 refuses to return any
protected outgoing intent unless the resulting current Lease, fence,
idempotency key, effect identity, and consumed approvals revalidate exactly.
Technical sandbox approval never substitutes for Owner approval. Intent,
model text, explanation, Outcome, and handoff text never grant approval.

If evidence cannot prove whether a protected or external effect occurred, the
workflow records `blocked/unknown` and `external-effect-ambiguous`. It does not
retry, infer success, delete evidence, or erase ambiguity during supersession.

## Gates, completion, and handoff

M8 has four completion profiles: `plan-only`, `implementation-verified`,
`independent-review-accepted`, and `release-candidate-ready`. It composes G1 through G4 and Automated
Handoff rather than replacing them. Outcomes are `completed`, `blocked`,
`rejected`, or `superseded` and cannot upgrade native task, solver, evidence,
review, Gate, or handoff truth.

Plan-only completion requires a validated baseline, passing G1, reproducible
Plan, and no planning blocker. Implementation completion additionally requires
native task success, required evidence and solver verification, applicable
Gates, and a completed Automated Handoff. Independent-review-accepted
additionally requires the existing independent-review contract and no
unresolved blocking finding. Release-candidate-ready additionally requires
validated M3 project-manifest, UI-validation, and release-candidate observations
plus the existing G4 service. When `ui_required=true`, valid native M3 UI
evidence and a passing G4 satisfy the UI condition; the flag is not itself a
permanent blocker. G3 receives the exact independently observed changed and
candidate path sets and never obtains its scope from the review's own
`reviewed_paths`;
it is local readiness, never publication authorization.

## Simulation and measurements

The deterministic fixed-clock simulator derives each scenario from one exact
scenario Plan, one fresh real M6 SQLite v2 store and Event history, and the
Outcome from that same execution. It authenticates the input Plan against the
supplied M6 authority, then uses one of exactly three real synthetic public
fixture bundles: `evals/projects/offline-config/`,
`evals/projects/ui-issue-tracker/`, or `evals/projects/secure-export/`. Each
bundle has one canonical `fixture_bundle_id`. It uses the real M8
planner, runtime, status, recovery, supersession, and Outcome contracts. Its
twelve scenarios are `non-ui-success`,
`ui-observation-unavailable`, `approval-required`, `approval-refused`,
`approval-expired`, `stale-candidate`, `stale-context`, `lease-lost`,
`solver-inconclusive`, `ambiguous-external-effect`, `crash-and-recovery`, and
`candidate-supersession`. UI success means an honest block when real UI
evidence is unavailable; it does not claim a browser or management UI.

The public scenario disposition and blockers come only from the actual
generated Workflow Outcome and terminal State, never from an observer label or
fixture name. Evaluation reports exactly 52 measurements in nine groups:
requirements, context, scheduling, solver, evidence, handoff, recovery,
approval, and `available_cost`. It publishes no aggregate score. The named
validator independently reloads native Plan, State, Event, M5, M6, M7, and M3
evidence and recomputes every status, value, unit, and source set without
calling or trusting the producer measurement implementation.

## CLI

The additive namespace is:

```text
sdaqf workflow validate ARTIFACT --json
sdaqf workflow plan INTENT --root ROOT --scheduler-state SUCCESSOR_DB --predecessor-scheduler-state PREDECESSOR_DB --output PLAN --json
sdaqf workflow explain PLAN --root ROOT --scheduler-state SUCCESSOR_DB [--predecessor-scheduler-state PREDECESSOR_DB] --json
sdaqf workflow simulate PLAN --root ROOT --scheduler-state SUCCESSOR_DB [--predecessor-scheduler-state PREDECESSOR_DB] --scenario SCENARIO --json
sdaqf workflow run PLAN --root ROOT --scheduler-state SUCCESSOR_DB [--predecessor-scheduler-state PREDECESSOR_DB] --output-state STATE --output-event EVENT --json
sdaqf workflow resume STATE --plan PLAN --root ROOT --scheduler-state SUCCESSOR_DB [--predecessor-scheduler-state PREDECESSOR_DB] --output-state NEXT_STATE --output-event EVENT --json
sdaqf workflow supersede STATE --plan PLAN --successor-intent INTENT --root ROOT --scheduler-state DB --output-state SUPERSEDED_STATE --output-event EVENT --output-outcome OUTCOME --json
sdaqf workflow status STATE --plan PLAN --root ROOT --scheduler-state SUCCESSOR_DB [--predecessor-scheduler-state PREDECESSOR_DB] --json
sdaqf workflow recover STATE --plan PLAN --root ROOT --scheduler-state SUCCESSOR_DB [--predecessor-scheduler-state PREDECESSOR_DB] --event EVENT [--event EVENT]... --output-state RECOVERED_STATE --output-event RECOVERY_EVENT --json
sdaqf workflow outcome STATE --plan PLAN --root ROOT --scheduler-state DB --output OUTCOME --output-event EVENT --output-state CLOSURE_STATE --json
```

`--predecessor-scheduler-state` is forbidden when all predecessor fields are
null and required when they are all present. Genesis plan, explain, simulate,
run, resume, status, recover, and Python terminal-observation finalization
therefore omit the argument; all corresponding successor paths use distinct
successor and predecessor databases. Existing genesis CLI and Python calls
remain compatible.

Plan opens its M6 epoch and reserves/confirms its Plan output. Explain
authenticates the Plan receipt. Simulate authenticates and reproduces the input,
then runs the scenario as a fresh genesis execution in an isolated v2 store.
Outcome and supersession reserve their
complete terminal publication in M6 before publishing a non-circular Event,
adopting closure State, and Outcome. Exact retries converge; different bytes,
paths, case aliases, identities, or requests fail closed without overwrite.
A generated Plan, explanation, simulation,
Outcome, or handoff never executes its own protected or external action.

## Validation boundary

`M8-WORKFLOW-INTEGRATION` validates all five public artifacts and schemas,
negative runtime/schema parity, native M5-M7 composition, deterministic Plan
explanation, runtime, status, recovery, Outcome, all twelve simulations, the
nine non-aggregate measurement groups, unchanged dependencies, and unchanged
stable top-level exports. It is local evidence only and does not replace G1-G4,
independent review, exact-SHA remote CI, release approval, or production
validation.

For the Owner-approved 2026-08-09 remediation candidate, the focused M6/M8
selection passes 246 tests with one explicit Windows directory-symlink
capability skip. Ruff and strict mypy pass all 43 approved Python targets; the
named validator passes M5 through M8; and its independent resolver reproduces
all twelve real Outcomes, three fixture bundles, and all nine groups/52
measurements. The earlier independent round-three review accepted F1 through
F11 but retained overall NO-GO because successor resume, status, recovery, and
Python terminal-observation finalization could not reproduce predecessor
authority after the first run. The follow-up propagates that exact optional
authority through each lifecycle path. The latest independent successor
lifecycle compatibility review returned GO for the reviewed M8 repository
state, maintained every F1-through-F11 ACCEPT result, and left zero unresolved
findings within its scope, superseding the earlier overall NO-GO for that state.

That review records PASS for 28 focused compatibility/CLI tests, the 120-test
complete M8 selection, the 9-test round-three regression selection,
whole-project Ruff, strict mypy, all M5-through-M8 named validators, and
M0-through-M8 CLI smoke. It did not rerun full pytest or coverage; the prior
round-three full and coverage run remains supporting evidence only. M8 remains
Experimental and unreleased. This compatibility GO did not establish release
GO or production readiness. The reviewed M8 state was later committed, pushed,
and merged to `main`, whose exact-triggering-SHA Actions run `31497539609`
passed the full matrix. The separate M6 status-publication state later passed
exact pull-request head run `31558960113`, merged through pull request #4, and
passed post-merge `main` exact-triggering-SHA run `31563987706`. The M8 review
did not decide M5 or M6. Their
historical later final NO-GO reviews remain recorded; the latest M5 and M6
dispositions are GO. None of these statuses revises this M8 disposition or the
existing M7 GO.
