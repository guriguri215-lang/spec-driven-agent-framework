"""Focused tests for the transient M8 user-facing report classifier."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import sdaqf.application.workflow_explanation as workflow_explanation_module
from sdaqf.application.orchestration import (
    OrchestrationContractError,
    load_agent_registry,
    load_agent_result,
)
from sdaqf.application.workflow_contracts import (
    LoadedWorkflowArtifact,
    load_workflow_artifact,
)
from sdaqf.application.workflow_explanation import (
    ClaimConclusion,
    EpistemicClassification,
    WorkflowFinalReportError,
    WorkflowReportSourceKind,
    _report_values,
    _unique_report_claims,
    build_workflow_final_report,
    classify_agent_findings,
    classify_assumption,
    classify_evidence_claim,
    classify_program_claim,
    classify_skill_claim,
    classify_solver_verification_claim,
)
from sdaqf.domain.context import Sensitivity
from sdaqf.domain.orchestration import (
    AgentResultStatus,
    EvidenceStrength,
    FindingSeverity,
)
from sdaqf.domain.quality import (
    ArtifactReference,
    CandidateIdentity,
    ClaimState,
    EvidenceStatus,
    EvidenceType,
)
from sdaqf.domain.solver import (
    SolverLeaseEvidence,
    SolverVerification,
    SolverVerificationCheck,
    SolverVerificationOutcome,
)
from sdaqf.domain.workflow import WorkflowArtifactType, WorkflowOutcome
from tests.m2_helpers import m2_example
from tests.m3_helpers import candidate, ledger


def test_evidence_classifier_keeps_recorded_machine_support_as_inference() -> None:
    evidence_ledger = ledger()
    claim = evidence_ledger.claims[0]

    recorded = classify_evidence_claim(claim, evidence_ledger.evidence)
    assert recorded.classification is EpistemicClassification.INFERENCE
    assert recorded.conclusion is ClaimConclusion.SUPPORTED
    assert recorded.human_review_required
    assert recorded.rationale == (
        "machine-evidence-recorded-but-not-independently-replayed"
    )
    assert {source.source_kind for source in recorded.supporting_sources} == {
        WorkflowReportSourceKind.PROGRAM,
        WorkflowReportSourceKind.REVIEW,
    }

    unverified = classify_evidence_claim(
        replace(claim, state=ClaimState.UNVERIFIED),
        evidence_ledger.evidence,
    )
    assert unverified.classification is EpistemicClassification.UNKNOWN
    assert unverified.human_review_required

    machine_evidence = next(
        item for item in evidence_ledger.evidence if item.evidence_type is EvidenceType.TEST
    )
    conflict = replace(
        machine_evidence,
        evidence_id="EV-INSTALL-CONFLICT",
        status=EvidenceStatus.FAIL,
    )
    conflicted = classify_evidence_claim(claim, (*evidence_ledger.evidence, conflict))
    assert conflicted.classification is EpistemicClassification.UNKNOWN
    assert conflicted.conclusion is ClaimConclusion.UNRESOLVED
    assert conflicted.supporting_sources
    assert conflicted.refuting_sources


def test_self_declared_stale_machine_pass_cannot_become_fact() -> None:
    evidence_ledger = ledger()
    claim = evidence_ledger.claims[0]
    machine_evidence = next(
        item for item in evidence_ledger.evidence if item.evidence_type is EvidenceType.TEST
    )
    stale_self_declared_pass = replace(
        machine_evidence,
        evidence_id="EV-STALE-SELF-DECLARED-PASS",
        commit="0" * 40,
        repository_digest="F" * 64,
        recorded_at="2000-01-01T00:00:00+00:00",
    )

    assessment = classify_evidence_claim(claim, (stale_self_declared_pass,))

    assert assessment.classification is EpistemicClassification.INFERENCE
    assert assessment.conclusion is ClaimConclusion.SUPPORTED
    assert assessment.human_review_required
    assert assessment.rationale == (
        "machine-evidence-recorded-but-not-independently-replayed"
    )
    assert assessment.supporting_sources[0].source_id == (
        "EV-STALE-SELF-DECLARED-PASS"
    )


def test_failed_or_unverified_sources_remain_fail_closed() -> None:
    evidence_ledger = ledger()
    claim = evidence_ledger.claims[0]
    machine_evidence = next(
        item for item in evidence_ledger.evidence if item.evidence_type is EvidenceType.TEST
    )
    review_evidence = next(
        item
        for item in evidence_ledger.evidence
        if item.evidence_type is EvidenceType.MANUAL_REVIEW
    )

    refuted = classify_evidence_claim(
        claim,
        (replace(machine_evidence, status=EvidenceStatus.FAIL),),
    )
    review_only = classify_evidence_claim(claim, (review_evidence,))
    unknown_source = classify_evidence_claim(
        claim,
        (
            replace(
                review_evidence,
                evidence_id="EV-UNKNOWN-SOURCE",
                evidence_type=EvidenceType.UNVERIFIED,
            ),
        ),
    )
    failed_program = classify_program_claim(
        "CLM-PROGRAM-FAIL",
        "The exact calculation failed.",
        source_id="CALC-FAIL",
        status=EvidenceStatus.FAIL,
    )
    failed_skill = classify_skill_claim(
        "CLM-SKILL-FAIL",
        "The selected Skill failed.",
        source_id="SKILL-FAIL",
        status=EvidenceStatus.FAIL,
    )
    unverified_skill = classify_skill_claim(
        "CLM-SKILL-UNKNOWN",
        "The selected Skill did not return a verified result.",
        source_id="SKILL-UNKNOWN",
        status=EvidenceStatus.NOT_VERIFIED,
    )

    assert refuted.classification is EpistemicClassification.UNKNOWN
    assert refuted.conclusion is ClaimConclusion.REFUTED
    assert refuted.refuting_sources[0].source_kind is WorkflowReportSourceKind.PROGRAM
    assert review_only.classification is EpistemicClassification.INFERENCE
    assert review_only.rationale == "review-supported-claim"
    assert unknown_source.supporting_sources[0].source_kind is (
        WorkflowReportSourceKind.UNKNOWN
    )
    assert failed_program.classification is EpistemicClassification.UNKNOWN
    assert failed_program.conclusion is ClaimConclusion.REFUTED
    assert failed_skill.classification is EpistemicClassification.UNKNOWN
    assert failed_skill.conclusion is ClaimConclusion.REFUTED
    assert unverified_skill.classification is EpistemicClassification.UNKNOWN
    assert unverified_skill.conclusion is ClaimConclusion.UNRESOLVED
    assert unverified_skill.unresolved_sources


def test_invalid_agent_sources_remain_unknown() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    implementer = load_agent_result(m2_example("implementer-result.json"), registry)
    reviewer = load_agent_result(m2_example("reviewer-result.json"), registry)

    blocked = classify_agent_findings(
        (replace(implementer, status=AgentResultStatus.BLOCKED),)
    )[0]
    duplicate_identity = classify_agent_findings(
        (implementer, replace(reviewer, agent_id=implementer.agent_id))
    )[0]
    unverified = classify_agent_findings(
        (
            replace(
                implementer,
                findings=(
                    replace(
                        implementer.findings[0],
                        evidence_strength=EvidenceStrength.UNVERIFIED,
                    ),
                ),
            ),
        )
    )[0]

    assert blocked.classification is EpistemicClassification.UNKNOWN
    assert blocked.rationale == "agent-result-not-completed"
    assert duplicate_identity.classification is EpistemicClassification.UNKNOWN
    assert duplicate_identity.rationale == "duplicate-agent-identity"
    assert unverified.classification is EpistemicClassification.UNKNOWN
    assert unverified.rationale == "agent-evidence-unverified"


def test_program_skill_and_user_sources_keep_distinct_epistemic_authority() -> None:
    program = classify_program_claim(
        "CLM-PROGRAM",
        "The exact calculation passed.",
        source_id="CALC-1",
        status=EvidenceStatus.PASS,
    )
    skill = classify_skill_claim(
        "CLM-SKILL",
        "The selected Skill recommends the bounded option.",
        source_id="decision-report",
        status=EvidenceStatus.PASS,
    )
    assumption = classify_assumption(
        "CLM-ASSUMPTION",
        "The user-supplied budget remains available.",
        source_id="USER-INPUT-1",
    )
    unknown_program = classify_program_claim(
        "CLM-UNKNOWN",
        "The interrupted calculation succeeded.",
        source_id="CALC-2",
        status=EvidenceStatus.NOT_VERIFIED,
    )

    assert program.classification is EpistemicClassification.INFERENCE
    assert program.supporting_sources[0].source_kind is WorkflowReportSourceKind.PROGRAM
    assert program.human_review_required
    assert program.rationale == "program-pass-recorded-but-not-independently-replayed"
    assert skill.classification is EpistemicClassification.INFERENCE
    assert skill.supporting_sources[0].source_kind is WorkflowReportSourceKind.SKILL
    assert skill.human_review_required
    assert assumption.classification is EpistemicClassification.ASSUMPTION
    assert assumption.unresolved_sources[0].source_kind is WorkflowReportSourceKind.USER
    assert unknown_program.classification is EpistemicClassification.UNKNOWN
    assert unknown_program.unresolved_sources


def test_solver_fact_requires_verified_adoptable_result_on_exact_lineage() -> None:
    expected = candidate()
    verification = _solver_verification(expected)

    verified = classify_solver_verification_claim(
        "CLM-SOLVER",
        "The bounded solver claim holds.",
        verification,
        verification_id="M7-SOLVER-VERIFICATION-" + "A" * 64,
        expected_candidate=expected,
        expected_context_snapshot_id="M5-CONTEXT-SNAPSHOT-1",
    )
    assert verified.classification is EpistemicClassification.FACT
    assert not verified.human_review_required

    wrong_candidate = replace(expected, git_head="2" * 40)
    mismatched = classify_solver_verification_claim(
        "CLM-SOLVER",
        "The bounded solver claim holds.",
        verification,
        verification_id="M7-SOLVER-VERIFICATION-" + "A" * 64,
        expected_candidate=wrong_candidate,
        expected_context_snapshot_id="M5-CONTEXT-SNAPSHOT-1",
    )
    assert mismatched.classification is EpistemicClassification.UNKNOWN
    assert mismatched.conclusion is ClaimConclusion.UNRESOLVED
    assert mismatched.human_review_required

    incomplete = replace(
        verification,
        outcome=SolverVerificationOutcome.INCONCLUSIVE,
        adoption_allowed=False,
    )
    inconclusive = classify_solver_verification_claim(
        "CLM-SOLVER",
        "The bounded solver claim holds.",
        incomplete,
        verification_id="M7-SOLVER-VERIFICATION-" + "B" * 64,
        expected_candidate=expected,
    )
    assert inconclusive.classification is EpistemicClassification.UNKNOWN
    assert inconclusive.unresolved_sources

    rejected = classify_solver_verification_claim(
        "CLM-SOLVER",
        "The bounded solver claim holds.",
        replace(
            verification,
            outcome=SolverVerificationOutcome.REJECTED,
            adoption_allowed=False,
        ),
        verification_id="M7-SOLVER-VERIFICATION-" + "C" * 64,
        expected_candidate=expected,
    )
    assert rejected.classification is EpistemicClassification.UNKNOWN
    assert rejected.conclusion is ClaimConclusion.REFUTED
    assert rejected.refuting_sources


def test_agent_disagreement_uses_existing_evidence_policy_without_creating_fact() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    implementer = load_agent_result(m2_example("implementer-result.json"), registry)
    reviewer = load_agent_result(m2_example("reviewer-result.json"), registry)

    assessment = classify_agent_findings((implementer, reviewer))[0]

    assert assessment.classification is EpistemicClassification.INFERENCE
    assert assessment.conclusion is ClaimConclusion.SUPPORTED
    assert assessment.human_review_required
    assert [source.source_id for source in assessment.supporting_sources] == [
        "AGT-REVIEWER-1:FND-BOUNDARY-1"
    ]
    assert [source.source_id for source in assessment.refuting_sources] == [
        "AGT-IMPLEMENTER-1:FND-BOUNDARY-1"
    ]
    assert {source.assertion for source in assessment.supporting_sources} == {
        "A path overlap counterexample must be rejected."
    }


def test_equal_strength_agent_disagreement_stays_unknown_and_preserves_sources() -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    implementer = load_agent_result(m2_example("implementer-result.json"), registry)
    reviewer = load_agent_result(m2_example("reviewer-result.json"), registry)
    tied_reviewer = replace(
        reviewer,
        findings=(
            replace(
                reviewer.findings[0],
                severity=FindingSeverity.LOW,
                evidence_strength=EvidenceStrength.DIRECT,
                counterexample=None,
            ),
        ),
    )

    assessment = classify_agent_findings((implementer, tied_reviewer))[0]

    assert assessment.classification is EpistemicClassification.UNKNOWN
    assert assessment.conclusion is ClaimConclusion.UNRESOLVED
    assert not assessment.supporting_sources
    assert not assessment.refuting_sources
    assert {source.source_id for source in assessment.unresolved_sources} == {
        "AGT-IMPLEMENTER-1:FND-BOUNDARY-1",
        "AGT-REVIEWER-1:FND-BOUNDARY-1",
    }
    assert {source.assertion for source in assessment.unresolved_sources} == {
        "The owned path remained isolated.",
        "A path overlap counterexample must be rejected.",
    }


def test_unexpected_disagreement_contract_error_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_agent_registry(m2_example("agent-registry.json"))
    implementer = load_agent_result(m2_example("implementer-result.json"), registry)
    reviewer = load_agent_result(m2_example("reviewer-result.json"), registry)

    def fail_resolution(*_args: object, **_kwargs: object) -> None:
        raise OrchestrationContractError("unexpected disagreement failure")

    monkeypatch.setattr(
        workflow_explanation_module,
        "resolve_disagreement",
        fail_resolution,
    )
    with pytest.raises(OrchestrationContractError, match="unexpected disagreement"):
        classify_agent_findings((implementer, reviewer))


def test_report_value_and_claim_identity_helpers_fail_closed() -> None:
    examples = Path(__file__).parents[1] / "examples" / "m8-workflow"
    plan = load_workflow_artifact(
        examples / "integrated-plan.json",
        expected_type=WorkflowArtifactType.INTEGRATED_PLAN,
    )
    state = load_workflow_artifact(
        examples / "workflow-state.json",
        expected_type=WorkflowArtifactType.WORKFLOW_STATE,
    )
    outcome = load_workflow_artifact(
        examples / "workflow-outcome.json",
        expected_type=WorkflowArtifactType.WORKFLOW_OUTCOME,
    )
    assert _report_values(outcome, state, plan) == (
        plan.value,
        state.value,
        outcome.value,
    )

    wrong_type_cases = (
        (state, state, plan, "Workflow Outcome"),
        (outcome, outcome, plan, "Workflow State"),
        (outcome, state, outcome, "Integrated Plan"),
    )
    for supplied_outcome, supplied_state, supplied_plan, match in wrong_type_cases:
        with pytest.raises(WorkflowFinalReportError, match=match):
            _report_values(supplied_outcome, supplied_state, supplied_plan)

    wrong_value_cases: tuple[
        tuple[
            LoadedWorkflowArtifact,
            LoadedWorkflowArtifact,
            LoadedWorkflowArtifact,
            str,
        ],
        ...,
    ] = (
        (outcome, state, replace(plan, value=state.value), "Plan value"),
        (outcome, replace(state, value=plan.value), plan, "State value"),
        (replace(outcome, value=plan.value), state, plan, "Outcome value"),
    )
    for supplied_outcome, supplied_state, supplied_plan, match in wrong_value_cases:
        with pytest.raises(WorkflowFinalReportError, match=match):
            _report_values(supplied_outcome, supplied_state, supplied_plan)

    outcome_value = outcome.value
    assert isinstance(outcome_value, WorkflowOutcome)
    mismatched_outcome = replace(
        outcome,
        value=replace(
            outcome_value,
            terminal_state_id="M8-WORKFLOW-STATE-" + "F" * 64,
        ),
    )
    with pytest.raises(WorkflowFinalReportError, match="lineage"):
        _report_values(mismatched_outcome, state, plan)

    assessment = classify_assumption(
        "CLM-DUPLICATE",
        "The user-supplied condition remains provisional.",
        source_id="USER-DUPLICATE",
    )
    qualified = _unique_report_claims(
        (("SOURCE-A", assessment), ("SOURCE-B", assessment))
    )
    assert tuple(item.claim_id for item in qualified) == (
        "CLM-DUPLICATE@SOURCE-A",
        "CLM-DUPLICATE@SOURCE-B",
    )
    with pytest.raises(WorkflowFinalReportError, match="ambiguous"):
        _unique_report_claims(
            (("SOURCE-A", assessment), ("SOURCE-A", assessment))
        )


def test_transient_report_is_deterministic_and_marks_the_human_boundary() -> None:
    factual = classify_program_claim(
        "CLM-Z",
        "The exact check passed.",
        source_id="CHECK-Z",
        status=EvidenceStatus.PASS,
    )
    assumption = classify_assumption(
        "CLM-A",
        "The user accepts the stated tradeoff.",
        source_id="USER-INPUT-A",
    )
    report = build_workflow_final_report(
        outcome_id="M8-WORKFLOW-OUTCOME-1",
        plan_id="M8-INTEGRATED-PLAN-1",
        terminal_state_id="M8-WORKFLOW-STATE-1",
        candidate=candidate(),
        disposition="completed",
        aggregate_claim_state="unverified",
        claims=(factual, assumption),
        ambiguities=("User preference is provisional.", "User preference is provisional."),
        limitations=("No terminal artifact loading in this slice.",),
    )

    payload = report.to_dict()
    assert payload == report.to_dict()
    claim_payloads = cast(list[dict[str, object]], payload["claims"])
    assert [item["claim_id"] for item in claim_payloads] == ["CLM-A", "CLM-Z"]
    assert payload["human_review_required"] is True
    assert payload["human_review_claim_ids"] == ["CLM-A", "CLM-Z"]
    assert payload["ambiguities"] == ["User preference is provisional."]
    assert payload["deterministic"] is True
    assert payload["side_effect_free"] is True

    with pytest.raises(ValueError, match="unique"):
        build_workflow_final_report(
            outcome_id="M8-WORKFLOW-OUTCOME-1",
            plan_id="M8-INTEGRATED-PLAN-1",
            terminal_state_id="M8-WORKFLOW-STATE-1",
            candidate=candidate(),
            disposition="completed",
            aggregate_claim_state="verified",
            claims=(factual, factual),
        )


def _solver_verification(identity: CandidateIdentity) -> SolverVerification:
    return SolverVerification(
        sensitivity=Sensitivity.REPOSITORY_PRIVATE,
        request=ArtifactReference("evidence/solver-request.json", "A" * 64),
        request_id="M7-SOLVER-REQUEST-" + "A" * 64,
        result=ArtifactReference("evidence/solver-result.json", "B" * 64),
        result_id="M7-SOLVER-RESULT-" + "B" * 64,
        contract_id="SOLVER-CONTRACT-1",
        candidate=identity,
        graph_id="GRF-SOLVER-1",
        task_id="TSK-SOLVER-1",
        context_snapshot_id="M5-CONTEXT-SNAPSHOT-1",
        lease=SolverLeaseEvidence(
            graph_id="GRF-SOLVER-1",
            task_id="TSK-SOLVER-1",
            host_id="HST-SOLVER-1",
            attempt=1,
            lease_id="LEASE-SOLVER-1",
            fence=1,
            idempotency_key="IDEMP-SOLVER-1",
            dispatch_message_id="MSG-SOLVER-1",
            expires_at="2026-08-13T00:10:00+00:00",
            reserved_solver_calls=1,
            reserved_solver_steps=100,
        ),
        outcome=SolverVerificationOutcome.VERIFIED,
        adoption_allowed=True,
        checks=(SolverVerificationCheck("exact-replay", True),),
        reasons=(),
        verification_steps=10,
    )
