import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from sdaqf.application.checkpoints import (
    CheckpointContractError,
    CheckpointStore,
    transition_checkpoint,
    validate_resume,
)
from sdaqf.domain.tooling import (
    CheckpointState,
    ExecutionCheckpoint,
    ExecutionContext,
    FailureClass,
    ToolObservation,
    ToolObservationStatus,
)
from tests.m2_helpers import m2_example


def loaded_checkpoint(tmp_path: Path) -> ExecutionCheckpoint:
    target = tmp_path / "checkpoint.json"
    target.write_bytes(m2_example("execution-checkpoint.json").read_bytes())
    return CheckpointStore(tmp_path).load(target)


def test_checkpoint_store_round_trips_and_recovers_backup(tmp_path: Path) -> None:
    checkpoint = loaded_checkpoint(tmp_path)
    assert hasattr(checkpoint, "state")
    store = CheckpointStore(tmp_path)
    target = tmp_path / "checkpoint.json"
    updated = replace(checkpoint, state=CheckpointState.READY)

    store.save(target, updated)
    target.write_text("{", encoding="utf-8")
    recovered = store.load(target)

    assert recovered.state is CheckpointState.PLANNED
    assert (tmp_path / "checkpoint.json.bak").is_file()


def test_failed_atomic_publish_preserves_previous_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = loaded_checkpoint(tmp_path)
    store = CheckpointStore(tmp_path)
    target = tmp_path / "checkpoint.json"
    real_replace = os.replace
    calls = 0

    def fail_primary(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("simulated publish denial")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_primary)

    with pytest.raises(PermissionError, match="publish denial"):
        store.save(
            target,
            replace(checkpoint, state=CheckpointState.READY),
        )

    assert json.loads(target.read_text(encoding="utf-8"))["state"] == "planned"


def test_failed_backup_publish_cleans_all_temporary_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = loaded_checkpoint(tmp_path)
    store = CheckpointStore(tmp_path)
    target = tmp_path / "checkpoint.json"

    def fail_backup(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
    ) -> None:
        raise PermissionError("simulated backup denial")

    monkeypatch.setattr(os, "replace", fail_backup)

    with pytest.raises(PermissionError, match="backup denial"):
        store.save(target, replace(checkpoint, state=CheckpointState.READY))

    assert json.loads(target.read_text(encoding="utf-8"))["state"] == "planned"
    assert not tuple(tmp_path.glob("*.tmp"))
    assert not tuple(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize(
    ("field", "value", "label"),
    (
        ("plan_version", "2.0", "plan version"),
        ("specification_digest", "B" * 64, "specification digest"),
        ("git_head", "b" * 40, "Git HEAD"),
        ("worktree_digest", "C" * 64, "worktree digest"),
    ),
)
def test_resume_rejects_each_context_mismatch(
    tmp_path: Path,
    field: str,
    value: str,
    label: str,
) -> None:
    checkpoint = loaded_checkpoint(tmp_path)
    context = replace(checkpoint.context, **{field: value})

    with pytest.raises(CheckpointContractError, match=label):
        validate_resume(checkpoint, context)


def test_checkpoint_transitions_are_explicit(tmp_path: Path) -> None:
    checkpoint = loaded_checkpoint(tmp_path)

    ready = transition_checkpoint(checkpoint, CheckpointState.READY)

    assert ready.state is CheckpointState.READY
    with pytest.raises(CheckpointContractError, match="Invalid"):
        transition_checkpoint(checkpoint, CheckpointState.COMPLETED)


def test_checkpoint_rejects_secret_or_unbounded_raw_evidence(tmp_path: Path) -> None:
    checkpoint = loaded_checkpoint(tmp_path)
    observation = ToolObservation(
        tool_name="python",
        status=ToolObservationStatus.NON_ZERO_EXIT,
        failure_class=FailureClass.NON_ZERO_EXIT,
        detail="failed",
        version=None,
        exit_code=2,
        stdout="ghp_" + ("x" * 25),
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
    )

    with pytest.raises(CheckpointContractError, match="secret"):
        CheckpointStore(tmp_path).save(
            tmp_path / "unsafe.json",
            replace(checkpoint, observation=observation),
        )


def test_checkpoint_target_must_stay_inside_allowed_root(tmp_path: Path) -> None:
    checkpoint = loaded_checkpoint(tmp_path)

    with pytest.raises(CheckpointContractError, match="allowed root"):
        CheckpointStore(tmp_path / "allowed").save(
            tmp_path / "outside.json",
            checkpoint,
        )


def test_valid_resume_context_passes(tmp_path: Path) -> None:
    checkpoint = loaded_checkpoint(tmp_path)
    context = ExecutionContext(
        plan_version="1.0",
        specification_digest="89340E628F631CEE6A020C7F1008446ECDB9D0470E7CD56B856F91BB9B10D2D5",
        git_head="eff9e3abfa6aff3e22d71b23140e838cd222832a",
        worktree_digest="A" * 64,
    )

    validate_resume(checkpoint, context)


def test_checkpoint_observation_round_trip_records_bounded_command_evidence(
    tmp_path: Path,
) -> None:
    checkpoint = loaded_checkpoint(tmp_path)
    observation = ToolObservation(
        tool_name="python",
        status=ToolObservationStatus.AVAILABLE,
        failure_class=FailureClass.NONE,
        detail="Safe bounded version probe succeeded.",
        version="3.12.13",
        exit_code=0,
        stdout="Python 3.12.13",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=17,
        execution_mode="approved",
        approval_ids=("APR-0001",),
    )
    completed = replace(
        checkpoint,
        state=CheckpointState.COMPLETED,
        attempts=1,
        last_failure=FailureClass.NONE,
        observation=observation,
    )
    target = tmp_path / "completed.json"

    CheckpointStore(tmp_path).save(target, completed)
    loaded = CheckpointStore(tmp_path).load(target)

    assert loaded == completed
    assert loaded.observation is not None
    assert loaded.observation.duration_ms == 17
    assert loaded.observation.execution_mode == "approved"
    assert loaded.observation.approval_ids == ("APR-0001",)


def test_completed_checkpoint_sample_is_runtime_valid() -> None:
    checkpoint = CheckpointStore(m2_example(".").resolve()).load(
        m2_example("completed-checkpoint.json")
    )

    assert checkpoint.state is CheckpointState.COMPLETED
    assert checkpoint.observation is not None
    assert checkpoint.observation.duration_ms == 17


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda checkpoint: replace(checkpoint, command_digest="bad"),
            "SHA-256",
        ),
        (
            lambda checkpoint: replace(
                checkpoint,
                attempts=1,
                last_failure=FailureClass.NON_ZERO_EXIT,
                state=CheckpointState.BLOCKED,
                observation=ToolObservation(
                    tool_name="git",
                    status=ToolObservationStatus.NON_ZERO_EXIT,
                    failure_class=FailureClass.NON_ZERO_EXIT,
                    detail="failed",
                    version=None,
                    exit_code=2,
                    stdout="",
                    stderr="failed",
                    stdout_truncated=False,
                    stderr_truncated=False,
                ),
            ),
            "tool names",
        ),
        (
            lambda checkpoint: replace(
                checkpoint,
                attempts=1,
                last_failure=FailureClass.PROCESS_TIMEOUT,
                state=CheckpointState.COMPLETED,
                observation=ToolObservation(
                    tool_name="python",
                    status=ToolObservationStatus.TIMEOUT,
                    failure_class=FailureClass.PROCESS_TIMEOUT,
                    detail="timed out",
                    version=None,
                    exit_code=None,
                    stdout="",
                    stderr="",
                    stdout_truncated=False,
                    stderr_truncated=False,
                ),
            ),
            "successful observation",
        ),
    ),
)
def test_checkpoint_save_rejects_incoherent_in_memory_state(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    checkpoint = loaded_checkpoint(tmp_path)
    assert callable(mutation)
    invalid = mutation(checkpoint)

    with pytest.raises(CheckpointContractError, match=message):
        CheckpointStore(tmp_path).save(tmp_path / "invalid.json", invalid)


@pytest.mark.parametrize(
    ("field_path", "value"),
    (
        (("schema_version",), "2.0"),
        (("checkpoint_id",), "unsafe"),
        (("command_digest",), "bad"),
        (("context", "plan_version"), "latest"),
        (("context", "specification_digest"), "bad"),
        (("context", "git_head"), "BAD"),
        (("attempts",), 3),
        (("state",), "unknown"),
    ),
)
def test_checkpoint_loader_boundary_matrix(
    tmp_path: Path,
    field_path: tuple[str, ...],
    value: object,
) -> None:
    payload = json.loads(
        m2_example("execution-checkpoint.json").read_text(encoding="utf-8")
    )
    target = payload
    for field in field_path[:-1]:
        target = target[field]
    target[field_path[-1]] = value
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CheckpointContractError, match="Primary and backup"):
        CheckpointStore(tmp_path).load(path)
