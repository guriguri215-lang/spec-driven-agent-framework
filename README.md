# SDAQF

[![Continuous integration](https://github.com/guriguri215-lang/spec-driven-agent-framework/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/guriguri215-lang/spec-driven-agent-framework/actions/workflows/ci.yml)

SDAQF is an offline-first Python CLI that turns Markdown specifications and
versioned JSON records into validated requirements, plans, evidence gates,
context snapshots, host-execution intents, and bounded finite-domain solver
results for Codex-assisted software projects.

> **Status: experimental reference implementation.** The
> [`v1.0.0-rc.1`](https://github.com/guriguri215-lang/spec-driven-agent-framework/releases/tag/v1.0.0-rc.1)
> prerelease contains the M0-M4 baseline. The current `main` branch adds the
> M5-M8 context, scheduling, solver, and integrated workflow frameworks; all
> four remain Experimental and unreleased. The current dispositions are
> independent: M5 GO, M6 GO, M7 GO, and M8 successor lifecycle GO. The latest
> M8 successor lifecycle compatibility review maintained F1 through F11 and
> left zero unresolved scope findings. The reviewed M6 state completed pull
> request #4: exact-head
> [run 31558960113](https://github.com/guriguri215-lang/spec-driven-agent-framework/actions/runs/31558960113)
> and post-merge `main`
> [run 31563987706](https://github.com/guriguri215-lang/spec-driven-agent-framework/actions/runs/31563987706)
> passed on Windows/Linux and Python 3.12/3.13. Historical M5/M6 NO-GO records
> remain preserved. These dispositions and CI results do not establish release GO
> or production readiness; the project is not production-ready, and
> macOS is not verified.

## Why SDAQF

AI-assisted development can lose the connection between an original
specification, the plan produced from it, approvals for side effects, evidence
from implementation, and the state handed to another session. SDAQF makes
those boundaries explicit with strict schemas and deterministic local checks.

The intended users are framework evaluators and advanced Codex users who want
reviewable artifacts and fail-closed quality gates around an agent-assisted
workflow. It is not an autonomous coding product or an LLM runtime.

## What it does

| Capability | Current state | Evidence |
|---|---|---|
| Specification ingestion, requirement normalization, change comparison, plans, and prompts | Implemented | `src/sdaqf/application/requirements.py`, `planning.py`, M1 tests |
| Agent/tool registries, bounded role selection, approvals, checkpoints, and handoff contracts | Implemented | `src/sdaqf/application/orchestration.py`, `tooling.py`, M2/M3 tests |
| Claim-evidence, review, UI-observation, and local release-quality gates | Implemented | `src/sdaqf/application/quality_gates.py`, `release_qa.py`, M3 tests |
| Deterministic context indexing, selection, snapshots, and extractive compaction | Experimental | [Context Framework](docs/context-framework.md), M5 tests and validator |
| Durable SQLite scheduling, leases, mailboxes, budgets, recovery, and simulations | Experimental | [Multi-Agent Control Framework](docs/multi-agent-control-framework.md), M6 tests and validator |
| Exact-integer finite-domain feasibility and optimization with independent result verification | Experimental | [Mathematical Solver Framework](docs/mathematical-solver-framework.md), M7 tests and validator |
| Deterministic integrated planning, immutable workflow projections, recovery, Outcomes, and offline simulation | Experimental | [Integrated Vibe-Coding Framework](docs/integrated-vibe-coding-framework.md), M8 tests and validator |

See [Implementation status](docs/implementation-status.md) for the detailed
milestone inventory, validation boundaries, and the distinction between code
presence and independent verification.

## What it does not do

- It does not call an LLM, the OpenAI API, the Agents SDK, or a hosted service.
- It does not launch Codex sessions, agents, browsers, or Git worktrees. It
  validates records and emits bounded instructions or intents for a host.
- It does not grant approvals, publish releases, push Git changes, or retry an
  ambiguous external effect automatically.
- It does not provide a web or desktop UI.
- It does not execute third-party solvers. The only executable solver is the
  dependency-free bounded reference adapter.
- It does not establish production security, correctness for arbitrary inputs,
  or general natural-language understanding.

## How it works

```mermaid
flowchart LR
    A["Markdown specification and versioned JSON"] --> B["SDAQF CLI"]
    B --> C["Strict schema and policy validation"]
    C --> D["Requirements, plans, context, evidence, and solver artifacts"]
    C --> E["Quality-gate results and scheduler intents"]
    E --> F["Human-approved host actions"]
    F --> G["Observed results returned as untrusted records"]
    G --> C
```

Responsibility is deliberately split:

| Actor | Responsibility |
|---|---|
| SDAQF's Python runtime | Deterministic parsing, validation, comparison, selection, state transitions, local simulation, and bounded reference solving |
| AI agent or LLM | Optional external proposal generation and implementation; its output remains untrusted input to SDAQF |
| Human or host | Approvals, session dispatch, worktree operations, browser observations, GitHub actions, publication, and other side effects |

The package is layered into domain records, application services, external
ports, local adapters, and the CLI. See [Architecture](docs/architecture.md)
for the complete flow and trust boundaries.

## Requirements

| Requirement | Supported state |
|---|---|
| Python | 3.12 or 3.13 |
| Operating systems | Windows and Linux verified in CI; macOS not verified |
| Runtime dependencies | None outside the Python standard library |
| Development tools | Exact versions in `requirements-dev.lock` |
| Git | Required by candidate-bound and repository-inspection operations |
| GitHub CLI and browser | Optional host capabilities; not required by the offline core |
| API keys, model provider, GPU, paid service | Not required |

The repository is distributed as source. There is no package-registry
publication or attached release asset.

## Quickstart

Clone the repository and create an isolated environment.

### Windows PowerShell

```powershell
git clone https://github.com/guriguri215-lang/spec-driven-agent-framework.git
cd spec-driven-agent-framework
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip --isolated install -r requirements-dev.lock
.\.venv\Scripts\python -m pip --isolated install --no-build-isolation --no-deps -e .
.\.venv\Scripts\python -m sdaqf validate examples/sample-project
```

### POSIX shell

```bash
git clone https://github.com/guriguri215-lang/spec-driven-agent-framework.git
cd spec-driven-agent-framework
python3.12 -m venv .venv
.venv/bin/python -m pip --isolated install -r requirements-dev.lock
.venv/bin/python -m pip --isolated install --no-build-isolation --no-deps -e .
.venv/bin/python -m sdaqf validate examples/sample-project
```

Expected result:

```text
valid: True
errors: []
files_checked: ['manifest.json', 'requirements.json', 'evidence.json', 'approval.json', 'execution-attempt.json', 'handoff.json', 'tool-registry.json', 'agent-registry.json']
```

Then inspect the available command groups:

```text
python -m sdaqf --help
```

## Minimal examples

### Turn a specification into a requirement baseline

The first command writes a new file and refuses to overwrite an existing one.

```text
python -m sdaqf ingest examples/sample-specification.md --output baseline.json
python -m sdaqf gate requirements baseline.json --json
```

### Plan bounded agent roles

This validates registries and returns assignments and host prompts. It does not
launch any agent.

```text
python -m sdaqf agents plan examples/m2-orchestration/orchestration-request.json --registry examples/m2-orchestration/agent-registry.json --tools examples/m2-orchestration/tool-registry.json --json
```

### Validate a context artifact

```text
python -m sdaqf context validate examples/m5-context/context-snapshot.json --json
```

The scheduler and solver require exact candidate, task, lease, budget, and
artifact identities. Use their complete guides rather than copying partial
commands:

- [Multi-Agent Control Framework](docs/multi-agent-control-framework.md)
- [Mathematical Solver Framework](docs/mathematical-solver-framework.md)
- [Integrated Vibe-Coding Framework](docs/integrated-vibe-coding-framework.md)

### Plan and inspect an integrated workflow

The public M8 files are structural synthetic examples. A runnable Plan must
reference exact current requirements, Context, Registry, Task Graph, and any
Solver Request bytes under the supplied root.

```text
python -m sdaqf workflow validate examples/m8-workflow/development-intent.json --json
python -m sdaqf agents schedule init examples/m6-scheduler/task-graph.json --root . --state workflow/m8.sqlite3 --workflow-authority --json
python -m sdaqf workflow plan examples/m8-workflow/development-intent.json --root . --scheduler-state workflow/m8.sqlite3 --output workflow/plan.json --json
python -m sdaqf workflow simulate workflow/plan.json --root . --scheduler-state workflow/m8.sqlite3 --scenario ui-observation-unavailable --json
```

For an all-present predecessor lineage, planning uses two distinct databases:

```text
python -m sdaqf workflow plan INTENT --root ROOT --scheduler-state SUCCESSOR_DB --predecessor-scheduler-state PREDECESSOR_DB --output PLAN --json
python -m sdaqf workflow explain PLAN --root ROOT --scheduler-state SUCCESSOR_DB --predecessor-scheduler-state PREDECESSOR_DB --json
python -m sdaqf workflow simulate PLAN --root ROOT --scheduler-state SUCCESSOR_DB --predecessor-scheduler-state PREDECESSOR_DB --scenario ui-observation-unavailable --json
python -m sdaqf workflow run PLAN --root ROOT --scheduler-state SUCCESSOR_DB --predecessor-scheduler-state PREDECESSOR_DB --output-state STATE --output-event EVENT --json
python -m sdaqf workflow resume STATE --plan PLAN --root ROOT --scheduler-state SUCCESSOR_DB --predecessor-scheduler-state PREDECESSOR_DB --output-state NEXT_STATE --output-event NEXT_EVENT --json
python -m sdaqf workflow status STATE --plan PLAN --root ROOT --scheduler-state SUCCESSOR_DB --predecessor-scheduler-state PREDECESSOR_DB --json
python -m sdaqf workflow recover STATE --plan PLAN --root ROOT --scheduler-state SUCCESSOR_DB --predecessor-scheduler-state PREDECESSOR_DB --output-state RECOVERED_STATE --output-event RECOVERY_EVENT --json
```

The predecessor flag is forbidden when all predecessor fields are null and is
required when they are all present for plan, explain, simulate, run, resume,
status, and recover. It remains optional for backward-compatible genesis calls.

Plan, explanation, and simulation authenticate the same M6 v2 workflow
authority. Simulation uses a fresh isolated v2 store after authentication.
Planning, explanation, simulation, Outcome, and generated handoff content do
not dispatch a host action.

## Use cases

- Convert a bounded software specification into traceable requirement records,
  acceptance criteria, plans, and prompts.
- Validate agent/tool registries and prepare a deterministic host execution
  plan with explicit approval and reviewer-separation rules.
- Build reproducible, provenance-bound context selections and snapshots from
  explicit repository sources.
- Simulate and inspect host-agnostic multi-agent scheduling failure modes
  without launching agents.
- Solve and independently verify small exact-integer finite-domain feasibility
  or optimization requests with the reference adapter.
- Validate and explain one exact cross-framework Plan, project native M6 truth
  into immutable workflow records, and exercise recovery paths offline without
  launching a host.

## Validation and evidence

The current repository contains positive, negative, boundary, corruption,
recovery, and CLI tests. Passing tests support only the documented contracts;
they do not prove production readiness or correctness outside the bounded
input models.

| Check | Current evidence |
|---|---|
| Automated tests | The latest M6 schema remediation passes 65 public-contract tests and 145 related M6 contract/public/migration tests. The prior M8 review passed 28 focused compatibility/CLI tests, 120 complete M8 tests, and 9 round-three regression tests; it did not rerun full pytest. The recorded 87-test M5, 102-test M6, 14-test integration, and 1,241-test full-run results remain historical evidence |
| Pull request #5 merged-state CI | [Run 31594557932](https://github.com/guriguri215-lang/spec-driven-agent-framework/actions/runs/31594557932) passed the exact pull request #5 merge-commit state on Windows/Linux and Python 3.12/3.13 after exact-head run `31586128196` passed the same matrix |
| Static checks | That exact pull request #5 merged state passes Ruff and strict mypy |
| Coverage | That exact pull request #5 merged state passes the project and M1-through-M8 critical coverage thresholds |
| Named validators | M5 context integrity, M6 scheduler safety, M7 solver evidence, and M8 workflow integration pass for that exact pull request #5 merged state |
| CLI smoke | The offline M0-through-M8 smoke passes for that exact pull request #5 merged state without network access or persistent Git configuration changes |
| Independent review | The historical M5 and M6 final NO-GO reviews remain recorded. The latest M5 disposition is GO for the reviewed repository state; three fresh independent reviewers ACCEPTED the M6 remediation with no unresolved Critical, High, or Medium finding, and that state was merged by pull request #4; M7 and M8 retain their separate GO dispositions |
| External validation | No independent production deployment, macOS run, hosted-agent evaluation, or third-party solver validation |

The exact local gate commands are in the
[Release Contract](docs/release-contract.md). Historical and milestone-specific
evidence is under `docs/evidence/` and `docs/exec-plans/`.

## Limitations

- The release is a prerelease and the post-RC M5-M8 changes on `main` are
  unreleased.
- The M6 scheduler provides durable state and host intents, not an agent
  runtime; delivery is at-least-once and exactly-once execution is not claimed.
- Context selection is deterministic lexical and graph retrieval, not semantic
  embedding search or model-based ranking.
- The reference solver enumerates bounded finite domains and is unsuitable for
  large or continuous problems. External solver entries are descriptive only.
- Model-generated, browser-generated, tool-generated, and solver-generated
  records remain untrusted until their applicable validators pass.
- Scalability is bounded by explicit input, byte, graph, scheduler, and solver
  limits; this repository does not publish throughput or latency guarantees.
- No security audit or independent production validation has been performed.
- APIs outside the documented CLI, JSON schemas, and `sdaqf.__all__` are
  internal and may change during the prerelease.

## Project structure

| Path | Purpose |
|---|---|
| `src/sdaqf/` | Runtime package and CLI |
| `schemas/` | Versioned public JSON schemas |
| `examples/` | Synthetic valid inputs and representative artifacts |
| `tests/` | Contract, boundary, regression, corruption, and CLI tests |
| `scripts/` | Release checks, audits, smoke tests, and named validators |
| `docs/` | Architecture, contracts, guides, evidence, and milestone plans |
| `evals/` | Bounded authored evaluation fixtures and results |
| `.agents/skills/` | Repository-local Codex skills |

## Documentation

- [Implementation status](docs/implementation-status.md)
- [Architecture](docs/architecture.md)
- [Public specification](docs/specification.md)
- [Roadmap](docs/roadmap.md)
- [Compatibility and migration](docs/compatibility.md)
- [Context Framework](docs/context-framework.md)
- [Multi-Agent Control Framework](docs/multi-agent-control-framework.md)
- [Mathematical Solver Framework](docs/mathematical-solver-framework.md)
- [Release Contract](docs/release-contract.md)
- [Dependency and license record](docs/dependencies.md)

## Roadmap

M0-M4 form the published release-candidate baseline. M5-M8 are implemented on
`main` with the validation qualifications above. M8 composes the existing
contracts without bypassing their validators and remains experimental and
unreleased. Its latest successor lifecycle compatibility review is GO for the
reviewed M8 state. The historical M5 and M6 NO-GO reviews remain recorded and
do not revise the M7 or M8 dispositions. The latest M5 and M6 dispositions are
GO. The current dispositions are independent: M5 GO, M6 GO, M7 GO, and M8
successor lifecycle GO. Release GO, production readiness, version, tag, release,
and deployment remain separately gated. See the
[Roadmap](docs/roadmap.md) for scope, exclusions, risks, and completion criteria.

## Contributing, security, and support

The repository is public, but external pull requests are not accepted during
the release-candidate phase. Bug and documentation issues are handled on a
best-effort basis. See [Contributing](CONTRIBUTING.md) and the
[Contributor Guide](docs/contributor-guide.md).

Do not disclose suspected vulnerabilities in public issues. Use GitHub private
vulnerability reporting as described in [Security](SECURITY.md). Support has
no SLA; see [Support](SUPPORT.md).

## License

SDAQF is licensed under Apache License 2.0. Copyright 2026
`guriguri215-lang`. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
