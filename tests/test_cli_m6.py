"""M6 scheduler CLI signature and offline workflow tests."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.migrations import migration_root_identity
from sdaqf.application.scheduler import SchedulerService
from sdaqf.application.scheduler_contracts import (
    SchedulerContractError,
    artifact_from_value,
    serialize_scheduler_artifact,
)
from sdaqf.cli import main
from sdaqf.domain.scheduler import (
    SchedulerArtifactType,
    SchedulerStoreMigrationApproval,
)
from tests.m6_scheduler_helpers import (
    ROOT,
    TASK_GRAPH_PATH,
    MutableClock,
    materialize_scheduler_root,
)


def _run(arguments: list[str], *, expected: int = 0) -> dict[str, object]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = main(arguments)
    assert result == expected, stdout.getvalue() + stderr.getvalue()
    payload = json.loads(stdout.getvalue())
    assert isinstance(payload, dict)
    return payload


def test_exact_m6_cli_commands_cover_the_local_lifecycle(tmp_path: Path) -> None:
    project_root, project_graph = materialize_scheduler_root(tmp_path)
    root = str(project_root)
    graph = str(project_graph)
    validated = _run(["agents", "schedule", "validate", graph, "--root", root, "--json"])
    assert validated["valid"] is True
    assert validated["tasks"] == 1

    state = project_root / "cli.sqlite3"
    initialized = _run(
        [
            "agents",
            "schedule",
            "init",
            graph,
            "--root",
            root,
            "--state",
            str(state),
            "--json",
        ]
    )
    assert initialized["valid"] is True
    tick = _run(
        [
            "agents",
            "schedule",
            "tick",
            str(state),
            "--root",
            root,
            "--host-id",
            "HST-CLI",
            "--json",
        ]
    )
    assert len(tick["outgoing"]) == 1  # type: ignore[arg-type]
    status = _run(["agents", "schedule", "status", str(state), "--root", root, "--json"])
    assert status["state"]["artifact_type"] == "scheduler-state"  # type: ignore[index]
    assert status["wait_report"]["kind"] == "stall"  # type: ignore[index]

    migrated = project_root / "cli-migrated.sqlite3"
    approval = project_root / "scheduler-migration-approval.json"
    source_store = SQLiteSchedulerStore(state, project_root)
    graph_id = source_store.graph_artifact().artifact_id
    approval.write_bytes(
        serialize_scheduler_artifact(
            artifact_from_value(
                SchedulerArtifactType.SCHEDULER_STORE_MIGRATION_APPROVAL,
                SchedulerStoreMigrationApproval(
                    action="migrate-scheduler-store-v1-to-v2",
                    source_path=state.relative_to(project_root).as_posix(),
                    output_path=migrated.relative_to(project_root).as_posix(),
                    source_graph_id=graph_id,
                    source_current_event_head_id=source_store.current_event_head_id,
                    root_sha256=migration_root_identity(project_root.resolve()),
                    to_version=2,
                    approved_by="Owner",
                    issued_at="2020-01-01T00:00:00Z",
                    not_before="2020-01-01T00:00:00Z",
                    expires_at="2030-01-01T00:00:00Z",
                ),
            )
        )
    )
    migration = _run(
        [
            "agents",
            "schedule",
            "migrate",
            str(state),
            "--root",
            root,
            "--output",
            str(migrated),
            "--to-version",
            "2",
            "--approval",
            str(approval),
            "--json",
        ]
    )
    assert migration["source_preserved"] is True
    assert SQLiteSchedulerStore(migrated, project_root).store_version == 2

    workflow_state = project_root / "cli-workflow-authority.sqlite3"
    workflow_initialized = _run(
        [
            "agents",
            "schedule",
            "init",
            graph,
            "--root",
            root,
            "--state",
            str(workflow_state),
            "--workflow-authority",
            "--json",
        ]
    )
    assert workflow_initialized["valid"] is True
    assert SQLiteSchedulerStore(workflow_state, project_root).store_version == 2

    mailbox = _run(["agents", "mailbox", "inspect", str(state), "--root", root, "--json"])
    assert mailbox["count"] == 1
    exported = project_root / "events.json"
    result = _run(
        [
            "agents",
            "schedule",
            "export",
            str(state),
            "--root",
            root,
            "--kind",
            "events",
            "--output",
            str(exported),
            "--json",
        ]
    )
    exported_payload = json.loads(exported.read_text(encoding="ascii"))
    exported_items = exported_payload["items"]
    assert isinstance(exported_items, list)
    causes = [item["content"]["cause"] for item in exported_items]
    assert causes in (
        ["initialize", "dispatch-intent"],
        ["initialize", "wall-time-observed", "dispatch-intent"],
    )
    assert result["count"] == len(causes)
    assert exported.is_file()

    recovered = project_root / "recovered.sqlite3"
    result = _run(
        [
            "agents",
            "recover",
            str(state),
            "--root",
            root,
            "--output",
            str(recovered),
            "--json",
        ]
    )
    assert result["valid"] is True
    simulated = _run(
        [
            "agents",
            "simulate",
            graph,
            "--root",
            root,
            "--scenario",
            "success",
            "--json",
        ]
    )
    assert simulated["outcome"] == "completed-after-verification"
    assert simulated["offline"] is True


def test_json_failure_is_bounded_and_does_not_create_output(tmp_path: Path) -> None:
    output = tmp_path / "must-not-exist.sqlite3"
    result = _run(
        [
            "agents",
            "recover",
            str(tmp_path / "missing.sqlite3"),
            "--root",
            str(ROOT),
            "--output",
            str(output),
            "--json",
        ],
        expected=2,
    )
    assert result == {"error": "m6-scheduler-invalid", "operation": "recover"}
    assert not output.exists()


def test_scheduler_service_confines_inputs_and_publishes_exports_exclusively(
    tmp_path: Path,
) -> None:
    service = SchedulerService(MutableClock())
    with pytest.raises(SchedulerContractError):
        service.validate_graph(ROOT / "README.md", ROOT)
    with pytest.raises(SchedulerContractError):
        service.validate_graph(ROOT / "examples" / "missing.json", ROOT)
    root_file = tmp_path / "not-a-root"
    root_file.write_text("x", encoding="utf-8")
    with pytest.raises(SchedulerContractError):
        service.validate_graph(TASK_GRAPH_PATH, root_file)

    state = tmp_path / "service.sqlite3"
    initialized = service.initialize(TASK_GRAPH_PATH, ROOT, state)
    assert initialized.artifact_type.value == "scheduler-state"
    assert service.status(state, ROOT) == initialized
    output = tmp_path / "state-export.json"
    result = service.export(state, ROOT, "state", output, limit=1)
    assert result["count"] == 1
    with pytest.raises(SchedulerContractError):
        service.export(state, ROOT, "state", output, limit=1)
    assert service.inspect_mailbox(state, ROOT) == ()
