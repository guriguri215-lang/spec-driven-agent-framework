"""Atomic, bounded M2 checkpoint persistence and resume validation."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import cast

from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.tooling import (
    CheckpointState,
    ExecutionCheckpoint,
    ExecutionContext,
    FailureClass,
    ToolObservation,
    ToolObservationStatus,
)

_MAX_CHECKPOINT_BYTES = 128 * 1024
_ID = re.compile(r"^CHK-[0-9A-F]{16}$")
_TOOL = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_SHA256 = re.compile(r"^[0-9A-F]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_PLAN_VERSION = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$")
_SECRET = re.compile(
    r"(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)
_PERSONAL_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]\x55sers[\\/]|/\x55sers/|/\x68ome/[^/\s]+/)",
    re.IGNORECASE,
)
_TRANSITIONS: dict[CheckpointState, frozenset[CheckpointState]] = {
    CheckpointState.PLANNED: frozenset(
        {CheckpointState.READY, CheckpointState.REJECTED}
    ),
    CheckpointState.READY: frozenset(
        {CheckpointState.RUNNING, CheckpointState.BLOCKED, CheckpointState.REJECTED}
    ),
    CheckpointState.RUNNING: frozenset(
        {
            CheckpointState.BLOCKED,
            CheckpointState.VERIFICATION,
            CheckpointState.REJECTED,
        }
    ),
    CheckpointState.BLOCKED: frozenset(
        {CheckpointState.READY, CheckpointState.REJECTED, CheckpointState.SUPERSEDED}
    ),
    CheckpointState.VERIFICATION: frozenset(
        {CheckpointState.COMPLETED, CheckpointState.BLOCKED, CheckpointState.REJECTED}
    ),
    CheckpointState.COMPLETED: frozenset({CheckpointState.SUPERSEDED}),
    CheckpointState.REJECTED: frozenset({CheckpointState.SUPERSEDED}),
    CheckpointState.SUPERSEDED: frozenset(),
}


class CheckpointContractError(ValueError):
    """One bounded checkpoint, transition, or resume failure."""


class CheckpointStore:
    """Persist checkpoints atomically within one allowed root."""

    def __init__(self, allowed_root: Path) -> None:
        self._allowed_root = allowed_root.resolve()

    def save(self, path: Path, checkpoint: ExecutionCheckpoint) -> None:
        """Atomically publish one bounded, redaction-safe checkpoint."""

        target = self._target(path)
        raw_text = json.dumps(checkpoint.to_dict(), indent=2, sort_keys=True) + "\n"
        encoded = raw_text.encode("utf-8")
        if len(encoded) > _MAX_CHECKPOINT_BYTES:
            raise CheckpointContractError("Checkpoint exceeds the size limit.")
        if _SECRET.search(raw_text) or _PERSONAL_PATH.search(raw_text):
            raise CheckpointContractError(
                "Checkpoint contains a secret or personal absolute path."
            )
        validated = _parse_checkpoint_object(checkpoint.to_dict())
        text = json.dumps(validated.to_dict(), indent=2, sort_keys=True) + "\n"
        encoded = text.encode("utf-8")
        temporary: Path | None = None
        backup_temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if target.exists():
                backup_temporary = target.with_name(f".{target.name}.bak.tmp")
                shutil.copyfile(target, backup_temporary)
                os.replace(backup_temporary, self._backup(target))
                backup_temporary = None
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if backup_temporary is not None:
                backup_temporary.unlink(missing_ok=True)

    def load(self, path: Path) -> ExecutionCheckpoint:
        """Load the primary checkpoint or recover from its last backup."""

        target = self._target(path)
        errors: list[CheckpointContractError] = []
        for candidate in (target, self._backup(target)):
            if not candidate.exists():
                continue
            try:
                return _load_checkpoint_file(candidate)
            except CheckpointContractError as exc:
                errors.append(exc)
        if errors:
            raise CheckpointContractError(
                "Primary and backup checkpoints are invalid."
            ) from errors[-1]
        raise CheckpointContractError("Checkpoint does not exist.")

    def _target(self, path: Path) -> Path:
        if path.suffix.casefold() != ".json":
            raise CheckpointContractError("Checkpoint must use a JSON filename.")
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self._allowed_root):
            raise CheckpointContractError(
                "Checkpoint must stay within the allowed root."
            )
        if (
            not resolved.parent.is_dir()
            or is_reparse_point(resolved.parent)
            or path.is_symlink()
        ):
            raise CheckpointContractError(
                "Checkpoint parent and target must be regular and unlinked."
            )
        return resolved

    @staticmethod
    def _backup(path: Path) -> Path:
        return path.with_name(f"{path.name}.bak")


def validate_resume(
    checkpoint: ExecutionCheckpoint,
    context: ExecutionContext,
) -> None:
    """Reject every resume-sensitive context mismatch."""

    mismatches = [
        label
        for label, previous, current in (
            ("plan version", checkpoint.context.plan_version, context.plan_version),
            (
                "specification digest",
                checkpoint.context.specification_digest,
                context.specification_digest,
            ),
            ("Git HEAD", checkpoint.context.git_head, context.git_head),
            (
                "worktree digest",
                checkpoint.context.worktree_digest,
                context.worktree_digest,
            ),
        )
        if previous != current
    ]
    if mismatches:
        raise CheckpointContractError(
            "Resume context mismatch: " + ", ".join(mismatches) + "."
        )


def transition_checkpoint(
    checkpoint: ExecutionCheckpoint,
    state: CheckpointState,
) -> ExecutionCheckpoint:
    """Apply one explicit valid state transition."""

    if state not in _TRANSITIONS[checkpoint.state]:
        raise CheckpointContractError(
            f"Invalid checkpoint transition: {checkpoint.state.value} -> {state.value}."
        )
    return ExecutionCheckpoint(
        checkpoint_id=checkpoint.checkpoint_id,
        tool_name=checkpoint.tool_name,
        command_digest=checkpoint.command_digest,
        context=checkpoint.context,
        state=state,
        attempts=checkpoint.attempts,
        last_failure=checkpoint.last_failure,
        state_change_token=checkpoint.state_change_token,
        observation=checkpoint.observation,
    )


def _load_checkpoint_file(path: Path) -> ExecutionCheckpoint:
    if path.is_symlink() or is_reparse_point(path) or not path.is_file():
        raise CheckpointContractError("Checkpoint must be a regular, unlinked file.")
    try:
        if path.stat().st_size > _MAX_CHECKPOINT_BYTES:
            raise CheckpointContractError("Checkpoint exceeds the size limit.")
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise CheckpointContractError("Checkpoint could not be read.") from exc
    if _SECRET.search(text) or _PERSONAL_PATH.search(text):
        raise CheckpointContractError(
            "Checkpoint contains a secret or personal absolute path."
        )
    try:
        decoded: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CheckpointContractError("Checkpoint is not valid JSON.") from exc
    return _parse_checkpoint_object(decoded)


def _parse_checkpoint_object(decoded: object) -> ExecutionCheckpoint:
    root = _object(decoded, "checkpoint")
    _only_keys(
        root,
        {
            "schema_version",
            "checkpoint_id",
            "tool_name",
            "command_digest",
            "context",
            "state",
            "attempts",
            "last_failure",
            "state_change_token",
            "observation",
        },
        "checkpoint",
    )
    if _string(root.get("schema_version"), "schema_version") != "1.0":
        raise CheckpointContractError("Checkpoint schema_version must be 1.0.")
    checkpoint_id = _string(root.get("checkpoint_id"), "checkpoint_id")
    tool_name = _string(root.get("tool_name"), "tool_name")
    digest = _string(root.get("command_digest"), "command_digest")
    if not _ID.fullmatch(checkpoint_id) or not _TOOL.fullmatch(tool_name):
        raise CheckpointContractError("Checkpoint identifiers are invalid.")
    if not _SHA256.fullmatch(digest):
        raise CheckpointContractError("command_digest must be SHA-256.")
    context_raw = _object(root.get("context"), "context")
    _only_keys(
        context_raw,
        {
            "plan_version",
            "specification_digest",
            "git_head",
            "worktree_digest",
        },
        "context",
    )
    context = ExecutionContext(
        plan_version=_string(context_raw.get("plan_version"), "context.plan_version"),
        specification_digest=_string(
            context_raw.get("specification_digest"),
            "context.specification_digest",
        ),
        git_head=_string(context_raw.get("git_head"), "context.git_head"),
        worktree_digest=_string(
            context_raw.get("worktree_digest"),
            "context.worktree_digest",
        ),
    )
    if not _PLAN_VERSION.fullmatch(context.plan_version):
        raise CheckpointContractError("context.plan_version is invalid.")
    if not _SHA256.fullmatch(context.specification_digest) or not _SHA256.fullmatch(
        context.worktree_digest
    ):
        raise CheckpointContractError("Context digests must be SHA-256.")
    if not _GIT_SHA.fullmatch(context.git_head):
        raise CheckpointContractError("context.git_head must be a lowercase Git SHA.")
    attempts = _integer(root.get("attempts"), "attempts")
    if not 0 <= attempts <= 2:
        raise CheckpointContractError("attempts must be between 0 and 2.")
    state_token_value = root.get("state_change_token")
    state_token = (
        None
        if state_token_value is None
        else _string(state_token_value, "state_change_token")
    )
    observation_value = root.get("observation")
    observation = (
        None
        if observation_value is None
        else _parse_observation(observation_value)
    )
    state = _enum(CheckpointState, root.get("state"), "state")
    last_failure = _enum(
        FailureClass,
        root.get("last_failure"),
        "last_failure",
    )
    if attempts == 0 and (
        observation is not None or last_failure is not FailureClass.NONE
    ):
        raise CheckpointContractError(
            "A zero-attempt checkpoint cannot contain execution evidence."
        )
    if attempts > 0 and observation is None:
        raise CheckpointContractError(
            "An attempted checkpoint must contain an observation."
        )
    if observation is not None:
        if observation.tool_name != tool_name:
            raise CheckpointContractError(
                "Checkpoint and observation tool names must match."
            )
        if observation.failure_class is not last_failure:
            raise CheckpointContractError(
                "Checkpoint and observation failure classes must match."
            )
    if state is CheckpointState.COMPLETED and (
        observation is None
        or observation.status is not ToolObservationStatus.AVAILABLE
        or last_failure is not FailureClass.NONE
    ):
        raise CheckpointContractError(
            "A completed checkpoint requires a successful observation."
        )
    if (
        state is CheckpointState.BLOCKED
        and observation is not None
        and observation.status is ToolObservationStatus.AVAILABLE
    ):
        raise CheckpointContractError(
            "A blocked checkpoint cannot contain a successful observation."
        )
    return ExecutionCheckpoint(
        checkpoint_id=checkpoint_id,
        tool_name=tool_name,
        command_digest=digest,
        context=context,
        state=state,
        attempts=attempts,
        last_failure=last_failure,
        state_change_token=state_token,
        observation=observation,
    )


def _parse_observation(value: object) -> ToolObservation:
    record = _object(value, "observation")
    _only_keys(
        record,
        {
            "tool_name",
            "status",
            "failure_class",
            "detail",
            "version",
            "exit_code",
            "stdout",
            "stderr",
            "stdout_truncated",
            "stderr_truncated",
            "duration_ms",
            "execution_mode",
            "approval_ids",
        },
        "observation",
    )
    version_value = record.get("version")
    exit_value = record.get("exit_code")
    duration_value = record.get("duration_ms")
    duration = (
        None
        if duration_value is None
        else _integer(duration_value, "observation.duration_ms")
    )
    if duration is not None and not 0 <= duration <= 86_400_000:
        raise CheckpointContractError(
            "observation.duration_ms must be bounded and non-negative."
        )
    execution_mode = _string(
        record.get("execution_mode"),
        "observation.execution_mode",
    )
    if execution_mode not in {"normal", "approved", "denied", "not_executed"}:
        raise CheckpointContractError(
            "observation.execution_mode is unsupported."
        )
    approval_ids = _string_tuple(
        record.get("approval_ids"),
        "observation.approval_ids",
    )
    return ToolObservation(
        tool_name=_string(record.get("tool_name"), "observation.tool_name"),
        status=_enum(
            ToolObservationStatus,
            record.get("status"),
            "observation.status",
        ),
        failure_class=_enum(
            FailureClass,
            record.get("failure_class"),
            "observation.failure_class",
        ),
        detail=_string(record.get("detail"), "observation.detail"),
        version=(
            None
            if version_value is None
            else _string(version_value, "observation.version")
        ),
        exit_code=(
            None
            if exit_value is None
            else _integer(exit_value, "observation.exit_code")
        ),
        stdout=_bounded_text(record.get("stdout"), "observation.stdout"),
        stderr=_bounded_text(record.get("stderr"), "observation.stderr"),
        stdout_truncated=_boolean(
            record.get("stdout_truncated"),
            "observation.stdout_truncated",
        ),
        stderr_truncated=_boolean(
            record.get("stderr_truncated"),
            "observation.stderr_truncated",
        ),
        duration_ms=duration,
        execution_mode=execution_mode,
        approval_ids=approval_ids,
    )


def _object(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CheckpointContractError(f"{where} must be an object.")
    raw = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in raw):
        raise CheckpointContractError(f"{where} keys must be strings.")
    return {cast(str, key): item for key, item in raw.items()}


def _only_keys(
    value: dict[str, object],
    allowed: set[str],
    where: str,
) -> None:
    missing = allowed - set(value)
    extra = set(value) - allowed
    if missing:
        raise CheckpointContractError(
            f"{where} is missing fields: {', '.join(sorted(missing))}."
        )
    if extra:
        raise CheckpointContractError(
            f"{where} contains unknown fields: {', '.join(sorted(extra))}."
        )


def _string(value: object, where: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 4_096
        or "\x00" in value
    ):
        raise CheckpointContractError(f"{where} must be a bounded string.")
    return value


def _bounded_text(value: object, where: str) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 8_192:
        raise CheckpointContractError(f"{where} exceeds the evidence limit.")
    return value


def _string_tuple(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 16:
        raise CheckpointContractError(f"{where} must be a bounded array.")
    parsed = tuple(_string(item, where) for item in value)
    if len(parsed) != len(set(parsed)):
        raise CheckpointContractError(f"{where} values must be unique.")
    return parsed


def _integer(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CheckpointContractError(f"{where} must be an integer.")
    return value


def _boolean(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise CheckpointContractError(f"{where} must be a boolean.")
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
        raise CheckpointContractError(f"{where} is unsupported.") from exc
