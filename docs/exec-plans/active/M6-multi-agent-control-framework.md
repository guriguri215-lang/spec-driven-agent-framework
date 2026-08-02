# M6 Multi-Agent Control Framework

This living ExecPlan follows `PLANS.md`. Keep Progress, Surprises &
Discoveries, Decision Log, and Outcomes & Retrospective current as the
candidate advances through local validation, independent review, Git
finalization, and exact-candidate CI.

## Purpose / Big Picture

M6 turns the existing deterministic M2 role plan into offline, durable,
resumable, host-agnostic execution control. A user or host can initialize a
validated task DAG, advance it transactionally, exchange bounded typed
messages, recover after crashes without rewriting history, inspect exact
blockers, and reproduce success and failure scenarios locally.

The observable result is:

- every task consumes an exact M5 Context Snapshot and exact candidate;
- SQLite has one canonical transactional task/event/lease/budget state while
  portable audit records remain immutable content-addressed JSON;
- at-least-once dispatch uses stable idempotency keys and fenced single-owner
  leases without claiming exactly-once execution;
- duplicate, conflicting, stale, foreign, and late results cannot mutate the
  current task projection;
- cancellation and ambiguous effects remain truthful `blocked/unknown`;
- roles, paths, approvals, budgets, review separation, and worktree authority
  are checked before every protected transition;
- simulation executes the real state machine with no network or host effect;
- `M6-SCHEDULER-SAFETY` reports named outcomes without an aggregate score.

## Progress

- [x] (2026-08-01) Verified the exact M5 baseline commit, clean starting
  index/worktree, required local evidence, and the bounded implementation
  scope.
- [x] (2026-08-01) Obtained Owner approval for M6-D1 through M6-D7 and the
  exact 53-path tracked implementation scope.
- [x] (2026-08-01) Completed Checkpoint 1: frozen domain contracts, strict
  loaders, seven schemas/examples, exact M2/M5 binding, ports, and parity
  tests.
- [x] (2026-08-01) Completed Checkpoint 2: SQLite schema 1, transactional
  transitions, events, leases, mailbox, budgets, approvals, and worktree
  observations.
- [x] (2026-08-01) Completed Checkpoint 3: fresh-output recovery, exact CLI,
  ten real-store simulations, public evaluation, M0-through-M6 smoke, and the
  named validator.
- [x] (2026-08-01) Completed Checkpoint 4 implementation and the full local
  Release Contract: 850 tests passed with three platform-capability skips,
  total coverage was 90 percent, M1/M2/M3/M4/M6 critical coverage was at
  least 90 percent, M5 coverage was 83 percent, and all named validators,
  smoke, evaluation, audits, dependency checks, and whitespace checks passed.
- [x] (2026-08-01) Froze the final local candidate for private path/hash and
  Git-state evidence capture without staging or remote access.
- [x] (2026-08-01) Resolved the temporal test conflict between the required M6
  CI change and the historical M4 workflow evidence. The first approved
  two-path amendment preserved the exact M4 workflow while leaving the M4
  evidence record unchanged; the second approved amendment updated the M4
  public-contract test to verify those historical bytes. Targeted and full
  suites passed afterward.
- [x] (2026-08-01) Obtained separate Owner approval and completed a logically
  independent read-only review in reviewer task
  `019fbb81-56bb-7903-9846-0ca07c33f387`. The exact frozen fingerprint was
  preserved; the review returned NO-GO with zero Critical, seven High, and two
  Medium findings.
- [x] (2026-08-01) Remediated all nine review findings inside the approved
  56-path scope: external approval authority and atomic dual consumption,
  protected-transition identity/evidence checks, exact SQLite projection
  recovery, causal cancel/worktree requests, periodic heartbeat leases, full
  budget reservation/settlement, durable validator scenarios, sensitivity
  parity, and deep immutable artifact values.
- [x] (2026-08-01) Repeated the full local Release Contract for the remediated
  candidate. Coverage first exposed one missing recovery-boundary test; after
  adding a durable worktree/capability projection reconstruction case without
  lowering thresholds, the complete Gate passed with 865 tests, three explicit
  platform-capability skips, and 90 percent M6 critical branch coverage.
- [x] (2026-08-01) Froze the remediated candidate for new private path/hash
  evidence without staging, network, or remote access.
- [x] (2026-08-01) Obtained separate Owner approval and completed the second
  logically independent read-only review in reviewer task
  `019fbbe2-870c-7973-a2cd-882cd22c225e`. The reviewed fingerprint was
  reproduced before and after review; the result was NO-GO with zero Critical,
  four High, two Medium, and one Low finding.
- [x] (2026-08-01) Obtained Owner approval for the exact 20-path second
  remediation and closed all seven findings: persisted approval-proposal
  identity, closed completion predicates, exact missing-row projection checks,
  attempt-scoped budget settlement, schema/runtime parity, M5 roadmap
  restoration, and M6 CLI wording.
- [x] (2026-08-01) Repeated the full local Release Contract after the second
  remediation. It passed with 874 tests, three explicit platform-capability
  skips, 134 focused M6 tests, and total/M1/M2/M3/M4/M5/M6 branch coverage of
  90/94/90/91/92/83/90 percent. Ruff, strict mypy over 137 files, both named
  validators, M0-through-M6 CLI smoke, evaluation reproduction, workspace,
  publication, and dependency audits, `pip check`, and whitespace validation
  all passed without changing a threshold.
- [x] (2026-08-01) Freeze the second-remediated candidate for exact private path/hash and
  Git-state evidence without staging or remote access.
- [x] (2026-08-01) Obtained separate Owner approval and completed the third
  logically independent read-only review in reviewer task
  `019fbc4c-a051-72b1-9809-810c9349ee79`. The result was NO-GO with zero
  Critical, eight High, two Medium, and zero Low findings.
- [x] (2026-08-01) Obtained Owner approval for the exact 22-path third
  remediation and implemented expire-before-ingest Lease authority, closed
  causal/event replay, activation-time approval consumption, production D6
  wait projection, full Worktree Lease lifecycle/reuse, per-host capability
  isolation, strict generated ingress, schema/runtime path/text parity, and
  unresolved-link/reparse rejection.
- [x] (2026-08-01) Repeated the complete local Release Contract after the
  third remediation. It passed with 921 tests, four explicit platform-
  capability skips, 157 focused M6 tests with one symlink-capability skip, and
  total/M1/M2/M3/M4/M5/M6 branch coverage of 90/94/90/91/92/83/91 percent.
  Ruff, strict mypy over 137 files, both named validators, M0-through-M6 CLI
  smoke, evaluation reproduction, workspace/publication/dependency audits,
  `pip check`, and whitespace validation all passed without lowering a
  threshold.
- [x] (2026-08-01) Froze the exact third-remediated candidate for private
  path/hash and Git-state evidence without staging, network, or remote access.
- [x] (2026-08-01) Obtained separate Owner approval and completed the fourth
  logically independent read-only review in reviewer task
  `m6_fourth_independent_review`. The exact 55-record fingerprint
  `82EBD49B4B779261F027D2A90AB6C0294369AE67A2160B6634EF7ADD38A28E22`
  was reproduced before and after review. The result was NO-GO with zero
  Critical, one High, four Medium, and zero Low findings.
- [x] (2026-08-01) Obtained Owner approval for the exact 22-path fourth
  remediation and a one-path test-scope amendment. Implemented total 24-cause
  event replay and scheduler-egress proof, budget-before-approval admission,
  durable simulation/evaluation stall reporting, schema/runtime safe-text and
  capability-identity parity, and expiry-bound cancellation. The focused M6
  regression currently passes 215 tests with one symlink-capability skip;
  Ruff, strict mypy over 137 files, and `M6-SCHEDULER-SAFETY` also pass.
- [x] (2026-08-01) Repeated the complete local Release Contract after the
  fourth remediation. It passed with 955 tests, four explicit platform-
  capability skips, 215 focused M6 tests with one symlink-capability skip, and
  total/M1/M2/M3/M4/M5/M6 branch coverage of 90/94/90/91/92/83/90 percent.
  Ruff, strict mypy over 137 files, both named validators, M0-through-M6 CLI
  smoke, evaluation reproduction, workspace/publication/dependency audits,
  `pip check`, and whitespace validation all passed without lowering a
  threshold. One parallel validation attempt transiently observed another
  validator's owned temporary directory; the affected smoke and audit both
  passed when repeated sequentially after confirming no temporary residue.
- [x] (2026-08-01) Froze the exact fourth-remediated candidate for private
  path/hash and Git-state evidence without staging, network, or remote access.
- [x] (2026-08-01) Obtained separate Owner approval and completed the fifth
  logically independent read-only review in reviewer task
  `m6_fifth_independent_rereview`. The exact 55-record fingerprint
  `492AFF2294F7D64F08998BDD73862D7A20FF653677441A0264ACF108F556690B`
  was reproduced before and after review. The result was NO-GO with zero
  Critical, three High, one Medium, and zero Low findings.
- [x] (2026-08-01) Obtained Owner approval for the exact 12-path fifth
  remediation and a one-path evaluation-result amendment. Implemented exact
  successful and terminal result replay, complete scheduler-egress envelope
  and causal authority, deterministic event-derived Budget Ledger history,
  retry deltas, and same-store same-Lease delayed Worktree admission. The
  focused approved tests pass 173 cases with one symlink-capability skip; the
  complete M6 selection passes 240 cases with the same skip, and the strengthened
  `M6-SCHEDULER-SAFETY` validator passes deliberate result, egress, and budget
  corruption/recovery cases.
- [x] (2026-08-01) Repeated the complete local Release Contract for the fifth
  remediation. It passed with 980 tests, four explicit platform-capability
  skips, 240 focused M6 tests with one symlink-capability skip, and
  total/M1/M2/M3/M4/M5/M6 branch coverage of 90/94/90/91/92/83/90 percent.
  Ruff, strict mypy over 137 files, both named validators, M0-through-M6 CLI
  smoke, evaluation reproduction, workspace/publication/dependency audits,
  `pip check`, and whitespace validation all passed without lowering a
  threshold. The first coverage run reproduced the previously classified
  one-second CLI lifecycle boundary; the unchanged command passed on its one
  justified sequential retry.
- [x] (2026-08-01) Froze the exact fifth-remediated candidate for private
  path/hash and Git-state evidence without staging, network, or remote access.
- [x] (2026-08-01) Obtained separate Owner approval and completed the sixth
  logically independent read-only review in reviewer task
  `m6_sixth_independent_rereview`. The exact 55-record fingerprint
  `B27BB79C672A22C12B1B4F4B901A3B5D30B81D6326DCC27674AB8678AA3DFAFA`
  was reproduced before and after review. The result was NO-GO with zero
  Critical, three High, zero Medium, and zero Low findings.
- [x] (2026-08-01) Obtained Owner approval for the exact 12-path sixth
  remediation. Implemented exact cause-specific non-result replay, a complete
  immutable message-adoption ledger, and independently rederived dispatch,
  result-usage, blocker, and wall-time budget authority. Correctly rehashed
  acknowledgement, Lease, orphan-message, approval-effect, admission-blocker,
  result-overuse, and wall-time forgeries now fail validation and fresh-output
  recovery.
- [x] (2026-08-01) Repeated the complete local Release Contract for the sixth
  remediation. It passed with 990 tests, four explicit platform-capability
  skips, 250 focused M6 tests with one symlink-capability skip, and
  total/M1/M2/M3/M4/M5/M6 branch coverage of 90/94/90/91/92/83/90 percent.
  Ruff, strict mypy over 137 files, both named validators, M0-through-M6 CLI
  smoke, evaluation reproduction, workspace/publication/dependency audits,
  `pip check`, and whitespace validation all passed without lowering a
  threshold.
- [x] (2026-08-01) Froze the exact sixth-remediated candidate for private
  path/hash and Git-state evidence without staging, network, or remote access.
- [x] (2026-08-01) Obtained separate Owner approval and completed the seventh
  fresh independent read-only review in `m6_seventh_independent_rereview`. It
  reproduced fingerprint
  `952D9EF1A48BB712EB0D68B31185384C4D083529C0DB56E55B510D9F6F3BB978`
  before and after inspection and returned NO-GO with zero Critical, three
  High, zero Medium, and zero Low findings. All three High findings were
  classified as materially recurrent.
- [x] (2026-08-01) Applied the Owner's loop-safety stop, obtained explicit
  authorization to continue despite recurrence, and implemented the seventh
  remediation: initialization-bound immutable Lease policy and whole-object
  replay, exact cause-derived Worktree history cardinality, primary-adopted
  same-Lease cancellation selection, commit-time self-validation, and
  initialization-anchored nondecreasing wall-time replay.
- [x] (2026-08-01) Repeated the complete local Release Contract for the seventh
  remediation. It passed with 1006 tests, four explicit platform-capability
  skips, 266 focused M6 tests with one symlink-capability skip, 25 M4/M6 public
  contract tests, and total/M1/M2/M3/M4/M5/M6 branch coverage of
  90/94/90/91/92/83/90 percent. Ruff, strict mypy over 137 files, both named
  validators, M0-through-M6 CLI smoke, evaluation reproduction,
  workspace/publication/dependency audits, `pip check`, and whitespace
  validation all passed without lowering a threshold.
- [x] (2026-08-02) Froze the exact seventh-remediated candidate at fingerprint
  `D8338BF14FA61877DE167CC10FCEF8E54F9D917030B3768D4261875843BF31F5`
  and completed the eighth fresh independent read-only review in
  `m6_eighth_independent_rereview`. It returned NO-GO with zero Critical, one
  High, zero Medium, and zero Low finding; the Worktree-observation live/replay
  authority gap was classified as materially recurrent.
- [x] (2026-08-02) Applied the Owner's loop-safety stop, obtained explicit
  authorization to continue, and implemented one shared live/replay
  Worktree-observation authority reducer. It binds the exact prior phase,
  assignment, causal request, latest requested/observed Worktree, and latest
  active Lease. Fully rehashed foreign-path, post-dispatch, and old-Lease
  recovery cases and the named validator pass.
- [x] (2026-08-02) Repeated the complete local Release Contract for the eighth
  remediation. It passed with 1009 tests, four explicit platform-capability
  skips, 269 focused M6 tests with one symlink-capability skip, 25 M4/M6 public
  contract tests, and total/M1/M2/M3/M4/M5/M6 branch coverage of
  90/94/90/91/92/83/90 percent. Ruff, strict mypy over 137 files, both named
  validators, M0-through-M6 CLI smoke, evaluation reproduction,
  workspace/publication/dependency audits, `pip check`, and whitespace
  validation all passed without lowering a threshold.
- [x] (2026-08-02) Froze the exact eighth-remediated candidate in the private
  eighth-remediation validation record without staging or remote access.
- [x] (2026-08-02) Completed the ninth fresh independent read-only review of
  fingerprint
  `CAF665556879CB922EC51FEFFB5B70CBD041CC367C523A748B1763908C6815E1`.
  It returned NO-GO with zero Critical, one High, zero Medium, and zero Low
  finding; the nonterminal Worktree-observation extra Lease-history output was
  classified as materially recurrent.
- [x] (2026-08-02) Applied the Owner's loop-safety stop, obtained explicit
  authorization to continue, and implemented centralized non-result Lease-
  history cause/output cardinality. A nonterminal Worktree observation permits
  zero Lease rows, terminal observation retains one exact release, and every
  Lease now proves heartbeat-plus-TTL expiry. The fully content-addressed extra
  current-Lease recovery case and named validator pass.
- [x] (2026-08-02) Repeated the complete local Release Contract for the ninth
  remediation. It passed with 1010 tests, four explicit platform-capability
  skips, 270 focused M6 tests with one symlink-capability skip, 25 M4/M6 public
  contract tests, and total/M1/M2/M3/M4/M5/M6 branch coverage of
  90/94/90/91/92/83/90 percent. Ruff, strict mypy over 137 files, both named
  validators, M0-through-M6 CLI smoke, evaluation reproduction,
  workspace/publication/dependency audits, `pip check`, and whitespace
  validation all passed without lowering a threshold.
- [x] (2026-08-02) Froze the exact ninth-remediated candidate in the private
  ninth-remediation validation record without staging or remote access.
- [ ] Perform a tenth fresh independent read-only review of that frozen
  candidate.
- [ ] Present a separate exact stage/commit proposal. Push and exact-SHA CI
  observation remain later separate approval boundaries.

## Surprises & Discoveries

- M2 `AgentOrchestrator` intentionally returns assignments and bounded prompts
  only. M6 therefore emits a typed dispatch intent and does not launch a host.
- Existing Agent Result 1.0 remains unchanged. A content-addressed
  `task_result` Mailbox Message supplies candidate, Context, attempt, lease,
  fence, idempotency, effect, and evidence identity around it.
- Rollback journaling plus fail-fast `BEGIN IMMEDIATE` serializes lease claims
  without persistent WAL sidecars.
- Focused tests found two adoption gaps during implementation: a heartbeat
  after expiry and an unexpected worktree observation were initially reported
  as accepted even though their transition was rejected. Both now reject
  before mailbox adoption.
- Corruption testing found that direct attempt/fence projection drift was not
  detected. Store validation now requires equal monotonic attempt/fence values
  within the task's exact maximum.
- The historical M4 platform-evidence test binds its evidence record to the
  current `.github/workflows/ci.yml` bytes. Adding the approved M6 CI steps
  therefore makes that historical assertion fail. Rewriting the M4 evidence
  SHA to the unexecuted M6 workflow would be false; preserving the old
  workflow as a separately named historical evidence artifact is the proposed
  minimal correction and requires a two-path scope amendment.
- The approved historical snapshot has the exact recorded M4 workflow SHA.
  Attempting to change `candidate.workflow_path` then revealed that the M4
  schema intentionally fixes the original execution path. The evidence record
  has therefore been restored unchanged. The remaining correct change is to
  make the M4 repository test verify the recorded historical bytes from the
  preserved snapshot while retaining the declared original path; this needs
  one additional test path and does not alter an existing schema or claim.
  The Owner approved that path as the second scope amendment.
- The focused M6 suite currently exceeds the approved 90 percent critical
  branch threshold without excluding production branches.
- The first independent review found that broad positive-path coverage did not
  prove nine trust-boundary properties. Remediation therefore added a negative
  runtime/schema parity corpus, deliberate mutable-projection corruption and
  immutable-evidence rebuilding, exact causal host-intent tests, durable
  scenario assertions, complete integer resource settlement, and deep
  immutability checks rather than weakening thresholds.
- The second independent review found that valid positive rows still did not
  prove stable approval identity, missing-row detection, completion-policy
  closure, or per-attempt budget ownership. The second remediation derives
  those authorities from durable Lease/event history and adds independent
  corruption and concurrency cases.
- The third independent review showed that a cryptographically intact evidence
  chain still needed cause-specific semantic replay, and that one global
  capability list or a simulator-only wait graph could not represent durable
  execution authority. The third remediation therefore derives event, wait,
  capability, approval, and Worktree authority from exact persisted identities
  and lifecycle state.
- The fourth independent review showed that partial cause dispatch still left
  terminal projection authority forgeable through a valid but unrelated cause,
  and that a durable typed wait graph must remain authoritative even when it
  reports a stall rather than a cycle. The fourth remediation makes the cause
  table total, validates scheduler egress from immutable evidence, and binds
  simulations and evaluation records to the production wait report.
- The fifth independent review showed that a total cause table still required
  exact payload-to-projection result semantics, complete scheduler-egress
  envelope and Worktree authority, and a reducer that reconstructs every
  Budget Ledger from immutable events. It also showed that an unconsumed
  approval is not reusable if budget failure releases its Lease. The fifth
  remediation closes those boundaries with rehashed corruption cases and a
  same-store delayed-admission test that preserves the exact Lease identity.
- Recording the required `retries=1` terminal-event delta changed the
  deterministic `host-timeout` evaluation digest. The original 12-path
  remediation boundary did not include the already-authorized evaluation
  result, so work stopped until the Owner approved that exact one-path
  amendment; no suite expectation or threshold changed.
- The first coverage pass crossed a one-second wall-clock boundary in an
  existing CLI lifecycle assertion and observed one additional legitimate
  `wall-time-observed` event. The exact test and the unchanged full coverage
  command both passed on the single classified retry; no test, product
  threshold, or unapproved path was changed.
- The sixth independent review showed that a closed cause vocabulary and
  internally consistent immutable chains still did not prove exact non-result
  policy, exact message adoption, or independently sourced budget causes. The
  sixth remediation now reconstructs those authorities from the graph, prior
  immutable state, event-adopted messages, verified Context bytes, and recorded
  time rather than accepting self-consistent rehashed claims.
- The seventh independent review found that the remaining three gaps were
  recurrent forms of the same Lease/Worktree, cancellation-parent, and
  wall-time authority classes. The Owner explicitly authorized one further
  cycle. Preserving M6-D4 required selecting a bounded TTL/heartbeat pair at
  initialization and making it immutable per store, rather than narrowing the
  approved range to one global pair.
- Final validation reproduced the legitimate optional `wall-time-observed`
  event when the exact CLI lifecycle crossed an integer-second boundary. The
  CLI test now validates both legal causal chains explicitly instead of using
  a timing-dependent fixed event count; the focused and complete suites then
  passed sequentially.
- The eighth independent review found that exact Worktree history cardinality
  did not by itself prove live observation admission. The observation reducer
  had to rederive the prior `not_dispatched` phase, task assignment, exact
  causal request, latest requested/observed Worktree, and latest active Lease
  from independent inputs rather than using the observation payload to derive
  its own expected Worktree object.
- The ninth independent review found the complementary output-side gap: a
  valid nonterminal Worktree observation correctly rederived all inputs but did
  not forbid an additional Lease-history output. Cause replay must prove both
  the complete inputs and the complete immutable output set; deriving the
  mutable current projection from the latest history row is not sufficient.

## Decision Log

- **M6-D1 — Owner-approved.** Seven schema 1.0 content-addressed artifacts use
  M5 canonical JSON and exact M2/M5 path, digest, candidate, and identity
  binding. Agent Result 1.0 is unchanged and wrapped by `task_result`.
- **M6-D2 — Owner-approved.** Preserve eight execution states; add exact task
  kinds and orthogonal dispatch/outcome fields; enforce deterministic DAG,
  role, review, integration, path, and external approval rules.
- **M6-D3 — Owner-approved.** SQLite uses application ID `0x53444151`,
  `user_version=1`, metadata schema `1.0`, rollback journal, synchronous FULL,
  foreign keys, trusted schema off, zero busy wait, `BEGIN IMMEDIATE`, fresh
  exclusive publication, no in-place migration, and fresh-output recovery.
- **M6-D4 — Owner-approved.** Lease TTL is 30–3600 seconds; heartbeat is 5
  seconds through half TTL capped at 300; fence starts at 1; attempts are 1–3;
  identity is stable per exact attempt; only unambiguous safe work retries;
  cancellation is cooperative; ambiguity is `blocked/unknown`. The seventh
  remediation preserves these ranges by selecting the pair at initialization,
  binding it to initialization evidence and recovery identity, and requiring
  every later tick, Lease, and egress payload to reproduce it exactly.
- **M6-D5 — Owner-approved.** Mailbox has ten exact variants, 64 KiB and
  64-reference bounds, sensitivity and provenance propagation, exact causal
  identity, complete hash-chained events, and bounded sequence exports.
- **M6-D6 — Owner-approved.** Exact integer budgets cover dispatch, retry,
  time, tool, Context, solver, and optional cost resources. Reservation and
  usage are transactional; waits and all ten simulator cases are named.
- **M6-D7 — Owner-approved, amended.** Add only the exact CLI, five ports,
  standard-library adapters, validator, 90 percent critical coverage, public
  synthetic evidence, one roadmap status line, and the original 53-path
  allowlist.
  Existing stable exports, dependencies, versions, and behavior stay intact.
  The Owner later approved two historical-evidence paths and the existing M4
  public-contract test, producing a 56-path authorization set so the M4
  executed workflow remains immutable and truthful after the M6 CI change.

- **Second-review remediation — Owner-approved.** Approval decisions name an
  already persisted provisional Lease and are rejected without an exact
  current identity; evidence and terminal predicates use a closed vocabulary
  and review targets must be complete; current Lease and Worktree sets derive
  from immutable history; budget settlement derives exact outstanding amounts
  per Lease attempt; schema/runtime parity retains the safe
  `max_concurrency <= max_agents` invariant and moves non-representable time
  comparisons to the authoritative scheduler boundary.
- **Third-review remediation — Owner-approved.** The exact 22-path boundary
  closes Lease expiry and dispatch causality, replays event semantics during
  validation/recovery, consumes fresh approvals immediately before dispatch,
  shares one typed durable wait projection across application/CLI/simulation,
  derives Worktree and per-host capability authority from latest immutable
  state, reparses generated artifacts, aligns representable path/text schema
  parity, and rejects unresolved linked/reparse path components.
- **Fourth-review remediation — Owner-approved, amended.** The exact 22-path
  proposal plus `tests/test_m6_budgets.py` makes event replay total across all
  24 causes, proves scheduler-authored egress against immutable Lease/message
  evidence, admits budgets before consuming approvals, preserves durable stall
  edges in simulation/evaluation, aligns safe-text and capability identity
  schema/runtime contracts, and treats Lease-expiry equality as non-cancellable.
- **Fifth-review remediation — Owner-approved, amended.** The exact 12-path
  proposal plus the existing M6 evaluation-result path binds accepted results
  to exact successful verification projections, proves scheduler egress from
  exact envelope, causal, Lease, and observed-Worktree evidence, derives every
  Budget Ledger snapshot and mutable total from cause-specific immutable event
  semantics, records retry consumption in the terminal event, and preserves a
  budget-blocked observed-worktree Lease and approval for exact later admission.
- **Sixth-review remediation - Owner-approved.** The exact 12-path proposal
  makes every authority-bearing non-result cause reproduce its one live-policy
  outcome and exact Lease/Worktree artifacts; requires one compatible primary
  adoption event for every immutable mailbox row; restricts parents,
  capabilities, and approvals to that adoption ledger; and rederives dispatch
  reservations, result ceilings, wall time, and dispatch blockers from
  independent immutable inputs.
- **Seventh-review remediation - Owner-approved after loop-safety stop.** Bind
  one bounded Lease policy to initialization and recovery, reconstruct whole
  provisional and active Lease authority, require exact cause-derived
  Worktree history cardinality, select cancellation parents only from the
  adopted current Lease and phase, validate mutations before commit, and
  derive every elapsed wall-time transition from the initialization-anchored
  event chain.
- **Eighth-review remediation - Owner-approved after loop-safety stop.** Use a
  single normalized Worktree-observation authority reducer in both live ingress
  and immutable replay, deriving exact phase, assignment, request, prior
  Worktree, current Lease, message envelope, and complete resulting Worktree
  history before accepting or recovering the observation.
- **Ninth-review remediation - Owner-approved after loop-safety stop.** Define
  one centralized non-result Lease-history cause/output classification, require
  zero rows for non-producing causes and the nonterminal Worktree observation,
  preserve the terminal observation's exact single release, and enforce the
  immutable heartbeat-plus-TTL expiry equation for every Lease.

## Context and Orientation

The layers are:

- `src/sdaqf/domain/scheduler.py`: frozen values and enums, no I/O;
- `src/sdaqf/ports/scheduler.py`: clock, store, artifact, agent-host, and
  worktree-host protocols;
- `src/sdaqf/application/scheduler_contracts.py`: strict envelopes, identity,
  Task Graph and message validation;
- `src/sdaqf/application/scheduler.py`: root-confined public services and wait
  reports;
- `src/sdaqf/application/scheduler_recovery.py`: recovery use case;
- `src/sdaqf/application/scheduler_simulation.py`: fixed-clock named cases;
- `src/sdaqf/adapters/scheduler.py`: SQLite, clock, exclusive publisher, and
  explicitly unsupported real-host adapters;
- `src/sdaqf/cli.py`: additive `agents` subcommands;
- `schemas/`, `examples/m6-scheduler/`, and `evals/`: portable public
  contracts and synthetic evidence;
- `.sdaqf/`: ignored runtime state, never a fixture or publication input.

Reuse existing M2 registry/request/worktree/result loaders, M5 canonical JSON
and Snapshot loaders, CandidateIdentity, reviewer separation, approval
patterns, and immutable publication. Do not create a second Context or Agent
Result contract.

## Acceptance Criteria

- All seven artifacts reject malformed, duplicate-key, non-finite, oversized,
  unsafe-path, unsupported-version, unknown-field, and identity-mismatched
  input with runtime/schema parity.
- Task Graph rejects cycles, missing nodes, unstable ordering, unauthorized
  roles/tools/worktrees, path overlap, reviewer/integrator conflict, and any
  M2/M5 candidate, Snapshot, sensitivity, or digest mismatch.
- SQLite initialization is exclusive, settings and thirteen-table shape are
  exact, integrity/event/projection validation fails closed, and concurrent
  claimers cannot own one task.
- Fence, heartbeat, expiry, retry, duplicate, conflict, stale/foreign/late
  result, approval consumption, cancellation, and ambiguity match the approved
  semantics.
- Budgets never use floats or negative/overflowed totals and block exact
  exhaustion, missing capability, or unavailable cost without averaging.
- Worktree creation/integration remains a host intent/observation. Ambiguous
  state is preserved and never deleted automatically; terminal lifecycle rows
  release current authority and allow only legitimate sequential reuse.
- Typed wait edges cover dependencies, review targets, Leases, worktrees,
  approvals, capabilities, and budgets, and production deadlock reports are
  deterministic and non-speculative.
- Recovery produces only a fresh validated evidence-equivalent store or no
  output.
- Ten scenarios reproduce their exact named result and deterministic digest
  using the real SQLite state machine offline.
- Exact CLI help, JSON, exit codes, roots, collisions, bounds, and no-partial
  output preserve all existing commands.
- Full pytest, Ruff, strict mypy, total and M1–M6 critical coverage, CLI smoke,
  named validators, evaluation, repository/workspace/dependency audits,
  `pip check`, and whitespace checks pass without weakening.
- Independent read-only review later returns GO with no unresolved Critical,
  High, or Medium finding on the exact frozen candidate.

## Implementation Plan

### Checkpoint 1 — contracts, identity, and ports

Create the frozen domain and five ports. Implement canonical envelopes and all
seven runtime loaders/schemas. Revalidate every referenced M2/M5 artifact and
cross-contract role, candidate, Context, sensitivity, review, integration,
path, and budget invariant. Add public examples and negative parity tests.

### Checkpoint 2 — transactional state machine

Create schema 1 only through an exclusive fresh database. In bounded
`BEGIN IMMEDIATE` transactions, adopt current-fence messages, refresh
dependencies/capabilities, reserve budgets, consume exact approvals, acquire
or release leases, append chained events and snapshots, and dispatch ready
intents. Validate complete store identity and projection on every open.

### Checkpoint 3 — recovery, CLI, and simulation

Add immutable-evidence-driven fresh-output SQLite projection rebuilding,
deterministic exports and mailbox inspection, exact nested CLI signatures,
fixed-clock real-store simulation, ten named evaluation cases, the named
validator, and M0-through-M6 CLI smoke.

### Checkpoint 4 — release validation and freeze

Update only the approved English documents and CI job. Run:

```text
python -m pytest
python -m ruff check src tests scripts
python -m mypy src tests scripts
python -m coverage run -m pytest
python -m coverage report --fail-under=80
python -m coverage report --include="src/sdaqf/domain/models.py,src/sdaqf/domain/requirements.py,src/sdaqf/application/gates.py,src/sdaqf/application/approvals.py,src/sdaqf/application/baselines.py,src/sdaqf/application/comparison.py,src/sdaqf/application/planning.py,src/sdaqf/application/requirements.py,src/sdaqf/application/requirements_gate.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/orchestration.py,src/sdaqf/domain/tooling.py,src/sdaqf/adapters/process.py,src/sdaqf/application/orchestration.py,src/sdaqf/application/skills.py,src/sdaqf/application/tooling.py,src/sdaqf/application/checkpoints.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/quality.py,src/sdaqf/application/contracts.py,src/sdaqf/application/evidence.py,src/sdaqf/application/quality_gates.py,src/sdaqf/application/ui_validation.py,src/sdaqf/application/release_qa.py,src/sdaqf/application/handoffs.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/evaluation.py,src/sdaqf/domain/migrations.py,src/sdaqf/application/evaluation.py,src/sdaqf/application/migrations.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/context.py,src/sdaqf/ports/context.py,src/sdaqf/adapters/context.py,src/sdaqf/application/context_contracts.py,src/sdaqf/application/context_index.py,src/sdaqf/application/context_selection.py,src/sdaqf/application/context_compaction.py,src/sdaqf/application/context_quality.py" --fail-under=80
python -m coverage report --include="src/sdaqf/domain/scheduler.py,src/sdaqf/ports/scheduler.py,src/sdaqf/adapters/scheduler.py,src/sdaqf/application/scheduler_contracts.py,src/sdaqf/application/scheduler.py,src/sdaqf/application/scheduler_recovery.py,src/sdaqf/application/scheduler_simulation.py" --fail-under=90
python scripts/run_cli_smoke.py
python scripts/validate_m5_context.py
python scripts/validate_m6_scheduler.py
python -m sdaqf eval validate evals/comparison-suite.json --result evals/results/public-beta-comparison.json --json
python scripts/check_workspace_boundary.py --repo . --expected-origin-url https://github.com/guriguri215-lang/spec-driven-agent-framework.git
python scripts/audit_repository.py --root . --workspace-parent ..
python scripts/audit_dependencies.py --root .
python -m pip check
git diff --check
```

Freeze only after every command passes. Record exact paths, hashes, tests,
coverage, scenarios, platform limits, and Git worktree/index state privately.
Do not stage or contact a remote.

## Exact Tracked Scope

The amended approved scope is exactly one current workflow, one historical M4
workflow snapshot, its unchanged M4 evidence record, `README.md`,
`CHANGELOG.md`, seven documentation paths, two evaluation paths, seven
examples, seven schemas, two scripts, eleven source/module paths, and fifteen
test/helper paths: 56 authorized paths in total, including the existing M4
public-contract test approved by the second scope amendment. The unchanged M4
evidence record means the frozen candidate is expected to contain 55 actual
changed or untracked paths. No specification, existing schema, dependency,
package metadata, stable top-level export, or release metadata may change.

## Failure, Retry, and Recovery

Classify a development-command failure before one justified retry. Never lower
a test or threshold. Preserve an indeterminate database, publication, worktree,
or external effect as a named blocker. Remove only exact owned temporary state
after validating its identity. Product recovery always targets a fresh output.

## Owner Approval Gates

Local implementation inside the amended 56-path authorization set is approved
through the ninth remediation and Checkpoint 4. Nonfatal review/fix/re-review
cycles may continue without another pause, but a materially recurrent finding
requires the Owner's loop-safety confirmation. Stop separately for remediation
outside the scope, stage/commit, push/remote CI observation, PR/merge/tag/
release, settings, credentials, charges, destructive cleanup, history rewrite,
or any architecture/scope/dependency/version change.

## Outcomes & Retrospective

The first implementation candidate completed the local Release Contract with
850 passing tests and its first independent review returned NO-GO with zero
Critical, seven High, and two Medium findings. The first remediation passed
865 tests; the second review returned NO-GO with zero Critical, four High, two
Medium, and one Low finding. The second remediation passed 874 tests; the third
review returned NO-GO with zero Critical, eight High, two Medium, and zero Low
findings. All third-review findings are now remediated inside the approved exact
22-path subset of the 56-path candidate. The fresh Release Contract passed 921
tests with four explicit platform-capability skips and 157 focused M6 tests
with one symlink-capability skip; total/M1/M2/M3/M4/M5/M6 branch coverage was
90/94/90/91/92/83/91 percent. Ruff, strict mypy over 137 files, both named
validators, M0-through-M6 CLI smoke, evaluation reproduction,
workspace/publication/dependency audits, `pip check`, and whitespace validation
passed. The fourth independent review then returned NO-GO with zero Critical,
one High, four Medium, and zero Low findings. All five findings are implemented
inside the approved exact 22-path proposal plus its one-path test amendment.
The complete Release Contract passed 955 tests with four explicit platform-
capability skips and 215 focused M6 tests with one symlink-capability skip;
total/M1/M2/M3/M4/M5/M6 branch coverage was 90/94/90/91/92/83/90 percent.
Ruff, strict mypy over 137 files, both named validators, M0-through-M6 CLI
smoke, evaluation reproduction, workspace/publication/dependency audits,
`pip check`, and whitespace validation passed. The fifth independent review
then returned NO-GO with zero Critical, three High, one Medium, and zero Low
findings. All four findings are implemented inside the approved exact 12-path
proposal plus its one-path evaluation-result amendment. The complete Release
Contract passed 980 tests with four explicit platform-capability skips and 240
focused M6 tests with one symlink-capability skip; total/M1/M2/M3/M4/M5/M6
branch coverage was 90/94/90/91/92/83/90 percent. Ruff, strict mypy over 137
files, both named validators, M0-through-M6 CLI smoke, evaluation reproduction,
workspace/publication/dependency audits, `pip check`, and whitespace validation
passed. The sixth independent review then returned NO-GO with zero Critical,
three High, zero Medium, and zero Low findings. All three findings are
implemented inside the approved exact 12-path proposal. The complete Release
Contract passed 990 tests with four explicit platform-capability skips and 250
focused M6 tests with one symlink-capability skip;
total/M1/M2/M3/M4/M5/M6 branch coverage was 90/94/90/91/92/83/90 percent.
Ruff, strict mypy over 137 files, both named validators, M0-through-M6 CLI
smoke, evaluation reproduction, workspace/publication/dependency audits,
`pip check`, and whitespace validation passed. The sixth-remediation
fingerprint freeze is complete and the seventh independent review remains
separately Owner-gated. No network, remote, stage, commit, or Git host effect
has been performed by the remediation.

The seventh-remediated candidate passed its complete Release Contract and was
frozen at
`D8338BF14FA61877DE167CC10FCEF8E54F9D917030B3768D4261875843BF31F5`.
The eighth independent review then returned NO-GO with zero Critical, one
recurrent High, zero Medium, and zero Low finding. After the required
loop-safety confirmation, the eighth remediation introduced one shared
live/replay Worktree-observation authority reducer and fully rehashed negative
proofs for foreign path, post-dispatch phase, and old/released Lease authority.
The complete Release Contract now passes 1009 tests with four explicit
platform-capability skips and 269 focused M6 tests with one symlink-capability
skip; total/M1/M2/M3/M4/M5/M6 branch coverage is
90/94/90/91/92/83/90 percent. Ruff, strict mypy over 137 files, both named
validators, M0-through-M6 CLI smoke, evaluation reproduction,
workspace/publication/dependency audits, `pip check`, and whitespace validation
all pass. The eighth-remediation candidate was frozen at
`CAF665556879CB922EC51FEFFB5B70CBD041CC367C523A748B1763908C6815E1`;
the ninth independent review then returned NO-GO with zero Critical, one
recurrent High, zero Medium, and zero Low finding. After the required
loop-safety confirmation, centralized cause/output cardinality, the
nonterminal zero-row rule, exact heartbeat-plus-TTL expiry, the rehashed
extra-current-Lease regression, and the named validator are implemented. The
complete Release Contract now passes 1010 tests with four explicit platform-
capability skips and 270 focused M6 tests with one symlink-capability skip;
total/M1/M2/M3/M4/M5/M6 branch coverage is 90/94/90/91/92/83/90 percent.
Ruff, strict mypy over 137 files, both named validators, M0-through-M6 CLI
smoke, evaluation reproduction, workspace/publication/dependency audits,
`pip check`, and whitespace validation all pass. Exact ninth-remediation
freeze is complete and the tenth fresh independent review remains pending; no
network, remote, stage, commit, or Git-host effect has been performed.
