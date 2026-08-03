# Open Decisions

The V1.0 release-readiness product decisions are resolved:

- project `SDAQF`, repository `spec-driven-agent-framework`, and
  distribution/CLI `sdaqf`;
- Apache-2.0 with copyright holder `guriguri215-lang`;
- public repository visibility;
- release candidate `1.0.0rc1` for framework evaluators and advanced Codex
  users, not for production use;
- annotated tag and GitHub prerelease `v1.0.0-rc.1`, source-only GitHub
  archives, no attached assets, and no package-registry publication;
- Windows and Linux with Python 3.12 and 3.13 required; macOS
  `NOT_VERIFIED`;
- external pull requests closed during the release candidate, issue support
  best effort, and Code of Conduct deferred until open contributions; and
- GitHub private vulnerability reporting enabled, no prerelease backports,
  and best-effort six-month Critical-fix maintenance after final `1.0.0`.

The OpenAI API or Agents SDK adapter and management UI are deferred post-V1.
Final `1.0.0` requires a new exact candidate and Owner approval.

Candidate `9f14e2287da3afc078db787e823765320b1e23ac` completed its separately
approved commit, push, exact-SHA observation, visibility, tag, prerelease,
private-vulnerability-reporting, and post-publication checks. Actual Gate G5
passed for that tagged candidate. These approvals and observations do not
transfer to later M5-M7 commits or to a future release. Every new external
action remains a separate exact approval boundary.

The GitHub release body was reconciled with the tracked publication note on
2026-08-03. No V1 publication-metadata decision remains open; future release
or repository-setting changes still require their own reviewed action.
