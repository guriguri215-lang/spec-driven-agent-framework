# SDAQF Public Specification Baseline

## Provenance

- Public baseline: `SDAQF-SPEC-001`, version `0.2.0-draft`.
- Authoritative source filename: `SPECIFICATION.md`.
- Source SHA-256:
  `F28E02029768F80816001BD98DA43739F4BA33C1197710E02B1E20786EAD188B`.
- Derived on: 2026-07-27.
- Derivation rule: translate and summarize requirements in English while
  preserving stable identifiers, normative strength, safety boundaries, and
  unresolved decisions. Do not copy private state or personal paths.
- Known difference: this public baseline is an English operational summary,
  not a line-for-line translation. It preserves every stable requirement ID,
  normative boundary, Gate, data contract, milestone, and open decision needed
  for later implementation. Explanatory prose and examples are condensed.
- Transformation status: no requirement is intentionally omitted, weakened,
  or promoted. No item remains untranslated. Any future ambiguity must be
  recorded rather than silently resolved.
- Authority: this English baseline is the approved public working baseline
  derived during M0. The named source and digest remain the provenance
  authority for resolving a suspected translation error.

## Normative language

`MUST` is required for the applicable milestone or release. `SHOULD` is the
default unless a documented rationale and impact justify a deviation. `MAY` is
optional. Requirements below are `MUST` unless they explicitly say `SHOULD` or
`MAY`. A requirement assigned to a later milestone is normative for that
milestone and is not an M0 implementation claim.

## Purpose

SDAQF transforms an input specification into structured requirements,
acceptance criteria, plans, implementation evidence, gate decisions, releases,
and handoffs. It aims to reduce scope drift, unverified completion claims,
unsafe automation, and loss of state between Codex sessions.

## Product goals

- `G-001`: Extract functional and non-functional requirements, exclusions,
  open decisions, and acceptance criteria with stable identifiers.
- `G-002`: Preserve traceability across requirements, design, implementation,
  tests, evidence, and release.
- `G-003`: Support Goal and Standard modes through a common execution contract.
- `G-004`: Use multiple agents only when needed, favoring safe read-heavy
  parallelism and independent review.
- `G-005`: Manage reusable Codex Skills, templates, validation scripts, and
  tool definitions.
- `G-006`: Validate UI/UX through real interaction, screenshots,
  accessibility checks, and primary flows when a project has a UI.
- `G-007`: Focus human involvement on purpose, specification changes, risk,
  publication, and other bounded decisions.
- `G-008`: Produce state, evidence, open decisions, recommended next work, and
  a new-session prompt at session completion.
- `G-009`: Structurally separate local private state from publishable content.
- `G-010`: Evaluate whether SDAQF improves outcomes over unstructured
  AI-assisted development.

## Non-goals

- `NG-001`: Do not replace human product, ethical, legal, or publication
  judgment.
- `NG-002`: Do not claim to guarantee the absence of defects.
- `NG-003`: Do not require the OpenAI API, Agents SDK, or cloud execution for
  core functionality.
- `NG-004`: Do not bundle every solver, EDA tool, browser, or database; extend
  them through adapters and the tool registry.
- `NG-005`: Do not replace IDEs, GitHub, CI, or package managers wholesale.
- `NG-006`: Do not deploy, create a public repository, push, incur charges, or
  change credentials without Owner approval.
- `NG-007`: Do not maximize agent or test counts as proxy quality metrics.

## Constraints

- `C-001`: Windows 11 is the primary environment; Linux and macOS compatibility
  is `SHOULD`.
- `C-002`: Support Python 3.12 or newer and include Python 3.13 in primary
  development validation.
- `C-003`: The basic workflow must work with a Codex subscription alone.
- `C-004`: Never store API keys, GitHub tokens, or secrets in the repository.
- `C-005`: Specification analysis, state management, prompt generation, and
  Gate decisions must work without network access.
- `C-006`: Never install packages globally; use an isolated environment such
  as `repo/.venv`.
- `C-007`: Record provenance and licenses for generated code, dependencies,
  templates, and external material.
- `C-008`: Owner dialogue and private parent state may use Japanese.
- `C-009`: Every GitHub-facing artifact and metadata item must be English,
  including public files, source, identifiers, comments, CLI output, tests,
  branches, commits, workflows, issues, reviews, labels, and releases.
- `C-010`: User or machine Codex settings are Owner-managed and must not be
  changed automatically.
- `C-011`: On native Windows, use a managed Permission Profile when present;
  otherwise the Owner should use an on-request, workspace-write, elevated
  Windows sandbox boundary without mixing configuration models.
- `C-012`: A sandbox or access denial alone must not be classified as a missing
  tool.
- `C-013`: An already approved local operation may request the narrowest
  necessary technical sandbox approval.
- `C-014`: Do not launch an administrator shell, bypass UAC or OS controls, use
  unrestricted access, or use sandbox-bypass flags.
- `C-015`: Technical sandbox approval never replaces Owner approval for
  publication, external effects, destructive work, or other product decisions.
- `C-016`: At M0 start, record observable differences between the actual
  client and changing Codex concepts such as configuration, protected paths,
  Goal mode, Subagents, and Skills.

## Workspace and Git boundaries

- `WKS-001`: The parent workspace must not be a Git repository.
- `WKS-002`: Only `repo/` is the Git root.
- `WKS-003`: Run Git with `git -C repo` or from the repository directory.
- `WKS-004`: Stop if `repo/` is a link, junction, or unexplained existing
  repository.
- `WKS-005`: Stop and ask the Owner about relocation or a submodule if the
  parent contains `.git`.
- `WKS-006`: Do not automatically copy `private/`, `scratch/`, `state/`, or
  other parent files into the repository.
- `WKS-007`: Derive required public content in English only after a disclosure
  and confidentiality review.
- `WKS-008`: Do not delete, move, or overwrite outside `repo/` without explicit
  Owner approval.
- `WKS-009`: Provide an automated parent/child Git-boundary check.
- `WKS-010`: M0 uses the parent workspace as the Primary folder only to read
  the source and create `repo/`.
- `WKS-011`: Normal work after M0 uses `repo/` as the Primary folder.
- `WKS-012`: Add only a specifically required parent subfolder, normally
  `state/`, as an additional write root; never grant broad parent or `private/`
  access.
- `WKS-013`: Parent-root coordination is allowed for cross-repository or local
  approval work only after naming the target Git root.
- `WKS-014`: User-level Codex configuration and global `AGENTS.md` remain
  untracked and Owner-managed.
- `WKS-015`: Repository Codex configuration contains only safe, portable
  project settings, never personal paths or machine sandbox policy.
- `WKS-016`: Repository instructions contain generalized safety rules in
  English; machine-specific private rules may remain in the parent.

## Functional requirements

### Workspace and initialization

- `FR-WKS-001`: Distinguish new and existing workspaces.
- `FR-WKS-002`: Inspect parent Git state, an existing `repo/`, links, and write
  access.
- `FR-WKS-003`: Limit writes outside `repo/` to explicitly allowed paths.
- `FR-WKS-004`: Create `.git` only within `repo/`.
- `FR-WKS-005`: Initialization must be idempotent and must not
  unconditionally overwrite existing files.
- `FR-WKS-006`: `doctor` reports Python, Git, Codex, GitHub CLI, Node, browser,
  and optional solver availability.
- `FR-WKS-007`: An unavailable optional tool is a capability state, not a
  fatal error.
- `FR-WKS-008`: Abstract or clearly document PowerShell and POSIX shell
  differences.
- `FR-WKS-009`: Distinguish at least `AVAILABLE`, `UNAVAILABLE`,
  `PERMISSION_DENIED`, and `NOT_CHECKED`.
- `FR-WKS-010`: Do not interpret a sandbox or access denial as proof that an
  executable is absent.
- `FR-WKS-011`: At M0 start, record observable Primary folder, sandbox,
  approval policy, and additional write roots.
- `FR-WKS-012`: Do not automatically inspect or change user Codex settings,
  GitHub authentication, or credential stores.
- `FR-WKS-013`: If local configuration could improve, generate an Owner
  recommendation without changing settings.
- `FR-WKS-014`: Guide post-M0 sessions to use `repo/` as Primary folder and add
  only required parent subfolders.

### Specification intake and requirements

- `FR-REQ-001`: Ingest a Markdown specification.
- `FR-REQ-002`: Record input SHA-256, modification time, path, and import time.
- `FR-REQ-003`: Assign stable requirement identifiers.
- `FR-REQ-004`: Distinguish functional, non-functional, constraint, non-goal,
  assumption, and open-decision records.
- `FR-REQ-005`: Preserve Must, Should, and Could or an equivalent priority.
- `FR-REQ-006`: Link every requirement to acceptance criteria and verification
  methods.
- `FR-REQ-007`: Trace source location, derivation basis, and interpretation
  assumptions.
- `FR-REQ-008`: Detect ambiguity, contradiction, missing assumptions, and
  requirements that cannot be implemented or verified.
- `FR-REQ-009`: Generate a requirement baseline and change comparison.
- `FR-REQ-010`: Require approval to remove or weaken a requirement.
- `FR-REQ-011`: Trace requirement to design, code, test, evidence, and release.
- `FR-REQ-012`: Never treat an unverified requirement as implemented.

### Roadmap, planning, and prompts

- `FR-PLN-001`: Manage Product Roadmap, ExecPlan, and Release Contract as
  separate artifacts.
- `FR-PLN-002`: Give each milestone an objective, scope, exclusions,
  dependencies, risks, completion criteria, and stop conditions.
- `FR-PLN-003`: Maintain the ExecPlan as a living document.
- `FR-PLN-004`: Generate Goal-mode prompts.
- `FR-PLN-005`: Generate Standard-mode prompts.
- `FR-PLN-006`: Assess Goal suitability and fall back to Standard mode when
  unsuitable.
- `FR-PLN-007`: Center each Goal on one objective and one verifiable terminal
  state.
- `FR-PLN-008`: Include references, protected scope, verification commands,
  checkpoints, and approval stops in each Goal.
- `FR-PLN-009`: Do not implement unsettled requirements implicitly.
- `FR-PLN-010`: Generate recommended next work and a new-session prompt when a
  task completes.

### Multi-agent operation

- `FR-AGT-001`: Maintain an Agent Registry with role, responsibility, inputs,
  outputs, tools, and prohibited actions.
- `FR-AGT-002`: Select only roles justified by problem type, scale, risk, and
  parallelism.
- `FR-AGT-003`: Native Codex Subagents may be used when available.
- `FR-AGT-004`: Fall back to independent-session prompts or sequential work
  when Subagents are unavailable.
- `FR-AGT-005`: Initially parallelize read-heavy discovery, test design, log
  analysis, and review.
- `FR-AGT-006`: By default, prohibit parallel writes to the same worktree or
  file.
- `FR-AGT-007`: Parallel writes require separate worktrees, explicit
  ownership, and an integrator.
- `FR-AGT-008`: Logically separate implementer and independent reviewer.
- `FR-AGT-009`: Subagents return a defined structured summary, not raw logs.
- `FR-AGT-010`: Resolve disagreements through specification, counterexamples,
  and evidence strength.
- `FR-AGT-011`: Allow budgets for agent count, reasoning effort, and
  concurrency.
- `FR-AGT-012`: Do not overvalue same-model agreement as independent evidence.

### Skills, templates, and tools

- `FR-TOL-001`: Store repository Skills at
  `.agents/skills/<skill-name>/SKILL.md`.
- `FR-TOL-002`: Each Skill defines its name, triggers, non-applicability,
  procedure, output, validation, and risks.
- `FR-TOL-003`: Each template records target, compatible version,
  dependencies, license, prohibited conditions, and validation date.
- `FR-TOL-004`: The Tool Registry records name, capability, command, platform,
  availability, risk, network use, and approval needs.
- `FR-TOL-005`: Check tool presence and version before use.
- `FR-TOL-006`: Run external processes with argument arrays, timeouts, exit
  codes, and bounded output.
- `FR-TOL-007`: Do not install globally.
- `FR-TOL-008`: Adding a production dependency requires Owner approval.
- `FR-TOL-009`: Add mathematical, SAT/SMT, optimization, statistics, and
  simulation tools only as optional adapters.
- `FR-TOL-010`: An unavailable optional solver must not break the core.
- `FR-TOL-011`: Record provenance and licenses for external code and templates.
- `FR-TOL-012`: Record claim, source, access date, and use when web research is
  performed.
- `FR-TOL-013`: The Tool Registry distinguishes normal scope, protected paths,
  network destinations, technical sandbox approval, and Owner approval.
- `FR-TOL-014`: Command evidence records normal or approved execution, denial
  class, and approval scope.

### Execution control and state

- `FR-EXE-001`: Track `planned`, `ready`, `running`, `blocked`,
  `verification`, `completed`, `rejected`, and `superseded` task states.
- `FR-EXE-002`: Persist long-running work at checkpoints.
- `FR-EXE-003`: Update state atomically and provide corruption recovery.
- `FR-EXE-004`: On resume, detect disagreement in Git HEAD, worktree,
  specification digest, or plan version.
- `FR-EXE-005`: Stop as `blocked` at a stop condition instead of guessing.
- `FR-EXE-006`: Record commands, results, duration, exit status, and related
  tasks.
- `FR-EXE-007`: Do not retain secrets, personal data, or unbounded raw logs in
  state.
- `FR-EXE-008`: An implementer must not self-approve using only its own result.
- `FR-EXE-009`: Bound retry count and retry conditions after failure.
- `FR-EXE-010`: Stop or reject changes outside the declared scope.
- `FR-EXE-011`: After a sandbox denial, classify it and request one narrow
  technical approval or block; do not repeat the identical normal attempt.
- `FR-EXE-012`: If approval is refused, unavailable, or ineffective, record the
  command, denial, Owner decision, and retry outcome as evidence.
- `FR-EXE-013`: Never use technical sandbox approval for prohibited work or
  unapproved external effects.

### Quality assurance and evidence

- `FR-QA-001`: Maintain a Claim-Evidence Ledger.
- `FR-QA-002`: Support `TEST`, `STATIC_ANALYSIS`, `TYPE_CHECK`, `BENCHMARK`,
  `VISUAL`, `MANUAL_REVIEW`, `SOURCE_REVIEW`, and `UNVERIFIED` evidence.
- `FR-QA-003`: Record claim, environment, command, result, artifact, timestamp,
  and commit for each evidence item.
- `FR-QA-004`: Select applicable unit, integration, E2E, property, regression,
  performance, and security test layers.
- `FR-QA-005`: Do not infer requirement conformance from passing tests alone.
- `FR-QA-006`: Trace each test to the acceptance criteria it verifies.
- `FR-QA-007`: Review diffs for scope drift, dead code, regressions, and
  dangerous patterns.
- `FR-QA-008`: Include secret, dependency, and license audits in the public
  release Gate.
- `FR-QA-009`: Confirm installation and execution in a clean or reproducible
  environment.
- `FR-QA-010`: Declare unrun tests, missing environments, and network limits.
- `FR-QA-011`: Critical Must, security, data-loss, or disclosure failures are
  hard blockers that no score can offset.
- `FR-QA-012`: Final reports distinguish implemented, verified, unverified,
  and known-problem states.
- `FR-QA-013`: Facts may carry A, B, C, or D confidence.
- `FR-QA-014`: Do not claim complete, safe, or production-ready without
  evidence.

### UI and UX

- `FR-UI-001`: Classify whether a project has a UI during intake.
- `FR-UI-002`: For a UI project, define a Design Brief, users, flows, states,
  and target devices.
- `FR-UI-003`: Design loading, empty, error, permission-denied, and offline
  states.
- `FR-UI-004`: Exercise primary flows in a real browser or target platform.
- `FR-UI-005`: Check viewports, keyboard operation, focus order, readability,
  and contrast.
- `FR-UI-006`: Store screenshots and execution results as evidence.
- `FR-UI-007`: Use visual regression when practical.
- `FR-UI-008`: UI/UX review covers information structure, recovery,
  efficiency, and accessibility as well as appearance.
- `FR-UI-009`: Prefer primary sources and official design systems in web
  research.
- `FR-UI-010`: Do not copy third-party designs, images, or prose without
  authorization.
- `FR-UI-011`: Limit Owner questions to value judgments such as direction,
  priority flows, brand, and publication.
- `FR-UI-012`: Do not start a UI agent for a project without a UI.

### Approval and safety

- `FR-APR-001`: Classify actions as `low`, `medium`, `high`, or `prohibited`.
- `FR-APR-002`: Approval requests state target, reason, recommendation,
  alternatives, impact of declining, risk, reversibility, privilege, and
  validation.
- `FR-APR-003`: Explicit Owner approval is required for GitHub repository
  creation, remotes, push, releases, licenses, production dependencies,
  destructive Git, writes outside `repo/`, credentials or personal data,
  external transfer, charges, deployment, migration, or changes to Must
  requirements, non-goals, or security boundaries.
- `FR-APR-004`: Record approval target, scope, lifetime, and conditions.
- `FR-APR-005`: Do not reuse approval for a different operation.
- `FR-APR-006`: Choose the higher risk class when uncertain.
- `FR-APR-007`: Do not re-ask for a scope already explicitly approved.
- `FR-APR-008`: Refuse prohibited work instead of requesting approval.
- `FR-APR-009`: Model technical sandbox and Owner approvals separately.
- `FR-APR-010`: A narrow technical approval may unblock an already approved
  local operation.
- `FR-APR-011`: A technical approval request states the full command, reason,
  paths, network destination, effects, reversibility, and validation.
- `FR-APR-012`: Technical approval is limited to one command or a narrow
  command family.
- `FR-APR-013`: Do not request permanent broad permission for Python,
  PowerShell, Git, or GitHub CLI.
- `FR-APR-014`: Audit sandbox denials, requests, Owner decisions, approval
  scope, and retry results.
- `FR-APR-015`: If the Owner refuses technical approval, do not repeat it; mark
  the work blocked.
- `FR-APR-016`: Technical approval cannot authorize a prohibited or
  Owner-gated operation.

### Session handoff

- `FR-HOF-001`: At session end, record branch, HEAD, worktree state,
  specification digest, and milestone.
- `FR-HOF-002`: Record completed work, evidence, incomplete work, open
  decisions, known problems, and recommended next work.
- `FR-HOF-003`: A next-session prompt includes role, references, change scope,
  exclusions, completion criteria, stop conditions, and approval conditions.
- `FR-HOF-004`: At a new session, detect mismatch between the handoff and the
  actual repository.
- `FR-HOF-005`: Keep related work within one Goal or ExecPlan; split at
  milestones, independent review, direction changes, or context contamination.
- `FR-HOF-006`: Never execute the next prompt automatically; await the Owner.
- `FR-HOF-007`: Carry English-publication, sandbox-denial, no-full-access, and
  Owner-approval rules into the next prompt.
- `FR-HOF-008`: State the Primary folder and any narrowly required additional
  write root in the next prompt.

### Git, GitHub, and release

- `FR-GIT-001`: Git operations target only `repo/`.
- `FR-GIT-002`: The default branch is `main`.
- `FR-GIT-003`: Create a local commit only inside approved scope after quality
  Gates pass.
- `FR-GIT-004`: Keep commits purpose-specific with descriptive English
  messages.
- `FR-GIT-005`: Review and stage explicit paths; avoid indiscriminate
  `git add .`.
- `FR-GIT-006`: Do not use hard reset, destructive clean, force push, or
  history rewriting without Owner approval.
- `FR-GIT-007`: Before commit, inspect the diff, secrets, generated debris, and
  personal paths.
- `FR-GIT-008`: M0 creates no remote and performs no push.
- `FR-GIT-009`: Before publication, present repository name, visibility,
  description, license, default branch, and initial tag to the Owner.
- `FR-GIT-010`: GitHub Actions uses least privilege.
- `FR-GIT-011`: A public repository includes README, CONTRIBUTING, SECURITY,
  changelog, installation, and known limitations.
- `FR-GIT-012`: Before publication, scan for absolute paths, usernames, email,
  tokens, secrets, and personal data.
- `FR-GIT-013`: Do not call the project open source before a license is chosen.
- `FR-GIT-014`: Link releases to a requirement baseline and evidence summary.
- `FR-GIT-015`: Create all GitHub-facing artifacts and metadata in English.
- `FR-GIT-016`: English PR and issue templates require English title and body.
- `FR-GIT-017`: Branches, tags, public filenames, and public identifiers
  normally use ASCII English.
- `FR-GIT-018`: Before posting or publishing, scan for Japanese, untranslated
  Owner reports, and local-only information.
- `FR-GIT-019`: Review disclosure and translate or summarize a private
  Japanese report before using it on GitHub.
- `FR-GIT-020`: Before any external GitHub action, show the target and proposed
  English body to the Owner.

### Framework evaluation

- `FR-EVL-001`: Keep sample specifications and expected normalized results as
  fixtures.
- `FR-EVL-002`: Measure missed requirements, scope additions, critical
  defects, rework, approval count, and failed handoffs.
- `FR-EVL-003`: Define comparison with ordinary unstructured Codex use.
- `FR-EVL-004`: Do not hide security or Must failures inside one aggregate
  score.
- `FR-EVL-005`: Run evaluations before and after changing a Skill, template,
  or prompt.
- `FR-EVL-006`: When failures repeat, perform cause analysis and choose whether
  to change instructions, Skills, schemas, or tests.
- `FR-EVL-007`: Evaluate execution traces, decisions, evidence, and cost as
  well as deliverables.

## Non-functional requirements

- `NFR-001 Auditability`: Trace important decisions, approvals, commands,
  evidence, and state transitions.
- `NFR-002 Reproducibility`: The same input and versions produce equivalent
  normalization and Gate outcomes.
- `NFR-003 Portability`: Validate Windows 11, include Linux in CI, and support
  macOS on a `SHOULD` basis.
- `NFR-004 Offline Core`: Start and validate the core CLI without a network.
- `NFR-005 Security`: Treat inputs as untrusted and prevent path traversal,
  command injection, and secret disclosure.
- `NFR-006 Maintainability`: Separate domain logic, I/O, CLI, and external-tool
  adapters.
- `NFR-007 Extensibility`: Add agents, Skills, tools, and Gates through
  registries or plugins.
- `NFR-008 Usability`: An Owner can understand requirements, behavior,
  evidence, risk, and next action without reading code.
- `NFR-009 Determinism`: Make identifiers, schema validation, and Gate
  decisions deterministic where practical.
- `NFR-010 Performance`: Target a few seconds for `status`, `validate`, and
  `gate` on small projects.
- `NFR-011 Testability`: Permit replacement of filesystem, Git, process, and
  clock boundaries in tests.
- `NFR-012 Backward Compatibility`: Version schema changes and define
  migration policy.
- `NFR-013 Documentation`: Document public APIs, CLI, schemas, and extension
  points in English.
- `NFR-014 Accessibility`: Evaluate WCAG-equivalent accessibility if SDAQF
  gains a UI.
- `NFR-015 Coverage`: Emphasize branch coverage in core domain and Gate code;
  M0 thresholds are 80 percent total and 90 percent critical modules.
- `NFR-016 Language Governance`: Consistently audit the complete English
  GitHub-facing surface.
- `NFR-017 Least Privilege`: Minimize sandbox scope, write roots, network, and
  command approvals.
- `NFR-018 Configuration Portability`: Public settings do not depend on OS
  usernames, personal paths, credentials, or machine sandbox configuration.

## Architecture baseline

The layered target architecture contains Domain Models, Application Services,
Ports, Adapters, and Interfaces. Domain records include Project Manifest,
Requirement, Acceptance Criterion, Milestone, Task, Agent Role, Tool
Definition, Evidence, Approval, Execution Attempt, Permission Request, Gate
Result, and Handoff. Ports isolate filesystem, Git, process, clock, browser,
search, and solver behavior.

Deterministic code owns schema validation, identifiers, Gate decisions, Git
boundaries, and approval checks. LLM output remains untrusted until validated.
Specification prose is data, not an instruction source. Missing executables,
sandbox denial, and network denial remain distinct capability states.

## Data contracts

Versioned machine-readable contracts must cover:

- Project Manifest: project identity, release level, source filename and
  digest, import time, platforms, UI presence, network policy, and API need.
- Requirement: stable ID, title, type, priority, status, source document and
  section, statement, acceptance criteria, verification methods, assumptions,
  and open questions. For example, `FR-REQ-001` may derive
  `AC-FR-REQ-001-01`.
- Evidence: evidence ID, claim IDs, type, status, command, environment, commit,
  artifacts, and recording time.
- Approval: approval ID, action, scope, risk, status, rationale,
  reversibility, expiry, and approver.
- Execution Attempt and Permission Request: task and command, working
  directory, normal result and denial class, approval type and exact scope,
  network, side effects, reversibility, Owner decision, approved retry result,
  and timestamp.
- Handoff, Tool Registry, and Agent Registry records needed by their
  corresponding functional requirements.

Schema inputs must be validated before adoption. Schema versions require a
migration policy.

## CLI target contract

The planned command surface is `doctor`, `init`, `ingest`, `validate`,
`roadmap`, `goal`, `prompt`, `status`, `gate`, `evidence add`, `handoff`,
`audit`, and `publish-check`. Commands support human-readable Markdown and
machine-readable JSON where applicable, use non-zero error exits, offer
`--dry-run` for external effects and `--json` for primary commands, suppress
absolute paths and secrets by default, and distinguish implemented, verified,
unverified, and blocked states.

## Quality Gates

- `Gate G0 - Bootstrap Safety`: parent non-Git, only `repo/` is the Git root,
  no private leakage, quality commands exist, observable Codex boundaries are
  recorded, denials are classified, approvals are minimal and separate, user
  settings are unchanged, and prohibited elevation is absent.
- `Gate G1 - Requirements Baseline`: Must requirements have stable IDs and
  acceptance criteria; ambiguity, open decisions, non-goals, and Owner
  approval state are recorded.
- `Gate G2 - Implementation Evidence`: requirement mapping, passing applicable
  tests, diff review, and explicit unverified items exist.
- `Gate G3 - Independent Review`: an independent review evaluates regression,
  security, and maintainability, and every critical finding is resolved or
  explicitly accepted.
- `Gate G4 - Release Candidate`: reproducible installation, verified Must
  requirements, secret/dependency/license/documentation audits, removal or
  rollback guidance, and a clean Git state are present.
- `Gate G5 - Public GitHub Release`: repository metadata and license are
  approved, the publishable diff and proposed English outbound content are
  reviewed, the Owner explicitly approves publication, and remote, branch,
  commit, and tag are verified.

Critical Must, security, data-loss, and disclosure failures are hard blockers.

## Milestone baseline

- `M0 Bootstrap Foundation`: create the tested, local-only repository
  foundation described below.
- `M1 Requirements and Planning MVP`: implement specification ingestion,
  source hashing and metadata, deterministic normalization contracts, stable
  IDs and priorities, acceptance criteria, ambiguity and open-decision
  detection, baseline comparison, end-to-end traceability, roadmap, living
  ExecPlan, Goal and Standard prompt generation, Goal suitability, and
  `Gate G1`.
- `M2 Agent, Skill, and Tool Orchestration`: implement registries, role
  selection, native Subagent use and fallback prompts, tool and Skill
  lifecycle, and worktree isolation.
- `M3 Evidence, UI/UX, and Release QA`: implement the Claim-Evidence Ledger,
  Gate Engine, browser validation loop, security/dependency/license audits,
  release-candidate audit, and automated handoff.
- `M4 Public Beta Hardening`: add multiple sample projects, cross-platform
  evidence, structured comparisons, schema migration, contributor workflow,
  and hardened public documentation.
- `V1.0`: satisfy Must requirements, validate primary flows in real projects,
  have no known critical defects, and complete public installation,
  extension, security, and release operations.

M1 must implement `FR-REQ-001` through `FR-REQ-012` and `FR-PLN-001` through
`FR-PLN-010` as its primary normative slice, while enforcing applicable
workspace, approval, quality, handoff, Git, and non-functional requirements.
M1 excludes M2 orchestration and M3 release automation.

## M0 scope

M0 establishes a safe, executable, tested repository foundation. It includes:

- Workspace and Git-boundary validation.
- Public English documentation and GitHub templates.
- A layered Python package and CLI vertical slice.
- Initial schemas, samples, registries, and Codex skills.
- Tests, linting, type checking, coverage, CI, and publication audits.
- Local-only Git initialization and a clean local commit.
- A complete M1 handoff prompt.

M0 excludes remote creation, push, GitHub posting, release publication, license
selection, production deployment, full orchestration, full UI automation, and
paid API use.

## M0 acceptance criteria

- `AC-M0-001`: Do not create `workspace-root/.git`.
- `AC-M0-002`: `repo/.git` exists and the default branch is `main`.
- `AC-M0-003`: No private file outside `repo/` is present in its Git index.
- `AC-M0-004`: `python -m pytest` passes.
- `AC-M0-005`: Lint and type checking pass.
- `AC-M0-006`: Critical coverage meets the provisional threshold or the
  shortfall is explicit.
- `AC-M0-007`: `doctor`, `validate`, `status`, and `goal-template` run against
  the samples.
- `AC-M0-008`: A Goal template contains Objective, Context, Constraints, Done
  when, Checkpoints, Stop conditions, Approval gates, Sandbox handling, and
  Language policy.
- `AC-M0-009`: Public specification, architecture, roadmap, release contract,
  and local permissions guidance exist in English.
- `AC-M0-010`: At least three valid repository Skills exist.
- `AC-M0-011`: README separates implemented from unimplemented scope.
- `AC-M0-012`: No remote creation, push, GitHub posting, or release occurs.
- `AC-M0-013`: A local commit exists and the worktree is clean.
- `AC-M0-014`: The recommended next-milestone prompt exists.
- `AC-M0-015`: License, public name, visibility, and other Owner decisions are
  listed.
- `AC-M0-016`: Python, Git, test, lint, and type-check commands run; evidence
  distinguishes normal execution, technical approval, Owner decision, retry,
  or the final blocked reason. Coverage and CLI smoke are also mandatory for
  the M0 execution contract.
- `AC-M0-017`: `doctor` distinguishes missing tools and permission denial and
  never infers absence from sandbox denial alone.
- `AC-M0-018`: Technical approvals are minimal and do not broadly authorize a
  tool family.
- `AC-M0-019`: No administrator shell, UAC bypass, unrestricted access, or
  sandbox-bypass flag is used.
- `AC-M0-020`: User Codex configuration, global instructions, GitHub
  authentication, and credential stores are neither changed nor needlessly
  inspected.
- `AC-M0-021`: Public files, code, comments, CLI output, tests, branch, commit,
  and GitHub templates are English.
- `AC-M0-022`: Repository instructions and the next prompt inherit language,
  denial handling, Owner approval, and no-full-access rules.
- `AC-M0-023`: The next prompt names `repo/` as the normal post-M0 Primary
  folder.

## Quality thresholds

M0 targets at least 80 percent total branch coverage and at least 90 percent for
core domain and gate logic. A critical security, data-loss, publication, or
Must-requirement failure is a hard blocker and cannot be offset by a score.

## Open decisions

The Owner must decide the final project and repository name, license, GitHub
visibility, package and CLI names, initial release level, required CI matrix,
external contribution policy, optional API extension scope, and whether a
future management UI is desired.
