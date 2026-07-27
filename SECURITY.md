# Security Policy

## Supported status

M0 is a development bootstrap and is not a production release.

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
- Credentials, user-level Codex settings, and GitHub authentication state are
  out of scope.
- Publication requires secret, personal-path, language, dependency, and license
  audits plus separate Owner approval.

No production security support commitment is made for this pre-release state.
