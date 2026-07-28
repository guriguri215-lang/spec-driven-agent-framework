import json
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sdaqf.application.tooling import (
    ExecutionApprovalConsumptionStore,
    ExecutionApprovalLoader,
    ExecutionController,
    ToolContractError,
    ToolService,
    load_tool_registry,
)
from sdaqf.domain.tooling import (
    ApprovalRequirement,
    ExecutionApproval,
    ExecutionContext,
    FailureClass,
    ToolDefinition,
    ToolObservationStatus,
)
from sdaqf.ports.process import ProcessResult
from tests.m2_helpers import m2_example, write_json

NOW = datetime(2026, 7, 28, 10, tzinfo=UTC)


class RecordingRunner:
    def __init__(self, results: list[ProcessResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> ProcessResult:
        self.calls.append(tuple(args))
        return self.results.pop(0)


def python_tool() -> ToolDefinition:
    tool = load_tool_registry(m2_example("tool-registry.json")).by_name("python")
    assert tool is not None
    return tool


def approval_payload(
    tool: ToolDefinition,
    *,
    approval_type: str = "owner",
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "approval_id": "APR-M2-0001",
        "approval_type": approval_type,
        "action": "Execute one registered tool version probe",
        "scope": {
            "tool_name": tool.name,
            "command": list(tool.version_command),
            "normal_scope": list(tool.normal_scope),
            "protected_paths": list(tool.protected_paths),
            "network_destinations": list(tool.network_destinations),
        },
        "risk": tool.risk.value,
        "status": "approved",
        "rationale": "Permit this exact bounded local version probe.",
        "reversible": True,
        "approved_by": (
            "Owner"
            if approval_type == "owner"
            else "Technical sandbox reviewer"
        ),
        "approved_at": "2026-07-28T09:00:00+00:00",
        "expires_at": "2026-07-28T11:00:00+00:00",
        "lifetime": "single_execution",
        "conditions": {
            "execution": "version_probe",
            "max_executions": 1,
        },
    }


def loader() -> ExecutionApprovalLoader:
    return ExecutionApprovalLoader(clock=lambda: NOW)


def context() -> ExecutionContext:
    return ExecutionContext(
        plan_version="1.0",
        specification_digest="A" * 64,
        git_head="a" * 40,
        worktree_digest="B" * 64,
    )


def test_execution_approval_requires_strict_loader_and_regular_file(
    tmp_path: Path,
) -> None:
    path = write_json(tmp_path / "approval.json", approval_payload(python_tool()))

    approval = loader().load(path)

    assert approval.approval_id == "APR-M2-0001"
    assert approval.approved_by == "Owner"
    assert approval.lifetime == "single_execution"
    with pytest.raises(TypeError, match="strict loader"):
        ExecutionApproval()


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda value: value.update(schema_version="2.0"),
            "schema_version",
        ),
        (
            lambda value: value.update(approved_by="Agent"),
            "approved_by",
        ),
        (
            lambda value: value.update(approved_at="2026-07-28T12:00:00+00:00"),
            "future",
        ),
        (
            lambda value: value.update(expires_at="2026-07-28T08:59:00+00:00"),
            "expiry",
        ),
        (
            lambda value: value.update(expires_at="2026-07-28T10:00:00+00:00"),
            "expired",
        ),
        (
            lambda value: value.update(lifetime="session"),
            "single_execution",
        ),
        (
            lambda value: _conditions(value).update(max_executions=2),
            "max_executions",
        ),
        (
            lambda value: value.update(risk="prohibited"),
            "prohibited",
        ),
        (
            lambda value: value.update(extra="unsupported"),
            "unknown fields",
        ),
    ),
)
def test_execution_approval_loader_rejects_untrusted_lifecycle_fields(
    mutate: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    payload = approval_payload(python_tool())
    mutate(payload)

    with pytest.raises(ToolContractError, match=message):
        loader().parse(payload)


def test_technical_approval_has_distinct_authority() -> None:
    tool = python_tool()
    payload = approval_payload(tool, approval_type="technical_sandbox")
    payload["approved_by"] = "Owner"

    with pytest.raises(ToolContractError, match="approved_by"):
        loader().parse(payload)

    payload["approved_by"] = "Technical sandbox reviewer"
    approval = loader().parse(payload)
    assert approval.approval_type == "technical_sandbox"


def test_expired_after_load_and_consumed_single_use_block_before_runner() -> None:
    tool = replace(
        python_tool(),
        owner_approval=ApprovalRequirement.REQUIRED,
    )
    approval = loader().parse(approval_payload(tool))
    expired_runner = RecordingRunner([])
    expired = ToolService(
        expired_runner,
        locator=lambda _: "python",
        platform="windows",
        clock=lambda: datetime(2026, 7, 28, 12, tzinfo=UTC),
    ).check(tool, approvals=(approval,))
    consumed_runner = RecordingRunner([])
    consumed = ToolService(
        consumed_runner,
        locator=lambda _: "python",
        platform="windows",
        clock=lambda: NOW,
    ).check(
        tool,
        approvals=(approval,),
        consumed_approval_ids=frozenset({approval.approval_id}),
    )

    assert expired.status is ToolObservationStatus.BLOCKED
    assert consumed.status is ToolObservationStatus.BLOCKED
    assert "consumed" in consumed.detail
    assert not expired_runner.calls
    assert not consumed_runner.calls


def test_approval_claim_persists_across_independent_executions(
    tmp_path: Path,
) -> None:
    tool = replace(
        python_tool(),
        owner_approval=ApprovalRequirement.REQUIRED,
    )
    approval = loader().parse(approval_payload(tool))
    first_runner = RecordingRunner(
        [ProcessResult(0, "Python 3.12.13", "")]
    )
    second_runner = RecordingRunner([])

    first = ToolService(
        first_runner,
        locator=lambda _: "python",
        platform="windows",
        clock=lambda: NOW,
        consumption_store=ExecutionApprovalConsumptionStore(tmp_path),
    ).check(tool, approvals=(approval,))
    second = ToolService(
        second_runner,
        locator=lambda _: "python",
        platform="windows",
        clock=lambda: NOW,
        consumption_store=ExecutionApprovalConsumptionStore(tmp_path),
    ).check(tool, approvals=(approval,))

    assert first.status is ToolObservationStatus.AVAILABLE
    assert second.status is ToolObservationStatus.BLOCKED
    assert "already consumed" in second.detail
    assert len(first_runner.calls) == 1
    assert not second_runner.calls
    assert (
        tmp_path
        / ".sdaqf"
        / "execution-approval-consumption.json"
    ).is_file()


def test_concurrent_claim_allows_exactly_one_process_start(tmp_path: Path) -> None:
    tool = replace(
        python_tool(),
        owner_approval=ApprovalRequirement.REQUIRED,
    )
    approval = loader().parse(approval_payload(tool))
    runners = [
        RecordingRunner([ProcessResult(0, "Python 3.12.13", "")]),
        RecordingRunner([ProcessResult(0, "Python 3.12.13", "")]),
    ]

    def invoke(runner: RecordingRunner) -> ToolObservationStatus:
        return ToolService(
            runner,
            locator=lambda _: "python",
            platform="windows",
            clock=lambda: NOW,
            consumption_store=ExecutionApprovalConsumptionStore(tmp_path),
        ).check(tool, approvals=(approval,)).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = tuple(executor.map(invoke, runners))

    assert statuses.count(ToolObservationStatus.AVAILABLE) == 1
    assert statuses.count(ToolObservationStatus.BLOCKED) == 1
    assert sum(len(runner.calls) for runner in runners) == 1


def test_approval_execution_requires_store_and_preserves_foreign_lock(
    tmp_path: Path,
) -> None:
    tool = replace(
        python_tool(),
        owner_approval=ApprovalRequirement.REQUIRED,
    )
    approval = loader().parse(approval_payload(tool))
    no_store_runner = RecordingRunner([])
    no_store = ToolService(
        no_store_runner,
        locator=lambda _: "python",
        platform="windows",
        clock=lambda: NOW,
    ).check(tool, approvals=(approval,))
    state_directory = tmp_path / ".sdaqf"
    state_directory.mkdir()
    lock = state_directory / "execution-approval-consumption.lock"
    lock.write_text("foreign lock\n", encoding="utf-8")
    locked_runner = RecordingRunner([])
    locked = ToolService(
        locked_runner,
        locator=lambda _: "python",
        platform="windows",
        clock=lambda: NOW,
        consumption_store=ExecutionApprovalConsumptionStore(tmp_path),
    ).check(tool, approvals=(approval,))

    assert no_store.status is ToolObservationStatus.BLOCKED
    assert "persistent" in no_store.detail
    assert locked.status is ToolObservationStatus.BLOCKED
    assert "locked" in locked.detail
    assert lock.is_file()
    assert not no_store_runner.calls
    assert not locked_runner.calls


@pytest.mark.parametrize(
    "store_content",
    (
        "{not-json",
        "\u0000",
        json.dumps({"schema_version": "2.0", "consumed": []}),
        json.dumps({"schema_version": "1.0", "consumed": {}}),
        json.dumps(
            {
                "schema_version": "1.0",
                "consumed": [
                    {
                        "approval_id": "bad",
                        "scope_digest": "A" * 64,
                        "claimed_at": "2026-07-28T09:00:00+00:00",
                    }
                ],
            }
        ),
        json.dumps(
            {
                "schema_version": "1.0",
                "consumed": [
                    {
                        "approval_id": "APR-M2-FUTURE",
                        "scope_digest": "A" * 64,
                        "claimed_at": "2026-07-28T11:00:00+00:00",
                    }
                ],
            }
        ),
        json.dumps(
            {
                "schema_version": "1.0",
                "consumed": [
                    {
                        "approval_id": "APR-M2-DUPLICATE",
                        "scope_digest": "A" * 64,
                        "claimed_at": "2026-07-28T09:00:00+00:00",
                    },
                    {
                        "approval_id": "APR-M2-DUPLICATE",
                        "scope_digest": "B" * 64,
                        "claimed_at": "2026-07-28T09:01:00+00:00",
                    },
                ],
            }
        ),
        json.dumps(
            {
                "schema_version": "1.0",
                "consumed": [
                    {
                        "approval_id": "APR-M2-ZZZ",
                        "scope_digest": "A" * 64,
                        "claimed_at": "2026-07-28T09:00:00+00:00",
                    },
                    {
                        "approval_id": "APR-M2-AAA",
                        "scope_digest": "B" * 64,
                        "claimed_at": "2026-07-28T09:01:00+00:00",
                    },
                ],
            }
        ),
    ),
)
def test_corrupt_consumption_store_blocks_before_process(
    tmp_path: Path,
    store_content: str,
) -> None:
    tool = replace(
        python_tool(),
        owner_approval=ApprovalRequirement.REQUIRED,
    )
    approval = loader().parse(approval_payload(tool))
    state_directory = tmp_path / ".sdaqf"
    state_directory.mkdir()
    (state_directory / "execution-approval-consumption.json").write_text(
        store_content,
        encoding="utf-8",
    )
    runner = RecordingRunner([])

    result = ToolService(
        runner,
        locator=lambda _: "python",
        platform="windows",
        clock=lambda: NOW,
        consumption_store=ExecutionApprovalConsumptionStore(tmp_path),
    ).check(tool, approvals=(approval,))

    assert result.status is ToolObservationStatus.BLOCKED
    assert result.failure_class is FailureClass.AUTHORIZATION_FAILURE
    assert not runner.calls


def test_consumption_store_rejects_invalid_root_and_naive_claim_time(
    tmp_path: Path,
) -> None:
    approval = loader().parse(approval_payload(python_tool()))
    missing_root = tmp_path / "missing"

    with pytest.raises(ToolContractError, match="regular directory"):
        ExecutionApprovalConsumptionStore(missing_root).claim(
            (approval,),
            claimed_at=NOW,
        )
    with pytest.raises(ToolContractError, match="timezone-aware"):
        ExecutionApprovalConsumptionStore(tmp_path).claim(
            (approval,),
            claimed_at=datetime(2026, 7, 28, 10),
        )
    ExecutionApprovalConsumptionStore(tmp_path).claim((), claimed_at=NOW)


def test_sandbox_retry_requires_exact_technical_approval(tmp_path: Path) -> None:
    tool = replace(
        python_tool(),
        technical_approval=ApprovalRequirement.MAY_BE_REQUIRED,
    )
    runner = RecordingRunner(
        [
            ProcessResult(2, "", "sandbox denied"),
            ProcessResult(0, "Python 3.12.13", ""),
        ]
    )
    controller = ExecutionController(
        ToolService(
            runner,
            locator=lambda _: "python",
            platform="windows",
            clock=lambda: NOW,
            consumption_store=ExecutionApprovalConsumptionStore(tmp_path),
        )
    )

    first = controller.execute(tool, context=context())
    blocked = ToolService(
        RecordingRunner([]),
        locator=lambda _: "python",
        platform="windows",
        clock=lambda: NOW,
    ).check(
        tool,
        additional_required_approval_types=frozenset({"technical_sandbox"}),
    )
    approval = loader().parse(
        approval_payload(tool, approval_type="technical_sandbox")
    )
    second = controller.execute(
        tool,
        context=context(),
        prior=first,
        state_change_token="APR-M2-0001",
        approvals=(approval,),
    )

    assert first.last_failure is FailureClass.SANDBOX_DENIAL
    assert blocked.failure_class is FailureClass.AUTHORIZATION_FAILURE
    assert second.state.value == "completed"
    assert second.observation is not None
    assert second.observation.approval_ids == ("APR-M2-0001",)


def _conditions(value: dict[str, object]) -> dict[str, object]:
    conditions = value["conditions"]
    assert isinstance(conditions, dict)
    return conditions
