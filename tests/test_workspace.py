import json
from pathlib import Path

from sdaqf.application.workspace import WorkspaceInitializer, is_reparse_point


def test_safe_initialization_is_planned_and_applied(tmp_path: Path) -> None:
    target = tmp_path / "project"
    initializer = WorkspaceInitializer(tmp_path)

    plan = initializer.plan(target)
    applied = initializer.initialize(target)

    assert plan.safe
    assert applied.safe
    assert plan.to_dict()["target"] == "project"
    payload = json.loads((target / ".sdaqf" / "project.json").read_text(encoding="utf-8"))
    assert payload["network_policy"] == "default-deny"
    repeated = initializer.initialize(target)
    assert repeated.safe
    assert repeated.would_create == ()


def test_initialization_does_not_overwrite_existing_state(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    state = target / ".sdaqf"
    state.mkdir()
    manifest = state / "project.json"
    manifest.write_text("original", encoding="utf-8")

    plan = WorkspaceInitializer(tmp_path).initialize(target)

    assert not plan.safe
    assert manifest.read_text(encoding="utf-8") == "original"


def test_initialization_completes_known_empty_state_directory(tmp_path: Path) -> None:
    target = tmp_path / "project"
    (target / ".sdaqf").mkdir(parents=True)

    plan = WorkspaceInitializer(tmp_path).initialize(target)

    assert plan.safe
    assert plan.would_create == (".sdaqf/project.json",)
    assert (target / ".sdaqf" / "project.json").is_file()


def test_plan_reports_state_directory_for_existing_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()

    plan = WorkspaceInitializer(tmp_path).plan(target)

    assert plan.safe
    assert plan.would_create == (".sdaqf", ".sdaqf/project.json")


def test_initialization_rejects_file_target_and_missing_parent(tmp_path: Path) -> None:
    file_target = tmp_path / "file"
    file_target.write_text("content", encoding="utf-8")
    missing_parent_target = tmp_path / "missing" / "project"

    initializer = WorkspaceInitializer(tmp_path)
    file_plan = initializer.plan(file_target)
    missing_plan = initializer.plan(missing_parent_target)

    assert not file_plan.safe
    assert not missing_plan.safe
    assert not is_reparse_point(tmp_path)


def test_initialization_rejects_target_outside_allowed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    plan = WorkspaceInitializer(allowed).plan(tmp_path / "outside")

    assert not plan.safe
    assert "Target must stay within the allowed root." in plan.conflicts
