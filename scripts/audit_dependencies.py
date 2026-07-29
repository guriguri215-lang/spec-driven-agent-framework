"""Audit the empty runtime dependency and documented development lock contract."""

from __future__ import annotations

import argparse
from pathlib import Path

from sdaqf.application.release_qa import audit_dependencies as _audit_dependencies

audit_dependencies = _audit_dependencies


def main() -> int:
    """Command entry point."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    errors = audit_dependencies(args.root)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: runtime, development dependency, and license records are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
