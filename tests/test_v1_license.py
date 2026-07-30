from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

from sdaqf.application.release_qa import (
    _valid_project_license,
    audit_dependencies,
    audit_repository,
    load_release_candidate,
)
from tests.m3_helpers import write_json

LICENSE_SHA256 = "C71D239DF91726FC519C6EB72D318EC65820627232B2F796219E87DCF35D0AB4"
NOTICE_SHA256 = "2D2F956085982C50C8E1EC40DBADFAAF36E77FE2B3F3979BD2AFF3E29E1CD01D"


def test_v1_license_files_and_metadata_are_exact() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE", "NOTICE"]
    assert "license" not in " ".join(project.get("classifiers", [])).casefold()
    assert hashlib.sha256((root / "LICENSE").read_bytes()).hexdigest().upper() == (
        LICENSE_SHA256
    )
    assert hashlib.sha256((root / "NOTICE").read_bytes()).hexdigest().upper() == (
        NOTICE_SHA256
    )
    assert (root / "NOTICE").read_text(encoding="utf-8") == (
        "SDAQF\nCopyright 2026 guriguri215-lang\n"
    )
    assert audit_dependencies(root) == ()
    assert audit_repository(root) == ()


def test_v1_release_candidate_1_1_binds_exact_license(tmp_path: Path) -> None:
    candidate = {
        "schema_version": "1.1",
        "install_evidence_id": "EV-INSTALL-0001",
        "execution_module": "sdaqf",
        "install_target": ".sdaqf/install-target",
        "rollback_guidance": (
            "Remove only the owned .sdaqf/install-target and "
            ".sdaqf/install-target-source directories."
        ),
        "documentation_paths": ["README.md"],
        "license": {
            "spdx_expression": "Apache-2.0",
            "copyright_holder": "guriguri215-lang",
            "license_file": {"path": "LICENSE", "sha256": LICENSE_SHA256},
            "notice_file": {"path": "NOTICE", "sha256": NOTICE_SHA256},
        },
    }

    loaded = load_release_candidate(write_json(tmp_path / "candidate.json", candidate))

    assert loaded.schema_version == "1.1"
    assert loaded.license_status == "selected"
    assert loaded.license is not None
    assert loaded.to_dict() == candidate

    repository = Path(__file__).resolve().parents[1]
    (tmp_path / "LICENSE").write_bytes((repository / "LICENSE").read_bytes())
    (tmp_path / "NOTICE").write_bytes((repository / "NOTICE").read_bytes())
    assert _valid_project_license(tmp_path, loaded)

    historical = dict(candidate)
    historical["schema_version"] = "1.0"
    historical["license_status"] = "not-selected"
    historical.pop("license")
    old = load_release_candidate(write_json(tmp_path / "historical.json", historical))
    assert not _valid_project_license(tmp_path, old)


def test_v1_license_audits_reject_modified_nested_and_conflicting_material(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    repository = Path(__file__).resolve().parents[1]
    (root / "LICENSE").write_bytes((repository / "LICENSE").read_bytes())
    (root / "NOTICE").write_text("modified\n", encoding="utf-8")
    nested = root / "licenses"
    nested.mkdir()
    (nested / "COPYING").write_text("conflicting\n", encoding="utf-8")

    findings = audit_repository(root)

    assert any("NOTICE: approved project license content" in item for item in findings)
    assert any("licenses/COPYING" in item for item in findings)
