"""Explicit non-destructive M4 migrations for legacy registry contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.application.contracts import (
    ContractError,
    array_value,
    boolean_value,
    load_json_object,
    object_value,
    only_keys,
    parse_json_object_bytes,
    path_free_text,
    safe_relative_path,
    sha256,
    string_tuple,
    string_value,
    timestamp,
)
from sdaqf.application.orchestration import (
    OrchestrationContractError,
    load_agent_registry,
    validate_agent_tool_references,
)
from sdaqf.application.tooling import (
    ToolContractError,
    load_tool_registry,
    load_tool_registry_snapshot,
)
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.migrations import MigrationApproval, MigrationResult
from sdaqf.domain.tooling import ToolRegistry

_CONTRACTS = {"agent-registry", "tool-registry"}
_SLUG = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_PLATFORMS = {"windows", "linux", "macos"}
_RISKS = {"low", "medium", "high", "prohibited"}
_TECHNICAL_APPROVALS = {"not_required", "may_be_required", "required"}
_OWNER_APPROVALS = {"not_required", "required", "prohibited"}
_SANDBOX_STATES = {
    "AVAILABLE",
    "UNAVAILABLE",
    "PERMISSION_DENIED",
    "NOT_CHECKED",
}
_VERSION_PROFILES: dict[tuple[str, ...], str] = {
    ("git", "--version"): r"git version ([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
    ("python", "--version"): r"Python ([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
    ("python", "-V"): r"Python ([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
    ("python3", "--version"): r"Python ([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
    ("python3", "-V"): r"Python ([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
    ("z3", "--version"): r"Z3 version ([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
}


class MigrationService:
    """Migrate one supported 1.0 registry to a validated new 2.0 file."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def migrate(
        self,
        *,
        root: Path,
        contract: str,
        source: Path,
        output: Path,
        approval: Path,
        tool_registry: Path | None = None,
        source_version: str,
        target_version: str,
    ) -> MigrationResult:
        """Transform, validate, and exclusively publish one migration output."""

        if contract not in _CONTRACTS:
            raise ContractError("Migration contract is unsupported.")
        if source_version != "1.0" or target_version != "2.0":
            raise ContractError("Only explicit version 1.0 to 2.0 migration is supported.")
        resolved_root = _regular_root(root)
        resolved_source = _source_path(resolved_root, source)
        raw_output = output if output.is_absolute() else resolved_root / output
        try:
            if raw_output.resolve(strict=True) == resolved_source:
                raise ContractError("Migration source and output must be distinct.")
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ContractError("Migration output could not be resolved.") from exc
        resolved_output = _output_path(resolved_root, output)
        if resolved_source == resolved_output:
            raise ContractError("Migration source and output must be distinct.")
        source_bytes = _read_source(resolved_source)
        source_digest = hashlib.sha256(source_bytes).hexdigest().upper()
        display = resolved_output.relative_to(resolved_root).as_posix()
        tools, tool_registry_path, tool_registry_sha256 = _load_companion_tools(
            root=resolved_root,
            contract=contract,
            path=tool_registry,
        )
        migration_approval = _load_migration_approval(
            root=resolved_root,
            path=approval,
            contract=contract,
            source_sha256=source_digest,
            output_path=display,
            tool_registry_path=tool_registry_path,
            tool_registry_sha256=tool_registry_sha256,
            source_version=source_version,
            target_version=target_version,
            now=self._clock(),
        )
        payload = parse_json_object_bytes(
            source_bytes,
            f"legacy {contract}",
            maximum_bytes=1_000_000,
        )
        if contract == "agent-registry":
            migrated, inserted, warnings = _migrate_agent_registry(payload)
        else:
            migrated, inserted, warnings = _migrate_tool_registry(payload)
        output_bytes = (
            json.dumps(migrated, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _validate_and_publish(
            contract=contract,
            output=resolved_output,
            output_bytes=output_bytes,
            tool_registry=tools,
        )
        try:
            if _read_source(resolved_source) != source_bytes:
                raise ContractError("Migration source changed during migration.")
        except ContractError:
            _remove_failed_output(resolved_output)
            raise
        return MigrationResult(
            approval_id=migration_approval.approval_id,
            contract=contract,
            source_version=source_version,
            target_version=target_version,
            source_sha256=source_digest,
            tool_registry_path=tool_registry_path,
            tool_registry_sha256=tool_registry_sha256,
            output_sha256=hashlib.sha256(output_bytes).hexdigest().upper(),
            inserted_defaults=inserted,
            warnings=warnings,
            output_path=display,
            rollback=f"Remove only the newly created {display} file.",
        )


def _migrate_agent_registry(
    root: dict[str, object],
) -> tuple[dict[str, object], tuple[str, ...], tuple[str, ...]]:
    only_keys(root, {"schema_version", "agents"}, "legacy Agent Registry")
    if string_value(root.get("schema_version"), "schema_version", maximum=10) != "1.0":
        raise ContractError("Legacy Agent Registry schema_version must be 1.0.")
    raw_agents = array_value(root.get("agents"), "agents", maximum=64)
    if not raw_agents:
        raise ContractError("Legacy Agent Registry agents must not be empty.")
    migrated: list[dict[str, object]] = []
    role_ids: list[str] = []
    for index, raw in enumerate(raw_agents):
        where = f"agents[{index}]"
        item = object_value(raw, where)
        only_keys(
            item,
            {
                "role",
                "responsibilities",
                "inputs",
                "outputs",
                "tools",
                "prohibited_actions",
            },
            where,
        )
        display_name = path_free_text(
            item.get("role"),
            f"{where}.role",
            maximum=500,
        )
        role_id = _role_slug(display_name)
        tools = _slug_tuple(item.get("tools"), f"{where}.tools")
        migrated.append(
            {
                "role_id": role_id,
                "display_name": display_name,
                "responsibilities": list(
                    _nonempty_text_tuple(
                        item.get("responsibilities"),
                        f"{where}.responsibilities",
                    )
                ),
                "inputs": list(
                    _nonempty_text_tuple(item.get("inputs"), f"{where}.inputs")
                ),
                "outputs": list(
                    _nonempty_text_tuple(item.get("outputs"), f"{where}.outputs")
                ),
                "tools": list(tools),
                "prohibited_actions": list(
                    _nonempty_text_tuple(
                        item.get("prohibited_actions"),
                        f"{where}.prohibited_actions",
                    )
                ),
                "problem_types": ["discovery"],
                "scales": ["small"],
                "max_risk": "low",
                "parallelism": ["sequential"],
                "can_write": False,
                "independent_reviewer": False,
            }
        )
        role_ids.append(role_id)
    if len(role_ids) != len(set(role_ids)):
        raise ContractError("Legacy roles collide after portable slug migration.")
    migrated.sort(key=lambda item: str(item["role_id"]))
    inserted = (
        "agents[].can_write=false",
        "agents[].display_name=legacy role",
        "agents[].independent_reviewer=false",
        "agents[].max_risk=low",
        "agents[].parallelism=[sequential]",
        "agents[].problem_types=[discovery]",
        "agents[].role_id=portable role slug",
        "agents[].scales=[small]",
    )
    warnings = (
        "Legacy Agent Registry capability is conservatively restricted to read-only "
        "small sequential discovery until an Owner reviews the migrated fields.",
    )
    return {"schema_version": "2.0", "agents": migrated}, inserted, warnings


def _migrate_tool_registry(
    root: dict[str, object],
) -> tuple[dict[str, object], tuple[str, ...], tuple[str, ...]]:
    only_keys(root, {"schema_version", "tools"}, "legacy Tool Registry")
    if string_value(root.get("schema_version"), "schema_version", maximum=10) != "1.0":
        raise ContractError("Legacy Tool Registry schema_version must be 1.0.")
    raw_tools = array_value(root.get("tools"), "tools", maximum=64)
    if not raw_tools:
        raise ContractError("Legacy Tool Registry tools must not be empty.")
    migrated: list[dict[str, object]] = []
    names: list[str] = []
    for index, raw in enumerate(raw_tools):
        where = f"tools[{index}]"
        item = object_value(raw, where)
        only_keys(
            item,
            {
                "name",
                "capability",
                "command",
                "platforms",
                "normal_scope",
                "network",
                "sandbox_status",
                "technical_approval",
                "owner_approval",
                "risk",
            },
            where,
        )
        name = _slug(item.get("name"), f"{where}.name")
        command = _command(item.get("command"), f"{where}.command")
        pattern = _VERSION_PROFILES.get(command)
        if pattern is None:
            raise ContractError(
                f"{where}.command has no safe deterministic version profile."
            )
        platforms = string_tuple(
            item.get("platforms"),
            f"{where}.platforms",
            minimum=1,
            maximum=3,
        )
        if not set(platforms) <= _PLATFORMS:
            raise ContractError(f"{where}.platforms contains an unsupported platform.")
        normal_scope = tuple(
            safe_relative_path(value, f"{where}.normal_scope[{scope_index}]")
            for scope_index, value in enumerate(
                array_value(
                    item.get("normal_scope"),
                    f"{where}.normal_scope",
                    maximum=64,
                )
            )
        )
        if not normal_scope or len(normal_scope) != len(set(normal_scope)):
            raise ContractError(f"{where}.normal_scope must be non-empty and unique.")
        network = object_value(item.get("network"), f"{where}.network")
        only_keys(network, {"required", "destinations"}, f"{where}.network")
        network_required = boolean_value(
            network.get("required"),
            f"{where}.network.required",
        )
        destinations = string_tuple(
            network.get("destinations"),
            f"{where}.network.destinations",
            maximum=64,
        )
        if network_required != bool(destinations):
            raise ContractError(f"{where}.network is ambiguous.")
        if destinations:
            raise ContractError(
                f"{where}.network migration would preserve external capability; "
                "manual review is required."
            )
        sandbox_status = string_value(
            item.get("sandbox_status"),
            f"{where}.sandbox_status",
            maximum=30,
        )
        if sandbox_status not in _SANDBOX_STATES:
            raise ContractError(f"{where}.sandbox_status is unsupported.")
        technical = string_value(
            item.get("technical_approval"),
            f"{where}.technical_approval",
            maximum=30,
        )
        owner = string_value(
            item.get("owner_approval"),
            f"{where}.owner_approval",
            maximum=30,
        )
        risk = string_value(item.get("risk"), f"{where}.risk", maximum=20)
        if technical not in _TECHNICAL_APPROVALS:
            raise ContractError(f"{where}.technical_approval is unsupported.")
        if owner not in _OWNER_APPROVALS:
            raise ContractError(f"{where}.owner_approval is unsupported.")
        if risk not in _RISKS:
            raise ContractError(f"{where}.risk is unsupported.")
        if risk == "prohibited" and owner != "prohibited":
            raise ContractError(
                f"{where}.owner_approval must remain prohibited for prohibited risk."
            )
        migrated.append(
            {
                "name": name,
                "capability": path_free_text(
                    item.get("capability"),
                    f"{where}.capability",
                    maximum=500,
                ),
                "version_command": list(command),
                "version_pattern": pattern,
                "minimum_version": None,
                "platforms": sorted(platforms),
                "normal_scope": sorted(normal_scope),
                "protected_paths": [".git"],
                "network": {"required": False, "destinations": []},
                "optional": False,
                "risk": risk,
                "technical_approval": technical,
                "owner_approval": owner,
                "max_attempts": 1,
            }
        )
        names.append(name)
    if len(names) != len(set(names)):
        raise ContractError("Legacy tool names must be unique.")
    migrated.sort(key=lambda item: str(item["name"]))
    inserted = (
        "tools[].max_attempts=1",
        "tools[].minimum_version=null",
        "tools[].network=offline-only",
        "tools[].optional=false",
        "tools[].protected_paths=[.git]",
        "tools[].version_pattern=known safe profile",
    )
    warnings = (
        "Legacy sandbox_status is observation data and is not migrated into policy.",
        "Legacy tools remain required, offline, single-attempt capabilities until "
        "an Owner reviews optionality and minimum versions.",
    )
    return {"schema_version": "2.0", "tools": migrated}, inserted, warnings


def _regular_root(root: Path) -> Path:
    if root.is_symlink() or is_reparse_point(root):
        raise ContractError("Migration root must be a regular directory.")
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ContractError("Migration root could not be resolved.") from exc
    if not resolved.is_dir() or resolved.is_symlink() or is_reparse_point(resolved):
        raise ContractError("Migration root must be a regular directory.")
    return resolved


def _source_path(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    _reject_lexical_links(root, candidate, include_leaf=True)
    if candidate.is_symlink() or is_reparse_point(candidate):
        raise ContractError("Migration source must be a regular file below the root.")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ContractError("Migration source could not be resolved.") from exc
    if (
        not resolved.is_relative_to(root)
        or not resolved.is_file()
        or resolved.suffix != ".json"
        or resolved.is_symlink()
        or is_reparse_point(resolved)
    ):
        raise ContractError(
            "Migration source must be a lowercase .json regular file below the root."
        )
    relative = safe_relative_path(
        resolved.relative_to(root).as_posix(),
        "migration source",
    )
    if Path(relative).parts[0].casefold() == ".git":
        raise ContractError("Migration source cannot be inside .git.")
    _reject_linked_ancestors(root, resolved)
    return resolved


def _output_path(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    _reject_lexical_links(root, candidate, include_leaf=False)
    if candidate.is_symlink() or is_reparse_point(candidate):
        raise ContractError("Migration output must be a new JSON file below the root.")
    try:
        parent = candidate.parent.resolve(strict=True)
        resolved = parent / candidate.name
    except OSError as exc:
        raise ContractError("Migration output parent could not be resolved.") from exc
    if (
        not resolved.is_relative_to(root)
        or resolved.suffix != ".json"
        or resolved.exists()
        or resolved.is_symlink()
        or is_reparse_point(resolved)
    ):
        raise ContractError(
            "Migration output must be a new JSON file with a lowercase .json suffix "
            "below the root."
        )
    relative = safe_relative_path(
        resolved.relative_to(root).as_posix(),
        "migration output",
    )
    if Path(relative).parts[0].casefold() == ".git":
        raise ContractError("Migration output cannot be inside .git.")
    _reject_linked_ancestors(root, parent)
    return resolved


def _reject_linked_ancestors(root: Path, path: Path) -> None:
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink() or is_reparse_point(current):
            raise ContractError("Migration path contains a link or reparse point.")


def _reject_lexical_links(
    root: Path,
    candidate: Path,
    *,
    include_leaf: bool,
) -> None:
    lexical = Path(os.path.abspath(candidate))
    if not lexical.is_relative_to(root):
        raise ContractError("Migration path is outside the root.")
    parts = lexical.relative_to(root).parts
    inspected = parts if include_leaf else parts[:-1]
    current = root
    for part in inspected:
        current = current / part
        if current.is_symlink() or is_reparse_point(current):
            raise ContractError("Migration path contains a link or reparse point.")


def _read_source(path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ContractError("Migration source could not be read.") from exc
    if len(data) > 1_000_000:
        raise ContractError("Migration source exceeds the size limit.")
    return data


def _validate_and_publish(
    *,
    contract: str,
    output: Path,
    output_bytes: bytes,
    tool_registry: ToolRegistry | None,
) -> None:
    temporary: Path | None = None
    descriptor = -1
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{output.stem}.",
            suffix=".json",
            dir=output.parent,
        )
        temporary = Path(raw_path)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(output_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        if contract == "agent-registry":
            agents = load_agent_registry(temporary)
            if tool_registry is None:
                raise ContractError(
                    "Agent Registry migration requires a companion Tool Registry."
                )
            validate_agent_tool_references(agents, tool_registry)
        else:
            load_tool_registry(temporary)
        os.link(temporary, output)
    except OrchestrationContractError as exc:
        raise ContractError(
            "Migrated Agent Registry contains an unknown tool reference."
        ) from exc
    except (OSError, ToolContractError) as exc:
        raise ContractError("Migrated output could not be validated and published.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load_companion_tools(
    *,
    root: Path,
    contract: str,
    path: Path | None,
) -> tuple[ToolRegistry | None, str | None, str | None]:
    if contract == "tool-registry":
        if path is not None:
            raise ContractError(
                "Tool Registry migration does not accept a companion registry."
            )
        return None, None, None
    if path is None:
        raise ContractError(
            "Agent Registry migration requires --tool-registry."
        )
    resolved = _source_path(root, path)
    content = _read_source(resolved)
    try:
        registry = load_tool_registry_snapshot(content)
    except ToolContractError as exc:
        raise ContractError("Companion Tool Registry is invalid.") from exc
    return (
        registry,
        resolved.relative_to(root).as_posix(),
        hashlib.sha256(content).hexdigest().upper(),
    )


def _load_migration_approval(
    *,
    root: Path,
    path: Path,
    contract: str,
    source_sha256: str,
    output_path: str,
    tool_registry_path: str | None,
    tool_registry_sha256: str | None,
    source_version: str,
    target_version: str,
    now: datetime,
) -> MigrationApproval:
    if now.tzinfo is None:
        raise ValueError("Migration approval clock must be timezone-aware.")
    record = load_json_object(
        _source_path(root, path),
        "migration approval",
        maximum_bytes=64 * 1024,
    )
    only_keys(
        record,
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
        "migration approval",
    )
    if string_value(
        record.get("schema_version"),
        "migration approval.schema_version",
        maximum=10,
    ) != "1.0":
        raise ContractError("Migration approval schema_version must be 1.0.")
    approval_id = string_value(
        record.get("approval_id"),
        "migration approval.approval_id",
        maximum=68,
    )
    if not re.fullmatch(r"APR-[A-Z0-9][A-Z0-9-]{2,63}", approval_id):
        raise ContractError("Migration approval_id is invalid.")
    exact_values = {
        "approval_type": "owner",
        "action": "Migrate one registry schema",
        "risk": "medium",
        "status": "approved",
        "approved_by": "Owner",
        "lifetime": "until_expiry",
    }
    for field, expected in exact_values.items():
        if string_value(
            record.get(field),
            f"migration approval.{field}",
            maximum=100,
        ) != expected:
            raise ContractError(f"Migration approval {field} is invalid.")
    path_free_text(
        record.get("rationale"),
        "migration approval.rationale",
        maximum=500,
    )
    if not boolean_value(
        record.get("reversible"),
        "migration approval.reversible",
    ):
        raise ContractError("Migration approval must record reversible=true.")
    approved_at = timestamp(
        record.get("approved_at"),
        "migration approval.approved_at",
    )
    expires_at = timestamp(
        record.get("expires_at"),
        "migration approval.expires_at",
    )
    approved_time = datetime.fromisoformat(approved_at)
    expires_time = datetime.fromisoformat(expires_at)
    if approved_time > now or expires_time <= approved_time or expires_time <= now:
        raise ContractError("Migration approval is not currently valid.")
    scope = object_value(record.get("scope"), "migration approval.scope")
    only_keys(
        scope,
        {
            "contract",
            "source_sha256",
            "output_path",
            "tool_registry_path",
            "tool_registry_sha256",
            "source_version",
            "target_version",
        },
        "migration approval.scope",
    )
    expected_scope = {
        "contract": contract,
        "source_sha256": source_sha256,
        "output_path": output_path,
        "tool_registry_path": tool_registry_path,
        "tool_registry_sha256": tool_registry_sha256,
        "source_version": source_version,
        "target_version": target_version,
    }
    parsed_scope = {
        "contract": string_value(
            scope.get("contract"),
            "migration approval.scope.contract",
            maximum=30,
        ),
        "source_sha256": sha256(
            scope.get("source_sha256"),
            "migration approval.scope.source_sha256",
        ),
        "output_path": safe_relative_path(
            scope.get("output_path"),
            "migration approval.scope.output_path",
        ),
        "tool_registry_path": (
            None
            if scope.get("tool_registry_path") is None
            else safe_relative_path(
                scope.get("tool_registry_path"),
                "migration approval.scope.tool_registry_path",
            )
        ),
        "tool_registry_sha256": (
            None
            if scope.get("tool_registry_sha256") is None
            else sha256(
                scope.get("tool_registry_sha256"),
                "migration approval.scope.tool_registry_sha256",
            )
        ),
        "source_version": string_value(
            scope.get("source_version"),
            "migration approval.scope.source_version",
            maximum=10,
        ),
        "target_version": string_value(
            scope.get("target_version"),
            "migration approval.scope.target_version",
            maximum=10,
        ),
    }
    if parsed_scope != expected_scope:
        raise ContractError("Migration approval scope does not match the operation.")
    conditions = object_value(
        record.get("conditions"),
        "migration approval.conditions",
    )
    only_keys(
        conditions,
        {"source_preserved", "exclusive_output"},
        "migration approval.conditions",
    )
    if not boolean_value(
        conditions.get("source_preserved"),
        "migration approval.conditions.source_preserved",
    ) or not boolean_value(
        conditions.get("exclusive_output"),
        "migration approval.conditions.exclusive_output",
    ):
        raise ContractError("Migration approval conditions are invalid.")
    return MigrationApproval(
        approval_id=approval_id,
        contract=contract,
        source_sha256=source_sha256,
        output_path=output_path,
        tool_registry_path=tool_registry_path,
        tool_registry_sha256=tool_registry_sha256,
        source_version=source_version,
        target_version=target_version,
        approved_at=approved_at,
        expires_at=expires_at,
    )


def _remove_failed_output(output: Path) -> None:
    try:
        output.unlink()
    except OSError as exc:
        raise ContractError(
            "Migration failed and named-output cleanup could not be confirmed."
        ) from exc


def _role_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not _SLUG.fullmatch(slug):
        raise ContractError("Legacy role cannot be converted to a portable role_id.")
    return slug


def _slug(value: object, where: str) -> str:
    parsed = string_value(value, where, maximum=64)
    if not _SLUG.fullmatch(parsed):
        raise ContractError(f"{where} is not a portable slug.")
    return parsed


def _slug_tuple(value: object, where: str) -> tuple[str, ...]:
    parsed = tuple(
        _slug(item, f"{where}[{index}]")
        for index, item in enumerate(array_value(value, where, maximum=64))
    )
    if not parsed or len(parsed) != len(set(parsed)):
        raise ContractError(f"{where} must be non-empty and unique.")
    return parsed


def _nonempty_text_tuple(value: object, where: str) -> tuple[str, ...]:
    parsed = tuple(
        path_free_text(item, f"{where}[{index}]", maximum=500)
        for index, item in enumerate(array_value(value, where, maximum=64))
    )
    if not parsed or len(parsed) != len(set(parsed)):
        raise ContractError(f"{where} must be non-empty and unique.")
    return parsed


def _command(value: object, where: str) -> tuple[str, ...]:
    if value is None:
        raise ContractError(f"{where} cannot be null for deterministic migration.")
    parsed = tuple(
        string_value(item, f"{where}[{index}]", maximum=256)
        for index, item in enumerate(array_value(value, where, maximum=64))
    )
    if not parsed:
        raise ContractError(f"{where} must not be empty.")
    return parsed
