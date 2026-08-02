"""Application services for host-agnostic M6 scheduling."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from sdaqf.adapters.scheduler import (
    ExclusiveSchedulerArtifactStore,
    SchedulerTick,
    SQLiteSchedulerStore,
    SystemSchedulerClock,
)
from sdaqf.application.scheduler_contracts import (
    LoadedSchedulerArtifact,
    SchedulerContractError,
    load_scheduler_artifact,
)
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.scheduler import SchedulerArtifactType, SchedulerState, TaskGraph
from sdaqf.ports.scheduler import SchedulerClock


@dataclass(frozen=True, slots=True)
class WaitReport:
    """Deterministic deadlock or stall explanation."""

    kind: str
    cycle: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "cycle": list(self.cycle),
            "blockers": list(self.blockers),
        }


class SchedulerService:
    """Validate inputs and coordinate one explicit local scheduler store."""

    def __init__(self, clock: SchedulerClock | None = None) -> None:
        self._clock = SystemSchedulerClock() if clock is None else clock

    def validate_graph(self, task_graph: Path, root: Path) -> LoadedSchedulerArtifact:
        """Validate one Task Graph and every exact referenced M2/M5 input."""

        resolved_root = _regular_root(root)
        path = _existing_under_root(resolved_root, task_graph, ".json")
        return load_scheduler_artifact(
            path,
            expected_type=SchedulerArtifactType.TASK_GRAPH,
            root=resolved_root,
        )

    def initialize(
        self,
        task_graph: Path,
        root: Path,
        state: Path,
    ) -> LoadedSchedulerArtifact:
        """Exclusively initialize one fresh schema-1 scheduler database."""

        graph = self.validate_graph(task_graph, root)
        store = SQLiteSchedulerStore.initialize(state, root, graph, self._clock.now())
        return store.status()

    def tick(
        self,
        state: Path,
        root: Path,
        host_id: str,
        messages: tuple[Path, ...] = (),
    ) -> SchedulerTick:
        """Advance one bounded transaction without dispatching a process."""

        resolved_root = _regular_root(root)
        store = SQLiteSchedulerStore(state, resolved_root)
        loaded = tuple(
            load_scheduler_artifact(
                _existing_under_root(resolved_root, path, ".json"),
                expected_type=SchedulerArtifactType.MAILBOX_MESSAGE,
            )
            for path in messages
        )
        return store.tick(resolved_root, host_id, loaded, self._clock.now())

    def status(self, state: Path, root: Path) -> LoadedSchedulerArtifact:
        """Return the current deterministic state without mutation."""

        return SQLiteSchedulerStore(state, root).status()

    def wait_report(self, state: Path, root: Path) -> WaitReport:
        """Return the production typed wait-for report from durable scheduler state."""

        projection = SQLiteSchedulerStore(state, root).wait_for_projection()
        return deterministic_wait_report(projection)

    def request_cancel(
        self,
        state: Path,
        root: Path,
        host_id: str,
        task_id: str,
        reason: str,
    ) -> LoadedSchedulerArtifact:
        """Create one durable scheduler-to-host cooperative cancellation intent."""

        resolved_root = _regular_root(root)
        return SQLiteSchedulerStore(state, resolved_root).request_cancel(
            resolved_root,
            host_id,
            task_id,
            reason,
            self._clock.now(),
        )

    def export(
        self,
        state: Path,
        root: Path,
        kind: str,
        output: Path,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> dict[str, object]:
        """Exclusively publish one bounded export wrapper."""

        resolved_root = _regular_root(root)
        artifacts = SQLiteSchedulerStore(state, resolved_root).export(
            kind,
            after_sequence=after_sequence,
            limit=limit,
        )
        payload: dict[str, object] = {
            "kind": kind,
            "after_sequence": after_sequence,
            "limit": limit,
            "items": [item.to_dict() for item in artifacts],
        }
        content = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "ascii"
        )
        ExclusiveSchedulerArtifactStore(resolved_root).publish(output, content)
        return {
            "kind": kind,
            "count": len(artifacts),
            "output": Path(output).name,
        }

    def inspect_mailbox(
        self,
        state: Path,
        root: Path,
        *,
        task_id: str | None = None,
        direction: str | None = None,
        limit: int = 100,
    ) -> tuple[LoadedSchedulerArtifact, ...]:
        """Return a filtered bounded mailbox view without mutation."""

        return SQLiteSchedulerStore(state, root).inspect_mailbox(
            task_id=task_id,
            direction=direction,
            limit=limit,
        )


def deterministic_wait_report(
    wait_for: dict[str, tuple[str, ...]],
) -> WaitReport:
    """Return the canonical smallest cycle or sorted stall blockers."""

    normalized = {node: tuple(sorted(set(targets))) for node, targets in sorted(wait_for.items())}
    cycles: list[tuple[str, ...]] = []
    for start in normalized:
        stack: list[tuple[str, tuple[str, ...]]] = [(start, (start,))]
        while stack:
            node, path = stack.pop()
            for target in reversed(normalized.get(node, ())):
                if target == start:
                    canonical = _canonical_cycle(path)
                    if canonical not in cycles:
                        cycles.append(canonical)
                elif target not in path and len(path) <= len(normalized):
                    stack.append((target, (*path, target)))
    if cycles:
        cycle = min(cycles, key=lambda value: (len(value), value))
        return WaitReport("deadlock", cycle, ())
    blockers = tuple(
        f"{node}->{target}" for node, targets in normalized.items() for target in targets
    )
    return WaitReport("clear" if not blockers else "stall", (), blockers)


def scheduler_state_wait_report(
    graph: TaskGraph,
    state: SchedulerState,
) -> WaitReport:
    """Project dependency and blocker waits from one state artifact."""

    projections = {item.task_id: item for item in state.tasks}
    wait_sets: dict[str, set[str]] = {}

    def add(source: str, target: str) -> None:
        wait_sets.setdefault(source, set()).add(target)

    for task in graph.tasks:
        if projections[task.task_id].state.value in {
            "completed",
            "rejected",
            "superseded",
        }:
            continue
        node = f"task:{task.task_id}"
        for dependency in task.dependencies:
            if projections[dependency].state.value != "completed":
                add(node, f"task:{dependency}")
        for target in task.review_targets:
            if projections[target].state.value != "completed":
                add(node, f"task:{target}")
        for blocker in projections[task.task_id].blockers:
            references = blocker.references or (task.task_id,)
            for reference in references:
                add(node, f"blocker:{blocker.code}:{reference}")
    waits = {node: tuple(sorted(targets)) for node, targets in sorted(wait_sets.items())}
    return deterministic_wait_report(waits)


def _canonical_cycle(path: tuple[str, ...]) -> tuple[str, ...]:
    rotations = tuple(path[index:] + path[:index] for index in range(len(path)))
    return min(rotations)


def _regular_root(root: Path) -> Path:
    try:
        if root.is_symlink() or is_reparse_point(root):
            raise SchedulerContractError("Scheduler root must be regular and unlinked.")
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise SchedulerContractError("Scheduler root is unavailable.") from exc
    if not resolved.is_dir():
        raise SchedulerContractError("Scheduler root must be a directory.")
    return resolved


def _existing_under_root(root: Path, path: Path, suffix: str) -> Path:
    candidate = path if path.is_absolute() else root / path
    if candidate.suffix.casefold() != suffix:
        raise SchedulerContractError(f"Scheduler input must end in {suffix}.")
    try:
        lexical = Path(os.path.abspath(candidate))
        if ".." in candidate.parts or not lexical.is_relative_to(root):
            raise SchedulerContractError("Scheduler input escapes its regular root.")
        current = root
        for part in lexical.relative_to(root).parts:
            current = current / part
            if current.is_symlink() or is_reparse_point(current):
                raise SchedulerContractError("Scheduler input contains a linked component.")
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SchedulerContractError("Scheduler input is unavailable.") from exc
    if (
        not resolved.is_relative_to(root)
        or not resolved.is_file()
    ):
        raise SchedulerContractError("Scheduler input escapes its regular root.")
    return resolved
