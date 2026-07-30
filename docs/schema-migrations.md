# Schema Migration Policy

## Compatibility policy

M4 preserves every M1, M2, and M3 schema and strict-loader version. Runtime
loaders continue to adopt Agent Registry 2.0 and Tool Registry 2.0 only. Legacy
1.0 records are accepted only by the explicit migration command; they are
never silently upgraded during normal validation or execution.

Supported migration routes:

| Contract | Source | Target | Runtime adoption |
|---|---:|---:|---|
| Agent Registry | 1.0 | 2.0 | migrated output must pass the existing 2.0 loader |
| Tool Registry | 1.0 | 2.0 | migrated output must pass the existing 2.0 loader |

Downgrade, multi-hop, in-place, and other contract migrations are unsupported.

## Command

```text
python -m sdaqf schema migrate --contract agent-registry --from-version 1.0 --to-version 2.0 INPUT.json --output NEW.json --approval .sdaqf/migration-approval.json --tool-registry CURRENT-TOOLS.json --json
python -m sdaqf schema migrate --contract tool-registry --from-version 1.0 --to-version 2.0 INPUT.json --output NEW.json --approval .sdaqf/migration-approval.json --json
```

All source, approval, companion Tool Registry, and output paths must use a
lowercase `.json` suffix. This portable boundary is identical in runtime
validation and the public approval/result schemas.

The input and output must be distinct regular files below the current
repository root. The output parent must already exist. The command refuses an
existing output and never overwrites the source. Agent Registry migration also
requires a current strict Tool Registry and rejects every missing tool
reference before publication.

Migration is an explicit Owner-approval boundary. The required versioned
approval record uses schema version 1.1 and names the exact contract, a
non-disclosing SHA-256 identity for the resolved local repository root, the
normalized source path and initial source SHA-256, normalized output path,
source and target versions, approval and expiry times, reversible
exclusive-output conditions, and `Owner` provenance. Agent migration also
binds the normalized companion Tool Registry path and its immutable byte
snapshot SHA-256; Tool Registry migration requires both companion fields to be
null. The approval must be current and match the operation exactly. Approval
schema 1.0 is intentionally rejected because it did not bind the local root or
source path; it must not be migrated or reused as authorization. Migration
result schema 1.1 records the same root and source identities. Historical 1.0
results remain records only and are never adopted as new approval. Keep real
approval records in ignored local state such as `.sdaqf/`; do not publish them.
A technical sandbox approval cannot replace this Owner record.

Every approval is `single_use`. Immediately before exclusive publication, the
service atomically claims its approval ID in
`.sdaqf/migration-approval-consumption.json`. A prior claim, corrupt or linked
state, an existing lock, or a claim-persistence failure blocks publication. A
claim remains consumed when a later exclusive link fails, including a
concurrent-output race, so any retry requires a new exact Owner approval.

## Conservative defaults

Agent Registry 1.0 does not express the M2 selection and write-safety fields.
Migration derives a portable role slug and preserves the legacy display name,
responsibilities, inputs, outputs, tools, and prohibited actions. It inserts:

- `problem_types: ["discovery"]`;
- `scales: ["small"]`;
- `max_risk: "low"`;
- `parallelism: ["sequential"]`;
- `can_write: false`;
- `independent_reviewer: false`.

These defaults reduce capability. They do not infer write access, parallel
work, reviewer independence, or broader risk.

Tool Registry 1.0 migration supports only known exact safe version probes for
Git, Python, and Z3. It preserves the legacy name, capability, platforms,
normal scope, risk, and approval classifications while inserting:

- the known one-capture numeric version pattern;
- `minimum_version: null`;
- `protected_paths: [".git"]`;
- offline network policy;
- `optional: false`;
- `max_attempts: 1`.

Legacy `sandbox_status` is observation data and is not converted into policy.
Network-enabled legacy tools and unknown commands require manual redesign and
fail migration.

## Validation and publication

The migration loader parses the initial bounded source-byte snapshot and
rejects duplicate JSON keys, unsupported versions,
oversized or linked input, traversal, unsafe or unknown commands, ambiguous
network policy, empty required fields, identifier collisions, missing Agent
tool references, and any invalid current contract. It serializes
deterministically to a temporary regular file, validates that file with the
existing 2.0 loader, confirms the source identity again immediately before
publication, rechecks the companion Tool Registry when applicable, atomically
claims a freshly current approval, and creates the named output exclusively
only after those checks succeed. It then repeats the source and companion
identity checks while retaining the unique temporary hard link.

The result records approval, local-root, source-path, source-content,
companion Tool Registry when applicable, and output identities, inserted
defaults, warnings, source preservation, the new path, and exact rollback
guidance.

## Failure and rollback

Validation, pre-publication source-identity, approval-consumption, or
source-read failure occurs before the named output is published. If a
post-link identity check fails, portable path-based deletion cannot prove that
the name was not replaced after its last identity check. The command therefore
returns the explicit `publication is indeterminate` failure, prohibits use of
the named output, consumes the approval, and never deletes that path. The
Owner must inspect its current type, identity, and digest before any explicit
cleanup or retry under a new approval. An output created concurrently by
another actor causes exclusive publication to fail and is never removed by
the migration service.
The command never performs a partial in-place update. After success, rollback
means removing only the newly created output and continuing to retain the
unchanged legacy source. Removal is an Owner-controlled filesystem action; the
migration command does not perform it automatically.
This successful-result guidance does not apply to an indeterminate
publication, whose current name may belong to another actor.

Every migrated record requires review before it becomes a project input,
especially the conservative role and tool defaults. A migration does not grant
Owner approval, technical sandbox approval, network access, publication, or a
new security boundary.
