# Agent Instructions

## Scope

Work inside this repository for normal development. The parent workspace is
local-only. Access a parent `state/` directory only when it is explicitly added
as a narrow secondary write root.

## Language

All tracked files, source code, identifiers, comments, CLI text, tests, branch
names, commit messages, GitHub templates, workflow labels, and future GitHub
metadata must be English. Translate or summarize approved local reports before
publication. Never copy private workspace reports into the repository.

## Sandbox and tools

- Distinguish a missing tool from a permission or sandbox denial.
- After one denied normal attempt, classify the cause before requesting one
  minimal technical sandbox approval for the exact command or narrow command
  family.
- Record the command, reason, paths, network destination, side effects,
  reversibility, Owner decision, and retry result.
- A technical sandbox approval does not replace an Owner approval.
- Do not use an administrator shell, UAC bypass, full-access mode, sandbox
  bypass flags, or `--yolo`.
- Do not read or change user-level Codex configuration, global agent
  instructions, GitHub authentication state, or credential stores.

## Git

- Confirm the Git root, branch, worktree, and staged paths before every write.
- Keep this repository on `main` unless an approved task specifies otherwise.
- Stage reviewed files explicitly; do not use an unreviewed `git add .`.
- Do not rewrite history, force push, hard reset, or indiscriminately clean.
- Creating a remote, pushing, posting to GitHub, tagging remotely, and
  publishing a release require a separate Owner approval.

## Quality

Run tests, lint, type checks, coverage, CLI smoke tests, boundary checks, and
publication audits before committing. Do not weaken requirements or tests to
make a gate pass. Preserve unresolved decisions as explicit open items.
