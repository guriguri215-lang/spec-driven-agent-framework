# V1 Compatibility and Migration

## Public API

SDAQF `1.0.0rc1` is a prerelease of the target V1 public API line `1.0.0`.
The supported public surface consists of:

- documented `sdaqf` CLI commands;
- documented exit-code and JSON output contracts;
- JSON schemas published in `schemas/`; and
- names exported through `sdaqf.__all__`.

Modules and names outside that surface are implementation details and may
change without deprecation. The release candidate is not stable or
production-ready, and compatibility is not guaranteed until a separately
approved final `1.0.0` candidate is released.

## Python and platform compatibility

Python 3.12 and 3.13 on Windows and Linux are the required verification matrix.
macOS is optional and remains `NOT_VERIFIED` until an exact-candidate run
provides evidence.

The runtime dependency set is empty. The core remains offline-first and does
not require a network service, OpenAI API, Agents SDK, hosted deployment, or
management UI.

## Schema compatibility

Published schema versions remain immutable. Consumers must select and validate
the exact schema version they use.

`release-candidate.schema.json` remains historical schema 1.0 and represents
only the explicit `not-selected` project-license state.
`release-candidate-v1.1.schema.json` adds the exact selected Apache-2.0
license contract. The new schema does not silently reinterpret schema 1.0.

The public-release-candidate schema records offline local readiness only. A
successful result is `LOCAL_READY`; it is never proof that Gate G5 ran or that
publication occurred.

M5 adds eight independent Context schema `1.0` contracts. They do not change or
reinterpret any existing schema. Context consumers must validate the exact
`artifact_type`, full content identity, and schema version. A Graph, Query,
Selection, Snapshot, or Compaction from another candidate or identity chain is
not compatible even when its JSON shape validates.

Within the initial M5 schema `1.0`, Graph exclusions, the Selection's embedded
Query and derived sensitivity, Snapshot exclusions, and downstream
CandidateIdentity/sensitivity fields are identity-bearing. Compaction extracts
also retain source identity, authority, sensitivity, and exact contradiction
IDs. A consumer must not reconstruct or omit them. Snapshot producers additionally rerun the embedded
Query and require exact Selection equality; structural schema validity alone
does not establish semantic compatibility. Production Compaction requires
explicit roots and reauthenticates a persisted Snapshot before use.

M6 originally added seven independent scheduler schema `1.0` contracts. M8
remediation adds three independent schema `1.0` contracts for Workflow Epoch
Event, Scheduler Store Migration Approval, and Scheduler Store Migration
Result. They are additive
and do not reinterpret an Agent Result, M2 registry/request/worktree record,
M5 Context artifact, Gate, approval, checkpoint, or handoff. Task Graphs are
compatible only with the exact referenced M2/M5 bytes and candidate identity.
Mailbox and result adoption additionally requires the exact graph, task,
Context Snapshot, attempt, lease, fence, idempotency key, sensitivity, and
causal parent identities.

The SQLite database is a local implementation detail, not a portable public
schema. Both supported versions use application ID `0x53444151`. M6-only v1
requires `user_version=1` and metadata schema `1.0`. M8 runtime requires v2,
`user_version=2`, metadata schema `2.0`, the append-only workflow epoch chain,
and its replay-checked current-head projection. Unknown versions and altered
table shape fail closed. V1 remains readable and operable for M6-only use;
there is no in-place or automatic database migration.

M7 adds four independent Solver Registry, Request, Result, and Verification
schema `1.0` contracts. They are additive and do not reinterpret M2 Tool
Registry or approval records, M5 Context artifacts, M6 Task Graphs, Leases,
messages, budgets, events, or Agent Results. Compatibility requires the exact
artifact IDs and referenced bytes, operational contract ID, candidate,
Context, graph, task, adapter, resource policy, and Lease reservation. Shape
compatibility alone is insufficient. Scheduler adoption additionally requires
the current Task Graph identity, task ID, and unique solver capability token;
evidence from another operational contract is incompatible. Solve and
Verification step limits are independent and cannot be treated as pooled
capacity. The exact referenced raw Result byte length must remain within the
Request `max_result_bytes` policy during live adoption, history validation, and
recovery; canonical typed content with an oversized on-disk representation is
incompatible. A `rejected` Solver Verification is incompatible with every M6
Task Result outcome; a failed task remains compatible with truthful
`inconclusive` or verified-but-claim-unsatisfied evidence.

The initial M7 contract uses exact finite integers and exact-zero tolerance.
The two problem kinds, three profiles, five constraints, ten statuses, proof
dispositions, verification outcomes, numeric-domain declaration, and complete
reference-adapter D2 limits are closed. M7 Lease host IDs use the exact M6
`HST-` grammar, and solver task IDs use the exact M6 `TSK-` grammar, including
their maximum lengths. Solver sensitivity labels are exactly the M5 labels;
`internal`, `confidential`, and `restricted` are not M7 compatibility aliases.
Solver references also reuse the exact M6 portable-path exclusions, and
embedded Lease expiry timestamps use the exact M6 RFC 3339 UTC `Z` grammar;
Windows reserved paths, trailing-dot paths, and `+00:00` timestamp aliases are
not compatible schema `1.0` representations.
Adding an approximate numeric theory, new status, executable external adapter,
or different proof meaning requires a new contract version; it must not be
silently accepted as schema `1.0`.

M8 adds five independent Development Intent, Integrated Plan, Workflow State,
Workflow Event, and Workflow Outcome schema `1.0` contracts. They are additive
and do not reinterpret M1 Requirement Baselines, M2 Registries, M3 evidence,
reviews, Gates or handoffs, M5 Context artifacts, M6 Task Graphs, SQLite state,
Leases, budgets or events, or M7 solver artifacts. Compatibility requires the
exact referenced bytes, full native artifact IDs, CandidateIdentity, sensitivity,
Task Graph, scheduler event head, and predecessor lineage; matching shape alone
is insufficient.

The M8 reason, status, event-cause, effect-disposition, completion-profile,
Outcome-disposition, and measurement vocabularies are closed in schema `1.0`.
Adding a field, status, reason, authority, automatic retry, new mutable store,
executable hosted adapter, or different completion meaning requires a new
version. It cannot silently extend `1.0` or reuse existing approvals.

M8 preserves every pre-M8 CLI meaning and uses only the `workflow` namespace.
The unpublished local M8 surface had no external consumer or artifact, so the
Owner-approved remediation corrects it within the pre-release 1.0 line: Plan,
Explain, and Simulate require `--scheduler-state`; Supersede remains public;
Outcome requires its closure `--output-state`. No external 1.1 conversion or
headless-artifact grandfathering applies. M8 does not widen stable top-level
`sdaqf.__all__` exports or add a runtime dependency. The internal workflow
modules remain prerelease implementation details until a separately approved
stable Python API exists.

## Migration

No migration is required from the M4 Public Beta CLI behavior. Existing
versioned JSON remains subject to its original schema. A consumer that adopts
the selected-license release-candidate contract must:

1. retain its historical schema 1.0 records unchanged;
2. create a new schema 1.1 record;
3. bind the exact `LICENSE` and `NOTICE` paths and SHA-256 values; and
4. rerun the applicable local Gates against the new candidate identity.

Downgrade, multi-hop, in-place, and automatic publication migrations remain
unsupported.

There is no pre-M5 Context schema to migrate. Adoption creates new immutable
artifacts through the additive `context` namespace. Existing V1 commands and
JSON remain unchanged. Context artifacts are never upgraded in place; a future
schema version must preserve the historical file and produce a separately
identified artifact.

Missing source sensitivity has one conservative compatibility rule:
canonicalize it to `owner-private` before source identity checking. No other
missing Context field receives an inferred lower-trust value.

The stable top-level `sdaqf.__all__` remains unchanged. Context domain and
application modules are implementation details until a separately approved
stable Python API contract is published.

M6 v1 adoption creates a fresh database from a validated Task Graph and remains
the default for M6-only use. A caller may instead initialize a fresh v2
workflow-authority store. The one supported database migration is explicit
copy-on-write v1 to v2: it requires an exact time-bounded Owner approval,
binds the canonical repository `root_sha256`, consumes that approval once in
the shared M4 migration consumption store,
preserves the validated v1 source, exclusively publishes a fresh v2 output,
and starts an empty workflow epoch chain. In-place, implicit, opportunistic,
recovery-disguised, and v2-to-v1 migration are prohibited. After a v2 workflow
epoch exists, downgrade would erase authority and is prohibited. Recovery
writes only a fresh same-version output after exact schema, immutable evidence,
epoch-chain, receipt, and projection replay.
Supplying a v1 store to an M8 command fails before output with the deterministic
`migration-required` result; no existing headless M8 file is grandfathered.

There is no pre-M7 Solver artifact to migrate. Adoption creates new immutable
artifacts through the additive `solver` namespace. Existing V1, M2, M5, and M6
records remain unchanged. A future Solver version must preserve schema `1.0`
files and evidence, produce separately identified artifacts, document proof
and adoption compatibility, and use a separately approved explicit conversion
if conversion is possible. Optional external-adapter Registry data never
migrates into process authority or reusable approval.

There is no compatible headless predecessor M8 workflow artifact to migrate.
Adoption creates new content-addressed records through the additive `workflow`
namespace and an authenticated M6 v2 epoch. Workflow State does not migrate or
replace the M6 SQLite database. Resume preserves an exact Plan epoch; a changed
candidate or native reference requires a new Plan and fully rederived,
predecessor-linked terminal Outcome rather than an in-place update. Recovery
writes fresh Event and State artifacts only for a nonterminal epoch; a
terminal-reserved epoch permits only exact pending finalization. A future M8
conversion must preserve all source artifacts and ambiguity, document native
semantic compatibility, and require separate approval.

Successor `workflow explain`, `workflow simulate`, `workflow run`,
`workflow resume`, `workflow status`, and `workflow recover` add the same
optional `--predecessor-scheduler-state` accepted by planning. It is required
exactly for successor lineage and omitted for genesis, preserving all existing
genesis CLI and Python call shapes. Python `finalize_observation` accepts the
same optional authority for successor terminal closure. Terminal retries preserve the
reservation timestamp and accept only exact receipt-bound existing artifacts;
these are semantic tightening rules within schema `1.0`, not artifact migration.

The latest independent successor lifecycle compatibility review returned GO for
this exact boundary, maintained every F1-through-F11 ACCEPT result, and left zero
unresolved findings within its scope. It supersedes the earlier M8 overall
NO-GO for the reviewed M8 state only. At review time, the M8 surface remained
local, Experimental, and unreleased, and the compatibility disposition did not
establish release GO, production readiness, commit, push, or exact-SHA remote
CI. That reviewed state was later merged to `main`, whose exact-triggering-SHA
Actions run `31497539609` passed the required matrix.

## Current compatibility dispositions

The historical 2026-08-10 final independent M5 compatibility re-review remains
recorded NO-GO. Snapshot publication now revalidates the CandidateIdentity from the
validated Snapshot being serialized after all estimator work, and Selection
ranking shares one authoritative graph distance with its published rank. The
High blocking and Medium non-blocking findings are remediated. The latest M5
disposition is GO for the reviewed repository state; this updates current
status without deleting or rewriting the historical NO-GO record.

The historical, separate 2026-08-10 final independent M6 compatibility review
remains recorded NO-GO. The public Workflow Epoch Event schema now rejects receipt
type/ID-prefix mismatches and one-sided artifact-head ID/path pairs exactly as
runtime parsing does. That Medium blocking finding is remediated. A later pre-
publication review stopped with one separate Medium finding because eight
pattern-constrained identifiers and digests in three additive M6 schemas did not
explicitly require strings. The five-file remediation makes those fields
string-only and adds 32-case public-test and named-validator parity matrices.
Runtime parsing, SQLite replay meanings, schema versions, samples, and
evaluation fixtures are unchanged. Three fresh independent reviewers ACCEPT
with zero unresolved Critical, High, or Medium finding. The latest M6
disposition is GO for the reviewed state merged by pull request #4; both the
historical NO-GO and the later pre-publication stop remain recorded.

The current dispositions are independent: M5 GO, M6 GO, M7 GO, and M8
successor lifecycle GO. The M5 and M6 findings do not reopen or supersede the
recorded M7 or M8 reviews. All four milestones remain Experimental and
unreleased. These compatibility dispositions do not establish release GO or
production readiness. Pull request #4 exact-head Actions run `31558960113`
passed before merge, and the resulting `main` exact-triggering-SHA run
`31563987706` passed the same Windows/Linux and Python 3.12/3.13 matrix.
Version, tag, release, and deployment require separate authorization.

## Deprecation

No target V1 public API is deprecated in `1.0.0rc1`. A future deprecation must
be documented in the changelog and compatibility guide, preserve a safe
migration path, and receive the applicable approval before a breaking change.

## Rollback

Before publication, discard only the exact unstaged V1-owned changes or
ignored `.sdaqf/v1/` evidence after inspecting the target. Do not use broad
cleanup, history rewrite, or hard reset.

After publication, never delete or move a published tag automatically.
Correct a defect with a new version and new exact evidence.
