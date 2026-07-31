# Contributing

This project is in the `1.0.0rc1` release-candidate phase and is not open for
external pull requests. The Owner-approved A7 visibility-change command was
accepted with exit code `0` and no output, but no independent post-A7 remote
read has confirmed current public availability. Bug and documentation issues
are handled through GitHub Issues on a best-effort basis only after public
availability is independently confirmed.

For approved local work:

1. Read `AGENTS.md`, `docs/contributor-guide.md`, and the active execution
   plan.
2. Keep changes within the approved requirement scope.
3. Use an isolated Python 3.12 or 3.13 environment and the exact development
   lock.
4. Add positive, negative, boundary, and regression tests with implementation
   changes.
5. Update versioned schemas, migration policy, evaluation fixtures, CLI help,
   and public documentation for contract changes.
6. Run every command in `docs/release-contract.md`.
7. Review the complete diff and publication audit before requesting approval
   to stage or commit.
8. Use English for every tracked artifact and commit message.

The project is licensed under Apache License 2.0. Do not add production
dependencies, change project-license material, publish a branch, or change
security boundaries without explicit Owner approval.

Schema changes follow `docs/schema-migrations.md`. Skill, template, or prompt
evaluation changes follow `docs/evaluation.md` and require parity-bound before
and after records. Executing a migration requires a separate exact
time-bounded Owner approval record even when the migration code is already
approved. Gate G4 remains local and does not authorize Gate G5 publication.
Local publication readiness may return `LOCAL_READY`; it also does not
authorize Gate G5. A project Code of Conduct is deferred until the Owner opens
external contributions.
