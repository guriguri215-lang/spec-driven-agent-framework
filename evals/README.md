# Evaluation Fixtures

M4 provides three paired public-beta fixture projects:

- `offline-config`: a non-UI offline command-line validator;
- `ui-issue-tracker`: a local UI workflow with required states and
  accessibility behavior;
- `secure-export`: an approval, containment, security, and disclosure-sensitive
  command.

Each project contains a specification, the same bounded task for both workflow
arms, an expected deterministic normalization projection, a structured-SDAQF
run record, and an ordinary-unstructured-Codex run record. The suite validates
input parity and the exact per-arm instruction digests, measures missed
requirements, scope additions, critical defects, rework, approvals, and failed
handoffs, and retains trace, decisions, content-bound evidence artifacts, and
cost availability.

The results are authored single-session scenario fixtures, not independently
executed Codex sessions or a blinded or statistically powered benchmark. See
`docs/evaluation.md` for the protocol, fixture-derived result, and limits.

Run:

```text
python -m sdaqf eval validate evals/comparison-suite.json --result evals/results/public-beta-comparison.json --json
python -m sdaqf eval compare evals/comparison-suite.json --json
```

`fixtures/manifest-missing-id.json` remains the preserved M0 invalid-manifest
fixture.
