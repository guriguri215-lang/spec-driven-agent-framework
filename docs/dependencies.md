# Dependency and License Record

## Runtime

M0 through M4 have no third-party runtime dependency. The application uses
only Python 3.12 standard-library modules. M4 adds no package to the
development lock.

## Development lock

`requirements-dev.lock` records the complete installed dependency set observed
for the M0 Windows validation environment. Direct development tools are:

| Package | Version | Purpose | License |
|---|---:|---|---|
| pytest | 9.1.1 | Test runner | MIT |
| Ruff | 0.16.0 | Lint | MIT |
| mypy | 2.3.0 | Static type check | MIT |
| Coverage.py | 7.15.2 | Branch coverage | Apache-2.0 |
| setuptools | 83.0.0 | Reproducible local build backend | MIT |

Transitive development-only packages are:

| Package | Version | Introduced by | License metadata |
|---|---:|---|---|
| ast-serialize | 0.6.0 | mypy | MIT |
| colorama | 0.4.6 | pytest on Windows | BSD |
| iniconfig | 2.3.0 | pytest | MIT |
| librt | 0.13.0 | mypy | MIT |
| mypy-extensions | 1.1.0 | mypy | MIT |
| packaging | 26.2 | pytest | Apache-2.0 OR BSD-2-Clause |
| pathspec | 1.1.1 | mypy | MPL-2.0 |
| pluggy | 1.6.0 | pytest | MIT |
| Pygments | 2.20.0 | pytest | BSD-2-Clause |
| typing-extensions | 4.16.0 | mypy | PSF-2.0 |

## CI actions

GitHub Actions are pinned to immutable commit identifiers:

| Action | Release | Commit | License |
|---|---:|---|---|
| actions/checkout | 6.1.0 | `d23441a48e516b6c34aea4fa41551a30e30af803` | MIT |
| actions/setup-python | 6.3.0 | `ece7cb06caefa5fff74198d8649806c4678c61a1` | MIT |

## Sources and verification

Versions were resolved from PyPI into the isolated M0 virtual environment on
2026-07-27 and then pinned. Direct-tool versions and licenses were checked
against the official PyPI project pages:

- `https://pypi.org/project/pytest/`
- `https://pypi.org/project/ruff/`
- `https://pypi.org/project/mypy/`
- `https://pypi.org/project/coverage/`
- `https://pypi.org/project/setuptools/`

Installed distribution metadata was inspected for the full transitive set.
Colorama and PathSpec licenses, which were not declared through the installed
`License-Expression` field, were checked on their official PyPI project pages.
The CI action releases and immutable commits were checked against their
official GitHub release pages and repositories on 2026-07-27:

- `https://github.com/actions/checkout/releases/tag/v6.1.0`
- `https://github.com/actions/setup-python/releases/tag/v6.3.0`

`python -m pip check` passed. No package is imported by the SDAQF runtime.
Network-backed vulnerability advisory status is `NOT VERIFIED`; repeat a
current advisory audit before public release.
