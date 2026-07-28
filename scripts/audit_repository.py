"""Audit the local repository candidate for publication safety."""

from __future__ import annotations

import argparse
import re
import stat
from pathlib import Path

_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".coverage",
    "__pycache__",
    ".pytest_cache",
    ".pytest-tmp",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
}
_TEXT_SUFFIXES = {
    "",
    ".json",
    ".lock",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yml",
    ".yaml",
}
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
_PERSONAL_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]\x55sers[\\/]|/\x55sers/|/\x68ome/[^/\s]+/)",
    re.IGNORECASE,
)
_SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def candidate_files(root: Path) -> tuple[Path, ...]:
    """Return non-generated regular candidate files."""

    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in _EXCLUDED_PARTS for part in path.relative_to(root).parts):
            continue
        if path.is_file() or path.is_symlink():
            files.append(path)
    return tuple(sorted(files))


def is_link_or_reparse(path: Path) -> bool:
    """Return true for a symbolic link or Windows reparse point."""

    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & _REPARSE_POINT)


def audit(root: Path, workspace_parent: Path | None = None) -> tuple[str, ...]:
    """Return publication-safety findings without modifying files."""

    errors: list[str] = []
    if not root.is_dir() or is_link_or_reparse(root):
        return ("Repository root must be a regular directory.",)
    if (root / "LICENSE").exists():
        errors.append("LICENSE must not exist before the Owner selects a license.")
    parent = workspace_parent.resolve() if workspace_parent else root.resolve().parent
    if (parent / ".git").exists():
        errors.append("The parent workspace must not contain .git.")

    for path in candidate_files(root):
        relative = path.relative_to(root).as_posix()
        if is_link_or_reparse(path):
            errors.append(f"{relative}: links and reparse points are not allowed.")
            continue
        if path.stat().st_size > 1_000_000:
            errors.append(f"{relative}: file exceeds the M0 size limit.")
            continue
        if path.suffix.casefold() not in _TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append(f"{relative}: text file is not valid UTF-8.")
            continue
        if _CJK.search(text):
            errors.append(f"{relative}: contains non-English CJK text.")
        if _PERSONAL_PATH.search(text):
            errors.append(f"{relative}: contains a personal absolute path.")
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            errors.append(f"{relative}: contains a possible secret.")
    return tuple(errors)


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
