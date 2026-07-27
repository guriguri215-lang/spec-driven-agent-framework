import json
from pathlib import Path

from sdaqf.application.validation import ProjectValidator


def sample_project() -> Path:
    return Path(__file__).resolve().parents[1] / "examples" / "sample-project"


def test_sample_project_is_valid() -> None:
    report = ProjectValidator().validate(sample_project())

    assert report.valid
    assert report.errors == ()
    assert len(report.files_checked) == 8
    assert report.to_dict()["valid"] is True


def test_non_directory_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "file"
    path.write_text("not a directory", encoding="utf-8")

    report = ProjectValidator().validate(path)

    assert not report.valid
    assert "regular directory" in report.errors[0]


def test_missing_and_invalid_files_are_reported(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{", encoding="utf-8")

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert any("invalid JSON" in error for error in report.errors)
    assert any("requirements.json" in error for error in report.errors)


def test_invalid_manifest_and_requirements_are_reported(tmp_path: Path) -> None:
    source = sample_project()
    for path in source.iterdir():
        (tmp_path / path.name).write_bytes(path.read_bytes())
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    del manifest["project_id"]
    manifest["source_spec"]["sha256"] = "bad"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    requirements = [
        {"id": "bad", "statement": "", "acceptance_criteria": []},
        {"id": "FR-DUPLICATE", "statement": "first", "acceptance_criteria": ["one"]},
        {"id": "FR-DUPLICATE", "statement": "second", "acceptance_criteria": ["two"]},
        "not an object",
    ]
    (tmp_path / "requirements.json").write_text(
        json.dumps(requirements),
        encoding="utf-8",
    )

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert any("project_id" in error for error in report.errors)
    assert any("SHA-256" in error for error in report.errors)
    assert any("identifiers must be unique" in error for error in report.errors)
    assert any("item must be an object" in error for error in report.errors)


def test_non_object_auxiliary_sample_is_rejected(tmp_path: Path) -> None:
    source = sample_project()
    for path in source.iterdir():
        (tmp_path / path.name).write_bytes(path.read_bytes())
    (tmp_path / "evidence.json").write_text("[]", encoding="utf-8")

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert "evidence.json: top-level value must be an object." in report.errors
