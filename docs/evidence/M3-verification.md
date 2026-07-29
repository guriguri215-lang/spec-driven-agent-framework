# M3 Verification Evidence

## Scope and starting state

- Milestone: M3 Evidence, UI/UX, and Release QA only.
- Primary folder and Git root: `repo/`.
- Starting and current branch: `main`.
- Starting and current HEAD:
  `9421661343809d95affbcd5a97d0d7fca3b7f690`.
- Starting worktree: clean.
- Current worktree: intentionally dirty with the uncommitted M3 implementation.
- Canonical public specification SHA-256:
  `89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5`.

Before implementation, the complete repository instructions, approved
specification, roadmap, Release Contract, architecture, M2 verification
evidence, and M2 living ExecPlan were read. The branch, exact starting HEAD,
clean state, workspace boundary, and M0 through M2 local Gates were confirmed
read-only.

M3 did not inspect GitHub authentication, private repository metadata, remote
HEAD, or Actions. It did not commit, push, publish, deploy, create a tag, PR,
issue, or discussion, change repository settings, select a project license, or
add a production dependency.

## Delivered behavior

M3 provides immutable and bounded Claim-Evidence Ledger, evidence-addition,
independent-review, finding-acceptance, UI-validation, release-candidate, and
automated-handoff contracts. Strict offline loaders reject duplicate keys,
excessive size or depth, unsupported numbers, links, reparse points, traversal,
changing input, and schema drift. Evidence addition uses locked,
exclusive-create, atomic publication and validates both the existing ledger
and proposed record before mutation.

Gates G2 and G3 bind all claims, evidence, reviews, approvals, the source
specification, Git HEAD, and the repository publication digest to one candidate
identity. Review independence, acceptance ownership and expiry, artifact
content, command identity, and unresolved finding severity are fail-closed.

UI projects require a bounded Design Brief, structured browser execution trace,
supported browser/executable/version binding, required states and viewports,
keyboard and focus checks, readability, contrast, information structure,
efficiency, offline and recovery checks, and a valid bounded PNG screenshot.
Non-UI classification is deterministic and does not create a false UI pass.

Gate G4 is non-compensating. It requires G2, G3, UI applicability, a clean exact
Git candidate, required published documentation, security and
dependency/license audits, and reproducible installation evidence. The install
uses an exact `python -I -m pip --isolated` command with no index, build
isolation, or dependencies. It installs only a fresh source tree materialized
from Git publication files, verifies exact path-and-byte parity, executes the
installed module from a fresh target, records a bounded trace, and rolls back
only generated materialization output during smoke. The release candidate
records exact rollback guidance naming only the two owned install and source
paths. Actual smoke failure injection proves ignored
`setup.py`, ambient `pip.py`, and `PYTHONPATH` installer shadows cannot enter or
take over the candidate.

The automated handoff records candidate, Git, and baseline identity; branch,
HEAD, and worktree state; completed and incomplete work; evidence identifiers;
open decisions; known problems; recommended next work; the primary folder;
approval stops; prompt context; and resume checks without claiming unobserved
completion.

## Local command evidence

| Check | Exact command or contract | Result |
|---|---|---|
| Negative, boundary, failure-injection, and regression tests | `python -m coverage run -m pytest` | PASS, 523 passed and one environment skip |
| Lint | `python -m ruff check src tests scripts` | PASS |
| Strict typing | `python -m mypy src tests scripts` | PASS, 87 source files |
| Total branch coverage | `python -m coverage report --fail-under=80` | PASS, 91 percent |
| Critical M1 branch coverage | Release Contract M1 include command | PASS, 94 percent |
| Critical M2 branch coverage | Release Contract M2 include command | PASS, 90 percent |
| Critical M3 branch coverage | Release Contract M3 include command | PASS, 91 percent |
| M0 through M3 CLI smoke | `python scripts/run_cli_smoke.py` | PASS |
| Canonical M1 and Gate G1 | canonical ingest and Requirements Gate inside CLI smoke | PASS |
| Schema and sample parity | complete pytest public-contract and strict-loader tests | PASS |
| Git and workspace boundary | Release Contract exact local-origin boundary command | PASS |
| Publication, secret, path, language, link, generated-state, and license audit | `python scripts/audit_repository.py --root . --workspace-parent ..` | PASS |
| Runtime, lock, dependency-license, and project-license audit | `python scripts/audit_dependencies.py --root .` | PASS |
| Installed dependency consistency | `python -m pip check` | PASS |
| Patch whitespace | `git diff --check` | PASS |

The skipped test attempts to create a real symbolic link, which is unavailable
in this Windows environment. Simulated Windows reparse-point rejection,
artifact-ancestor rejection, and every other link boundary test pass. No
threshold, assertion, prior Gate, approval invariant, legacy schema, canonical
digest, or CI workflow was weakened.

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| `AC-M3-001` | PASS | bounded regular unlinked ledger loading, strict contracts, candidate binding, and mutation tests |
| `AC-M3-002` | PASS | complete evidence provenance, environment, command, commit, digest, artifact, confidence, and timestamp validation |
| `AC-M3-003` | PASS | locked validation-before-write, exclusive creation, concurrent-writer, failure-injection, and atomic rollback tests |
| `AC-M3-004` | PASS | G2 Must and acceptance mapping, evidence status, artifact content, command, environment, identity, and stale-evidence blockers |
| `AC-M3-005` | PASS | G3 logical independence, read-only scope, severity, conformance, diff, finding acceptance, owner, and expiry blockers |
| `AC-M3-006` | PASS | deterministic UI/non-UI manifest classification and disagreement rejection |
| `AC-M3-007` | PASS | Design Brief, flow/state/device, accessibility, offline/recovery, browser execution, PNG, and failure-path tests |
| `AC-M3-008` | PASS | non-compensating G4, direct Git observation, publication-only isolated install, documentation, audit, and dirty-candidate blockers |
| `AC-M3-009` | PASS | truthful bounded handoff creation and exact resume identity verification |
| `AC-M3-010` | PASS | M3 schema/sample parity and bounded offline primary CLI paths |
| `AC-M3-011` | PASS | complete M0 through M2 regression suite, canonical digest, Gate G1, legacy CLI/schema, and approval-security tests |
| `AC-M3-012` | PASS | empty runtime dependency set, no project license, all local Gates, and independent final review GO |

The repository itself remains dirty because M3 is intentionally uncommitted.
Therefore a G4 evaluation of the current repository correctly fails closed with
the Git candidate blocker. The actual-install positive G4 path passes in an
owned clean temporary Git repository containing the exact publication set;
the current repository can only become an exact clean G4 candidate after a
separately Owner-approved commit.

## Independent review

Final status: `GO`, with zero unresolved Critical, High, or Medium findings.

The first independent read-only review returned NO-GO with four High and eight
Medium findings. Candidate identity, artifact integrity, review approvals, Git
observation, UI proof, repository audits, bounded input, publication-source
installation, and failure paths were hardened in response. A later review
identified one High because installation from the worktree could consume
ignored build input; materialization was restricted to the exact Git
publication set. The next review identified one High because `python -m pip`
could be shadowed before pip's own isolation applied; Python isolated mode and
actual ambient-shadow injection were added. The final reviewer inspected the
complete resulting diff and returned GO with no remaining Critical, High, or
Medium finding.

## Residual, unverified, and deferred work

- Windows and Python 3.12 are verified locally.
- Linux, Python 3.13, macOS, and the remote Actions matrix are `NOT VERIFIED`
  for this uncommitted M3 candidate.
- A positive live in-app browser run and screenshot are `NOT VERIFIED` because
  the browser safety boundary rejected local `file://` navigation. The offline
  UI validator's positive PNG/trace path is fixture-tested, and the public
  sample fails closed rather than presenting simulated evidence as observed.
- Real symbolic-link creation on this Windows host is `NOT VERIFIED`; one test
  is skipped and simulated reparse/link cases pass.
- Network-backed vulnerability advisory state is `NOT VERIFIED`; the runtime
  dependency set is empty.
- GitHub authentication, private repository metadata, remote HEAD, and Actions
  were not inspected.
- No implementation deviation expands beyond M3. Gate G5, schema migrations,
  project-license selection, release publication, deployment, and later
  evaluation work remain M4 or later.

No Owner approval was consumed. A future commit requires approval for the exact
M3 path set and command. A future push and exact-SHA Actions observation require
separate approval for the exact private `origin/main`, followed by read-only
verification of private metadata, remote HEAD, and the Windows/Linux Python
3.12/3.13 matrix. Force push and history rewrite remain prohibited.
