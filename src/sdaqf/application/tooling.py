"""Strict M2 Tool Registry, approval, version, and retry services."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Self, cast
from urllib.parse import urlsplit

from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.orchestration import RiskLevel
from sdaqf.domain.tooling import (
    ApprovalRequirement,
    CheckpointState,
    ExecutionApproval,
    ExecutionCheckpoint,
    ExecutionContext,
    FailureClass,
    ToolDefinition,
    ToolObservation,
    ToolObservationStatus,
    ToolRegistry,
)
from sdaqf.ports.process import ProcessRunner, ProcessTimeout

Locator = Callable[[str], str | None]

_MAX_REGISTRY_BYTES = 1_000_000
_MAX_APPROVAL_BYTES = 64 * 1024
_MAX_CONSUMPTION_BYTES = 1_000_000
_MAX_CONSUMPTION_RECORDS = 4_096
_MAX_ITEMS = 64
_MAX_TEXT = 500
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_APPROVAL_ID = re.compile(r"^APR-[A-Z0-9][A-Z0-9-]{2,63}$")
_SHA256 = re.compile(r"^[0-9A-F]{64}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,3}$")
_APPROVAL_ACTION = "Execute one registered tool version probe"
_APPROVAL_LIFETIME = "single_execution"
_APPROVAL_AUTHORITIES = {
    "owner": "Owner",
    "technical_sandbox": "Technical sandbox reviewer",
}
_SHELLS = {
    "bash",
    "cmd",
    "cmd.exe",
    "command.com",
    "dash",
    "fish",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "sh",
    "zsh",
}
_DESTRUCTIVE_EXECUTABLES = {
    "del",
    "erase",
    "format",
    "mkfs",
    "rm",
    "rmdir",
}
_PROHIBITED_ARGUMENTS = {
    "--break-system-packages",
    "--global",
    "--unsafe-perm",
    "--user",
    "--yolo",
    "-g",
    "install",
}
_WINDOWS_RESERVED = {
    "aux",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}
_SECRET = re.compile(
    r"(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)
_PERSONAL_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]\x55sers[\\/]|/\x55sers/|/\x68ome/[^/\s]+/)",
    re.IGNORECASE,
)
_RETRYABLE = {
    FailureClass.PROCESS_TIMEOUT,
    FailureClass.SANDBOX_DENIAL,
    FailureClass.NETWORK_DENIAL,
    FailureClass.EXTERNAL_SERVICE_FAILURE,
}


class ToolContractError(ValueError):
    """One bounded Tool Registry or execution-control failure."""


def load_tool_registry(path: Path) -> ToolRegistry:
    """Load a strict Tool Registry version 2.0."""

    root = _load_object(path, "Tool Registry")
    _only_keys(root, {"schema_version", "tools"}, "Tool Registry")
    if _string(root.get("schema_version"), "schema_version") != "2.0":
        raise ToolContractError(
            "Tool Registry schema_version must be 2.0; migration is required."
        )
    raw_tools = _array(root.get("tools"), "tools")
    if not raw_tools:
        raise ToolContractError("tools must not be empty.")
    tools = tuple(
        _parse_tool(item, f"tools[{index}]")
        for index, item in enumerate(raw_tools)
    )
    names = [tool.name.casefold() for tool in tools]
    if len(names) != len(set(names)):
        raise ToolContractError("Tool names must be unique.")
    return ToolRegistry(tools=tuple(sorted(tools, key=lambda item: item.name)))


class ExecutionApprovalLoader:
    """Load a bounded, versioned approval with explicit authority and lifetime."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def load(self, path: Path) -> ExecutionApproval:
        """Load one regular JSON approval record."""

        try:
            if path.stat().st_size > _MAX_APPROVAL_BYTES:
                raise ToolContractError("Execution approval exceeds the size limit.")
        except OSError as exc:
            raise ToolContractError("Execution approval could not be read.") from exc
        return self.parse(_load_object(path, "Execution approval"))

    def parse(self, payload: object) -> ExecutionApproval:
        """Validate exact scope, authority, expiry, and single-use conditions."""

        root = _object(payload, "Execution approval")
        _only_keys(
            root,
            {
                "schema_version",
                "approval_id",
                "approval_type",
                "action",
                "scope",
                "risk",
                "status",
                "rationale",
                "reversible",
                "approved_by",
                "approved_at",
                "expires_at",
                "lifetime",
                "conditions",
            },
            "Execution approval",
        )
        schema_version = _string(root.get("schema_version"), "schema_version")
        if schema_version != "1.0":
            raise ToolContractError(
                "Execution approval schema_version must be 1.0."
            )
        approval_id = _string(root.get("approval_id"), "approval_id")
        if not _APPROVAL_ID.fullmatch(approval_id):
            raise ToolContractError(
                "Execution approval approval_id must be a stable APR identifier."
            )
        approval_type = _string(root.get("approval_type"), "approval_type")
        authority = _APPROVAL_AUTHORITIES.get(approval_type)
        if authority is None:
            raise ToolContractError(
                "Execution approval approval_type is unsupported."
            )
        action = _string(root.get("action"), "action")
        if action != _APPROVAL_ACTION:
            raise ToolContractError(
                "Execution approval action is not a registered version probe."
            )
        if _string(root.get("status"), "status") != "approved":
            raise ToolContractError("Execution approval status must be approved.")
        approved_by = _string(root.get("approved_by"), "approved_by")
        if approved_by != authority:
            raise ToolContractError(
                "Execution approval approved_by does not match approval_type."
            )
        if not _boolean(root.get("reversible"), "reversible"):
            raise ToolContractError("Execution approval reversible must be true.")
        lifetime = _string(root.get("lifetime"), "lifetime")
        if lifetime != _APPROVAL_LIFETIME:
            raise ToolContractError(
                "Execution approval lifetime must be single_execution."
            )
        approved_at = _timestamp(root.get("approved_at"), "approved_at")
        expires_at = _timestamp(root.get("expires_at"), "expires_at")
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        if approved_at > now:
            raise ToolContractError(
                "Execution approval time cannot be in the future."
            )
        if expires_at <= approved_at:
            raise ToolContractError(
                "Execution approval expiry must follow approval time."
            )
        if expires_at <= now:
            raise ToolContractError("Execution approval has expired.")

        scope = _object(root.get("scope"), "scope")
        _only_keys(
            scope,
            {
                "tool_name",
                "command",
                "normal_scope",
                "protected_paths",
                "network_destinations",
            },
            "scope",
        )
        tool_name = _string(scope.get("tool_name"), "scope.tool_name")
        if not _NAME.fullmatch(tool_name):
            raise ToolContractError("scope.tool_name is invalid.")
        command = _string_tuple(scope.get("command"), "scope.command")
        _validate_command(command)
        normal_scope = tuple(
            _safe_relative_path(item, "scope.normal_scope")
            for item in _string_tuple(scope.get("normal_scope"), "scope.normal_scope")
        )
        protected_paths = tuple(
            _safe_relative_path(item, "scope.protected_paths")
            for item in _string_tuple(
                scope.get("protected_paths"),
                "scope.protected_paths",
                allow_empty=True,
            )
        )
        if any(
            _paths_overlap(path, protected)
            for path in normal_scope
            for protected in protected_paths
        ):
            raise ToolContractError(
                "scope.normal_scope must not overlap protected_paths."
            )
        destinations = tuple(
            _network_destination(item, "scope.network_destinations")
            for item in _string_tuple(
                scope.get("network_destinations"),
                "scope.network_destinations",
                allow_empty=True,
            )
        )
        if len(destinations) != len(set(destinations)):
            raise ToolContractError(
                "scope.network_destinations must be canonically unique."
            )
        conditions = _object(root.get("conditions"), "conditions")
        _only_keys(
            conditions,
            {"execution", "max_executions"},
            "conditions",
        )
        if _string(conditions.get("execution"), "conditions.execution") != "version_probe":
            raise ToolContractError(
                "Execution approval condition must name version_probe."
            )
        max_executions = _integer(
            conditions.get("max_executions"),
            "conditions.max_executions",
        )
        if max_executions != 1:
            raise ToolContractError(
                "Execution approval max_executions must be 1."
            )
        risk = _enum(RiskLevel, root.get("risk"), "risk")
        if risk is RiskLevel.PROHIBITED:
            raise ToolContractError(
                "Execution approval cannot authorize prohibited work."
            )
        return ExecutionApproval._from_validated_record(
            schema_version=schema_version,
            approval_id=approval_id,
            approval_type=approval_type,
            action=action,
            tool_name=tool_name,
            command=command,
            network_destinations=destinations,
            normal_scope=normal_scope,
            protected_paths=protected_paths,
            risk=risk,
            status="approved",
            rationale=_string(root.get("rationale"), "rationale"),
            reversible=True,
            approved_by=approved_by,
            approved_at=approved_at,
            expires_at=expires_at,
            lifetime=lifetime,
            max_executions=max_executions,
        )


class ExecutionApprovalConsumptionStore:
    """Atomically persist approval claims before an approved process starts."""

    _STATE_DIRECTORY = ".sdaqf"
    _STORE_NAME = "execution-approval-consumption.json"
    _LOCK_NAME = "execution-approval-consumption.lock"

    def __init__(self, allowed_root: Path) -> None:
        self._allowed_root = allowed_root.resolve()

    @classmethod
    def for_registry(cls, registry_path: Path) -> Self:
        """Bind consumption to the registry's stable project boundary."""

        return cls(_registry_consumption_root(registry_path))

    def claim(
        self,
        approvals: tuple[ExecutionApproval, ...],
        *,
        claimed_at: datetime,
    ) -> None:
        """Claim every approval ID transactionally or fail without execution."""

        if not approvals:
            return
        if claimed_at.tzinfo is None:
            raise ToolContractError(
                "Approval consumption time must be timezone-aware."
            )
        state_directory, target, lock = self._paths()
        lock_descriptor: int | None = None
        lock_owned = False
        temporary: Path | None = None
        try:
            try:
                lock_descriptor = os.open(
                    lock,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                lock_owned = True
            except FileExistsError as exc:
                raise ToolContractError(
                    "Approval consumption store is busy or locked."
                ) from exc
            with os.fdopen(lock_descriptor, "wb") as stream:
                lock_descriptor = None
                stream.write(b"locked\n")
                stream.flush()
                os.fsync(stream.fileno())
            existing = _load_consumption_records(target, now=claimed_at)
            consumed_ids = {item[0] for item in existing}
            requested_ids = {approval.approval_id for approval in approvals}
            reused = sorted(consumed_ids & requested_ids)
            if reused:
                raise ToolContractError(
                    f"Execution approval {reused[0]} is already consumed."
                )
            additions = tuple(
                (
                    approval.approval_id,
                    _approval_scope_digest(approval),
                    claimed_at.isoformat(),
                )
                for approval in approvals
            )
            records = tuple(sorted((*existing, *additions)))
            if len(records) > _MAX_CONSUMPTION_RECORDS:
                raise ToolContractError(
                    "Approval consumption store exceeds the record limit."
                )
            payload = {
                "schema_version": "1.0",
                "consumed": [
                    {
                        "approval_id": approval_id,
                        "scope_digest": scope_digest,
                        "claimed_at": record_claimed_at,
                    }
                    for approval_id, scope_digest, record_claimed_at in records
                ],
            }
            encoded = (
                json.dumps(payload, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            if len(encoded) > _MAX_CONSUMPTION_BYTES:
                raise ToolContractError(
                    "Approval consumption store exceeds the size limit."
                )
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=state_directory,
                prefix=f".{self._STORE_NAME}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        except OSError as exc:
            raise ToolContractError(
                "Approval consumption could not be persisted."
            ) from exc
        finally:
            if lock_descriptor is not None:
                os.close(lock_descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if lock_owned:
                try:
                    lock.unlink(missing_ok=True)
                except OSError as exc:
                    raise ToolContractError(
                        "Approval consumption lock could not be released."
                    ) from exc

    def _paths(self) -> tuple[Path, Path, Path]:
        if (
            not self._allowed_root.is_dir()
            or is_reparse_point(self._allowed_root)
        ):
            raise ToolContractError(
                "Approval consumption root must be a regular directory."
            )
        state_directory = self._allowed_root / self._STATE_DIRECTORY
        try:
            state_directory.mkdir(exist_ok=True)
        except OSError as exc:
            raise ToolContractError(
                "Approval consumption directory could not be created."
            ) from exc
        if (
            not state_directory.is_dir()
            or state_directory.is_symlink()
            or is_reparse_point(state_directory)
            or not state_directory.resolve().is_relative_to(self._allowed_root)
        ):
            raise ToolContractError(
                "Approval consumption directory must be regular and local."
            )
        target = state_directory / self._STORE_NAME
        lock = state_directory / self._LOCK_NAME
        for candidate in (target, lock):
            if candidate.is_symlink() or is_reparse_point(candidate):
                raise ToolContractError(
                    "Approval consumption files must be regular and unlinked."
                )
        if target.exists() and not target.is_file():
            raise ToolContractError(
                "Approval consumption store must be a regular file."
            )
        return state_directory, target, lock


class ToolService:
    """Observe and execute only a validated version command."""

    def __init__(
        self,
        runner: ProcessRunner,
        *,
        locator: Locator = shutil.which,
        platform: str | None = None,
        clock: Callable[[], datetime] | None = None,
        consumption_store: ExecutionApprovalConsumptionStore | None = None,
    ) -> None:
        self._runner = runner
        self._locator = locator
        self._platform = platform or _current_platform()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._consumption_store = consumption_store

    def check(
        self,
        tool: ToolDefinition,
        *,
        approvals: tuple[ExecutionApproval, ...] = (),
        consumed_approval_ids: frozenset[str] = frozenset(),
        additional_required_approval_types: frozenset[str] = frozenset(),
    ) -> ToolObservation:
        """Check policy, presence, version, and bounded execution."""

        if self._platform not in tool.platforms:
            return _observation(
                tool,
                (
                    ToolObservationStatus.NOT_CHECKED
                    if tool.optional
                    else ToolObservationStatus.BLOCKED
                ),
                FailureClass.VALIDATION_FAILURE,
                "Tool does not support the current platform.",
            )
        now = self._clock()
        policy_error = _approval_error(
            tool,
            approvals,
            now=now,
            consumed_approval_ids=consumed_approval_ids,
            additional_required_approval_types=additional_required_approval_types,
        )
        if policy_error is not None:
            return _observation(
                tool,
                ToolObservationStatus.BLOCKED,
                FailureClass.AUTHORIZATION_FAILURE,
                policy_error,
                execution_mode="denied",
            )
        if tool.risk is RiskLevel.PROHIBITED:
            return _observation(
                tool,
                ToolObservationStatus.BLOCKED,
                FailureClass.AUTHORIZATION_FAILURE,
                "Prohibited tools cannot be executed.",
                execution_mode="denied",
            )
        resolved_executable = self._locator(tool.version_command[0])
        if resolved_executable is None:
            return _observation(
                tool,
                ToolObservationStatus.UNAVAILABLE,
                FailureClass.TOOL_UNAVAILABLE,
                "Executable was not found.",
            )
        approval_ids = _applied_approval_ids(
            tool,
            approvals,
            additional_required_approval_types=additional_required_approval_types,
        )
        if approval_ids:
            if self._consumption_store is None:
                return _observation(
                    tool,
                    ToolObservationStatus.BLOCKED,
                    FailureClass.AUTHORIZATION_FAILURE,
                    "A persistent approval consumption store is required.",
                    execution_mode="denied",
                )
            applied_approvals = tuple(
                approval
                for approval in approvals
                if approval.approval_id in set(approval_ids)
            )
            try:
                self._consumption_store.claim(
                    applied_approvals,
                    claimed_at=now,
                )
            except ToolContractError as exc:
                return _observation(
                    tool,
                    ToolObservationStatus.BLOCKED,
                    FailureClass.AUTHORIZATION_FAILURE,
                    str(exc),
                    execution_mode="denied",
                )
        execution_mode = "approved" if approval_ids else "normal"
        try:
            result = self._runner.run(
                (resolved_executable, *tool.version_command[1:])
            )
        except FileNotFoundError:
            return _observation(
                tool,
                ToolObservationStatus.UNAVAILABLE,
                FailureClass.TOOL_UNAVAILABLE,
                "Executable was not found.",
                execution_mode=execution_mode,
                approval_ids=approval_ids,
            )
        except PermissionError:
            return _observation(
                tool,
                ToolObservationStatus.PERMISSION_DENIED,
                FailureClass.PERMISSION_DENIAL,
                "The executable or probe was denied.",
                execution_mode=execution_mode,
                approval_ids=approval_ids,
            )
        except ProcessTimeout as exc:
            return ToolObservation(
                tool_name=tool.name,
                status=ToolObservationStatus.TIMEOUT,
                failure_class=FailureClass.PROCESS_TIMEOUT,
                detail="The bounded version probe timed out.",
                version=None,
                exit_code=None,
                stdout=_sanitize_output(exc.stdout),
                stderr=_sanitize_output(exc.stderr),
                stdout_truncated=exc.stdout_truncated,
                stderr_truncated=exc.stderr_truncated,
                duration_ms=exc.duration_ms,
                execution_mode=execution_mode,
                approval_ids=approval_ids,
            )
        except TimeoutError:
            return _observation(
                tool,
                ToolObservationStatus.TIMEOUT,
                FailureClass.PROCESS_TIMEOUT,
                "The bounded version probe timed out.",
                execution_mode=execution_mode,
                approval_ids=approval_ids,
            )
        except OSError as exc:
            failure = classify_failure(str(exc))
            return _observation(
                tool,
                _status_for_failure(failure),
                failure,
                "The operating system could not run the version probe.",
                execution_mode=execution_mode,
                approval_ids=approval_ids,
            )
        stdout = _sanitize_output(result.stdout)
        stderr = _sanitize_output(result.stderr)
        if result.returncode != 0:
            failure = classify_failure(f"{stdout}\n{stderr}")
            if failure is FailureClass.UNKNOWN_FAILURE:
                failure = FailureClass.NON_ZERO_EXIT
            return ToolObservation(
                tool_name=tool.name,
                status=_status_for_failure(failure),
                failure_class=failure,
                detail=f"Version probe exited with code {result.returncode}.",
                version=None,
                exit_code=result.returncode,
                stdout=stdout,
                stderr=stderr,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                duration_ms=result.duration_ms,
                execution_mode=execution_mode,
                approval_ids=approval_ids,
            )
        output = "\n".join(item for item in (stdout, stderr) if item)
        match = re.search(tool.version_pattern, output)
        if match is None or match.lastindex is None:
            return ToolObservation(
                tool_name=tool.name,
                status=ToolObservationStatus.UNSUPPORTED_VERSION,
                failure_class=FailureClass.UNSUPPORTED_VERSION,
                detail="Version output did not match the registry policy.",
                version=None,
                exit_code=0,
                stdout=stdout,
                stderr=stderr,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                duration_ms=result.duration_ms,
                execution_mode=execution_mode,
                approval_ids=approval_ids,
            )
        version = match.group(1)
        if version is None:
            return ToolObservation(
                tool_name=tool.name,
                status=ToolObservationStatus.UNSUPPORTED_VERSION,
                failure_class=FailureClass.UNSUPPORTED_VERSION,
                detail="Version output did not contain a captured version.",
                version=None,
                exit_code=0,
                stdout=stdout,
                stderr=stderr,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                duration_ms=result.duration_ms,
                execution_mode=execution_mode,
                approval_ids=approval_ids,
            )
        parsed_version = _parse_version(version, "observed version")
        if (
            tool.minimum_version is not None
            and _padded_version(parsed_version) < _padded_version(tool.minimum_version)
        ):
            return ToolObservation(
                tool_name=tool.name,
                status=ToolObservationStatus.UNSUPPORTED_VERSION,
                failure_class=FailureClass.UNSUPPORTED_VERSION,
                detail="Observed version is below the minimum.",
                version=version,
                exit_code=0,
                stdout=stdout,
                stderr=stderr,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
                duration_ms=result.duration_ms,
                execution_mode=execution_mode,
                approval_ids=approval_ids,
            )
        return ToolObservation(
            tool_name=tool.name,
            status=ToolObservationStatus.AVAILABLE,
            failure_class=FailureClass.NONE,
            detail="Safe bounded version probe succeeded.",
            version=version,
            exit_code=0,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=result.stdout_truncated,
            stderr_truncated=result.stderr_truncated,
            duration_ms=result.duration_ms,
            execution_mode=execution_mode,
            approval_ids=approval_ids,
        )


class ExecutionController:
    """Apply bounded retry rules and return a checkpoint."""

    def __init__(self, service: ToolService) -> None:
        self._service = service

    def execute(
        self,
        tool: ToolDefinition,
        *,
        approvals: tuple[ExecutionApproval, ...] = (),
        context: ExecutionContext,
        prior: ExecutionCheckpoint | None = None,
        state_change_token: str | None = None,
    ) -> ExecutionCheckpoint:
        """Execute a first attempt or one justified retry."""

        digest = hashlib.sha256(
            json.dumps(
                list(tool.version_command),
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest().upper()
        if prior is not None:
            if prior.tool_name != tool.name or prior.command_digest != digest:
                raise ToolContractError("Retry checkpoint does not match the command.")
            if prior.context != context:
                raise ToolContractError("Retry context does not match the checkpoint.")
            if prior.attempts >= tool.max_attempts:
                raise ToolContractError("Retry budget is exhausted.")
            if prior.last_failure not in _RETRYABLE:
                raise ToolContractError("The previous failure is not retryable.")
            if (
                state_change_token is None
                or state_change_token == prior.state_change_token
            ):
                raise ToolContractError(
                    "An identical failed command requires a recorded state change."
                )
        consumed_approval_ids = (
            frozenset()
            if prior is None or prior.observation is None
            else frozenset(prior.observation.approval_ids)
        )
        additional_required = (
            frozenset({"technical_sandbox"})
            if prior is not None
            and prior.last_failure is FailureClass.SANDBOX_DENIAL
            else frozenset()
        )
        observation = self._service.check(
            tool,
            approvals=approvals,
            consumed_approval_ids=consumed_approval_ids,
            additional_required_approval_types=additional_required,
        )
        attempts = 1 if prior is None else prior.attempts + 1
        completed = observation.status is ToolObservationStatus.AVAILABLE
        return ExecutionCheckpoint(
            checkpoint_id=f"CHK-{digest[:16]}",
            tool_name=tool.name,
            command_digest=digest,
            context=context,
            state=CheckpointState.COMPLETED if completed else CheckpointState.BLOCKED,
            attempts=attempts,
            last_failure=observation.failure_class,
            state_change_token=state_change_token,
            observation=observation,
        )


def classify_failure(text: str) -> FailureClass:
    """Classify bounded diagnostic text without treating it as authorization."""

    folded = text.casefold()
    markers = (
        (
            FailureClass.SANDBOX_DENIAL,
            ("sandbox denied", "blocked by sandbox", "operation not permitted by sandbox"),
        ),
        (
            FailureClass.NETWORK_DENIAL,
            (
                "network is unreachable",
                "could not resolve host",
                "connection refused",
                "socket access permissions",
            ),
        ),
        (
            FailureClass.AUTHENTICATION_FAILURE,
            ("authentication failed", "not logged in", "invalid token"),
        ),
        (
            FailureClass.AUTHORIZATION_FAILURE,
            ("authorization failed", "forbidden"),
        ),
        (
            FailureClass.PERMISSION_DENIAL,
            ("permission denied", "access is denied", "winerror 5"),
        ),
        (
            FailureClass.TEST_FAILURE,
            ("test failure", "assertionerror"),
        ),
        (
            FailureClass.WORKFLOW_FAILURE,
            ("workflow failure", "github actions"),
        ),
        (
            FailureClass.EXTERNAL_SERVICE_FAILURE,
            ("service unavailable", "http 503", "temporary service failure"),
        ),
    )
    return next(
        (
            failure
            for failure, candidates in markers
            if any(marker in folded for marker in candidates)
        ),
        FailureClass.UNKNOWN_FAILURE,
    )


def _parse_tool(value: object, where: str) -> ToolDefinition:
    record = _object(value, where)
    _only_keys(
        record,
        {
            "name",
            "capability",
            "version_command",
            "version_pattern",
            "minimum_version",
            "platforms",
            "normal_scope",
            "protected_paths",
            "network",
            "optional",
            "risk",
            "technical_approval",
            "owner_approval",
            "max_attempts",
        },
        where,
    )
    name = _string(record.get("name"), f"{where}.name")
    if not _NAME.fullmatch(name):
        raise ToolContractError(f"{where}.name is invalid.")
    command = _string_tuple(
        record.get("version_command"),
        f"{where}.version_command",
    )
    _validate_command(command)
    version_pattern = _string(
        record.get("version_pattern"),
        f"{where}.version_pattern",
    )
    try:
        compiled = re.compile(version_pattern)
    except re.error as exc:
        raise ToolContractError(f"{where}.version_pattern is invalid.") from exc
    if compiled.groups != 1:
        raise ToolContractError(
            f"{where}.version_pattern must contain exactly one capture group."
        )
    minimum_value = record.get("minimum_version")
    minimum = (
        None
        if minimum_value is None
        else _parse_version(
            _string(minimum_value, f"{where}.minimum_version"),
            f"{where}.minimum_version",
        )
    )
    platforms = _string_tuple(record.get("platforms"), f"{where}.platforms")
    if any(item not in {"windows", "linux", "macos"} for item in platforms):
        raise ToolContractError(f"{where}.platforms contains an unsupported platform.")
    normal_scope = tuple(
        _safe_relative_path(item, f"{where}.normal_scope")
        for item in _string_tuple(record.get("normal_scope"), f"{where}.normal_scope")
    )
    protected_paths = tuple(
        _safe_relative_path(item, f"{where}.protected_paths")
        for item in _string_tuple(
            record.get("protected_paths"),
            f"{where}.protected_paths",
            allow_empty=True,
        )
    )
    if any(
        _paths_overlap(path, protected)
        for path in normal_scope
        for protected in protected_paths
    ):
        raise ToolContractError(
            f"{where}.normal_scope must not overlap protected_paths."
        )
    network = _object(record.get("network"), f"{where}.network")
    _only_keys(network, {"required", "destinations"}, f"{where}.network")
    network_required = _boolean(network.get("required"), f"{where}.network.required")
    destinations = _string_tuple(
        network.get("destinations"),
        f"{where}.network.destinations",
        allow_empty=True,
    )
    if network_required and not destinations:
        raise ToolContractError(
            f"{where}.network.destinations must not be empty when required."
        )
    if not network_required and destinations:
        raise ToolContractError(
            f"{where}.network.destinations must be empty when network is disabled."
        )
    normalized_destinations = tuple(
        _network_destination(item, f"{where}.network.destinations")
        for item in destinations
    )
    if len(normalized_destinations) != len(set(normalized_destinations)):
        raise ToolContractError(
            f"{where}.network.destinations must be canonically unique."
        )
    risk = _enum(RiskLevel, record.get("risk"), f"{where}.risk")
    owner_approval = _enum(
        ApprovalRequirement,
        record.get("owner_approval"),
        f"{where}.owner_approval",
    )
    if risk is RiskLevel.PROHIBITED and owner_approval is not ApprovalRequirement.PROHIBITED:
        raise ToolContractError(
            f"{where}.owner_approval must be prohibited for prohibited risk."
        )
    if network_required and owner_approval is not ApprovalRequirement.REQUIRED:
        raise ToolContractError(
            f"{where}.owner_approval must be required when network is required."
        )
    max_attempts = _integer(record.get("max_attempts"), f"{where}.max_attempts")
    if max_attempts not in {1, 2}:
        raise ToolContractError(f"{where}.max_attempts must be 1 or 2.")
    return ToolDefinition(
        name=name,
        capability=_string(record.get("capability"), f"{where}.capability"),
        version_command=command,
        version_pattern=version_pattern,
        minimum_version=minimum,
        platforms=platforms,
        normal_scope=normal_scope,
        protected_paths=protected_paths,
        network_required=network_required,
        network_destinations=normalized_destinations,
        optional=_boolean(record.get("optional"), f"{where}.optional"),
        risk=risk,
        technical_approval=_enum(
            ApprovalRequirement,
            record.get("technical_approval"),
            f"{where}.technical_approval",
        ),
        owner_approval=owner_approval,
        max_attempts=max_attempts,
    )


def _validate_command(command: tuple[str, ...]) -> None:
    executable = command[0].casefold()
    if (
        "/" in executable
        or "\\" in executable
        or ":" in executable
        or executable in _SHELLS
        or executable in _DESTRUCTIVE_EXECUTABLES
        or executable.endswith((".bat", ".cmd"))
        or not re.fullmatch(r"[a-z0-9][a-z0-9_.+-]{0,63}", executable)
    ):
        raise ToolContractError("version_command executable is unsafe.")
    for argument in command[1:]:
        if (
            len(argument) > 256
            or "\x00" in argument
            or "\r" in argument
            or "\n" in argument
            or argument.casefold() in _PROHIBITED_ARGUMENTS
        ):
            raise ToolContractError("version_command contains an unsafe argument.")
        if argument.casefold() in {"-c", "/c"}:
            raise ToolContractError("version_command cannot execute inline code.")
        parsed = urlsplit(argument)
        if parsed.scheme or parsed.netloc:
            raise ToolContractError(
                "version_command cannot contain a network destination."
            )


def _approval_error(
    tool: ToolDefinition,
    approvals: tuple[ExecutionApproval, ...],
    *,
    now: datetime,
    consumed_approval_ids: frozenset[str],
    additional_required_approval_types: frozenset[str],
) -> str | None:
    if now.tzinfo is None:
        return "Tool approval clock must be timezone-aware."
    if not additional_required_approval_types <= {"technical_sandbox"}:
        return "An unsupported additional approval requirement was supplied."
    approval_ids = [approval.approval_id for approval in approvals]
    if len(approval_ids) != len(set(approval_ids)):
        return "Execution approval identifiers must be unique."
    for approval in approvals:
        integrity_error = _approval_integrity_error(approval, now)
        if integrity_error is not None:
            return integrity_error
    if tool.owner_approval is ApprovalRequirement.PROHIBITED:
        return "Owner policy prohibits this tool."
    if (
        "technical_sandbox" in additional_required_approval_types
        and tool.technical_approval
        not in {ApprovalRequirement.MAY_BE_REQUIRED, ApprovalRequirement.REQUIRED}
    ):
        return "Tool policy does not permit a technical sandbox retry."
    if (
        tool.network_required
        and tool.owner_approval is not ApprovalRequirement.REQUIRED
    ):
        return "Network tools require an explicit Owner approval contract."
    requirements = (
        ("owner", tool.owner_approval),
        ("technical_sandbox", tool.technical_approval),
    )
    for approval_type, requirement in requirements:
        if (
            requirement is not ApprovalRequirement.REQUIRED
            and approval_type not in additional_required_approval_types
        ):
            continue
        matches = [
            approval
            for approval in approvals
            if approval.approval_type == approval_type
            and _approval_matches_tool(approval, tool)
        ]
        if len(matches) != 1:
            return f"Exact {approval_type} approval is required."
        if matches[0].approval_id in consumed_approval_ids:
            return f"Execution approval {matches[0].approval_id} is already consumed."
    return None


def _observation(
    tool: ToolDefinition,
    status: ToolObservationStatus,
    failure: FailureClass,
    detail: str,
    *,
    execution_mode: str = "not_executed",
    approval_ids: tuple[str, ...] = (),
) -> ToolObservation:
    return ToolObservation(
        tool_name=tool.name,
        status=status,
        failure_class=failure,
        detail=detail,
        version=None,
        exit_code=None,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        execution_mode=execution_mode,
        approval_ids=approval_ids,
    )


def _applied_approval_ids(
    tool: ToolDefinition,
    approvals: tuple[ExecutionApproval, ...],
    *,
    additional_required_approval_types: frozenset[str],
) -> tuple[str, ...]:
    required_types = {
        approval_type
        for approval_type, requirement in (
            ("owner", tool.owner_approval),
            ("technical_sandbox", tool.technical_approval),
        )
        if requirement is ApprovalRequirement.REQUIRED
    }
    required_types.update(additional_required_approval_types)
    return tuple(
        sorted(
            approval.approval_id
            for approval in approvals
            if approval.approval_type in required_types
            and _approval_matches_tool(approval, tool)
        )
    )


def _approval_matches_tool(
    approval: ExecutionApproval,
    tool: ToolDefinition,
) -> bool:
    return (
        approval.status == "approved"
        and approval.action == _APPROVAL_ACTION
        and approval.tool_name == tool.name
        and approval.command == tool.version_command
        and approval.network_destinations == tool.network_destinations
        and approval.normal_scope == tool.normal_scope
        and approval.protected_paths == tool.protected_paths
        and approval.risk is tool.risk
    )


def _approval_integrity_error(
    approval: ExecutionApproval,
    now: datetime,
) -> str | None:
    expected_authority = _APPROVAL_AUTHORITIES.get(approval.approval_type)
    if (
        approval.schema_version != "1.0"
        or not _APPROVAL_ID.fullmatch(approval.approval_id)
        or expected_authority is None
        or approval.approved_by != expected_authority
        or approval.action != _APPROVAL_ACTION
        or approval.status != "approved"
        or not approval.reversible
        or approval.lifetime != _APPROVAL_LIFETIME
        or approval.max_executions != 1
        or not isinstance(approval.risk, RiskLevel)
        or approval.risk is RiskLevel.PROHIBITED
        or not isinstance(approval.approved_at, datetime)
        or not isinstance(approval.expires_at, datetime)
        or approval.approved_at.tzinfo is None
        or approval.expires_at.tzinfo is None
        or approval.approved_at > now
        or approval.expires_at <= approval.approved_at
        or approval.expires_at <= now
    ):
        return "Execution approval provenance, lifetime, or validity is invalid."
    try:
        if (
            not _NAME.fullmatch(approval.tool_name)
            or not _string(approval.rationale, "rationale")
        ):
            return "Execution approval scope or rationale is invalid."
        _validate_command(approval.command)
        normal_scope = tuple(
            _safe_relative_path(item, "normal_scope")
            for item in approval.normal_scope
        )
        protected_paths = tuple(
            _safe_relative_path(item, "protected_paths")
            for item in approval.protected_paths
        )
        destinations = tuple(
            _network_destination(item, "network_destinations")
            for item in approval.network_destinations
        )
    except (ToolContractError, TypeError):
        return "Execution approval scope or rationale is invalid."
    if (
        normal_scope != approval.normal_scope
        or protected_paths != approval.protected_paths
        or destinations != approval.network_destinations
        or len(destinations) != len(set(destinations))
        or any(
            _paths_overlap(path, protected)
            for path in normal_scope
            for protected in protected_paths
        )
    ):
        return "Execution approval scope or rationale is invalid."
    return None


def _load_consumption_records(
    path: Path,
    *,
    now: datetime,
) -> tuple[tuple[str, str, str], ...]:
    if not path.exists():
        return ()
    if path.is_symlink() or is_reparse_point(path) or not path.is_file():
        raise ToolContractError(
            "Approval consumption store must be a regular, unlinked file."
        )
    try:
        if path.stat().st_size > _MAX_CONSUMPTION_BYTES:
            raise ToolContractError(
                "Approval consumption store exceeds the size limit."
            )
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise ToolContractError(
            "Approval consumption store could not be read."
        ) from exc
    if "\x00" in text:
        raise ToolContractError("Approval consumption store contains NUL.")
    try:
        decoded: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolContractError(
            "Approval consumption store is not valid JSON."
        ) from exc
    root = _object(decoded, "Approval consumption store")
    _only_keys(
        root,
        {"schema_version", "consumed"},
        "Approval consumption store",
    )
    if _string(root.get("schema_version"), "schema_version") != "1.0":
        raise ToolContractError(
            "Approval consumption schema_version must be 1.0."
        )
    raw_records = root.get("consumed")
    if not isinstance(raw_records, list):
        raise ToolContractError(
            "Approval consumption records must be an array."
        )
    if len(raw_records) > _MAX_CONSUMPTION_RECORDS:
        raise ToolContractError(
            "Approval consumption store exceeds the record limit."
        )
    records: list[tuple[str, str, str]] = []
    for index, value in enumerate(raw_records):
        where = f"consumed[{index}]"
        record = _object(value, where)
        _only_keys(
            record,
            {"approval_id", "scope_digest", "claimed_at"},
            where,
        )
        approval_id = _string(record.get("approval_id"), f"{where}.approval_id")
        digest = _string(record.get("scope_digest"), f"{where}.scope_digest")
        claimed_at_text = _string(record.get("claimed_at"), f"{where}.claimed_at")
        if not _APPROVAL_ID.fullmatch(approval_id) or not _SHA256.fullmatch(digest):
            raise ToolContractError(
                "Approval consumption record identifiers are invalid."
            )
        if _timestamp(claimed_at_text, f"{where}.claimed_at") > now:
            raise ToolContractError(
                "Approval consumption time cannot be in the future."
            )
        records.append((approval_id, digest, claimed_at_text))
    if len(records) != len({item[0] for item in records}):
        raise ToolContractError(
            "Approval consumption identifiers must be unique."
        )
    if records != sorted(records):
        raise ToolContractError(
            "Approval consumption records must be deterministically ordered."
        )
    return tuple(records)


def _registry_consumption_root(registry_path: Path) -> Path:
    if registry_path.is_symlink() or is_reparse_point(registry_path):
        raise ToolContractError(
            "Tool Registry must be regular before approval consumption."
        )
    try:
        resolved = registry_path.resolve(strict=True)
    except OSError as exc:
        raise ToolContractError(
            "Tool Registry path cannot anchor approval consumption."
        ) from exc
    if (
        not resolved.is_file()
        or resolved.is_symlink()
        or is_reparse_point(resolved)
    ):
        raise ToolContractError(
            "Tool Registry must be regular before approval consumption."
        )
    start = resolved.parent
    for candidate in (start, *start.parents):
        git_marker = candidate / ".git"
        marker_present = (
            git_marker.exists()
            or git_marker.is_symlink()
            or is_reparse_point(git_marker)
        )
        if marker_present:
            if (
                git_marker.is_symlink()
                or is_reparse_point(git_marker)
                or not (git_marker.is_dir() or git_marker.is_file())
            ):
                raise ToolContractError(
                    "Tool Registry Git boundary is unsafe."
                )
            return candidate
        state_directory = candidate / ".sdaqf"
        project_marker = state_directory / "project.json"
        project_present = (
            project_marker.exists()
            or project_marker.is_symlink()
            or is_reparse_point(project_marker)
        )
        if project_present:
            if (
                state_directory.is_symlink()
                or is_reparse_point(state_directory)
                or not state_directory.is_dir()
                or project_marker.is_symlink()
                or is_reparse_point(project_marker)
                or not project_marker.is_file()
            ):
                raise ToolContractError(
                    "Tool Registry project boundary is unsafe."
                )
            return candidate
    return start


def _approval_scope_digest(approval: ExecutionApproval) -> str:
    payload = {
        "schema_version": approval.schema_version,
        "approval_id": approval.approval_id,
        "approval_type": approval.approval_type,
        "action": approval.action,
        "tool_name": approval.tool_name,
        "command": list(approval.command),
        "network_destinations": list(approval.network_destinations),
        "normal_scope": list(approval.normal_scope),
        "protected_paths": list(approval.protected_paths),
        "risk": approval.risk.value,
        "status": approval.status,
        "rationale": approval.rationale,
        "reversible": approval.reversible,
        "approved_by": approval.approved_by,
        "approved_at": approval.approved_at.isoformat(),
        "expires_at": approval.expires_at.isoformat(),
        "lifetime": approval.lifetime,
        "max_executions": approval.max_executions,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest().upper()


def _status_for_failure(failure: FailureClass) -> ToolObservationStatus:
    if failure in {FailureClass.PERMISSION_DENIAL, FailureClass.SANDBOX_DENIAL}:
        return ToolObservationStatus.PERMISSION_DENIED
    if failure is FailureClass.NETWORK_DENIAL:
        return ToolObservationStatus.BLOCKED
    return ToolObservationStatus.NON_ZERO_EXIT


def _sanitize_output(value: str) -> str:
    redacted = _SECRET.sub("[REDACTED]", value)
    return _PERSONAL_PATH.sub("[REDACTED-PATH]/", redacted)


def _parse_version(value: str, where: str) -> tuple[int, ...]:
    if not _VERSION.fullmatch(value):
        raise ToolContractError(f"{where} must be a numeric dotted version.")
    return tuple(int(part) for part in value.split("."))


def _timestamp(value: object, where: str) -> datetime:
    text = _string(value, where)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ToolContractError(f"{where} must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ToolContractError(f"{where} must include a timezone.")
    return parsed


def _padded_version(value: tuple[int, ...]) -> tuple[int, ...]:
    return (*value, *(0 for _ in range(4 - len(value))))


def _network_destination(value: str, where: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ToolContractError(
            f"{where} must contain canonical HTTPS origins."
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise ToolContractError(f"{where} must contain canonical HTTPS origins.")
    hostname = parsed.hostname.casefold()
    return f"https://{hostname}"


def _safe_relative_path(value: str, where: str) -> str:
    if (
        len(value) > 240
        or "\\" in value
        or ":" in value
        or value.startswith(("/", "~"))
    ):
        raise ToolContractError(f"{where} must be a safe relative path.")
    parts = PurePosixPath(value).parts
    if not parts or any(
        part in {"", ".", ".."}
        or part.endswith((" ", "."))
        or part.casefold().split(".", maxsplit=1)[0] in _WINDOWS_RESERVED
        for part in parts
    ):
        raise ToolContractError(f"{where} must be a safe relative path.")
    return "/".join(parts)


def _paths_overlap(first: str, second: str) -> bool:
    first_parts = PurePosixPath(first.casefold()).parts
    second_parts = PurePosixPath(second.casefold()).parts
    common = min(len(first_parts), len(second_parts))
    return first_parts[:common] == second_parts[:common]


def _current_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _load_object(path: Path, label: str) -> dict[str, object]:
    if path.suffix.casefold() != ".json":
        raise ToolContractError(f"{label} must be a JSON file.")
    if path.is_symlink() or is_reparse_point(path) or not path.is_file():
        raise ToolContractError(f"{label} must be a regular, unlinked file.")
    try:
        if path.stat().st_size > _MAX_REGISTRY_BYTES:
            raise ToolContractError(f"{label} exceeds the size limit.")
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise ToolContractError(f"{label} could not be read.") from exc
    if "\x00" in text:
        raise ToolContractError(f"{label} contains NUL.")
    try:
        decoded: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolContractError(f"{label} is not valid JSON.") from exc
    return _object(decoded, label)


def _object(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ToolContractError(f"{where} must be an object.")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise ToolContractError(f"{where} keys must be strings.")
    return {cast(str, key): item for key, item in raw.items()}


def _array(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise ToolContractError(f"{where} must be an array.")
    if len(value) > _MAX_ITEMS:
        raise ToolContractError(f"{where} exceeds the item limit.")
    return cast(list[object], value)


def _only_keys(
    value: dict[str, object],
    allowed: set[str],
    where: str,
) -> None:
    missing = allowed - set(value)
    extra = set(value) - allowed
    if missing:
        raise ToolContractError(
            f"{where} is missing fields: {', '.join(sorted(missing))}."
        )
    if extra:
        raise ToolContractError(
            f"{where} contains unknown fields: {', '.join(sorted(extra))}."
        )


def _string(value: object, where: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_TEXT
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise ToolContractError(
            f"{where} must be a bounded non-empty single-line string."
        )
    return value


def _string_tuple(
    value: object,
    where: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    items = _array(value, where)
    parsed = tuple(_string(item, where) for item in items)
    if not allow_empty and not parsed:
        raise ToolContractError(f"{where} must not be empty.")
    if len(parsed) != len(set(item.casefold() for item in parsed)):
        raise ToolContractError(f"{where} values must be unique.")
    return parsed


def _integer(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolContractError(f"{where} must be an integer.")
    return value


def _boolean(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise ToolContractError(f"{where} must be a boolean.")
    return value


def _enum[T: str](
    enum_type: type[T],
    value: object,
    where: str,
) -> T:
    text = _string(value, where)
    try:
        return enum_type(text)
    except ValueError as exc:
        raise ToolContractError(f"{where} is unsupported.") from exc
