"""Immutable M4 schema-migration result contract."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MigrationApproval:
    """Exact, time-bounded Owner approval for one migration target."""

    approval_id: str
    contract: str
    source_sha256: str
    output_path: str
    tool_registry_path: str | None
    tool_registry_sha256: str | None
    source_version: str
    target_version: str
    approved_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Evidence for one explicit non-destructive schema migration."""

    approval_id: str
    contract: str
    source_version: str
    target_version: str
    source_sha256: str
    tool_registry_path: str | None
    tool_registry_sha256: str | None
    output_sha256: str
    inserted_defaults: tuple[str, ...]
    warnings: tuple[str, ...]
    output_path: str
    rollback: str
    source_preserved: bool = True
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible migration result."""

        return {
            "schema_version": self.schema_version,
            "approval_id": self.approval_id,
            "contract": self.contract,
            "source_version": self.source_version,
            "target_version": self.target_version,
            "source_sha256": self.source_sha256,
            "tool_registry_path": self.tool_registry_path,
            "tool_registry_sha256": self.tool_registry_sha256,
            "output_sha256": self.output_sha256,
            "inserted_defaults": list(self.inserted_defaults),
            "warnings": list(self.warnings),
            "source_preserved": self.source_preserved,
            "output_path": self.output_path,
            "rollback": self.rollback,
        }
