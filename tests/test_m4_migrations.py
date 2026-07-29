from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import pytest

from sdaqf.application.contracts import ContractError, parse_json_object_bytes
from sdaqf.application.migrations import MigrationService
from sdaqf.application.orchestration import load_agent_registry
from sdaqf.application.tooling import (
    ToolContractError,
    load_tool_registry,
    load_tool_registry_snapshot,
)
from sdaqf.cli import main
from sdaqf.domain.migrations import MigrationResult
from tests.schema_validation import LocalSchemaValidator, SchemaValidationError


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def migration_examples() -> Path:
    return repository_root() / "examples" / "m4-migration"


def copy_fixture(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    shutil.copy2(migration_examples() / name, path)
    return path


def write_json(path: Path, payload: object) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def write_migration_approval(
    *,
    root: Path,
    contract: str,
    source: Path,
    output: Path,
    source_version: str,
    target_version: str,
    tool_registry: Path | None = None,
) -> Path:
    resolved_source = source if source.is_absolute() else root / source
    source_digest = (
        sha256(resolved_source.read_bytes()).hexdigest().upper()
        if resolved_source.is_file()
        else "A" * 64
    )
    resolved_output = output if output.is_absolute() else root / output
    try:
        output_path = resolved_output.relative_to(root).as_posix()
    except ValueError:
        output_path = "outside.json"
    if tool_registry is None:
        tool_registry_path = None
        tool_registry_sha256 = None
    else:
        resolved_tools = (
            tool_registry if tool_registry.is_absolute() else root / tool_registry
        )
        tool_registry_path = resolved_tools.relative_to(root).as_posix()
        tool_registry_sha256 = sha256(
            resolved_tools.read_bytes()
        ).hexdigest().upper()
    return write_json(
        root / "migration-approval.json",
        {
            "schema_version": "1.0",
            "approval_id": "APR-M4-MIGRATION-TEST",
            "approval_type": "owner",
            "action": "Migrate one registry schema",
            "scope": {
                "contract": contract,
                "source_sha256": source_digest,
                "output_path": output_path,
                "tool_registry_path": tool_registry_path,
                "tool_registry_sha256": tool_registry_sha256,
                "source_version": source_version,
                "target_version": target_version,
            },
            "risk": "medium",
            "status": "approved",
            "rationale": "Test-only exact migration approval.",
            "reversible": True,
            "approved_by": "Owner",
            "approved_at": "2026-07-29T10:00:00+09:00",
            "expires_at": "2030-07-29T10:00:00+09:00",
            "lifetime": "until_expiry",
            "conditions": {
                "source_preserved": True,
                "exclusive_output": True,
            },
        },
    )


def approved_migrate(
    *,
    root: Path,
    contract: str,
    source: Path,
    output: Path,
    source_version: str,
    target_version: str,
    tool_registry: Path | None = None,
) -> MigrationResult:
    if contract == "agent-registry" and tool_registry is None:
        tool_registry = root / "companion-tool-registry.json"
        if not tool_registry.exists():
            shutil.copy2(
                migration_examples() / "tool-registry-v2.json",
                tool_registry,
            )
    approval = write_migration_approval(
        root=root,
        contract=contract,
        source=source,
        output=output,
        source_version=source_version,
        target_version=target_version,
        tool_registry=tool_registry,
    )
    return MigrationService(
        clock=lambda: datetime.fromisoformat("2026-07-29T12:00:00+09:00")
    ).migrate(
        root=root,
        contract=contract,
        source=source,
        output=output,
        approval=approval,
        tool_registry=tool_registry,
        source_version=source_version,
        target_version=target_version,
    )


@pytest.mark.parametrize(
    ("contract", "source_name", "expected_name"),
    [
        ("agent-registry", "agent-registry-v1.json", "agent-registry-v2.json"),
        ("tool-registry", "tool-registry-v1.json", "tool-registry-v2.json"),
    ],
)
def test_registry_migration_is_deterministic_validated_and_non_destructive(
    tmp_path: Path,
    contract: str,
    source_name: str,
    expected_name: str,
) -> None:
    source = copy_fixture(tmp_path, source_name)
    before = source.read_bytes()
    output = tmp_path / "migrated.json"
    result = approved_migrate(
        root=tmp_path,
        contract=contract,
        source=source,
        output=output,
        source_version="1.0",
        target_version="2.0",
    )

    assert source.read_bytes() == before
    assert json.loads(output.read_text(encoding="utf-8")) == json.loads(
        (migration_examples() / expected_name).read_text(encoding="utf-8")
    )
    assert result.source_preserved
    assert result.output_path == "migrated.json"
    assert result.rollback == "Remove only the newly created migrated.json file."
    assert result.inserted_defaults
    assert result.warnings
    if contract == "agent-registry":
        assert load_agent_registry(output).schema_version == "2.0"
        assert result.tool_registry_path == "companion-tool-registry.json"
        assert result.tool_registry_sha256 is not None
    else:
        assert load_tool_registry(output).schema_version == "2.0"
        assert result.tool_registry_path is None
        assert result.tool_registry_sha256 is None
    LocalSchemaValidator(repository_root() / "schemas").validate(
        "migration-result.schema.json",
        result.to_dict(),
    )

    second = tmp_path / "migrated-second.json"
    second_result = approved_migrate(
        root=tmp_path,
        contract=contract,
        source=source,
        output=second,
        source_version="1.0",
        target_version="2.0",
    )
    assert second.read_bytes() == output.read_bytes()
    assert second_result.output_sha256 == result.output_sha256


def test_migration_refuses_existing_output_and_preserves_bytes(tmp_path: Path) -> None:
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    output = write_json(tmp_path / "existing.json", {"sentinel": True})
    source_before = source.read_bytes()
    output_before = output.read_bytes()

    with pytest.raises(ContractError, match="new JSON"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=source,
            output=output,
            source_version="1.0",
            target_version="2.0",
        )
    assert source.read_bytes() == source_before
    assert output.read_bytes() == output_before


@pytest.mark.parametrize(
    ("contract", "source_version", "target_version", "message"),
    [
        ("unknown", "1.0", "2.0", "unsupported"),
        ("agent-registry", "2.0", "2.0", "1.0 to 2.0"),
        ("agent-registry", "1.0", "3.0", "1.0 to 2.0"),
    ],
)
def test_migration_rejects_unsupported_routes(
    tmp_path: Path,
    contract: str,
    source_version: str,
    target_version: str,
    message: str,
) -> None:
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    with pytest.raises(ContractError, match=message):
        approved_migrate(
            root=tmp_path,
            contract=contract,
            source=source,
            output=tmp_path / "output.json",
            source_version=source_version,
            target_version=target_version,
        )
    assert not (tmp_path / "output.json").exists()


@pytest.mark.parametrize(
    ("name", "mutate", "message"),
    [
        (
            "agent-registry-v1.json",
            lambda value: value["agents"].append(
                {
                    **value["agents"][0],
                    "role": "Legacy-Reviewer",
                }
            ),
            "collide",
        ),
        (
            "agent-registry-v1.json",
            lambda value: value["agents"][0].update({"tools": []}),
            "non-empty",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update(
                {"command": ["custom", "--version"]}
            ),
            "no safe deterministic",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update(
                {
                    "network": {
                        "required": True,
                        "destinations": ["https://example.invalid"],
                    }
                }
            ),
            "external capability",
        ),
    ],
)
def test_migration_fails_closed_without_output(
    tmp_path: Path,
    name: str,
    mutate: object,
    message: str,
) -> None:
    payload = json.loads((migration_examples() / name).read_text(encoding="utf-8"))
    mutator = mutate
    assert callable(mutator)
    mutator(payload)
    source = write_json(tmp_path / name, payload)
    before = source.read_bytes()
    contract = "agent-registry" if name.startswith("agent") else "tool-registry"

    with pytest.raises(ContractError, match=message):
        approved_migrate(
            root=tmp_path,
            contract=contract,
            source=source,
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )
    assert source.read_bytes() == before
    assert not (tmp_path / "output.json").exists()


def test_migration_rejects_duplicate_keys_and_source_output_alias(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":"1.0","schema_version":"1.0","agents":[]}',
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="duplicate"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=duplicate,
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    with pytest.raises(ContractError, match="distinct"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=source,
            output=source,
            source_version="1.0",
            target_version="2.0",
        )


def test_companion_tool_registry_snapshot_rejects_duplicate_keys() -> None:
    with pytest.raises(ToolContractError, match="snapshot is invalid"):
        load_tool_registry_snapshot(
            b'{"schema_version":"2.0","schema_version":"2.0","tools":[]}'
        )


def test_migration_rejects_link_input_when_supported(
    tmp_path: Path,
) -> None:
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    linked = tmp_path / "linked.json"
    try:
        os.symlink(source, linked)
    except (OSError, NotImplementedError):
        pytest.skip("The environment does not permit symbolic-link creation.")
    with pytest.raises(ContractError, match="regular file"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=linked,
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )


def test_migration_rejects_linked_parent_when_supported(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    shutil.copy2(
        migration_examples() / "agent-registry-v1.json",
        real / "source.json",
    )
    linked = tmp_path / "linked"
    try:
        os.symlink(real, linked, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("The environment does not permit directory-link creation.")
    with pytest.raises(ContractError, match="link"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=linked / "source.json",
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    with pytest.raises(ContractError, match="link"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=source,
            output=linked / "output.json",
            source_version="1.0",
            target_version="2.0",
        )


def test_schema_migrate_cli_creates_only_named_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    tools = copy_fixture(tmp_path, "tool-registry-v2.json")
    approval = write_migration_approval(
        root=tmp_path,
        contract="agent-registry",
        source=source,
        output=Path("migrated.json"),
        source_version="1.0",
        target_version="2.0",
        tool_registry=tools,
    )
    monkeypatch.chdir(tmp_path)
    result = main(
        [
            "schema",
            "migrate",
            "--contract",
            "agent-registry",
            "--from-version",
            "1.0",
            "--to-version",
            "2.0",
            "agent-registry-v1.json",
            "--output",
            "migrated.json",
            "--approval",
            approval.name,
            "--tool-registry",
            tools.name,
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["source_preserved"] is True
    assert load_agent_registry(tmp_path / "migrated.json").schema_version == "2.0"

    assert (
        main(
            [
                "schema",
                "migrate",
                "--contract",
                "agent-registry",
                "--from-version",
                "1.0",
                "--to-version",
                "2.0",
                "agent-registry-v1.json",
                "--output",
                "migrated.json",
                "--approval",
                approval.name,
                "--tool-registry",
                tools.name,
            ]
        )
        == 2
    )
    assert "schema migration is invalid" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "mutation", "message"),
    [
        (
            "agent-registry-v1.json",
            lambda value: value.update({"schema_version": "2.0"}),
            "schema_version",
        ),
        (
            "agent-registry-v1.json",
            lambda value: value.update({"agents": []}),
            "agents must not be empty",
        ),
        (
            "agent-registry-v1.json",
            lambda value: value["agents"][0].update({"role": "---"}),
            "portable role_id",
        ),
        (
            "agent-registry-v1.json",
            lambda value: value["agents"][0].update({"responsibilities": []}),
            "non-empty",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value.update({"schema_version": "2.0"}),
            "schema_version",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value.update({"tools": []}),
            "tools must not be empty",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update({"platforms": ["plan9"]}),
            "unsupported platform",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update({"normal_scope": []}),
            "normal_scope",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update(
                {"network": {"required": True, "destinations": []}}
            ),
            "network is ambiguous",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update({"sandbox_status": "UNKNOWN"}),
            "sandbox_status",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update(
                {"technical_approval": "prohibited"}
            ),
            "technical_approval",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update(
                {"owner_approval": "may_be_required"}
            ),
            "owner_approval",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update({"risk": "critical"}),
            "risk",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update(
                {"risk": "prohibited", "owner_approval": "required"}
            ),
            "remain prohibited",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update({"name": "Bad Name"}),
            "portable slug",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update({"command": None}),
            "cannot be null",
        ),
        (
            "tool-registry-v1.json",
            lambda value: value["tools"][0].update({"command": []}),
            "must not be empty",
        ),
    ],
)
def test_migration_rejects_invalid_legacy_contract_fields(
    tmp_path: Path,
    name: str,
    mutation: object,
    message: str,
) -> None:
    payload = json.loads((migration_examples() / name).read_text(encoding="utf-8"))
    mutator = mutation
    assert callable(mutator)
    mutator(payload)
    source = write_json(tmp_path / name, payload)
    contract = "agent-registry" if name.startswith("agent") else "tool-registry"
    with pytest.raises(ContractError, match=message):
        approved_migrate(
            root=tmp_path,
            contract=contract,
            source=source,
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )
    assert not (tmp_path / "output.json").exists()


def test_migration_rejects_duplicate_tool_names(tmp_path: Path) -> None:
    payload = json.loads(
        (migration_examples() / "tool-registry-v1.json").read_text(encoding="utf-8")
    )
    payload["tools"].append(dict(payload["tools"][0]))
    source = write_json(tmp_path / "tools.json", payload)
    with pytest.raises(ContractError, match="names must be unique"):
        approved_migrate(
            root=tmp_path,
            contract="tool-registry",
            source=source,
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )


@pytest.mark.parametrize(
    ("source", "output", "message"),
    [
        ("missing.json", "output.json", "source could not be resolved"),
        ("agent-registry-v1.json", "missing/output.json", "output parent"),
        ("agent-registry-v1.json", "output.txt", "lowercase .json"),
        ("agent-registry-v1.json", "output.JSON", "lowercase .json"),
        ("agent-registry-v1.json", "CON.json", "portable"),
        ("agent-registry-v1.json", "../outside.json", "outside the root"),
    ],
)
def test_migration_rejects_unsafe_paths(
    tmp_path: Path,
    source: str,
    output: str,
    message: str,
) -> None:
    copy_fixture(tmp_path, "agent-registry-v1.json")
    with pytest.raises(ContractError, match=message):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=Path(source),
            output=Path(output),
            source_version="1.0",
            target_version="2.0",
        )


@pytest.mark.parametrize("suffix", [".txt", ".JSON"])
def test_migration_rejects_non_json_source_suffix(
    tmp_path: Path,
    suffix: str,
) -> None:
    source = tmp_path / f"tool-registry-v1{suffix}"
    shutil.copy2(migration_examples() / "tool-registry-v1.json", source)
    with pytest.raises(ContractError, match=r"lowercase \.json"):
        approved_migrate(
            root=tmp_path,
            contract="tool-registry",
            source=source,
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )


@pytest.mark.parametrize("suffix", [".txt", ".JSON"])
def test_agent_migration_rejects_non_json_companion_suffix(
    tmp_path: Path,
    suffix: str,
) -> None:
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    tools = tmp_path / f"tool-registry-v2{suffix}"
    shutil.copy2(migration_examples() / "tool-registry-v2.json", tools)
    with pytest.raises(ContractError, match=r"lowercase \.json"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=source,
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
            tool_registry=tools,
        )


def test_migration_publish_failure_leaves_no_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = copy_fixture(tmp_path, "agent-registry-v1.json")

    def fail_link(source_path: Path, output_path: Path) -> None:
        raise OSError("injected link failure")

    monkeypatch.setattr("sdaqf.application.migrations.os.link", fail_link)
    with pytest.raises(ContractError, match="validated and published"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=source,
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )
    assert not (tmp_path / "output.json").exists()
    assert not tuple(tmp_path.glob(".output.*.json"))


def test_migration_requires_exact_current_owner_approval(
    tmp_path: Path,
) -> None:
    source = copy_fixture(tmp_path, "tool-registry-v1.json")
    output = tmp_path / "output.json"
    with pytest.raises(ContractError, match="could not be resolved"):
        MigrationService().migrate(
            root=tmp_path,
            contract="tool-registry",
            source=source,
            output=output,
            approval=tmp_path / "missing-approval.json",
            source_version="1.0",
            target_version="2.0",
        )

    approval = write_migration_approval(
        root=tmp_path,
        contract="tool-registry",
        source=source,
        output=output,
        source_version="1.0",
        target_version="2.0",
    )
    LocalSchemaValidator(repository_root() / "schemas").validate(
        "migration-approval.schema.json",
        json.loads(approval.read_text(encoding="utf-8")),
    )
    payload = json.loads(approval.read_text(encoding="utf-8"))
    payload["scope"]["output_path"] = "different.json"
    write_json(approval, payload)
    with pytest.raises(ContractError, match="scope does not match"):
        MigrationService(
            clock=lambda: datetime.fromisoformat("2026-07-29T12:00:00+09:00")
        ).migrate(
            root=tmp_path,
            contract="tool-registry",
            source=source,
            output=output,
            approval=approval,
            source_version="1.0",
            target_version="2.0",
        )
    assert not output.exists()

    payload["scope"]["output_path"] = "output.json"
    payload["expires_at"] = "2026-07-29T11:00:00+09:00"
    write_json(approval, payload)
    with pytest.raises(ContractError, match="not currently valid"):
        MigrationService(
            clock=lambda: datetime.fromisoformat("2026-07-29T12:00:00+09:00")
        ).migrate(
            root=tmp_path,
            contract="tool-registry",
            source=source,
            output=output,
            approval=approval,
            source_version="1.0",
            target_version="2.0",
        )
    assert not output.exists()


def test_migration_schemas_bind_companion_identity_by_contract(
    tmp_path: Path,
) -> None:
    validator = LocalSchemaValidator(repository_root() / "schemas")

    agent_root = tmp_path / "agent"
    agent_root.mkdir()
    agent_source = copy_fixture(agent_root, "agent-registry-v1.json")
    agent_tools = copy_fixture(agent_root, "tool-registry-v2.json")
    agent_result = approved_migrate(
        root=agent_root,
        contract="agent-registry",
        source=agent_source,
        output=agent_root / "output.json",
        source_version="1.0",
        target_version="2.0",
        tool_registry=agent_tools,
    ).to_dict()
    agent_approval = json.loads(
        (agent_root / "migration-approval.json").read_text(encoding="utf-8")
    )

    for schema_name, original in (
        ("migration-approval.schema.json", agent_approval),
        ("migration-result.schema.json", agent_result),
    ):
        for field in ("tool_registry_path", "tool_registry_sha256"):
            payload = json.loads(json.dumps(original))
            target = payload.get("scope", payload)
            target[field] = None
            with pytest.raises(SchemaValidationError):
                validator.validate(schema_name, payload)

    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    tool_source = copy_fixture(tool_root, "tool-registry-v1.json")
    tool_result = approved_migrate(
        root=tool_root,
        contract="tool-registry",
        source=tool_source,
        output=tool_root / "output.json",
        source_version="1.0",
        target_version="2.0",
    ).to_dict()
    tool_approval = json.loads(
        (tool_root / "migration-approval.json").read_text(encoding="utf-8")
    )

    for schema_name, original in (
        ("migration-approval.schema.json", tool_approval),
        ("migration-result.schema.json", tool_result),
    ):
        for field, value in (
            ("tool_registry_path", "tool-registry-v2.json"),
            ("tool_registry_sha256", "A" * 64),
        ):
            payload = json.loads(json.dumps(original))
            target = payload.get("scope", payload)
            target[field] = value
            with pytest.raises(SchemaValidationError):
                validator.validate(schema_name, payload)


def test_agent_migration_rejects_missing_tool_reference(
    tmp_path: Path,
) -> None:
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["agents"][0]["tools"] = ["unknown-tool"]
    write_json(source, payload)
    with pytest.raises(ContractError, match="unknown tool"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=source,
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )
    assert not (tmp_path / "output.json").exists()


def test_agent_migration_approval_binds_companion_registry_snapshot(
    tmp_path: Path,
) -> None:
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    source_payload = json.loads(source.read_text(encoding="utf-8"))
    source_payload["agents"][0]["tools"] = ["unknown-tool"]
    write_json(source, source_payload)
    tools = copy_fixture(tmp_path, "tool-registry-v2.json")
    output = tmp_path / "output.json"
    approval = write_migration_approval(
        root=tmp_path,
        contract="agent-registry",
        source=source,
        output=output,
        source_version="1.0",
        target_version="2.0",
        tool_registry=tools,
    )
    tool_payload = json.loads(tools.read_text(encoding="utf-8"))
    admitted = dict(tool_payload["tools"][0])
    admitted["name"] = "unknown-tool"
    tool_payload["tools"].append(admitted)
    write_json(tools, tool_payload)

    with pytest.raises(ContractError, match="scope does not match"):
        MigrationService(
            clock=lambda: datetime.fromisoformat("2026-07-29T12:00:00+09:00")
        ).migrate(
            root=tmp_path,
            contract="agent-registry",
            source=source,
            output=output,
            approval=approval,
            tool_registry=tools,
            source_version="1.0",
            target_version="2.0",
        )
    assert not output.exists()


def test_final_source_read_failure_removes_named_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = copy_fixture(tmp_path, "tool-registry-v1.json")
    output = tmp_path / "output.json"
    from sdaqf.application import migrations

    original = migrations._read_source
    calls = 0

    def fail_second_read(path: Path) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ContractError("injected final source read failure")
        return original(path)

    monkeypatch.setattr(migrations, "_read_source", fail_second_read)
    with pytest.raises(ContractError, match="injected final"):
        approved_migrate(
            root=tmp_path,
            contract="tool-registry",
            source=source,
            output=output,
            source_version="1.0",
            target_version="2.0",
        )
    assert not output.exists()


def test_migration_parses_the_initial_source_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = copy_fixture(tmp_path, "tool-registry-v1.json")
    initial = source.read_bytes()
    changed_payload = json.loads(initial)
    changed_payload["tools"][0]["capability"] = "Changed concurrent content."
    changed = (
        json.dumps(changed_payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    from sdaqf.application import migrations

    def concurrent_aba(
        content: bytes,
        label: str,
        *,
        maximum_bytes: int,
    ) -> dict[str, object]:
        assert content == initial
        source.write_bytes(changed)
        parsed = parse_json_object_bytes(
            content,
            label,
            maximum_bytes=maximum_bytes,
        )
        source.write_bytes(initial)
        return parsed

    monkeypatch.setattr(migrations, "parse_json_object_bytes", concurrent_aba)
    output = tmp_path / "output.json"
    approved_migrate(
        root=tmp_path,
        contract="tool-registry",
        source=source,
        output=output,
        source_version="1.0",
        target_version="2.0",
    )
    migrated = json.loads(output.read_text(encoding="utf-8"))
    assert migrated["tools"][0]["capability"] == (
        "Inspect the local repository version."
    )


def test_migration_rejects_git_internal_paths(tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    shutil.copy2(
        migration_examples() / "agent-registry-v1.json",
        git_dir / "source.json",
    )
    with pytest.raises(ContractError, match=r"inside \.git"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=git_dir / "source.json",
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    with pytest.raises(ContractError, match=r"inside \.git"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=source,
            output=git_dir / "output.json",
            source_version="1.0",
            target_version="2.0",
        )


def test_migration_detects_source_change_after_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = copy_fixture(tmp_path, "agent-registry-v1.json")
    original = source.read_bytes()
    from sdaqf.application import migrations

    regular_read = migrations._read_source
    calls = 0

    def changing_read(path: Path) -> bytes:
        nonlocal calls
        if path != source:
            return regular_read(path)
        calls += 1
        return original if calls == 1 else original + b" "

    monkeypatch.setattr(
        "sdaqf.application.migrations._read_source",
        changing_read,
    )
    with pytest.raises(ContractError, match="changed during migration"):
        approved_migrate(
            root=tmp_path,
            contract="agent-registry",
            source=source,
            output=tmp_path / "output.json",
            source_version="1.0",
            target_version="2.0",
        )
    assert not (tmp_path / "output.json").exists()
