---
name: release-audit
description: Audit a release candidate for reproducibility and publication safety.
---

# Release Audit

## Trigger

Use only after implementation gates pass and a candidate publication set is
known.

## Do not use

Do not use to publish, choose a license, access credentials, or bypass an Owner
approval.

## Procedure

1. Reproduce installation and required checks in a clean environment.
2. Verify requirement coverage and evidence sufficiency.
3. Audit tracked files for secrets, personal paths, private state, language,
   licenses, dependencies, generated files, and unsafe links.
4. Verify branch, commit, tags, remotes, and worktree.
5. Prepare exact English outbound metadata.
6. Stop before every external GitHub action and request Owner approval.

## Output

Return pass, fail, and not-verified results; the candidate file set; outbound
metadata; residual risks; and required Owner decisions.

## Verification

No hard blocker is open, every public claim has evidence, and the requested
external action is explicit and separately approved.

## Risks

Primary risks are secret disclosure, accidental publication, license
misrepresentation, stale evidence, and technical approval being mistaken for
product approval.
