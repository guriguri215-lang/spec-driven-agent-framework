# Security Policy

## Supported status

SDAQF `1.0.0rc1` is a release candidate, not a production release.

## Reporting

Do not disclose suspected vulnerabilities in a public issue. GitHub private
vulnerability reporting is the intended channel only after it is enabled
through a separately approved repository-setting change when the repository
is public. Until that channel is confirmed, keep the report private and
request the current disclosure instructions from the Owner.

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

No prerelease backports or production security SLA are promised. A separately
approved final `1.0.0` receives best-effort Critical security and data-loss
fixes for six months. Evaluation fixtures and passing Gates do not guarantee
the absence of defects.
