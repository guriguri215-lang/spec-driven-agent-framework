"""Standard-library SQLite and local-file adapters for M6 scheduling."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.scheduler_contracts import (
    EVENT_CAUSES,
    LoadedSchedulerArtifact,
    SchedulerContractError,
    artifact_from_value,
    derive_idempotency_key,
    event_digest,
    format_utc,
    parse_scheduler_artifact_bytes,
    parse_utc,
    strict_host_id,
    strict_reason,
    topological_ranks,
    validate_task_graph_inputs,
    validate_task_result_reference,
    verified_reference_size,
)
from sdaqf.application.solver_contracts import SolverContractError, parse_solver_capability_token
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.context import SENSITIVITY_RANK, Sensitivity
from sdaqf.domain.scheduler import (
    Blocker,
    BudgetLedger,
    DispatchPhase,
    EffectKind,
    Lease,
    LeaseStatus,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerEvent,
    SchedulerState,
    TaskGraph,
    TaskOutcome,
    TaskProjection,
    TaskState,
    WorktreeLease,
    WorktreeLeaseStatus,
)
from sdaqf.domain.solver import SolverLeaseEvidence

APPLICATION_ID = 0x53444151
USER_VERSION = 1
SCHEMA_VERSION = "1.0"
MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_EXPORT = 1000
DEFAULT_LEASE_TTL_SECONDS = 60
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15
RESOURCE_NAMES = (
    "concurrency",
    "context_bytes",
    "dispatches",
    "microunits",
    "retries",
    "solver_calls",
    "solver_steps",
    "tool_calls",
    "wall_time_seconds",
)
TABLE_NAMES = {
    "approval_consumptions",
    "budget_entries",
    "budget_totals",
    "current_leases",
    "current_worktree_leases",
    "dependencies",
    "events",
    "lease_history",
    "messages",
    "metadata",
    "task_graph",
    "tasks",
    "worktree_lease_history",
}


def _require_semantics(condition: bool, message: str) -> None:
    if not condition:
        raise SchedulerAdapterError(message)


def _validate_lease_policy(ttl_seconds: int, heartbeat_interval_seconds: int) -> None:
    if not 30 <= ttl_seconds <= 3600:
        raise SchedulerAdapterError("Lease TTL is outside the supported range.")
    if not 5 <= heartbeat_interval_seconds <= min(300, ttl_seconds // 2):
        raise SchedulerAdapterError("Heartbeat interval is outside the supported range.")


def _lease_policy_reason(ttl_seconds: int, heartbeat_interval_seconds: int) -> str:
    return f"lease-policy-ttl-{ttl_seconds}-heartbeat-{heartbeat_interval_seconds}"


_EVENT_MESSAGE_TYPES = {
    "approval-consumed": MessageType.APPROVAL_DECISION,
    "approval-received": MessageType.APPROVAL_DECISION,
    "cancel-acknowledgement": MessageType.CANCEL_ACKNOWLEDGEMENT,
    "cancel-request": MessageType.CANCEL_REQUEST,
    "capability-observed": MessageType.CAPABILITY_OBSERVATION,
    "dispatch-accepted": MessageType.DISPATCH_ACKNOWLEDGEMENT,
    "dispatch-intent": MessageType.DISPATCH_INTENT,
    "dispatch-rejected": MessageType.DISPATCH_ACKNOWLEDGEMENT,
    "heartbeat": MessageType.HEARTBEAT,
    "result-received": MessageType.TASK_RESULT,
    "result-terminal": MessageType.TASK_RESULT,
    "worktree-observed": MessageType.WORKTREE_OBSERVATION,
    "worktree-request": MessageType.WORKTREE_REQUEST,
}

_PRIMARY_EVENT_CAUSES_BY_MESSAGE = {
    MessageType.APPROVAL_DECISION: frozenset({"approval-received"}),
    MessageType.CANCEL_ACKNOWLEDGEMENT: frozenset({"cancel-acknowledgement"}),
    MessageType.CANCEL_REQUEST: frozenset({"cancel-request"}),
    MessageType.CAPABILITY_OBSERVATION: frozenset({"capability-observed"}),
    MessageType.DISPATCH_ACKNOWLEDGEMENT: frozenset({"dispatch-accepted", "dispatch-rejected"}),
    MessageType.DISPATCH_INTENT: frozenset({"dispatch-intent"}),
    MessageType.HEARTBEAT: frozenset({"heartbeat"}),
    MessageType.TASK_RESULT: frozenset({"result-received", "result-terminal"}),
    MessageType.WORKTREE_OBSERVATION: frozenset({"worktree-observed"}),
    MessageType.WORKTREE_REQUEST: frozenset({"worktree-request"}),
}

_PRIMARY_MESSAGE_EVENT_CAUSES = frozenset(
    cause for causes in _PRIMARY_EVENT_CAUSES_BY_MESSAGE.values() for cause in causes
)

_WORKTREE_HISTORY_EVENT_CAUSES = frozenset(
    {
        "approval-proposal-expired",
        "cancel-acknowledgement",
        "dispatch-rejected",
        "lease-expired",
        "result-received",
        "result-terminal",
        "worktree-observed",
        "worktree-request",
    }
)

_EVENT_SCOPES = {
    "approval-consumed": "task",
    "approval-proposal-expired": "task",
    "approval-received": "task",
    "cancel-acknowledgement": "task",
    "cancel-request": "task",
    "capability-observed": "graph",
    "dispatch-accepted": "task",
    "dispatch-approval-blocked": "task",
    "dispatch-budget-blocked": "task",
    "dispatch-intent": "task",
    "dispatch-rejected": "task",
    "duplicate-message": "optional-task",
    "heartbeat": "task",
    "initialize": "graph",
    "lease-expired": "task",
    "message-rejected": "optional-task",
    "readiness-refreshed": "task",
    "result-received": "task",
    "result-terminal": "task",
    "verification-blocked": "task",
    "verification-completed": "task",
    "wall-time-observed": "graph",
    "worktree-observed": "task",
    "worktree-request": "task",
}

_UNCHANGED_TRANSITIONS: set[tuple[str | None, str]] = {(None, state.value) for state in TaskState}
_READINESS_STATES = {
    TaskState.PLANNED.value,
    TaskState.READY.value,
    TaskState.BLOCKED.value,
}

_EVENT_TRANSITIONS: dict[str, set[tuple[str | None, str]]] = {
    "approval-consumed": {
        (TaskState.READY.value, TaskState.READY.value),
        (TaskState.RUNNING.value, TaskState.RUNNING.value),
    },
    "approval-proposal-expired": {
        (TaskState.BLOCKED.value, TaskState.READY.value),
        (TaskState.RUNNING.value, TaskState.READY.value),
    },
    "approval-received": _UNCHANGED_TRANSITIONS,
    "cancel-acknowledgement": {
        (TaskState.RUNNING.value, TaskState.BLOCKED.value),
        (TaskState.RUNNING.value, TaskState.SUPERSEDED.value),
    },
    "cancel-request": {(TaskState.RUNNING.value, TaskState.RUNNING.value)},
    "dispatch-accepted": {(TaskState.RUNNING.value, TaskState.RUNNING.value)},
    "dispatch-approval-blocked": {
        (TaskState.READY.value, TaskState.BLOCKED.value),
        (TaskState.RUNNING.value, TaskState.RUNNING.value),
    },
    "dispatch-budget-blocked": {
        (TaskState.READY.value, TaskState.BLOCKED.value),
        (TaskState.RUNNING.value, TaskState.BLOCKED.value),
        (TaskState.RUNNING.value, TaskState.RUNNING.value),
    },
    "dispatch-intent": {
        (TaskState.READY.value, TaskState.RUNNING.value),
        (TaskState.RUNNING.value, TaskState.RUNNING.value),
    },
    "dispatch-rejected": {
        (TaskState.RUNNING.value, TaskState.BLOCKED.value),
        (TaskState.RUNNING.value, TaskState.READY.value),
    },
    "duplicate-message": _UNCHANGED_TRANSITIONS,
    "heartbeat": {(TaskState.RUNNING.value, TaskState.RUNNING.value)},
    "lease-expired": {
        (TaskState.RUNNING.value, TaskState.BLOCKED.value),
        (TaskState.RUNNING.value, TaskState.READY.value),
    },
    "message-rejected": _UNCHANGED_TRANSITIONS,
    "readiness-refreshed": {
        (before, after) for before in _READINESS_STATES for after in _READINESS_STATES
    },
    "result-received": {(TaskState.RUNNING.value, TaskState.VERIFICATION.value)},
    "result-terminal": {
        (TaskState.RUNNING.value, TaskState.BLOCKED.value),
        (TaskState.RUNNING.value, TaskState.READY.value),
        (TaskState.RUNNING.value, TaskState.REJECTED.value),
    },
    "verification-blocked": {(TaskState.VERIFICATION.value, TaskState.BLOCKED.value)},
    "verification-completed": {(TaskState.VERIFICATION.value, TaskState.COMPLETED.value)},
    "worktree-observed": {
        (TaskState.RUNNING.value, TaskState.BLOCKED.value),
        (TaskState.RUNNING.value, TaskState.RUNNING.value),
    },
    "worktree-request": {(TaskState.READY.value, TaskState.RUNNING.value)},
}

_EVENT_PROJECTION_MUTATIONS: dict[str, frozenset[str]] = {
    "approval-consumed": frozenset(),
    "approval-proposal-expired": frozenset(
        {"state", "dispatch_phase", "attempt", "fence", "blockers"}
    ),
    "approval-received": frozenset(),
    "cancel-acknowledgement": frozenset({"state", "dispatch_phase", "outcome", "blockers"}),
    "cancel-request": frozenset({"dispatch_phase"}),
    "dispatch-accepted": frozenset({"dispatch_phase"}),
    "dispatch-approval-blocked": frozenset({"state", "attempt", "fence", "blockers"}),
    "dispatch-budget-blocked": frozenset({"state", "dispatch_phase", "outcome", "blockers"}),
    "dispatch-intent": frozenset(
        {"state", "dispatch_phase", "outcome", "attempt", "fence", "blockers"}
    ),
    "dispatch-rejected": frozenset({"state", "dispatch_phase", "outcome", "blockers"}),
    "duplicate-message": frozenset(),
    "heartbeat": frozenset(),
    "lease-expired": frozenset({"state", "dispatch_phase", "outcome", "blockers"}),
    "message-rejected": frozenset(),
    "readiness-refreshed": frozenset({"state", "blockers"}),
    "result-received": frozenset({"state", "dispatch_phase", "outcome", "blockers"}),
    "result-terminal": frozenset({"state", "dispatch_phase", "outcome", "blockers"}),
    "verification-blocked": frozenset({"state", "outcome", "blockers"}),
    "verification-completed": frozenset({"state", "outcome", "blockers"}),
    "worktree-observed": frozenset({"state", "dispatch_phase", "outcome", "blockers"}),
    "worktree-request": frozenset({"state", "outcome", "attempt", "fence", "blockers"}),
}

_SCHEDULER_ACTOR_CAUSES = {
    "approval-consumed",
    "approval-proposal-expired",
    "cancel-request",
    "dispatch-budget-blocked",
    "dispatch-intent",
    "duplicate-message",
    "initialize",
    "lease-expired",
    "message-rejected",
    "readiness-refreshed",
    "verification-blocked",
    "verification-completed",
    "wall-time-observed",
    "worktree-request",
}

_NON_RESULT_LEASE_HISTORY_OUTPUT_CAUSES = {
    "approval-proposal-expired",
    "cancel-acknowledgement",
    "dispatch-approval-blocked",
    "dispatch-intent",
    "dispatch-rejected",
    "heartbeat",
    "lease-expired",
    "worktree-observed",
    "worktree-request",
}

_EVENT_BUDGET_CAUSES = {
    "cancel-acknowledgement",
    "dispatch-accepted",
    "dispatch-budget-blocked",
    "dispatch-intent",
    "dispatch-rejected",
    "lease-expired",
    "result-received",
    "result-terminal",
    "wall-time-observed",
    "worktree-observed",
    "worktree-request",
}

_EVENT_REASON_CAUSES = {
    "approval-proposal-expired",
    "cancel-acknowledgement",
    "dispatch-approval-blocked",
    "dispatch-budget-blocked",
    "dispatch-rejected",
    "duplicate-message",
    "lease-expired",
    "initialize",
    "message-rejected",
    "readiness-refreshed",
    "result-terminal",
    "verification-blocked",
    "worktree-observed",
}

if set(_EVENT_SCOPES) != set(EVENT_CAUSES) or set(_EVENT_TRANSITIONS) != {
    cause for cause, scope in _EVENT_SCOPES.items() if scope != "graph"
}:
    raise RuntimeError("Scheduler event semantic dispatch must cover every allowed cause.")

_SCHEMA = """
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE task_graph (
    graph_id TEXT PRIMARY KEY,
    artifact_json TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    definition_json TEXT NOT NULL,
    wave INTEGER NOT NULL CHECK (wave >= 0),
    topological_rank INTEGER NOT NULL CHECK (topological_rank >= 0),
    state TEXT NOT NULL,
    dispatch_phase TEXT NOT NULL,
    outcome TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt BETWEEN 0 AND 3),
    fence INTEGER NOT NULL CHECK (fence >= 0),
    blockers_json TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    dependency_id TEXT NOT NULL REFERENCES tasks(task_id),
    PRIMARY KEY (task_id, dependency_id)
) WITHOUT ROWID;
CREATE TABLE events (
    sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
    artifact_id TEXT NOT NULL UNIQUE,
    event_sha256 TEXT NOT NULL,
    previous_sha256 TEXT NOT NULL,
    artifact_json TEXT NOT NULL
);
CREATE TABLE messages (
    sequence INTEGER PRIMARY KEY CHECK (sequence > 0),
    artifact_id TEXT NOT NULL UNIQUE,
    message_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    task_id TEXT,
    idempotency_key TEXT,
    artifact_json TEXT NOT NULL
);
CREATE TABLE lease_history (
    event_sequence INTEGER NOT NULL REFERENCES events(sequence)
        DEFERRABLE INITIALLY DEFERRED,
    artifact_id TEXT NOT NULL,
    authority_lease_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    fence INTEGER NOT NULL CHECK (fence > 0),
    status TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    PRIMARY KEY (event_sequence, artifact_id)
) WITHOUT ROWID;
CREATE TABLE current_leases (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    lease_id TEXT NOT NULL UNIQUE,
    projection_artifact_id TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt BETWEEN 1 AND 3),
    fence INTEGER NOT NULL CHECK (fence > 0),
    idempotency_key TEXT NOT NULL UNIQUE,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    artifact_json TEXT NOT NULL
) WITHOUT ROWID;
CREATE UNIQUE INDEX current_lease_owner_task ON current_leases(task_id, owner_id);
CREATE TABLE budget_entries (
    event_sequence INTEGER PRIMARY KEY REFERENCES events(sequence),
    artifact_id TEXT NOT NULL UNIQUE,
    artifact_json TEXT NOT NULL
);
CREATE TABLE budget_totals (
    resource TEXT PRIMARY KEY,
    reserved INTEGER NOT NULL CHECK (reserved >= 0),
    used INTEGER NOT NULL CHECK (used >= 0),
    availability TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE worktree_lease_history (
    event_sequence INTEGER NOT NULL REFERENCES events(sequence)
        DEFERRABLE INITIALLY DEFERRED,
    artifact_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    status TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    PRIMARY KEY (event_sequence, artifact_id)
) WITHOUT ROWID;
CREATE TABLE current_worktree_leases (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    artifact_id TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL,
    fence INTEGER NOT NULL CHECK (fence > 0),
    worktree TEXT NOT NULL UNIQUE,
    artifact_json TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE approval_consumptions (
    approval_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE REFERENCES messages(artifact_id),
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    event_sequence INTEGER NOT NULL REFERENCES events(sequence)
        DEFERRABLE INITIALLY DEFERRED
) WITHOUT ROWID;
"""


class SchedulerAdapterError(SchedulerContractError):
    """A scheduler persistence or host boundary failed closed."""


@dataclass(frozen=True, slots=True)
class SchedulerTick:
    """One bounded transaction result."""

    state: LoadedSchedulerArtifact
    outgoing: tuple[LoadedSchedulerArtifact, ...]
    accepted_message_ids: tuple[str, ...]
    rejected_message_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.to_dict(),
            "outgoing": [item.to_dict() for item in self.outgoing],
            "accepted_message_ids": list(self.accepted_message_ids),
            "rejected_message_ids": list(self.rejected_message_ids),
        }


class SystemSchedulerClock:
    """System UTC clock for scheduler transactions."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class ExclusiveSchedulerArtifactStore:
    """Root-confined exclusive immutable JSON publication."""

    def __init__(self, root: Path) -> None:
        self._root = _regular_root(root)

    def publish(self, output: Path, content: bytes) -> None:
        target = _path_under_root(self._root, output, suffix=".json", existing=False)
        descriptor = -1
        temporary: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            temporary = Path(name)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, target)
            if not os.path.samefile(temporary, target):
                raise SchedulerAdapterError("Artifact publication identity is indeterminate.")
        except FileExistsError as exc:
            raise SchedulerAdapterError("Artifact output already exists.") from exc
        except SchedulerAdapterError:
            raise
        except OSError as exc:
            raise SchedulerAdapterError("Artifact publication failed or is indeterminate.") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class UnsupportedAgentHost:
    """Explicitly non-dispatching packaged host adapter."""

    def dispatch(self, message: MailboxMessage) -> None:
        del message
        raise SchedulerAdapterError("Agent dispatch is host-owned and unsupported here.")

    def cancel(self, message: MailboxMessage) -> None:
        del message
        raise SchedulerAdapterError("Agent cancellation is host-owned and unsupported here.")


class UnsupportedWorktreeHost:
    """Explicitly non-mutating packaged worktree adapter."""

    def request(self, message: MailboxMessage) -> None:
        del message
        raise SchedulerAdapterError("Worktree mutation is host-owned and unsupported here.")


class SQLiteSchedulerStore:
    """Canonical schema-1 transactional scheduler store."""

    def __init__(self, state: Path, root: Path) -> None:
        self._root = _regular_root(root)
        self._path = _path_under_root(self._root, state, suffix=".sqlite3", existing=True)

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def initialize(
        cls,
        state: Path,
        root: Path,
        graph_artifact: LoadedSchedulerArtifact,
        now: datetime,
        *,
        lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
        heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> SQLiteSchedulerStore:
        """Create, validate, and exclusively publish a fresh database."""

        if graph_artifact.artifact_type is not SchedulerArtifactType.TASK_GRAPH:
            raise SchedulerAdapterError("Scheduler initialization requires a Task Graph.")
        graph = graph_artifact.value
        assert isinstance(graph, TaskGraph)
        _validate_lease_policy(lease_ttl_seconds, heartbeat_interval_seconds)
        resolved_root = _regular_root(root)
        target = _path_under_root(resolved_root, state, suffix=".sqlite3", existing=False)
        timestamp = format_utc(now)
        descriptor = -1
        temporary: Path | None = None
        linked = False
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            os.close(descriptor)
            descriptor = -1
            temporary = Path(name)
            connection = sqlite3.connect(temporary, timeout=0, isolation_level=None)
            try:
                _configure(connection)
                connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version = {USER_VERSION}")
                connection.executescript(_SCHEMA)
                connection.execute("BEGIN IMMEDIATE")
                try:
                    cls._seed(
                        connection,
                        graph_artifact,
                        graph,
                        timestamp,
                        lease_ttl_seconds,
                        heartbeat_interval_seconds,
                    )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
            finally:
                connection.close()
            _validate_database_path(temporary)
            _validate_connection_file(temporary)
            os.link(temporary, target)
            linked = True
            if not os.path.samefile(temporary, target):
                raise SchedulerAdapterError("Database publication identity is indeterminate.")
        except FileExistsError as exc:
            raise SchedulerAdapterError("Scheduler state output already exists.") from exc
        except SchedulerAdapterError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise SchedulerAdapterError(
                "Scheduler initialization failed or publication is indeterminate."
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        if not linked:
            raise SchedulerAdapterError("Scheduler database was not published.")
        store = cls(target, resolved_root)
        store.validate()
        return store

    @staticmethod
    def _seed(
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        timestamp: str,
        lease_ttl_seconds: int,
        heartbeat_interval_seconds: int,
    ) -> None:
        graph_json = _artifact_json(graph_artifact)
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("schema_version", SCHEMA_VERSION),
                ("graph_id", graph_artifact.artifact_id),
                ("created_at", timestamp),
                ("lease_ttl_seconds", str(lease_ttl_seconds)),
                ("heartbeat_interval_seconds", str(heartbeat_interval_seconds)),
                ("host_capabilities", "{}"),
            ),
        )
        connection.execute(
            "INSERT INTO task_graph(graph_id, artifact_json) VALUES (?, ?)",
            (graph_artifact.artifact_id, graph_json),
        )
        ranks = topological_ranks(graph)
        for task in graph.tasks:
            state = TaskState.READY if not task.dependencies else TaskState.PLANNED
            connection.execute(
                """INSERT INTO tasks(
                    task_id, definition_json, wave, topological_rank, state,
                    dispatch_phase, outcome, attempt, fence, blockers_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, '[]')""",
                (
                    task.task_id,
                    canonical_json_bytes(task.to_dict()).decode("ascii"),
                    task.wave,
                    ranks[task.task_id],
                    state.value,
                    DispatchPhase.NOT_DISPATCHED.value,
                    TaskOutcome.NONE.value,
                ),
            )
            connection.executemany(
                "INSERT INTO dependencies(task_id, dependency_id) VALUES (?, ?)",
                ((task.task_id, dependency) for dependency in task.dependencies),
            )
        availability = {
            name: (
                "not_available"
                if name == "microunits" and graph.budget.cost_status == "not_available"
                else "available"
            )
            for name in RESOURCE_NAMES
        }
        connection.executemany(
            "INSERT INTO budget_totals(resource, reserved, used, availability) VALUES (?, 0, 0, ?)",
            ((name, availability[name]) for name in RESOURCE_NAMES),
        )
        event = SchedulerEvent(
            sequence=1,
            previous_event_sha256="0" * 64,
            actor="scheduler",
            cause="initialize",
            graph_id=graph_artifact.artifact_id,
            task_id=None,
            candidate=graph.candidate,
            context_snapshot_id=None,
            before_state=None,
            after_state=None,
            lease_id=None,
            message_id=None,
            result_id=None,
            approval_id=None,
            budget_deltas={},
            task_projection=None,
            reason=_lease_policy_reason(
                lease_ttl_seconds,
                heartbeat_interval_seconds,
            ),
            recorded_at=timestamp,
        )
        event_artifact = artifact_from_value(SchedulerArtifactType.SCHEDULER_EVENT, event)
        digest = event_digest(event_artifact)
        connection.execute(
            "INSERT INTO events(sequence, artifact_id, event_sha256, previous_sha256, "
            "artifact_json) VALUES (1, ?, ?, ?, ?)",
            (event_artifact.artifact_id, digest, "0" * 64, _artifact_json(event_artifact)),
        )
        ledger = BudgetLedger(
            graph_id=graph_artifact.artifact_id,
            limits=graph.budget,
            reserved={name: 0 for name in RESOURCE_NAMES},
            used={name: 0 for name in RESOURCE_NAMES},
            availability=availability,
            blocker_codes=(),
            event_sequence=1,
        )
        ledger_artifact = artifact_from_value(SchedulerArtifactType.BUDGET_LEDGER, ledger)
        connection.execute(
            "INSERT INTO budget_entries(event_sequence, artifact_id, artifact_json) "
            "VALUES (1, ?, ?)",
            (ledger_artifact.artifact_id, _artifact_json(ledger_artifact)),
        )

    def validate(self) -> None:
        """Validate SQLite settings, exact shape, immutable records, and chain."""

        _validate_database_path(self._path)
        try:
            connection = self._connect(read_only=True)
            try:
                self._validate_connection(connection)
            finally:
                connection.close()
        except SchedulerAdapterError:
            raise
        except sqlite3.Error as exc:
            raise SchedulerAdapterError("Scheduler database validation failed.") from exc

    def validate_evidence(self) -> None:
        """Validate immutable evidence while allowing mutable projection drift."""

        _validate_database_path(self._path)
        try:
            connection = self._connect(read_only=True)
            try:
                self._validate_evidence_connection(connection)
            finally:
                connection.close()
        except SchedulerAdapterError:
            raise
        except sqlite3.Error as exc:
            raise SchedulerAdapterError("Scheduler evidence validation failed.") from exc

    def graph_artifact(self) -> LoadedSchedulerArtifact:
        with self._read_connection() as connection:
            row = connection.execute("SELECT artifact_json FROM task_graph").fetchone()
            if row is None:
                raise SchedulerAdapterError("Scheduler Task Graph is missing.")
            return _parse_artifact_json(row[0], SchedulerArtifactType.TASK_GRAPH)

    def status(self) -> LoadedSchedulerArtifact:
        with self._read_connection() as connection:
            return self._status(connection)

    def wait_for_projection(self) -> dict[str, tuple[str, ...]]:
        """Return typed wait edges projected from the validated durable store."""

        with self._read_connection() as connection:
            graph_artifact = self._graph(connection)
            graph = graph_artifact.value
            assert isinstance(graph, TaskGraph)
            state_artifact = self._status(connection)
            state = state_artifact.value
            assert isinstance(state, SchedulerState)
            projections = {item.task_id: item for item in state.tasks}
            tasks = {item.task_id: item for item in graph.tasks}
            current_leases = {
                str(row["task_id"]): row
                for row in connection.execute("SELECT * FROM current_leases").fetchall()
            }
            current_worktrees = {
                str(row["task_id"]): row
                for row in connection.execute("SELECT * FROM current_worktree_leases").fetchall()
            }
            edges: dict[str, set[str]] = {}

            def add(source: str, target: str) -> None:
                edges.setdefault(source, set()).add(target)

            for task_id, row in current_worktrees.items():
                add(f"worktree:{row['worktree']}", f"task:{task_id}")

            terminal = {TaskState.COMPLETED, TaskState.REJECTED, TaskState.SUPERSEDED}
            for task in graph.tasks:
                projection = projections[task.task_id]
                if projection.state in terminal:
                    continue
                node = f"task:{task.task_id}"
                for dependency in task.dependencies:
                    if projections[dependency].state is not TaskState.COMPLETED:
                        add(node, f"task:{dependency}")
                for target in task.review_targets:
                    if projections[target].state is not TaskState.COMPLETED:
                        add(node, f"task:{target}")
                lease_row = current_leases.get(task.task_id)
                owner = None if lease_row is None else str(lease_row["owner_id"])
                for blocker in projection.blockers:
                    if blocker.code == "missing-capability":
                        authority = "unassigned" if owner is None else owner
                        for reference in blocker.references:
                            capability_node = f"capability:{authority}:{reference}"
                            add(node, capability_node)
                            if reference.startswith("task:"):
                                provider = reference.removeprefix("task:")
                                if provider in tasks:
                                    add(capability_node, f"task:{provider}")
                    elif blocker.code == "approval-required":
                        for approval_type in task.approval_stops:
                            add(node, f"approval:{approval_type}:{task.task_id}")
                    elif blocker.code == "budget-exhausted":
                        add(node, "budget:scheduler")
                    elif blocker.code == "worktree-unavailable":
                        assert task.worktree_assignment is not None
                        add(node, f"worktree:{task.worktree_assignment}")
                    elif blocker.code in {
                        "dependency-terminal-blocker",
                        "review-targets-unsatisfied",
                    }:
                        for reference in blocker.references:
                            add(node, f"task:{reference}")
                    else:
                        references = blocker.references or (task.task_id,)
                        for reference in references:
                            add(node, f"blocker:{blocker.code}:{reference}")
                if lease_row is None:
                    continue
                phase = projection.dispatch_phase
                lease_id = str(lease_row["lease_id"])
                if phase is DispatchPhase.INTENT_PENDING:
                    add(node, f"lease:{lease_id}:dispatch-ack")
                elif phase is DispatchPhase.ACCEPTED:
                    add(node, f"lease:{lease_id}:result")
                elif phase is DispatchPhase.CANCELLATION_REQUESTED:
                    add(node, f"lease:{lease_id}:cancel-ack")
                elif phase is DispatchPhase.NOT_DISPATCHED:
                    worktree_row = current_worktrees.get(task.task_id)
                    if worktree_row is not None:
                        worktree = _parse_artifact_json(
                            worktree_row["artifact_json"],
                            SchedulerArtifactType.WORKTREE_LEASE,
                        ).value
                        assert isinstance(worktree, WorktreeLease)
                        if worktree.status is WorktreeLeaseStatus.REQUESTED:
                            add(node, f"worktree-observation:{worktree.worktree}")
                        elif not projection.blockers:
                            add(node, f"lease:{lease_id}:dispatch")
            return {
                node: tuple(sorted(targets)) for node, targets in sorted(edges.items()) if targets
            }

    def tick(
        self,
        root: Path,
        host_id: str,
        messages: Iterable[LoadedSchedulerArtifact],
        now: datetime,
        *,
        lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
        heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> SchedulerTick:
        """Ingest messages, recover expiries, and dispatch ready work atomically."""

        try:
            strict_host_id(host_id, "tick host_id")
        except SchedulerContractError as exc:
            raise SchedulerAdapterError("tick host_id must be a host identifier.") from exc
        _validate_lease_policy(lease_ttl_seconds, heartbeat_interval_seconds)
        timestamp = format_utc(now)
        accepted: list[str] = []
        rejected: list[str] = []
        outgoing: list[LoadedSchedulerArtifact] = []
        with self._transaction() as connection:
            graph_artifact = self._graph(connection)
            graph = graph_artifact.value
            assert isinstance(graph, TaskGraph)
            if self._lease_policy(connection) != (
                lease_ttl_seconds,
                heartbeat_interval_seconds,
            ):
                raise SchedulerAdapterError(
                    "Tick Lease policy differs from the immutable initialization policy."
                )
            validate_task_graph_inputs(graph_artifact, Path(root))
            self._observe_wall_time(connection, graph_artifact, graph, timestamp)
            self._expire_leases(connection, graph_artifact, graph, timestamp)
            for artifact in messages:
                if artifact.artifact_type is not SchedulerArtifactType.MAILBOX_MESSAGE:
                    raise SchedulerAdapterError("tick input must contain Mailbox Messages.")
                message = artifact.value
                assert isinstance(message, MailboxMessage)
                if self._ingest_message(
                    connection,
                    Path(root),
                    graph_artifact,
                    graph,
                    host_id,
                    artifact,
                    message,
                    timestamp,
                    outgoing,
                ):
                    accepted.append(artifact.artifact_id)
                else:
                    rejected.append(artifact.artifact_id)
            self._refresh_ready(connection, graph_artifact, graph, host_id, timestamp)
            outgoing.extend(
                self._retry_budget_blocked_worktrees(
                    connection,
                    graph_artifact,
                    graph,
                    timestamp,
                )
            )
            outgoing.extend(
                self._dispatch_ready(
                    connection,
                    graph_artifact,
                    graph,
                    host_id,
                    timestamp,
                    lease_ttl_seconds,
                    heartbeat_interval_seconds,
                )
            )
            state = self._status(connection)
        return SchedulerTick(
            state=state,
            outgoing=tuple(outgoing),
            accepted_message_ids=tuple(sorted(accepted)),
            rejected_message_ids=tuple(sorted(rejected)),
        )

    def export(
        self,
        kind: str,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> tuple[LoadedSchedulerArtifact, ...]:
        """Return a bounded deterministic portable projection."""

        if kind not in {"state", "leases", "messages", "events", "budget", "worktrees"}:
            raise SchedulerAdapterError("Scheduler export kind is unsupported.")
        if after_sequence < 0 or not 1 <= limit <= MAX_EXPORT:
            raise SchedulerAdapterError("Scheduler export bounds are invalid.")
        if kind == "state":
            return (self.status(),)
        queries = {
            "leases": (
                "SELECT artifact_json FROM lease_history WHERE event_sequence > ? "
                "ORDER BY event_sequence, artifact_id LIMIT ?",
                SchedulerArtifactType.LEASE,
            ),
            "messages": (
                "SELECT artifact_json FROM messages WHERE sequence > ? ORDER BY sequence LIMIT ?",
                SchedulerArtifactType.MAILBOX_MESSAGE,
            ),
            "events": (
                "SELECT artifact_json FROM events WHERE sequence > ? ORDER BY sequence LIMIT ?",
                SchedulerArtifactType.SCHEDULER_EVENT,
            ),
            "budget": (
                "SELECT artifact_json FROM budget_entries WHERE event_sequence > ? "
                "ORDER BY event_sequence LIMIT ?",
                SchedulerArtifactType.BUDGET_LEDGER,
            ),
            "worktrees": (
                "SELECT artifact_json FROM worktree_lease_history WHERE "
                "event_sequence > ? ORDER BY event_sequence, artifact_id LIMIT ?",
                SchedulerArtifactType.WORKTREE_LEASE,
            ),
        }
        statement, expected = queries[kind]
        with self._read_connection() as connection:
            rows = connection.execute(statement, (after_sequence, limit)).fetchall()
        return tuple(_parse_artifact_json(row[0], expected) for row in rows)

    def request_cancel(
        self,
        root: Path,
        host_id: str,
        task_id: str,
        reason: str,
        now: datetime,
    ) -> LoadedSchedulerArtifact:
        """Durably create or replay one scheduler-authored cooperative cancel intent."""

        try:
            strict_host_id(host_id, "cancel host_id")
            strict_reason(reason, "cancel reason")
        except SchedulerContractError as exc:
            raise SchedulerAdapterError("Cancellation request arguments are invalid.") from exc
        timestamp = format_utc(now)
        expired_target = False
        with self._transaction() as connection:
            graph_artifact = self._graph(connection)
            graph = graph_artifact.value
            assert isinstance(graph, TaskGraph)
            self._observe_wall_time(connection, graph_artifact, graph, timestamp)
            current = connection.execute(
                "SELECT * FROM current_leases WHERE task_id = ?", (task_id,)
            ).fetchone()
            if (
                current is not None
                and current["owner_id"] == host_id
                and parse_utc(timestamp) >= parse_utc(str(current["expires_at"]))
            ):
                self._expire_leases(connection, graph_artifact, graph, timestamp)
                expired_target = True
        if expired_target:
            raise SchedulerAdapterError("Cancellation requires the current host-owned lease.")
        with self._transaction() as connection:
            graph_artifact = self._graph(connection)
            graph = graph_artifact.value
            assert isinstance(graph, TaskGraph)
            validate_task_graph_inputs(graph_artifact, Path(root))
            task = next((item for item in graph.tasks if item.task_id == task_id), None)
            self._observe_wall_time(connection, graph_artifact, graph, timestamp)
            self._expire_leases(connection, graph_artifact, graph, timestamp)
            current = connection.execute(
                "SELECT * FROM current_leases WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None or current is None or current["owner_id"] != host_id:
                raise SchedulerAdapterError("Cancellation requires the current host-owned lease.")
            existing_rows = connection.execute(
                "SELECT artifact_json FROM messages WHERE message_type = ? AND task_id = ? "
                "ORDER BY sequence DESC",
                (MessageType.CANCEL_REQUEST.value, task_id),
            ).fetchall()
            for row in existing_rows:
                existing = _parse_artifact_json(
                    row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
                )
                value = existing.value
                assert isinstance(value, MailboxMessage)
                if value.lease_id == current["lease_id"]:
                    return existing
            task_row = connection.execute(
                "SELECT state, dispatch_phase FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None or task_row["state"] != TaskState.RUNNING.value:
                raise SchedulerAdapterError("Cancellation has no active host intent.")
            phase = DispatchPhase(str(task_row["dispatch_phase"]))
            expected_cause = (
                "worktree-request"
                if phase is DispatchPhase.NOT_DISPATCHED
                else (
                    "dispatch-intent"
                    if phase in {DispatchPhase.INTENT_PENDING, DispatchPhase.ACCEPTED}
                    else None
                )
            )
            parent_entry = next(
                (
                    entry
                    for entry in reversed(_adopted_message_entries(connection))
                    if expected_cause is not None
                    and entry[0].cause == expected_cause
                    and entry[0].task_id == task_id
                    and entry[0].lease_id == current["lease_id"]
                    and entry[2].task_id == task_id
                    and entry[2].lease_id == current["lease_id"]
                    and entry[2].recipient == current["owner_id"]
                ),
                None,
            )
            if parent_entry is None:
                raise SchedulerAdapterError("Cancellation has no active host intent.")
            _, parent_id, _, _ = parent_entry
            binding = next(
                item for item in graph.contexts if item.artifact_id == task.context_snapshot_id
            )
            message = MailboxMessage(
                message_type=MessageType.CANCEL_REQUEST,
                direction=MessageDirection.SCHEDULER_TO_HOST,
                sender="HST-SCHEDULER",
                recipient=host_id,
                graph_id=graph_artifact.artifact_id,
                task_id=task.task_id,
                candidate=graph.candidate,
                context_snapshot_id=task.context_snapshot_id,
                attempt=current["attempt"],
                lease_id=current["lease_id"],
                fence=current["fence"],
                idempotency_key=current["idempotency_key"],
                sensitivity=binding.sensitivity,
                provenance=(binding.reference,),
                causal_parent_message_ids=(parent_id,),
                recorded_at=timestamp,
                payload={"reason": reason},
            )
            artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, message)
            self._insert_message(connection, artifact, message)
            state_row = connection.execute(
                "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            connection.execute(
                "UPDATE tasks SET dispatch_phase = ? WHERE task_id = ?",
                (DispatchPhase.CANCELLATION_REQUESTED.value, task_id),
            )
            self._append_event(
                connection,
                graph_artifact,
                timestamp,
                actor="scheduler",
                cause="cancel-request",
                task_id=task.task_id,
                context_snapshot_id=task.context_snapshot_id,
                before_state=state_row["state"],
                after_state=state_row["state"],
                lease_id=current["lease_id"],
                message_id=artifact.artifact_id,
            )
            return artifact

    def inspect_mailbox(
        self,
        *,
        task_id: str | None = None,
        direction: str | None = None,
        limit: int = 100,
    ) -> tuple[LoadedSchedulerArtifact, ...]:
        """Read a bounded mailbox view without mutation."""

        if not 1 <= limit <= MAX_EXPORT:
            raise SchedulerAdapterError("Mailbox limit is invalid.")
        clauses: list[str] = []
        parameters: list[object] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            parameters.append(task_id)
        if direction is not None:
            if direction not in {item.value for item in MessageDirection}:
                raise SchedulerAdapterError("Mailbox direction is unsupported.")
            clauses.append("direction = ?")
            parameters.append(direction)
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        statement = "SELECT artifact_json FROM messages" + where + " ORDER BY sequence DESC LIMIT ?"
        parameters.append(limit)
        with self._read_connection() as connection:
            rows = connection.execute(statement, parameters).fetchall()
        rows.reverse()
        return tuple(
            _parse_artifact_json(row[0], SchedulerArtifactType.MAILBOX_MESSAGE) for row in rows
        )

    def _connect(self, *, read_only: bool) -> sqlite3.Connection:
        if read_only:
            uri = self._path.as_uri() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=0, isolation_level=None)
        else:
            connection = sqlite3.connect(self._path, timeout=0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        _configure(connection)
        if read_only:
            connection.execute("PRAGMA query_only = ON")
        return connection

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        self.validate()
        connection = self._connect(read_only=True)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self.validate()
        connection = self._connect(read_only=False)
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            self._validate_connection(connection)
            connection.commit()
        except sqlite3.OperationalError as exc:
            connection.rollback()
            raise SchedulerAdapterError("Scheduler store is busy or unavailable.") from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _validate_connection(self, connection: sqlite3.Connection) -> None:
        graph = self._validate_evidence_connection(connection)
        self._validate_projections(connection, graph)

    def _validate_evidence_connection(
        self, connection: sqlite3.Connection
    ) -> LoadedSchedulerArtifact:
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if application_id != APPLICATION_ID or user_version != USER_VERSION:
            raise SchedulerAdapterError("Scheduler database version identity is invalid.")
        integrity = connection.execute("PRAGMA integrity_check(1)").fetchone()[0]
        if integrity != "ok":
            raise SchedulerAdapterError("Scheduler database integrity check failed.")
        rows = connection.execute(
            "SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        tables = {str(row["name"]) for row in rows if row["type"] == "table"}
        if tables != TABLE_NAMES or any(row["type"] in {"trigger", "view"} for row in rows):
            raise SchedulerAdapterError("Scheduler database schema shape is unexpected.")
        if _schema_signature(connection) != _expected_schema_signature():
            raise SchedulerAdapterError("Scheduler database schema definition drifted.")
        metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
        if set(metadata) != {
            "schema_version",
            "graph_id",
            "created_at",
            "lease_ttl_seconds",
            "heartbeat_interval_seconds",
            "host_capabilities",
        }:
            raise SchedulerAdapterError("Scheduler metadata shape is invalid.")
        if metadata["schema_version"] != SCHEMA_VERSION:
            raise SchedulerAdapterError("Scheduler metadata version is unsupported.")
        try:
            parse_utc(metadata["created_at"])
            lease_ttl_seconds = int(metadata["lease_ttl_seconds"])
            heartbeat_interval_seconds = int(metadata["heartbeat_interval_seconds"])
            capabilities = json.loads(metadata["host_capabilities"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SchedulerAdapterError("Scheduler metadata values are invalid.") from exc
        if (
            str(lease_ttl_seconds) != metadata["lease_ttl_seconds"]
            or str(heartbeat_interval_seconds) != metadata["heartbeat_interval_seconds"]
        ):
            raise SchedulerAdapterError("Scheduler Lease policy metadata is noncanonical.")
        _validate_lease_policy(lease_ttl_seconds, heartbeat_interval_seconds)
        if not isinstance(capabilities, dict) or any(
            not isinstance(owner, str)
            or not isinstance(items, list)
            or any(not isinstance(item, str) for item in items)
            for owner, items in capabilities.items()
        ):
            raise SchedulerAdapterError("Scheduler host capabilities are invalid.")
        for owner in capabilities:
            strict_host_id(owner, "capability owner")
        graph = self._graph(connection)
        if graph.artifact_id != metadata["graph_id"]:
            raise SchedulerAdapterError("Scheduler graph metadata drifted.")
        self._validate_events(
            connection,
            graph,
            str(metadata["created_at"]),
            lease_ttl_seconds,
            heartbeat_interval_seconds,
        )
        self._validate_immutable_rows(connection)
        self._validate_message_adoption(connection)
        graph_value = graph.value
        assert isinstance(graph_value, TaskGraph)
        self._validate_budget_evidence(connection, graph, graph_value)
        return graph

    def _graph(self, connection: sqlite3.Connection) -> LoadedSchedulerArtifact:
        rows = connection.execute("SELECT graph_id, artifact_json FROM task_graph").fetchall()
        if len(rows) != 1:
            raise SchedulerAdapterError("Scheduler must contain exactly one Task Graph.")
        artifact = _parse_artifact_json(rows[0]["artifact_json"], SchedulerArtifactType.TASK_GRAPH)
        if artifact.artifact_id != rows[0]["graph_id"]:
            raise SchedulerAdapterError("Stored Task Graph identity is invalid.")
        return artifact

    @staticmethod
    def _lease_policy(connection: sqlite3.Connection) -> tuple[int, int]:
        metadata = dict(
            connection.execute(
                "SELECT key, value FROM metadata WHERE key IN "
                "('lease_ttl_seconds', 'heartbeat_interval_seconds')"
            ).fetchall()
        )
        if set(metadata) != {"lease_ttl_seconds", "heartbeat_interval_seconds"}:
            raise SchedulerAdapterError("Scheduler Lease policy metadata is missing.")
        try:
            ttl_seconds = int(metadata["lease_ttl_seconds"])
            heartbeat_interval_seconds = int(metadata["heartbeat_interval_seconds"])
        except (TypeError, ValueError) as exc:
            raise SchedulerAdapterError("Scheduler Lease policy metadata is invalid.") from exc
        if (
            str(ttl_seconds) != metadata["lease_ttl_seconds"]
            or str(heartbeat_interval_seconds) != metadata["heartbeat_interval_seconds"]
        ):
            raise SchedulerAdapterError("Scheduler Lease policy metadata is noncanonical.")
        _validate_lease_policy(ttl_seconds, heartbeat_interval_seconds)
        return ttl_seconds, heartbeat_interval_seconds

    def _validate_events(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        created_at: str,
        lease_ttl_seconds: int,
        heartbeat_interval_seconds: int,
    ) -> None:
        rows = connection.execute(
            "SELECT sequence, artifact_id, event_sha256, previous_sha256, "
            "artifact_json FROM events ORDER BY sequence"
        ).fetchall()
        if not rows:
            raise SchedulerAdapterError("Scheduler event chain is empty.")
        graph = graph_artifact.value
        assert isinstance(graph, TaskGraph)
        projections = {
            task.task_id: TaskProjection(
                task_id=task.task_id,
                state=TaskState.READY if not task.dependencies else TaskState.PLANNED,
                dispatch_phase=DispatchPhase.NOT_DISPATCHED,
                outcome=TaskOutcome.NONE,
                attempt=0,
                fence=0,
                blockers=(),
            )
            for task in graph.tasks
        }
        accepted_leases: set[str] = set()
        accepted_results: dict[str, str] = {}
        previous = "0" * 64
        creation_time = parse_utc(created_at)
        previous_recorded_at = creation_time
        observed_wall_elapsed = 0
        for expected_sequence, row in enumerate(rows, start=1):
            if row["sequence"] != expected_sequence or row["previous_sha256"] != previous:
                raise SchedulerAdapterError("Scheduler event sequence or chain is broken.")
            artifact = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            )
            event = artifact.value
            assert isinstance(event, SchedulerEvent)
            digest = event_digest(artifact)
            if (
                artifact.artifact_id != row["artifact_id"]
                or event.sequence != expected_sequence
                or event.previous_event_sha256 != previous
                or event.graph_id != graph_artifact.artifact_id
                or digest != row["event_sha256"]
            ):
                raise SchedulerAdapterError("Scheduler event artifact is inconsistent.")
            recorded_at = parse_utc(event.recorded_at)
            if recorded_at < previous_recorded_at:
                raise SchedulerAdapterError("Scheduler event time moved backwards.")
            elapsed = int((recorded_at - creation_time).total_seconds())
            if expected_sequence == 1:
                if (
                    event.recorded_at != created_at
                    or elapsed != 0
                    or event.reason
                    != _lease_policy_reason(
                        lease_ttl_seconds,
                        heartbeat_interval_seconds,
                    )
                ):
                    raise SchedulerAdapterError(
                        "Scheduler creation time is not anchored to initialization."
                    )
            elif elapsed > observed_wall_elapsed:
                if event.cause != "wall-time-observed":
                    raise SchedulerAdapterError(
                        "Scheduler operation advanced without an exact wall-time observation "
                        "before Lease authority use."
                    )
                observed_wall_elapsed = elapsed
            elif event.cause == "wall-time-observed":
                raise SchedulerAdapterError("Wall-time observation is extra or misplaced.")
            self._validate_event_semantics(
                connection,
                graph,
                event,
                projections,
                accepted_leases,
                accepted_results,
            )
            if event.task_id is not None:
                assert event.task_projection is not None
                projections[event.task_id] = event.task_projection
            previous = digest
            previous_recorded_at = recorded_at

    def _validate_event_semantics(
        self,
        connection: sqlite3.Connection,
        graph: TaskGraph,
        event: SchedulerEvent,
        projections: dict[str, TaskProjection],
        accepted_leases: set[str],
        accepted_results: dict[str, str],
    ) -> None:
        tasks = {task.task_id: task for task in graph.tasks}
        task_definition: Any | None = None
        prior_projection: TaskProjection | None = None
        scope = _EVENT_SCOPES.get(event.cause)
        if scope is None:
            raise SchedulerAdapterError("Scheduler event cause has no semantic handler.")
        if event.candidate != graph.candidate:
            raise SchedulerAdapterError("Scheduler event candidate identity drifted.")
        if event.cause in _SCHEDULER_ACTOR_CAUSES and event.actor != "scheduler":
            raise SchedulerAdapterError("Scheduler-authored event actor drifted.")
        if event.cause not in _EVENT_BUDGET_CAUSES and event.budget_deltas:
            raise SchedulerAdapterError("Scheduler event contains forbidden budget deltas.")
        if event.cause not in _EVENT_REASON_CAUSES and event.reason is not None:
            raise SchedulerAdapterError("Scheduler event contains a forbidden reason.")
        result_causes = {
            "result-received",
            "result-terminal",
            "verification-blocked",
            "verification-completed",
        }
        if event.cause not in result_causes and event.result_id is not None:
            raise SchedulerAdapterError("Scheduler event contains a forbidden result identity.")
        approval_causes = {"approval-consumed", "approval-received"}
        if event.cause not in approval_causes and event.approval_id is not None:
            raise SchedulerAdapterError("Scheduler event contains a forbidden approval identity.")

        if event.cause == "initialize":
            if (
                event.sequence != 1
                or event.task_id is not None
                or event.context_snapshot_id is not None
                or event.before_state is not None
                or event.after_state is not None
                or event.lease_id is not None
                or event.message_id is not None
                or event.result_id is not None
                or event.approval_id is not None
                or event.task_projection is not None
                or event.reason is None
                or event.budget_deltas
            ):
                raise SchedulerAdapterError("Scheduler initialization event is invalid.")
            return

        if scope == "graph" and (
            event.task_id is not None
            or event.context_snapshot_id is not None
            or event.before_state is not None
            or event.after_state is not None
            or event.lease_id is not None
            or event.result_id is not None
            or event.approval_id is not None
            or event.task_projection is not None
        ):
            raise SchedulerAdapterError("Graph-wide Scheduler event contains task authority.")
        if scope == "task" and event.task_id is None:
            raise SchedulerAdapterError("Task-scoped Scheduler event is missing its task.")

        if event.task_id is not None:
            task = tasks.get(event.task_id)
            projection = projections.get(event.task_id)
            if task is None or projection is None or event.task_projection is None:
                raise SchedulerAdapterError("Scheduler event task semantics are invalid.")
            task_definition = task
            prior_projection = projection
            if event.context_snapshot_id != task.context_snapshot_id:
                raise SchedulerAdapterError("Scheduler event Context identity drifted.")
            if event.before_state is not None and event.before_state != projection.state.value:
                raise SchedulerAdapterError("Scheduler event before-state is not replayable.")
            allowed = _EVENT_TRANSITIONS.get(event.cause)
            if allowed is None or (event.before_state, event.after_state) not in allowed:
                raise SchedulerAdapterError("Scheduler event transition is not allowed.")
            changes = _projection_changes(projection, event.task_projection)
            permitted_changes = _EVENT_PROJECTION_MUTATIONS[event.cause]
            if not changes.issubset(permitted_changes):
                raise SchedulerAdapterError("Scheduler event projection mutation is not allowed.")
            if event.before_state is None and event.task_projection != projection:
                raise SchedulerAdapterError("Scheduler audit event changed its task projection.")
            attempt_delta = event.task_projection.attempt - projection.attempt
            fence_delta = event.task_projection.fence - projection.fence
            if event.cause in {
                "dispatch-approval-blocked",
                "dispatch-intent",
                "worktree-request",
            }:
                if attempt_delta not in {0, 1} or fence_delta != attempt_delta:
                    raise SchedulerAdapterError("Scheduler dispatch identity increment is invalid.")
            elif event.cause == "approval-proposal-expired" and (
                attempt_delta != -1 or fence_delta != -1
            ):
                raise SchedulerAdapterError("Expired proposal identity rollback is invalid.")

        message: MailboxMessage | None = None
        expected_message_type = _EVENT_MESSAGE_TYPES.get(event.cause)
        if expected_message_type is not None:
            if event.message_id is None:
                raise SchedulerAdapterError("Scheduler event causal message is missing.")
            row = connection.execute(
                "SELECT artifact_json FROM messages WHERE artifact_id = ?", (event.message_id,)
            ).fetchone()
            if row is None:
                raise SchedulerAdapterError("Scheduler event causal message is unavailable.")
            message_value = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
            ).value
            assert isinstance(message_value, MailboxMessage)
            message = message_value
            if message.message_type is not expected_message_type:
                raise SchedulerAdapterError("Scheduler event causal message type drifted.")
            if event.task_id != message.task_id:
                raise SchedulerAdapterError("Scheduler event causal task drifted.")
        elif event.cause == "duplicate-message":
            if event.message_id is None:
                raise SchedulerAdapterError("Duplicate event message identity is missing.")
            row = connection.execute(
                "SELECT artifact_json FROM messages WHERE artifact_id = ?", (event.message_id,)
            ).fetchone()
            if row is None:
                raise SchedulerAdapterError("Duplicate event message is unavailable.")
            message_value = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
            ).value
            assert isinstance(message_value, MailboxMessage)
            message = message_value
            if event.task_id != message.task_id:
                raise SchedulerAdapterError("Duplicate event causal task drifted.")
        elif event.cause == "message-rejected":
            if event.message_id is None:
                raise SchedulerAdapterError("Rejected event message identity is missing.")
            if (
                connection.execute(
                    "SELECT 1 FROM messages WHERE artifact_id = ?", (event.message_id,)
                ).fetchone()
                is not None
            ):
                raise SchedulerAdapterError("Rejected event message was incorrectly adopted.")
        elif event.message_id is not None:
            raise SchedulerAdapterError("Scheduler event contains a forbidden message identity.")

        if message is not None:
            if (
                message.graph_id != event.graph_id
                or message.candidate != event.candidate
                or message.task_id != event.task_id
                or (
                    event.task_id is not None
                    and message.context_snapshot_id != event.context_snapshot_id
                )
            ):
                raise SchedulerAdapterError("Scheduler event causal identity drifted.")
            if event.cause not in {"approval-consumed", "approval-received"} and (
                event.lease_id != message.lease_id
            ):
                raise SchedulerAdapterError("Scheduler event causal Lease identity drifted.")
            if event.cause not in _SCHEDULER_ACTOR_CAUSES and event.actor != message.sender:
                raise SchedulerAdapterError(
                    "Scheduler event causal actor or Lease authority drifted."
                )

        if event.cause == "capability-observed":
            _require_semantics(message is not None, "Capability observation evidence is missing.")
            assert message is not None
            capability_payload = message.to_dict()["payload"]
            assert isinstance(capability_payload, dict)
            _require_semantics(
                (
                    message.direction,
                    message.recipient,
                    message.task_id,
                    message.context_snapshot_id,
                    message.attempt,
                    message.lease_id,
                    message.fence,
                    message.idempotency_key,
                    message.sensitivity,
                    message.provenance,
                    message.causal_parent_message_ids,
                    message.recorded_at <= event.recorded_at,
                    event.actor,
                    set(capability_payload),
                )
                == (
                    MessageDirection.HOST_TO_SCHEDULER,
                    "HST-SCHEDULER",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    Sensitivity.PUBLIC,
                    (),
                    (),
                    True,
                    message.sender,
                    {"capabilities"},
                ),
                "Capability observation semantics drifted.",
            )

        if event.cause in approval_causes and (
            message is None
            or event.approval_id is None
            or event.approval_id != message.payload.get("approval_id")
        ):
            raise SchedulerAdapterError("Scheduler approval event identity is incomplete.")
        if event.cause in approval_causes:
            assert task_definition is not None
            assert message is not None
            self._validate_exact_approval_message(connection, task_definition, event, message)

        if event.cause in {"cancel-request", "dispatch-intent", "worktree-request"}:
            if event.task_id is None or message is None:
                raise SchedulerAdapterError("Scheduler egress event evidence is incomplete.")
            self._validate_scheduler_egress_event(
                connection,
                graph,
                tasks[event.task_id],
                event,
                message,
            )

        causal_parent_types = {
            MessageType.DISPATCH_ACKNOWLEDGEMENT: MessageType.DISPATCH_INTENT,
            MessageType.HEARTBEAT: MessageType.DISPATCH_INTENT,
            MessageType.TASK_RESULT: MessageType.DISPATCH_INTENT,
            MessageType.CANCEL_ACKNOWLEDGEMENT: MessageType.CANCEL_REQUEST,
            MessageType.WORKTREE_OBSERVATION: MessageType.WORKTREE_REQUEST,
        }
        if (
            message is not None
            and message.message_type in causal_parent_types
            and (
                message.lease_id is None
                or not self._has_causal_parent(
                    connection,
                    message,
                    causal_parent_types[message.message_type],
                    message.lease_id,
                    before_event_sequence=event.sequence,
                )
            )
        ):
            raise SchedulerAdapterError("Scheduler event causal parent is invalid.")

        if (
            message is not None
            and message.lease_id is not None
            and message.direction
            in {
                MessageDirection.HOST_TO_SCHEDULER,
                MessageDirection.OWNER_TO_SCHEDULER,
            }
        ):
            lease_row = connection.execute(
                "SELECT artifact_json FROM lease_history WHERE authority_lease_id = ? "
                "AND task_id = ? AND event_sequence < ? ORDER BY event_sequence DESC LIMIT 1",
                (message.lease_id, message.task_id, event.sequence),
            ).fetchone()
            if lease_row is None:
                raise SchedulerAdapterError("Scheduler event has no prior Lease authority.")
            lease = _parse_artifact_json(
                lease_row["artifact_json"], SchedulerArtifactType.LEASE
            ).value
            assert isinstance(lease, Lease)
            if (
                message.sender != lease.owner_id
                and message.message_type is not MessageType.APPROVAL_DECISION
            ) or (
                message.attempt != lease.attempt
                or message.fence != lease.fence
                or message.idempotency_key != lease.idempotency_key
                or parse_utc(event.recorded_at) >= parse_utc(lease.expires_at)
            ):
                raise SchedulerAdapterError("Scheduler event Lease authority is invalid.")

        if (
            task_definition is not None
            and prior_projection is not None
            and event.cause
            not in {
                "result-received",
                "result-terminal",
                "verification-blocked",
                "verification-completed",
            }
        ):
            self._validate_non_result_event_semantics(
                connection,
                graph,
                task_definition,
                prior_projection,
                event,
                message,
            )

        if event.cause == "dispatch-accepted":
            assert event.lease_id is not None
            accepted_leases.add(event.lease_id)
        if event.cause in {"result-received", "result-terminal"}:
            if message is None or event.result_id != event.message_id:
                raise SchedulerAdapterError("Scheduler result event evidence is incomplete.")
            assert event.task_id is not None
            before_projection = projections[event.task_id]
            after_projection = event.task_projection
            assert after_projection is not None
            if before_projection.dispatch_phase not in {
                DispatchPhase.INTENT_PENDING,
                DispatchPhase.ACCEPTED,
            }:
                raise SchedulerAdapterError("Scheduler result lacks an authorized dispatch phase.")
            validate_task_result_reference(
                self._root,
                graph,
                message,
                solver_lease_evidence=(
                    self._m7_lease_evidence(connection, message, None)
                    if task_definition is not None and task_definition.kind.value == "solver"
                    else None
                ),
            )
            payload = message.to_dict()["payload"]
            assert isinstance(payload, dict)
            outcome_text = str(payload["outcome"])
            effect = str(payload["effect_observed"])
            successful = outcome_text == "succeeded" and effect != "ambiguous"
            if event.cause == "result-received":
                if not successful or (
                    after_projection.state is not TaskState.VERIFICATION
                    or after_projection.dispatch_phase is not DispatchPhase.ACCEPTED
                    or after_projection.outcome is not TaskOutcome.SUCCEEDED
                    or after_projection.blockers
                ):
                    raise SchedulerAdapterError(
                        "Accepted result event does not prove successful result semantics."
                    )
                self._validate_exact_lease_release(connection, event, TaskOutcome.SUCCEEDED)
                assert event.result_id is not None
                accepted_results[event.task_id] = event.result_id
            else:
                task = tasks[event.task_id]
                if successful:
                    raise SchedulerAdapterError(
                        "Successful result was recorded as a terminal failure event."
                    )
                safe_retry = (
                    outcome_text == "failed"
                    and effect == "none"
                    and task.effect_kind is EffectKind.READ_ONLY
                    and before_projection.attempt < task.max_attempts
                    and self._retry_usage_before(connection, event.sequence)
                    < graph.budget.max_retries
                )
                if safe_retry:
                    expected_state = TaskState.READY
                    expected_outcome = TaskOutcome.FAILED
                    expected_reason = "safe-read-only-retry"
                elif outcome_text == "failed" and effect == "none":
                    expected_state = TaskState.REJECTED
                    expected_outcome = TaskOutcome.FAILED
                    expected_reason = "unambiguous-failure"
                else:
                    expected_state = TaskState.BLOCKED
                    expected_outcome = TaskOutcome.UNKNOWN
                    expected_reason = "ambiguous-external-effect"
                if (
                    event.reason != expected_reason
                    or after_projection.state is not expected_state
                    or after_projection.dispatch_phase is not DispatchPhase.NOT_DISPATCHED
                    or after_projection.outcome is not expected_outcome
                    or after_projection.blockers != (Blocker(expected_reason, ()),)
                ):
                    raise SchedulerAdapterError(
                        "Terminal result event does not match its exact result semantics."
                    )
                self._validate_exact_lease_release(connection, event, expected_outcome)

        if event.cause in {"verification-blocked", "verification-completed"}:
            if event.task_id is None or event.result_id is None:
                raise SchedulerAdapterError("Verification event evidence is incomplete.")
            if accepted_results.get(event.task_id) != event.result_id:
                raise SchedulerAdapterError("Verification event result was not accepted.")
            row = connection.execute(
                "SELECT artifact_json FROM messages WHERE artifact_id = ?", (event.result_id,)
            ).fetchone()
            if row is None:
                raise SchedulerAdapterError("Verification result message is unavailable.")
            result = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
            ).value
            assert isinstance(result, MailboxMessage)
            result_payload = result.to_dict()["payload"]
            assert isinstance(result_payload, dict)
            if (
                result_payload["outcome"] != "succeeded"
                or result_payload["effect_observed"] == "ambiguous"
            ):
                raise SchedulerAdapterError(
                    "Verification event does not reference an accepted successful result."
                )
            task = tasks[event.task_id]
            incomplete_reviews = tuple(
                target
                for target in task.review_targets
                if projections[target].state is not TaskState.COMPLETED
            )
            verification_reason: str | None = None
            if (
                task.evidence_predicate == ("evidence-reference-present",)
                and not result.payload["evidence_refs"]
            ):
                verification_reason = "evidence-predicate-unsatisfied"
            elif task.terminal_predicate != ("agent-result-valid",):
                verification_reason = "terminal-predicate-unsupported"
            elif incomplete_reviews:
                verification_reason = "review-targets-unsatisfied"
            projection = event.task_projection
            assert projection is not None
            if event.cause == "verification-completed":
                if verification_reason is not None or (
                    projection.state is not TaskState.COMPLETED
                    or projection.dispatch_phase is not DispatchPhase.ACCEPTED
                    or projection.outcome is not TaskOutcome.SUCCEEDED
                    or projection.blockers
                ):
                    raise SchedulerAdapterError(
                        "Completed verification predicate or projection is unsatisfied."
                    )
            elif (
                verification_reason is None
                or event.reason != verification_reason
                or projection.state is not TaskState.BLOCKED
                or projection.dispatch_phase is not DispatchPhase.ACCEPTED
                or projection.outcome is not TaskOutcome.UNKNOWN
                or projection.blockers != (Blocker(verification_reason, incomplete_reviews),)
            ):
                raise SchedulerAdapterError("Blocked verification reason is not replayable.")
            if (
                connection.execute(
                    "SELECT 1 FROM lease_history WHERE event_sequence = ? AND task_id = ?",
                    (event.sequence, event.task_id),
                ).fetchone()
                is not None
            ):
                raise SchedulerAdapterError(
                    "Verification event has an unexpected Lease history artifact."
                )

    def _validate_non_result_event_semantics(
        self,
        connection: sqlite3.Connection,
        graph: TaskGraph,
        task: Any,
        prior: TaskProjection,
        event: SchedulerEvent,
        message: MailboxMessage | None,
    ) -> None:
        """Reproduce exact live-policy outcomes for non-result task events."""

        projection = event.task_projection
        assert projection is not None

        def require_projection(expected: TaskProjection) -> None:
            _require_semantics(
                (projection, event.after_state) == (expected, expected.state.value),
                "Scheduler event projection does not match exact cause semantics.",
            )

        unchanged = replace(prior)
        if event.cause == "approval-received":
            _require_semantics(message is not None, "Approval receipt evidence is missing.")
            assert message is not None
            _require_semantics(
                (
                    event.before_state,
                    event.reason,
                    message.direction,
                    message.recipient,
                    message.recorded_at <= event.recorded_at,
                )
                == (
                    None,
                    None,
                    MessageDirection.OWNER_TO_SCHEDULER,
                    "HST-SCHEDULER",
                    True,
                ),
                "Approval receipt event semantics drifted.",
            )
            require_projection(unchanged)
        elif event.cause == "approval-consumed":
            _require_semantics(message is not None, "Approval consumption evidence is missing.")
            assert message is not None
            _require_semantics(
                (
                    event.before_state,
                    event.reason,
                    message.payload.get("decision"),
                    message.payload.get("transition"),
                    parse_utc(str(message.payload["approved_at"]))
                    <= parse_utc(event.recorded_at)
                    < parse_utc(str(message.payload["expires_at"])),
                )
                == (prior.state.value, None, "approved", "dispatch", True),
                "Approval consumption semantics drifted.",
            )
            require_projection(unchanged)
        elif event.cause == "duplicate-message":
            _require_semantics(message is not None, "Duplicate-message evidence is missing.")
            _require_semantics(
                (event.before_state, event.reason) == (None, "duplicate-message-retained"),
                "Duplicate-message audit semantics drifted.",
            )
            require_projection(unchanged)
        elif event.cause == "message-rejected":
            _require_semantics(
                (event.before_state is None, event.reason is not None) == (True, True),
                "Message rejection audit semantics drifted.",
            )
            require_projection(unchanged)
        elif event.cause == "cancel-request":
            _require_semantics(
                (prior.state, event.reason) == (TaskState.RUNNING, None),
                "Cancellation request semantics drifted.",
            )
            require_projection(replace(prior, dispatch_phase=DispatchPhase.CANCELLATION_REQUESTED))
        elif event.cause == "dispatch-accepted":
            _require_semantics(message is not None, "Dispatch acknowledgement is missing.")
            assert message is not None
            _require_semantics(
                (
                    message.payload.get("accepted"),
                    prior.state,
                    prior.dispatch_phase,
                    event.reason,
                )
                == (True, TaskState.RUNNING, DispatchPhase.INTENT_PENDING, None),
                "Dispatch acknowledgement does not prove exact acceptance.",
            )
            require_projection(replace(prior, dispatch_phase=DispatchPhase.ACCEPTED))
        elif event.cause == "dispatch-rejected":
            _require_semantics(message is not None, "Dispatch acknowledgement is missing.")
            assert message is not None
            _require_semantics(
                (
                    message.payload.get("accepted"),
                    prior.state,
                    prior.dispatch_phase,
                )
                == (False, TaskState.RUNNING, DispatchPhase.INTENT_PENDING),
                "Dispatch acknowledgement does not prove exact rejection.",
            )
            observed = str(message.payload["effect_observed"])
            retry_used = self._retry_usage_before(connection, event.sequence)
            safe_retry = (
                observed == "none"
                and task.effect_kind is EffectKind.READ_ONLY
                and prior.attempt < task.max_attempts
                and retry_used < graph.budget.max_retries
            )
            reason = (
                "unambiguous-dispatch-rejection" if safe_retry else "dispatch-rejection-ambiguous"
            )
            require_projection(
                replace(
                    prior,
                    state=TaskState.READY if safe_retry else TaskState.BLOCKED,
                    dispatch_phase=DispatchPhase.NOT_DISPATCHED,
                    outcome=TaskOutcome.FAILED if safe_retry else TaskOutcome.UNKNOWN,
                    blockers=(Blocker(reason, ()),),
                )
            )
            _require_semantics(event.reason == reason, "Dispatch rejection policy reason drifted.")
            self._validate_exact_lease_release(
                connection,
                event,
                TaskOutcome.FAILED if safe_retry else TaskOutcome.UNKNOWN,
            )
        elif event.cause == "heartbeat":
            _require_semantics(message is not None, "Heartbeat message evidence is missing.")
            _require_semantics(
                (
                    prior.state,
                    prior.dispatch_phase in {DispatchPhase.INTENT_PENDING, DispatchPhase.ACCEPTED},
                    event.reason,
                )
                == (TaskState.RUNNING, True, None),
                "Heartbeat event semantics drifted.",
            )
            require_projection(unchanged)
            prior_lease = self._prior_lease_for_event(connection, event)
            ttl_seconds, _ = self._lease_policy(connection)
            expires_at = format_utc(parse_utc(event.recorded_at) + timedelta(seconds=ttl_seconds))
            self._validate_exact_lease_history(
                connection,
                event,
                replace(
                    prior_lease,
                    heartbeat_at=event.recorded_at,
                    expires_at=expires_at,
                    status=LeaseStatus.CURRENT,
                    release_outcome=TaskOutcome.NONE,
                ),
            )
        elif event.cause == "cancel-acknowledgement":
            _require_semantics(
                message is not None, "Cancellation acknowledgement evidence is missing."
            )
            assert message is not None
            _require_semantics(
                (prior.state, prior.dispatch_phase)
                == (TaskState.RUNNING, DispatchPhase.CANCELLATION_REQUESTED),
                "Cancellation acknowledgement semantics drifted.",
            )
            cancelled = bool(message.payload["cancelled"])
            observed = str(message.payload["effect_observed"])
            exact = cancelled and observed == "none"
            reason = "cancellation-acknowledged" if exact else "cancellation-ambiguous"
            outcome = TaskOutcome.CANCELLED if exact else TaskOutcome.UNKNOWN
            require_projection(
                replace(
                    prior,
                    state=TaskState.SUPERSEDED if exact else TaskState.BLOCKED,
                    dispatch_phase=(
                        DispatchPhase.CANCELLATION_ACKNOWLEDGED
                        if exact
                        else DispatchPhase.CANCELLATION_REQUESTED
                    ),
                    outcome=outcome,
                    blockers=(Blocker(reason, ()),),
                )
            )
            _require_semantics(
                event.reason == reason, "Cancellation acknowledgement reason drifted."
            )
            self._validate_exact_lease_release(connection, event, outcome)
        elif event.cause == "worktree-observed":
            _require_semantics(message is not None, "Worktree observation evidence is missing.")
            assert message is not None
            lease_row = self._prior_lease_row_for_event(connection, event)
            _require_semantics(
                lease_row["authority_lease_id"] == event.lease_id,
                "Worktree observation authority is not the latest active Lease.",
            )
            lease = _parse_artifact_json(
                lease_row["artifact_json"], SchedulerArtifactType.LEASE
            ).value
            assert isinstance(lease, Lease)
            prior_worktree = self._prior_worktree_for_observation(
                connection,
                event.sequence,
                task.task_id,
            )
            causal_request = self._causal_parent_message(
                connection,
                message,
                MessageType.WORKTREE_REQUEST,
                str(event.lease_id),
                before_event_sequence=event.sequence,
            )
            _require_semantics(
                causal_request is not None,
                "Worktree observation authority has no exact prior request.",
            )
            assert causal_request is not None
            expected_worktree, terminal, worktree_reason = self._derive_exact_worktree_observation(
                event.graph_id,
                graph,
                task,
                prior,
                str(event.lease_id),
                lease,
                prior_worktree,
                message,
                causal_request,
                event.recorded_at,
            )
            if terminal:
                require_projection(
                    replace(
                        prior,
                        state=TaskState.BLOCKED,
                        dispatch_phase=DispatchPhase.NOT_DISPATCHED,
                        outcome=TaskOutcome.UNKNOWN,
                        blockers=(Blocker(str(worktree_reason), ()),),
                    )
                )
                self._validate_exact_lease_release(
                    connection,
                    event,
                    TaskOutcome.UNKNOWN,
                    expect_worktree_release=False,
                )
            else:
                require_projection(unchanged)
                self._require_no_lease_history(connection, event)
            _require_semantics(
                event.reason == worktree_reason, "Worktree observation reason drifted."
            )
            self._validate_exact_worktree_history(connection, event, expected_worktree)
        elif event.cause == "approval-proposal-expired":
            prior_lease = self._prior_lease_for_event(connection, event)
            _require_semantics(
                (
                    event.reason,
                    parse_utc(event.recorded_at) >= parse_utc(prior_lease.expires_at),
                    self._lease_has_adopted_activation_before(connection, event),
                )
                == ("approval-proposal-expired", True, False),
                "Approval proposal expiry semantics drifted.",
            )
            require_projection(
                replace(
                    prior,
                    state=TaskState.READY,
                    dispatch_phase=DispatchPhase.NOT_DISPATCHED,
                    attempt=prior.attempt - 1,
                    fence=prior.fence - 1,
                    blockers=(),
                )
            )
            self._validate_exact_lease_release(connection, event, TaskOutcome.NONE)
        elif event.cause == "lease-expired":
            prior_lease = self._prior_lease_for_event(connection, event)
            retry_used = self._retry_usage_before(connection, event.sequence)
            safe_retry = (
                task.effect_kind is EffectKind.READ_ONLY
                and prior.attempt < task.max_attempts
                and retry_used < graph.budget.max_retries
            )
            reason = "lease-expired-safe-retry" if safe_retry else "lease-expired-ambiguous"
            outcome = TaskOutcome.FAILED if safe_retry else TaskOutcome.UNKNOWN
            _require_semantics(
                (
                    event.reason,
                    parse_utc(event.recorded_at) >= parse_utc(prior_lease.expires_at),
                    self._lease_has_adopted_activation_before(connection, event),
                )
                == (reason, True, True),
                "Lease expiry semantics drifted.",
            )
            require_projection(
                replace(
                    prior,
                    state=TaskState.READY if safe_retry else TaskState.BLOCKED,
                    dispatch_phase=DispatchPhase.NOT_DISPATCHED,
                    outcome=outcome,
                    blockers=(Blocker(reason, ()),),
                )
            )
            self._validate_exact_lease_release(connection, event, outcome)
        elif event.cause == "dispatch-intent":
            _require_semantics(message is not None, "Dispatch intent evidence is missing.")
            assert message is not None
            _require_semantics(event.reason is None, "Dispatch intent semantics drifted.")
            if prior.state is TaskState.READY:
                reused = self._event_reuses_prior_current_lease(connection, event)
                require_projection(
                    replace(
                        prior,
                        state=TaskState.RUNNING,
                        dispatch_phase=DispatchPhase.INTENT_PENDING,
                        outcome=TaskOutcome.NONE,
                        attempt=prior.attempt + (0 if reused else 1),
                        fence=prior.fence + (0 if reused else 1),
                        blockers=(),
                    )
                )
                if reused:
                    self._require_no_lease_history(connection, event)
                else:
                    self._validate_exact_lease_acquisition(connection, task, event, message)
            elif prior.state is TaskState.RUNNING:
                require_projection(
                    replace(
                        prior,
                        dispatch_phase=DispatchPhase.INTENT_PENDING,
                        outcome=TaskOutcome.NONE,
                        blockers=(),
                    )
                )
                self._require_no_lease_history(connection, event)
            else:
                raise SchedulerAdapterError("Dispatch intent prior state is not live-policy valid.")
        elif event.cause == "worktree-request":
            _require_semantics(message is not None, "Worktree request evidence is missing.")
            assert message is not None
            _require_semantics(
                (prior.state, event.reason) == (TaskState.READY, None),
                "Worktree request semantics drifted.",
            )
            reused = self._event_reuses_prior_current_lease(connection, event)
            require_projection(
                replace(
                    prior,
                    state=TaskState.RUNNING,
                    dispatch_phase=DispatchPhase.NOT_DISPATCHED,
                    outcome=TaskOutcome.NONE,
                    attempt=prior.attempt + (0 if reused else 1),
                    fence=prior.fence + (0 if reused else 1),
                    blockers=(),
                )
            )
            if reused:
                self._require_no_lease_history(connection, event)
            else:
                self._validate_exact_lease_acquisition(connection, task, event, message)
        elif event.cause == "dispatch-approval-blocked":
            _require_semantics(
                event.reason == "approval-required", "Approval blocker reason drifted."
            )
            if prior.state is TaskState.READY:
                try:
                    strict_host_id(event.actor, "provisional Lease owner")
                except SchedulerContractError as exc:
                    raise SchedulerAdapterError(
                        "Provisional Lease owner evidence is invalid."
                    ) from exc
                reused = self._event_reuses_prior_current_lease(connection, event)
                require_projection(
                    replace(
                        prior,
                        state=TaskState.BLOCKED,
                        attempt=prior.attempt + (0 if reused else 1),
                        fence=prior.fence + (0 if reused else 1),
                        blockers=(Blocker("approval-required", ()),),
                    )
                )
                if reused:
                    _require_semantics(
                        self._prior_lease_for_event(connection, event).owner_id == event.actor,
                        "Reused provisional Lease owner evidence drifted.",
                    )
                    self._require_no_lease_history(connection, event)
                else:
                    self._validate_provisional_lease_acquisition(connection, task, event)
            elif prior.state is TaskState.RUNNING:
                _require_semantics(
                    event.actor == "scheduler",
                    "Scheduler-authored approval blocker actor drifted.",
                )
                require_projection(replace(prior, blockers=(Blocker("approval-required", ()),)))
                self._require_no_lease_history(connection, event)
            else:
                raise SchedulerAdapterError("Approval blocker prior state drifted.")
            lease = self._lease_at_or_before_event(connection, event)
            observed_approval_types = self._approval_types_before_event(
                connection,
                task,
                lease,
                event,
                _sha256_json(task.to_dict()),
                "approval-received",
            )
            _require_semantics(
                observed_approval_types != set(task.approval_stops),
                "Approval blocker has no missing approval.",
            )
        elif event.cause == "dispatch-budget-blocked":
            _require_semantics(event.reason == "budget-exhausted", "Budget blocker reason drifted.")
            if prior.state is TaskState.READY:
                require_projection(
                    replace(
                        prior,
                        state=TaskState.BLOCKED,
                        blockers=(Blocker("budget-exhausted", ()),),
                    )
                )
            elif prior.state is TaskState.RUNNING:
                require_projection(
                    replace(
                        prior,
                        state=TaskState.RUNNING,
                        dispatch_phase=DispatchPhase.NOT_DISPATCHED,
                        outcome=TaskOutcome.NONE,
                        blockers=(Blocker("budget-exhausted", ()),),
                    )
                )
            else:
                raise SchedulerAdapterError("Budget blocker prior state drifted.")
        elif event.cause == "readiness-refreshed":
            self._validate_exact_readiness(connection, graph, task, prior, event)

        if event.cause not in _NON_RESULT_LEASE_HISTORY_OUTPUT_CAUSES:
            self._require_no_lease_history(connection, event)

    @staticmethod
    def _retry_usage_before(connection: sqlite3.Connection, sequence: int) -> int:
        used = 0
        for row in connection.execute(
            "SELECT artifact_json FROM events WHERE sequence < ? ORDER BY sequence",
            (sequence,),
        ).fetchall():
            prior = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            ).value
            assert isinstance(prior, SchedulerEvent)
            used += int(prior.budget_deltas.get("retries", 0))
        return used

    @staticmethod
    def _prior_lease_row_for_event(
        connection: sqlite3.Connection, event: SchedulerEvent
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM lease_history WHERE task_id = ? AND event_sequence < ? "
            "ORDER BY event_sequence DESC, artifact_id DESC LIMIT 1",
            (event.task_id, event.sequence),
        ).fetchone()
        _require_semantics(row is not None, "Scheduler event has no exact prior current Lease.")
        assert isinstance(row, sqlite3.Row)
        _require_semantics(
            row["status"] == LeaseStatus.CURRENT.value,
            "Scheduler event has no exact prior current Lease.",
        )
        return row

    @staticmethod
    def _event_reuses_prior_current_lease(
        connection: sqlite3.Connection, event: SchedulerEvent
    ) -> bool:
        row = connection.execute(
            "SELECT authority_lease_id, status FROM lease_history WHERE task_id = ? "
            "AND event_sequence < ? ORDER BY event_sequence DESC, artifact_id DESC LIMIT 1",
            (event.task_id, event.sequence),
        ).fetchone()
        return bool(
            row is not None
            and row["status"] == LeaseStatus.CURRENT.value
            and row["authority_lease_id"] == event.lease_id
        )

    @staticmethod
    def _require_no_lease_history(connection: sqlite3.Connection, event: SchedulerEvent) -> None:
        _require_semantics(
            connection.execute(
                "SELECT 1 FROM lease_history WHERE task_id = ? AND event_sequence = ?",
                (event.task_id, event.sequence),
            ).fetchone()
            is None,
            "Scheduler cause has an unexpected Lease history artifact.",
        )

    @classmethod
    def _prior_lease_for_event(cls, connection: sqlite3.Connection, event: SchedulerEvent) -> Lease:
        row = cls._prior_lease_row_for_event(connection, event)
        lease = _parse_artifact_json(row["artifact_json"], SchedulerArtifactType.LEASE).value
        assert isinstance(lease, Lease)
        _require_semantics(
            event.lease_id == row["authority_lease_id"],
            "Scheduler event Lease identity drifted.",
        )
        return lease

    @staticmethod
    def _validate_exact_lease_history(
        connection: sqlite3.Connection,
        event: SchedulerEvent,
        expected: Lease,
    ) -> None:
        rows = connection.execute(
            "SELECT * FROM lease_history WHERE event_sequence = ? AND task_id = ?",
            (event.sequence, event.task_id),
        ).fetchall()
        _require_semantics(len(rows) == 1, "Scheduler event Lease history cardinality drifted.")
        row = rows[0]
        artifact = _parse_artifact_json(row["artifact_json"], SchedulerArtifactType.LEASE)
        lease = artifact.value
        assert isinstance(lease, Lease)
        _require_semantics(
            (
                lease,
                artifact.artifact_id,
                event.lease_id,
                expected.status.value,
            )
            == (
                expected,
                row["artifact_id"],
                row["authority_lease_id"],
                row["status"],
            ),
            "Authoritative Lease history semantics drifted.",
        )

    @staticmethod
    def _validate_exact_worktree_history(
        connection: sqlite3.Connection,
        event: SchedulerEvent,
        expected: WorktreeLease,
    ) -> None:
        rows = connection.execute(
            "SELECT * FROM worktree_lease_history WHERE event_sequence = ?",
            (event.sequence,),
        ).fetchall()
        _require_semantics(
            len(rows) == 1,
            "Worktree authority history cardinality drifted.",
        )
        row = rows[0]
        artifact = _parse_artifact_json(row["artifact_json"], SchedulerArtifactType.WORKTREE_LEASE)
        actual = artifact.value
        assert isinstance(actual, WorktreeLease)
        _require_semantics(
            (
                actual,
                artifact.artifact_id,
                event.task_id,
                expected.status.value,
            )
            == (
                expected,
                row["artifact_id"],
                row["task_id"],
                row["status"],
            ),
            "Worktree authority history semantics drifted.",
        )

    @classmethod
    def _validate_exact_lease_release(
        cls,
        connection: sqlite3.Connection,
        event: SchedulerEvent,
        outcome: TaskOutcome,
        *,
        expect_worktree_release: bool = True,
    ) -> None:
        prior = cls._prior_lease_for_event(connection, event)
        cls._validate_exact_lease_history(
            connection,
            event,
            replace(prior, status=LeaseStatus.RELEASED, release_outcome=outcome),
        )
        prior_worktree_row = connection.execute(
            "SELECT * FROM worktree_lease_history WHERE task_id = ? "
            "AND event_sequence < ? ORDER BY event_sequence DESC, artifact_id DESC LIMIT 1",
            (event.task_id, event.sequence),
        ).fetchone()
        event_rows = connection.execute(
            "SELECT * FROM worktree_lease_history WHERE task_id = ? AND event_sequence = ?",
            (event.task_id, event.sequence),
        ).fetchall()
        prior_active = prior_worktree_row is not None and prior_worktree_row["status"] in {
            WorktreeLeaseStatus.REQUESTED.value,
            WorktreeLeaseStatus.OBSERVED.value,
        }
        if not expect_worktree_release or not prior_active:
            _require_semantics(
                not (expect_worktree_release and event_rows),
                "Unexpected Worktree release evidence.",
            )
            return
        _require_semantics(len(event_rows) == 1, "Worktree release evidence is incomplete.")
        prior_worktree = _parse_artifact_json(
            prior_worktree_row["artifact_json"], SchedulerArtifactType.WORKTREE_LEASE
        ).value
        assert isinstance(prior_worktree, WorktreeLease)
        expected = replace(
            prior_worktree,
            status=WorktreeLeaseStatus.RELEASED,
            ambiguous=False,
            recovery_guidance="Worktree authority is released; reacquire before reuse.",
        )
        cls._validate_exact_worktree_history(connection, event, expected)

    @classmethod
    def _validate_exact_lease_acquisition(
        cls,
        connection: sqlite3.Connection,
        task: Any,
        event: SchedulerEvent,
        message: MailboxMessage,
    ) -> None:
        assert message.attempt is not None
        assert message.fence is not None
        ttl_seconds, heartbeat_interval_seconds = cls._lease_policy(connection)
        expected_idempotency = derive_idempotency_key(
            event.graph_id,
            task.task_id,
            int(message.attempt),
            int(message.fence),
            event.candidate.to_dict(),
            task.context_snapshot_id,
            _sha256_json(task.to_dict()),
        )
        expected = Lease(
            graph_id=event.graph_id,
            task_id=task.task_id,
            candidate=event.candidate,
            context_snapshot_id=task.context_snapshot_id,
            attempt=int(message.attempt),
            owner_id=message.recipient,
            fence=int(message.fence),
            idempotency_key=expected_idempotency,
            acquired_at=event.recorded_at,
            heartbeat_at=event.recorded_at,
            expires_at=format_utc(parse_utc(event.recorded_at) + timedelta(seconds=ttl_seconds)),
            ttl_seconds=ttl_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            status=LeaseStatus.CURRENT,
            release_outcome=TaskOutcome.NONE,
        )
        _require_semantics(
            message.idempotency_key == expected_idempotency,
            "Dispatch Lease idempotency evidence drifted.",
        )
        cls._validate_exact_lease_history(connection, event, expected)

    @classmethod
    def _validate_provisional_lease_acquisition(
        cls,
        connection: sqlite3.Connection,
        task: Any,
        event: SchedulerEvent,
    ) -> None:
        projection = event.task_projection
        assert projection is not None
        ttl_seconds, heartbeat_interval_seconds = cls._lease_policy(connection)
        effect_digest = _sha256_json(task.to_dict())
        expected_idempotency = derive_idempotency_key(
            event.graph_id,
            task.task_id,
            projection.attempt,
            projection.fence,
            event.candidate.to_dict(),
            task.context_snapshot_id,
            effect_digest,
        )
        expected = Lease(
            graph_id=event.graph_id,
            task_id=task.task_id,
            candidate=event.candidate,
            context_snapshot_id=task.context_snapshot_id,
            attempt=projection.attempt,
            owner_id=event.actor,
            fence=projection.fence,
            idempotency_key=expected_idempotency,
            acquired_at=event.recorded_at,
            heartbeat_at=event.recorded_at,
            expires_at=format_utc(parse_utc(event.recorded_at) + timedelta(seconds=ttl_seconds)),
            ttl_seconds=ttl_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            status=LeaseStatus.CURRENT,
            release_outcome=TaskOutcome.NONE,
        )
        cls._validate_exact_lease_history(connection, event, expected)

    @classmethod
    def _lease_has_adopted_activation_before(
        cls, connection: sqlite3.Connection, event: SchedulerEvent
    ) -> bool:
        return any(
            prior.sequence < event.sequence
            and prior.lease_id == event.lease_id
            and prior.cause in {"dispatch-intent", "worktree-request"}
            for prior, _, _, _ in _adopted_message_entries(connection)
        )

    @staticmethod
    def _prior_worktree_for_observation(
        connection: sqlite3.Connection,
        event_sequence: int,
        task_id: str,
    ) -> WorktreeLease:
        row = connection.execute(
            "SELECT * FROM worktree_lease_history WHERE task_id = ? "
            "AND event_sequence < ? ORDER BY event_sequence DESC, artifact_id DESC LIMIT 1",
            (task_id, event_sequence),
        ).fetchone()
        _require_semantics(
            row is not None
            and row["status"]
            in {
                WorktreeLeaseStatus.REQUESTED.value,
                WorktreeLeaseStatus.OBSERVED.value,
            },
            "Worktree observation authority has no current prior Worktree Lease.",
        )
        artifact = _parse_artifact_json(row["artifact_json"], SchedulerArtifactType.WORKTREE_LEASE)
        worktree = artifact.value
        assert isinstance(worktree, WorktreeLease)
        _require_semantics(
            (
                artifact.artifact_id,
                worktree.task_id,
                worktree.status.value,
            )
            == (
                row["artifact_id"],
                row["task_id"],
                row["status"],
            ),
            "Worktree observation authority prior history drifted.",
        )
        return worktree

    @staticmethod
    def _derive_exact_worktree_observation(
        graph_id: str,
        graph: TaskGraph,
        task: Any,
        prior: TaskProjection,
        lease_id: str,
        lease: Lease,
        prior_worktree: WorktreeLease,
        message: MailboxMessage,
        causal_request: tuple[str, MailboxMessage],
        recorded_at: str,
    ) -> tuple[WorktreeLease, bool, str | None]:
        binding = next(
            (item for item in graph.contexts if item.artifact_id == task.context_snapshot_id),
            None,
        )
        request_id, request = causal_request
        _require_semantics(
            graph.worktree_plan is not None
            and task.worktree_assignment is not None
            and binding is not None,
            "Worktree observation authority is not assigned by the graph.",
        )
        assert graph.worktree_plan is not None
        assert task.worktree_assignment is not None
        assert binding is not None
        request_payload = request.to_dict()["payload"]
        assert isinstance(request_payload, dict)
        _require_semantics(
            (
                prior.state,
                prior.dispatch_phase,
                prior.outcome,
                lease.graph_id,
                lease.task_id,
                lease.candidate,
                lease.context_snapshot_id,
                lease.status,
                lease.release_outcome,
                request.message_type,
                request.direction,
                request.sender,
                request.recipient,
                request.graph_id,
                request.task_id,
                request.candidate,
                request.context_snapshot_id,
                request.attempt,
                request.lease_id,
                request.fence,
                request.idempotency_key,
                request.sensitivity,
                request.provenance,
                request.causal_parent_message_ids,
                request_payload,
                message.message_type,
                message.direction,
                message.sender,
                message.recipient,
                message.graph_id,
                message.task_id,
                message.candidate,
                message.context_snapshot_id,
                message.attempt,
                message.lease_id,
                message.fence,
                message.idempotency_key,
                message.sensitivity,
                message.provenance,
                message.causal_parent_message_ids,
                parse_utc(message.recorded_at) <= parse_utc(recorded_at),
                str(message.payload["worktree"]),
            )
            == (
                TaskState.RUNNING,
                DispatchPhase.NOT_DISPATCHED,
                TaskOutcome.NONE,
                graph_id,
                task.task_id,
                graph.candidate,
                task.context_snapshot_id,
                LeaseStatus.CURRENT,
                TaskOutcome.NONE,
                MessageType.WORKTREE_REQUEST,
                MessageDirection.SCHEDULER_TO_HOST,
                "HST-SCHEDULER",
                lease.owner_id,
                graph_id,
                task.task_id,
                graph.candidate,
                task.context_snapshot_id,
                lease.attempt,
                lease_id,
                lease.fence,
                lease.idempotency_key,
                binding.sensitivity,
                (binding.reference,),
                (),
                {
                    "owned_paths": list(task.owned_paths),
                    "worktree": task.worktree_assignment,
                },
                MessageType.WORKTREE_OBSERVATION,
                MessageDirection.HOST_TO_SCHEDULER,
                lease.owner_id,
                "HST-SCHEDULER",
                graph_id,
                task.task_id,
                graph.candidate,
                task.context_snapshot_id,
                lease.attempt,
                lease_id,
                lease.fence,
                lease.idempotency_key,
                binding.sensitivity,
                (binding.reference,),
                (request_id,),
                True,
                task.worktree_assignment,
            ),
            "Worktree observation authority does not match live policy.",
        )
        _require_semantics(
            prior_worktree.status in {WorktreeLeaseStatus.REQUESTED, WorktreeLeaseStatus.OBSERVED}
            and prior_worktree.graph_id == graph_id
            and prior_worktree.task_id == task.task_id
            and prior_worktree.worktree_plan == graph.worktree_plan
            and prior_worktree.base_commit == graph.candidate.git_head
            and prior_worktree.worktree == task.worktree_assignment
            and prior_worktree.owner_id == lease.owner_id
            and prior_worktree.owned_paths == task.owned_paths
            and prior_worktree.fence == lease.fence,
            "Worktree observation authority prior Worktree Lease drifted.",
        )
        state = str(message.payload["state"])
        ambiguous = state == "ambiguous"
        integrated = state == "integrated"
        terminal = ambiguous or integrated
        reason = (
            "ambiguous-worktree"
            if ambiguous
            else ("worktree-already-integrated" if integrated else None)
        )
        observed_raw = message.payload["observed_digest"]
        expected = WorktreeLease(
            graph_id=graph_id,
            task_id=task.task_id,
            worktree_plan=graph.worktree_plan,
            base_commit=graph.candidate.git_head,
            worktree=task.worktree_assignment,
            owner_id=lease.owner_id,
            owned_paths=task.owned_paths,
            fence=lease.fence,
            observed_digest=None if observed_raw is None else str(observed_raw),
            status=(
                WorktreeLeaseStatus.BLOCKED
                if ambiguous
                else (
                    WorktreeLeaseStatus.INTEGRATED if integrated else WorktreeLeaseStatus.OBSERVED
                )
            ),
            integration_state="ambiguous" if ambiguous else "verified",
            ambiguous=ambiguous,
            recovery_guidance="Preserve the worktree and require an exact host observation.",
        )
        return expected, terminal, reason

    def _validate_exact_readiness(
        self,
        connection: sqlite3.Connection,
        graph: TaskGraph,
        task: Any,
        prior: TaskProjection,
        event: SchedulerEvent,
    ) -> None:
        projection = event.task_projection
        assert projection is not None
        _require_semantics(
            prior.state in {TaskState.PLANNED, TaskState.READY, TaskState.BLOCKED},
            "Readiness event prior state is not refreshable.",
        )
        _require_semantics(
            (prior.state, prior.outcome) != (TaskState.BLOCKED, TaskOutcome.UNKNOWN),
            "Unknown task cannot be refreshed as ready.",
        )
        _require_semantics(
            (
                projection.dispatch_phase,
                projection.outcome,
                projection.attempt,
                projection.fence,
            )
            == (
                prior.dispatch_phase,
                prior.outcome,
                prior.attempt,
                prior.fence,
            ),
            "Readiness event changed protected task identity.",
        )
        dependencies = {
            dependency: self._projection_before_event(connection, dependency, event.sequence)
            for dependency in task.dependencies
        }
        if any(
            item.state in {TaskState.BLOCKED, TaskState.REJECTED, TaskState.SUPERSEDED}
            for item in dependencies.values()
        ):
            expected = replace(
                prior,
                state=TaskState.BLOCKED,
                blockers=(Blocker("dependency-terminal-blocker", tuple(task.dependencies)),),
            )
        elif not all(item.state is TaskState.COMPLETED for item in dependencies.values()):
            expected = replace(prior, state=TaskState.PLANNED, blockers=())
        else:
            blockers: list[Blocker] = []
            if event.reason == "worktree-unavailable":
                if task.worktree_assignment is None:
                    raise SchedulerAdapterError("Worktree blocker has no planned assignment.")
                occupied = self._worktree_owners_before_event(connection, event.sequence).get(
                    task.worktree_assignment
                )
                _require_semantics(
                    occupied is not None and occupied != task.task_id,
                    "Worktree blocker authority is not replayable.",
                )
                assert occupied is not None
                blockers.append(Blocker("worktree-unavailable", (occupied,)))
            else:
                _require_semantics(event.reason is None, "Readiness event reason drifted.")
                capabilities = self._capabilities_before_event(connection, event.sequence)
                authority_host = self._readiness_authority_host(connection, event, capabilities)
                if authority_host is None:
                    missing_sets = {
                        tuple(sorted(set(task.required_capabilities) - set(host_capabilities)))
                        for host_capabilities in (capabilities.values() if capabilities else ((),))
                    }
                    _require_semantics(
                        len(missing_sets) == 1,
                        "Readiness capability authority is ambiguous.",
                    )
                    missing = next(iter(missing_sets))
                else:
                    missing = tuple(
                        sorted(
                            set(task.required_capabilities)
                            - set(capabilities.get(authority_host, ()))
                        )
                    )
                if missing:
                    blockers.append(Blocker("missing-capability", missing))
                if task.kind.value == "solver" and _m7_solver_reservation(task, graph) is None:
                    blockers.append(Blocker("solver-contract-unavailable", (task.task_id,)))
            expected_blockers = tuple(
                sorted(blockers, key=lambda item: (item.code, item.references))
            )
            expected_state = TaskState.BLOCKED if expected_blockers else TaskState.READY
            expected = replace(prior, state=expected_state, blockers=expected_blockers)
        _require_semantics(
            projection == expected,
            "Readiness projection is not deterministically replayable.",
        )

    @staticmethod
    def _capabilities_before_event(
        connection: sqlite3.Connection, sequence: int
    ) -> dict[str, tuple[str, ...]]:
        capabilities: dict[str, tuple[str, ...]] = {}
        for adopted, _, message, _ in _adopted_message_entries(
            connection,
            cause="capability-observed",
            message_type=MessageType.CAPABILITY_OBSERVATION,
        ):
            if adopted.sequence >= sequence:
                break
            payload = message.to_dict()["payload"]
            assert isinstance(payload, dict)
            capability_values = payload["capabilities"]
            assert isinstance(capability_values, list)
            capabilities[message.sender] = tuple(str(item) for item in capability_values)
        return capabilities

    @classmethod
    def _readiness_authority_host(
        cls,
        connection: sqlite3.Connection,
        event: SchedulerEvent,
        capabilities: dict[str, tuple[str, ...]],
    ) -> str | None:
        row = connection.execute(
            "SELECT artifact_json FROM lease_history WHERE task_id = ? "
            "AND event_sequence < ? ORDER BY event_sequence DESC, artifact_id DESC LIMIT 1",
            (event.task_id, event.sequence),
        ).fetchone()
        if row is not None:
            lease = _parse_artifact_json(row["artifact_json"], SchedulerArtifactType.LEASE).value
            assert isinstance(lease, Lease)
            if lease.status is LeaseStatus.CURRENT:
                return lease.owner_id
        preceding = [
            adopted.actor
            for adopted, _, message, _ in _adopted_message_entries(connection)
            if adopted.sequence < event.sequence
            and adopted.recorded_at == event.recorded_at
            and message.direction is MessageDirection.HOST_TO_SCHEDULER
        ]
        if preceding:
            return preceding[-1]
        return next(iter(capabilities)) if len(capabilities) == 1 else None

    @staticmethod
    def _worktree_owners_before_event(
        connection: sqlite3.Connection, sequence: int
    ) -> dict[str, str]:
        latest: dict[str, WorktreeLease] = {}
        for row in connection.execute(
            "SELECT task_id, artifact_json FROM worktree_lease_history "
            "WHERE event_sequence < ? ORDER BY event_sequence, artifact_id",
            (sequence,),
        ).fetchall():
            worktree = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.WORKTREE_LEASE
            ).value
            assert isinstance(worktree, WorktreeLease)
            latest[str(row["task_id"])] = worktree
        return {
            worktree.worktree: task_id
            for task_id, worktree in latest.items()
            if worktree.status in {WorktreeLeaseStatus.REQUESTED, WorktreeLeaseStatus.OBSERVED}
        }

    @staticmethod
    def _projection_before_event(
        connection: sqlite3.Connection, task_id: str, sequence: int
    ) -> TaskProjection:
        latest: TaskProjection | None = None
        for row in connection.execute(
            "SELECT artifact_json FROM events WHERE sequence < ? ORDER BY sequence",
            (sequence,),
        ).fetchall():
            prior = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            ).value
            assert isinstance(prior, SchedulerEvent)
            if prior.task_id == task_id and prior.task_projection is not None:
                latest = prior.task_projection
        if latest is None:
            graph_row = connection.execute("SELECT artifact_json FROM task_graph").fetchone()
            graph = _parse_artifact_json(
                graph_row["artifact_json"], SchedulerArtifactType.TASK_GRAPH
            ).value
            assert isinstance(graph, TaskGraph)
            task = next(item for item in graph.tasks if item.task_id == task_id)
            return TaskProjection(
                task_id=task_id,
                state=TaskState.READY if not task.dependencies else TaskState.PLANNED,
                dispatch_phase=DispatchPhase.NOT_DISPATCHED,
                outcome=TaskOutcome.NONE,
                attempt=0,
                fence=0,
                blockers=(),
            )
        return latest

    def _validate_scheduler_egress_event(
        self,
        connection: sqlite3.Connection,
        graph: TaskGraph,
        task: Any,
        event: SchedulerEvent,
        message: MailboxMessage,
    ) -> None:
        """Replay exact scheduler-to-host intent, Lease, approval, and budget evidence."""

        ttl_seconds, heartbeat_interval_seconds = self._lease_policy(connection)
        if event.lease_id is None:
            raise SchedulerAdapterError("Scheduler egress event Lease is missing.")
        lease_row = connection.execute(
            "SELECT artifact_json FROM lease_history WHERE authority_lease_id = ? "
            "AND task_id = ? AND event_sequence <= ? ORDER BY event_sequence DESC LIMIT 1",
            (event.lease_id, task.task_id, event.sequence),
        ).fetchone()
        if lease_row is None:
            raise SchedulerAdapterError(
                "Scheduler egress event has no prior Lease authority evidence."
            )
        lease = _parse_artifact_json(lease_row["artifact_json"], SchedulerArtifactType.LEASE).value
        assert isinstance(lease, Lease)
        if (
            lease.status is not LeaseStatus.CURRENT
            or lease.graph_id != event.graph_id
            or lease.task_id != task.task_id
            or lease.candidate != event.candidate
            or lease.context_snapshot_id != task.context_snapshot_id
            or lease.owner_id != message.recipient
            or lease.attempt != message.attempt
            or lease.fence != message.fence
            or lease.idempotency_key != message.idempotency_key
            or parse_utc(event.recorded_at) >= parse_utc(lease.expires_at)
        ):
            raise SchedulerAdapterError("Scheduler egress event Lease evidence drifted.")

        binding = next(
            item for item in graph.contexts if item.artifact_id == task.context_snapshot_id
        )
        message_row = connection.execute(
            "SELECT sequence FROM messages WHERE artifact_id = ?", (event.message_id,)
        ).fetchone()
        if message_row is None or (
            message.direction is not MessageDirection.SCHEDULER_TO_HOST
            or message.sender != "HST-SCHEDULER"
            or message.recorded_at != event.recorded_at
            or message.sensitivity != binding.sensitivity
            or message.provenance != (binding.reference,)
        ):
            raise SchedulerAdapterError("Scheduler egress envelope evidence drifted.")
        message_sequence = int(message_row["sequence"])

        if event.cause == "cancel-request":
            parent_entry = next(
                (
                    entry
                    for entry in reversed(_adopted_message_entries(connection))
                    if entry[0].sequence < event.sequence
                    and entry[0].cause in {"dispatch-intent", "worktree-request"}
                    and entry[0].task_id == task.task_id
                    and entry[3] < message_sequence
                ),
                None,
            )
            if parent_entry is None:
                raise SchedulerAdapterError("Cancellation request causal parent is missing.")
            _, parent_id, parent, _ = parent_entry
            if (
                message.causal_parent_message_ids != (parent_id,)
                or parent.lease_id != event.lease_id
                or parent.task_id != task.task_id
                or parent.recipient != lease.owner_id
                or event.budget_deltas
            ):
                raise SchedulerAdapterError("Cancellation request budget evidence drifted.")
            return

        payload_value = message.to_dict()["payload"]
        assert isinstance(payload_value, dict)
        effect_digest = _sha256_json(task.to_dict())
        expected_approval_cause = (
            "approval-consumed" if event.cause == "dispatch-intent" else "approval-received"
        )
        self._validate_approvals_before_egress(
            connection,
            task,
            lease,
            event,
            effect_digest,
            expected_approval_cause,
        )

        if event.cause == "worktree-request":
            if (
                message.causal_parent_message_ids
                or payload_value
                != {
                    "owned_paths": list(task.owned_paths),
                    "worktree": task.worktree_assignment,
                }
                or event.budget_deltas != {"concurrency": 1}
            ):
                raise SchedulerAdapterError("Worktree request evidence drifted.")
            assert graph.worktree_plan is not None
            assert task.worktree_assignment is not None
            expected_worktree = WorktreeLease(
                graph_id=event.graph_id,
                task_id=task.task_id,
                worktree_plan=graph.worktree_plan,
                base_commit=graph.candidate.git_head,
                worktree=task.worktree_assignment,
                owner_id=lease.owner_id,
                owned_paths=task.owned_paths,
                fence=lease.fence,
                observed_digest=None,
                status=WorktreeLeaseStatus.REQUESTED,
                integration_state="requested",
                ambiguous=False,
                recovery_guidance="Await the exact host worktree observation.",
            )
            self._validate_exact_worktree_history(connection, event, expected_worktree)
            return

        if task.worktree_assignment is None:
            if message.causal_parent_message_ids:
                raise SchedulerAdapterError("Plain dispatch has a forbidden causal parent.")
        else:
            observation_id = self._latest_worktree_observation_message_id(
                connection,
                task.task_id,
                event.lease_id,
                before_sequence=message_sequence,
                before_event_sequence=event.sequence,
            )
            worktree_row = connection.execute(
                "SELECT artifact_json FROM worktree_lease_history WHERE task_id = ? "
                "AND event_sequence < ? ORDER BY event_sequence DESC, artifact_id DESC LIMIT 1",
                (task.task_id, event.sequence),
            ).fetchone()
            if observation_id is None or worktree_row is None:
                raise SchedulerAdapterError("Dispatch Worktree authority is missing.")
            worktree = _parse_artifact_json(
                worktree_row["artifact_json"], SchedulerArtifactType.WORKTREE_LEASE
            ).value
            assert isinstance(worktree, WorktreeLease)
            if (
                message.causal_parent_message_ids != (observation_id,)
                or worktree.status is not WorktreeLeaseStatus.OBSERVED
                or worktree.graph_id != event.graph_id
                or worktree.task_id != task.task_id
                or worktree.worktree_plan != graph.worktree_plan
                or worktree.base_commit != graph.candidate.git_head
                or worktree.worktree != task.worktree_assignment
                or worktree.owner_id != lease.owner_id
                or worktree.owned_paths != task.owned_paths
                or worktree.fence != lease.fence
            ):
                raise SchedulerAdapterError("Dispatch Worktree authority drifted.")

        context_bytes = verified_reference_size(self._root, binding.reference)
        reservation = payload_value.get("budget_reservation")
        if not isinstance(reservation, dict):
            raise SchedulerAdapterError("Dispatch reservation evidence is missing.")
        expected_payload = {
            "budget_reservation": reservation,
            "context_bytes": context_bytes,
            "effect_digest": effect_digest,
            "heartbeat_interval_seconds": heartbeat_interval_seconds,
            "lease_ttl_seconds": ttl_seconds,
            "required_capabilities": list(task.required_capabilities),
            "required_tools": list(task.required_tools),
        }
        if payload_value != expected_payload:
            raise SchedulerAdapterError(
                "Dispatch intent payload or Authoritative Lease evidence drifted."
            )
        expected_deltas = {
            "context_bytes": context_bytes,
            "dispatches": 1,
            "microunits": int(reservation["microunits"]),
            "solver_calls": int(reservation["solver_calls"]),
            "solver_steps": int(reservation["solver_steps"]),
            "tool_calls": int(reservation["tool_calls"]),
        }
        if event.before_state == TaskState.READY.value:
            expected_deltas["concurrency"] = 1
        if event.budget_deltas != dict(sorted(expected_deltas.items())):
            raise SchedulerAdapterError("Dispatch intent budget evidence drifted.")

    def _validate_approvals_before_egress(
        self,
        connection: sqlite3.Connection,
        task: Any,
        lease: Lease,
        event: SchedulerEvent,
        effect_digest: str,
        expected_cause: str,
    ) -> None:
        required = set(task.approval_stops)
        if not required:
            return
        observed = self._approval_types_before_event(
            connection, task, lease, event, effect_digest, expected_cause
        )
        if observed != required:
            raise SchedulerAdapterError("Scheduler egress approval evidence is incomplete.")

    @staticmethod
    def _lease_at_or_before_event(connection: sqlite3.Connection, event: SchedulerEvent) -> Lease:
        row = connection.execute(
            "SELECT artifact_json FROM lease_history WHERE authority_lease_id = ? "
            "AND task_id = ? AND event_sequence <= ? "
            "ORDER BY event_sequence DESC, artifact_id DESC LIMIT 1",
            (event.lease_id, event.task_id, event.sequence),
        ).fetchone()
        if row is None:
            raise SchedulerAdapterError("Approval event Lease evidence is missing.")
        lease = _parse_artifact_json(row["artifact_json"], SchedulerArtifactType.LEASE).value
        assert isinstance(lease, Lease)
        if lease.status is not LeaseStatus.CURRENT:
            raise SchedulerAdapterError("Approval event Lease is not current.")
        return lease

    def _validate_exact_approval_message(
        self,
        connection: sqlite3.Connection,
        task: Any,
        event: SchedulerEvent,
        message: MailboxMessage,
    ) -> None:
        payload = message.to_dict()["payload"]
        assert isinstance(payload, dict)
        approval_type = str(payload["approval_type"])
        authorities = {
            "owner": ("HST-OWNER", "Owner"),
            "technical_sandbox": (
                "HST-TECHNICAL-SANDBOX",
                "Technical sandbox reviewer",
            ),
        }
        expected_sender, expected_authority = authorities.get(approval_type, (None, None))
        lease = self._lease_at_or_before_event(connection, event)
        _require_semantics(
            (
                message.direction,
                message.sender,
                payload["authority"],
                message.recipient,
                approval_type in task.approval_stops,
                payload["effect_digest"],
                payload["transition"],
                parse_utc(str(payload["approved_at"])) < parse_utc(str(payload["expires_at"])),
                message.attempt,
                message.lease_id,
                message.fence,
                message.idempotency_key,
                event.lease_id,
            )
            == (
                MessageDirection.OWNER_TO_SCHEDULER,
                expected_sender,
                expected_authority,
                "HST-SCHEDULER",
                True,
                _sha256_json(task.to_dict()),
                "dispatch",
                True,
                lease.attempt,
                event.lease_id,
                lease.fence,
                lease.idempotency_key,
                message.lease_id,
            ),
            "Approval authority semantics drifted.",
        )

    @staticmethod
    def _approval_types_before_event(
        connection: sqlite3.Connection,
        task: Any,
        lease: Lease,
        event: SchedulerEvent,
        effect_digest: str,
        expected_cause: str,
    ) -> set[str]:
        required = set(task.approval_stops)
        observed: set[str] = set()
        rows = connection.execute(
            "SELECT artifact_json FROM events WHERE sequence < ? ORDER BY sequence",
            (event.sequence,),
        ).fetchall()
        for row in rows:
            prior = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            ).value
            assert isinstance(prior, SchedulerEvent)
            if (
                prior.cause != expected_cause
                or prior.task_id != task.task_id
                or prior.lease_id != event.lease_id
                or prior.message_id is None
            ):
                continue
            message_row = connection.execute(
                "SELECT artifact_json FROM messages WHERE artifact_id = ?",
                (prior.message_id,),
            ).fetchone()
            if message_row is None:
                continue
            approval = _parse_artifact_json(
                message_row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
            ).value
            assert isinstance(approval, MailboxMessage)
            payload = approval.payload
            approval_type = payload.get("approval_type")
            if (
                approval.message_type is MessageType.APPROVAL_DECISION
                and isinstance(approval_type, str)
                and approval_type in required
                and payload.get("decision") == "approved"
                and payload.get("transition") == "dispatch"
                and payload.get("effect_digest") == effect_digest
                and approval.attempt == lease.attempt
                and approval.lease_id == event.lease_id
                and approval.fence == lease.fence
                and approval.idempotency_key == lease.idempotency_key
                and parse_utc(str(payload["approved_at"]))
                <= parse_utc(event.recorded_at)
                < parse_utc(str(payload["expires_at"]))
            ):
                observed.add(approval_type)
        return observed

    def _validate_immutable_rows(self, connection: sqlite3.Connection) -> None:
        checks = (
            ("messages", "artifact_id", SchedulerArtifactType.MAILBOX_MESSAGE),
            ("lease_history", "artifact_id", SchedulerArtifactType.LEASE),
            ("budget_entries", "artifact_id", SchedulerArtifactType.BUDGET_LEDGER),
            (
                "worktree_lease_history",
                "artifact_id",
                SchedulerArtifactType.WORKTREE_LEASE,
            ),
        )
        for table, identity_column, artifact_type in checks:
            rows = connection.execute(
                f"SELECT {identity_column}, artifact_json FROM {table}"
            ).fetchall()
            for row in rows:
                artifact = _parse_artifact_json(row["artifact_json"], artifact_type)
                if artifact.artifact_id != row[identity_column]:
                    raise SchedulerAdapterError("Immutable scheduler row identity drifted.")
        message_rows = connection.execute("SELECT * FROM messages ORDER BY sequence").fetchall()
        for expected_sequence, row in enumerate(message_rows, start=1):
            artifact = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
            )
            message = artifact.value
            assert isinstance(message, MailboxMessage)
            if (
                row["sequence"] != expected_sequence
                or artifact.artifact_id != row["artifact_id"]
                or message.message_type.value != row["message_type"]
                or message.direction.value != row["direction"]
                or message.task_id != row["task_id"]
                or message.idempotency_key != row["idempotency_key"]
            ):
                raise SchedulerAdapterError("Immutable mailbox evidence drifted.")
        ttl_seconds, heartbeat_interval_seconds = self._lease_policy(connection)
        for row in connection.execute("SELECT * FROM lease_history").fetchall():
            artifact = _parse_artifact_json(row["artifact_json"], SchedulerArtifactType.LEASE)
            lease = artifact.value
            assert isinstance(lease, Lease)
            self._validate_authoritative_lease(
                lease,
                ttl_seconds,
                heartbeat_interval_seconds,
            )
            event_row = connection.execute(
                "SELECT artifact_json FROM events WHERE sequence = ?", (row["event_sequence"],)
            ).fetchone()
            if event_row is None:
                raise SchedulerAdapterError("Lease history event is missing.")
            event = _parse_artifact_json(
                event_row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            ).value
            assert isinstance(event, SchedulerEvent)
            if (
                lease.task_id != row["task_id"]
                or lease.fence != row["fence"]
                or lease.status.value != row["status"]
                or event.task_id != lease.task_id
                or event.lease_id != row["authority_lease_id"]
            ):
                raise SchedulerAdapterError("Immutable lease evidence drifted.")
        for row in connection.execute("SELECT * FROM budget_entries").fetchall():
            artifact = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.BUDGET_LEDGER
            )
            ledger = artifact.value
            assert isinstance(ledger, BudgetLedger)
            event_exists = connection.execute(
                "SELECT 1 FROM events WHERE sequence = ?", (row["event_sequence"],)
            ).fetchone()
            if ledger.event_sequence != row["event_sequence"] or event_exists is None:
                raise SchedulerAdapterError("Immutable budget evidence drifted.")
        for row in connection.execute("SELECT * FROM worktree_lease_history").fetchall():
            artifact = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.WORKTREE_LEASE
            )
            lease = artifact.value
            assert isinstance(lease, WorktreeLease)
            event_row = connection.execute(
                "SELECT artifact_json FROM events WHERE sequence = ?", (row["event_sequence"],)
            ).fetchone()
            if event_row is None:
                raise SchedulerAdapterError("Worktree history event is missing.")
            event = _parse_artifact_json(
                event_row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            ).value
            assert isinstance(event, SchedulerEvent)
            if (
                lease.task_id != row["task_id"]
                or lease.status.value != row["status"]
                or event.task_id != lease.task_id
                or event.cause not in _WORKTREE_HISTORY_EVENT_CAUSES
            ):
                raise SchedulerAdapterError("Immutable worktree evidence drifted.")

    def _validate_message_adoption(self, connection: sqlite3.Connection) -> None:
        """Require every immutable mailbox row to have one exact adopting event."""

        message_rows = connection.execute(
            "SELECT sequence, artifact_id, artifact_json FROM messages ORDER BY sequence"
        ).fetchall()
        messages: dict[str, tuple[int, MailboxMessage]] = {}
        for row in message_rows:
            message = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
            ).value
            assert isinstance(message, MailboxMessage)
            messages[str(row["artifact_id"])] = (int(row["sequence"]), message)

        primary: dict[str, list[SchedulerEvent]] = {message_id: [] for message_id in messages}
        duplicates: list[SchedulerEvent] = []
        consumptions: list[SchedulerEvent] = []
        for row in connection.execute(
            "SELECT artifact_json FROM events ORDER BY sequence"
        ).fetchall():
            event = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            ).value
            assert isinstance(event, SchedulerEvent)
            if event.cause in _PRIMARY_MESSAGE_EVENT_CAUSES:
                if event.message_id not in messages:
                    raise SchedulerAdapterError(
                        "Primary mailbox adoption event has no immutable message."
                    )
                primary[event.message_id].append(event)
            elif event.cause == "duplicate-message":
                duplicates.append(event)
            elif event.cause == "approval-consumed":
                consumptions.append(event)

        primary_by_id: dict[str, SchedulerEvent] = {}
        for message_id, (message_sequence, message) in messages.items():
            adopters = primary[message_id]
            allowed_causes = _PRIMARY_EVENT_CAUSES_BY_MESSAGE[message.message_type]
            _require_semantics(
                len(adopters) == 1,
                "Immutable mailbox message does not have one exact primary adoption.",
            )
            adopter = adopters[0]
            _require_semantics(
                adopter.cause in allowed_causes,
                "Immutable mailbox message does not have one exact primary adoption.",
            )
            _require_semantics(
                parse_utc(adopter.recorded_at) >= parse_utc(message.recorded_at),
                "Mailbox message was adopted before its recorded time.",
            )
            primary_by_id[message_id] = adopter
            for parent_id in message.causal_parent_message_ids:
                parent_entry = messages.get(parent_id)
                parent_adopter = primary_by_id.get(parent_id)
                _require_semantics(
                    parent_entry is not None,
                    "Mailbox causal parent has no immutable message.",
                )
                assert parent_entry is not None
                if parent_adopter is None:
                    parent_adopters = primary[parent_id]
                    _require_semantics(
                        len(parent_adopters) == 1,
                        "Mailbox causal parent lacks exact primary adoption.",
                    )
                    parent_adopter = parent_adopters[0]
                _require_semantics(
                    (
                        parent_entry[0] < message_sequence,
                        parent_adopter.sequence < adopter.sequence,
                    )
                    == (True, True),
                    "Mailbox causal parent is not an earlier adopted message.",
                )

        for duplicate in duplicates:
            _require_semantics(
                duplicate.message_id is not None,
                "Duplicate mailbox audit is not replayable.",
            )
            assert duplicate.message_id is not None
            primary_adopter = primary_by_id.get(duplicate.message_id)
            _require_semantics(
                primary_adopter is not None,
                "Duplicate mailbox audit is not replayable.",
            )
            assert primary_adopter is not None
            _require_semantics(
                (primary_adopter.sequence < duplicate.sequence, duplicate.reason)
                == (True, "duplicate-message-retained"),
                "Duplicate mailbox audit is not replayable.",
            )

        consumed: set[tuple[str, str]] = set()
        for consumption in consumptions:
            _require_semantics(
                (consumption.message_id is not None, consumption.approval_id is not None)
                == (True, True),
                "Approval consumption adoption is incomplete.",
            )
            assert consumption.message_id is not None
            assert consumption.approval_id is not None
            entry = messages.get(consumption.message_id)
            consumption_adopter = primary_by_id.get(consumption.message_id)
            _require_semantics(
                (entry is not None, consumption_adopter is not None) == (True, True),
                "Consumed approval was not adopted.",
            )
            assert entry is not None
            assert consumption_adopter is not None
            approval = entry[1]
            identity = (consumption.message_id, consumption.approval_id)
            _require_semantics(
                (
                    approval.message_type,
                    consumption_adopter.cause,
                    consumption_adopter.sequence < consumption.sequence,
                    approval.payload.get("approval_id"),
                    consumption.task_id,
                    consumption.lease_id,
                    identity in consumed,
                )
                == (
                    MessageType.APPROVAL_DECISION,
                    "approval-received",
                    True,
                    consumption.approval_id,
                    consumption_adopter.task_id,
                    consumption_adopter.lease_id,
                    False,
                ),
                "Approval consumption is not bound to one adopted decision.",
            )
            consumed.add(identity)

    @staticmethod
    def _validate_authoritative_lease(
        lease: Lease,
        ttl_seconds: int,
        heartbeat_interval_seconds: int,
    ) -> None:
        if (
            lease.ttl_seconds != ttl_seconds
            or lease.heartbeat_interval_seconds != heartbeat_interval_seconds
        ):
            raise SchedulerAdapterError("Authoritative Lease policy drifted.")
        if not (
            parse_utc(lease.acquired_at)
            <= parse_utc(lease.heartbeat_at)
            < parse_utc(lease.expires_at)
        ):
            raise SchedulerAdapterError("Authoritative Lease timestamps are inconsistent.")
        if parse_utc(lease.expires_at) != parse_utc(lease.heartbeat_at) + timedelta(
            seconds=ttl_seconds
        ):
            raise SchedulerAdapterError("Authoritative Lease expiry derivation drifted.")

    def _validate_budget_evidence(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
    ) -> BudgetLedger:
        availability = {
            name: (
                "not_available"
                if name == "microunits" and graph.budget.cost_status == "not_available"
                else "available"
            )
            for name in RESOURCE_NAMES
        }
        reserved = {name: 0 for name in RESOURCE_NAMES}
        used = {name: 0 for name in RESOURCE_NAMES}
        outstanding: dict[str, dict[str, int]] = {}
        original_reservations: dict[str, dict[str, int]] = {}
        expected_ledgers: dict[int, BudgetLedger] = {}
        limits = self._budget_limits(graph)
        tasks = {task.task_id: task for task in graph.tasks}
        created_at = str(
            connection.execute("SELECT value FROM metadata WHERE key = 'created_at'").fetchone()[0]
        )

        def dispatch_admission(
            event: SchedulerEvent,
        ) -> tuple[int, dict[str, int], bool]:
            if event.task_id is None or event.task_id not in tasks:
                raise SchedulerAdapterError("Dispatch budget task evidence is missing.")
            task = tasks[event.task_id]
            binding = next(
                item for item in graph.contexts if item.artifact_id == task.context_snapshot_id
            )
            context_bytes = verified_reference_size(self._root, binding.reference)
            solver_reservation = _m7_solver_reservation(task, graph)
            solver = task.kind.value == "solver"
            reservation = {
                "context_bytes": context_bytes,
                "microunits": (
                    max(
                        0,
                        int(graph.budget.max_microunits or 0)
                        - reserved["microunits"]
                        - used["microunits"],
                    )
                    if graph.budget.cost_status == "available"
                    else 0
                ),
                "solver_calls": 1 if solver else 0,
                "solver_steps": (sum(solver_reservation) if solver_reservation is not None else 0),
                "tool_calls": len(task.required_tools),
            }
            admission_checks = (
                context_bytes <= graph.budget.max_context_bytes_per_dispatch,
                used["dispatches"] < graph.budget.max_dispatches,
                reserved["concurrency"] + (1 if event.before_state == TaskState.READY.value else 0)
                <= limits["concurrency"],
                used["wall_time_seconds"] <= graph.budget.max_wall_time_seconds,
                tuple(
                    reserved[resource] + used[resource] + amount <= limits[resource]
                    for resource, amount in reservation.items()
                ),
            )
            allowed = admission_checks == (
                True,
                True,
                True,
                True,
                tuple(True for _ in reservation),
            )
            return context_bytes, reservation, allowed

        def message_for(event: SchedulerEvent) -> MailboxMessage:
            if event.message_id is None:
                raise SchedulerAdapterError("Budget event message evidence is missing.")
            row = connection.execute(
                "SELECT artifact_json FROM messages WHERE artifact_id = ?",
                (event.message_id,),
            ).fetchone()
            if row is None:
                raise SchedulerAdapterError("Budget event message evidence is unavailable.")
            value = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
            ).value
            assert isinstance(value, MailboxMessage)
            return value

        def change(
            resource: str,
            *,
            reserved_delta: int = 0,
            used_delta: int = 0,
        ) -> None:
            reserved[resource] += reserved_delta
            used[resource] += used_delta
            if reserved[resource] < 0 or used[resource] < 0:
                raise SchedulerAdapterError("Budget evidence replay became negative.")

        rows = connection.execute("SELECT artifact_json FROM events ORDER BY sequence").fetchall()
        for row in rows:
            event = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            ).value
            assert isinstance(event, SchedulerEvent)
            expected_deltas: dict[str, int] = {}
            changed = False
            if event.cause == "initialize":
                expected_ledgers[event.sequence] = BudgetLedger(
                    graph_id=graph_artifact.artifact_id,
                    limits=graph.budget,
                    reserved=reserved,
                    used=used,
                    availability=availability,
                    blocker_codes=(),
                    event_sequence=event.sequence,
                )
                continue
            if event.cause == "worktree-request":
                expected_deltas = {"concurrency": 1}
                change("concurrency", reserved_delta=1)
                changed = True
            elif event.cause == "dispatch-intent":
                message = message_for(event)
                payload = message.to_dict()["payload"]
                assert isinstance(payload, dict)
                reservation_value = payload["budget_reservation"]
                assert isinstance(reservation_value, dict)
                context_bytes, reservation, allowed = dispatch_admission(event)
                payload_reservation = {
                    key: int(reservation_value[key])
                    for key in (
                        "context_bytes",
                        "microunits",
                        "solver_calls",
                        "solver_steps",
                        "tool_calls",
                    )
                }
                _require_semantics(
                    (int(payload["context_bytes"]), payload_reservation, allowed)
                    == (context_bytes, reservation, True),
                    "Dispatch reservation is not deterministically replayable.",
                )
                expected_deltas = {"dispatches": 1, **reservation}
                if event.before_state == TaskState.READY.value:
                    expected_deltas["concurrency"] = 1
                    change("concurrency", reserved_delta=1)
                change("dispatches", used_delta=1)
                for resource, amount in reservation.items():
                    change(resource, reserved_delta=amount)
                if event.lease_id is None or event.lease_id in outstanding:
                    raise SchedulerAdapterError("Dispatch budget Lease evidence is invalid.")
                outstanding[event.lease_id] = reservation
                original_reservations[event.lease_id] = dict(reservation)
                changed = True
            elif event.cause == "dispatch-accepted":
                if event.lease_id is None or event.lease_id not in outstanding:
                    raise SchedulerAdapterError("Dispatch settlement Lease evidence is missing.")
                amount = outstanding[event.lease_id]["context_bytes"]
                expected_deltas = {"context_bytes": amount} if amount else {}
                if amount:
                    change("context_bytes", reserved_delta=-amount, used_delta=amount)
                    outstanding[event.lease_id]["context_bytes"] = 0
                    changed = True
            elif event.cause in {
                "cancel-acknowledgement",
                "dispatch-rejected",
                "lease-expired",
                "result-received",
                "result-terminal",
            }:
                if event.lease_id is None:
                    raise SchedulerAdapterError("Terminal budget Lease evidence is missing.")
                reservation = outstanding.pop(
                    event.lease_id,
                    {
                        resource: 0
                        for resource in (
                            "context_bytes",
                            "microunits",
                            "solver_calls",
                            "solver_steps",
                            "tool_calls",
                        )
                    },
                )
                if event.cause in {
                    "dispatch-rejected",
                    "result-received",
                    "result-terminal",
                } and not any(reservation.values()):
                    dispatch = self._dispatch_for_lease(
                        connection,
                        str(event.task_id),
                        event.lease_id,
                    )
                    if dispatch is None:
                        raise SchedulerAdapterError("Terminal budget dispatch evidence is missing.")
                expected_deltas = {"concurrency": -1}
                change("concurrency", reserved_delta=-1)
                if event.cause in {"result-received", "result-terminal"}:
                    message = message_for(event)
                    payload = message.to_dict()["payload"]
                    assert isinstance(payload, dict)
                    usage = payload["budget_usage"]
                    assert isinstance(usage, dict)
                    actual_usage = {
                        "context_bytes": reservation["context_bytes"],
                        "microunits": int(usage["microunits"]),
                        "solver_calls": int(usage["solver_calls"]),
                        "solver_steps": int(usage["solver_steps"]),
                        "tool_calls": int(usage["tool_calls"]),
                    }
                    original = original_reservations.get(event.lease_id)
                    _require_semantics(
                        original is not None,
                        "Result usage exceeds its rederived dispatch reservation.",
                    )
                    assert original is not None
                    _require_semantics(
                        tuple(
                            actual_usage[resource] <= original[resource]
                            for resource in (
                                "microunits",
                                "solver_calls",
                                "solver_steps",
                                "tool_calls",
                            )
                        )
                        == (True, True, True, True),
                        "Result usage exceeds its rederived dispatch reservation.",
                    )
                elif event.cause in {"cancel-acknowledgement", "lease-expired"}:
                    actual_usage = dict(reservation)
                else:
                    actual_usage = {resource: 0 for resource in reservation}
                for resource, amount in reservation.items():
                    change(resource, reserved_delta=-amount)
                for resource, amount in actual_usage.items():
                    if amount:
                        change(resource, used_delta=amount)
                        expected_deltas[resource] = amount
                if event.reason in {
                    "lease-expired-safe-retry",
                    "safe-read-only-retry",
                    "unambiguous-dispatch-rejection",
                }:
                    change("retries", used_delta=1)
                    expected_deltas["retries"] = 1
                changed = True
            elif event.cause == "worktree-observed":
                if event.after_state == TaskState.BLOCKED.value:
                    expected_deltas = {"concurrency": -1}
                    change("concurrency", reserved_delta=-1)
                    changed = True
            elif event.cause == "wall-time-observed":
                elapsed = int(
                    (parse_utc(event.recorded_at) - parse_utc(created_at)).total_seconds()
                )
                delta = elapsed - used["wall_time_seconds"]
                if elapsed < 0 or delta <= 0:
                    raise SchedulerAdapterError("Wall-time budget evidence is invalid.")
                expected_deltas = {"wall_time_seconds": delta}
                change("wall_time_seconds", used_delta=delta)
                changed = True
            elif event.cause == "dispatch-budget-blocked":
                _, _, allowed = dispatch_admission(event)
                _require_semantics(
                    not allowed,
                    "Budget blocker has no replayable admission failure.",
                )
            elif event.cause in _EVENT_BUDGET_CAUSES:
                expected_deltas = {}

            if event.budget_deltas != dict(sorted(expected_deltas.items())):
                raise SchedulerAdapterError("Scheduler event budget semantics drifted.")
            for resource in RESOURCE_NAMES:
                if resource != "wall_time_seconds" and (
                    reserved[resource] + used[resource] > limits[resource]
                ):
                    raise SchedulerAdapterError(
                        "Budget evidence exceeds its configured admission limit."
                    )
                if availability[resource] == "not_available" and (
                    reserved[resource] or used[resource]
                ):
                    raise SchedulerAdapterError("Unavailable budget evidence was consumed.")
            if changed:
                expected_ledgers[event.sequence] = BudgetLedger(
                    graph_id=graph_artifact.artifact_id,
                    limits=graph.budget,
                    reserved=reserved,
                    used=used,
                    availability=availability,
                    blocker_codes=(),
                    event_sequence=event.sequence,
                )

        budget_entries = connection.execute(
            "SELECT * FROM budget_entries ORDER BY event_sequence"
        ).fetchall()
        if [int(entry["event_sequence"]) for entry in budget_entries] != list(expected_ledgers):
            raise SchedulerAdapterError("Budget evidence snapshot sequence drifted.")
        for entry in budget_entries:
            artifact = _parse_artifact_json(
                entry["artifact_json"], SchedulerArtifactType.BUDGET_LEDGER
            )
            ledger = artifact.value
            assert isinstance(ledger, BudgetLedger)
            expected = expected_ledgers[int(entry["event_sequence"])]
            if (
                artifact.artifact_id != entry["artifact_id"]
                or ledger.to_dict() != expected.to_dict()
            ):
                raise SchedulerAdapterError("Budget evidence semantic replay drifted.")
        if not budget_entries:
            raise SchedulerAdapterError("Budget evidence is missing.")
        return expected_ledgers[int(budget_entries[-1]["event_sequence"])]

    def _validate_projections(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
    ) -> None:
        graph = graph_artifact.value
        assert isinstance(graph, TaskGraph)
        task_rows = connection.execute("SELECT * FROM tasks ORDER BY task_id").fetchall()
        if [row["task_id"] for row in task_rows] != [item.task_id for item in graph.tasks]:
            raise SchedulerAdapterError("Scheduler task projection does not match the graph.")
        ranks = topological_ranks(graph)
        latest_projections: dict[str, TaskProjection] = {}
        event_rows = connection.execute(
            "SELECT artifact_json FROM events ORDER BY sequence"
        ).fetchall()
        approval_events: set[tuple[str, str, str, int]] = set()
        for row in event_rows:
            artifact = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            )
            event = artifact.value
            assert isinstance(event, SchedulerEvent)
            if event.task_id is not None:
                if event.task_projection is None:
                    raise SchedulerAdapterError("Task event projection is missing.")
                latest_projections[event.task_id] = event.task_projection
            if event.cause == "approval-consumed":
                if event.approval_id is None or event.message_id is None or event.task_id is None:
                    raise SchedulerAdapterError("Approval consumption event is incomplete.")
                approval_events.add(
                    (event.approval_id, event.message_id, event.task_id, event.sequence)
                )
        for row, task in zip(task_rows, graph.tasks, strict=True):
            if json.loads(row["definition_json"]) != task.to_dict():
                raise SchedulerAdapterError("Scheduler task definition drifted.")
            if int(row["wave"]) != task.wave or int(row["topological_rank"]) != ranks[task.task_id]:
                raise SchedulerAdapterError("Scheduler task ordering projection drifted.")
            if int(row["attempt"]) != int(row["fence"]) or int(row["attempt"]) > task.max_attempts:
                raise SchedulerAdapterError("Scheduler task attempt or fence drifted.")
            actual_projection = _projection_from_row(row)
            expected_projection = latest_projections.get(task.task_id)
            if expected_projection is None:
                expected_projection = TaskProjection(
                    task_id=task.task_id,
                    state=TaskState.READY if not task.dependencies else TaskState.PLANNED,
                    dispatch_phase=DispatchPhase.NOT_DISPATCHED,
                    outcome=TaskOutcome.NONE,
                    attempt=0,
                    fence=0,
                    blockers=(),
                )
            if actual_projection != expected_projection:
                raise SchedulerAdapterError(
                    "Scheduler task projection drifted from event evidence."
                )
        expected_dependencies = {
            (task.task_id, dependency) for task in graph.tasks for dependency in task.dependencies
        }
        actual_dependencies = {
            (str(row["task_id"]), str(row["dependency_id"]))
            for row in connection.execute(
                "SELECT task_id, dependency_id FROM dependencies"
            ).fetchall()
        }
        if actual_dependencies != expected_dependencies:
            raise SchedulerAdapterError("Scheduler dependency projection drifted.")
        lease_rows = connection.execute("SELECT * FROM current_leases").fetchall()
        ttl_seconds, heartbeat_interval_seconds = self._lease_policy(connection)
        latest_lease_status: dict[str, str] = {}
        for history in connection.execute(
            "SELECT task_id, status FROM lease_history ORDER BY event_sequence"
        ).fetchall():
            latest_lease_status[str(history["task_id"])] = str(history["status"])
        expected_current_lease_tasks = {
            task_id
            for task_id, status in latest_lease_status.items()
            if status == LeaseStatus.CURRENT.value
        }
        actual_current_lease_tasks = {str(row["task_id"]) for row in lease_rows}
        if actual_current_lease_tasks != expected_current_lease_tasks:
            raise SchedulerAdapterError("Current lease projection set drifted from lease history.")
        for row in lease_rows:
            artifact = _parse_artifact_json(row["artifact_json"], SchedulerArtifactType.LEASE)
            lease = artifact.value
            assert isinstance(lease, Lease)
            self._validate_authoritative_lease(
                lease,
                ttl_seconds,
                heartbeat_interval_seconds,
            )
            if (
                artifact.artifact_id != row["projection_artifact_id"]
                or lease.task_id != row["task_id"]
                or lease.owner_id != row["owner_id"]
                or lease.attempt != row["attempt"]
                or lease.fence != row["fence"]
                or lease.idempotency_key != row["idempotency_key"]
                or lease.acquired_at != row["acquired_at"]
                or lease.heartbeat_at != row["heartbeat_at"]
                or lease.expires_at != row["expires_at"]
                or lease.status is not LeaseStatus.CURRENT
            ):
                raise SchedulerAdapterError("Current lease projection drifted.")
            history = connection.execute(
                "SELECT * FROM lease_history WHERE task_id = ? ORDER BY event_sequence DESC "
                "LIMIT 1",
                (row["task_id"],),
            ).fetchone()
            if (
                history is None
                or history["status"] != LeaseStatus.CURRENT.value
                or history["artifact_id"] != row["projection_artifact_id"]
                or history["authority_lease_id"] != row["lease_id"]
                or history["artifact_json"] != row["artifact_json"]
            ):
                raise SchedulerAdapterError("Current lease does not match lease history.")
        for history in connection.execute("SELECT * FROM lease_history").fetchall():
            artifact = _parse_artifact_json(history["artifact_json"], SchedulerArtifactType.LEASE)
            lease = artifact.value
            assert isinstance(lease, Lease)
            event = connection.execute(
                "SELECT artifact_json FROM events WHERE sequence = ?",
                (history["event_sequence"],),
            ).fetchone()
            if event is None:
                raise SchedulerAdapterError("Lease history event is missing.")
            event_value = _parse_artifact_json(
                event["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            ).value
            assert isinstance(event_value, SchedulerEvent)
            if (
                artifact.artifact_id != history["artifact_id"]
                or lease.task_id != history["task_id"]
                or lease.fence != history["fence"]
                or lease.status.value != history["status"]
                or event_value.task_id != lease.task_id
                or event_value.lease_id != history["authority_lease_id"]
            ):
                raise SchedulerAdapterError("Lease history projection drifted.")
        budget_rows = connection.execute(
            "SELECT resource, reserved, used, availability FROM budget_totals ORDER BY resource"
        ).fetchall()
        if [row["resource"] for row in budget_rows] != list(RESOURCE_NAMES):
            raise SchedulerAdapterError("Budget projection resources are incomplete.")
        if any(row["reserved"] < 0 or row["used"] < 0 for row in budget_rows):
            raise SchedulerAdapterError("Budget projection contains a negative total.")
        latest_ledger = self._validate_budget_evidence(connection, graph_artifact, graph)
        if (
            dict(latest_ledger.reserved)
            != {str(row["resource"]): int(row["reserved"]) for row in budget_rows}
            or dict(latest_ledger.used)
            != {str(row["resource"]): int(row["used"]) for row in budget_rows}
            or dict(latest_ledger.availability)
            != {str(row["resource"]): str(row["availability"]) for row in budget_rows}
        ):
            raise SchedulerAdapterError("Budget totals drifted from immutable ledger evidence.")
        current_worktrees = connection.execute("SELECT * FROM current_worktree_leases").fetchall()
        latest_worktree_rows: dict[str, sqlite3.Row] = {}
        for history_row in connection.execute(
            "SELECT * FROM worktree_lease_history ORDER BY event_sequence, artifact_id"
        ).fetchall():
            latest_worktree_rows[str(history_row["task_id"])] = history_row
        active_worktree_statuses = {
            WorktreeLeaseStatus.REQUESTED.value,
            WorktreeLeaseStatus.OBSERVED.value,
        }
        expected_current_worktree_tasks = {
            task_id
            for task_id, history_row in latest_worktree_rows.items()
            if history_row["status"] in active_worktree_statuses
        }
        actual_current_worktree_tasks = {str(row["task_id"]) for row in current_worktrees}
        if actual_current_worktree_tasks != expected_current_worktree_tasks:
            raise SchedulerAdapterError(
                "Current Worktree Lease projection set drifted from worktree history."
            )
        for row in current_worktrees:
            artifact = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.WORKTREE_LEASE
            )
            lease = artifact.value
            assert isinstance(lease, WorktreeLease)
            history = latest_worktree_rows.get(str(row["task_id"]))
            if (
                artifact.artifact_id != row["artifact_id"]
                or lease.task_id != row["task_id"]
                or lease.owner_id != row["owner_id"]
                or lease.fence != row["fence"]
                or lease.worktree != row["worktree"]
                or history is None
                or history["status"] not in active_worktree_statuses
                or history["artifact_id"] != row["artifact_id"]
                or history["artifact_json"] != row["artifact_json"]
            ):
                raise SchedulerAdapterError("Current worktree lease projection drifted.")
        actual_approvals = {
            (
                str(row["approval_id"]),
                str(row["message_id"]),
                str(row["task_id"]),
                int(row["event_sequence"]),
            )
            for row in connection.execute("SELECT * FROM approval_consumptions").fetchall()
        }
        if actual_approvals != approval_events:
            raise SchedulerAdapterError("Approval consumption projection drifted.")
        expected_capabilities: dict[str, object] = {}
        for _, _, capability_message, _ in _adopted_message_entries(
            connection,
            cause="capability-observed",
            message_type=MessageType.CAPABILITY_OBSERVATION,
        ):
            capability_payload = capability_message.to_dict()["payload"]
            assert isinstance(capability_payload, dict)
            expected_capabilities[capability_message.sender] = capability_payload["capabilities"]
        metadata_capabilities = json.loads(
            connection.execute(
                "SELECT value FROM metadata WHERE key = 'host_capabilities'"
            ).fetchone()[0]
        )
        if metadata_capabilities != expected_capabilities:
            raise SchedulerAdapterError("Host capability projection drifted.")

    def _status(self, connection: sqlite3.Connection) -> LoadedSchedulerArtifact:
        graph_artifact = self._graph(connection)
        graph = graph_artifact.value
        assert isinstance(graph, TaskGraph)
        rows = connection.execute("SELECT * FROM tasks ORDER BY task_id").fetchall()
        projections = tuple(_projection_from_row(row) for row in rows)
        ranks = {row["task_id"]: (row["wave"], row["topological_rank"]) for row in rows}
        ready_order = tuple(
            sorted(
                (item.task_id for item in projections if item.state is TaskState.READY),
                key=lambda identifier: (*ranks[identifier], identifier),
            )
        )
        event = connection.execute(
            "SELECT sequence, event_sha256 FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        ledger = self._budget_ledger(
            connection, graph_artifact.artifact_id, graph, event["sequence"]
        )
        ledger_artifact = artifact_from_value(SchedulerArtifactType.BUDGET_LEDGER, ledger)
        lease_ids = tuple(
            row[0]
            for row in connection.execute(
                "SELECT lease_id FROM current_leases ORDER BY lease_id"
            ).fetchall()
        )
        message_ids = tuple(
            row[0]
            for row in connection.execute(
                "SELECT artifact_id FROM messages ORDER BY artifact_id LIMIT 1000"
            ).fetchall()
        )
        worktree_ids = tuple(
            row[0]
            for row in connection.execute(
                "SELECT artifact_id FROM current_worktree_leases ORDER BY artifact_id"
            ).fetchall()
        )
        state = SchedulerState(
            graph_id=graph_artifact.artifact_id,
            candidate=graph.candidate,
            tasks=projections,
            ready_order=ready_order,
            lease_ids=lease_ids,
            message_ids=message_ids,
            budget_ledger_id=ledger_artifact.artifact_id,
            worktree_lease_ids=worktree_ids,
            event_sequence=event["sequence"],
            event_head_sha256=event["event_sha256"],
        )
        return artifact_from_value(SchedulerArtifactType.SCHEDULER_STATE, state)

    def _ingest_message(
        self,
        connection: sqlite3.Connection,
        root: Path,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        host_id: str,
        artifact: LoadedSchedulerArtifact,
        message: MailboxMessage,
        timestamp: str,
        outgoing: list[LoadedSchedulerArtifact],
    ) -> bool:
        existing = connection.execute(
            "SELECT artifact_json FROM messages WHERE artifact_id = ?",
            (artifact.artifact_id,),
        ).fetchone()
        if existing is not None:
            self._append_event(
                connection,
                graph_artifact,
                timestamp,
                actor="scheduler",
                cause="duplicate-message",
                task_id=message.task_id,
                context_snapshot_id=message.context_snapshot_id,
                before_state=None,
                after_state=None,
                lease_id=message.lease_id,
                message_id=artifact.artifact_id,
                reason="duplicate-message-retained",
            )
            return True
        repeatable = {
            MessageType.APPROVAL_DECISION,
            MessageType.HEARTBEAT,
            MessageType.WORKTREE_OBSERVATION,
        }
        if message.idempotency_key is not None and message.message_type not in repeatable:
            conflict = connection.execute(
                """SELECT artifact_id FROM messages
                   WHERE idempotency_key = ? AND message_type = ? AND direction = ?""",
                (
                    message.idempotency_key,
                    message.message_type.value,
                    message.direction.value,
                ),
            ).fetchone()
            if conflict is not None:
                self._append_rejection(
                    connection,
                    graph_artifact,
                    message,
                    artifact.artifact_id,
                    timestamp,
                    "conflicting-idempotency-message",
                )
                return False
        if message.graph_id != graph_artifact.artifact_id or message.candidate != graph.candidate:
            self._append_rejection(
                connection,
                graph_artifact,
                message,
                artifact.artifact_id,
                timestamp,
                "foreign-graph-or-candidate",
            )
            return False
        missing_parent = next(
            (
                parent
                for parent in message.causal_parent_message_ids
                if self._primary_event_for_message(connection, parent) is None
            ),
            None,
        )
        if missing_parent is not None:
            self._append_rejection(
                connection,
                graph_artifact,
                message,
                artifact.artifact_id,
                timestamp,
                "missing-causal-parent",
            )
            return False
        if message.message_type is MessageType.CAPABILITY_OBSERVATION:
            if message.sender != host_id or message.recipient != "HST-SCHEDULER":
                self._append_rejection(
                    connection,
                    graph_artifact,
                    message,
                    artifact.artifact_id,
                    timestamp,
                    "foreign-host",
                )
                return False
            self._insert_message(connection, artifact, message)
            payload = message.to_dict()["payload"]
            assert isinstance(payload, dict)
            capabilities = payload["capabilities"]
            observed_by_host = self._capabilities_by_host(connection)
            observed_by_host[message.sender] = list(capabilities)
            connection.execute(
                "UPDATE metadata SET value = ? WHERE key = 'host_capabilities'",
                (canonical_json_bytes(observed_by_host).decode("ascii"),),
            )
            self._append_event(
                connection,
                graph_artifact,
                timestamp,
                actor=host_id,
                cause="capability-observed",
                task_id=None,
                context_snapshot_id=None,
                before_state=None,
                after_state=None,
                message_id=artifact.artifact_id,
            )
            return True
        task = next((item for item in graph.tasks if item.task_id == message.task_id), None)
        if task is None:
            self._append_rejection(
                connection,
                graph_artifact,
                message,
                artifact.artifact_id,
                timestamp,
                "unknown-task",
            )
            return False
        binding = next(
            item for item in graph.contexts if item.artifact_id == task.context_snapshot_id
        )
        if (
            message.context_snapshot_id != task.context_snapshot_id
            or SENSITIVITY_RANK[message.sensitivity] < SENSITIVITY_RANK[binding.sensitivity]
        ):
            self._append_rejection(
                connection,
                graph_artifact,
                message,
                artifact.artifact_id,
                timestamp,
                "context-or-sensitivity-mismatch",
            )
            return False
        if message.message_type is MessageType.APPROVAL_DECISION:
            expected_actor = {
                "owner": ("HST-OWNER", "Owner"),
                "technical_sandbox": (
                    "HST-TECHNICAL-SANDBOX",
                    "Technical sandbox reviewer",
                ),
            }[str(message.payload["approval_type"])]
            current = connection.execute(
                "SELECT * FROM current_leases WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            if (
                message.recipient != "HST-SCHEDULER"
                or (message.sender, message.payload["authority"]) != expected_actor
                or str(message.payload["approval_type"]) not in task.approval_stops
            ):
                self._append_rejection(
                    connection,
                    graph_artifact,
                    message,
                    artifact.artifact_id,
                    timestamp,
                    "approval-recipient-mismatch",
                )
                return False
            if (
                current is None
                or message.attempt != current["attempt"]
                or message.lease_id != current["lease_id"]
                or message.fence != current["fence"]
                or message.idempotency_key != current["idempotency_key"]
            ):
                self._append_rejection(
                    connection,
                    graph_artifact,
                    message,
                    artifact.artifact_id,
                    timestamp,
                    "approval-proposal-mismatch",
                )
                return False
            if parse_utc(str(message.payload["expires_at"])) <= parse_utc(
                str(message.payload["approved_at"])
            ):
                self._append_rejection(
                    connection,
                    graph_artifact,
                    message,
                    artifact.artifact_id,
                    timestamp,
                    "approval-time-window-invalid",
                )
                return False
            self._insert_message(connection, artifact, message)
            self._append_event(
                connection,
                graph_artifact,
                timestamp,
                actor=message.sender,
                cause="approval-received",
                task_id=task.task_id,
                context_snapshot_id=task.context_snapshot_id,
                before_state=None,
                after_state=None,
                lease_id=message.lease_id,
                message_id=artifact.artifact_id,
                approval_id=str(message.payload["approval_id"]),
            )
            worktree_row = connection.execute(
                "SELECT * FROM current_worktree_leases WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            task_row = connection.execute(
                "SELECT dispatch_phase FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            if (
                current is not None
                and worktree_row is not None
                and task_row["dispatch_phase"] == DispatchPhase.NOT_DISPATCHED.value
            ):
                parent = self._latest_worktree_observation_message_id(
                    connection, task.task_id, current["lease_id"]
                )
                if parent is not None:
                    dispatch = self._activate_dispatch_after_worktree(
                        connection,
                        graph_artifact,
                        graph,
                        task,
                        current,
                        parent,
                        timestamp,
                    )
                    if dispatch is not None:
                        outgoing.append(dispatch)
            return True
        current = connection.execute(
            "SELECT * FROM current_leases WHERE task_id = ?", (task.task_id,)
        ).fetchone()
        if (
            current is None
            or message.sender != current["owner_id"]
            or message.sender != host_id
            or message.recipient != "HST-SCHEDULER"
            or message.attempt != current["attempt"]
            or message.lease_id != current["lease_id"]
            or message.fence != current["fence"]
            or message.idempotency_key != current["idempotency_key"]
        ):
            self._append_rejection(
                connection,
                graph_artifact,
                message,
                artifact.artifact_id,
                timestamp,
                "stale-foreign-or-late-message",
            )
            return False
        if parse_utc(timestamp) >= parse_utc(current["expires_at"]):
            self._append_rejection(
                connection,
                graph_artifact,
                message,
                artifact.artifact_id,
                timestamp,
                "message-at-or-after-lease-expiry",
            )
            return False
        phase = DispatchPhase(
            connection.execute(
                "SELECT dispatch_phase FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()[0]
        )
        causal_requirements = {
            MessageType.DISPATCH_ACKNOWLEDGEMENT: (
                {DispatchPhase.INTENT_PENDING},
                MessageType.DISPATCH_INTENT,
            ),
            MessageType.HEARTBEAT: (
                {DispatchPhase.INTENT_PENDING, DispatchPhase.ACCEPTED},
                MessageType.DISPATCH_INTENT,
            ),
            MessageType.TASK_RESULT: (
                {DispatchPhase.INTENT_PENDING, DispatchPhase.ACCEPTED},
                MessageType.DISPATCH_INTENT,
            ),
        }
        requirement = causal_requirements.get(message.message_type)
        if requirement is not None and (
            phase not in requirement[0]
            or not self._has_causal_parent(connection, message, requirement[1], current["lease_id"])
        ):
            self._append_rejection(
                connection,
                graph_artifact,
                message,
                artifact.artifact_id,
                timestamp,
                "dispatch-cause-or-phase-mismatch",
            )
            return False
        worktree_authority: tuple[WorktreeLease, bool, str | None] | None = None
        if message.message_type is MessageType.WORKTREE_OBSERVATION and (
            graph.worktree_plan is None or task.worktree_assignment is None
        ):
            self._append_rejection(
                connection,
                graph_artifact,
                message,
                artifact.artifact_id,
                timestamp,
                "unexpected-worktree-observation",
            )
            return False
        if message.message_type is MessageType.WORKTREE_OBSERVATION:
            task_row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            current_worktree_row = connection.execute(
                "SELECT artifact_json FROM current_worktree_leases WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            causal_request = self._causal_parent_message(
                connection,
                message,
                MessageType.WORKTREE_REQUEST,
                current["lease_id"],
            )
            try:
                _require_semantics(
                    task_row is not None
                    and current_worktree_row is not None
                    and causal_request is not None,
                    "Worktree observation authority is incomplete.",
                )
                lease = _parse_artifact_json(
                    current["artifact_json"], SchedulerArtifactType.LEASE
                ).value
                prior_worktree = _parse_artifact_json(
                    current_worktree_row["artifact_json"],
                    SchedulerArtifactType.WORKTREE_LEASE,
                ).value
                assert isinstance(lease, Lease)
                assert isinstance(prior_worktree, WorktreeLease)
                assert task_row is not None
                assert causal_request is not None
                worktree_authority = self._derive_exact_worktree_observation(
                    graph_artifact.artifact_id,
                    graph,
                    task,
                    _projection_from_row(task_row),
                    str(current["lease_id"]),
                    lease,
                    prior_worktree,
                    message,
                    causal_request,
                    timestamp,
                )
            except SchedulerAdapterError:
                self._append_rejection(
                    connection,
                    graph_artifact,
                    message,
                    artifact.artifact_id,
                    timestamp,
                    "worktree-request-or-assignment-mismatch",
                )
                return False
        if message.message_type is MessageType.CANCEL_ACKNOWLEDGEMENT and (
            current["task_id"] != task.task_id
            or connection.execute(
                "SELECT dispatch_phase FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()[0]
            != DispatchPhase.CANCELLATION_REQUESTED.value
            or not self._has_causal_parent(
                connection,
                message,
                MessageType.CANCEL_REQUEST,
                current["lease_id"],
            )
        ):
            self._append_rejection(
                connection,
                graph_artifact,
                message,
                artifact.artifact_id,
                timestamp,
                "cancel-request-missing",
            )
            return False
        self._insert_message(connection, artifact, message)
        if message.message_type is MessageType.DISPATCH_ACKNOWLEDGEMENT:
            self._apply_dispatch_ack(
                connection,
                graph_artifact,
                graph,
                task,
                current,
                artifact,
                message,
                timestamp,
            )
        elif message.message_type is MessageType.HEARTBEAT:
            self._apply_heartbeat(connection, graph_artifact, task, current, artifact, timestamp)
        elif message.message_type is MessageType.TASK_RESULT:
            validate_task_result_reference(
                root,
                graph,
                message,
                solver_lease_evidence=(
                    self._m7_lease_evidence(connection, message, current)
                    if task.kind.value == "solver"
                    else None
                ),
            )
            self._apply_result(
                connection,
                graph_artifact,
                graph,
                task,
                current,
                artifact,
                message,
                timestamp,
            )
        elif message.message_type is MessageType.CANCEL_ACKNOWLEDGEMENT:
            self._apply_cancel_ack(
                connection,
                graph_artifact,
                graph,
                task,
                current,
                artifact,
                message,
                timestamp,
            )
        elif message.message_type is MessageType.WORKTREE_OBSERVATION:
            assert worktree_authority is not None
            self._apply_worktree_observation(
                connection,
                graph_artifact,
                graph,
                task,
                current,
                artifact,
                message,
                worktree_authority,
                timestamp,
                outgoing,
            )
        else:
            self._append_rejection(
                connection,
                graph_artifact,
                message,
                artifact.artifact_id,
                timestamp,
                "host-message-not-adoptable",
            )
            return False
        return True

    def _causal_parent_message(
        self,
        connection: sqlite3.Connection,
        message: MailboxMessage,
        expected_type: MessageType,
        lease_id: str,
        *,
        before_event_sequence: int | None = None,
    ) -> tuple[str, MailboxMessage] | None:
        if len(message.causal_parent_message_ids) != 1:
            return None
        for parent_id in message.causal_parent_message_ids:
            row = connection.execute(
                "SELECT artifact_json FROM messages WHERE artifact_id = ?", (parent_id,)
            ).fetchone()
            if row is None:
                continue
            parent_artifact = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
            )
            parent = parent_artifact.value
            assert isinstance(parent, MailboxMessage)
            primary = self._primary_event_for_message(connection, parent_id)
            if (
                parent.message_type is expected_type
                and primary is not None
                and primary.cause in _PRIMARY_EVENT_CAUSES_BY_MESSAGE[expected_type]
                and (before_event_sequence is None or primary.sequence < before_event_sequence)
                and parent.task_id == message.task_id
                and parent.attempt == message.attempt
                and parent.lease_id == lease_id
                and parent.fence == message.fence
                and parent.idempotency_key == message.idempotency_key
            ):
                return parent_id, parent
        return None

    def _has_causal_parent(
        self,
        connection: sqlite3.Connection,
        message: MailboxMessage,
        expected_type: MessageType,
        lease_id: str,
        *,
        before_event_sequence: int | None = None,
    ) -> bool:
        return (
            self._causal_parent_message(
                connection,
                message,
                expected_type,
                lease_id,
                before_event_sequence=before_event_sequence,
            )
            is not None
        )

    @staticmethod
    def _primary_event_for_message(
        connection: sqlite3.Connection,
        message_id: str,
    ) -> SchedulerEvent | None:
        primary: list[SchedulerEvent] = []
        for row in connection.execute(
            "SELECT artifact_json FROM events ORDER BY sequence"
        ).fetchall():
            event = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            ).value
            assert isinstance(event, SchedulerEvent)
            if event.message_id == message_id and event.cause in _PRIMARY_MESSAGE_EVENT_CAUSES:
                primary.append(event)
        return primary[0] if len(primary) == 1 else None

    def _latest_worktree_observation_message_id(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        lease_id: str,
        *,
        before_sequence: int | None = None,
        before_event_sequence: int | None = None,
    ) -> str | None:
        if before_sequence is None:
            rows = connection.execute(
                "SELECT artifact_id, artifact_json FROM messages WHERE message_type = ? "
                "AND task_id = ? ORDER BY sequence DESC",
                (MessageType.WORKTREE_OBSERVATION.value, task_id),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT artifact_id, artifact_json FROM messages WHERE message_type = ? "
                "AND task_id = ? AND sequence < ? ORDER BY sequence DESC",
                (MessageType.WORKTREE_OBSERVATION.value, task_id, before_sequence),
            ).fetchall()
        for row in rows:
            message = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
            ).value
            assert isinstance(message, MailboxMessage)
            primary = self._primary_event_for_message(connection, str(row["artifact_id"]))
            if (
                message.lease_id == lease_id
                and primary is not None
                and primary.cause == "worktree-observed"
                and (before_event_sequence is None or primary.sequence < before_event_sequence)
            ):
                return str(row["artifact_id"])
        return None

    def _insert_message(
        self,
        connection: sqlite3.Connection,
        artifact: LoadedSchedulerArtifact,
        message: MailboxMessage,
    ) -> None:
        sequence = int(
            connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages").fetchone()[0]
        )
        connection.execute(
            "INSERT INTO messages(sequence, artifact_id, message_type, direction, "
            "task_id, idempotency_key, artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sequence,
                artifact.artifact_id,
                message.message_type.value,
                message.direction.value,
                message.task_id,
                message.idempotency_key,
                _artifact_json(artifact),
            ),
        )

    def _append_rejection(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        message: MailboxMessage,
        message_id: str,
        timestamp: str,
        reason: str,
    ) -> None:
        graph = graph_artifact.value
        assert isinstance(graph, TaskGraph)
        known_task = next(
            (task for task in graph.tasks if task.task_id == message.task_id),
            None,
        )
        self._append_event(
            connection,
            graph_artifact,
            timestamp,
            actor="scheduler",
            cause="message-rejected",
            task_id=known_task.task_id if known_task is not None else None,
            context_snapshot_id=(
                known_task.context_snapshot_id if known_task is not None else None
            ),
            before_state=None,
            after_state=None,
            lease_id=message.lease_id,
            message_id=message_id,
            reason=reason,
        )

    def _apply_dispatch_ack(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        task: Any,
        current: sqlite3.Row,
        artifact: LoadedSchedulerArtifact,
        message: MailboxMessage,
        timestamp: str,
    ) -> None:
        if bool(message.payload["accepted"]):
            context_used = self._settle_context_reservation(
                connection, task.task_id, current["lease_id"]
            )
            connection.execute(
                "UPDATE tasks SET dispatch_phase = ? WHERE task_id = ?",
                (DispatchPhase.ACCEPTED.value, task.task_id),
            )
            sequence = self._append_event(
                connection,
                graph_artifact,
                timestamp,
                actor=current["owner_id"],
                cause="dispatch-accepted",
                task_id=task.task_id,
                context_snapshot_id=task.context_snapshot_id,
                before_state=TaskState.RUNNING.value,
                after_state=TaskState.RUNNING.value,
                lease_id=current["lease_id"],
                message_id=artifact.artifact_id,
                budget_deltas={"context_bytes": context_used} if context_used else None,
            )
            if context_used:
                self._append_budget_snapshot(connection, graph_artifact, graph, sequence)
            return
        observed = str(message.payload["effect_observed"])
        retry_reserved = (
            observed == "none"
            and task.effect_kind is EffectKind.READ_ONLY
            and current["attempt"] < task.max_attempts
            and self._reserve_retry(connection, graph)
        )
        if retry_reserved:
            next_state = TaskState.READY
            outcome = TaskOutcome.FAILED
            reason = "unambiguous-dispatch-rejection"
        else:
            next_state = TaskState.BLOCKED
            outcome = TaskOutcome.UNKNOWN
            reason = "dispatch-rejection-ambiguous"
        resource_deltas = self._close_attempt_budget(
            connection, task.task_id, current["lease_id"], conservative=False
        )
        self._release_current_lease(connection, current, task, outcome)
        connection.execute(
            "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ?, "
            "blockers_json = ? WHERE task_id = ?",
            (
                next_state.value,
                DispatchPhase.NOT_DISPATCHED.value,
                outcome.value,
                _blockers_json(reason),
                task.task_id,
            ),
        )
        self._change_budget(connection, "concurrency", reserved_delta=-1)
        sequence = self._append_event(
            connection,
            graph_artifact,
            timestamp,
            actor=current["owner_id"],
            cause="dispatch-rejected",
            task_id=task.task_id,
            context_snapshot_id=task.context_snapshot_id,
            before_state=TaskState.RUNNING.value,
            after_state=next_state.value,
            lease_id=current["lease_id"],
            message_id=artifact.artifact_id,
            reason=reason,
            budget_deltas={
                "concurrency": -1,
                **resource_deltas,
                **({"retries": 1} if retry_reserved else {}),
            },
        )
        self._append_budget_snapshot(connection, graph_artifact, graph, sequence)

    def _apply_heartbeat(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        task: Any,
        current: sqlite3.Row,
        artifact: LoadedSchedulerArtifact,
        timestamp: str,
    ) -> None:
        now = parse_utc(timestamp)
        lease_artifact = _parse_artifact_json(current["artifact_json"], SchedulerArtifactType.LEASE)
        lease = lease_artifact.value
        assert isinstance(lease, Lease)
        expires = format_utc(now + timedelta(seconds=lease.ttl_seconds))
        refreshed = Lease(
            graph_id=lease.graph_id,
            task_id=lease.task_id,
            candidate=lease.candidate,
            context_snapshot_id=lease.context_snapshot_id,
            attempt=lease.attempt,
            owner_id=lease.owner_id,
            fence=lease.fence,
            idempotency_key=lease.idempotency_key,
            acquired_at=lease.acquired_at,
            heartbeat_at=timestamp,
            expires_at=expires,
            ttl_seconds=lease.ttl_seconds,
            heartbeat_interval_seconds=lease.heartbeat_interval_seconds,
            status=LeaseStatus.CURRENT,
            release_outcome=TaskOutcome.NONE,
        )
        refreshed_artifact = artifact_from_value(SchedulerArtifactType.LEASE, refreshed)
        connection.execute(
            "UPDATE current_leases SET projection_artifact_id = ?, heartbeat_at = ?, "
            "expires_at = ?, artifact_json = ? WHERE task_id = ?",
            (
                refreshed_artifact.artifact_id,
                timestamp,
                expires,
                _artifact_json(refreshed_artifact),
                task.task_id,
            ),
        )
        sequence = self._append_event(
            connection,
            graph_artifact,
            timestamp,
            actor=current["owner_id"],
            cause="heartbeat",
            task_id=task.task_id,
            context_snapshot_id=task.context_snapshot_id,
            before_state=TaskState.RUNNING.value,
            after_state=TaskState.RUNNING.value,
            lease_id=current["lease_id"],
            message_id=artifact.artifact_id,
        )
        connection.execute(
            "INSERT INTO lease_history(event_sequence, artifact_id, authority_lease_id, "
            "task_id, fence, status, artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sequence,
                refreshed_artifact.artifact_id,
                current["lease_id"],
                task.task_id,
                current["fence"],
                LeaseStatus.CURRENT.value,
                _artifact_json(refreshed_artifact),
            ),
        )

    def _apply_result(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        task: Any,
        current: sqlite3.Row,
        artifact: LoadedSchedulerArtifact,
        message: MailboxMessage,
        timestamp: str,
    ) -> None:
        outcome_text = str(message.payload["outcome"])
        effect = str(message.payload["effect_observed"])
        resource_deltas = self._settle_result_budget(
            connection, task.task_id, current["lease_id"], message
        )
        if outcome_text == "succeeded" and effect != "ambiguous":
            self._release_current_lease(connection, current, task, TaskOutcome.SUCCEEDED)
            connection.execute(
                "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ?, "
                "blockers_json = '[]' WHERE task_id = ?",
                (
                    TaskState.VERIFICATION.value,
                    DispatchPhase.ACCEPTED.value,
                    TaskOutcome.SUCCEEDED.value,
                    task.task_id,
                ),
            )
            self._change_budget(connection, "concurrency", reserved_delta=-1)
            sequence = self._append_event(
                connection,
                graph_artifact,
                timestamp,
                actor=current["owner_id"],
                cause="result-received",
                task_id=task.task_id,
                context_snapshot_id=task.context_snapshot_id,
                before_state=TaskState.RUNNING.value,
                after_state=TaskState.VERIFICATION.value,
                lease_id=current["lease_id"],
                message_id=artifact.artifact_id,
                result_id=artifact.artifact_id,
                budget_deltas={"concurrency": -1, **resource_deltas},
            )
            evidence = message.payload["evidence_refs"]
            incomplete_reviews = (
                tuple(
                    str(row["task_id"])
                    for row in connection.execute(
                        "SELECT task_id FROM tasks WHERE task_id IN ("
                        + ",".join("?" for _ in task.review_targets)
                        + ") AND state != ? ORDER BY task_id",
                        (*task.review_targets, TaskState.COMPLETED.value),
                    ).fetchall()
                )
                if task.review_targets
                else ()
            )
            verification_reason = None
            if task.evidence_predicate == ("evidence-reference-present",) and not evidence:
                verification_reason = "evidence-predicate-unsatisfied"
            elif task.terminal_predicate != ("agent-result-valid",):
                verification_reason = "terminal-predicate-unsupported"
            elif incomplete_reviews:
                verification_reason = "review-targets-unsatisfied"
            if verification_reason is not None:
                connection.execute(
                    "UPDATE tasks SET state = ?, outcome = ?, blockers_json = ? WHERE task_id = ?",
                    (
                        TaskState.BLOCKED.value,
                        TaskOutcome.UNKNOWN.value,
                        _blockers_json(verification_reason, incomplete_reviews),
                        task.task_id,
                    ),
                )
                self._append_event(
                    connection,
                    graph_artifact,
                    timestamp,
                    actor="scheduler",
                    cause="verification-blocked",
                    task_id=task.task_id,
                    context_snapshot_id=task.context_snapshot_id,
                    before_state=TaskState.VERIFICATION.value,
                    after_state=TaskState.BLOCKED.value,
                    result_id=artifact.artifact_id,
                    reason=verification_reason,
                )
            else:
                connection.execute(
                    "UPDATE tasks SET state = ?, outcome = ?, blockers_json = '[]' "
                    "WHERE task_id = ?",
                    (
                        TaskState.COMPLETED.value,
                        TaskOutcome.SUCCEEDED.value,
                        task.task_id,
                    ),
                )
                self._append_event(
                    connection,
                    graph_artifact,
                    timestamp,
                    actor="scheduler",
                    cause="verification-completed",
                    task_id=task.task_id,
                    context_snapshot_id=task.context_snapshot_id,
                    before_state=TaskState.VERIFICATION.value,
                    after_state=TaskState.COMPLETED.value,
                    result_id=artifact.artifact_id,
                )
            self._append_budget_snapshot(connection, graph_artifact, graph, sequence)
            return
        retry_reserved = (
            outcome_text == "failed"
            and effect == "none"
            and task.effect_kind is EffectKind.READ_ONLY
            and current["attempt"] < task.max_attempts
            and self._reserve_retry(connection, graph)
        )
        if retry_reserved:
            next_state = TaskState.READY
            outcome = TaskOutcome.FAILED
            reason = "safe-read-only-retry"
        elif outcome_text == "failed" and effect == "none":
            next_state = TaskState.REJECTED
            outcome = TaskOutcome.FAILED
            reason = "unambiguous-failure"
        else:
            next_state = TaskState.BLOCKED
            outcome = TaskOutcome.UNKNOWN
            reason = "ambiguous-external-effect"
        self._release_current_lease(connection, current, task, outcome)
        connection.execute(
            "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ?, "
            "blockers_json = ? WHERE task_id = ?",
            (
                next_state.value,
                DispatchPhase.NOT_DISPATCHED.value,
                outcome.value,
                _blockers_json(reason),
                task.task_id,
            ),
        )
        self._change_budget(connection, "concurrency", reserved_delta=-1)
        sequence = self._append_event(
            connection,
            graph_artifact,
            timestamp,
            actor=current["owner_id"],
            cause="result-terminal",
            task_id=task.task_id,
            context_snapshot_id=task.context_snapshot_id,
            before_state=TaskState.RUNNING.value,
            after_state=next_state.value,
            lease_id=current["lease_id"],
            message_id=artifact.artifact_id,
            result_id=artifact.artifact_id,
            reason=reason,
            budget_deltas={
                "concurrency": -1,
                **resource_deltas,
                **({"retries": 1} if retry_reserved else {}),
            },
        )
        self._append_budget_snapshot(connection, graph_artifact, graph, sequence)

    def _apply_cancel_ack(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        task: Any,
        current: sqlite3.Row,
        artifact: LoadedSchedulerArtifact,
        message: MailboxMessage,
        timestamp: str,
    ) -> None:
        cancelled = bool(message.payload["cancelled"])
        observed = str(message.payload["effect_observed"])
        if cancelled and observed == "none":
            state = TaskState.SUPERSEDED
            outcome = TaskOutcome.CANCELLED
            reason = "cancellation-acknowledged"
            phase = DispatchPhase.CANCELLATION_ACKNOWLEDGED
        else:
            state = TaskState.BLOCKED
            outcome = TaskOutcome.UNKNOWN
            reason = "cancellation-ambiguous"
            phase = DispatchPhase.CANCELLATION_REQUESTED
        resource_deltas = self._close_attempt_budget(
            connection, task.task_id, current["lease_id"], conservative=True
        )
        self._release_current_lease(connection, current, task, outcome)
        connection.execute(
            "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ?, "
            "blockers_json = ? WHERE task_id = ?",
            (state.value, phase.value, outcome.value, _blockers_json(reason), task.task_id),
        )
        self._change_budget(connection, "concurrency", reserved_delta=-1)
        sequence = self._append_event(
            connection,
            graph_artifact,
            timestamp,
            actor=current["owner_id"],
            cause="cancel-acknowledgement",
            task_id=task.task_id,
            context_snapshot_id=task.context_snapshot_id,
            before_state=TaskState.RUNNING.value,
            after_state=state.value,
            lease_id=current["lease_id"],
            message_id=artifact.artifact_id,
            reason=reason,
            budget_deltas={"concurrency": -1, **resource_deltas},
        )
        self._append_budget_snapshot(connection, graph_artifact, graph, sequence)

    def _apply_worktree_observation(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        task: Any,
        current: sqlite3.Row,
        artifact: LoadedSchedulerArtifact,
        message: MailboxMessage,
        authority: tuple[WorktreeLease, bool, str | None],
        timestamp: str,
        outgoing: list[LoadedSchedulerArtifact],
    ) -> None:
        assert graph.worktree_plan is not None
        assert task.worktree_assignment is not None
        worktree, terminal_observation, observation_reason = authority
        worktree_artifact = artifact_from_value(SchedulerArtifactType.WORKTREE_LEASE, worktree)
        if terminal_observation:
            self._release_current_lease(
                connection,
                current,
                task,
                TaskOutcome.UNKNOWN,
                release_worktree=False,
            )
            connection.execute(
                "DELETE FROM current_worktree_leases WHERE task_id = ?", (task.task_id,)
            )
            connection.execute(
                "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ?, "
                "blockers_json = ? WHERE task_id = ?",
                (
                    TaskState.BLOCKED.value,
                    DispatchPhase.NOT_DISPATCHED.value,
                    TaskOutcome.UNKNOWN.value,
                    _blockers_json(str(observation_reason)),
                    task.task_id,
                ),
            )
            self._change_budget(connection, "concurrency", reserved_delta=-1)
        event_sequence = self._append_event(
            connection,
            graph_artifact,
            timestamp,
            actor=current["owner_id"],
            cause="worktree-observed",
            task_id=task.task_id,
            context_snapshot_id=task.context_snapshot_id,
            before_state=TaskState.RUNNING.value,
            after_state=(
                TaskState.BLOCKED.value if terminal_observation else TaskState.RUNNING.value
            ),
            lease_id=current["lease_id"],
            message_id=artifact.artifact_id,
            reason=observation_reason,
            budget_deltas={"concurrency": -1} if terminal_observation else None,
        )
        connection.execute(
            "INSERT INTO worktree_lease_history(event_sequence, artifact_id, "
            "task_id, status, artifact_json) VALUES (?, ?, ?, ?, ?)",
            (
                event_sequence,
                worktree_artifact.artifact_id,
                task.task_id,
                worktree.status.value,
                _artifact_json(worktree_artifact),
            ),
        )
        if not terminal_observation:
            connection.execute(
                "INSERT INTO current_worktree_leases(task_id, artifact_id, owner_id, "
                "fence, worktree, artifact_json) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET artifact_id=excluded.artifact_id, "
                "owner_id=excluded.owner_id, fence=excluded.fence, "
                "worktree=excluded.worktree, artifact_json=excluded.artifact_json",
                (
                    task.task_id,
                    worktree_artifact.artifact_id,
                    current["owner_id"],
                    current["fence"],
                    worktree.worktree,
                    _artifact_json(worktree_artifact),
                ),
            )
        if terminal_observation:
            self._append_budget_snapshot(connection, graph_artifact, graph, event_sequence)
            return
        dispatch = self._activate_dispatch_after_worktree(
            connection,
            graph_artifact,
            graph,
            task,
            current,
            artifact.artifact_id,
            timestamp,
        )
        if dispatch is not None:
            outgoing.append(dispatch)

    def _activate_dispatch_after_worktree(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        task: Any,
        current: sqlite3.Row,
        causal_parent: str,
        timestamp: str,
    ) -> LoadedSchedulerArtifact | None:
        effect_digest = _sha256_json(task.to_dict())
        ttl_seconds, heartbeat_interval_seconds = self._lease_policy(connection)
        binding = next(
            item for item in graph.contexts if item.artifact_id == task.context_snapshot_id
        )
        context_bytes = verified_reference_size(self._root, binding.reference)
        reservation = self._dispatch_reservation(connection, graph, task, context_bytes)
        if not self._budget_allows_dispatch(
            connection,
            graph,
            context_bytes,
            reservation,
            acquire_concurrency=False,
        ):
            task_row = connection.execute(
                "SELECT blockers_json FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            connection.execute(
                "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ?, "
                "blockers_json = ? WHERE task_id = ?",
                (
                    TaskState.RUNNING.value,
                    DispatchPhase.NOT_DISPATCHED.value,
                    TaskOutcome.NONE.value,
                    _blockers_json("budget-exhausted"),
                    task.task_id,
                ),
            )
            if task_row["blockers_json"] != _blockers_json("budget-exhausted"):
                self._append_event(
                    connection,
                    graph_artifact,
                    timestamp,
                    actor="scheduler",
                    cause="dispatch-budget-blocked",
                    task_id=task.task_id,
                    context_snapshot_id=task.context_snapshot_id,
                    before_state=TaskState.RUNNING.value,
                    after_state=TaskState.RUNNING.value,
                    lease_id=current["lease_id"],
                    reason="budget-exhausted",
                )
            return None
        if not self._consume_approvals(
            connection,
            graph_artifact,
            task,
            current["lease_id"],
            int(current["attempt"]),
            int(current["fence"]),
            str(current["idempotency_key"]),
            effect_digest,
            timestamp,
        ):
            connection.execute(
                "UPDATE tasks SET blockers_json = ? WHERE task_id = ?",
                (_blockers_json("approval-required"), task.task_id),
            )
            self._append_event(
                connection,
                graph_artifact,
                timestamp,
                actor="scheduler",
                cause="dispatch-approval-blocked",
                task_id=task.task_id,
                context_snapshot_id=task.context_snapshot_id,
                before_state=TaskState.RUNNING.value,
                after_state=TaskState.RUNNING.value,
                lease_id=current["lease_id"],
                reason="approval-required",
            )
            return None
        current_lease = _parse_artifact_json(
            current["artifact_json"], SchedulerArtifactType.LEASE
        ).value
        assert isinstance(current_lease, Lease)
        dispatch = MailboxMessage(
            message_type=MessageType.DISPATCH_INTENT,
            direction=MessageDirection.SCHEDULER_TO_HOST,
            sender="HST-SCHEDULER",
            recipient=current["owner_id"],
            graph_id=graph_artifact.artifact_id,
            task_id=task.task_id,
            candidate=graph.candidate,
            context_snapshot_id=task.context_snapshot_id,
            attempt=current["attempt"],
            lease_id=current["lease_id"],
            fence=current["fence"],
            idempotency_key=current["idempotency_key"],
            sensitivity=binding.sensitivity,
            provenance=(binding.reference,),
            causal_parent_message_ids=(causal_parent,),
            recorded_at=timestamp,
            payload={
                "effect_digest": effect_digest,
                "lease_ttl_seconds": ttl_seconds,
                "heartbeat_interval_seconds": heartbeat_interval_seconds,
                "required_capabilities": list(task.required_capabilities),
                "required_tools": list(task.required_tools),
                "context_bytes": context_bytes,
                "budget_reservation": reservation,
            },
        )
        dispatch_artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, dispatch)
        self._insert_message(connection, dispatch_artifact, dispatch)
        connection.execute(
            "UPDATE tasks SET dispatch_phase = ?, blockers_json = '[]' WHERE task_id = ?",
            (DispatchPhase.INTENT_PENDING.value, task.task_id),
        )
        self._change_budget(connection, "dispatches", used_delta=1)
        for resource, amount in reservation.items():
            self._change_budget(connection, resource, reserved_delta=amount)
        sequence = self._append_event(
            connection,
            graph_artifact,
            timestamp,
            actor="scheduler",
            cause="dispatch-intent",
            task_id=task.task_id,
            context_snapshot_id=task.context_snapshot_id,
            before_state=TaskState.RUNNING.value,
            after_state=TaskState.RUNNING.value,
            lease_id=current["lease_id"],
            message_id=dispatch_artifact.artifact_id,
            budget_deltas={
                "context_bytes": context_bytes,
                "dispatches": 1,
                "microunits": reservation["microunits"],
                "solver_calls": reservation["solver_calls"],
                "solver_steps": reservation["solver_steps"],
                "tool_calls": reservation["tool_calls"],
            },
        )
        self._append_budget_snapshot(connection, graph_artifact, graph, sequence)
        return dispatch_artifact

    def _retry_budget_blocked_worktrees(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        timestamp: str,
    ) -> tuple[LoadedSchedulerArtifact, ...]:
        tasks = {task.task_id: task for task in graph.tasks}
        rows = connection.execute(
            "SELECT leases.* FROM current_leases AS leases "
            "JOIN tasks ON tasks.task_id = leases.task_id "
            "JOIN current_worktree_leases AS worktrees ON worktrees.task_id = leases.task_id "
            "WHERE tasks.state = ? AND tasks.dispatch_phase = ? AND tasks.blockers_json = ? "
            "ORDER BY tasks.wave, tasks.topological_rank, tasks.task_id",
            (
                TaskState.RUNNING.value,
                DispatchPhase.NOT_DISPATCHED.value,
                _blockers_json("budget-exhausted"),
            ),
        ).fetchall()
        outgoing: list[LoadedSchedulerArtifact] = []
        for current in rows:
            task = tasks[str(current["task_id"])]
            parent = self._latest_worktree_observation_message_id(
                connection,
                task.task_id,
                str(current["lease_id"]),
            )
            if parent is None:
                raise SchedulerAdapterError(
                    "Budget-blocked Worktree dispatch lost its observation authority."
                )
            dispatch = self._activate_dispatch_after_worktree(
                connection,
                graph_artifact,
                graph,
                task,
                current,
                parent,
                timestamp,
            )
            if dispatch is not None:
                outgoing.append(dispatch)
        return tuple(outgoing)

    def _release_current_lease(
        self,
        connection: sqlite3.Connection,
        current: sqlite3.Row,
        task: Any,
        outcome: TaskOutcome,
        *,
        release_worktree: bool = True,
    ) -> None:
        acquisition = _parse_artifact_json(current["artifact_json"], SchedulerArtifactType.LEASE)
        lease = acquisition.value
        assert isinstance(lease, Lease)
        released = Lease(
            graph_id=lease.graph_id,
            task_id=lease.task_id,
            candidate=lease.candidate,
            context_snapshot_id=lease.context_snapshot_id,
            attempt=lease.attempt,
            owner_id=lease.owner_id,
            fence=lease.fence,
            idempotency_key=lease.idempotency_key,
            acquired_at=lease.acquired_at,
            heartbeat_at=current["heartbeat_at"],
            expires_at=current["expires_at"],
            ttl_seconds=lease.ttl_seconds,
            heartbeat_interval_seconds=lease.heartbeat_interval_seconds,
            status=LeaseStatus.RELEASED,
            release_outcome=outcome,
        )
        released_artifact = artifact_from_value(SchedulerArtifactType.LEASE, released)
        next_event = int(connection.execute("SELECT MAX(sequence) + 1 FROM events").fetchone()[0])
        if release_worktree:
            self._release_current_worktree(connection, task.task_id, next_event)
        connection.execute("DELETE FROM current_leases WHERE task_id = ?", (task.task_id,))
        connection.execute(
            "INSERT INTO lease_history(event_sequence, artifact_id, authority_lease_id, "
            "task_id, fence, status, artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                next_event,
                released_artifact.artifact_id,
                current["lease_id"],
                task.task_id,
                lease.fence,
                LeaseStatus.RELEASED.value,
                _artifact_json(released_artifact),
            ),
        )

    def _release_current_worktree(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        event_sequence: int,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM current_worktree_leases WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return
        artifact = _parse_artifact_json(row["artifact_json"], SchedulerArtifactType.WORKTREE_LEASE)
        lease = artifact.value
        assert isinstance(lease, WorktreeLease)
        released = WorktreeLease(
            graph_id=lease.graph_id,
            task_id=lease.task_id,
            worktree_plan=lease.worktree_plan,
            base_commit=lease.base_commit,
            worktree=lease.worktree,
            owner_id=lease.owner_id,
            owned_paths=lease.owned_paths,
            fence=lease.fence,
            observed_digest=lease.observed_digest,
            status=WorktreeLeaseStatus.RELEASED,
            integration_state=lease.integration_state,
            ambiguous=False,
            recovery_guidance="Worktree authority is released; reacquire before reuse.",
        )
        released_artifact = artifact_from_value(SchedulerArtifactType.WORKTREE_LEASE, released)
        connection.execute("DELETE FROM current_worktree_leases WHERE task_id = ?", (task_id,))
        connection.execute(
            "INSERT INTO worktree_lease_history(event_sequence, artifact_id, task_id, "
            "status, artifact_json) VALUES (?, ?, ?, ?, ?)",
            (
                event_sequence,
                released_artifact.artifact_id,
                task_id,
                released.status.value,
                _artifact_json(released_artifact),
            ),
        )

    def _expire_leases(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        timestamp: str,
    ) -> None:
        rows = connection.execute("SELECT * FROM current_leases ORDER BY task_id").fetchall()
        tasks = {item.task_id: item for item in graph.tasks}
        for row in rows:
            if parse_utc(row["expires_at"]) > parse_utc(timestamp):
                continue
            task = tasks[row["task_id"]]
            task_row = connection.execute(
                "SELECT state, blockers_json FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            if not self._lease_was_activated(connection, task.task_id, row["lease_id"]):
                self._release_current_lease(connection, row, task, TaskOutcome.NONE)
                connection.execute(
                    "UPDATE tasks SET state = ?, dispatch_phase = ?, attempt = ?, fence = ?, "
                    "blockers_json = '[]' WHERE task_id = ?",
                    (
                        TaskState.READY.value,
                        DispatchPhase.NOT_DISPATCHED.value,
                        max(0, int(row["attempt"]) - 1),
                        max(0, int(row["fence"]) - 1),
                        task.task_id,
                    ),
                )
                self._append_event(
                    connection,
                    graph_artifact,
                    timestamp,
                    actor="scheduler",
                    cause="approval-proposal-expired",
                    task_id=task.task_id,
                    context_snapshot_id=task.context_snapshot_id,
                    before_state=str(task_row["state"]),
                    after_state=TaskState.READY.value,
                    lease_id=row["lease_id"],
                    reason="approval-proposal-expired",
                )
                continue
            retry_reserved = (
                task.effect_kind is EffectKind.READ_ONLY
                and row["attempt"] < task.max_attempts
                and self._reserve_retry(connection, graph)
            )
            if retry_reserved:
                state = TaskState.READY
                outcome = TaskOutcome.FAILED
                reason = "lease-expired-safe-retry"
            else:
                state = TaskState.BLOCKED
                outcome = TaskOutcome.UNKNOWN
                reason = "lease-expired-ambiguous"
            resource_deltas = self._close_attempt_budget(
                connection, task.task_id, row["lease_id"], conservative=True
            )
            self._release_current_lease(connection, row, task, outcome)
            connection.execute(
                "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ?, "
                "blockers_json = ? WHERE task_id = ?",
                (
                    state.value,
                    DispatchPhase.NOT_DISPATCHED.value,
                    outcome.value,
                    _blockers_json(reason),
                    task.task_id,
                ),
            )
            self._change_budget(connection, "concurrency", reserved_delta=-1)
            sequence = self._append_event(
                connection,
                graph_artifact,
                timestamp,
                actor="scheduler",
                cause="lease-expired",
                task_id=task.task_id,
                context_snapshot_id=task.context_snapshot_id,
                before_state=TaskState.RUNNING.value,
                after_state=state.value,
                lease_id=row["lease_id"],
                reason=reason,
                budget_deltas={
                    "concurrency": -1,
                    **resource_deltas,
                    **({"retries": 1} if retry_reserved else {}),
                },
            )
            self._append_budget_snapshot(connection, graph_artifact, graph, sequence)

    def _refresh_ready(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        host_id: str,
        timestamp: str,
    ) -> None:
        task_rows = connection.execute(
            "SELECT task_id, state, outcome, blockers_json FROM tasks"
        ).fetchall()
        states = {row["task_id"]: TaskState(row["state"]) for row in task_rows}
        outcomes = {row["task_id"]: TaskOutcome(row["outcome"]) for row in task_rows}
        blocker_values = {row["task_id"]: row["blockers_json"] for row in task_rows}
        capabilities_by_host = self._capabilities_by_host(connection)
        current_owners = {
            str(row["task_id"]): str(row["owner_id"])
            for row in connection.execute("SELECT task_id, owner_id FROM current_leases").fetchall()
        }
        for task in graph.tasks:
            current = states[task.task_id]
            if current not in {TaskState.PLANNED, TaskState.READY, TaskState.BLOCKED}:
                continue
            if current is TaskState.BLOCKED and outcomes[task.task_id] is TaskOutcome.UNKNOWN:
                continue
            dependency_states = [states[identifier] for identifier in task.dependencies]
            blockers: list[Blocker] = []
            if any(
                state in {TaskState.BLOCKED, TaskState.REJECTED, TaskState.SUPERSEDED}
                for state in dependency_states
            ):
                blockers.append(Blocker("dependency-terminal-blocker", tuple(task.dependencies)))
            elif not all(state is TaskState.COMPLETED for state in dependency_states):
                if current is not TaskState.PLANNED or blocker_values[task.task_id] != "[]":
                    connection.execute(
                        "UPDATE tasks SET state = ?, blockers_json = '[]' WHERE task_id = ?",
                        (TaskState.PLANNED.value, task.task_id),
                    )
                    self._append_event(
                        connection,
                        graph_artifact,
                        timestamp,
                        actor="scheduler",
                        cause="readiness-refreshed",
                        task_id=task.task_id,
                        context_snapshot_id=task.context_snapshot_id,
                        before_state=current.value,
                        after_state=TaskState.PLANNED.value,
                    )
                states[task.task_id] = TaskState.PLANNED
                continue
            authority_host = current_owners.get(task.task_id, host_id)
            capabilities = set(capabilities_by_host.get(authority_host, ()))
            missing = tuple(sorted(set(task.required_capabilities) - capabilities))
            if missing:
                blockers.append(Blocker("missing-capability", missing))
            if task.kind.value == "solver" and _m7_solver_reservation(task, graph) is None:
                blockers.append(Blocker("solver-contract-unavailable", (task.task_id,)))
            target = TaskState.BLOCKED if blockers else TaskState.READY
            blockers_json = canonical_json_bytes(
                [
                    item.to_dict()
                    for item in sorted(blockers, key=lambda item: (item.code, item.references))
                ]
            ).decode("ascii")
            if current is not target or blocker_values[task.task_id] != blockers_json:
                connection.execute(
                    "UPDATE tasks SET state = ?, blockers_json = ? WHERE task_id = ?",
                    (target.value, blockers_json, task.task_id),
                )
                self._append_event(
                    connection,
                    graph_artifact,
                    timestamp,
                    actor="scheduler",
                    cause="readiness-refreshed",
                    task_id=task.task_id,
                    context_snapshot_id=task.context_snapshot_id,
                    before_state=current.value,
                    after_state=target.value,
                )
            states[task.task_id] = target

    @staticmethod
    def _capabilities_by_host(connection: sqlite3.Connection) -> dict[str, list[str]]:
        value = json.loads(
            connection.execute(
                "SELECT value FROM metadata WHERE key = 'host_capabilities'"
            ).fetchone()[0]
        )
        if not isinstance(value, dict):
            raise SchedulerAdapterError("Scheduler host capabilities are invalid.")
        result: dict[str, list[str]] = {}
        for owner, capabilities in value.items():
            strict_host_id(owner, "capability owner")
            if not isinstance(capabilities, list) or any(
                not isinstance(item, str) for item in capabilities
            ):
                raise SchedulerAdapterError("Scheduler host capabilities are invalid.")
            result[owner] = list(capabilities)
        return result

    def _dispatch_ready(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        host_id: str,
        timestamp: str,
        ttl: int,
        heartbeat: int,
    ) -> tuple[LoadedSchedulerArtifact, ...]:
        concurrency_limit = min(graph.budget.max_agents, graph.budget.max_concurrency)
        current_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM current_leases AS leases "
                "JOIN tasks ON tasks.task_id = leases.task_id WHERE tasks.state = ?",
                (TaskState.RUNNING.value,),
            ).fetchone()[0]
        )
        capacity = concurrency_limit - current_count
        if capacity <= 0:
            return ()
        rows = connection.execute(
            "SELECT * FROM tasks WHERE state = ? ORDER BY wave, topological_rank, task_id",
            (TaskState.READY.value,),
        ).fetchall()
        tasks = {item.task_id: item for item in graph.tasks}
        outgoing: list[LoadedSchedulerArtifact] = []
        for row in rows:
            if capacity <= 0:
                break
            task = tasks[row["task_id"]]
            context_binding = next(
                item for item in graph.contexts if item.artifact_id == task.context_snapshot_id
            )
            context_bytes = verified_reference_size(self._root, context_binding.reference)
            reservation = self._dispatch_reservation(connection, graph, task, context_bytes)
            if not self._budget_allows_dispatch(connection, graph, context_bytes, reservation):
                connection.execute(
                    "UPDATE tasks SET state = ?, blockers_json = ? WHERE task_id = ?",
                    (
                        TaskState.BLOCKED.value,
                        _blockers_json("budget-exhausted"),
                        task.task_id,
                    ),
                )
                self._append_event(
                    connection,
                    graph_artifact,
                    timestamp,
                    actor="scheduler",
                    cause="dispatch-budget-blocked",
                    task_id=task.task_id,
                    context_snapshot_id=task.context_snapshot_id,
                    before_state=TaskState.READY.value,
                    after_state=TaskState.BLOCKED.value,
                    reason="budget-exhausted",
                )
                continue
            effect_digest = _sha256_json(task.to_dict())
            current = connection.execute(
                "SELECT * FROM current_leases WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            if current is None:
                attempt = row["attempt"] + 1
                fence = row["fence"] + 1
                idem = derive_idempotency_key(
                    graph_artifact.artifact_id,
                    task.task_id,
                    attempt,
                    fence,
                    graph.candidate.to_dict(),
                    task.context_snapshot_id,
                    effect_digest,
                )
                acquired = parse_utc(timestamp)
                lease = Lease(
                    graph_id=graph_artifact.artifact_id,
                    task_id=task.task_id,
                    candidate=graph.candidate,
                    context_snapshot_id=task.context_snapshot_id,
                    attempt=attempt,
                    owner_id=host_id,
                    fence=fence,
                    idempotency_key=idem,
                    acquired_at=timestamp,
                    heartbeat_at=timestamp,
                    expires_at=format_utc(acquired + timedelta(seconds=ttl)),
                    ttl_seconds=ttl,
                    heartbeat_interval_seconds=heartbeat,
                    status=LeaseStatus.CURRENT,
                    release_outcome=TaskOutcome.NONE,
                )
                lease_artifact = artifact_from_value(SchedulerArtifactType.LEASE, lease)
            else:
                lease_artifact = _parse_artifact_json(
                    current["artifact_json"], SchedulerArtifactType.LEASE
                )
                loaded_lease = lease_artifact.value
                assert isinstance(loaded_lease, Lease)
                lease = loaded_lease
                attempt = int(current["attempt"])
                fence = int(current["fence"])
                idem = str(current["idempotency_key"])
            if not self._consume_approvals(
                connection,
                graph_artifact,
                task,
                lease_artifact.artifact_id,
                attempt,
                fence,
                idem,
                effect_digest,
                timestamp,
                consume=task.worktree_assignment is None,
            ):
                connection.execute(
                    "UPDATE tasks SET state = ?, attempt = ?, fence = ?, blockers_json = ? "
                    "WHERE task_id = ?",
                    (
                        TaskState.BLOCKED.value,
                        attempt,
                        fence,
                        _blockers_json("approval-required"),
                        task.task_id,
                    ),
                )
                sequence = self._append_event(
                    connection,
                    graph_artifact,
                    timestamp,
                    actor=lease.owner_id,
                    cause="dispatch-approval-blocked",
                    task_id=task.task_id,
                    context_snapshot_id=task.context_snapshot_id,
                    before_state=TaskState.READY.value,
                    after_state=TaskState.BLOCKED.value,
                    lease_id=lease_artifact.artifact_id,
                    reason="approval-required",
                )
                if current is None:
                    connection.execute(
                        "INSERT INTO lease_history(event_sequence, artifact_id, "
                        "authority_lease_id, task_id, fence, status, artifact_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            sequence,
                            lease_artifact.artifact_id,
                            lease_artifact.artifact_id,
                            task.task_id,
                            fence,
                            LeaseStatus.CURRENT.value,
                            _artifact_json(lease_artifact),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO current_leases(task_id, lease_id, "
                        "projection_artifact_id, owner_id, attempt, fence, "
                        "idempotency_key, acquired_at, heartbeat_at, expires_at, "
                        "artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            task.task_id,
                            lease_artifact.artifact_id,
                            lease_artifact.artifact_id,
                            lease.owner_id,
                            attempt,
                            fence,
                            idem,
                            lease.acquired_at,
                            lease.heartbeat_at,
                            lease.expires_at,
                            _artifact_json(lease_artifact),
                        ),
                    )
                continue
            if task.worktree_assignment is not None:
                occupied = connection.execute(
                    "SELECT task_id FROM current_worktree_leases WHERE worktree = ? "
                    "AND task_id != ?",
                    (task.worktree_assignment, task.task_id),
                ).fetchone()
                if occupied is not None:
                    connection.execute(
                        "UPDATE tasks SET state = ?, blockers_json = ? WHERE task_id = ?",
                        (
                            TaskState.BLOCKED.value,
                            _blockers_json("worktree-unavailable", (str(occupied["task_id"]),)),
                            task.task_id,
                        ),
                    )
                    self._append_event(
                        connection,
                        graph_artifact,
                        timestamp,
                        actor="scheduler",
                        cause="readiness-refreshed",
                        task_id=task.task_id,
                        context_snapshot_id=task.context_snapshot_id,
                        before_state=TaskState.READY.value,
                        after_state=TaskState.BLOCKED.value,
                        lease_id=lease_artifact.artifact_id if current is not None else None,
                        reason="worktree-unavailable",
                    )
                    continue
                request = MailboxMessage(
                    message_type=MessageType.WORKTREE_REQUEST,
                    direction=MessageDirection.SCHEDULER_TO_HOST,
                    sender="HST-SCHEDULER",
                    recipient=lease.owner_id,
                    graph_id=graph_artifact.artifact_id,
                    task_id=task.task_id,
                    candidate=graph.candidate,
                    context_snapshot_id=task.context_snapshot_id,
                    attempt=attempt,
                    lease_id=lease_artifact.artifact_id,
                    fence=fence,
                    idempotency_key=idem,
                    sensitivity=context_binding.sensitivity,
                    provenance=(context_binding.reference,),
                    causal_parent_message_ids=(),
                    recorded_at=timestamp,
                    payload={
                        "worktree": task.worktree_assignment,
                        "owned_paths": list(task.owned_paths),
                    },
                )
                request_artifact = artifact_from_value(
                    SchedulerArtifactType.MAILBOX_MESSAGE, request
                )
                self._insert_message(connection, request_artifact, request)
                connection.execute(
                    "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ?, "
                    "attempt = ?, fence = ?, blockers_json = '[]' WHERE task_id = ?",
                    (
                        TaskState.RUNNING.value,
                        DispatchPhase.NOT_DISPATCHED.value,
                        TaskOutcome.NONE.value,
                        attempt,
                        fence,
                        task.task_id,
                    ),
                )
                self._change_budget(connection, "concurrency", reserved_delta=1)
                sequence = self._append_event(
                    connection,
                    graph_artifact,
                    timestamp,
                    actor="scheduler",
                    cause="worktree-request",
                    task_id=task.task_id,
                    context_snapshot_id=task.context_snapshot_id,
                    before_state=TaskState.READY.value,
                    after_state=TaskState.RUNNING.value,
                    lease_id=lease_artifact.artifact_id,
                    message_id=request_artifact.artifact_id,
                    budget_deltas={"concurrency": 1},
                )
                assert graph.worktree_plan is not None
                requested_worktree = WorktreeLease(
                    graph_id=graph_artifact.artifact_id,
                    task_id=task.task_id,
                    worktree_plan=graph.worktree_plan,
                    base_commit=graph.candidate.git_head,
                    worktree=task.worktree_assignment,
                    owner_id=lease.owner_id,
                    owned_paths=task.owned_paths,
                    fence=fence,
                    observed_digest=None,
                    status=WorktreeLeaseStatus.REQUESTED,
                    integration_state="requested",
                    ambiguous=False,
                    recovery_guidance="Await the exact host worktree observation.",
                )
                requested_artifact = artifact_from_value(
                    SchedulerArtifactType.WORKTREE_LEASE, requested_worktree
                )
                connection.execute(
                    "INSERT INTO worktree_lease_history(event_sequence, artifact_id, task_id, "
                    "status, artifact_json) VALUES (?, ?, ?, ?, ?)",
                    (
                        sequence,
                        requested_artifact.artifact_id,
                        task.task_id,
                        requested_worktree.status.value,
                        _artifact_json(requested_artifact),
                    ),
                )
                connection.execute(
                    "INSERT INTO current_worktree_leases(task_id, artifact_id, owner_id, "
                    "fence, worktree, artifact_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        task.task_id,
                        requested_artifact.artifact_id,
                        lease.owner_id,
                        fence,
                        task.worktree_assignment,
                        _artifact_json(requested_artifact),
                    ),
                )
                if current is None:
                    connection.execute(
                        "INSERT INTO lease_history(event_sequence, artifact_id, "
                        "authority_lease_id, task_id, fence, status, artifact_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            sequence,
                            lease_artifact.artifact_id,
                            lease_artifact.artifact_id,
                            task.task_id,
                            fence,
                            LeaseStatus.CURRENT.value,
                            _artifact_json(lease_artifact),
                        ),
                    )
                    connection.execute(
                        "INSERT INTO current_leases(task_id, lease_id, projection_artifact_id, "
                        "owner_id, attempt, fence, idempotency_key, acquired_at, heartbeat_at, "
                        "expires_at, artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            task.task_id,
                            lease_artifact.artifact_id,
                            lease_artifact.artifact_id,
                            lease.owner_id,
                            attempt,
                            fence,
                            idem,
                            lease.acquired_at,
                            lease.heartbeat_at,
                            lease.expires_at,
                            _artifact_json(lease_artifact),
                        ),
                    )
                self._append_budget_snapshot(connection, graph_artifact, graph, sequence)
                outgoing.append(request_artifact)
                capacity -= 1
                continue
            message = MailboxMessage(
                message_type=MessageType.DISPATCH_INTENT,
                direction=MessageDirection.SCHEDULER_TO_HOST,
                sender="HST-SCHEDULER",
                recipient=lease.owner_id,
                graph_id=graph_artifact.artifact_id,
                task_id=task.task_id,
                candidate=graph.candidate,
                context_snapshot_id=task.context_snapshot_id,
                attempt=attempt,
                lease_id=lease_artifact.artifact_id,
                fence=fence,
                idempotency_key=idem,
                sensitivity=context_binding.sensitivity,
                provenance=(context_binding.reference,),
                causal_parent_message_ids=(),
                recorded_at=timestamp,
                payload={
                    "effect_digest": effect_digest,
                    "lease_ttl_seconds": ttl,
                    "heartbeat_interval_seconds": heartbeat,
                    "required_capabilities": list(task.required_capabilities),
                    "required_tools": list(task.required_tools),
                    "context_bytes": context_bytes,
                    "budget_reservation": reservation,
                },
            )
            message_artifact = artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, message)
            self._insert_message(connection, message_artifact, message)
            connection.execute(
                "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ?, "
                "attempt = ?, fence = ?, blockers_json = '[]' WHERE task_id = ?",
                (
                    TaskState.RUNNING.value,
                    DispatchPhase.INTENT_PENDING.value,
                    TaskOutcome.NONE.value,
                    attempt,
                    fence,
                    task.task_id,
                ),
            )
            self._change_budget(connection, "concurrency", reserved_delta=1)
            self._change_budget(connection, "dispatches", used_delta=1)
            for resource, amount in reservation.items():
                self._change_budget(connection, resource, reserved_delta=amount)
            sequence = self._append_event(
                connection,
                graph_artifact,
                timestamp,
                actor="scheduler",
                cause="dispatch-intent",
                task_id=task.task_id,
                context_snapshot_id=task.context_snapshot_id,
                before_state=TaskState.READY.value,
                after_state=TaskState.RUNNING.value,
                lease_id=lease_artifact.artifact_id,
                message_id=message_artifact.artifact_id,
                budget_deltas={
                    "concurrency": 1,
                    "context_bytes": context_bytes,
                    "dispatches": 1,
                    "tool_calls": reservation["tool_calls"],
                    "solver_calls": reservation["solver_calls"],
                    "solver_steps": reservation["solver_steps"],
                    "microunits": reservation["microunits"],
                },
            )
            if current is None:
                connection.execute(
                    "INSERT INTO lease_history(event_sequence, artifact_id, authority_lease_id, "
                    "task_id, fence, status, artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        sequence,
                        lease_artifact.artifact_id,
                        lease_artifact.artifact_id,
                        task.task_id,
                        fence,
                        LeaseStatus.CURRENT.value,
                        _artifact_json(lease_artifact),
                    ),
                )
                connection.execute(
                    "INSERT INTO current_leases(task_id, lease_id, projection_artifact_id, "
                    "owner_id, attempt, fence, idempotency_key, acquired_at, heartbeat_at, "
                    "expires_at, artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task.task_id,
                        lease_artifact.artifact_id,
                        lease_artifact.artifact_id,
                        lease.owner_id,
                        attempt,
                        fence,
                        idem,
                        lease.acquired_at,
                        lease.heartbeat_at,
                        lease.expires_at,
                        _artifact_json(lease_artifact),
                    ),
                )
            self._append_budget_snapshot(connection, graph_artifact, graph, sequence)
            outgoing.append(message_artifact)
            capacity -= 1
        return tuple(outgoing)

    def _consume_approvals(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        task: Any,
        lease_id: str,
        attempt: int,
        fence: int,
        idem: str,
        effect_digest: str,
        timestamp: str,
        *,
        consume: bool = True,
    ) -> bool:
        selections: list[tuple[str, MailboxMessage]] = []
        for approval_type in task.approval_stops:
            selected: tuple[str, MailboxMessage] | None = None
            for _, message_id, message, _ in _adopted_message_entries(
                connection,
                cause="approval-received",
                message_type=MessageType.APPROVAL_DECISION,
            ):
                if message.task_id != task.task_id:
                    continue
                payload = message.payload
                consumed = connection.execute(
                    "SELECT 1 FROM approval_consumptions WHERE approval_id = ?",
                    (payload["approval_id"],),
                ).fetchone()
                if (
                    consumed is None
                    and payload["approval_type"] == approval_type
                    and payload["decision"] == "approved"
                    and payload["transition"] == "dispatch"
                    and payload["effect_digest"] == effect_digest
                    and message.attempt == attempt
                    and message.lease_id == lease_id
                    and message.fence == fence
                    and message.idempotency_key == idem
                    and parse_utc(str(payload["approved_at"]))
                    <= parse_utc(timestamp)
                    < parse_utc(str(payload["expires_at"]))
                ):
                    selected = (message_id, message)
                    break
            if selected is None:
                return False
            selections.append(selected)
        if not consume:
            return True
        state = str(
            connection.execute(
                "SELECT state FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()[0]
        )
        for message_id, message in selections:
            next_sequence = int(
                connection.execute("SELECT MAX(sequence) + 1 FROM events").fetchone()[0]
            )
            connection.execute(
                "INSERT INTO approval_consumptions(approval_id, message_id, task_id, "
                "event_sequence) VALUES (?, ?, ?, ?)",
                (
                    message.payload["approval_id"],
                    message_id,
                    task.task_id,
                    next_sequence,
                ),
            )
            self._append_event(
                connection,
                graph_artifact,
                timestamp,
                actor="scheduler",
                cause="approval-consumed",
                task_id=task.task_id,
                context_snapshot_id=task.context_snapshot_id,
                before_state=state,
                after_state=state,
                lease_id=lease_id,
                message_id=message_id,
                approval_id=str(message.payload["approval_id"]),
            )
        return True

    def _reserve_retry(self, connection: sqlite3.Connection, graph: TaskGraph) -> bool:
        row = connection.execute(
            "SELECT used FROM budget_totals WHERE resource = 'retries'"
        ).fetchone()
        if row["used"] >= graph.budget.max_retries:
            return False
        self._change_budget(connection, "retries", used_delta=1)
        return True

    def _observe_wall_time(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        timestamp: str,
    ) -> None:
        created_at = connection.execute(
            "SELECT value FROM metadata WHERE key = 'created_at'"
        ).fetchone()[0]
        elapsed = int((parse_utc(timestamp) - parse_utc(created_at)).total_seconds())
        if elapsed < 0:
            raise SchedulerAdapterError("Scheduler clock moved before database creation.")
        row = connection.execute(
            "SELECT used FROM budget_totals WHERE resource = 'wall_time_seconds'"
        ).fetchone()
        previous = int(row["used"])
        if elapsed <= previous:
            return
        delta = elapsed - previous
        self._change_budget(connection, "wall_time_seconds", used_delta=delta)
        sequence = self._append_event(
            connection,
            graph_artifact,
            timestamp,
            actor="scheduler",
            cause="wall-time-observed",
            task_id=None,
            context_snapshot_id=None,
            before_state=None,
            after_state=None,
            budget_deltas={"wall_time_seconds": delta},
        )
        self._append_budget_snapshot(connection, graph_artifact, graph, sequence)

    def _m7_lease_evidence(
        self,
        connection: sqlite3.Connection,
        message: MailboxMessage,
        current: sqlite3.Row | None,
    ) -> SolverLeaseEvidence:
        """Derive exact M6 authority for M7 evidence replay."""

        if message.task_id is None or message.lease_id is None:
            raise SchedulerAdapterError("Solver task result lacks Lease identity.")
        row = current
        if row is None:
            row = connection.execute(
                "SELECT * FROM current_leases WHERE task_id = ? AND lease_id = ?",
                (message.task_id, message.lease_id),
            ).fetchone()
        if row is not None:
            lease_artifact = _parse_artifact_json(
                str(row["artifact_json"]), SchedulerArtifactType.LEASE
            )
        else:
            history = connection.execute(
                "SELECT artifact_json FROM lease_history "
                "WHERE task_id = ? AND authority_lease_id = ? "
                "ORDER BY event_sequence DESC LIMIT 1",
                (message.task_id, message.lease_id),
            ).fetchone()
            if history is None:
                raise SchedulerAdapterError("Solver Lease history is unavailable.")
            lease_artifact = _parse_artifact_json(
                str(history["artifact_json"]), SchedulerArtifactType.LEASE
            )
        lease = lease_artifact.value
        assert isinstance(lease, Lease)
        dispatch_matches = tuple(
            (message_id, dispatch)
            for _, message_id, dispatch, _ in _adopted_message_entries(
                connection,
                cause="dispatch-intent",
                message_type=MessageType.DISPATCH_INTENT,
            )
            if dispatch.task_id == message.task_id and dispatch.lease_id == message.lease_id
        )
        if len(dispatch_matches) != 1:
            raise SchedulerAdapterError("Solver dispatch evidence is ambiguous.")
        dispatch_id, dispatch = dispatch_matches[0]
        payload = dispatch.to_dict()["payload"]
        assert isinstance(payload, dict)
        reservation = payload.get("budget_reservation")
        if not isinstance(reservation, dict):
            raise SchedulerAdapterError("Solver dispatch reservation is unavailable.")
        calls = int(reservation.get("solver_calls", -1))
        steps = int(reservation.get("solver_steps", -1))
        if calls != 1 or steps < 2 or lease.owner_id != message.sender:
            raise SchedulerAdapterError("Solver Lease authority is inconsistent.")
        return SolverLeaseEvidence(
            graph_id=lease.graph_id,
            task_id=lease.task_id,
            host_id=lease.owner_id,
            attempt=lease.attempt,
            lease_id=message.lease_id,
            fence=lease.fence,
            idempotency_key=lease.idempotency_key,
            dispatch_message_id=dispatch_id,
            expires_at=lease.expires_at,
            reserved_solver_calls=calls,
            reserved_solver_steps=steps,
        )

    def _dispatch_for_lease(
        self, connection: sqlite3.Connection, task_id: str, lease_id: str
    ) -> MailboxMessage | None:
        for _, _, message, _ in reversed(
            _adopted_message_entries(
                connection,
                cause="dispatch-intent",
                message_type=MessageType.DISPATCH_INTENT,
            )
        ):
            if message.task_id == task_id and message.lease_id == lease_id:
                return message
        return None

    def _lease_was_activated(
        self, connection: sqlite3.Connection, task_id: str, lease_id: str
    ) -> bool:
        for event, _, message, _ in _adopted_message_entries(connection):
            if (
                event.cause in {"dispatch-intent", "worktree-request"}
                and message.task_id == task_id
                and message.lease_id == lease_id
            ):
                return True
        return False

    def _dispatch_reservation_for_lease(
        self, connection: sqlite3.Connection, task_id: str, lease_id: str
    ) -> dict[str, int] | None:
        message = self._dispatch_for_lease(connection, task_id, lease_id)
        if message is None:
            return None
        payload = message.to_dict()["payload"]
        assert isinstance(payload, dict)
        reservation = payload["budget_reservation"]
        assert isinstance(reservation, dict)
        return {str(key): int(value) for key, value in reservation.items()}

    def _outstanding_reservation_for_lease(
        self, connection: sqlite3.Connection, task_id: str, lease_id: str
    ) -> dict[str, int] | None:
        reservation = self._dispatch_reservation_for_lease(connection, task_id, lease_id)
        if reservation is None:
            return None
        settled: set[str] = set()
        all_resources = set(reservation)
        rows = connection.execute("SELECT artifact_json FROM events ORDER BY sequence").fetchall()
        for row in rows:
            event = _parse_artifact_json(
                row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
            ).value
            assert isinstance(event, SchedulerEvent)
            if event.lease_id != lease_id:
                continue
            if event.cause == "dispatch-accepted":
                settled.add("context_bytes")
            elif event.cause in {
                "cancel-acknowledgement",
                "dispatch-rejected",
                "lease-expired",
                "result-received",
                "result-terminal",
            }:
                settled.update(all_resources)
        return {
            resource: 0 if resource in settled else amount
            for resource, amount in reservation.items()
        }

    def _settle_context_reservation(
        self, connection: sqlite3.Connection, task_id: str, lease_id: str
    ) -> int:
        outstanding = self._outstanding_reservation_for_lease(connection, task_id, lease_id)
        if outstanding is None:
            return 0
        amount = outstanding["context_bytes"]
        row = connection.execute(
            "SELECT reserved FROM budget_totals WHERE resource = 'context_bytes'"
        ).fetchone()
        if amount > int(row["reserved"]):
            raise SchedulerAdapterError("Attempt-scoped context reservation drifted.")
        if not amount:
            return 0
        self._change_budget(
            connection,
            "context_bytes",
            reserved_delta=-amount,
            used_delta=amount,
        )
        return amount

    def _settle_result_budget(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        lease_id: str,
        message: MailboxMessage,
    ) -> dict[str, int]:
        reservation = self._dispatch_reservation_for_lease(connection, task_id, lease_id)
        outstanding = self._outstanding_reservation_for_lease(connection, task_id, lease_id)
        if reservation is None or outstanding is None:
            raise SchedulerAdapterError("Task Result has no current dispatch reservation.")
        payload = message.to_dict()["payload"]
        assert isinstance(payload, dict)
        usage = payload["budget_usage"]
        assert isinstance(usage, dict)
        deltas: dict[str, int] = {}
        context_used = self._settle_context_reservation(connection, task_id, lease_id)
        if context_used:
            deltas["context_bytes"] = context_used
        for resource in ("microunits", "solver_calls", "solver_steps", "tool_calls"):
            actual = int(usage[resource])
            reserved = int(reservation[resource])
            if actual > reserved:
                raise SchedulerAdapterError("Task Result exceeds its budget reservation.")
            if resource == "microunits":
                availability = connection.execute(
                    "SELECT availability FROM budget_totals WHERE resource = 'microunits'"
                ).fetchone()[0]
                if availability == "not_available" and actual:
                    raise SchedulerAdapterError("Unavailable cost cannot be reported as used.")
            outstanding_amount = int(outstanding[resource])
            if outstanding_amount != reserved:
                raise SchedulerAdapterError("Attempt-scoped result reservation drifted.")
            total_reserved = int(
                connection.execute(
                    "SELECT reserved FROM budget_totals WHERE resource = ?", (resource,)
                ).fetchone()[0]
            )
            if outstanding_amount > total_reserved:
                raise SchedulerAdapterError("Attempt-scoped result reservation drifted.")
            if outstanding_amount:
                self._change_budget(connection, resource, reserved_delta=-outstanding_amount)
            if actual:
                self._change_budget(connection, resource, used_delta=actual)
                deltas[resource] = actual
        return deltas

    def _close_attempt_budget(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        lease_id: str,
        *,
        conservative: bool,
    ) -> dict[str, int]:
        reservation = self._outstanding_reservation_for_lease(connection, task_id, lease_id)
        if reservation is None:
            return {}
        deltas: dict[str, int] = {}
        for resource, amount in reservation.items():
            row = connection.execute(
                "SELECT reserved FROM budget_totals WHERE resource = ?", (resource,)
            ).fetchone()
            if amount > int(row["reserved"]):
                raise SchedulerAdapterError("Attempt-scoped closing reservation drifted.")
            if not amount:
                continue
            self._change_budget(connection, resource, reserved_delta=-amount)
            if conservative:
                self._change_budget(connection, resource, used_delta=amount)
                deltas[resource] = amount
        return deltas

    def _budget_allows_dispatch(
        self,
        connection: sqlite3.Connection,
        graph: TaskGraph,
        context_bytes: int,
        reservation: dict[str, int],
        *,
        acquire_concurrency: bool = True,
    ) -> bool:
        totals = {row["resource"]: row for row in connection.execute("SELECT * FROM budget_totals")}
        if context_bytes > graph.budget.max_context_bytes_per_dispatch:
            return False
        limits = self._budget_limits(graph)
        return (
            int(totals["dispatches"]["used"]) < graph.budget.max_dispatches
            and int(totals["concurrency"]["reserved"]) + (1 if acquire_concurrency else 0)
            <= limits["concurrency"]
            and int(totals["wall_time_seconds"]["used"]) <= graph.budget.max_wall_time_seconds
            and all(
                int(totals[resource]["reserved"]) + int(totals[resource]["used"]) + amount
                <= limits[resource]
                for resource, amount in reservation.items()
            )
        )

    def _dispatch_reservation(
        self,
        connection: sqlite3.Connection,
        graph: TaskGraph,
        task: Any,
        context_bytes: int,
    ) -> dict[str, int]:
        totals = {row["resource"]: row for row in connection.execute("SELECT * FROM budget_totals")}
        solver = task.kind.value == "solver"
        solver_binding = _m7_solver_reservation(task, graph)
        solver_steps = 0 if solver_binding is None else sum(solver_binding)
        microunits = 0
        if graph.budget.cost_status == "available":
            assert graph.budget.max_microunits is not None
            microunits = max(
                0,
                graph.budget.max_microunits
                - int(totals["microunits"]["reserved"])
                - int(totals["microunits"]["used"]),
            )
        return {
            "context_bytes": context_bytes,
            "microunits": microunits,
            "solver_calls": 1 if solver else 0,
            "solver_steps": solver_steps,
            "tool_calls": len(task.required_tools),
        }

    @staticmethod
    def _budget_limits(graph: TaskGraph) -> dict[str, int]:
        return {
            "concurrency": min(graph.budget.max_agents, graph.budget.max_concurrency),
            "context_bytes": graph.budget.max_context_bytes_total,
            "dispatches": graph.budget.max_dispatches,
            "microunits": 0 if graph.budget.max_microunits is None else graph.budget.max_microunits,
            "retries": graph.budget.max_retries,
            "solver_calls": graph.budget.max_solver_calls,
            "solver_steps": graph.budget.max_solver_steps,
            "tool_calls": graph.budget.max_tool_calls,
            "wall_time_seconds": graph.budget.max_wall_time_seconds,
        }

    def _change_budget(
        self,
        connection: sqlite3.Connection,
        resource: str,
        *,
        reserved_delta: int = 0,
        used_delta: int = 0,
    ) -> None:
        row = connection.execute(
            "SELECT reserved, used FROM budget_totals WHERE resource = ?", (resource,)
        ).fetchone()
        reserved = row["reserved"] + reserved_delta
        used = row["used"] + used_delta
        if (
            reserved < 0
            or used < 0
            or reserved > 1_000_000_000_000_000
            or used > 1_000_000_000_000_000
        ):
            raise SchedulerAdapterError("Budget arithmetic is invalid or overflowed.")
        connection.execute(
            "UPDATE budget_totals SET reserved = ?, used = ? WHERE resource = ?",
            (reserved, used, resource),
        )

    def _budget_ledger(
        self,
        connection: sqlite3.Connection,
        graph_id: str,
        graph: TaskGraph,
        event_sequence: int,
    ) -> BudgetLedger:
        rows = connection.execute("SELECT * FROM budget_totals ORDER BY resource").fetchall()
        return BudgetLedger(
            graph_id=graph_id,
            limits=graph.budget,
            reserved={row["resource"]: row["reserved"] for row in rows},
            used={row["resource"]: row["used"] for row in rows},
            availability={row["resource"]: row["availability"] for row in rows},
            blocker_codes=(),
            event_sequence=event_sequence,
        )

    def _append_budget_snapshot(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        graph: TaskGraph,
        event_sequence: int,
    ) -> None:
        ledger = self._budget_ledger(connection, graph_artifact.artifact_id, graph, event_sequence)
        artifact = artifact_from_value(SchedulerArtifactType.BUDGET_LEDGER, ledger)
        connection.execute(
            "INSERT INTO budget_entries(event_sequence, artifact_id, artifact_json) "
            "VALUES (?, ?, ?)",
            (event_sequence, artifact.artifact_id, _artifact_json(artifact)),
        )

    def _append_event(
        self,
        connection: sqlite3.Connection,
        graph_artifact: LoadedSchedulerArtifact,
        timestamp: str,
        *,
        actor: str,
        cause: str,
        task_id: str | None,
        context_snapshot_id: str | None,
        before_state: str | None,
        after_state: str | None,
        lease_id: str | None = None,
        message_id: str | None = None,
        result_id: str | None = None,
        approval_id: str | None = None,
        budget_deltas: dict[str, int] | None = None,
        reason: str | None = None,
    ) -> int:
        previous_row = connection.execute(
            "SELECT sequence, event_sha256 FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 1 if previous_row is None else previous_row["sequence"] + 1
        previous = "0" * 64 if previous_row is None else previous_row["event_sha256"]
        graph = graph_artifact.value
        assert isinstance(graph, TaskGraph)
        projection = None
        if task_id is not None:
            task_row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise SchedulerAdapterError("Scheduler Event task projection is missing.")
            projection = _projection_from_row(task_row)
            if after_state is None:
                after_state = projection.state.value
            elif after_state != projection.state.value:
                raise SchedulerAdapterError("Scheduler Event state does not match its projection.")
        event = SchedulerEvent(
            sequence=sequence,
            previous_event_sha256=previous,
            actor=actor,
            cause=cause,
            graph_id=graph_artifact.artifact_id,
            task_id=task_id,
            candidate=graph.candidate,
            context_snapshot_id=context_snapshot_id,
            before_state=before_state,
            after_state=after_state,
            lease_id=lease_id,
            message_id=message_id,
            result_id=result_id,
            approval_id=approval_id,
            budget_deltas=({} if budget_deltas is None else dict(sorted(budget_deltas.items()))),
            task_projection=projection,
            reason=reason,
            recorded_at=timestamp,
        )
        artifact = artifact_from_value(SchedulerArtifactType.SCHEDULER_EVENT, event)
        digest = event_digest(artifact)
        connection.execute(
            "INSERT INTO events(sequence, artifact_id, event_sha256, previous_sha256, "
            "artifact_json) VALUES (?, ?, ?, ?, ?)",
            (
                sequence,
                artifact.artifact_id,
                digest,
                previous,
                _artifact_json(artifact),
            ),
        )
        return sequence


def recover_scheduler_database(source: Path, output: Path, root: Path) -> SQLiteSchedulerStore:
    """Rebuild mutable projections from validated immutable evidence."""

    source_store = SQLiteSchedulerStore(source, root)
    source_store.validate_evidence()
    resolved_root = _regular_root(root)
    target = _path_under_root(resolved_root, output, suffix=".sqlite3", existing=False)
    source_connection = source_store._connect(read_only=True)
    try:
        graph_artifact = source_store._graph(source_connection)
        validate_task_graph_inputs(graph_artifact, resolved_root)
        before_evidence = _immutable_evidence_digest(source_connection)
    finally:
        source_connection.close()
    descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        os.close(descriptor)
        descriptor = -1
        temporary = Path(name)
        source_connection = source_store._connect(read_only=True)
        target_connection = sqlite3.connect(temporary, timeout=0, isolation_level=None)
        target_connection.row_factory = sqlite3.Row
        try:
            _configure(target_connection)
            target_connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            target_connection.execute(f"PRAGMA user_version = {USER_VERSION}")
            target_connection.executescript(_SCHEMA)
            target_connection.execute("BEGIN IMMEDIATE")
            try:
                _rebuild_from_evidence(source_connection, target_connection, graph_artifact)
                target_connection.commit()
            except BaseException:
                target_connection.rollback()
                raise
        finally:
            target_connection.close()
            source_connection.close()
        _validate_connection_file(temporary)
        temporary_store = SQLiteSchedulerStore.__new__(SQLiteSchedulerStore)
        temporary_store._root = resolved_root
        temporary_store._path = temporary
        temporary_store.validate()
        rebuilt_connection = temporary_store._connect(read_only=True)
        try:
            if _immutable_evidence_digest(rebuilt_connection) != before_evidence:
                raise SchedulerAdapterError("Recovery changed immutable scheduler evidence.")
        finally:
            rebuilt_connection.close()
        os.link(temporary, target)
        if not os.path.samefile(temporary, target):
            raise SchedulerAdapterError("Recovery publication identity is indeterminate.")
    except FileExistsError as exc:
        raise SchedulerAdapterError("Recovery output already exists.") from exc
    except SchedulerAdapterError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise SchedulerAdapterError("Recovery failed or publication is indeterminate.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    recovered = SQLiteSchedulerStore(target, resolved_root)
    recovered.validate()
    recovered_connection = recovered._connect(read_only=True)
    try:
        if _immutable_evidence_digest(recovered_connection) != before_evidence:
            raise SchedulerAdapterError("Recovered database evidence does not match the source.")
    finally:
        recovered_connection.close()
    return recovered


def _immutable_evidence_digest(connection: sqlite3.Connection) -> str:
    metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
    payload: dict[str, object] = {
        "metadata": {
            key: metadata[key]
            for key in (
                "created_at",
                "graph_id",
                "heartbeat_interval_seconds",
                "lease_ttl_seconds",
                "schema_version",
            )
        }
    }
    for table, order in (
        ("task_graph", "graph_id"),
        ("events", "sequence"),
        ("messages", "sequence"),
        ("lease_history", "event_sequence, artifact_id"),
        ("budget_entries", "event_sequence"),
        ("worktree_lease_history", "event_sequence, artifact_id"),
    ):
        rows = connection.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
        payload[table] = [dict(row) for row in rows]
    return _sha256_json(payload)


def _rebuild_from_evidence(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    graph_artifact: LoadedSchedulerArtifact,
) -> None:
    graph = graph_artifact.value
    assert isinstance(graph, TaskGraph)
    metadata = dict(source.execute("SELECT key, value FROM metadata").fetchall())
    target.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)",
        (
            ("schema_version", SCHEMA_VERSION),
            ("graph_id", graph_artifact.artifact_id),
            ("created_at", metadata["created_at"]),
            ("lease_ttl_seconds", metadata["lease_ttl_seconds"]),
            ("heartbeat_interval_seconds", metadata["heartbeat_interval_seconds"]),
            ("host_capabilities", "{}"),
        ),
    )
    target.execute(
        "INSERT INTO task_graph(graph_id, artifact_json) VALUES (?, ?)",
        (graph_artifact.artifact_id, _artifact_json(graph_artifact)),
    )
    ranks = topological_ranks(graph)
    for task in graph.tasks:
        state = TaskState.READY if not task.dependencies else TaskState.PLANNED
        target.execute(
            "INSERT INTO tasks(task_id, definition_json, wave, topological_rank, state, "
            "dispatch_phase, outcome, attempt, fence, blockers_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, '[]')",
            (
                task.task_id,
                canonical_json_bytes(task.to_dict()).decode("ascii"),
                task.wave,
                ranks[task.task_id],
                state.value,
                DispatchPhase.NOT_DISPATCHED.value,
                TaskOutcome.NONE.value,
            ),
        )
        target.executemany(
            "INSERT INTO dependencies(task_id, dependency_id) VALUES (?, ?)",
            ((task.task_id, dependency) for dependency in task.dependencies),
        )

    _copy_rows(
        source,
        target,
        "events",
        ("sequence", "artifact_id", "event_sha256", "previous_sha256", "artifact_json"),
        "sequence",
    )
    _copy_rows(
        source,
        target,
        "messages",
        (
            "sequence",
            "artifact_id",
            "message_type",
            "direction",
            "task_id",
            "idempotency_key",
            "artifact_json",
        ),
        "sequence",
    )
    _copy_rows(
        source,
        target,
        "lease_history",
        (
            "event_sequence",
            "artifact_id",
            "authority_lease_id",
            "task_id",
            "fence",
            "status",
            "artifact_json",
        ),
        "event_sequence, artifact_id",
    )
    _copy_rows(
        source,
        target,
        "budget_entries",
        ("event_sequence", "artifact_id", "artifact_json"),
        "event_sequence",
    )
    _copy_rows(
        source,
        target,
        "worktree_lease_history",
        ("event_sequence", "artifact_id", "task_id", "status", "artifact_json"),
        "event_sequence, artifact_id",
    )

    for row in target.execute("SELECT artifact_json FROM events ORDER BY sequence").fetchall():
        event = _parse_artifact_json(
            row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
        ).value
        assert isinstance(event, SchedulerEvent)
        if event.task_projection is None:
            continue
        projection = event.task_projection
        target.execute(
            "UPDATE tasks SET state = ?, dispatch_phase = ?, outcome = ?, attempt = ?, "
            "fence = ?, blockers_json = ? WHERE task_id = ?",
            (
                projection.state.value,
                projection.dispatch_phase.value,
                projection.outcome.value,
                projection.attempt,
                projection.fence,
                canonical_json_bytes([item.to_dict() for item in projection.blockers]).decode(
                    "ascii"
                ),
                projection.task_id,
            ),
        )

    availability = {
        name: (
            "not_available"
            if name == "microunits" and graph.budget.cost_status == "not_available"
            else "available"
        )
        for name in RESOURCE_NAMES
    }
    latest_budget_row = target.execute(
        "SELECT artifact_json FROM budget_entries ORDER BY event_sequence DESC LIMIT 1"
    ).fetchone()
    if latest_budget_row is None:
        raise SchedulerAdapterError("Recovery requires budget evidence.")
    latest_budget = _parse_artifact_json(
        latest_budget_row["artifact_json"], SchedulerArtifactType.BUDGET_LEDGER
    ).value
    assert isinstance(latest_budget, BudgetLedger)
    target.executemany(
        "INSERT INTO budget_totals(resource, reserved, used, availability) VALUES (?, ?, ?, ?)",
        (
            (
                name,
                int(latest_budget.reserved[name]),
                int(latest_budget.used[name]),
                str(latest_budget.availability.get(name, availability[name])),
            )
            for name in RESOURCE_NAMES
        ),
    )

    task_ids = [task.task_id for task in graph.tasks]
    for task_id in task_ids:
        row = target.execute(
            "SELECT * FROM lease_history WHERE task_id = ? ORDER BY event_sequence DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if row is None or row["status"] != LeaseStatus.CURRENT.value:
            continue
        artifact = _parse_artifact_json(row["artifact_json"], SchedulerArtifactType.LEASE)
        lease = artifact.value
        assert isinstance(lease, Lease)
        target.execute(
            "INSERT INTO current_leases(task_id, lease_id, projection_artifact_id, owner_id, "
            "attempt, fence, idempotency_key, acquired_at, heartbeat_at, expires_at, "
            "artifact_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                row["authority_lease_id"],
                artifact.artifact_id,
                lease.owner_id,
                lease.attempt,
                lease.fence,
                lease.idempotency_key,
                lease.acquired_at,
                lease.heartbeat_at,
                lease.expires_at,
                row["artifact_json"],
            ),
        )
    for task_id in task_ids:
        worktree_row = target.execute(
            "SELECT * FROM worktree_lease_history WHERE task_id = ? "
            "ORDER BY event_sequence DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if worktree_row is None or worktree_row["status"] not in {
            WorktreeLeaseStatus.REQUESTED.value,
            WorktreeLeaseStatus.OBSERVED.value,
        }:
            continue
        worktree_artifact = _parse_artifact_json(
            worktree_row["artifact_json"], SchedulerArtifactType.WORKTREE_LEASE
        )
        worktree = worktree_artifact.value
        assert isinstance(worktree, WorktreeLease)
        target.execute(
            "INSERT INTO current_worktree_leases(task_id, artifact_id, owner_id, fence, "
            "worktree, artifact_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                task_id,
                worktree_artifact.artifact_id,
                worktree.owner_id,
                worktree.fence,
                worktree.worktree,
                worktree_row["artifact_json"],
            ),
        )

    for row in target.execute("SELECT artifact_json FROM events ORDER BY sequence").fetchall():
        event = _parse_artifact_json(
            row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
        ).value
        assert isinstance(event, SchedulerEvent)
        if event.cause == "approval-consumed":
            assert event.approval_id is not None
            assert event.message_id is not None
            assert event.task_id is not None
            target.execute(
                "INSERT INTO approval_consumptions(approval_id, message_id, task_id, "
                "event_sequence) VALUES (?, ?, ?, ?)",
                (event.approval_id, event.message_id, event.task_id, event.sequence),
            )
    capabilities_by_host: dict[str, object] = {}
    for _, _, capability, _ in _adopted_message_entries(
        target,
        cause="capability-observed",
        message_type=MessageType.CAPABILITY_OBSERVATION,
    ):
        payload = capability.to_dict()["payload"]
        assert isinstance(payload, dict)
        capabilities_by_host[capability.sender] = payload["capabilities"]
    target.execute(
        "UPDATE metadata SET value = ? WHERE key = 'host_capabilities'",
        (canonical_json_bytes(capabilities_by_host).decode("ascii"),),
    )


def _copy_rows(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    order: str,
) -> None:
    column_list = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    rows = source.execute(f"SELECT {column_list} FROM {table} ORDER BY {order}").fetchall()
    target.executemany(
        f"INSERT INTO {table}({column_list}) VALUES ({placeholders})",
        (tuple(row[column] for column in columns) for row in rows),
    )


def _adopted_message_entries(
    connection: sqlite3.Connection,
    *,
    cause: str | None = None,
    message_type: MessageType | None = None,
) -> list[tuple[SchedulerEvent, str, MailboxMessage, int]]:
    """Return primary-adopted messages in immutable event order."""

    entries: list[tuple[SchedulerEvent, str, MailboxMessage, int]] = []
    for event_row in connection.execute(
        "SELECT artifact_json FROM events ORDER BY sequence"
    ).fetchall():
        event = _parse_artifact_json(
            event_row["artifact_json"], SchedulerArtifactType.SCHEDULER_EVENT
        ).value
        assert isinstance(event, SchedulerEvent)
        if (
            event.cause not in _PRIMARY_MESSAGE_EVENT_CAUSES
            or event.message_id is None
            or (cause is not None and event.cause != cause)
        ):
            continue
        message_row = connection.execute(
            "SELECT sequence, artifact_json FROM messages WHERE artifact_id = ?",
            (event.message_id,),
        ).fetchone()
        if message_row is None:
            continue
        message = _parse_artifact_json(
            message_row["artifact_json"], SchedulerArtifactType.MAILBOX_MESSAGE
        ).value
        assert isinstance(message, MailboxMessage)
        if message_type is not None and message.message_type is not message_type:
            continue
        entries.append((event, event.message_id, message, int(message_row["sequence"])))
    return entries


def _schema_signature(connection: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
    rows = connection.execute(
        "SELECT type, name, tbl_name, COALESCE(sql, '') AS sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    return tuple(
        (str(row["type"]), str(row["name"]), str(row["tbl_name"]), str(row["sql"])) for row in rows
    )


def _expected_schema_signature() -> tuple[tuple[str, str, str, str], ...]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(_SCHEMA)
        return _schema_signature(connection)
    finally:
        connection.close()


def _configure(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA trusted_schema = OFF")
    connection.execute("PRAGMA busy_timeout = 0")


def _validate_connection_file(path: Path) -> None:
    connection = sqlite3.connect(path, timeout=0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        _configure(connection)
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if application_id != APPLICATION_ID or user_version != USER_VERSION:
            raise SchedulerAdapterError("Temporary scheduler database version is invalid.")
        if connection.execute("PRAGMA integrity_check(1)").fetchone()[0] != "ok":
            raise SchedulerAdapterError("Temporary scheduler database is corrupt.")
    finally:
        connection.close()


def _validate_database_path(path: Path) -> None:
    if path.is_symlink() or is_reparse_point(path) or not path.is_file():
        raise SchedulerAdapterError("Scheduler database must be a regular unlinked file.")
    if path.stat().st_size > MAX_DATABASE_BYTES:
        raise SchedulerAdapterError("Scheduler database exceeds the size limit.")


def _regular_root(root: Path) -> Path:
    try:
        if root.is_symlink() or is_reparse_point(root):
            raise SchedulerAdapterError("Scheduler root must be regular and unlinked.")
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise SchedulerAdapterError("Scheduler root is unavailable.") from exc
    if not resolved.is_dir():
        raise SchedulerAdapterError("Scheduler root must be a directory.")
    return resolved


def _path_under_root(root: Path, path: Path, *, suffix: str, existing: bool) -> Path:
    candidate = path if path.is_absolute() else root / path
    if candidate.suffix.casefold() != suffix:
        raise SchedulerAdapterError(f"Scheduler path must end in {suffix}.")
    try:
        lexical = Path(os.path.abspath(candidate))
        if ".." in candidate.parts or not lexical.is_relative_to(root):
            raise SchedulerAdapterError("Scheduler path escapes its explicit regular root.")
        current = root
        for part in lexical.parent.relative_to(root).parts:
            current = current / part
            if not current.is_dir() or current.is_symlink() or is_reparse_point(current):
                raise SchedulerAdapterError("Scheduler path parent is linked or irregular.")
        resolved_parent = lexical.parent.resolve(strict=True)
    except OSError as exc:
        raise SchedulerAdapterError("Scheduler path parent is unavailable.") from exc
    if not resolved_parent.is_relative_to(root):
        raise SchedulerAdapterError("Scheduler path escapes its explicit regular root.")
    resolved = resolved_parent / lexical.name
    if existing:
        if not resolved.exists():
            raise SchedulerAdapterError("Scheduler state does not exist.")
        _validate_database_path(resolved)
    elif resolved.exists() or resolved.is_symlink() or is_reparse_point(resolved):
        raise SchedulerAdapterError("Scheduler output must be fresh.")
    return resolved


def _artifact_json(artifact: LoadedSchedulerArtifact) -> str:
    expected = artifact_from_value(artifact.artifact_type, artifact.value).artifact_id
    if artifact.artifact_id != expected:
        raise SchedulerAdapterError("Scheduler artifact identity is stale.")
    return canonical_json_bytes(artifact.to_dict()).decode("ascii")


def _parse_artifact_json(value: str, expected: SchedulerArtifactType) -> LoadedSchedulerArtifact:
    try:
        return parse_scheduler_artifact_bytes(value.encode("ascii"), expected_type=expected)
    except (UnicodeError, SchedulerContractError) as exc:
        raise SchedulerAdapterError("Stored scheduler artifact is invalid.") from exc


def _projection_changes(
    before: TaskProjection,
    after: TaskProjection,
) -> set[str]:
    """Return the exact mutable projection fields changed by one event."""

    fields = ("state", "dispatch_phase", "outcome", "attempt", "fence", "blockers")
    return {field for field in fields if getattr(before, field) != getattr(after, field)}


def _projection_from_row(row: sqlite3.Row) -> TaskProjection:
    blockers_raw = json.loads(row["blockers_json"])
    blockers = tuple(
        Blocker(str(item["code"]), tuple(str(value) for value in item["references"]))
        for item in blockers_raw
    )
    return TaskProjection(
        task_id=row["task_id"],
        state=TaskState(row["state"]),
        dispatch_phase=DispatchPhase(row["dispatch_phase"]),
        outcome=TaskOutcome(row["outcome"]),
        attempt=row["attempt"],
        fence=row["fence"],
        blockers=blockers,
    )


def _m7_solver_reservation(task: Any, graph: TaskGraph) -> tuple[int, int] | None:
    """Return one exact M7 solve/verification reservation or fail closed."""

    if task.kind.value != "solver":
        return None
    tokens = tuple(
        capability
        for capability in task.required_capabilities
        if capability.startswith("m7-solver-v1@")
    )
    if (
        len(tokens) != 1
        or task.effect_kind is not EffectKind.READ_ONLY
        or task.required_tools
        or task.owned_paths
        or task.worktree_assignment is not None
        or task.evidence_predicate != ("evidence-reference-present",)
        or task.terminal_predicate != ("agent-result-valid",)
        or graph.budget.max_solver_calls < 1
    ):
        return None
    try:
        _, solve_steps, verification_steps = parse_solver_capability_token(tokens[0])
    except SolverContractError:
        return None
    if solve_steps + verification_steps > graph.budget.max_solver_steps:
        return None
    return solve_steps, verification_steps


def _blockers_json(code: str, references: tuple[str, ...] = ()) -> str:
    return canonical_json_bytes([Blocker(code, references).to_dict()]).decode("ascii")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest().upper()
