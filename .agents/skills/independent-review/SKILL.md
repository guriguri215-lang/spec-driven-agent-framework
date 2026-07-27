---
name: independent-review
description: Review a change against requirements and evidence without editing it.
---

# Independent Review

## Trigger

Use after implementation and initial verification, before a gate or commit.

## Do not use

Do not use as the implementation agent, as an automatic approval, or as a
replacement for tests and static analysis.

## Procedure

1. Read the approved requirements, plan, diff, and evidence.
2. Search for missing Must behavior, counterexamples, regressions, and unsafe
   boundary changes.
3. Inspect tests for weak assertions and untested failure paths.
4. Review secrets, privacy, dependency, license, and publication risks.
5. Classify findings by severity with precise evidence.
6. Return findings only; do not edit, stage, or commit.

## Output

Return a structured finding list, residual risks, unverified claims, and a
gate recommendation.

## Verification

Every finding identifies an affected requirement or boundary, evidence, and a
clear remediation or acceptance decision.

## Risks

Primary risks are self-review bias, same-model consensus, speculative findings,
and accidentally mutating the reviewed worktree.
