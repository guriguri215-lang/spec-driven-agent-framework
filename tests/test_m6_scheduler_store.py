"""M6 SQLite scheduler store invariants."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from sdaqf.adapters.scheduler import (
    APPLICATION_ID,
    TABLE_NAMES,
    USER_VERSION,
    SchedulerAdapterError,
    SQLiteSchedulerStore,
)
from sdaqf.application.scheduler import _existing_under_root
from sdaqf.application.scheduler_contracts import SchedulerContractError, load_scheduler_artifact
from sdaqf.domain.scheduler import Lease, MailboxMessage, SchedulerArtifactType, SchedulerState
from tests.m6_scheduler_helpers import FIXED_TIME, ROOT, create_store, graph_artifact


def test_initial_database_has_exact_identity_shape_and_projection(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    store.validate()
    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert connection.execute("PRAGMA user_version").fetchone()[0] == USER_VERSION
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        connection.close()
    assert tables == TABLE_NAMES
    state = store.status().value
    assert isinstance(state, SchedulerState)
    assert state.event_sequence == 1
    assert state.ready_order == ("TSK-M6-DEMO",)
    assert store.graph_artifact() == graph_artifact()


def test_initialization_is_exclusive_and_paths_are_confined(tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite3"
    SQLiteSchedulerStore.initialize(state, ROOT, graph_artifact(), FIXED_TIME)
    with pytest.raises(SchedulerAdapterError, match=r"fresh|exists"):
        SQLiteSchedulerStore.initialize(state, ROOT, graph_artifact(), FIXED_TIME)
    with pytest.raises(SchedulerAdapterError):
        SQLiteSchedulerStore.initialize(tmp_path / "bad.db", ROOT, graph_artifact(), FIXED_TIME)
    lease = load_scheduler_artifact(
        ROOT / "examples" / "m6-scheduler" / "lease.json",
        expected_type=SchedulerArtifactType.LEASE,
    )
    with pytest.raises(SchedulerAdapterError, match="Task Graph"):
        SQLiteSchedulerStore.initialize(tmp_path / "wrong.sqlite3", ROOT, lease, FIXED_TIME)


def test_store_rejects_wrong_database_identity_and_event_tampering(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute("PRAGMA application_id = 0")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError):
        store.validate()

    other = SQLiteSchedulerStore.initialize(
        tmp_path / "tampered.sqlite3", ROOT, graph_artifact(), FIXED_TIME
    )
    connection = sqlite3.connect(other.path)
    try:
        connection.execute("UPDATE events SET event_sha256 = ? WHERE sequence = 1", ("F" * 64,))
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError, match=r"event|chain|immutable"):
        other.validate()


def test_export_mailbox_and_tick_bounds_fail_closed(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    for kind in ("state", "leases", "messages", "events", "budget", "worktrees"):
        assert isinstance(store.export(kind), tuple)
    with pytest.raises(SchedulerAdapterError):
        store.export("unknown")
    with pytest.raises(SchedulerAdapterError):
        store.export("events", limit=0)
    with pytest.raises(SchedulerAdapterError):
        store.export("events", after_sequence=-1)
    with pytest.raises(SchedulerAdapterError):
        store.inspect_mailbox(limit=1001)
    with pytest.raises(SchedulerAdapterError):
        store.tick(ROOT, "not-a-host", (), FIXED_TIME)
    with pytest.raises(SchedulerAdapterError):
        store.tick(ROOT, "HST-TEST", (), FIXED_TIME, lease_ttl_seconds=29)
    with pytest.raises(SchedulerAdapterError):
        store.tick(
            ROOT,
            "HST-TEST",
            (),
            FIXED_TIME,
            lease_ttl_seconds=60,
            heartbeat_interval_seconds=31,
        )


def test_lease_policy_is_selected_at_initialization_and_immutable_per_store(
    tmp_path: Path,
) -> None:
    store = SQLiteSchedulerStore.initialize(
        tmp_path / "custom-policy.sqlite3",
        ROOT,
        graph_artifact(),
        FIXED_TIME,
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
    )
    with pytest.raises(SchedulerAdapterError, match="immutable initialization policy"):
        store.tick(ROOT, "HST-TEST", (), FIXED_TIME)

    tick = store.tick(
        ROOT,
        "HST-TEST",
        (),
        FIXED_TIME,
        lease_ttl_seconds=120,
        heartbeat_interval_seconds=30,
    )
    message = tick.outgoing[0].value
    lease = store.export("leases")[0].value
    assert isinstance(message, MailboxMessage)
    assert isinstance(lease, Lease)
    assert message.payload["lease_ttl_seconds"] == lease.ttl_seconds == 120
    assert message.payload["heartbeat_interval_seconds"] == lease.heartbeat_interval_seconds == 30
    store.validate()


def test_only_one_tick_can_claim_the_single_ready_task(tmp_path: Path) -> None:
    store = create_store(tmp_path)
    first = store.tick(ROOT, "HST-FIRST", (), FIXED_TIME)
    second = store.tick(ROOT, "HST-SECOND", (), FIXED_TIME)
    assert len(first.outgoing) == 1
    assert second.outgoing == ()
    leases = store.export("leases")
    assert len(leases) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "DELETE FROM metadata WHERE key = 'schema_version'",
        "UPDATE metadata SET value = '0.0' WHERE key = 'schema_version'",
        "UPDATE metadata SET value = '{' WHERE key = 'host_capabilities'",
        "UPDATE metadata SET value = '[]' WHERE key = 'host_capabilities'",
        "UPDATE metadata SET value = "
        "'M6-GRAPH-0000000000000000000000000000000000000000000000000000000000000000' "
        "WHERE key = 'graph_id'",
        "DELETE FROM task_graph",
        "CREATE TABLE unexpected(value TEXT)",
        "ALTER TABLE tasks ADD COLUMN drift TEXT",
        "UPDATE tasks SET attempt = 3 WHERE task_id = 'TSK-M6-DEMO'",
        "UPDATE tasks SET state = 'blocked' WHERE task_id = 'TSK-M6-DEMO'",
        "UPDATE budget_totals SET used = 1 WHERE resource = 'tool_calls'",
    ],
)
def test_database_shape_metadata_and_projection_drift_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    store = create_store(tmp_path)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(mutation)
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(SchedulerAdapterError):
        store.validate()


def test_constructor_rejects_missing_wrong_suffix_and_outside_root(tmp_path: Path) -> None:
    with pytest.raises(SchedulerAdapterError):
        SQLiteSchedulerStore(tmp_path / "missing.sqlite3", ROOT)
    wrong = tmp_path / "state.db"
    wrong.write_bytes(b"not sqlite")
    with pytest.raises(SchedulerAdapterError):
        SQLiteSchedulerStore(wrong, ROOT)


@pytest.mark.parametrize("link_kind", ["symlink", "junction"])
def test_linked_ancestor_is_rejected_before_resolution(
    tmp_path: Path, link_kind: str
) -> None:
    if not tmp_path.is_relative_to(ROOT):
        pytest.skip("pytest temporary root is outside the repository")
    real = tmp_path / "real"
    linked = tmp_path / "linked"
    real.mkdir()
    if link_kind == "symlink":
        try:
            linked.symlink_to(real, target_is_directory=True)
        except OSError:
            pytest.skip("directory symlinks are unavailable")
    else:
        junction = subprocess.run(
            ("cmd.exe", "/d", "/c", "mklink", "/J", str(linked), str(real)),
            check=False,
            capture_output=True,
        )
        if junction.returncode != 0:
            pytest.skip("directory junctions are unavailable")

    with pytest.raises(SchedulerAdapterError, match=r"linked|irregular"):
        SQLiteSchedulerStore.initialize(
            linked / "state.sqlite3", ROOT, graph_artifact(), FIXED_TIME
        )

    artifact = real / "task-graph.json"
    artifact.write_bytes(
        (ROOT / "examples" / "m6-scheduler" / "task-graph.json").read_bytes()
    )
    with pytest.raises(SchedulerContractError, match=r"linked|regular"):
        _existing_under_root(ROOT, linked / "task-graph.json", ".json")
