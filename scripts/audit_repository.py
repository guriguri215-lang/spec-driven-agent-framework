"""Audit the local repository candidate for publication safety."""

from __future__ import annotations

import argparse
from pathlib import Path

from sdaqf.adapters.process import SubprocessRunner
from sdaqf.application.contracts import ContractError
from sdaqf.application.release_qa import GitInspector, audit_repository
from sdaqf.application.release_qa import candidate_files as _candidate_files
from sdaqf.application.release_qa import is_link_or_reparse as _is_link_or_reparse

candidate_files = _candidate_files
is_link_or_reparse = _is_link_or_reparse


def audit(root: Path, workspace_parent: Path | None = None) -> tuple[str, ...]:
    """Return publication-safety findings without modifying files."""

    if (root / ".git").exists():
        try:
            git = GitInspector(
                SubprocessRunner(timeout_seconds=5, output_limit=1_048_576)
            ).inspect(root)
        except (ContractError, OSError):
            return ("Bounded Git publication-path inspection failed.",)
        return audit_repository(
            root,
            workspace_parent,
            publication_paths=git.publication_paths,
        )
    return audit_repository(root, workspace_parent)


def main() -> int:
    """Command entry point."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace-parent", type=Path)
    args = parser.parse_args()
    errors = audit(args.root, args.workspace_parent)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: publication candidate contains no detected boundary violation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
