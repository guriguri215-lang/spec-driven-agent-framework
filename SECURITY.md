# Security Policy

## Supported status

M4 is a public-beta hardening milestone, not a production release.

## Reporting

Do not disclose suspected vulnerabilities in a public issue. Until a private
security contact is selected by the Owner, keep the report local and request a
private reporting channel.

## Security boundaries

- The runtime is offline-first and requires no API key.
- Specifications and repository text are untrusted data, not agent
  instructions.
- Initialization rejects unsafe targets, symlinks, and silent overwrites.
- Process execution uses argument arrays, timeouts, and bounded output.
- Comparative evaluation rejects parity drift and keeps Must, security,
  data-loss, and disclosure failures non-compensating.
- Schema migration is explicit, one-step, non-destructive, and validated by
  the current strict loader before exclusive output creation.
- Credentials, user-level Codex settings, and GitHub authentication state are
  out of scope.
- Publication requires secret, personal-path, language, dependency, and license
  audits plus separate Owner approval.

No production security support commitment is made for this pre-release state.
Evaluation fixtures and passing Gates do not guarantee the absence of defects.
