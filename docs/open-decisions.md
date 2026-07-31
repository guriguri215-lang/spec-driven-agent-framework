# Open Decisions

The V1.0 release-readiness product decisions are resolved:

- project `SDAQF`, repository `spec-driven-agent-framework`, and
  distribution/CLI `sdaqf`;
- Apache-2.0 with copyright holder `guriguri215-lang`;
- repository visibility was approved to remain private through local
  finalization and to change only through a separately approved A7 boundary;
  the approved A7 command has since been accepted with exit code `0` and no
  output, without an independent post-A7 observation;
- release candidate `1.0.0rc1` for framework evaluators and advanced Codex
  users, not for production use;
- proposed tag `v1.0.0-rc.1`, source-only GitHub tag archives, no attached
  assets, and no package-registry publication;
- Windows and Linux with Python 3.12 and 3.13 required; macOS
  `NOT_VERIFIED`;
- external pull requests closed during the release candidate, issue support
  best effort, and Code of Conduct deferred until open contributions; and
- GitHub private vulnerability reporting after separately approved enablement,
  no prerelease backports, and best-effort six-month Critical-fix maintenance
  after final `1.0.0`.

The OpenAI API or Agents SDK adapter and management UI are deferred post-V1.
Final `1.0.0` requires a new exact candidate and Owner approval.

Product decisions alone did not authorize external actions. For predecessor
candidate `97082edc6ccbfcea5dfcd745681f7db435515074`, A3 commit, A4 push, A5
remote read, A6 exact-SHA attestation, and the A7 visibility-change command
were each separately approved and completed. A7 proves successful command
acceptance only; current visibility has not been independently observed.
The proposed tag, GitHub release, and private vulnerability reporting remain
uncreated or disabled, and actual Gate G5 remains `NOT_RUN`. Every action for
a new candidate remains a separate exact approval boundary.
