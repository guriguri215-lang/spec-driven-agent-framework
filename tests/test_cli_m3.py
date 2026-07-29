from __future__ import annotations

from pathlib import Path

import pytest

from sdaqf.cli import main
from sdaqf.domain.quality import GitObservation
from tests.m3_helpers import (
    HEAD,
    RELEASE_PUBLICATION_PATHS,
    REPOSITORY_DIGEST,
    SOURCE_SHA,
    baseline,
    evidence_addition_payload,
    ledger_payload,
    materialize_release_source,
    review_payload,
    ui_payload,
    write_evidence_artifacts,
    write_json,
)


def test_m3_evidence_and_gate_cli_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_evidence_artifacts(tmp_path)
    state = tmp_path / ".sdaqf"
    state.mkdir()
    _mock_git(monkeypatch)
    baseline_path = write_json(tmp_path / "baseline.json", baseline().to_dict())
    specification = tmp_path / "specification.md"
    specification.write_text("specification\n", encoding="utf-8")
    ledger_path = write_json(state / "ledger.json", ledger_payload())
    review_path = write_json(tmp_path / "review.json", review_payload())
    record_path = write_json(
        tmp_path / "record.json",
        evidence_addition_payload(),
    )

    assert main(["evidence", "validate", str(ledger_path), "--json"]) == 0
    assert main(
        [
            "gate",
            "implementation",
            str(baseline_path),
            "--ledger",
            str(ledger_path),
            "--specification",
            str(specification),
            "--json",
        ]
    ) == 0
    assert main(
        [
            "gate",
            "review",
            str(review_path),
            "--baseline",
            str(baseline_path),
            "--specification",
            str(specification),
            "--json",
        ]
    ) == 0
    outside_ledger = write_json(tmp_path / "outside-ledger.json", ledger_payload())
    assert main(
        ["evidence", "add", str(outside_ledger), str(record_path), "--json"]
    ) == 2
    assert main(
        ["evidence", "add", str(ledger_path), str(record_path), "--json"]
    ) == 0

    outputs = capsys.readouterr().out
    assert '"gate_id": "G2"' in outputs
    assert '"gate_id": "G3"' in outputs
    assert '"evidence": 4' in outputs


def test_m3_ui_and_handoff_cli_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_evidence_artifacts(tmp_path)
    state = tmp_path / ".sdaqf"
    state.mkdir()
    _mock_git(monkeypatch)
    manifest_path = write_json(tmp_path / "manifest.json", _manifest(False))
    ui_path = write_json(tmp_path / "ui.json", ui_payload())
    baseline_path = write_json(tmp_path / "baseline.json", baseline().to_dict())
    specification = tmp_path / "specification.md"
    specification.write_text("specification\n", encoding="utf-8")
    ledger_path = write_json(state / "ledger.json", ledger_payload())
    input_path = write_json(tmp_path / "handoff-input.json", _handoff_input())
    output_path = state / "handoff.json"

    assert main(
        [
            "ui",
            "validate",
            str(manifest_path),
            str(ui_path),
            "--specification",
            str(specification),
            "--json",
        ]
    ) == 0
    assert main(
        [
            "handoff",
            "create",
            str(input_path),
            "--baseline",
            str(baseline_path),
            "--ledger",
            str(ledger_path),
            "--specification",
            str(specification),
            "--output",
            str(tmp_path / "outside-handoff.json"),
            "--json",
        ]
    ) == 2
    assert main(
        [
            "handoff",
            "create",
            str(input_path),
            "--baseline",
            str(baseline_path),
            "--ledger",
            str(ledger_path),
            "--specification",
            str(specification),
            "--output",
            str(output_path),
            "--json",
        ]
    ) == 0
    assert main(
        [
            "handoff",
            "resume",
            str(output_path),
            "--baseline",
            str(baseline_path),
            "--ledger",
            str(ledger_path),
            "--specification",
            str(specification),
            "--json",
        ]
    ) == 0

    output = capsys.readouterr().out
    assert '"gate_id": "UI"' in output
    assert '"next_prompt"' in output


def test_release_candidate_cli_runs_local_g4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    docs = root / "docs"
    docs.mkdir()
    for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md"):
        (root / name).write_text(f"# {name}\n", encoding="utf-8")
    (root / "README.md").write_text(
        "# Test release\n\n## Installation\n\nOffline.\n\n"
        "## Known limitations\n\nFixture only.\n",
        encoding="utf-8",
    )
    (docs / "release-contract.md").write_text("# Release Contract\n", encoding="utf-8")
    (docs / "dependencies.md").write_text(
        "# Dependency license\n\npytest license: MIT\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        "[project]\ndependencies = []\n",
        encoding="utf-8",
    )
    (root / "requirements-dev.lock").write_text("pytest==1\n", encoding="utf-8")
    write_evidence_artifacts(root)
    baseline_path = write_json(root / "baseline.json", baseline().to_dict())
    specification = root / "specification.md"
    specification.write_text("specification\n", encoding="utf-8")
    release_publication = tuple(
        sorted((*RELEASE_PUBLICATION_PATHS, "specification.md"))
    )
    ledger_path = write_json(root / "ledger.json", ledger_payload())
    review = review_payload()
    review["reviewed_paths"] = list(release_publication)
    review_path = write_json(root / "review.json", review)
    manifest_path = write_json(root / "manifest.json", _manifest(False))
    ui_path = write_json(root / "ui.json", ui_payload())
    candidate_path = write_json(
        root / "candidate.json",
        {
            "schema_version": "1.0",
            "install_evidence_id": "EV-INSTALL-0001",
            "execution_module": "sdaqf",
            "install_target": ".sdaqf/install-target",
            "rollback_guidance": (
                "Remove only the owned .sdaqf/install-target and "
                ".sdaqf/install-target-source directories."
            ),
            "documentation_paths": [
                "CHANGELOG.md",
                "CONTRIBUTING.md",
                "README.md",
                "SECURITY.md",
                "docs/release-contract.md",
            ],
            "license_status": "not-selected",
        },
    )
    materialize_release_source(root, release_publication)
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        "sdaqf.cli.inspect_specification",
        lambda root, path, *, expected_filename: SOURCE_SHA,
    )
    monkeypatch.setattr(
        "sdaqf.cli.GitInspector.inspect",
        lambda self, path: GitObservation(
            True,
            "main",
            HEAD,
            True,
            REPOSITORY_DIGEST,
            changed_paths=(),
            publication_paths=release_publication,
        ),
    )

    code = main(
        [
            "audit",
            "release-candidate",
            str(candidate_path),
            "--root",
            ".",
            "--baseline",
            str(baseline_path),
            "--ledger",
            str(ledger_path),
            "--review",
            str(review_path),
            "--manifest",
            str(manifest_path),
            "--ui-validation",
            str(ui_path),
            "--specification",
            str(specification),
            "--json",
        ]
    )

    assert code == 0
    assert '"gate_id": "G4"' in capsys.readouterr().out


def test_m3_cli_failures_are_generic_and_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")

    assert main(["evidence", "validate", str(invalid), "--json"]) == 2
    assert main(
        [
            "gate",
            "review",
            str(invalid),
            "--baseline",
            str(invalid),
            "--specification",
            str(invalid),
            "--json",
        ]
    ) == 2
    assert main(
        [
            "handoff",
            "create",
            str(invalid),
            "--baseline",
            str(invalid),
            "--ledger",
            str(invalid),
            "--specification",
            str(invalid),
            "--output",
            str(tmp_path / "x"),
        ]
    ) == 2

    error = capsys.readouterr().err
    assert str(tmp_path) not in error
    assert error.count("ERROR:") == 3


def _manifest(present: bool) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "project_id": "example-project",
        "title": "Example",
        "release_level": "prototype",
        "source_spec": {
            "filename": "specification.md",
            "sha256": SOURCE_SHA,
            "imported_at": "2026-07-29T00:00:00+00:00",
        },
        "platforms": {"required": ["windows"], "optional": []},
        "ui": {"present": present},
        "network_policy": "default-deny",
        "api_required": False,
    }


def _handoff_input() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "milestone": "M3",
        "status": "verification",
        "completed": ["M3 local implementation"],
        "incomplete": [],
        "evidence_ids": ["EV-DIFF-0001"],
        "open_decisions": ["License"],
        "known_problems": [],
        "recommended_next": "Review the local candidate.",
        "primary_folder": "repo/",
        "approval_stops": ["Stop before external action."],
        "next_prompt_context": {
            "role": "Reviewer",
            "references": ["docs/specification.md"],
            "change_scope": ["Review M3."],
            "exclusions": ["No publication."],
            "completion_criteria": ["Report findings."],
            "stop_conditions": ["Stop for approval."],
        },
    }


def _mock_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sdaqf.cli.inspect_specification",
        lambda root, path, *, expected_filename: SOURCE_SHA,
    )
    monkeypatch.setattr(
        "sdaqf.cli.GitInspector.inspect",
        lambda self, path: GitObservation(
            True,
            "main",
            HEAD,
            True,
            REPOSITORY_DIGEST,
            changed_paths=("src/sdaqf/application/quality_gates.py",),
            publication_paths=("specification.md",),
        ),
    )
