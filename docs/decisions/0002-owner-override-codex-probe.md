# ADR 0002: Nested Codex Probe Is Nonblocking

- Status: Accepted by Owner
- Date: 2026-07-27

## Context

A previous M0 attempt stopped before creating the repository because a nested
external `codex --version` process was denied both normally and after a narrow
technical sandbox approval.

## Decision

The Owner clarified that the nested external CLI is not required by
`AC-M0-016` and does not establish the health of the already active session.

- Current session: `CURRENT_SESSION_ACTIVE`.
- Goal mode: observed in use.
- Subagents: observed in use.
- External Codex CLI previous result:
  `PERMISSION_DENIED_NONBLOCKING`.
- External Codex CLI current probe: `NOT_CHECKED_NONBLOCKING`.
- Codex client version: `NOT VERIFIED`.

M0 must not execute `codex --version` again. Python, Git, tests, lint, type
checking, coverage, CLI smoke tests, safety boundaries, and publication gates
remain mandatory.

## Consequences

The previous blocked record remains audit history. The override changes only
the classification of the nested CLI probe; it does not weaken any other stop
condition or approval boundary.
