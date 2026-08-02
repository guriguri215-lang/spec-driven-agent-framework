# Mathematical Solver Framework

M7 adds a bounded, deterministic, offline mathematical-computation boundary.
It is evidence infrastructure for small finite-domain decisions and
optimization tasks; it is not a general-purpose solver host and does not turn
backend output into authority.

## Public artifacts

Four strict, immutable, content-addressed schema `1.0` artifacts are public:

- Solver Registry declares adapters, exact capabilities, limits, license, and
  provenance.
- Solver Request binds the Registry, operational contract, M5 candidate and
  Context Snapshot, M6 Task Graph and task, problem, required claim, exact-zero
  tolerance, and resource policy.
- Solver Result binds the Request, adapter, provenance, M6 Lease evidence,
  truthful disposition, witness or bound evidence, proof disposition, and
  measured resource use.
- Solver Verification independently reauthenticates those identities and
  re-evaluates the evidence before scheduler adoption.

Every artifact ID is the SHA-256 identity of canonical content. Objects reject
unknown fields; identifiers, arrays, finite integers, ordering, sizes, paths,
and cross-references are closed and bounded. M7 does not accept floating-point
tolerance, arbitrary callbacks, source expressions, shell text, or raw
agent-authored solver languages.

Sensitivity reuses the exact M5 vocabulary: `public`, `repository-private`,
`owner-private`, and `secret-or-prohibited`. No M7-only alias is accepted by
runtime or schema. M7 Task and host identifiers likewise reuse the exact M6
grammars and maximum lengths. Task IDs match
`^TSK-[A-Z0-9][A-Z0-9-]{0,63}$`; underscores are not permitted.
Repository-relative references reuse the exact M6 portable-path exclusions,
including Windows reserved names and trailing dots. Embedded Lease expiry
timestamps use the exact M6 RFC 3339 UTC `Z` grammar; equivalent offset aliases
are not schema `1.0` values.

## Problem contract

Schema `1.0` supports two problem kinds: `finite-domain-feasibility` and
`finite-domain-optimization`. The profiles are `general`, `boolean-sat`, and
`finite-scheduling`. The five typed constraints are `linear`,
`all-different`, `table`, `clause`, and `non-overlap`.

Every adapter declares `numeric_domain: exact-integer` and all D2 hard limits:
variables, values per domain, Cartesian search space, constraints, variables
per constraint, table rows, scalar range, and artifact bytes. The reference
values are respectively 16, 256, 1,000,000, 256, 16, 4,096,
`-1,000,000..1,000,000`, and 1,048,576. Request validation compares the actual
problem shape, scalar values, serialized Request size, and Result byte policy
with the selected adapter rather than only the global parser bounds. All
arithmetic, steps, and resource counters are exact bounded integers.
Variables, terms, constraints, assignments, references, checks, and reasons
have canonical ordering and uniqueness rules; table variable arrays are sorted
like every other identifier array and row columns follow that order.
Feasibility requests require the `decision` claim. Optimization requests use
`feasible`, `bounded`, or `optimal`.

## Adapters and external-tool boundary

`stdlib-finite-domain-v1` is mandatory. It is implemented with the Python
standard library, performs deterministic lexicographic complete-assignment
enumeration, uses exact integer arithmetic, never accesses the network, and
records Apache-2.0 provenance. It stops at the Request step limit, Request
timeout, or M6 Lease deadline.

An `external-cli` Registry entry is structural only in M7. It must be optional
and name an exact Tool Registry reference, tool, executable, input format,
version matcher, version-observation state and evidence, license, provenance,
`network: false`, and fresh Owner plus technical-sandbox approvals with
single-use atomic consumption. The public structural example records
`not-observed`; M7 never invokes that executable. Selecting such an adapter
therefore returns truthful `unavailable` evidence with zero solver calls and
steps. A future executable integration requires a new, separately approved
implementation boundary and fresh observations; the Registry entry alone is
not execution authority.

## Result and verification semantics

The closed Result dispositions are:

| Status | Evidence meaning | Verification/adoption rule |
| --- | --- | --- |
| `satisfiable` | feasible witness for a decision problem | independently re-evaluate; adopt only for `decision` |
| `unsatisfiable` | complete enumeration found no witness | independently repeat exhaustive proof |
| `feasible` | optimization witness, no optimality claim | re-evaluate witness and objective; adopt only for `feasible` |
| `infeasible` | complete enumeration found no optimization witness | verify proof; not enough for a positive optimization claim |
| `optimal` | witness and a singleton objective interval after complete enumeration | independently reproduce the optimum and tie-break |
| `bounded` | witness and directional objective interval from incomplete search | verify witness and bound; adopt only for `feasible` or `bounded` |
| `timeout` | Request or Lease deadline stopped work | `inconclusive`, never proof |
| `unavailable` | selected optional adapter cannot run | zero solver use, `inconclusive` |
| `unknown` | bounded step limit ended without a usable incumbent | `inconclusive`, never proof |
| `error` | a controlled adapter failure occurred | `inconclusive`, never proof |

An interrupted optimization may preserve a truthful incumbent, but its proof
disposition remains `none` and it cannot imply completeness. Backend agreement
is never a proof rule.

Verification is a separate application service. It reloads exact Request,
Registry, Task Graph, Result, current or historical M6 Lease and reservation
evidence; checks candidate, Context, task, contract, adapter, license,
provenance, sensitivity, witness feasibility, objective, bound, proof
disposition, and required claim. For the reference adapter it also replays the
canonical visited-assignment prefix and binds exact solver calls, steps,
constraint checks, termination reason, status, witness, objective, and proof
to that causal history. Verification measures the exact referenced raw Result
bytes, not a typed reserialization, and rejects a file above
`max_result_bytes` before mathematical replay. The same check runs during
current adoption, immutable-history validation, and fresh-output recovery.
That one replay is capped by
`max_verification_steps`; every independently evaluated assignment is reported
as one Verification step and settled through M6, with no hidden second pass.
Result `solver_steps` and visited assignments can never exceed
`max_solve_steps`; solve and Verification capacity remain separate limits and
cannot be pooled during adoption. Insufficient Verification capacity is
`inconclusive`. Non-timeout Results use canonical zero elapsed evidence, while
timeout elapsed evidence is observational and cannot be adopted. An external
adapter verifies only as truthful `unavailable` zero-use evidence. Its outcomes are `verified`,
`rejected`, and `inconclusive`. `adoption_allowed` is true only when the outcome
is `verified`, all checks pass, and the Result satisfies the Request's required
claim. A `rejected` Verification cannot back any successful or failed M6 Task
Result; failed tasks may report truthful `inconclusive` or
verified-but-claim-unsatisfied evidence without granting adoption.

## M5 and M6 integration

The operational contract has a stable content identity over Registry ID,
adapter, problem, required claim, exact tolerance, and resource policy. The
M6 required capability token includes that contract ID and the exact solve,
verification, and call reservations. A solver task dispatch reserves one
solver call and exactly `max_solve_steps + max_verification_steps`; it reserves
no tool call for the reference adapter. Before task-result adoption, the
current scheduler Task Graph identity, task ID, and unique M7 capability token
must match the Request and Lease exactly. Evidence for another Graph, task, or
operational contract cannot consume or settle the current task's authority.

`solver run` requires the exact current fenced Lease. The Result records the
dispatch and reservation evidence. `solver verify` may reauthenticate the same
Lease from the current projection or immutable Lease history. An M6 successful
Task Result for a solver task must reference exactly one Result and one
Verification, report their exact combined budget use and `effect_observed:
none`, and carry an adoptable Verification. Store validation and fresh-output
recovery replay those semantics rather than trusting the message text.

## CLI

The additive commands are:

```text
sdaqf solver registry validate REGISTRY --root ROOT --json
sdaqf solver request validate REQUEST --registry REGISTRY --task-graph TASK_GRAPH --root ROOT --json
sdaqf solver run REQUEST --registry REGISTRY --task-graph TASK_GRAPH --state STATE --root ROOT --host-id HOST --lease-id LEASE --output RESULT --json
sdaqf solver verify RESULT --request REQUEST --registry REGISTRY --task-graph TASK_GRAPH --state STATE --root ROOT --host-id HOST --lease-id LEASE --output VERIFICATION --json
```

Inputs are regular root-confined files. Every lexical input and output ancestor
is checked for a symbolic link or Windows reparse point before resolution.
Result and Verification publication is exclusive; existing output is never
overwritten. Publication-adapter failures stay inside the bounded CLI error
contract and do not disclose an absolute path.

## Validation and limits

Run the named offline validator from the repository root:

```text
python scripts/validate_m7_solver.py
```

`PASS: M7-SOLVER-EVIDENCE` validates all four public artifacts against runtime
and schema contracts, checks positive and negative schema/runtime parity,
reproduces the public proof, executes all ten statuses through production
services, adopts and recovers exact M6 evidence, validates the read-only Agent
Result, and preserves the empty runtime dependency and stable top-level export
boundaries. The focused M7 critical modules have at least 90 percent branch
coverage.

This evidence does not establish independent review, remote CI, arbitrary
problem scalability, third-party solver correctness, external-tool approval,
publication, or production readiness.
