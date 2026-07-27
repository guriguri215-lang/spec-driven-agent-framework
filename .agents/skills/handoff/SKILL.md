---
name: handoff
description: Produce a complete, non-executing prompt and state record for the next session.
---

# Handoff

## Trigger

Use at a milestone boundary, an intentional session split, or a genuine block.

## Do not use

Do not use to conceal failed checks, auto-run the next task, or copy private
state into public artifacts.

## Procedure

1. Record source digest, plan version, branch, commit, and worktree.
2. Separate completed, verified, unverified, blocked, and unresolved items.
3. List evidence commands and artifacts.
4. Preserve stop conditions, sandbox rules, language policy, and Owner gates.
5. Specify the exact Primary folder and any narrow secondary write root.
6. Generate a complete next-session prompt but do not execute it.

## Output

Return a structured handoff plus a complete next-session prompt.

## Verification

Compare the handoff with the actual Git state and confirm that no private or
personal data entered a GitHub-facing artifact.

## Risks

Primary risks are stale Git state, omitted blockers, implicit authorization,
and accidental continuation in the wrong working directory.
