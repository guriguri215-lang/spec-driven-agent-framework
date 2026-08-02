"""Deterministic offline simulations for the real M6 SQLite state machine."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.context_contracts import canonical_json_bytes
from sdaqf.application.scheduler import SchedulerService, deterministic_wait_report
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    artifact_from_value,
)
from sdaqf.domain.quality import ArtifactReference
from sdaqf.domain.scheduler import (
    EffectKind,
    MailboxMessage,
    MessageDirection,
    MessageType,
    SchedulerArtifactType,
    SchedulerState,
    TaskGraph,
)

SCENARIOS = (
    "success",
    "worker-crash-after-dispatch",
    "host-timeout",
    "result-disagreement",
    "wait-for-deadlock",
    "budget-exhaustion",
    "missing-capability",
    "duplicate-and-late-result",
    "cancellation-unknown",
    "ambiguous-external-effect",
)
FIXED_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
HOST_ID = "HST-SIMULATOR"


@dataclass(slots=True)
class FixedSchedulerClock:
    """Mutable fixed UTC clock owned only by a simulation."""

    value: datetime = FIXED_START

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class SchedulerSimulationResult:
    """One reproducible named scenario result."""

    scenario: str
    outcome: str
    state_id: str
    event_count: int
    message_count: int
    accepted_messages: int
    rejected_messages: int
    wait_kind: str
    blockers: tuple[str, ...]
    offline: bool
    deterministic_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "outcome": self.outcome,
            "state_id": self.state_id,
            "event_count": self.event_count,
            "message_count": self.message_count,
            "accepted_messages": self.accepted_messages,
            "rejected_messages": self.rejected_messages,
            "wait_kind": self.wait_kind,
            "blockers": list(self.blockers),
            "offline": self.offline,
            "deterministic_digest": self.deterministic_digest,
        }


class SchedulerSimulationService:
    """Execute named failure and success cases with no external host effect."""

    def run(
        self,
        task_graph: Path,
        root: Path,
        scenario: str,
    ) -> SchedulerSimulationResult:
        """Run one exact scenario using a fresh real SQLite store."""

        if scenario not in SCENARIOS:
            raise ValueError("Scheduler simulation scenario is unsupported.")
        clock = FixedSchedulerClock()
        base_artifact = SchedulerService(clock).validate_graph(task_graph, root)
        graph = base_artifact.value
        assert isinstance(graph, TaskGraph)
        graph = _scenario_graph(graph, scenario)
        graph_artifact = artifact_from_value(SchedulerArtifactType.TASK_GRAPH, graph)
        with tempfile.TemporaryDirectory(prefix=".sdaqf-m6-sim-", dir=root) as directory:
            state = Path(directory) / "state.sqlite3"
            store = SQLiteSchedulerStore.initialize(
                state,
                root,
                graph_artifact,
                clock.now(),
            )
            result = self._execute(store, root, graph, scenario, clock)
        return result

    def _execute(
        self,
        store: SQLiteSchedulerStore,
        root: Path,
        graph: TaskGraph,
        scenario: str,
        clock: FixedSchedulerClock,
    ) -> SchedulerSimulationResult:
        first_tick = store.tick(root, HOST_ID, (), clock.now())
        accepted = 0
        rejected = 0

        if scenario == "worker-crash-after-dispatch":
            store = SQLiteSchedulerStore(store.path, root)
            store.validate()
            outcome = "running-with-current-fenced-lease"
        elif scenario == "host-timeout":
            clock.advance(61)
            timed_out = store.tick(root, HOST_ID, (), clock.now())
            accepted += len(timed_out.accepted_message_ids)
            rejected += len(timed_out.rejected_message_ids)
            outcome = "safe-read-only-attempt-redispatched"
        elif scenario == "wait-for-deadlock":
            outcome = "deadlock-reported-without-speculation"
        elif scenario == "missing-capability":
            outcome = "blocked-missing-capability"
        elif scenario == "budget-exhaustion":
            outcome = "one-running-one-budget-blocked"
        else:
            dispatch = first_tick.outgoing[0]
            acknowledgement = _host_message(
                dispatch,
                MessageType.DISPATCH_ACKNOWLEDGEMENT,
                {
                    "accepted": True,
                    "effect_observed": "none",
                    "note": "Simulator accepted the bounded intent.",
                },
                clock.now(),
            )
            ack_tick = store.tick(root, HOST_ID, (acknowledgement,), clock.now())
            accepted += len(ack_tick.accepted_message_ids)
            rejected += len(ack_tick.rejected_message_ids)
            if scenario == "cancellation-unknown":
                cancel_request = store.request_cancel(
                    root,
                    HOST_ID,
                    graph.tasks[0].task_id,
                    "Simulator requested cooperative cancellation.",
                    clock.now(),
                )
                cancellation = _host_message(
                    cancel_request,
                    MessageType.CANCEL_ACKNOWLEDGEMENT,
                    {"cancelled": False, "effect_observed": "ambiguous"},
                    clock.now(),
                )
                final_tick = store.tick(root, HOST_ID, (cancellation,), clock.now())
                outcome = "blocked-unknown-cancellation"
            else:
                result = _result_message(
                    dispatch,
                    root,
                    outcome=("unknown" if scenario == "ambiguous-external-effect" else "succeeded"),
                    effect=("ambiguous" if scenario == "ambiguous-external-effect" else "none"),
                    clock=clock.now(),
                )
                incoming: tuple[LoadedSchedulerArtifact, ...]
                if scenario == "result-disagreement":
                    conflict = _result_message(
                        dispatch,
                        root,
                        outcome="failed",
                        effect="none",
                        clock=clock.now(),
                    )
                    incoming = (result, conflict)
                else:
                    incoming = (result,)
                final_tick = store.tick(root, HOST_ID, incoming, clock.now())
                if scenario == "duplicate-and-late-result":
                    duplicate_tick = store.tick(
                        root,
                        HOST_ID,
                        (acknowledgement,),
                        clock.now(),
                    )
                    late = _host_message(
                        dispatch,
                        MessageType.HEARTBEAT,
                        {"progress": "Late heartbeat retained only as rejected audit."},
                        clock.now(),
                    )
                    late_tick = store.tick(root, HOST_ID, (late,), clock.now())
                    accepted += len(duplicate_tick.accepted_message_ids)
                    rejected += len(late_tick.rejected_message_ids)
                    outcome = "duplicate-idempotent-late-rejected"
                elif scenario == "result-disagreement":
                    outcome = "first-result-adopted-conflict-rejected"
                elif scenario == "ambiguous-external-effect":
                    outcome = "blocked-unknown-no-automatic-retry"
                else:
                    outcome = "completed-after-verification"
            accepted += len(final_tick.accepted_message_ids)
            rejected += len(final_tick.rejected_message_ids)

        store.validate()
        wait_report = deterministic_wait_report(store.wait_for_projection())
        wait_kind = wait_report.kind
        blockers = wait_report.cycle if wait_report.kind == "deadlock" else wait_report.blockers
        state = store.status()
        events = store.export("events")
        messages = store.export("messages")
        state_value = state.value
        assert isinstance(state_value, SchedulerState)
        _assert_scenario_property(scenario, state_value, accepted, rejected, wait_kind)
        payload: dict[str, object] = {
            "scenario": scenario,
            "outcome": outcome,
            "state_id": state.artifact_id,
            "event_count": len(events),
            "message_count": len(messages),
            "accepted_messages": accepted,
            "rejected_messages": rejected,
            "wait_kind": wait_kind,
            "blockers": list(blockers),
            "offline": True,
        }
        digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest().upper()
        return SchedulerSimulationResult(
            scenario=scenario,
            outcome=outcome,
            state_id=state.artifact_id,
            event_count=len(events),
            message_count=len(messages),
            accepted_messages=accepted,
            rejected_messages=rejected,
            wait_kind=wait_kind,
            blockers=blockers,
            offline=True,
            deterministic_digest=digest,
        )


def run_all_scenarios(
    task_graph: Path,
    root: Path,
) -> tuple[SchedulerSimulationResult, ...]:
    """Execute all ten scenarios in exact public order."""

    service = SchedulerSimulationService()
    return tuple(service.run(task_graph, root, scenario) for scenario in SCENARIOS)


def _scenario_graph(graph: TaskGraph, scenario: str) -> TaskGraph:
    first = graph.tasks[0]
    tasks = graph.tasks
    budget = graph.budget
    if scenario == "missing-capability":
        changed = replace(first, required_capabilities=("unavailable-capability",))
        tasks = tuple(sorted((changed, *graph.tasks[1:]), key=lambda item: item.task_id))
    elif scenario == "ambiguous-external-effect":
        changed = replace(first, effect_kind=EffectKind.EXTERNAL)
        tasks = tuple(sorted((changed, *graph.tasks[1:]), key=lambda item: item.task_id))
    elif scenario == "budget-exhaustion":
        changed = replace(first, dependencies=(), required_capabilities=())
        second = replace(
            changed,
            task_id="TSK-SECOND",
            review_targets=(),
            owned_paths=(),
            worktree_assignment=None,
        )
        tasks = tuple(sorted((changed, second), key=lambda item: item.task_id))
        budget = replace(budget, max_dispatches=1, max_concurrency=2, max_agents=2)
    elif scenario == "wait-for-deadlock":
        first_wait = replace(
            first,
            task_id="TSK-WAIT-A",
            dependencies=(),
            required_capabilities=("task:TSK-WAIT-B",),
            review_targets=(),
            owned_paths=(),
            worktree_assignment=None,
        )
        second_wait = replace(
            first_wait,
            task_id="TSK-WAIT-B",
            required_capabilities=("task:TSK-WAIT-A",),
        )
        tasks = (first_wait, second_wait)
        budget = replace(budget, max_concurrency=2, max_agents=2)
    elif scenario == "host-timeout":
        changed = replace(
            first,
            effect_kind=EffectKind.READ_ONLY,
            max_attempts=2,
            required_capabilities=(),
        )
        tasks = tuple(sorted((changed, *graph.tasks[1:]), key=lambda item: item.task_id))
        budget = replace(budget, max_retries=max(1, budget.max_retries))
    return replace(graph, tasks=tasks, budget=budget)


def _assert_scenario_property(
    scenario: str,
    state: SchedulerState,
    accepted: int,
    rejected: int,
    wait_kind: str,
) -> None:
    projections = state.tasks
    states = [item.state.value for item in projections]
    outcomes = [item.outcome.value for item in projections]
    blockers = {
        blocker.code for projection in projections for blocker in projection.blockers
    }
    valid = {
        "success": states == ["completed"] and outcomes == ["succeeded"],
        "worker-crash-after-dispatch": states == ["running"] and bool(state.lease_ids),
        "host-timeout": states == ["running"] and projections[0].attempt == 2,
        "result-disagreement": states == ["completed"] and rejected >= 1,
        "wait-for-deadlock": wait_kind == "deadlock" and states == ["blocked", "blocked"],
        "budget-exhaustion": wait_kind == "stall"
        and states.count("running") == 1
        and states.count("blocked") == 1
        and "budget-exhausted" in blockers,
        "missing-capability": wait_kind == "stall"
        and states == ["blocked"]
        and "missing-capability" in blockers,
        "duplicate-and-late-result": states == ["completed"]
        and accepted >= 2
        and rejected >= 1,
        "cancellation-unknown": states == ["blocked"] and outcomes == ["unknown"],
        "ambiguous-external-effect": states == ["blocked"] and outcomes == ["unknown"],
    }[scenario]
    if not valid:
        raise RuntimeError(f"M6 scenario {scenario} did not establish its durable property.")


def _host_message(
    dispatch_artifact: LoadedSchedulerArtifact,
    message_type: MessageType,
    payload: dict[str, object],
    clock: datetime,
) -> LoadedSchedulerArtifact:
    dispatch = dispatch_artifact.value
    assert isinstance(dispatch, MailboxMessage)
    message = MailboxMessage(
        message_type=message_type,
        direction=MessageDirection.HOST_TO_SCHEDULER,
        sender=HOST_ID,
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
        causal_parent_message_ids=(dispatch_artifact.artifact_id,),
        recorded_at=clock.isoformat(timespec="seconds").replace("+00:00", "Z"),
        payload=payload,
    )
    return artifact_from_value(SchedulerArtifactType.MAILBOX_MESSAGE, message)


def _result_message(
    dispatch: LoadedSchedulerArtifact,
    root: Path,
    *,
    outcome: str,
    effect: str,
    clock: datetime,
) -> LoadedSchedulerArtifact:
    path = Path("examples/m2-orchestration/implementer-result.json")
    digest = hashlib.sha256((root / path).read_bytes()).hexdigest().upper()
    return _host_message(
        dispatch,
        MessageType.TASK_RESULT,
        {
            "agent_result": ArtifactReference(path.as_posix(), digest).to_dict(),
            "outcome": outcome,
            "effect_observed": effect,
            "evidence_refs": [ArtifactReference(path.as_posix(), digest).to_dict()],
            "budget_usage": {
                "microunits": 0,
                "solver_calls": 0,
                "solver_steps": 0,
                "tool_calls": 0,
            },
        },
        clock,
    )
