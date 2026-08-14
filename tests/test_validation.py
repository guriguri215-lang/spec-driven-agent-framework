import json
import shutil
from pathlib import Path

import pytest

from sdaqf.application.contracts import ContractError
from sdaqf.application.ui_validation import load_manifest_ui
from sdaqf.application.validation import ProjectValidator


def sample_project() -> Path:
    return Path(__file__).resolve().parents[1] / "examples" / "sample-project"


def copy_sample_project(target: Path) -> None:
    for path in sample_project().iterdir():
        shutil.copyfile(path, target / path.name)


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
    copy_sample_project(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    del manifest["project_id"]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    requirements = json.loads(
        (tmp_path / "requirements.json").read_text(encoding="utf-8")
    )
    requirements.append(requirements[0])
    (tmp_path / "requirements.json").write_text(
        json.dumps(requirements),
        encoding="utf-8",
    )

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert any("manifest.json" in error and "required" in error for error in report.errors)
    assert any("identifiers must be unique" in error for error in report.errors)


def test_non_object_auxiliary_sample_is_rejected(tmp_path: Path) -> None:
    copy_sample_project(tmp_path)
    (tmp_path / "evidence.json").write_text("[]", encoding="utf-8")

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert any("evidence.json" in error and "type" in error for error in report.errors)


def test_runtime_validation_uses_every_published_sample_schema(tmp_path: Path) -> None:
    copy_sample_project(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["schema_version"] = "9.9"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    evidence = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    del evidence["recorded_at"]
    (tmp_path / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert any("manifest.json" in error and "const" in error for error in report.errors)
    assert any("evidence.json" in error and "required" in error for error in report.errors)


def test_runtime_validation_rejects_unknown_fields(tmp_path: Path) -> None:
    copy_sample_project(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["unexpected"] = True
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert any(
        "manifest.json" in error and "additionalProperties" in error
        for error in report.errors
    )


def test_runtime_validation_rejects_duplicate_keys_and_non_finite_numbers(
    tmp_path: Path,
) -> None:
    copy_sample_project(tmp_path)
    manifest_text = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        manifest_text.replace(
            '"schema_version": "1.0",',
            '"schema_version": "1.0",\n  "schema_version": "1.0",',
            1,
        ),
        encoding="utf-8",
    )
    evidence_text = (tmp_path / "evidence.json").read_text(encoding="utf-8")
    (tmp_path / "evidence.json").write_text(
        evidence_text.replace('"os": "windows"', '"os": NaN'),
        encoding="utf-8",
    )

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert any(
        "manifest.json" in error and "duplicate JSON key" in error
        for error in report.errors
    )
    assert any("evidence.json" in error and "non-finite" in error for error in report.errors)


def test_runtime_validation_rejects_non_rfc3339_date_time(tmp_path: Path) -> None:
    copy_sample_project(tmp_path)
    evidence_path = tmp_path / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["recorded_at"] = "2026-07-27 12:00:00Z"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert any(
        "evidence.json" in error and "format" in error for error in report.errors
    )


def test_manifest_semantic_constraints_run_after_schema_validation(tmp_path: Path) -> None:
    copy_sample_project(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["platforms"]["optional"].append("windows")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert any("must not overlap" in error for error in report.errors)


def test_published_legacy_manifest_variant_uses_legacy_runtime_semantics(
    tmp_path: Path,
) -> None:
    copy_sample_project(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["release_level"]
    manifest["source_spec"]["sha256"] = manifest["source_spec"]["sha256"].lower()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert ProjectValidator().validate(tmp_path).valid
    with pytest.raises(ContractError, match="release_level"):
        load_manifest_ui(manifest_path)


def test_validation_fails_closed_when_published_schemas_are_unavailable(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    copy_sample_project(project)

    report = ProjectValidator(tmp_path / "missing-schemas").validate(project)

    assert not report.valid
    assert report.errors == ("Published schema directory is unavailable.",)


def test_oversized_input_is_reported_without_crashing(tmp_path: Path) -> None:
    copy_sample_project(tmp_path)
    (tmp_path / "evidence.json").write_bytes(b" " * 1_000_001)

    report = ProjectValidator().validate(tmp_path)

    assert not report.valid
    assert any(
        "evidence.json" in error and "size limit" in error for error in report.errors
    )
