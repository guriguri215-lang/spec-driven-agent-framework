"""Safe and idempotent local project initialization."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_INITIAL_MANIFEST: dict[str, str] = {
    "schema_version": "1.0",
    "status": "planned",
    "network_policy": "default-deny",
}


def is_reparse_point(path: Path) -> bool:
    """Return true for a symbolic link or Windows reparse point."""

    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & _REPARSE_POINT)


@dataclass(frozen=True, slots=True)
class InitializationPlan:
    """Description of a safe initialization operation."""

    target: Path
    would_create: tuple[str, ...]
    conflicts: tuple[str, ...]

    @property
    def safe(self) -> bool:
        """Return true when initialization would not overwrite data."""

        return not self.conflicts

    def to_dict(self) -> dict[str, object]:
        """Return a path-sanitized JSON-compatible representation."""

        return {
            "target": self.target.name,
            "safe": self.safe,
            "would_create": list(self.would_create),
            "conflicts": list(self.conflicts),
        }


class WorkspaceInitializer:
    """Create the minimum local state without overwriting existing content."""

    _STATE_DIR = ".sdaqf"
    _MANIFEST = ".sdaqf/project.json"

    def __init__(self, allowed_root: Path | None = None) -> None:
        self._allowed_root_input = allowed_root or Path.cwd()
        self._allowed_root = self._allowed_root_input.resolve()

    def plan(self, target: Path) -> InitializationPlan:
        """Return a non-mutating initialization plan."""

        conflicts: list[str] = []
        would_create: list[str] = []
        resolved_target = target.resolve(strict=False)
        within_allowed_root = resolved_target.is_relative_to(self._allowed_root)
        if is_reparse_point(self._allowed_root_input) or not self._allowed_root.is_dir():
            conflicts.append("Allowed root must be an existing regular directory.")
        if not within_allowed_root:
            conflicts.append("Target must stay within the allowed root.")
        if target.exists() and (
            not target.is_dir() or is_reparse_point(target)
        ):
            conflicts.append("Target must be a regular directory.")
        if within_allowed_root:
            state_dir = target / self._STATE_DIR
            manifest = target / self._MANIFEST
            if state_dir.exists() and (
                not state_dir.is_dir() or is_reparse_point(state_dir)
            ):
                conflicts.append(f"{self._STATE_DIR} must be a regular directory.")
            elif not state_dir.exists():
                would_create.append(self._STATE_DIR)
            if manifest.exists() or manifest.is_symlink():
                if not _is_initial_manifest(manifest):
                    conflicts.append(
                        f"{self._MANIFEST} exists but is not recognized initial state."
                    )
            else:
                would_create.append(self._MANIFEST)
        parent = target.parent
        if not parent.exists() or not parent.is_dir() or is_reparse_point(parent):
            conflicts.append("Target parent must be an existing regular directory.")
        return InitializationPlan(
            target=target,
            would_create=tuple(would_create),
            conflicts=tuple(conflicts),
        )

    def initialize(self, target: Path) -> InitializationPlan:
        """Apply a safe initialization plan using exclusive file creation."""

        plan = self.plan(target)
        if not plan.safe:
            return plan
        if not plan.would_create:
            return plan
        target.mkdir(exist_ok=True)
        state_dir = target / self._STATE_DIR
        state_dir.mkdir(exist_ok=True)
        if is_reparse_point(target) or is_reparse_point(state_dir):
            raise PermissionError("Initialization path changed during creation.")
        with (target / self._MANIFEST).open(
            "x",
            encoding="utf-8",
            errors="strict",
        ) as stream:
            stream.write(json.dumps(_INITIAL_MANIFEST, indent=2) + "\n")
        return plan


def _is_initial_manifest(path: Path) -> bool:
    """Return true only for the exact regular initial manifest contract."""

    if not path.is_file() or is_reparse_point(path):
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and bool(payload == _INITIAL_MANIFEST)
