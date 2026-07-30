# Release Contract

M4 implementation and validation do not themselves authorize a commit, push,
or public release. Separately Owner-approved finalization may commit and push
an inspected immutable private candidate; public release and every other
external action remain separately Owner-gated.

## Required local gates

Run these commands from the repository root with the isolated development
environment active:

```text
python -m pytest
python -m ruff check src tests scripts
python -m mypy src tests scripts
python -m coverage run -m pytest
python -m coverage report --fail-under=80
python -m coverage report --include="src/sdaqf/domain/models.py,src/sdaqf/domain/requirements.py,src/sdaqf/application/gates.py,src/sdaqf/application/approvals.py,src/sdaqf/application/baselines.py,src/sdaqf/application/comparison.py,src/sdaqf/application/planning.py,src/sdaqf/application/requirements.py,src/sdaqf/application/requirements_gate.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/orchestration.py,src/sdaqf/domain/tooling.py,src/sdaqf/adapters/process.py,src/sdaqf/application/orchestration.py,src/sdaqf/application/skills.py,src/sdaqf/application/tooling.py,src/sdaqf/application/checkpoints.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/quality.py,src/sdaqf/application/contracts.py,src/sdaqf/application/evidence.py,src/sdaqf/application/quality_gates.py,src/sdaqf/application/ui_validation.py,src/sdaqf/application/release_qa.py,src/sdaqf/application/handoffs.py" --fail-under=90
python -m coverage report --include="src/sdaqf/domain/evaluation.py,src/sdaqf/domain/migrations.py,src/sdaqf/application/evaluation.py,src/sdaqf/application/migrations.py" --fail-under=90
python scripts/run_cli_smoke.py
python -m sdaqf eval validate evals/comparison-suite.json --result evals/results/public-beta-comparison.json --json
python scripts/check_workspace_boundary.py --repo . --expected-origin-url https://github.com/guriguri215-lang/spec-driven-agent-framework.git
python scripts/audit_repository.py --root . --workspace-parent ..
python scripts/audit_dependencies.py --root .
python -m pip check
git diff --check
```

The complete pytest run is the schema/sample validation Gate. It also preserves
M0 and M1 CLI behavior, canonical specification ingestion, Requirements
Baseline counts and digest, and Gate G1. It validates M4 sample normalization,
paired comparison, non-compensating metrics, migrations, compatibility, and
public documentation. `scripts/run_cli_smoke.py` runs the
preserved `doctor`, `init`, `validate`, `status`, and `goal-template` commands;
the M1 `ingest`, `compare`, `roadmap`, `exec-plan`, `goal`, `prompt`, and
`gate requirements` commands; and the M2 `agents`, `skills`, `tools`, and
`checkpoint` primary paths. It also exercises M3 evidence validation, Gates G2
and G3, non-UI classification, handoff create/resume, a positive G4 path in a
temporary clean Git repository, and an explicit dirty-candidate negative path.
It also validates the tracked M4 evaluation result, calculates the comparison,
migrates a legacy Agent Registry to a new file, and validates the migrated
output through the current strict loader and companion Tool Registry. The
smoke supplies an exact generated single-use Owner migration-approval record
and exercises its atomic repository-local consumption claim; production
migration remains approval-bound.
The positive G4 fixture performs an actual `python -I -m pip --isolated`,
no-index, no-build-isolation, no-dependency target installation and executes
the installed module from that fresh target. It materializes only Git
publication files into a fresh owned source tree and includes ignored failing
`setup.py` and `pip.py` injections to prove that ignored worktree input is
neither built nor allowed to shadow the installer. Host
Git hooks, signing, attributes, excludes, file monitoring, and template input
are disabled for the owned fixture. The smoke also performs the canonical
ingest and Gate G1 offline in a temporary repository-local directory.

The repository audit uses Git's complete cached-plus-untracked publication set.
It checks secrets, email and personal paths in text and binary metadata,
English/CJK content, links and reparse ancestors, size, private/generated
state, and nested project-license filenames. The dependency audit verifies the
empty runtime dependency set, exact development pins, documented license
metadata, and absence of project-license filenames or metadata. `pip check`
verifies the installed dependency set. Gate G4 additionally requires all
declared release documents to be regular, unlinked, non-empty UTF-8 files and
members of the Git publication set, and requires README installation and
known-limitations sections.

## Continuous integration parity

Every Windows/Linux and Python 3.12/3.13 matrix job runs pytest, Ruff, strict
mypy, total and M1/M2 critical branch coverage, both repository audits, the Git
workspace boundary, installed dependency consistency, and the exact CLI smoke
script. Full pytest and smoke therefore exercise M4 on every existing matrix
job without a workflow change. The M3 and M4 critical thresholds are
additional local Gates; changing the GitHub workflow remains outside M4
authorization. CI uses only immutable pinned GitHub Action commits and installs
no runtime dependency.

Platform claims must come from `docs/evidence/M4-platform-evidence.json` and
bind to the exact M4 candidate. A prior M3 matrix does not verify M4. A remote
matrix claim requires a separately Owner-approved commit, normal push, and
exact-SHA Actions observation. macOS remains `NOT_VERIFIED` unless it is
actually run.

## Local commit gate

- Every required check passes without a threshold reduction or ignored
  failure.
- Independent read-only review returns GO with no unresolved Critical, High,
  or Medium finding.
- The staged names, status, stat, diff, and whitespace are reviewed
  explicitly.
- No secret, personal path, private state, link, generated cache, coverage
  output, temporary file, project license, or non-English GitHub-facing
  artifact is staged.
- The tracked evaluation result exactly reproduces from the suite and run
  records, retains its limits, and contains no aggregate score.
- Migration fixtures preserve their source and validate through the existing
  current-version loaders, the Agent/tool cross-reference, and an exact,
  time-bounded, atomically consumed single-use Owner approval.
- A post-link input-identity race returns a distinct indeterminate-publication
  failure, prohibits output use, and never auto-deletes the replaceable name.
- Runtime approval-consumption, M3 evidence, review, UI, trace, and handoff
  records under `.sdaqf/` remain repository-local ignored state and are never
  staged.
- The branch is `main`.
- The only remote is the approved `origin`; every fetch and push URL is the
  approved private repository.
- The commit message and repository-local author identity are non-personal
  English metadata.

## Private push and exact-SHA CI gate

Only an explicitly Owner-approved, inspected commit may be pushed normally to
the approved private `origin/main`. Force push, history rewrite, PRs, issues,
discussions, tags, releases, deployment, repository administration, secrets,
and runner changes remain prohibited.

After push, the observed workflow must have the exact local commit as its head
SHA and every required matrix job must succeed. A failure is diagnosed from
bounded logs before any retry. An in-scope fix receives focused tests, full
related Gates, read-only re-review, a new English commit, and a normal push.

## Public release gate

Publication is a separate future action. It requires Owner decisions for
visibility, description, license, default branch policy, initial tag, and
English outbound metadata. It also requires a fresh secret, personal-data,
dependency, license, language, advisory, and clean-environment audit.
