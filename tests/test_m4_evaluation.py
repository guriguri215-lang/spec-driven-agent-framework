from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from sdaqf.application.contracts import ContractError
from sdaqf.application.evaluation import (
    EvaluationService,
    load_evaluation_run,
    load_evaluation_suite,
    load_normalization_expectation,
)
from tests.schema_validation import LocalSchemaValidator


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def evals_root() -> Path:
    return repository_root() / "evals"


def write_json(path: Path, payload: object) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def copied_suite(tmp_path: Path) -> Path:
    target = tmp_path / "evals"
    shutil.copytree(evals_root(), target)
    return target / "comparison-suite.json"


def test_m4_public_beta_suite_is_reproducible_and_non_compensating() -> None:
    result = EvaluationService().evaluate(evals_root() / "comparison-suite.json")
    EvaluationService().validate_recorded_result(
        evals_root() / "results" / "public-beta-comparison.json",
        result,
    )

    by_project = {item.project_id: item for item in result.comparisons}
    assert set(by_project) == {
        "offline-config",
        "secure-export",
        "ui-issue-tracker",
    }
    assert all(not item.structured.hard_blockers for item in result.comparisons)
    assert by_project["offline-config"].unstructured.missed_requirements == 1
    assert by_project["offline-config"].unstructured.rework == 2
    assert by_project["secure-export"].structured.approval_count == 1
    assert by_project["secure-export"].unstructured.critical_defects == 2
    assert by_project["secure-export"].unstructured.failed_handoffs == 1
    assert by_project["ui-issue-tracker"].unstructured.scope_additions == 1
    assert any("CRITICAL:security" in item for item in result.hard_blockers)
    assert result.to_dict()["aggregate_score"] is None
    assert any("not blinded" in item for item in result.limitations)


def test_sample_expectations_match_public_schemas_and_strict_loaders() -> None:
    validator = LocalSchemaValidator(repository_root() / "schemas")
    for project in ("offline-config", "secure-export", "ui-issue-tracker"):
        root = evals_root() / "projects" / project
        expectation_payload = json.loads(
            (root / "expected-normalized.json").read_text(encoding="utf-8")
        )
        structured_payload = json.loads(
            (root / "structured-run.json").read_text(encoding="utf-8")
        )
        unstructured_payload = json.loads(
            (root / "unstructured-run.json").read_text(encoding="utf-8")
        )
        validator.validate("evaluation-expectation.schema.json", expectation_payload)
        validator.validate("evaluation-run.schema.json", structured_payload)
        validator.validate("evaluation-run.schema.json", unstructured_payload)
        assert load_normalization_expectation(
            root / "expected-normalized.json"
        ).project_id == project
        assert (
            load_evaluation_run(
                root / "structured-run.json"
            ).input_identity.project_id
            == project
        )

    suite_payload = json.loads(
        (evals_root() / "comparison-suite.json").read_text(encoding="utf-8")
    )
    result_payload = json.loads(
        (evals_root() / "results" / "public-beta-comparison.json").read_text(
            encoding="utf-8"
        )
    )
    validator.validate("evaluation-suite.schema.json", suite_payload)
    validator.validate("evaluation-result.schema.json", result_payload)
    assert load_evaluation_suite(
        evals_root() / "comparison-suite.json"
    ).suite_id == "EVS-PUBLIC-BETA-001"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value.update({"schema_version": "2.0"}),
            "schema_version",
        ),
        (
            lambda value: value["cost"].update(
                {"status": "NOT_VERIFIED", "tool_calls": 1}
            ),
            "cost",
        ),
        (
            lambda value: value.update(
                {"requirements_implemented": list(reversed(value["requirements_implemented"]))}
            ),
            "sorted",
        ),
        (
            lambda value: value["cause_analyses"][0].update(
                {"verification_evidence": ["EV-UNKNOWN"]}
            ),
            "unknown evidence",
        ),
        (
            lambda value: value.update({"cause_analyses": []}),
            "cause analysis",
        ),
    ],
)
def test_evaluation_run_rejects_invalid_and_hidden_evidence(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = json.loads(
        (
            evals_root()
            / "projects"
            / "secure-export"
            / "unstructured-run.json"
        ).read_text(encoding="utf-8")
    )
    mutator = mutation
    assert callable(mutator)
    mutator(payload)
    with pytest.raises(ContractError, match=message):
        load_evaluation_run(write_json(tmp_path / "run.json", payload))


def test_evaluation_run_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"schema_version":"1.0","schema_version":"1.0"}',
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="duplicate"):
        load_evaluation_run(path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda root: json.loads(
                (
                    root
                    / "projects"
                    / "offline-config"
                    / "unstructured-run.json"
                ).read_text(encoding="utf-8")
            ),
            "parity",
        ),
        (
            lambda root: (
                root / "projects" / "offline-config" / "task.md"
            ).write_text("# Changed task\n", encoding="utf-8"),
            "task identity",
        ),
        (
            lambda root: json.loads(
                (
                    root
                    / "projects"
                    / "offline-config"
                    / "expected-normalized.json"
                ).read_text(encoding="utf-8")
            ),
            "expected projection",
        ),
    ],
)
def test_evaluation_service_rejects_parity_and_projection_drift(
    tmp_path: Path,
    mutate: object,
    message: str,
) -> None:
    suite = copied_suite(tmp_path)
    root = suite.parent
    mutator = mutate
    assert callable(mutator)
    result = mutator(root)
    if isinstance(result, dict):
        if "workflow" in result:
            result["input_identity"]["budget_units"] = 99
            write_json(
                root / "projects" / "offline-config" / "unstructured-run.json",
                result,
            )
        else:
            result["requirements"][0]["statement"] = "Drifted expectation."
            write_json(
                root
                / "projects"
                / "offline-config"
                / "expected-normalized.json",
                result,
            )
    with pytest.raises(ContractError, match=message):
        EvaluationService().evaluate(suite)


def test_evaluation_rejects_unknown_requirement_and_same_intervention(
    tmp_path: Path,
) -> None:
    suite = copied_suite(tmp_path)
    run_path = (
        suite.parent
        / "projects"
        / "offline-config"
        / "unstructured-run.json"
    )
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["requirements_implemented"].append("FR-UNKNOWN-001")
    payload["requirements_implemented"].sort()
    write_json(run_path, payload)
    with pytest.raises(ContractError, match="unknown requirement"):
        EvaluationService().evaluate(suite)

    suite = copied_suite(tmp_path / "second")
    root = suite.parent / "projects" / "offline-config"
    structured = json.loads((root / "structured-run.json").read_text(encoding="utf-8"))
    unstructured = json.loads(
        (root / "unstructured-run.json").read_text(encoding="utf-8")
    )
    unstructured["intervention"] = structured["intervention"]
    write_json(root / "unstructured-run.json", unstructured)
    with pytest.raises(ContractError, match="intervention"):
        EvaluationService().evaluate(suite)


def test_change_evaluation_requires_both_parity_bound_runs(tmp_path: Path) -> None:
    suite = copied_suite(tmp_path)
    payload = json.loads(suite.read_text(encoding="utf-8"))
    payload["changes"][0]["before_run_id"] = "RUN-UNKNOWN"
    write_json(suite, payload)
    with pytest.raises(ContractError, match="unknown run"):
        EvaluationService().evaluate(suite)


def test_recorded_result_mismatch_fails_closed(tmp_path: Path) -> None:
    result = EvaluationService().evaluate(evals_root() / "comparison-suite.json")
    payload = copy.deepcopy(result.to_dict())
    payload["comparisons"][0]["structured"]["missed_requirements"] = 1
    with pytest.raises(ContractError, match="does not match"):
        EvaluationService().validate_recorded_result(
            write_json(tmp_path / "result.json", payload),
            result,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"baseline_id": "bad"}), "baseline_id"),
        (lambda value: value.update({"requirements": []}), "must not be empty"),
        (
            lambda value: value.update(
                {"requirements": list(reversed(value["requirements"]))}
            ),
            "sorted and unique",
        ),
        (
            lambda value: value.update(
                {"diagnostic_kinds": ["unverifiable", "ambiguity"]}
            ),
            "diagnostic_kinds must be sorted",
        ),
        (
            lambda value: value["requirements"][0].update(
                {"acceptance_ids": ["AC-OTHER-001-01"]}
            ),
            "acceptance_ids is inconsistent",
        ),
        (
            lambda value: value["requirements"][0].update({"priority": "urgent"}),
            "priority is unsupported",
        ),
        (
            lambda value: value["requirements"][0].update({"type": "feature"}),
            "type is unsupported",
        ),
        (lambda value: value.update({"project_id": "Bad"}), "project_id is invalid"),
        (
            lambda value: value["requirements"][0].update(
                {"requirement_id": "bad"}
            ),
            "requirements\\[0\\].id is invalid",
        ),
        (
            lambda value: value["requirements"][0].update({"acceptance_ids": []}),
            "too few",
        ),
    ],
)
def test_normalization_expectation_rejects_contract_drift(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = json.loads(
        (
            evals_root()
            / "projects"
            / "offline-config"
            / "expected-normalized.json"
        ).read_text(encoding="utf-8")
    )
    mutator = mutation
    assert callable(mutator)
    mutator(payload)
    with pytest.raises(ContractError, match=message):
        load_normalization_expectation(
            write_json(tmp_path / "expectation.json", payload)
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"run_id": "bad"}), "run_id"),
        (
            lambda value: value["input_identity"].update({"platform": "other"}),
            "platform",
        ),
        (
            lambda value: value["input_identity"].update(
                {"python_version": "latest"}
            ),
            "python_version",
        ),
        (
            lambda value: value["input_identity"].update({"trial_id": "bad"}),
            "trial_id",
        ),
        (
            lambda value: value["cause_analyses"][0].update({"layers": []}),
            "layers",
        ),
        (
            lambda value: value["cause_analyses"][0].update({"status": "done"}),
            "status",
        ),
        (
            lambda value: value["cause_analyses"][0].update(
                {"status": "open", "verification_evidence": ["EV-EXP-CAUSE"]}
            ),
            "contradicts open",
        ),
        (
            lambda value: value["evidence"].append("bad"),
            "evidence\\[",
        ),
    ],
)
def test_evaluation_run_rejects_invalid_metadata(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = json.loads(
        (
            evals_root()
            / "projects"
            / "secure-export"
            / "unstructured-run.json"
        ).read_text(encoding="utf-8")
    )
    mutator = mutation
    assert callable(mutator)
    mutator(payload)
    with pytest.raises(ContractError, match=message):
        load_evaluation_run(write_json(tmp_path / "run.json", payload))


def test_evaluation_run_accepts_available_cost_and_rejects_a_reason(
    tmp_path: Path,
) -> None:
    payload = json.loads(
        (
            evals_root()
            / "projects"
            / "offline-config"
            / "structured-run.json"
        ).read_text(encoding="utf-8")
    )
    payload["cost"] = {
        "status": "AVAILABLE",
        "elapsed_seconds": 12,
        "tool_calls": 3,
        "input_tokens": 100,
        "output_tokens": 50,
        "reason": None,
    }
    assert load_evaluation_run(
        write_json(tmp_path / "available.json", payload)
    ).cost.tool_calls == 3
    payload["cost"]["reason"] = "contradictory"
    with pytest.raises(ContractError, match="must be null"):
        load_evaluation_run(write_json(tmp_path / "bad.json", payload))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"suite_id": "bad"}), "suite_id"),
        (
            lambda value: value.update({"projects": value["projects"][:2]}),
            "at least three",
        ),
        (
            lambda value: value.update(
                {"projects": list(reversed(value["projects"]))}
            ),
            "sorted",
        ),
        (lambda value: value.update({"changes": []}), "before/after"),
        (
            lambda value: value["changes"][0].update({"artifact_type": "code"}),
            "artifact_type",
        ),
        (
            lambda value: value["changes"][0].update({"before_run_id": "bad"}),
            "invalid run",
        ),
    ],
)
def test_evaluation_suite_rejects_invalid_manifest(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = json.loads(
        (evals_root() / "comparison-suite.json").read_text(encoding="utf-8")
    )
    mutator = mutation
    assert callable(mutator)
    mutator(payload)
    with pytest.raises(ContractError, match=message):
        load_evaluation_suite(write_json(tmp_path / "suite.json", payload))


def test_evaluation_service_rejects_workflow_identity_and_change_mismatch(
    tmp_path: Path,
) -> None:
    suite = copied_suite(tmp_path)
    root = suite.parent
    run = root / "projects" / "offline-config" / "structured-run.json"
    payload = json.loads(run.read_text(encoding="utf-8"))
    payload["workflow"] = "ordinary_unstructured_codex"
    write_json(run, payload)
    with pytest.raises(ContractError, match="Structured run"):
        EvaluationService().evaluate(suite)

    suite = copied_suite(tmp_path / "second")
    root = suite.parent
    payload = json.loads(suite.read_text(encoding="utf-8"))
    payload["changes"][0]["after_run_id"] = "RUN-EXP-STRUCTURED"
    write_json(suite, payload)
    with pytest.raises(ContractError, match="Change evaluation input"):
        EvaluationService().evaluate(suite)

    suite = copied_suite(tmp_path / "third")
    payload = json.loads(suite.read_text(encoding="utf-8"))
    payload["changes"][0]["before_run_id"] = "RUN-CFG-STRUCTURED"
    payload["changes"][0]["after_run_id"] = "RUN-CFG-STRUCTURED"
    write_json(suite, payload)
    with pytest.raises(ContractError, match="distinct before and after"):
        EvaluationService().evaluate(suite)


def test_evaluation_service_rejects_specification_and_defect_identity(
    tmp_path: Path,
) -> None:
    suite = copied_suite(tmp_path)
    root = suite.parent / "projects" / "offline-config"
    for name in ("structured-run.json", "unstructured-run.json"):
        payload = json.loads((root / name).read_text(encoding="utf-8"))
        payload["input_identity"]["specification_sha256"] = "A" * 64
        write_json(root / name, payload)
    with pytest.raises(ContractError, match="specification identity"):
        EvaluationService().evaluate(suite)

    suite = copied_suite(tmp_path / "second")
    root = suite.parent / "projects" / "secure-export"
    run = root / "unstructured-run.json"
    payload = json.loads(run.read_text(encoding="utf-8"))
    payload["critical_defects"][0]["requirement_ids"] = ["FR-UNKNOWN-001"]
    write_json(run, payload)
    with pytest.raises(ContractError, match="defect references"):
        EvaluationService().evaluate(suite)


def test_evaluation_service_rejects_duplicate_run_and_missing_member(
    tmp_path: Path,
) -> None:
    suite = copied_suite(tmp_path)
    run = suite.parent / "projects" / "secure-export" / "structured-run.json"
    payload = json.loads(run.read_text(encoding="utf-8"))
    payload["run_id"] = "RUN-CFG-STRUCTURED"
    write_json(run, payload)
    with pytest.raises(ContractError, match="run identifiers"):
        EvaluationService().evaluate(suite)

    suite = copied_suite(tmp_path / "second")
    payload = json.loads(suite.read_text(encoding="utf-8"))
    payload["projects"][0]["task"] = "projects/offline-config/missing.md"
    write_json(suite, payload)
    with pytest.raises(ContractError, match="could not be resolved"):
        EvaluationService().evaluate(suite)


def test_evaluation_service_binds_exact_intervention_artifacts(
    tmp_path: Path,
) -> None:
    suite = copied_suite(tmp_path)
    run = (
        suite.parent
        / "projects"
        / "offline-config"
        / "structured-run.json"
    )
    payload = json.loads(run.read_text(encoding="utf-8"))
    payload["intervention_sha256"] = "A" * 64
    write_json(run, payload)
    with pytest.raises(ContractError, match="Structured intervention identity"):
        EvaluationService().evaluate(suite)

    suite = copied_suite(tmp_path / "second")
    instructions = (
        suite.parent / "protocols" / "ordinary-instructions.md"
    )
    instructions.write_text("# Changed intervention\n", encoding="utf-8")
    with pytest.raises(ContractError, match="Unstructured intervention identity"):
        EvaluationService().evaluate(suite)

    suite = copied_suite(tmp_path / "third")
    protocols = suite.parent / "protocols"
    same_content = (protocols / "structured-instructions.md").read_bytes()
    (protocols / "ordinary-instructions.md").write_bytes(same_content)
    run = suite.parent / "projects" / "offline-config" / "unstructured-run.json"
    payload = json.loads(run.read_text(encoding="utf-8"))
    payload["intervention_sha256"] = hashlib.sha256(same_content).hexdigest().upper()
    write_json(run, payload)
    with pytest.raises(ContractError, match="differ by content"):
        EvaluationService().evaluate(suite)


def test_evaluation_service_binds_evidence_artifact_content(
    tmp_path: Path,
) -> None:
    suite = copied_suite(tmp_path)
    artifact = (
        suite.parent
        / "projects"
        / "offline-config"
        / "evidence"
        / "structured-regression.md"
    )
    artifact.write_text("# Tampered evidence\n", encoding="utf-8")
    with pytest.raises(ContractError, match="evidence identity"):
        EvaluationService().evaluate(suite)


def test_open_repeated_failure_analysis_is_a_named_blocker(
    tmp_path: Path,
) -> None:
    suite = copied_suite(tmp_path)
    run = (
        suite.parent
        / "projects"
        / "secure-export"
        / "unstructured-run.json"
    )
    payload = json.loads(run.read_text(encoding="utf-8"))
    payload["cause_analyses"][0]["status"] = "open"
    payload["cause_analyses"][0]["verification_evidence"] = []
    write_json(run, payload)

    result = EvaluationService().evaluate(suite)

    assert (
        "secure-export:unstructured:CAUSE-ANALYSIS-OPEN:FAIL-EXP-BOUNDARY"
        in result.hard_blockers
    )


def test_verified_cause_analysis_requires_passing_evidence(
    tmp_path: Path,
) -> None:
    run = (
        evals_root()
        / "projects"
        / "secure-export"
        / "unstructured-run.json"
    )
    payload = json.loads(run.read_text(encoding="utf-8"))
    cause_id = payload["cause_analyses"][0]["verification_evidence"][0]
    for evidence in payload["evidence"]:
        if evidence["evidence_id"] == cause_id:
            evidence["status"] = "FAIL"
    with pytest.raises(ContractError, match="requires passing evidence"):
        load_evaluation_run(write_json(tmp_path / "run.json", payload))
