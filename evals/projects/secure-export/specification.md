# Approval-Bound Secure Export

## Functional requirements

- `FR-EXP-001`: The command must export only the records selected by stable identifier.
- `FR-EXP-002`: The command must require an exact Owner approval before writing an export.
- `FR-EXP-003`: The command must reject an export target outside the owned project state directory.
- `FR-EXP-004`: The command must record the approval identifier and content digest for every successful export.

## Non-functional requirements

- `NFR-EXP-001`: Identical selected records and options must produce identical export bytes.

## Constraints

- `C-EXP-001`: Export content must not contain credentials or authentication material.
- `C-EXP-002`: The export workflow must operate without network transfer.

## Non-goals

- `NG-EXP-001`: The project must not upload, email, or publish an export.
