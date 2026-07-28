from pathlib import Path

import pytest

from sdaqf.application.skills import (
    LifecycleState,
    SkillContractError,
    evaluate_templates,
    load_template_registry,
    validate_skills,
)
from tests.m2_helpers import load_example, m2_example, repository_root, write_json


def valid_skill_text(name: str) -> str:
    source = (
        repository_root() / ".agents" / "skills" / "independent-review" / "SKILL.md"
    ).read_text(encoding="utf-8")
    return source.replace(
        "name: independent-review",
        f"name: {name}",
        1,
    )


def test_skill_and_template_lifecycle_is_explicit_and_deterministic() -> None:
    skills = validate_skills(
        repository_root() / ".agents" / "skills",
        selected=("independent-review",),
    )
    templates = load_template_registry(m2_example("template-registry.json"))

    evaluated = evaluate_templates(
        templates,
        framework_version="0.1.0",
        available_dependencies=("independent-review",),
        selected=("m2-agent-result",),
    )

    assert [item.name for item in skills] == sorted(item.name for item in skills)
    review = next(item for item in skills if item.name == "independent-review")
    assert review.transitions == (
        LifecycleState.DISCOVERED,
        LifecycleState.VALIDATED,
        LifecycleState.COMPATIBLE,
        LifecycleState.SELECTED,
    )
    assert evaluated[0].state is LifecycleState.SELECTED


def test_skill_name_must_match_directory(tmp_path: Path) -> None:
    skill = tmp_path / "wrong-name"
    skill.mkdir()
    content = (
        (repository_root() / ".agents" / "skills" / "independent-review" / "SKILL.md")
        .read_text(encoding="utf-8")
        .replace("name: independent-review", "name: another-name")
    )
    (skill / "SKILL.md").write_text(content, encoding="utf-8")

    with pytest.raises(SkillContractError, match="match its directory"):
        validate_skills(tmp_path)


def test_skill_requires_complete_nonempty_lifecycle_sections(tmp_path: Path) -> None:
    skill = tmp_path / "incomplete"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: incomplete\ndescription: test\n---\n\n# Incomplete\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillContractError, match="required heading"):
        validate_skills(tmp_path)


def test_template_blockers_prevent_selection() -> None:
    templates = load_template_registry(m2_example("template-registry.json"))

    blocked = evaluate_templates(
        templates,
        framework_version="0.2.0",
        available_dependencies=(),
        active_conditions=("public-release",),
    )

    assert blocked[0].state is LifecycleState.BLOCKED
    assert len(blocked[0].blockers) == 3
    with pytest.raises(SkillContractError, match="blocked template"):
        evaluate_templates(
            templates,
            framework_version="0.2.0",
            available_dependencies=(),
            active_conditions=("public-release",),
            selected=("m2-agent-result",),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("compatible_version", "latest", "compatible_version"),
        ("provenance", "pending", "resolved"),
        ("license_status", "MIT", "unsupported"),
        ("target", "../outside", "safe relative"),
        ("validated_on", "not-a-date", "validated_on"),
    ),
)
def test_template_registry_rejects_unresolved_or_unsafe_metadata(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    payload = load_example("template-registry.json")
    payload["templates"][0][field] = value

    with pytest.raises(SkillContractError, match=message):
        load_template_registry(write_json(tmp_path / "templates.json", payload))


def test_skill_discovery_rejects_empty_unknown_and_duplicate_selection(
    tmp_path: Path,
) -> None:
    with pytest.raises(SkillContractError, match="contains no Skills"):
        validate_skills(tmp_path)

    skill = tmp_path / "bounded-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        valid_skill_text("bounded-skill"),
        encoding="utf-8",
    )
    with pytest.raises(SkillContractError, match="must be unique"):
        validate_skills(
            tmp_path,
            selected=("bounded-skill", "bounded-skill"),
        )
    with pytest.raises(SkillContractError, match="unavailable"):
        validate_skills(tmp_path, selected=("missing-skill",))


@pytest.mark.parametrize(
    ("name", "transform", "message"),
    (
        ("con", lambda text: text, "safe slug"),
        (
            "missing-frontmatter",
            lambda text: text.removeprefix("---\n"),
            "start with front matter",
        ),
        (
            "unclosed-frontmatter",
            lambda text: text.replace("---\n\n#", "\n#", 1),
            "not closed",
        ),
        (
            "invalid-frontmatter",
            lambda text: text.replace("description:", "description", 1),
            "invalid line",
        ),
        (
            "duplicate-key",
            lambda text: text.replace(
                "description:",
                "name: duplicate-key\ndescription:",
                1,
            ),
            "keys must be unique",
        ),
        (
            "extra-key",
            lambda text: text.replace(
                "description:",
                "owner: repository\ndescription:",
                1,
            ),
            "only name and description",
        ),
        (
            "empty-section",
            lambda text: text.split("## Risks\n", maxsplit=1)[0] + "## Risks\n",
            "must not be empty",
        ),
    ),
)
def test_skill_frontmatter_and_content_boundary_matrix(
    tmp_path: Path,
    name: str,
    transform: object,
    message: str,
) -> None:
    directory = tmp_path / name
    directory.mkdir()
    assert callable(transform)
    content = transform(valid_skill_text(name))
    (directory / "SKILL.md").write_text(content, encoding="utf-8")

    with pytest.raises(SkillContractError, match=message):
        validate_skills(tmp_path)


def test_skill_rejects_invalid_utf8_and_oversize_input(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "SKILL.md").write_bytes(b"\xff")

    with pytest.raises(SkillContractError, match="could not be read"):
        validate_skills(tmp_path)

    (invalid / "SKILL.md").write_bytes(b"x" * (64 * 1024 + 1))
    with pytest.raises(SkillContractError, match="size limit"):
        validate_skills(tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(schema_version="2.0"), "schema_version"),
        (lambda value: value.update(templates=[]), "must not be empty"),
        (
            lambda value: value["templates"].append(value["templates"][0]),
            "unique",
        ),
        (
            lambda value: value["templates"][0].update(template_id="BAD ID"),
            "template_id",
        ),
        (
            lambda value: value["templates"][0].update(target="CON/file"),
            "safe relative",
        ),
        (
            lambda value: value["templates"][0].update(
                dependencies=["same", "SAME"]
            ),
            "unique",
        ),
    ),
)
def test_template_registry_boundary_matrix(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = load_example("template-registry.json")
    assert callable(mutation)
    mutation(payload)

    with pytest.raises(SkillContractError, match=message):
        load_template_registry(write_json(tmp_path / "templates.json", payload))


def test_template_evaluation_rejects_invalid_version_and_unknown_selection() -> None:
    templates = load_template_registry(m2_example("template-registry.json"))

    with pytest.raises(SkillContractError, match="must be numeric"):
        evaluate_templates(
            templates,
            framework_version="latest",
            available_dependencies=(),
        )
    with pytest.raises(SkillContractError, match="unavailable"):
        evaluate_templates(
            templates,
            framework_version="0.1.0",
            available_dependencies=("independent-review",),
            selected=("missing-template",),
        )
