from collections.abc import Sequence
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
    classify_failure,
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
from sdaqf.ports.process import ProcessResult, ProcessTimeout
from tests.m2_helpers import m2_example


class RecordingRunner:
    def __init__(self, results: list[ProcessResult | BaseException]) -> None:
        self.results = results
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> ProcessResult:
        command = tuple(args)
        self.calls.append(command)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def context() -> ExecutionContext:
    return ExecutionContext(
        plan_version="1.0",
        specification_digest="A" * 64,
        git_head="a" * 40,
        worktree_digest="B" * 64,
    )


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


def load_approval(
    tool: ToolDefinition,
    *,
    approval_type: str = "owner",
) -> ExecutionApproval:
    return ExecutionApprovalLoader(
        clock=lambda: datetime(2026, 7, 28, 10, tzinfo=UTC)
    ).parse(approval_payload(tool, approval_type=approval_type))


def test_tool_check_observes_presence_numeric_version_and_bounds() -> None:
    runner = RecordingRunner(
        [
            ProcessResult(
                0,
                "Python 3.12.13",
                "",
                stdout_truncated=True,
                stderr_truncated=False,
            )
        ]
    )
    tool = python_tool()

    result = ToolService(
        runner,
        locator=lambda _: "python",
        platform="windows",
    ).check(tool)

    assert result.status is ToolObservationStatus.AVAILABLE
    assert result.version == "3.12.13"
    assert result.stdout_truncated
    assert result.execution_mode == "normal"
    assert runner.calls == [("python", "--version")]


def test_tool_check_distinguishes_optional_missing_and_unsupported_version() -> None:
    registry = load_tool_registry(m2_example("tool-registry.json"))
    optional = registry.by_name("z3")
    python = registry.by_name("python")
    assert optional is not None
    assert python is not None
    missing_runner = RecordingRunner([])

    missing = ToolService(
        missing_runner,
        locator=lambda _: None,
        platform="linux",
    ).check(optional)
    unsupported = ToolService(
        RecordingRunner([ProcessResult(0, "Python 3.9.10", "")]),
        locator=lambda _: "python",
        platform="linux",
    ).check(python)

    assert missing.status is ToolObservationStatus.UNAVAILABLE
    assert not missing_runner.calls
    assert unsupported.status is ToolObservationStatus.UNSUPPORTED_VERSION
    assert unsupported.version == "3.9.10"


@pytest.mark.parametrize(
    ("failure", "status", "classification"),
    (
        (
            PermissionError(),
            ToolObservationStatus.PERMISSION_DENIED,
            FailureClass.PERMISSION_DENIAL,
        ),
        (
            ProcessTimeout(
                "timeout",
                stdout="partial",
                stderr="",
                stdout_truncated=True,
                stderr_truncated=False,
            ),
            ToolObservationStatus.TIMEOUT,
            FailureClass.PROCESS_TIMEOUT,
        ),
        (
            ProcessResult(2, "", "sandbox denied"),
            ToolObservationStatus.PERMISSION_DENIED,
            FailureClass.SANDBOX_DENIAL,
        ),
        (
            ProcessResult(2, "", "ordinary failure"),
            ToolObservationStatus.NON_ZERO_EXIT,
            FailureClass.NON_ZERO_EXIT,
        ),
    ),
)
def test_tool_check_classifies_permission_timeout_and_nonzero(
    failure: ProcessResult | BaseException,
    status: ToolObservationStatus,
    classification: FailureClass,
) -> None:
    runner = RecordingRunner([failure])

    result = ToolService(
        runner,
        locator=lambda _: "python",
        platform="windows",
    ).check(python_tool())

    assert result.status is status
    assert result.failure_class is classification


def test_tool_output_is_redacted_before_checkpoint_use() -> None:
    secret = "ghp_" + ("x" * 25)
    personal = "C:\\" + "Users\\person\\project"
    runner = RecordingRunner(
        [ProcessResult(2, secret, personal)]
    )

    result = ToolService(
        runner,
        locator=lambda _: "python",
        platform="windows",
    ).check(python_tool())

    assert secret not in result.stdout
    assert personal not in result.stderr
    assert "[REDACTED]" in result.stdout
    assert "[REDACTED-PATH]" in result.stderr


def test_approval_scope_mismatch_blocks_before_runner() -> None:
    tool = replace(
        python_tool(),
        owner_approval=ApprovalRequirement.REQUIRED,
    )
    runner = RecordingRunner([])
    payload = approval_payload(tool)
    scope = payload["scope"]
    assert isinstance(scope, dict)
    scope["command"] = ["python", "-V"]
    mismatched = ExecutionApprovalLoader(
        clock=lambda: datetime(2026, 7, 28, 10, tzinfo=UTC)
    ).parse(payload)
    service = ToolService(
        runner,
        locator=lambda _: "python",
        platform="windows",
        clock=lambda: datetime(2026, 7, 28, 10, tzinfo=UTC),
    )

    result = service.check(tool, approvals=(mismatched,))

    assert result.status is ToolObservationStatus.BLOCKED
    assert result.failure_class is FailureClass.AUTHORIZATION_FAILURE
    assert not runner.calls


def test_exact_approval_scope_is_recorded_and_resolved_executable_is_used(
    tmp_path: Path,
) -> None:
    tool = replace(
        python_tool(),
        owner_approval=ApprovalRequirement.REQUIRED,
    )
    approval = load_approval(tool)
    runner = RecordingRunner(
        [ProcessResult(0, "Python 3.12.13", "", duration_ms=17)]
    )

    result = ToolService(
        runner,
        locator=lambda _: "C:/resolved/python.exe",
        platform="windows",
        clock=lambda: datetime(2026, 7, 28, 10, tzinfo=UTC),
        consumption_store=ExecutionApprovalConsumptionStore(tmp_path),
    ).check(tool, approvals=(approval,))

    assert result.status is ToolObservationStatus.AVAILABLE
    assert result.execution_mode == "approved"
    assert result.approval_ids == ("APR-M2-0001",)
    assert result.duration_ms == 17
    assert runner.calls == [("C:/resolved/python.exe", "--version")]


@pytest.mark.parametrize(
    ("failure", "status", "classification"),
    (
        (
            FileNotFoundError(),
            ToolObservationStatus.UNAVAILABLE,
            FailureClass.TOOL_UNAVAILABLE,
        ),
        (
            TimeoutError(),
            ToolObservationStatus.TIMEOUT,
            FailureClass.PROCESS_TIMEOUT,
        ),
        (
            OSError("authentication failed"),
            ToolObservationStatus.NON_ZERO_EXIT,
            FailureClass.AUTHENTICATION_FAILURE,
        ),
        (
            OSError("network is unreachable"),
            ToolObservationStatus.BLOCKED,
            FailureClass.NETWORK_DENIAL,
        ),
    ),
)
def test_tool_check_classifies_runner_exceptions(
    failure: BaseException,
    status: ToolObservationStatus,
    classification: FailureClass,
) -> None:
    result = ToolService(
        RecordingRunner([failure]),
        locator=lambda _: "python",
        platform="windows",
    ).check(python_tool())

    assert result.status is status
    assert result.failure_class is classification


def test_tool_check_handles_unsupported_platform_and_unmatched_versions() -> None:
    required = python_tool()
    optional = replace(required, optional=True)
    runner = RecordingRunner([])

    blocked = ToolService(
        runner,
        locator=lambda _: "python",
        platform="unsupported",
    ).check(required)
    skipped = ToolService(
        runner,
        locator=lambda _: "python",
        platform="unsupported",
    ).check(optional)
    unmatched = ToolService(
        RecordingRunner([ProcessResult(0, "not a version", "")]),
        locator=lambda _: "python",
        platform="windows",
    ).check(required)
    optional_capture = ToolService(
        RecordingRunner([ProcessResult(0, "Python", "")]),
        locator=lambda _: "python",
        platform="windows",
    ).check(
        replace(
            required,
            version_pattern=r"Python(?: ([0-9]+(?:\.[0-9]+)*))?",
        )
    )

    assert blocked.status is ToolObservationStatus.BLOCKED
    assert skipped.status is ToolObservationStatus.NOT_CHECKED
    assert unmatched.status is ToolObservationStatus.UNSUPPORTED_VERSION
    assert optional_capture.status is ToolObservationStatus.UNSUPPORTED_VERSION
    assert not runner.calls


def test_retry_requires_retryable_failure_and_new_state_token() -> None:
    timeout = ProcessTimeout(
        "timeout",
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
    )
    runner = RecordingRunner(
        [timeout, ProcessResult(0, "Python 3.12.13", "")]
    )
    service = ToolService(
        runner,
        locator=lambda _: "python",
        platform="windows",
    )
    controller = ExecutionController(service)
    tool = python_tool()

    first = controller.execute(tool, context=context())
    with pytest.raises(ToolContractError, match="state change"):
        controller.execute(
            tool,
            context=context(),
            prior=first,
        )
    second = controller.execute(
        tool,
        context=context(),
        prior=first,
        state_change_token="sandbox-approved-once",
    )

    assert first.attempts == 1
    assert first.last_failure is FailureClass.PROCESS_TIMEOUT
    assert second.attempts == 2
    assert second.state.value == "completed"


def test_retry_rejects_mismatched_exhausted_and_nonretryable_checkpoints() -> None:
    timeout = ProcessTimeout(
        "timeout",
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
    )
    tool = python_tool()
    service = ToolService(
        RecordingRunner([timeout]),
        locator=lambda _: "python",
        platform="windows",
    )
    controller = ExecutionController(service)
    first = controller.execute(tool, context=context())

    with pytest.raises(ToolContractError, match="command"):
        controller.execute(
            replace(tool, version_command=("python", "-V")),
            context=context(),
            prior=first,
            state_change_token="changed",
        )
    with pytest.raises(ToolContractError, match="context"):
        controller.execute(
            tool,
            context=replace(context(), git_head="b" * 40),
            prior=first,
            state_change_token="changed",
        )
    with pytest.raises(ToolContractError, match="exhausted"):
        controller.execute(
            tool,
            context=context(),
            prior=replace(first, attempts=tool.max_attempts),
            state_change_token="changed",
        )
    with pytest.raises(ToolContractError, match="not retryable"):
        controller.execute(
            tool,
            context=context(),
            prior=replace(first, last_failure=FailureClass.NON_ZERO_EXIT),
            state_change_token="changed",
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("network is unreachable", FailureClass.NETWORK_DENIAL),
        ("authentication failed", FailureClass.AUTHENTICATION_FAILURE),
        ("authorization failed", FailureClass.AUTHORIZATION_FAILURE),
        ("permission denied", FailureClass.PERMISSION_DENIAL),
        ("test failure", FailureClass.TEST_FAILURE),
        ("workflow failure", FailureClass.WORKFLOW_FAILURE),
        ("HTTP 503 service unavailable", FailureClass.EXTERNAL_SERVICE_FAILURE),
        ("unclassified", FailureClass.UNKNOWN_FAILURE),
    ),
)
def test_failure_classification_is_explicit(
    text: str,
    expected: FailureClass,
) -> None:
    assert classify_failure(text) is expected
