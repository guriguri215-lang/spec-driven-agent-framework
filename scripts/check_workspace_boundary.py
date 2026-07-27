"""Verify that only the repository directory is a Git boundary."""

from __future__ import annotations

import argparse
import stat
import subprocess
from pathlib import Path

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def is_link_or_reparse(path: Path) -> bool:
    """Return true for symbolic links and Windows reparse points."""

    if path.is_symlink():
        return True
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & _REPARSE_POINT)


def git_output(repo: Path, *args: str) -> str:
    """Run a read-only Git query."""

    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Git query failed: {' '.join(args)}")
    return result.stdout.strip()


def resolve_workspace_parent(repo: Path, explicit: Path | None) -> Path:
    """Resolve the parent independently of relative-path spelling."""

    return explicit.resolve() if explicit is not None else repo.resolve().parent


def check_boundary(repo: Path, workspace_parent: Path | None = None) -> tuple[str, ...]:
    """Return boundary violations without modifying either directory."""

    errors: list[str] = []
    resolved_repo = repo.resolve()
    parent = resolve_workspace_parent(repo, workspace_parent)
    if not resolved_repo.is_dir() or is_link_or_reparse(repo):
        return ("Repository must be a regular directory.",)
    if (parent / ".git").exists():
        errors.append("The parent workspace must not contain .git.")
    if not (resolved_repo / ".git").is_dir():
        errors.append("The repository must contain .git.")
        return tuple(errors)

    try:
        git_root = Path(git_output(resolved_repo, "rev-parse", "--show-toplevel")).resolve()
        branch = git_output(resolved_repo, "branch", "--show-current")
        remotes = git_output(resolved_repo, "remote")
        index = git_output(resolved_repo, "ls-files", "--stage")
    except RuntimeError as exc:
        errors.append(str(exc))
        return tuple(errors)

    if git_root != resolved_repo:
        errors.append("Git root does not match the repository directory.")
    if branch != "main":
        errors.append("The current branch must be main.")
    if remotes:
        errors.append("M0 must not configure a Git remote.")
    if any(line.startswith("120000 ") for line in index.splitlines()):
        errors.append("Tracked symbolic links are not allowed in M0.")
    tracked_names = {
        line.split("\t", maxsplit=1)[1]
        for line in index.splitlines()
        if "\t" in line
    }
    forbidden = {"SPECIFICATION.md", "INITIAL_CODEX_GOAL_PROMPT.md", "state"}
    if any(name.split("/", maxsplit=1)[0] in forbidden for name in tracked_names):
        errors.append("A private parent-workspace path is tracked.")
    return tuple(errors)


def main() -> int:
    """Command entry point."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--workspace-parent", type=Path)
    args = parser.parse_args()
    errors = check_boundary(args.repo, args.workspace_parent)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS: repository and parent workspace Git boundaries are safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
