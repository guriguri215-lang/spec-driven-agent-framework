"""Explicit Owner-approved copy-on-write M6 scheduler-store migration."""

from __future__ import annotations

import os
from datetime import UTC
from pathlib import Path

from sdaqf.adapters.scheduler import (
    SQLiteSchedulerStore,
    SystemSchedulerClock,
    migrate_scheduler_database_v1_to_v2,
)
from sdaqf.application.contracts import ContractError
from sdaqf.application.migrations import (
    MigrationApprovalConsumptionStore,
    migration_root_identity,
)
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    SchedulerContractError,
    artifact_from_value,
    format_utc,
    load_scheduler_artifact,
    parse_utc,
)
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.migrations import MigrationApproval
from sdaqf.domain.scheduler import (
    SchedulerArtifactType,
    SchedulerStoreMigrationApproval,
    SchedulerStoreMigrationResult,
    TaskGraph,
)
from sdaqf.ports.scheduler import SchedulerClock


class SchedulerMigrationService:
    """Validate and consume one exact migration approval without mutating v1."""

    def __init__(self, clock: SchedulerClock | None = None) -> None:
        self._clock = SystemSchedulerClock() if clock is None else clock

    def migrate(
        self,
        source: Path,
        root: Path,
        output: Path,
        *,
        to_version: int,
        approval: Path,
    ) -> LoadedSchedulerArtifact:
        """Create a fresh v2 store and return its immutable migration result."""

        if to_version != 2:
            raise SchedulerContractError("Scheduler migration supports only to-version 2.")
        resolved_root = _regular_root(root)
        source_path = _existing_under_root(resolved_root, source, ".sqlite3")
        output_path = _new_under_root(resolved_root, output, ".sqlite3")
        approval_path = _existing_under_root(resolved_root, approval, ".json")
        loaded_approval = load_scheduler_artifact(
            approval_path,
            expected_type=SchedulerArtifactType.SCHEDULER_STORE_MIGRATION_APPROVAL,
        )
        approval_value = loaded_approval.value
        assert isinstance(approval_value, SchedulerStoreMigrationApproval)
        source_store = SQLiteSchedulerStore(source_path, resolved_root)
        source_store.validate()
        if source_store.store_version != 1:
            raise SchedulerContractError("Scheduler migration source must be version 1.")
        graph_artifact = source_store.graph_artifact()
        graph = graph_artifact.value
        assert isinstance(graph, TaskGraph)
        now = self._clock.now().astimezone(UTC)
        source_relative = source_path.relative_to(resolved_root).as_posix()
        output_relative = output_path.relative_to(resolved_root).as_posix()
        root_sha256 = migration_root_identity(resolved_root)
        if (
            approval_value.action != "migrate-scheduler-store-v1-to-v2"
            or approval_value.source_path != source_relative
            or approval_value.output_path != output_relative
            or approval_value.source_graph_id != graph_artifact.artifact_id
            or approval_value.source_current_event_head_id != source_store.current_event_head_id
            or approval_value.root_sha256 != root_sha256
            or approval_value.to_version != to_version
            or approval_value.approved_by != "Owner"
            or not (
                parse_utc(approval_value.not_before)
                <= now
                < parse_utc(approval_value.expires_at)
            )
        ):
            raise SchedulerContractError(
                "Scheduler migration approval does not authorize this copy."
            )
        source_head_id = source_store.current_event_head_id
        result = artifact_from_value(
            SchedulerArtifactType.SCHEDULER_STORE_MIGRATION_RESULT,
            SchedulerStoreMigrationResult(
                source_path=source_relative,
                output_path=output_relative,
                root_sha256=root_sha256,
                source_graph_id=graph_artifact.artifact_id,
                source_current_event_head_id=source_head_id,
                output_current_event_head_id=source_head_id,
                from_version=1,
                to_version=2,
                approval_id=loaded_approval.artifact_id,
                workflow_epoch_count=0,
                migrated_at=format_utc(now),
            ),
        )
        common_approval = MigrationApproval(
            approval_id=f"APR-{loaded_approval.artifact_id.rsplit('-', 1)[1]}",
            contract="m6-scheduler-store-v1-to-v2",
            root_sha256=root_sha256,
            source_path=source_relative,
            source_sha256=source_head_id.rsplit("-", 1)[1],
            output_path=output_relative,
            tool_registry_path=None,
            tool_registry_sha256=None,
            source_version="1",
            target_version="2",
            approved_at=approval_value.not_before,
            expires_at=approval_value.expires_at,
        )

        def claim_approval() -> None:
            claim_now = self._clock.now().astimezone(UTC)
            if not (
                parse_utc(approval_value.not_before)
                <= claim_now
                < parse_utc(approval_value.expires_at)
            ):
                raise SchedulerContractError(
                    "Scheduler migration approval expired before its single-use claim."
                )
            try:
                MigrationApprovalConsumptionStore(resolved_root).claim(
                    common_approval,
                    claimed_at=claim_now,
                )
            except ContractError as exc:
                raise SchedulerContractError(str(exc)) from exc

        migrated = migrate_scheduler_database_v1_to_v2(
            source_path,
            output_path,
            resolved_root,
            expected_source_head_id=source_head_id,
            before_publish=claim_approval,
        )
        if migrated.current_event_head_id != source_head_id:
            raise SchedulerContractError(
                "Migrated scheduler event authority differs from v1 source."
            )
        return result


def _regular_root(root: Path) -> Path:
    try:
        if root.is_symlink() or is_reparse_point(root):
            raise SchedulerContractError("Scheduler migration root must be regular and unlinked.")
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise SchedulerContractError("Scheduler migration root is unavailable.") from exc
    if not resolved.is_dir():
        raise SchedulerContractError("Scheduler migration root must be a directory.")
    return resolved


def _existing_under_root(root: Path, path: Path, suffix: str) -> Path:
    target = path if path.is_absolute() else root / path
    if target.suffix.casefold() != suffix:
        raise SchedulerContractError(f"Scheduler migration input must end in {suffix}.")
    try:
        lexical = Path(os.path.abspath(target))
        if ".." in target.parts or not lexical.is_relative_to(root):
            raise SchedulerContractError("Scheduler migration input escapes its root.")
        current = root
        for part in lexical.relative_to(root).parts:
            current = current / part
            if current.is_symlink() or is_reparse_point(current):
                raise SchedulerContractError(
                    "Scheduler migration input contains a linked component."
                )
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise SchedulerContractError("Scheduler migration input is unavailable.") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise SchedulerContractError(
            "Scheduler migration input is not a regular root-confined file."
        )
    return resolved


def _new_under_root(root: Path, path: Path, suffix: str) -> Path:
    target = path if path.is_absolute() else root / path
    if target.suffix.casefold() != suffix:
        raise SchedulerContractError(f"Scheduler migration output must end in {suffix}.")
    lexical = Path(os.path.abspath(target))
    if ".." in target.parts or not lexical.is_relative_to(root):
        raise SchedulerContractError("Scheduler migration output escapes its root.")
    current = root
    for part in lexical.relative_to(root).parts[:-1]:
        current = current / part
        if not current.is_dir() or current.is_symlink() or is_reparse_point(current):
            raise SchedulerContractError("Scheduler migration output parent is unsafe.")
    if target.exists() or target.is_symlink() or is_reparse_point(target):
        raise SchedulerContractError("Scheduler migration output already exists or is linked.")
    return lexical
