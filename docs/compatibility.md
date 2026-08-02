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

M6 adds seven independent scheduler schema `1.0` contracts. They are additive
and do not reinterpret an Agent Result, M2 registry/request/worktree record,
M5 Context artifact, Gate, approval, checkpoint, or handoff. Task Graphs are
compatible only with the exact referenced M2/M5 bytes and candidate identity.
Mailbox and result adoption additionally requires the exact graph, task,
Context Snapshot, attempt, lease, fence, idempotency key, sensitivity, and
causal parent identities.

The SQLite database is a local implementation detail, not a portable public
schema. Compatibility requires application ID `0x53444151`, `user_version=1`,
and metadata schema `1.0`. Unknown versions and altered table shape fail
closed. There is no in-place or automatic database migration.

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

There is no pre-M6 scheduler artifact or database to migrate. Adoption creates
a fresh database from a validated Task Graph. Recovery also writes only a
fresh output after exact source-schema and immutable-evidence validation,
rebuilds every mutable projection, and requires evidence equivalence before
exclusive publication. A future scheduler schema or SQLite version must
preserve the old source and use a separately documented, explicitly approved
conversion.

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
