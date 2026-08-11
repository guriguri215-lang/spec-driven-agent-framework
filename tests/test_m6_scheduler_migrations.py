"""M6 v1-to-v2 copy-on-write migration invariants."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

import sdaqf.application.scheduler_migrations as migration_module
from sdaqf.adapters.scheduler import migrate_scheduler_database_v1_to_v2
from sdaqf.application.migrations import migration_root_identity
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    SchedulerContractError,
    artifact_from_value,
    serialize_scheduler_artifact,
)
from sdaqf.application.scheduler_migrations import (
    SchedulerMigrationService,
    _existing_under_root,
    _new_under_root,
    _regular_root,
)
from sdaqf.domain.scheduler import (
    SchedulerArtifactType,
    SchedulerStoreMigrationApproval,
    SchedulerStoreMigrationResult,
)
from tests.m6_scheduler_helpers import (
    FIXED_TIME,
    MutableClock,
    create_store,
    materialize_scheduler_root,
)


def _approval(
    source: Path, output: Path, head_id: str, graph_id: str, root: Path
) -> LoadedSchedulerArtifact:
    value = SchedulerStoreMigrationApproval(
        action="migrate-scheduler-store-v1-to-v2",
        source_path=source.relative_to(root).as_posix(),
        output_path=output.relative_to(root).as_posix(),
        source_graph_id=graph_id,
        source_current_event_head_id=head_id,
        root_sha256=migration_root_identity(root.resolve()),
        to_version=2,
        approved_by="Owner",
        issued_at="2026-08-01T00:00:00Z",
        not_before="2026-08-01T00:00:00Z",
        expires_at="2026-08-01T01:00:00Z",
    )
    return artifact_from_value(
        SchedulerArtifactType.SCHEDULER_STORE_MIGRATION_APPROVAL,
        value,
    )


def test_copy_on_write_migration_preserves_v1_and_starts_empty_epoch_chain(
    tmp_path: Path,
) -> None:
    root, _ = materialize_scheduler_root(tmp_path)
    source = create_store(root, root=root)
    output = root / "state-v2.sqlite3"
    approval_path = root / "approval.json"
    approval = _approval(
        source.path,
        output,
        source.current_event_head_id,
        source.graph_artifact().artifact_id,
        root,
    )
    approval_path.write_bytes(serialize_scheduler_artifact(approval))
    result = SchedulerMigrationService(MutableClock()).migrate(
        source.path,
        root,
        output,
        to_version=2,
        approval=approval_path,
    )
    assert isinstance(result.value, SchedulerStoreMigrationResult)
    assert source.store_version == 1
    assert result.value.workflow_epoch_count == 0
    assert result.value.source_current_event_head_id == source.current_event_head_id
    from sdaqf.adapters.scheduler import SQLiteSchedulerStore

    migrated = SQLiteSchedulerStore(output, root)
    assert migrated.store_version == 2
    assert migrated.current_event_head_id == source.current_event_head_id
    assert migrated.export("workflow-epochs") == ()


def test_migration_holds_source_writer_exclusion_through_exclusive_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = materialize_scheduler_root(tmp_path)
    source = create_store(root, root=root)
    output = root / "state-v2.sqlite3"
    approval_path = root / "approval.json"
    approval_path.write_bytes(
        serialize_scheduler_artifact(
            _approval(
                source.path,
                output,
                source.current_event_head_id,
                source.graph_artifact().artifact_id,
                root,
            )
        )
    )
    original_link = os.link
    writer_was_excluded = False

    def assert_writer_excluded(temporary: Path, target: Path) -> None:
        nonlocal writer_was_excluded
        contender = sqlite3.connect(source.path, timeout=0, isolation_level=None)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                contender.execute("BEGIN IMMEDIATE")
            writer_was_excluded = True
        finally:
            contender.close()
        original_link(temporary, target)

    monkeypatch.setattr("sdaqf.adapters.scheduler.os.link", assert_writer_excluded)
    SchedulerMigrationService(MutableClock()).migrate(
        source.path,
        root,
        output,
        to_version=2,
        approval=approval_path,
    )
    assert writer_was_excluded


def test_migration_rejects_expired_approval_without_output(tmp_path: Path) -> None:
    root, _ = materialize_scheduler_root(tmp_path)
    source = create_store(root, root=root)
    output = root / "state-v2.sqlite3"
    approval_path = root / "approval.json"
    approval_path.write_bytes(
        serialize_scheduler_artifact(
            _approval(
                source.path,
                output,
                source.current_event_head_id,
                source.graph_artifact().artifact_id,
                root,
            )
        )
    )
    clock = MutableClock(FIXED_TIME + timedelta(hours=2))
    with pytest.raises(SchedulerContractError, match="approval"):
        SchedulerMigrationService(clock).migrate(
            source.path,
            root,
            output,
            to_version=2,
            approval=approval_path,
        )
    assert not output.exists()


def test_migration_rejects_root_mismatch_and_consumes_approval_once(
    tmp_path: Path,
) -> None:
    root, _ = materialize_scheduler_root(tmp_path)
    source = create_store(root, root=root)
    output = root / "state-v2.sqlite3"
    approval_path = root / "approval.json"
    approval = _approval(
        source.path,
        output,
        source.current_event_head_id,
        source.graph_artifact().artifact_id,
        root,
    )
    value = approval.value
    assert isinstance(value, SchedulerStoreMigrationApproval)
    wrong_root = artifact_from_value(
        SchedulerArtifactType.SCHEDULER_STORE_MIGRATION_APPROVAL,
        replace(value, root_sha256="0" * 64),
    )
    approval_path.write_bytes(serialize_scheduler_artifact(wrong_root))
    with pytest.raises(SchedulerContractError, match="approval"):
        SchedulerMigrationService(MutableClock()).migrate(
            source.path,
            root,
            output,
            to_version=2,
            approval=approval_path,
        )
    approval_path.write_bytes(serialize_scheduler_artifact(approval))
    SchedulerMigrationService(MutableClock()).migrate(
        source.path,
        root,
        output,
        to_version=2,
        approval=approval_path,
    )
    output.unlink()
    with pytest.raises(SchedulerContractError, match="consum"):
        SchedulerMigrationService(MutableClock()).migrate(
            source.path,
            root,
            output,
            to_version=2,
            approval=approval_path,
        )


def test_migration_rechecks_approval_expiry_at_single_use_claim(tmp_path: Path) -> None:
    root, _ = materialize_scheduler_root(tmp_path)
    source = create_store(root, root=root)
    output = root / "state-v2.sqlite3"
    approval_path = root / "approval.json"
    approval_path.write_bytes(
        serialize_scheduler_artifact(
            _approval(
                source.path,
                output,
                source.current_event_head_id,
                source.graph_artifact().artifact_id,
                root,
            )
        )
    )

    class ExpiringClock:
        def __init__(self) -> None:
            self.calls = 0

        def now(self):  # type: ignore[no-untyped-def]
            self.calls += 1
            return FIXED_TIME if self.calls == 1 else FIXED_TIME + timedelta(hours=2)

    with pytest.raises(SchedulerContractError, match="expired"):
        SchedulerMigrationService(ExpiringClock()).migrate(
            source.path,
            root,
            output,
            to_version=2,
            approval=approval_path,
        )
    assert not output.exists()


def test_migration_claim_remains_consumed_after_post_link_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = materialize_scheduler_root(tmp_path)
    source = create_store(root, root=root)
    output = root / "state-v2.sqlite3"
    approval_path = root / "approval.json"
    approval_path.write_bytes(
        serialize_scheduler_artifact(
            _approval(
                source.path,
                output,
                source.current_event_head_id,
                source.graph_artifact().artifact_id,
                root,
            )
        )
    )
    original = cast(Any, migrate_scheduler_database_v1_to_v2)

    def fail_after_link(*args: object, **kwargs: object) -> object:
        original(*args, **kwargs)
        raise RuntimeError("synthetic post-link failure")

    monkeypatch.setattr(
        "sdaqf.application.scheduler_migrations.migrate_scheduler_database_v1_to_v2",
        fail_after_link,
    )
    with pytest.raises(RuntimeError, match="post-link"):
        SchedulerMigrationService(MutableClock()).migrate(
            source.path,
            root,
            output,
            to_version=2,
            approval=approval_path,
        )
    assert output.exists()
    output.unlink()
    monkeypatch.setattr(
        "sdaqf.application.scheduler_migrations.migrate_scheduler_database_v1_to_v2",
        original,
    )
    with pytest.raises(SchedulerContractError, match="consum"):
        SchedulerMigrationService(MutableClock()).migrate(
            source.path,
            root,
            output,
            to_version=2,
            approval=approval_path,
        )


def test_migration_path_boundaries_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = root / "source.sqlite3"
    source.write_bytes(b"source")
    assert _regular_root(root) == root.resolve()
    assert _existing_under_root(root, source, ".sqlite3") == source.resolve()
    assert _new_under_root(root, root / "new.sqlite3", ".sqlite3") == (
        root / "new.sqlite3"
    ).resolve()

    with pytest.raises(SchedulerContractError, match="to-version 2"):
        SchedulerMigrationService(MutableClock()).migrate(
            source,
            root,
            root / "never.sqlite3",
            to_version=3,
            approval=root / "missing.json",
        )
    with pytest.raises(SchedulerContractError, match=r"end in \.json"):
        _existing_under_root(root, source, ".json")
    with pytest.raises(SchedulerContractError, match="escapes"):
        _existing_under_root(root, root / ".." / "source.sqlite3", ".sqlite3")
    with pytest.raises(SchedulerContractError, match="unavailable"):
        _existing_under_root(root, root / "missing.sqlite3", ".sqlite3")
    with pytest.raises(SchedulerContractError, match=r"end in \.json"):
        _new_under_root(root, root / "new.sqlite3", ".json")
    with pytest.raises(SchedulerContractError, match="escapes"):
        _new_under_root(root, root / ".." / "new.sqlite3", ".sqlite3")

    unsafe_parent = root / "unsafe"
    unsafe_parent.write_text("not a directory", encoding="utf-8")
    with pytest.raises(SchedulerContractError, match="parent is unsafe"):
        _new_under_root(root, unsafe_parent / "new.sqlite3", ".sqlite3")
    existing = root / "existing.sqlite3"
    existing.write_bytes(b"exists")
    with pytest.raises(SchedulerContractError, match="already exists"):
        _new_under_root(root, existing, ".sqlite3")
    with pytest.raises(SchedulerContractError, match="directory"):
        _regular_root(existing)
    with pytest.raises(SchedulerContractError, match="unavailable"):
        _regular_root(root / "missing")

    monkeypatch.setattr(
        migration_module,
        "is_reparse_point",
        lambda path: Path(path) == root,
    )
    with pytest.raises(SchedulerContractError, match="regular and unlinked"):
        _regular_root(root)
