from pathlib import Path

import pytest

from sdaqf.application.orchestration import (
    OrchestrationContractError,
    load_agent_registry,
    validate_agent_tool_references,
)
from sdaqf.application.tooling import load_tool_registry
from tests.m2_helpers import load_example, m2_example, write_json


def test_m2_agent_registry_is_strict_and_cross_referenced() -> None:
    agents = load_agent_registry(m2_example("agent-registry.json"))
    tools = load_tool_registry(m2_example("tool-registry.json"))

    validate_agent_tool_references(agents, tools)

    assert agents.schema_version == "2.0"
    assert [item.role_id for item in agents.agents] == sorted(
        item.role_id for item in agents.agents
    )
    assert agents.by_role("independent-reviewer").independent_reviewer is True  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(schema_version="1.0"), "migration"),
        (lambda value: value["agents"].append(value["agents"][0]), "unique"),
        (lambda value: value["agents"][0].update(role_id="BAD ROLE"), "invalid"),
        (lambda value: value["agents"][0].pop("outputs"), "missing"),
        (lambda value: value["agents"][0].update(extra=True), "unknown"),
    ),
)
def test_agent_registry_rejects_invalid_contracts(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    value = load_example("agent-registry.json")
    assert callable(mutation)
    mutation(value)

    with pytest.raises(OrchestrationContractError, match=message):
        load_agent_registry(write_json(tmp_path / "agents.json", value))


def test_agent_registry_rejects_unknown_tool_reference(tmp_path: Path) -> None:
    value = load_example("agent-registry.json")
    value["agents"][0]["tools"] = ["unknown-tool"]
    agents = load_agent_registry(write_json(tmp_path / "agents.json", value))
    tools = load_tool_registry(m2_example("tool-registry.json"))

    with pytest.raises(OrchestrationContractError, match="unknown tools"):
        validate_agent_tool_references(agents, tools)


def test_agent_registry_rejects_non_json_or_malformed_file(tmp_path: Path) -> None:
    text = tmp_path / "agents.txt"
    text.write_text("{}", encoding="utf-8")
    malformed = tmp_path / "agents.json"
    malformed.write_text("{", encoding="utf-8")

    with pytest.raises(OrchestrationContractError, match="JSON file"):
        load_agent_registry(text)
    with pytest.raises(OrchestrationContractError, match="valid JSON"):
        load_agent_registry(malformed)
