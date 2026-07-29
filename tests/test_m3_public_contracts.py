from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.application.contracts import ContractError
from sdaqf.application.evidence import (
    load_evidence_ledger,
    load_evidence_record,
    parse_evidence_record,
)
from sdaqf.application.handoffs import (
    HandoffService,
    load_automated_handoff,
)
from sdaqf.application.quality_gates import (
    FindingAcceptanceLoader,
    load_independent_review,
)
from sdaqf.application.release_qa import load_release_candidate
from sdaqf.application.ui_validation import (
    UiValidationService,
    load_manifest_ui,
    load_ui_validation,
)
from sdaqf.domain.quality import CandidateIdentity, GitObservation
from tests.schema_validation import LocalSchemaValidator, SchemaValidationError


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def m3_example(name: str) -> Path:
    return repository_root() / "examples" / "m3-quality" / name


def test_m3_samples_satisfy_full_published_schemas() -> None:
    root = repository_root()
    pairs = (
        ("m3-project-manifest.schema.json", "ui-manifest.json"),
        ("claim-evidence-ledger.schema.json", "claim-evidence-ledger.json"),
        ("evidence-addition.schema.json", "evidence-addition.json"),
        ("independent-review.schema.json", "independent-review.json"),
        (
            "finding-acceptance-approval.schema.json",
            "finding-acceptance-approval.json",
        ),
        ("ui-validation.schema.json", "ui-validation.json"),
        ("ui-validation.schema.json", "ui-validation-browser.json"),
        ("release-candidate.schema.json", "release-candidate.json"),
        ("handoff-input.schema.json", "handoff-input.json"),
        ("automated-handoff.schema.json", "automated-handoff.json"),
    )

    validator = LocalSchemaValidator(root / "schemas")
    for schema_name, sample_name in pairs:
        sample = json.loads(m3_example(sample_name).read_text(encoding="utf-8"))
        validator.validate(schema_name, sample)


def test_m3_samples_pass_strict_runtime_loaders() -> None:
    ledger = load_evidence_ledger(m3_example("claim-evidence-ledger.json"))
    record = load_evidence_record(m3_example("evidence-addition.json"))
    review = load_independent_review(m3_example("independent-review.json"))
    approval = FindingAcceptanceLoader(
        clock=lambda: datetime(2026, 7, 30, tzinfo=UTC)
    ).load(m3_example("finding-acceptance-approval.json"))
    candidate = load_release_candidate(m3_example("release-candidate.json"))
    identity = CandidateIdentity(
        ledger.source_spec_sha256,
        ledger.git_head,
        ledger.repository_digest,
    )
    git = GitObservation(True, "main", ledger.git_head, True, ledger.repository_digest)
    handoff = HandoffService().create(
        m3_example("handoff-input.json"),
        baseline_id=ledger.baseline_id,
        candidate=identity,
        git=git,
        ledger=ledger,
    )

    assert ledger.schema_version == "1.0"
    assert record.evidence_id == "EV-STATIC-0001"
    assert review.review_id == approval.review_id
    assert candidate.license_status == "not-selected"
    assert load_automated_handoff(m3_example("automated-handoff.json")) == handoff


def test_ui_samples_cover_non_ui_and_fail_closed_missing_browser_evidence() -> None:
    manifest = load_manifest_ui(
        repository_root() / "examples" / "sample-project" / "manifest.json"
    )
    no_ui_validation = load_ui_validation(m3_example("ui-validation.json"))
    no_ui = UiValidationService().evaluate(
        manifest=manifest,
        candidate=no_ui_validation.candidate,
        validation=no_ui_validation,
        root=repository_root(),
    )
    ui_manifest = load_manifest_ui(m3_example("ui-manifest.json"))
    ui_validation = load_ui_validation(m3_example("ui-validation-browser.json"))
    browser = UiValidationService().evaluate(
        manifest=ui_manifest,
        candidate=ui_validation.candidate,
        validation=ui_validation,
        root=repository_root(),
    )

    assert no_ui.passed
    assert not browser.passed
    assert "UI-PRIMARY-FLOWS" in browser.hard_blockers


def test_evidence_schema_and_runtime_reject_same_boundary_cases() -> None:
    root = repository_root()
    validator = LocalSchemaValidator(root / "schemas")
    sample = json.loads(m3_example("evidence-addition.json").read_text(encoding="utf-8"))
    cases = []
    empty_environment = copy.deepcopy(sample)
    empty_environment["environment"] = {}
    cases.append(empty_environment)
    reserved_path = copy.deepcopy(sample)
    reserved_path["artifacts"][0]["path"] = "CON"
    cases.append(reserved_path)
    null_commit = copy.deepcopy(sample)
    null_commit["commit"] = None
    cases.append(null_commit)
    for unsafe_path in (
        "con",
        "file.",
        ".",
        "~state/file.json",
        "a//b",
        "a/./b",
        "a/",
        "folder./file.txt",
        "a" * 241,
    ):
        unsafe = copy.deepcopy(sample)
        unsafe["artifacts"][0]["path"] = unsafe_path
        cases.append(unsafe)
    wrong_unverified = copy.deepcopy(sample)
    wrong_unverified["status"] = "NOT_VERIFIED"
    cases.append(wrong_unverified)
    wrong_pass = copy.deepcopy(sample)
    wrong_pass["type"] = "UNVERIFIED"
    cases.append(wrong_pass)
    absolute_command = copy.deepcopy(sample)
    absolute_command["command"] = ["python", "C:\\Users\\person\\script.py"]
    cases.append(absolute_command)
    secret_environment = copy.deepcopy(sample)
    secret_environment["environment"] = {"token": "ghp_" + ("a" * 24)}
    cases.append(secret_environment)
    invalid_claim = copy.deepcopy(sample)
    invalid_claim["claim_ids"] = ["bad"]
    cases.append(invalid_claim)

    for payload in cases:
        try:
            validator.validate("evidence-addition.schema.json", payload)
        except SchemaValidationError:
            pass
        else:
            raise AssertionError("schema accepted an invalid runtime boundary")
        try:
            parse_evidence_record(payload)
        except ContractError:
            pass
        else:
            raise AssertionError("runtime accepted an invalid schema boundary")


def test_handoff_and_release_schemas_reject_runtime_path_boundaries(
    tmp_path: Path,
) -> None:
    root = repository_root()
    validator = LocalSchemaValidator(root / "schemas")

    handoff = json.loads(m3_example("handoff-input.json").read_text(encoding="utf-8"))
    handoff["next_prompt_context"]["references"] = ["../private.md"]
    try:
        validator.validate("handoff-input.schema.json", handoff)
    except SchemaValidationError:
        pass
    else:
        raise AssertionError("handoff schema accepted a traversal reference")

    generated = json.loads(
        m3_example("automated-handoff.json").read_text(encoding="utf-8")
    )
    generated["status"] = "completed"
    generated["incomplete"] = ["Still incomplete"]
    try:
        validator.validate("automated-handoff.schema.json", generated)
    except SchemaValidationError:
        pass
    else:
        raise AssertionError("generated handoff schema accepted unfinished completion")

    release = json.loads(
        m3_example("release-candidate.json").read_text(encoding="utf-8")
    )
    release["install_target"] = ".sdaqf/CON"
    release["rollback_guidance"] = "Remove only the owned .sdaqf/CON directory."
    try:
        validator.validate("release-candidate.schema.json", release)
    except SchemaValidationError:
        pass
    else:
        raise AssertionError("release schema accepted a reserved install target")
    release_path = tmp_path / "release-candidate.json"
    release_path.write_text(json.dumps(release), encoding="utf-8")
    try:
        load_release_candidate(release_path)
    except ContractError:
        pass
    else:
        raise AssertionError("release runtime accepted a reserved install target")


def test_every_m3_path_schema_rejects_component_trailing_dot() -> None:
    root = repository_root()
    validator = LocalSchemaValidator(root / "schemas")
    cases: list[tuple[str, dict[str, object]]] = []

    evidence = json.loads(m3_example("evidence-addition.json").read_text(encoding="utf-8"))
    evidence["artifacts"][0]["path"] = "folder./file.txt"
    cases.append(("evidence-addition.schema.json", evidence))

    ledger = json.loads(
        m3_example("claim-evidence-ledger.json").read_text(encoding="utf-8")
    )
    ledger["evidence"][0]["artifacts"][0]["path"] = "folder./file.txt"
    cases.append(("claim-evidence-ledger.schema.json", ledger))

    review = json.loads(m3_example("independent-review.json").read_text(encoding="utf-8"))
    review["reviewed_paths"][0] = "folder./file.txt"
    cases.append(("independent-review.schema.json", review))

    ui = json.loads(m3_example("ui-validation-browser.json").read_text(encoding="utf-8"))
    ui["observations"][0]["trace"]["path"] = "folder./trace.json"
    cases.append(("ui-validation.schema.json", ui))

    release = json.loads(
        m3_example("release-candidate.json").read_text(encoding="utf-8")
    )
    release["documentation_paths"][0] = "folder./README.md"
    cases.append(("release-candidate.schema.json", release))

    handoff = json.loads(m3_example("handoff-input.json").read_text(encoding="utf-8"))
    handoff["next_prompt_context"]["references"][0] = "folder./reference.md"
    cases.append(("handoff-input.schema.json", handoff))

    for schema_name, payload in cases:
        try:
            validator.validate(schema_name, payload)
        except SchemaValidationError:
            pass
        else:
            raise AssertionError(f"{schema_name} accepted a trailing-dot component")


def test_ui_and_manifest_schemas_match_runtime_conditionals(tmp_path: Path) -> None:
    root = repository_root()
    validator = LocalSchemaValidator(root / "schemas")
    ui = json.loads(m3_example("ui-validation-browser.json").read_text(encoding="utf-8"))
    ui["ui_present"] = False
    try:
        validator.validate("ui-validation.schema.json", ui)
    except SchemaValidationError:
        pass
    else:
        raise AssertionError("UI schema accepted fabricated non-UI evidence")

    manifest = json.loads(m3_example("ui-manifest.json").read_text(encoding="utf-8"))
    manifest["platforms"]["optional"] = ["windows"]
    try:
        validator.validate("m3-project-manifest.schema.json", manifest)
    except SchemaValidationError:
        pass
    else:
        raise AssertionError("M3 manifest schema accepted overlapping platforms")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        load_manifest_ui(path)
    except ContractError:
        pass
    else:
        raise AssertionError("M3 manifest runtime accepted overlapping platforms")


def test_legacy_project_manifest_schema_remains_backward_compatible() -> None:
    root = repository_root()
    validator = LocalSchemaValidator(root / "schemas")
    legacy = json.loads(
        (root / "examples" / "sample-project" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    legacy.pop("release_level")
    legacy["source_spec"]["sha256"] = str(legacy["source_spec"]["sha256"]).lower()

    validator.validate("project-manifest.schema.json", legacy)


def test_public_specification_m3_requirements_remain_present() -> None:
    specification = (repository_root() / "docs" / "specification.md").read_text(
        encoding="utf-8"
    )
    plan = (
        repository_root()
        / "docs"
        / "exec-plans"
        / "active"
        / "M3-evidence-ui-release-qa.md"
    ).read_text(encoding="utf-8")

    for prefix, maximum in (("FR-QA", 14), ("FR-UI", 12), ("FR-HOF", 8)):
        for number in range(1, maximum + 1):
            assert f"`{prefix}-{number:03d}" in specification
    for number in range(1, 13):
        assert f"`AC-M3-{number:03d}`" in plan
