"""Audit the empty runtime dependency and documented development lock contract."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path
from typing import cast

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+-]*)$")


def audit_dependencies(root: Path) -> tuple[str, ...]:
    """Return dependency and license-record violations."""

    errors: list[str] = []
    pyproject_path = root / "pyproject.toml"
    lock_path = root / "requirements-dev.lock"
    record_path = root / "docs" / "dependencies.md"
    if not pyproject_path.is_file() or not lock_path.is_file() or not record_path.is_file():
        return ("Dependency contract files are missing.",)
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        lock_lines = tuple(
            line.strip()
            for line in lock_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        record = record_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return ("Dependency contract files are unreadable or invalid.",)
    project = cast(dict[str, object], pyproject.get("project", {}))
    if project.get("dependencies") != []:
        errors.append("Runtime dependencies must remain empty.")
    if not lock_lines:
        errors.append("The development lock must not be empty.")
    packages: list[str] = []
    for line in lock_lines:
        match = _PIN.fullmatch(line)
        if match is None:
            errors.append("Every development dependency must use an exact version pin.")
            continue
        packages.append(match.group(1).casefold().replace("_", "-"))
    if len(packages) != len(set(packages)):
        errors.append("Development dependency names must be unique.")
    folded_record = record.casefold().replace("_", "-")
    for package in sorted(set(packages)):
        if package not in folded_record:
            errors.append(f"Dependency license record is missing: {package}.")
    if "license" not in folded_record:
        errors.append("Dependency documentation must record licenses.")
    if (root / "LICENSE").exists():
        errors.append("A project license requires an explicit Owner decision.")
    return tuple(errors)


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
