"""Focused tests for the idempotent filesystem agent-host boundary."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import sdaqf.adapters.scheduler as scheduler_adapter_module
from sdaqf.adapters.scheduler import (
    ExclusiveSchedulerArtifactStore,
    FilesystemAgentHost,
    SchedulerAdapterError,
)
from sdaqf.application.scheduler_contracts import (
    artifact_from_value,
    load_scheduler_artifact,
    serialize_scheduler_artifact,
)
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.scheduler import (
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
)

ROOT = Path(__file__).resolve().parents[1]


def _dispatch_message() -> MailboxMessage:
    artifact = load_scheduler_artifact(
        ROOT / "examples" / "m6-scheduler" / "mailbox-message.json",
        expected_type=SchedulerArtifactType.MAILBOX_MESSAGE,
        root=ROOT,
    )
    message = artifact.value
    assert isinstance(message, MailboxMessage)
    assert message.message_type is MessageType.DISPATCH_INTENT
    return message


def test_filesystem_agent_host_replays_exact_dispatch_as_no_op(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    host = FilesystemAgentHost(tmp_path, outbox)
    message = _dispatch_message()
    artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, message)
    target = outbox / f"{artifact.artifact_id}.json"

    host.dispatch(message)
    first_stat = target.stat()
    host.dispatch(message)

    assert tuple(outbox.iterdir()) == (target,)
    assert target.read_bytes() == serialize_scheduler_artifact(artifact)
    assert target.stat().st_mtime_ns == first_stat.st_mtime_ns


def test_filesystem_agent_host_fails_closed_on_conflict_or_wrong_route(
    tmp_path: Path,
) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    host = FilesystemAgentHost(tmp_path, Path("outbox"))
    dispatch = _dispatch_message()
    artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, dispatch)
    target = outbox / f"{artifact.artifact_id}.json"
    cancellation = replace(
        dispatch,
        message_type=MessageType.CANCEL_REQUEST,
        payload={"reason": "bounded test cancellation"},
    )

    with pytest.raises(SchedulerAdapterError, match="expected a cancel_request"):
        host.cancel(dispatch)
    with pytest.raises(SchedulerAdapterError, match="expected a dispatch_intent"):
        host.dispatch(cancellation)
    with pytest.raises(SchedulerAdapterError, match="scheduler-to-host"):
        host.dispatch(
            replace(dispatch, direction=MessageDirection.HOST_TO_SCHEDULER)
        )

    host.cancel(cancellation)
    host.cancel(cancellation)
    cancellation_artifact = artifact_from_value(
        SchedulerArtifactType.MAILBOX_MESSAGE,
        cancellation,
    )
    assert (
        outbox / f"{cancellation_artifact.artifact_id}.json"
    ).read_bytes() == serialize_scheduler_artifact(cancellation_artifact)

    host.dispatch(dispatch)
    target.write_bytes(b"conflicting publication\n")
    with pytest.raises(SchedulerAdapterError, match="conflicts"):
        host.dispatch(dispatch)
    assert target.read_bytes() == b"conflicting publication\n"


def test_filesystem_agent_host_accepts_an_exact_concurrent_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    host = FilesystemAgentHost(tmp_path, outbox)
    message = _dispatch_message()
    artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, message)
    expected = serialize_scheduler_artifact(artifact)
    target = outbox / f"{artifact.artifact_id}.json"

    def publish_then_report_conflict(
        _store: ExclusiveSchedulerArtifactStore,
        path: Path,
        content: bytes,
    ) -> None:
        path.write_bytes(content)
        raise SchedulerAdapterError("simulated concurrent publisher")

    monkeypatch.setattr(
        ExclusiveSchedulerArtifactStore,
        "publish",
        publish_then_report_conflict,
    )
    host.dispatch(message)

    assert target.read_bytes() == expected

    empty_outbox = tmp_path / "empty-outbox"
    empty_outbox.mkdir()
    empty_host = FilesystemAgentHost(tmp_path, empty_outbox)

    def fail_without_publication(
        _store: ExclusiveSchedulerArtifactStore,
        _path: Path,
        _content: bytes,
    ) -> None:
        raise SchedulerAdapterError("simulated failed publisher")

    monkeypatch.setattr(
        ExclusiveSchedulerArtifactStore,
        "publish",
        fail_without_publication,
    )
    with pytest.raises(SchedulerAdapterError, match="simulated failed publisher"):
        empty_host.dispatch(message)


def test_filesystem_agent_host_rejects_same_size_drift_and_indeterminate_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    host = FilesystemAgentHost(tmp_path, outbox)
    message = _dispatch_message()
    artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, message)
    target = outbox / f"{artifact.artifact_id}.json"
    host.dispatch(message)
    expected = serialize_scheduler_artifact(artifact)

    target.write_bytes(b"X" * len(expected))
    with pytest.raises(SchedulerAdapterError, match="conflicts"):
        host.dispatch(message)

    target.write_bytes(expected)
    original_read_bytes = Path.read_bytes

    def unavailable(path: Path) -> bytes:
        if path == target:
            raise OSError("simulated unreadable output")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", unavailable)
    with pytest.raises(SchedulerAdapterError, match="indeterminate"):
        host.dispatch(message)


def test_filesystem_agent_host_revalidates_outbox_and_output_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    host = FilesystemAgentHost(tmp_path, outbox)
    message = _dispatch_message()
    artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, message)
    target = outbox / f"{artifact.artifact_id}.json"
    host.dispatch(message)

    original_reparse_check = is_reparse_point
    monkeypatch.setattr(
        scheduler_adapter_module,
        "is_reparse_point",
        lambda path: path == target or original_reparse_check(path),
    )
    with pytest.raises(SchedulerAdapterError, match="linked or irregular"):
        host.dispatch(message)


def test_filesystem_agent_host_stops_when_outbox_resolution_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    host = FilesystemAgentHost(tmp_path, outbox)
    original_resolve = Path.resolve

    def unavailable(path: Path, *, strict: bool = False) -> Path:
        if path == outbox:
            raise OSError("simulated resolution failure")
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", unavailable)
    with pytest.raises(SchedulerAdapterError, match="outbox is unavailable"):
        host.dispatch(_dispatch_message())


def test_filesystem_agent_host_requires_existing_confined_outbox(tmp_path: Path) -> None:
    with pytest.raises(SchedulerAdapterError, match="outbox"):
        FilesystemAgentHost(tmp_path, Path("missing"))
    with pytest.raises(SchedulerAdapterError, match="escapes"):
        FilesystemAgentHost(tmp_path, Path("..") / tmp_path.name)
