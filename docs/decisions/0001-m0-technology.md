# ADR 0001: M0 Technology Baseline

- Status: Accepted for M0
- Date: 2026-07-27

## Decision

Use Python 3.12 or newer, `argparse`, dataclasses, JSON, pathlib, and subprocess
from the standard library. M0 has no runtime dependency.

Use isolated, exactly pinned development tools:

- pytest 9.1.1 for tests, MIT license.
- Ruff 0.16.0 for linting, MIT license.
- mypy 2.3.0 for static type checking, MIT license.
- Coverage.py 7.15.2 for branch coverage, Apache-2.0 license.
- setuptools 83.0.0 as the pinned build backend, MIT license.

The versions and license metadata were checked on their official PyPI project
pages on 2026-07-27. `requirements-dev.lock` is the reproducible local and CI
input. Installation scripts and global installation are not used.

## Rationale

Standard-library runtime code minimizes supply-chain and offline risks. The
four development tools directly satisfy the M0 quality contract and support
Python 3.12 on Windows and Linux.

## Consequences

M0 validation is intentionally smaller than a full JSON Schema implementation.
A production schema library may be proposed in M1, but adding a runtime
dependency requires a separate Owner decision.
