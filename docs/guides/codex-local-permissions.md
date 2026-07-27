# Codex Local Permissions Guide

User and machine settings are Owner-managed. This repository never modifies
them automatically.

## Windows guidance

When an Owner uses legacy user-level sandbox configuration rather than a
Permission Profile, a typical safe shape is:

```toml
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[windows]
sandbox = "elevated"
```

Do not combine Permission Profile settings with legacy sandbox keys. Managed
organization policy takes precedence. The word `elevated` identifies the
Windows sandbox implementation; it does not authorize an unrestricted
administrator shell.

## Denied commands

Do not classify a denied command as missing. Attempt a required command once,
classify the failure, and request one narrowly scoped technical sandbox
approval only when the product action is already authorized. Include the exact
command, reason, paths, network destination, side effects, reversibility, and
verification method.

A technical approval cannot authorize publication, destructive Git changes,
credential access, paid operations, or machine-wide settings.

## Prohibited approaches

Do not launch an administrator PowerShell, bypass UAC, disable the sandbox,
enable unrestricted access, use approval-bypass flags, or modify user settings
to silence a denial.

## Working directory

The parent workspace is used only for bootstrap and multi-repository
coordination. Normal M1 and later development uses this repository as the
Primary folder. Add only the parent `state/` directory as a secondary write root
when a task explicitly needs local handoff state.
