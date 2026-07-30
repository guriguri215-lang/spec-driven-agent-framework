# Comparative Evaluation

## Purpose

M4 adds a small, offline, reproducible evaluation suite for checking the
framework's normalization and comparison mechanics. It measures tracked paired
records; it is not a statistically powered benchmark and does not establish
that SDAQF caused an outcome.

The suite covers:

- an offline non-UI configuration validator;
- an offline UI issue tracker with accessibility and state requirements;
- an approval-bound export workflow with security and disclosure boundaries.

Each project contains the same task text for both workflow arms, its
specification, an expected normalized projection, one structured-SDAQF record,
and one ordinary-unstructured-Codex record.

## Input parity

The evaluator compares a pair only when all of these fields are exactly equal:

- project identifier;
- specification SHA-256;
- task SHA-256;
- starting repository digest;
- model identifier and client surface;
- platform and Python version;
- budget units;
- trial identifier.

The evaluator hashes the tracked specification, task, and exact per-arm
instruction artifact rather than trusting the run record. The intervention
must differ by content and remain explicit. Every evidence entry names a type,
status, observation timestamp, review command, safe relative artifact path,
and exact SHA-256. The evaluator resolves and hashes each tracked artifact
rather than accepting an opaque evidence identifier.

The paired fixtures use the exact M3 publication digest as their starting
repository identity. They are authored single-session scenario fixtures with
content-bound manual-review artifacts. They are not independently executed
Codex sessions and were not blinded, randomized, independently replicated, or
supplied with comparable per-arm token and elapsed-cost telemetry. They
exercise the comparison protocol and metric implementation; they do not
constitute an empirical model benchmark.

## Metrics

The deterministic result reports these measures for each workflow and project:

- missed requirements;
- scope additions;
- critical defects;
- rework events;
- approval count;
- failed handoffs;
- trace-step, decision, and evidence-item counts;
- cost values or an explicit `NOT_VERIFIED` cost record.

There is no aggregate quality score. A missed Must requirement, any recorded
security, Must, data-loss, or disclosure defect, and every `FAIL` or
`NOT_VERIFIED` evaluation-evidence item remains a named hard blocker. Version
1.0 has no evidence-bound critical-defect resolution contract, so a bare
`resolved` assertion cannot remove a recorded critical blocker. These blockers
cannot be offset by fewer tool calls, lower rework, another project's result,
or any average.

Repeated rework with the same failure signature requires a cause-analysis
record. That record selects one or more instruction, Skill, schema, test, or
implementation layers, names an owner and action, and links verification
evidence whose status is `PASS` when marked verified. An open cause analysis
remains a named hard
blocker.

## Fixture-derived result

The tracked deterministic result is
`evals/results/public-beta-comparison.json`.

| Project | Workflow | Missed | Scope additions | Critical defects | Rework | Approvals | Failed handoffs |
|---|---|---:|---:|---:|---:|---:|---:|
| offline configuration | structured | 0 | 0 | 0 | 0 | 0 | 0 |
| offline configuration | unstructured | 1 | 1 | 0 | 2 | 0 | 1 |
| secure export | structured | 0 | 0 | 0 | 0 | 1 | 0 |
| secure export | unstructured | 3 | 1 | 2 | 2 | 0 | 1 |
| UI issue tracker | structured | 0 | 0 | 0 | 1 | 0 | 0 |
| UI issue tracker | unstructured | 3 | 1 | 1 | 1 | 0 | 1 |

The result says only that the tracked content-bound scenario records and review
artifacts produce these metrics under the implemented protocol. It is not a
measurement of independent Codex executions and must not be generalized into a
model-quality, causal, security, cost, or production-readiness claim. An
empirical future evaluation should use independent sessions, immutable
deliverable snapshots, blind annotation, multiple seeds or repetitions, exact
model snapshots, and comparable cost telemetry.

## Reproduction

Run from the repository root:

```text
python -m sdaqf eval validate evals/comparison-suite.json --result evals/results/public-beta-comparison.json --json
python -m sdaqf eval compare evals/comparison-suite.json --json
```

The first command fails if any sample projection, input identity, run contract,
change-evaluation pair, or recorded result drifts. The second prints the
calculated result without writing a file.

## Before and after changes

A Skill, template, or prompt evaluation must name the changed artifact and
reference distinct before and after runs with the same input identity. Missing
arms or changed inputs fail closed. The artifact identifier binds the declared
artifact type to the exact before and after intervention SHA-256 values as
`TYPE:BEFORE_SHA256->AFTER_SHA256`; a descriptive but content-unbound name is
rejected. The M4 fixture records the evaluation protocol prompt intervention.
It does not claim a general prompt benchmark. Its Markdown review artifacts
are classified as manual or source review evidence, never as executed tests.
