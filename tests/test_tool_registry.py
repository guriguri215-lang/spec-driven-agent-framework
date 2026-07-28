from pathlib import Path

import pytest

from sdaqf.application.tooling import ToolContractError, load_tool_registry
from tests.m2_helpers import load_example, m2_example, write_json


def test_tool_registry_records_version_optional_scope_and_approval() -> None:
    registry = load_tool_registry(m2_example("tool-registry.json"))

    assert registry.schema_version == "2.0"
    assert registry.by_name("python").minimum_version == (3, 12)  # type: ignore[union-attr]
    assert registry.by_name("z3").optional is True  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(schema_version="1.0"), "migration"),
        (lambda value: value["tools"].append(value["tools"][0]), "unique"),
        (
            lambda value: value["tools"][0].update(version_command="git --version"),
            "array",
        ),
        (
            lambda value: value["tools"][0].update(version_command=["cmd", "/c"]),
            "unsafe",
        ),
        (
            lambda value: value["tools"][0].update(
                version_command=["python", "-m", "pip", "install"]
            ),
            "unsafe",
        ),
        (
            lambda value: value["tools"][0].update(
                normal_scope=["src"], protected_paths=["src/private"]
            ),
            "overlap",
        ),
        (
            lambda value: value["tools"][0].update(
                network={"required": False, "destinations": ["https://example.com"]}
            ),
            "must be empty",
        ),
        (
            lambda value: value["tools"][0].update(
                version_pattern="git version [0-9.]+"
            ),
            "exactly one",
        ),
        (
            lambda value: value["tools"][0].update(
                version_pattern="([invalid"
            ),
            "invalid",
        ),
        (
            lambda value: value["tools"][0].update(minimum_version="latest"),
            "numeric dotted",
        ),
        (
            lambda value: value["tools"][0].update(platforms=["plan9"]),
            "unsupported platform",
        ),
        (
            lambda value: value["tools"][0].update(
                network={"required": True, "destinations": []}
            ),
            "must not be empty",
        ),
        (
            lambda value: value["tools"][0].update(
                network={
                    "required": True,
                    "destinations": ["https://example.com"],
                }
            ),
            "owner_approval must be required",
        ),
        (
            lambda value: value["tools"][0].update(
                network={
                    "required": True,
                    "destinations": ["https://example.com:invalid"],
                }
            ),
            "canonical HTTPS",
        ),
        (
            lambda value: value["tools"][0].update(
                network={
                    "required": True,
                    "destinations": [
                        "https://EXAMPLE.com",
                        "https://example.com:443/",
                    ],
                }
            ),
            "canonically unique",
        ),
        (
            lambda value: value["tools"][0].update(normal_scope=["CON/file"]),
            "safe relative",
        ),
        (
            lambda value: value["tools"][0].update(
                risk="prohibited",
                owner_approval="required",
            ),
            "must be prohibited",
        ),
        (
            lambda value: value["tools"][0].update(max_attempts=3),
            "must be 1 or 2",
        ),
        (
            lambda value: value["tools"][0].update(version_command=["rm", "--version"]),
            "unsafe",
        ),
        (
            lambda value: value["tools"][0].update(
                version_command=["python", "-c", "pass"]
            ),
            "inline code",
        ),
        (
            lambda value: value["tools"][0].update(
                version_command=["tool", "https://example.com"]
            ),
            "network destination",
        ),
    ),
)
def test_tool_registry_rejects_unsafe_or_inconsistent_contract(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    value = load_example("tool-registry.json")
    assert callable(mutation)
    mutation(value)

    with pytest.raises(ToolContractError, match=message):
        load_tool_registry(write_json(tmp_path / "tools.json", value))


def test_tool_registry_rejects_empty_or_non_object_contract(tmp_path: Path) -> None:
    empty = load_example("tool-registry.json")
    empty["tools"] = []
    non_object = tmp_path / "tools.json"
    non_object.write_text("[]", encoding="utf-8")

    with pytest.raises(ToolContractError, match="must not be empty"):
        load_tool_registry(write_json(tmp_path / "empty.json", empty))
    with pytest.raises(ToolContractError, match="object"):
        load_tool_registry(non_object)
