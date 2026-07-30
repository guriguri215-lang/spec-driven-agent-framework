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
