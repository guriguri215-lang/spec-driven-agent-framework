---
name: create-exec-plan
description: Create a bounded execution plan for one approved milestone.
---

# Create Execution Plan

## Trigger

Use for a multi-step milestone with measurable completion, checkpoints, and
quality gates.

## Do not use

Do not use for an unbounded backlog, an approval decision, or a one-line
mechanical edit.

## Procedure

1. Link the approved requirement and acceptance-criterion identifiers.
2. Define objective, scope, and non-goals.
3. List dependencies, assumptions, risks, and unresolved decisions.
4. Define checkpoints, validation commands, and evidence artifacts.
5. State stop conditions and rollback or recovery behavior.
6. Separate technical sandbox handling from Owner approval gates.
7. Preserve language and publication boundaries.

## Output

Write a living Markdown execution plan under `docs/exec-plans/active/`.

## Verification

Confirm the plan has one measurable objective, complete gates, bounded scope,
and no authorization expansion.

## Risks

Primary risks are scope creep, circular completion criteria, missing approval
gates, and plans that hide unavailable evidence.
