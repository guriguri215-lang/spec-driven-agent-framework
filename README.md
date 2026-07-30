# SDAQF

SDAQF is a specification-driven development and quality-assurance framework for
Codex-assisted projects. This repository contains the M0 Bootstrap Foundation,
M1 Requirements and Planning MVP, M2 Agent, Skill, and Tool Orchestration, and
M3 Evidence, UI/UX, and Release QA, M4 Public Beta Hardening, and the local
V1.0 release-candidate readiness contract: an
offline-first Python CLI, deterministic
requirement, orchestration, evidence, review, UI-observation, release, and
handoff contracts, representative evaluation projects, explicit schema
migration, safety guidance, reusable agent skills, and local quality gates.

The authoritative source for this bootstrap was a private Japanese
specification. The public English baseline records its source digest without
copying private workspace state.

## Implemented in M0

- Safe workspace and Git-boundary checks.
- A standard-library Python package with no runtime dependencies.
- `doctor`, `init`, `validate`, `status`, and `goal-template` commands.
- Tool-state separation for available, unavailable, permission-denied, and
  intentionally untested capabilities.
- Initial project, requirement, evidence, approval, execution, handoff, tool,
  and agent schemas with samples.
- Tests, linting, strict type checking, branch coverage, and Windows/Linux CI.
- Public documentation, GitHub templates, and reusable Codex skills.
- Repository audits for publication scope, language, secrets, personal paths,
  symlinks, and local-only Git state.

## Implemented in M1

- Bounded UTF-8 Markdown ingestion with SHA-256, size, modification time, safe
  source path, and import-time metadata.
- Deterministic requirement types, priorities, stable explicit or generated
  identifiers, acceptance criteria, verification methods, and source excerpts.
- Explicit ambiguity, contradiction, duplicate, missing-assumption, and
  unverifiable-language diagnostics.
- Design, code, test, evidence, and release trace fields that remain empty until
  supported records are supplied.
- Approval-aware baseline comparison for additions, removals, statement,
  priority, type, acceptance, verification, and interpretation changes. A
  removal or potentially weakening change can be approved only through a
  structured Owner approval record scoped to both baselines and named change
  IDs.
- Product Roadmap, living ExecPlan, Goal prompt, and Standard prompt generation
  with Goal suitability and safe Standard fallback.
- Gate G1 enforcement for a complete, non-implemented requirements baseline.
- `ingest`, `compare`, `roadmap`, `exec-plan`, `goal`, `prompt`, and
  `gate requirements` CLI commands.

## Implemented in M2

- Strict versioned Agent and Tool Registries with cross-reference validation.
- Deterministic role selection by problem type, scale, risk, and parallelism,
  bounded by agent count, concurrency, and reasoning effort.
- Host-native Subagent planning with independent-session and sequential
  fallback prompts; the package does not launch a nested Codex process.
- Read-only parallelization boundaries and explicit isolated-write plans with
  distinct worktrees, non-overlapping ownership, one base commit, and an
  integrator.
- Logical implementer/reviewer separation, bounded structured summaries, and
  evidence-based disagreement resolution.
- Repository Skill and template lifecycle validation.
- Safe resolved-executable tool probes with exact argument arrays, no shell, a
  sanitized environment, timeout, exit status, duration, and truly bounded
  stdout and stderr.
- Strict versioned single-execution approvals with distinct Owner and technical
  sandbox provenance, exact command/path/network/risk scope, expiry checks,
  and a persistent atomic consumption claim before process start; denial
  classification, optional-tool isolation, bounded retry, atomic checkpoints,
  corruption recovery, and strict resume identity.
- `agents`, `skills`, `tools`, and `checkpoint` CLI command groups.

## Implemented in M3

- A bounded versioned Claim-Evidence Ledger with strict claim/evidence
  cross-references, explicit confidence and criticality, secret-free fields,
  safe relative artifacts, and deterministic serialization.
- Atomic repository-bounded `evidence add` with duplicate, traversal, link,
  corruption, and failure cleanup protection.
- Non-compensating Gate G2 implementation-evidence checks that require Must and
  acceptance mappings, applicable tests, evidence beyond passing tests alone,
  explicit unverified state, diff review, and hard critical blockers.
- Gate G3 independent read-only review checks for reviewer separation,
  regression/security/maintainability coverage, resolved material findings, and
  exact Owner approval for any accepted critical finding.
- Manifest-based UI classification. Non-UI projects require no fabricated UI
  work; UI projects require a Design Brief and bounded recorded host-browser
  observations for primary flows, states, viewports, keyboard, focus,
  readability, contrast, screenshots, offline behavior, and recovery. Passing
  observations also require a content-bound execution trace, a browser-matched
  executable and version, and a decodable bounded PNG.
- Local Gate G4 release-candidate checks combining G2/G3/UI results,
  exact-commit isolated offline installation from a publication-only owned
  source snapshot, installed-execution evidence, verified Must claims,
  secret/disclosure/dependency/license/documentation audits, rollback guidance,
  and a read-only clean-Git observation.
- Deterministic automated handoff creation and resume mismatch detection with a
  bounded next-session prompt that is recorded but never executed.
- `evidence`, `gate implementation`, `gate review`, `ui`,
  `audit release-candidate`, and `handoff` CLI paths.

## Implemented in M4

- Three representative sample specifications for an offline non-UI command,
  an offline UI workflow, and an approval/security-sensitive export, each with
  an expected deterministic normalization projection.
- Strict evaluation-suite and run-record contracts with exact input parity,
  deterministic missed requirements, scope additions, critical defects,
  rework, approvals, and failed handoffs.
- Execution trace, decision, evidence, and cost-availability comparison without
  an aggregate score. Must, security, data-loss, and disclosure failures remain
  named hard blockers.
- A tracked paired structured-SDAQF and ordinary-unstructured-Codex fixture
  result with content-bound review artifacts and explicit authored-scenario,
  non-empirical, non-causal limitations.
- Explicit non-destructive Agent Registry and Tool Registry 1.0-to-2.0
  migration with conservative defaults, current-loader validation, source
  preservation, an exact atomically consumed single-use Owner approval, and
  exact rollback or indeterminate-publication guidance without automatic path
  deletion.
- Public contributor, evaluation, migration, architecture, extension,
  security, testing, and release-limit documentation.
- `eval validate`, `eval compare`, and `schema migrate` CLI paths.

## V1.0 release-candidate readiness

- Distribution/runtime version `1.0.0rc1`, targeting public API line `1.0.0`.
- Apache License 2.0 with exact `LICENSE` and `NOTICE` material.
- Historical release-candidate schema 1.0 preservation and selected-license
  schema 1.1.
- An offline `gate publication-readiness` command that can return
  `LOCAL_READY` but never claims actual Gate G5 or publication.
- English compatibility, migration, release, support, security, contribution,
  platform, artifact, and known-limitation policies.

The proposed tag is `v1.0.0-rc.1`, but the tag, release, and public visibility
have not been created or changed. This release candidate is for framework
evaluators and advanced Codex users and is not for production use.

The pinned development dependency and license record is in
`docs/dependencies.md`.

## Known limitations

### Not implemented for the release candidate

- Automatic Git worktree creation, deletion, or integration.
- A management UI or automatic browser installation and launch. The offline
  core validates browser observations recorded by a host capability.
- Gate G5 publication or automatic release publication.
- Migration for contracts other than the explicit Agent and Tool Registry
  1.0-to-2.0 routes.
- A blinded, randomized, independently replicated, statistically powered, or
  cost-comparable Codex benchmark.
- Solver, OpenAI API, or Agents SDK integrations.
- GitHub repository creation, remotes, pushes, pull requests, issues, tags, or
  releases.
- Production deployment.

## Installation

### Quick start

Use Python 3.12 or newer in an isolated environment:

```text
python -m venv .venv
.venv\Scripts\python -m pip --isolated install -r requirements-dev.lock
.venv\Scripts\python -m pip --isolated install --no-build-isolation --no-deps -e .
.venv\Scripts\python -m pytest
.venv\Scripts\sdaqf --help
```

On POSIX systems, use `.venv/bin/python` instead.

Example commands:

```text
python -m sdaqf doctor --json
python -m sdaqf validate examples/sample-project
python -m sdaqf status examples/sample-project --json
python -m sdaqf goal-template M1
python -m sdaqf init scratch-project --dry-run
python -m sdaqf ingest examples/sample-specification.md --output baseline.json
python -m sdaqf gate requirements baseline.json --json
python -m sdaqf roadmap baseline.json M1 --output roadmap.md
python -m sdaqf exec-plan baseline.json M1 --output exec-plan.md
python -m sdaqf goal baseline.json M1 --output goal.md
python -m sdaqf prompt baseline.json M1 --output prompt.md
python -m sdaqf agents validate examples/m2-orchestration/agent-registry.json --tools examples/m2-orchestration/tool-registry.json --json
python -m sdaqf agents plan examples/m2-orchestration/orchestration-request.json --registry examples/m2-orchestration/agent-registry.json --tools examples/m2-orchestration/tool-registry.json --json
python -m sdaqf skills validate .agents/skills --templates examples/m2-orchestration/template-registry.json --framework-version 1.0.0 --available independent-review --json
python -m sdaqf tools check examples/m2-orchestration/tool-registry.json --name git --json
python -m sdaqf checkpoint validate examples/m2-orchestration/execution-checkpoint.json --json
python -m sdaqf evidence validate examples/m3-quality/claim-evidence-ledger.json --json
python -m sdaqf gate implementation baseline.json --ledger .sdaqf/ledger.json --specification specification.md --json
python -m sdaqf gate review .sdaqf/review.json --baseline baseline.json --specification specification.md --json
python -m sdaqf ui validate manifest.json .sdaqf/ui-validation.json --specification specification.md --json
python -m sdaqf audit release-candidate .sdaqf/release-candidate.json --root . --baseline baseline.json --ledger .sdaqf/ledger.json --review .sdaqf/review.json --manifest manifest.json --ui-validation .sdaqf/ui-validation.json --specification specification.md --json
python -m sdaqf gate publication-readiness .sdaqf/v1/public-release-candidate.json --root . --baseline .sdaqf/v1/requirements-baseline.json --ledger .sdaqf/v1/claim-evidence-ledger.json --review .sdaqf/v1/independent-review.json --release-candidate .sdaqf/v1/release-candidate.json --specification docs/specification.md --json
python -m sdaqf handoff create handoff-input.json --baseline baseline.json --ledger .sdaqf/ledger.json --specification specification.md --output .sdaqf/handoff.json --json
python -m sdaqf eval validate evals/comparison-suite.json --result evals/results/public-beta-comparison.json --json
python -m sdaqf eval compare evals/comparison-suite.json --json
python -m sdaqf schema migrate --contract agent-registry --from-version 1.0 --to-version 2.0 examples/m4-migration/agent-registry-v1.json --output migrated-agent-registry.json --approval .sdaqf/migration-approval.json --tool-registry examples/m4-migration/tool-registry-v2.json --json
```

## Safety boundaries

The runtime remains offline-first through the V1 release candidate. Private
remote operations and any
publication require an exact Owner-approved target and scope. A technical
sandbox approval never authorizes publication, destructive Git operations,
credential access, or machine-wide configuration changes.

M3 Gate and handoff commands inspect the current repository directly. Candidate
records under `.sdaqf/` must bind to the current source digest, full Git HEAD,
and deterministic repository digest; copied sample identities are illustrative
and are not accepted as current proof.

Gate G4 installation evidence must target the derived
`<install-target>-source` snapshot. That owned tree must contain exactly the
regular files in Git's cached-plus-untracked publication set; ignored worktree
files are never build inputs. Both owned install directories are named in the
exact rollback contract.

Schema migration never runs implicitly and never overwrites its source or an
existing output. Evaluation fixtures are measurement inputs, not instructions,
and their tracked comparison result does not establish causation, model
quality, production security, or production readiness.

## License

SDAQF is licensed under Apache License 2.0. Copyright 2026
`guriguri215-lang`. See `LICENSE` and `NOTICE`.

Support is best effort, has no SLA, and applies to the latest release only.
See `SUPPORT.md`, `SECURITY.md`, and `docs/compatibility.md`.
