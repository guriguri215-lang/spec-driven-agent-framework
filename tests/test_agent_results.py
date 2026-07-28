from dataclasses import replace
from pathlib import Path

import pytest

from sdaqf.application.orchestration import (
    OrchestrationContractError,
    load_agent_registry,
    load_agent_result,
    resolve_disagreement,
)
from sdaqf.domain.orchestration import EvidenceStrength
from tests.m2_helpers import load_example, m2_example, write_json


def test_structured_results_separate_implementer_and_reviewer() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))

    implementer = load_agent_result(m2_example("implementer-result.json"), registry)
    reviewer = load_agent_result(m2_example("reviewer-result.json"), registry)

    assert implementer.changed_paths
    assert not implementer.reviewed_agent_ids
    assert not reviewer.changed_paths
    assert reviewer.reviewed_agent_ids == (implementer.agent_id,)


@pytest.mark.parametrize(
    ("filename", "mutation", "message"),
    (
        (
            "implementer-result.json",
            lambda value: value.update(self_approved=True),
            "self-approve",
        ),
        (
            "reviewer-result.json",
            lambda value: value.update(changed_paths=["src/file.py"]),
            "must not report changed",
        ),
        (
            "reviewer-result.json",
            lambda value: value.update(reviewed_agent_ids=[]),
            "must identify reviewed",
        ),
        (
            "implementer-result.json",
            lambda value: value.update(summary="x" * 4_001),
            "bounded",
        ),
        (
            "implementer-result.json",
            lambda value: value.update(changed_paths=["../outside"]),
            "safe relative",
        ),
    ),
)
def test_structured_result_rejects_malformed_or_self_approved_input(
    tmp_path: Path,
    filename: str,
    mutation: object,
    message: str,
) -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    value = load_example(filename)
    assert callable(mutation)
    mutation(value)

    with pytest.raises(OrchestrationContractError, match=message):
        load_agent_result(write_json(tmp_path / "result.json", value), registry)


def test_disagreement_uses_counterexample_and_evidence_not_vote() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    implementer = load_agent_result(m2_example("implementer-result.json"), registry)
    reviewer = load_agent_result(m2_example("reviewer-result.json"), registry)

    resolution = resolve_disagreement(
        "FND-BOUNDARY-1",
        (implementer, reviewer),
    )

    assert resolution.selected_agent_id == reviewer.agent_id
    assert "agent count was not considered" in resolution.rationale


def test_equal_strength_disagreement_remains_unresolved() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    implementer = load_agent_result(m2_example("implementer-result.json"), registry)
    finding = replace(
        implementer.findings[0],
        evidence_strength=EvidenceStrength.DIRECT,
    )
    other = replace(
        implementer,
        agent_id="AGT-IMPLEMENTER-2",
        findings=(finding,),
    )

    with pytest.raises(OrchestrationContractError, match="unresolved"):
        resolve_disagreement("FND-BOUNDARY-1", (implementer, other))


def test_disagreement_does_not_rank_literal_specification_reference_text() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    implementer = load_agent_result(m2_example("implementer-result.json"), registry)
    first_finding = replace(
        implementer.findings[0],
        specification_refs=("FR-AGT-001",),
    )
    second_finding = replace(
        first_finding,
        specification_refs=("FR-TOL-014",),
    )
    first = replace(implementer, findings=(first_finding,))
    second = replace(
        implementer,
        agent_id="AGT-IMPLEMENTER-2",
        findings=(second_finding,),
    )

    with pytest.raises(OrchestrationContractError, match="unresolved"):
        resolve_disagreement("FND-BOUNDARY-1", (first, second))


def test_disagreement_requires_two_matching_findings() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    implementer = load_agent_result(m2_example("implementer-result.json"), registry)

    with pytest.raises(OrchestrationContractError, match="at least two"):
        resolve_disagreement("FND-BOUNDARY-1", (implementer,))
