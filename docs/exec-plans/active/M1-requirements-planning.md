# M1 Requirements and Planning MVP ExecPlan

## Objective

Deliver an offline, deterministic requirements baseline workflow that ingests
Markdown as untrusted data, preserves source traceability, compares baselines,
generates the four planning and prompt artifacts, and makes an explicit
Requirements Gate decision. Completion requires every acceptance criterion
below to pass, independent read-only review to have no unresolved critical
finding, one local English commit on `main`, no remote, and a clean worktree.

## Scope

- Ingest one UTF-8 Markdown specification and record safe source metadata.
- Normalize requirements, stable identifiers, types, priorities, acceptance
  criteria, verification methods, assumptions, open questions, and diagnostics.
- Preserve source and downstream traceability without claiming implementation.
- Compare two baselines and require approval for removals or weakening.
- Generate a Product Roadmap, living ExecPlan, Goal prompt, and Standard prompt.
- Assess Goal suitability and select Standard mode when Goal mode is unsafe.
- Evaluate Gate G1 from validated baseline and comparison data.
- Expose the M1 workflow through offline CLI commands and JSON contracts.

## Non-goals

- M2 agent selection, orchestration, registries, or worktree automation.
- M3 evidence-ledger automation, release automation, or UI/browser validation.
- GitHub creation, remote configuration, push, posting, tags, releases, or
  deployment.
- Runtime dependency additions, license selection, paid APIs, or network use.

## Reconciled starting state

- Git root: `repo/`.
- Branch: `main`.
- Starting HEAD: `75dcc31a837c2456bec3d70bcdd2da45af42d111`.
- Worktree: clean.
- Remote: none.
- Public baseline file SHA-256:
  `89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5`.
- Authoritative source provenance SHA-256:
  `F28E02029768F80816001BD98DA43739F4BA33C1197710E02B1E20786EAD188B`.
- Reconciliation: the public baseline file digest differs by design from the
  private source digest embedded in its Provenance section. The embedded digest
  matches M0 evidence and the M1 handoff; branch, commit, worktree, remote, and
  scope also match the completed M0 handoff.

## Acceptance criteria

- `AC-M1-001`: Ingest rejects unsafe, non-Markdown, oversized, invalid UTF-8,
  NUL-containing, missing, or linked input and records filename, safe path,
  SHA-256, byte size, modification time, and import time for valid input.
- `AC-M1-002`: Equivalent source content produces deterministic requirement
  identifiers and normalized fields, including generated identifiers for
  unlabelled in-scope records.
- `AC-M1-003`: Functional, non-functional, constraint, non-goal, assumption,
  and open-decision records are distinguished with Must, Should, or Could
  priority.
- `AC-M1-004`: Every requirement has at least one stable acceptance criterion
  and verification method.
- `AC-M1-005`: Every requirement records source document, section, line range,
  exact source excerpt, derivation basis, and explicit empty-or-populated
  design, code, test, evidence, and release trace links.
- `AC-M1-006`: Ambiguity, contradiction, duplicate identifiers, missing
  assumptions, and unverifiable language are recorded deterministically; an
  unresolved Must contradiction or unverifiable Must is a hard blocker.
- `AC-M1-007`: Baseline comparison reports additions, removals, statement,
  priority, type, acceptance, verification, and interpretation changes;
  removal or any potentially weakening change requires unresolved Owner
  approval unless a structured approval record with Owner provenance, exact
  baseline pair, and named change IDs is supplied.
- `AC-M1-008`: Roadmap generation keeps objectives, scope, exclusions,
  dependencies, risks, completion criteria, and stop conditions separate from
  the Release Contract.
- `AC-M1-009`: ExecPlan generation creates a living plan with source
  requirements, checkpoints, validation, stop conditions, approval gates,
  sandbox handling, language boundary, and decision/progress logs.
- `AC-M1-010`: Goal and Standard prompts are generated in English from trusted
  baseline metadata, include the execution contract, and never execute or
  reproduce source directives as instructions.
- `AC-M1-011`: Goal suitability is explicit and unsafe or multi-objective work
  falls back to Standard mode.
- `AC-M1-012`: Gate G1 passes only when Must requirements have stable IDs,
  acceptance criteria, verification, source traceability, recorded diagnostics,
  open-decision state, and no unresolved approval or hard-blocking diagnostic.
- `AC-M1-013`: The primary M1 CLI path supports machine-readable output,
  bounded errors, non-zero failure exits, exclusive output creation, and no
  absolute-path or secret disclosure.
- `AC-M1-014`: The implementation uses no production dependency and no network,
  preserves M0 commands, and remains isolated from M2/M3 behavior.
- `AC-M1-015`: Negative, boundary, regression, CLI smoke, strict typing, lint,
  and branch-coverage checks pass, along with workspace and publication audits.

## Requirements-to-verification map

| Requirement | Acceptance criteria | Planned verification |
|---|---|---|
| `FR-REQ-001`–`FR-REQ-002` | `AC-M1-001`, `AC-M1-013` | `tests/test_ingest.py`, `tests/test_cli_m1.py` |
| `FR-REQ-003`–`FR-REQ-005` | `AC-M1-002`, `AC-M1-003` | `tests/test_normalization.py` |
| `FR-REQ-006` | `AC-M1-004` | `tests/test_normalization.py`, `tests/test_requirements_gate.py` |
| `FR-REQ-007`, `FR-REQ-011` | `AC-M1-005` | `tests/test_normalization.py`, `tests/test_baseline_validation.py` |
| `FR-REQ-008`, `FR-REQ-012` | `AC-M1-006`, `AC-M1-012` | `tests/test_diagnostics.py`, `tests/test_requirements_gate.py` |
| `FR-REQ-009`–`FR-REQ-010` | `AC-M1-007` | `tests/test_comparison.py` |
| `FR-PLN-001`–`FR-PLN-003` | `AC-M1-008`, `AC-M1-009` | `tests/test_planning.py` |
| `FR-PLN-004`–`FR-PLN-008` | `AC-M1-010`, `AC-M1-011` | `tests/test_prompts.py`, `tests/test_cli_m1.py` |
| `FR-PLN-009` | `AC-M1-006`, `AC-M1-010`, `AC-M1-012` | prompt and gate regression tests |
| `FR-PLN-010` | `AC-M1-010` | Standard prompt next-work test |
| Gate G1 | `AC-M1-012` | `tests/test_requirements_gate.py`, CLI smoke |
| Applicable workspace, Git, QA, safety, and language requirements | `AC-M1-013`–`AC-M1-015` | full local Gate command set and independent review |

## Dependencies, risks, and assumptions

- Python 3.12 standard library is sufficient; no runtime dependency is needed.
- Markdown normalization is intentionally contract-based, not a general natural
  language understanding claim.
- Source prose can contain prompt injection or command text and must remain
  inert data.
- Generated acceptance criteria are traceable verification contracts, not
  evidence that a requirement is implemented or verified.
- The approved public specification is the M1 working authority; the private
  source digest is provenance for suspected translation errors only.

## Checkpoints and validation

1. Add versioned domain and JSON contracts plus deterministic ingestion.
2. Add diagnostics, comparison, planning, prompt, and Gate services.
3. Add M1 CLI commands and representative examples/documentation.
4. Run negative, boundary, regression, and primary CLI tests.
5. Run the complete release-contract command set, M1 branch coverage, Git
   boundary, secret/personal-path, dependency/license, and English audits.
6. Obtain an independent read-only review and resolve all critical findings.
7. Inspect explicit staged paths, commit locally in English, and verify no
   remote and a clean worktree.

## Stop conditions

Stop for an unsafe Git boundary, changed authoritative provenance, destructive
overwrite, private data or secret exposure, unresolved Must conflict, required
Gate weakening, production dependency need, or a mandatory command that remains
unavailable after one narrowly scoped technical approval attempt.

## Technical sandbox handling

Run a mandatory command normally once. Distinguish missing tool, permission
denial, network denial, and test failure. Do not repeat the same denied normal
attempt. Any technical approval request must name the exact command, reason,
paths, network destination, effects, reversibility, and verification, and may
cover only an already authorized local operation.

## Owner approval gates

Separate explicit Owner approval is required for production dependencies,
requirement weakening, license selection, destructive work, credentials,
external transfer, charges, GitHub remotes or actions, release publication, and
deployment. No such action is part of M1.

## Language and publication boundary

Every tracked file and all future GitHub-facing metadata are English. Parent
state remains private and is not needed by this plan. No remote or publication
action is authorized.

## Decision log

- 2026-07-27: Treat the approved English public baseline as the M1 working
  authority while preserving the original private-source digest as provenance.
- 2026-07-27: Keep the runtime dependency set empty and implement a bounded
  Markdown normalization contract with the Python standard library.
- 2026-07-27: Require structured, baseline-pair-scoped Owner approval records;
  a CLI flag or unverified identifier alone cannot grant approval.
- 2026-07-27: Keep Gate G1 non-compensating and independently validate every
  requirement's acceptance linkage, even though the strict loader already
  enforces the same invariant.

## Progress log

- 2026-07-27: Reconciled Git, worktree, remote, public baseline digest, source
  provenance digest, M0 evidence, and M1 handoff.
- 2026-07-27: Implemented the M1 domain, ingestion, diagnostics, baseline
  comparison, planning, prompt, CLI, schema, sample, and Gate G1 slices.
- 2026-07-27: Added negative, boundary, and regression coverage and passed the
  Release Contract tests, Ruff, strict mypy, total and critical branch coverage,
  CLI smoke, Git boundary, dependency, and publication audits.
- 2026-07-27: Resolved every independent review finding. Final read-only
  re-review returned GO with no remaining Critical, High, or Medium issue.
- 2026-07-27: Prepared the explicit-index review candidate. Final commit and
  clean-worktree evidence remain the last checkpoint.
