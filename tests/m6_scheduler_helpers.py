"""Shared deterministic fixtures for M6 scheduler tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    artifact_from_value,
    load_scheduler_artifact,
    scheduler_identity,
    serialize_scheduler_artifact,
)
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.scheduler import (
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    TaskGraph,
)

ROOT = Path(__file__).resolve().parents[1]
TASK_GRAPH_PATH = ROOT / "examples" / "m6-scheduler" / "task-graph.json"
FIXED_TIME = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
HOST_ID = "HST-TEST"


@dataclass(slots=True)
class MutableClock:
    value: datetime = FIXED_TIME

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def graph_artifact() -> LoadedSchedulerArtifact:
    return load_scheduler_artifact(
        TASK_GRAPH_PATH,
        expected_type=SchedulerArtifactType.TASK_GRAPH,
        root=ROOT,
    )


def graph_value() -> TaskGraph:
    value = graph_artifact().value
    assert isinstance(value, TaskGraph)
    return value


def worktree_graph() -> TaskGraph:
    graph = graph_value()
    plan_path = Path("examples/m2-orchestration/worktree-plan.json")
    plan = ArtifactReference(
        plan_path.as_posix(),
        hashlib.sha256((ROOT / plan_path).read_bytes()).hexdigest().upper(),
    )
    task = replace(
        graph.tasks[0],
        owned_paths=("src/sdaqf",),
        required_tools=("git", "python"),
        worktree_assignment="worktrees/implementation",
    )
    return replace(graph, worktree_plan=plan, tasks=(task,))


def create_store(
    tmp_path: Path,
    *,
    graph: TaskGraph | None = None,
    clock: datetime = FIXED_TIME,
) -> SQLiteSchedulerStore:
    selected = graph_value() if graph is None else graph
    artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, selected)
    return SQLiteSchedulerStore.initialize(
        tmp_path / "state.sqlite3",
        ROOT,
        artifact,
        clock,
    )


def first_dispatch(
    store: SQLiteSchedulerStore,
    *,
    clock: datetime = FIXED_TIME,
) -> LoadedSchedulerArtifact:
    tick = store.tick(ROOT, HOST_ID, (), clock)
    assert len(tick.outgoing) == 1
    return tick.outgoing[0]


def host_message(
    dispatch_artifact: LoadedSchedulerArtifact,
    message_type: MessageType,
    payload: dict[str, object],
    *,
    clock: datetime = FIXED_TIME,
    sender: str = HOST_ID,
    parents: tuple[str, ...] | None = None,
) -> LoadedSchedulerArtifact:
    dispatch = dispatch_artifact.value
    assert isinstance(dispatch, MailboxMessage)
    message = MailboxMessage(
        message_type=message_type,
        direction=MessageDirection.HOST_TO_SCHEDULER,
        sender=sender,
        recipient="HST-SCHEDULER",
        graph_id=dispatch.graph_id,
        task_id=dispatch.task_id,
        candidate=dispatch.candidate,
        context_snapshot_id=dispatch.context_snapshot_id,
        attempt=dispatch.attempt,
        lease_id=dispatch.lease_id,
        fence=dispatch.fence,
        idempotency_key=dispatch.idempotency_key,
        sensitivity=dispatch.sensitivity,
        provenance=dispatch.provenance,
        causal_parent_message_ids=(
            (dispatch_artifact.artifact_id,) if parents is None else parents
        ),
        recorded_at=clock.isoformat(timespec="seconds").replace("+00:00", "Z"),
        payload=payload,
    )
    return artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, message)


def result_message(
    dispatch: LoadedSchedulerArtifact,
    *,
    outcome: str = "succeeded",
    effect: str = "none",
    evidence: bool = True,
    tool_calls: int = 0,
    solver_calls: int = 0,
    solver_steps: int = 0,
    microunits: int = 0,
    clock: datetime = FIXED_TIME,
) -> LoadedSchedulerArtifact:
    path = Path("examples/m2-orchestration/implementer-result.json")
    digest = hashlib.sha256((ROOT / path).read_bytes()).hexdigest().upper()
    reference = ArtifactReference(path.as_posix(), digest).to_dict()
    return host_message(
        dispatch,
        MessageType.TASK_RESULT,
        {
            "agent_result": reference,
            "outcome": outcome,
            "effect_observed": effect,
            "evidence_refs": [reference] if evidence else [],
            "budget_usage": {
                "microunits": microunits,
                "solver_calls": solver_calls,
                "solver_steps": solver_steps,
                "tool_calls": tool_calls,
            },
        },
        clock=clock,
    )


def write_artifact(tmp_path: Path, artifact: LoadedSchedulerArtifact, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(serialize_scheduler_artifact(artifact))
    return path


def example_payload(name: str) -> dict[str, object]:
    value: object = json.loads(
        (ROOT / "examples" / "m6-scheduler" / name).read_text(encoding="utf-8")
    )
    assert isinstance(value, dict)
    return value


def refresh_identity(payload: dict[str, object]) -> dict[str, object]:
    artifact_type = SchedulerArtifactType(str(payload["artifact_type"]))
    payload["artifact_id"] = scheduler_identity(artifact_type, payload["content"])
    return payload


def strict_bytes(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
