import json
from pathlib import Path

import pytest

from sdaqf.cli import build_parser, main
from sdaqf.domain.models import GateCheck, GateResult
from sdaqf.domain.quality import GitObservation
from tests.m3_helpers import HEAD, REPOSITORY_DIGEST, SOURCE_SHA, baseline


def test_publication_readiness_command_is_registered_with_exact_inputs() -> None:
    args = build_parser().parse_args(
        [
            "gate",
            "publication-readiness",
            ".sdaqf/v1/public-release-candidate.json",
            "--root",
            ".",
            "--baseline",
            ".sdaqf/v1/requirements-baseline.json",
            "--ledger",
            ".sdaqf/v1/claim-evidence-ledger.json",
            "--review",
            ".sdaqf/v1/independent-review.json",
            "--release-candidate",
            ".sdaqf/v1/release-candidate.json",
            "--specification",
            "docs/specification.md",
            "--json",
        ]
    )

    assert args.command == "gate"
    assert args.gate_name == "publication-readiness"
    assert args.declaration == Path(".sdaqf/v1/public-release-candidate.json")


def test_publication_readiness_invalid_input_is_generic_and_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = main(
        [
            "gate",
            "publication-readiness",
            str(invalid),
            "--baseline",
            str(invalid),
            "--ledger",
            str(invalid),
            "--review",
            str(invalid),
            "--release-candidate",
            str(invalid),
            "--specification",
            str(invalid),
            "--json",
        ]
    )

    assert result == 2
    assert capsys.readouterr().err == (
        "ERROR: publication-readiness input is invalid.\n"
    )


def test_publication_readiness_cli_reports_local_ready_without_gate_g5(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    specification = tmp_path / "specification.md"
    specification.write_text("specification\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sdaqf.cli.load_baseline", lambda path: baseline())
    monkeypatch.setattr("sdaqf.cli.load_evidence_ledger", lambda path: object())
    monkeypatch.setattr("sdaqf.cli.load_independent_review", lambda path: object())
    monkeypatch.setattr("sdaqf.cli.load_publication_readiness", lambda path: object())
    monkeypatch.setattr("sdaqf.cli.load_release_candidate", lambda path: object())
    monkeypatch.setattr(
        "sdaqf.cli.inspect_specification",
        lambda root, path, *, expected_filename: SOURCE_SHA,
    )
    monkeypatch.setattr(
        "sdaqf.cli.GitInspector.inspect",
        lambda self, root: GitObservation(
            True,
            "main",
            HEAD,
            True,
            REPOSITORY_DIGEST,
            publication_paths=("specification.md",),
        ),
    )
    monkeypatch.setattr(
        "sdaqf.cli.RequirementsGateService.evaluate",
        _passing_service_evaluate,
    )
    monkeypatch.setattr(
        "sdaqf.cli.ImplementationEvidenceGateService.evaluate",
        _passing_service_evaluate,
    )
    monkeypatch.setattr(
        "sdaqf.cli.IndependentReviewGateService.evaluate",
        _passing_service_evaluate,
    )
    monkeypatch.setattr(
        "sdaqf.cli.PublicationReadinessService.evaluate",
        _publication_service_evaluate,
    )

    code = main(
        [
            "gate",
            "publication-readiness",
            "public.json",
            "--baseline",
            "baseline.json",
            "--ledger",
            "ledger.json",
            "--review",
            "review.json",
            "--release-candidate",
            "release.json",
            "--specification",
            str(specification),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["gate_id"] == "G5-LOCAL-READINESS"
    assert payload["status"] == "LOCAL_READY"
    assert payload["publication_performed"] is False
    assert payload["actual_gate_g5"] == "NOT_RUN"
    assert "PASS" not in {payload["status"], payload["actual_gate_g5"]}


def _passing_service_evaluate(*args: object, **kwargs: object) -> GateResult:
    gate_id = "G1"
    if len(args) > 1:
        service_name = type(args[0]).__name__
        gate_id = {
            "ImplementationEvidenceGateService": "G2",
            "IndependentReviewGateService": "G3",
        }.get(service_name, "G1")
    return GateResult(gate_id, (GateCheck("PASS", True, True, "passed"),))


def _publication_service_evaluate(*args: object, **kwargs: object) -> GateResult:
    return GateResult(
        "G5-LOCAL-READINESS",
        (GateCheck("PASS", True, True, "local only"),),
    )
