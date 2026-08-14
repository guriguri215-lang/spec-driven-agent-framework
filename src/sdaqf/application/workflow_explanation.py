"""Exact recomputing explanations for deterministic M8 Integrated Plans."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from sdaqf.application.orchestration import (
    OrchestrationContractError,
    resolve_disagreement,
)
from sdaqf.application.workflow_contracts import (
    LoadedWorkflowArtifact,
    WorkflowContractError,
    load_workflow_artifact,
    verify_workflow_reference,
)
from sdaqf.application.workflow_planning import IntegratedPlanner
from sdaqf.domain.orchestration import (
    AgentFinding,
    AgentResult,
    AgentResultStatus,
    EvidenceStrength,
)
from sdaqf.domain.quality import (
    ArtifactReference,
    CandidateIdentity,
    Claim,
    ClaimState,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceType,
)
from sdaqf.domain.requirements import RequirementType
from sdaqf.domain.scheduler import (
    MailboxMessage,
    SchedulerArtifactType,
    TaskGraph,
    TaskKind,
    WorkflowEpochPhase,
    WorkflowReceiptStatus,
)
from sdaqf.domain.solver import (
    SolverArtifactType,
    SolverResult,
    SolverVerification,
    SolverVerificationOutcome,
)
from sdaqf.domain.workflow import (
    DevelopmentIntent,
    IntegratedPlan,
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowDecisionKind,
    WorkflowOutcome,
    WorkflowPublicationObservation,
    WorkflowState,
)


class EpistemicClassification(StrEnum):
    """Conservative claim classes emitted by the read-only final report."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    ASSUMPTION = "ASSUMPTION"
    UNKNOWN = "UNKNOWN"


class ClaimConclusion(StrEnum):
    """Whether available sources support, refute, or leave a claim open."""

    SUPPORTED = "supported"
    REFUTED = "refuted"
    UNRESOLVED = "unresolved"


class WorkflowReportSourceKind(StrEnum):
    """Origin classes kept distinct in one user-facing claim assessment."""

    USER = "user"
    AGENT = "agent"
    SKILL = "skill"
    PROGRAM = "program"
    REVIEW = "review"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class WorkflowReportSource:
    """One traceable source without granting it factual authority by label."""

    source_id: str
    source_kind: WorkflowReportSourceKind
    status: str
    artifact_id: str | None = None
    assertion: str | None = None
    references: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-ready representation."""

        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind.value,
            "status": self.status,
            "artifact_id": self.artifact_id,
            "assertion": self.assertion,
            "references": list(sorted(set(self.references))),
        }


@dataclass(frozen=True, slots=True)
class WorkflowClaimAssessment:
    """One proposition with explicit epistemic and source separation."""

    claim_id: str
    statement: str
    classification: EpistemicClassification
    conclusion: ClaimConclusion
    supporting_sources: tuple[WorkflowReportSource, ...]
    refuting_sources: tuple[WorkflowReportSource, ...]
    unresolved_sources: tuple[WorkflowReportSource, ...]
    human_review_required: bool
    rationale: str

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-ready representation."""

        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "classification": self.classification.value,
            "conclusion": self.conclusion.value,
            "supporting_sources": [
                item.to_dict() for item in _sorted_sources(self.supporting_sources)
            ],
            "refuting_sources": [
                item.to_dict() for item in _sorted_sources(self.refuting_sources)
            ],
            "unresolved_sources": [
                item.to_dict() for item in _sorted_sources(self.unresolved_sources)
            ],
            "human_review_required": self.human_review_required,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class WorkflowFinalReport:
    """Transient read-only report; this is not an M8 artifact or schema."""

    outcome_id: str
    plan_id: str
    terminal_state_id: str
    candidate: CandidateIdentity
    disposition: str
    aggregate_claim_state: str
    claims: tuple[WorkflowClaimAssessment, ...]
    blockers: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @property
    def human_review_claim_ids(self) -> tuple[str, ...]:
        """Return every proposition that still needs human judgment."""

        return tuple(
            sorted(item.claim_id for item in self.claims if item.human_review_required)
        )

    @property
    def human_review_required(self) -> bool:
        """Return whether any claim or workflow-level uncertainty needs review."""

        return bool(
            self.human_review_claim_ids
            or self.blockers
            or self.ambiguities
            or self.disposition != "completed"
        )

    def to_dict(self) -> dict[str, object]:
        """Return deterministic JSON without changing any persisted Outcome."""

        claims = tuple(sorted(self.claims, key=lambda item: item.claim_id))
        return {
            "outcome_id": self.outcome_id,
            "plan_id": self.plan_id,
            "terminal_state_id": self.terminal_state_id,
            "candidate": self.candidate.to_dict(),
            "disposition": self.disposition,
            "aggregate_claim_state": self.aggregate_claim_state,
            "claims": [item.to_dict() for item in claims],
            "blockers": list(sorted(set(self.blockers))),
            "ambiguities": list(sorted(set(self.ambiguities))),
            "human_review_required": self.human_review_required,
            "human_review_claim_ids": list(self.human_review_claim_ids),
            "limitations": list(sorted(set(self.limitations))),
            "deterministic": True,
            "side_effect_free": True,
        }


_MACHINE_EVIDENCE_TYPES = frozenset(
    {
        EvidenceType.TEST,
        EvidenceType.STATIC_ANALYSIS,
        EvidenceType.TYPE_CHECK,
        EvidenceType.BENCHMARK,
    }
)
_EQUAL_STRENGTH_MESSAGE = "Equal-strength disagreement remains unresolved."


def classify_evidence_claim(
    claim: Claim,
    evidence: tuple[EvidenceRecord, ...],
) -> WorkflowClaimAssessment:
    """Classify one ledger claim without upgrading unverified evidence."""

    relevant = tuple(item for item in evidence if claim.claim_id in item.claim_ids)
    supporting = tuple(
        _evidence_source(item) for item in relevant if item.status is EvidenceStatus.PASS
    )
    refuting = tuple(
        _evidence_source(item) for item in relevant if item.status is EvidenceStatus.FAIL
    )
    unresolved = tuple(
        _evidence_source(item)
        for item in relevant
        if item.status is EvidenceStatus.NOT_VERIFIED
    )
    machine_support = any(
        item.status is EvidenceStatus.PASS and item.evidence_type in _MACHINE_EVIDENCE_TYPES
        for item in relevant
    )
    if refuting and not supporting and not unresolved:
        conclusion = ClaimConclusion.REFUTED
    elif refuting or unresolved or not supporting:
        conclusion = ClaimConclusion.UNRESOLVED
    else:
        conclusion = ClaimConclusion.SUPPORTED

    if (
        claim.state is ClaimState.VERIFIED
        and machine_support
        and conclusion is ClaimConclusion.SUPPORTED
    ):
        classification = EpistemicClassification.INFERENCE
        rationale = "machine-evidence-recorded-but-not-independently-replayed"
        human_review = True
    elif claim.state is ClaimState.VERIFIED and conclusion is ClaimConclusion.SUPPORTED:
        classification = EpistemicClassification.INFERENCE
        rationale = "review-supported-claim"
        human_review = True
    else:
        classification = EpistemicClassification.UNKNOWN
        rationale = (
            "conflicting-or-unresolved-evidence"
            if refuting or unresolved
            else "claim-not-machine-verified"
        )
        human_review = True
    return WorkflowClaimAssessment(
        claim_id=claim.claim_id,
        statement=claim.statement,
        classification=classification,
        conclusion=conclusion,
        supporting_sources=_sorted_sources(supporting),
        refuting_sources=_sorted_sources(refuting),
        unresolved_sources=_sorted_sources(unresolved),
        human_review_required=human_review,
        rationale=rationale,
    )


def classify_program_claim(
    claim_id: str,
    statement: str,
    *,
    source_id: str,
    status: EvidenceStatus,
    artifact_id: str | None = None,
    references: tuple[str, ...] = (),
) -> WorkflowClaimAssessment:
    """Classify one recorded program result without treating its status as replay proof."""

    source = WorkflowReportSource(
        source_id=source_id,
        source_kind=WorkflowReportSourceKind.PROGRAM,
        status=status.value,
        artifact_id=artifact_id,
        references=references,
    )
    if status is EvidenceStatus.PASS:
        return WorkflowClaimAssessment(
            claim_id,
            statement,
            EpistemicClassification.INFERENCE,
            ClaimConclusion.SUPPORTED,
            (source,),
            (),
            (),
            True,
            "program-pass-recorded-but-not-independently-replayed",
        )
    if status is EvidenceStatus.FAIL:
        return WorkflowClaimAssessment(
            claim_id,
            statement,
            EpistemicClassification.UNKNOWN,
            ClaimConclusion.REFUTED,
            (),
            (source,),
            (),
            True,
            "program-result-refutes-claim",
        )
    return WorkflowClaimAssessment(
        claim_id,
        statement,
        EpistemicClassification.UNKNOWN,
        ClaimConclusion.UNRESOLVED,
        (),
        (),
        (source,),
        True,
        "program-result-not-verified",
    )


def classify_solver_verification_claim(
    claim_id: str,
    statement: str,
    verification: SolverVerification,
    *,
    verification_id: str,
    expected_candidate: CandidateIdentity,
    expected_context_snapshot_id: str | None = None,
) -> WorkflowClaimAssessment:
    """Classify an independently verified solver result on its exact lineage."""

    source = WorkflowReportSource(
        source_id=verification_id,
        source_kind=WorkflowReportSourceKind.PROGRAM,
        status=verification.outcome.value,
        artifact_id=verification_id,
        references=(
            verification.request.path,
            verification.request_id,
            verification.result.path,
            verification.result_id,
            verification.context_snapshot_id,
        ),
    )
    lineage_matches = verification.candidate == expected_candidate and (
        expected_context_snapshot_id is None
        or verification.context_snapshot_id == expected_context_snapshot_id
    )
    checks_passed = bool(verification.checks) and all(
        check.passed for check in verification.checks
    )
    verified = (
        lineage_matches
        and verification.outcome is SolverVerificationOutcome.VERIFIED
        and verification.adoption_allowed
        and checks_passed
    )
    if verified:
        return WorkflowClaimAssessment(
            claim_id,
            statement,
            EpistemicClassification.FACT,
            ClaimConclusion.SUPPORTED,
            (source,),
            (),
            (),
            False,
            "verified-solver-result-on-exact-lineage",
        )
    refuted = lineage_matches and (
        verification.outcome is SolverVerificationOutcome.REJECTED
        or (
            verification.outcome is SolverVerificationOutcome.VERIFIED
            and not verification.adoption_allowed
        )
    )
    return WorkflowClaimAssessment(
        claim_id,
        statement,
        EpistemicClassification.UNKNOWN,
        ClaimConclusion.REFUTED if refuted else ClaimConclusion.UNRESOLVED,
        (),
        (source,) if refuted else (),
        () if refuted else (source,),
        True,
        (
            "solver-verification-candidate-or-context-mismatch"
            if not lineage_matches
            else "solver-verification-refutes-claim"
            if refuted
            else "solver-verification-inconclusive-or-incomplete"
        ),
    )


def classify_skill_claim(
    claim_id: str,
    statement: str,
    *,
    source_id: str,
    status: EvidenceStatus,
    artifact_id: str | None = None,
    references: tuple[str, ...] = (),
) -> WorkflowClaimAssessment:
    """Classify a Skill contribution without treating its output as a fact."""

    source = WorkflowReportSource(
        source_id=source_id,
        source_kind=WorkflowReportSourceKind.SKILL,
        status=status.value,
        artifact_id=artifact_id,
        references=references,
    )
    if status is EvidenceStatus.PASS:
        return WorkflowClaimAssessment(
            claim_id,
            statement,
            EpistemicClassification.INFERENCE,
            ClaimConclusion.SUPPORTED,
            (source,),
            (),
            (),
            True,
            "skill-supported-inference",
        )
    if status is EvidenceStatus.FAIL:
        return WorkflowClaimAssessment(
            claim_id,
            statement,
            EpistemicClassification.UNKNOWN,
            ClaimConclusion.REFUTED,
            (),
            (source,),
            (),
            True,
            "skill-execution-failed",
        )
    return WorkflowClaimAssessment(
        claim_id,
        statement,
        EpistemicClassification.UNKNOWN,
        ClaimConclusion.UNRESOLVED,
        (),
        (),
        (source,),
        True,
        "skill-output-not-verified",
    )


def classify_assumption(
    claim_id: str,
    statement: str,
    *,
    source_id: str,
    references: tuple[str, ...] = (),
) -> WorkflowClaimAssessment:
    """Retain a user-declared assumption without presenting it as fact."""

    source = WorkflowReportSource(
        source_id=source_id,
        source_kind=WorkflowReportSourceKind.USER,
        status="declared",
        references=references,
    )
    return WorkflowClaimAssessment(
        claim_id,
        statement,
        EpistemicClassification.ASSUMPTION,
        ClaimConclusion.UNRESOLVED,
        (),
        (),
        (source,),
        True,
        "user-declared-assumption",
    )


def classify_agent_findings(
    results: tuple[AgentResult, ...],
) -> tuple[WorkflowClaimAssessment, ...]:
    """Classify agent findings and consume the existing disagreement policy."""

    grouped: dict[str, list[tuple[AgentResult, AgentFinding]]] = {}
    for result in results:
        for finding in result.findings:
            grouped.setdefault(finding.finding_id, []).append((result, finding))
    assessments = [
        _classify_agent_finding(finding_id, tuple(grouped[finding_id]))
        for finding_id in sorted(grouped)
    ]
    return tuple(assessments)


def build_workflow_final_report(
    *,
    outcome_id: str,
    plan_id: str,
    terminal_state_id: str,
    candidate: CandidateIdentity,
    disposition: str,
    aggregate_claim_state: str,
    claims: tuple[WorkflowClaimAssessment, ...],
    blockers: tuple[str, ...] = (),
    ambiguities: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
) -> WorkflowFinalReport:
    """Build one deterministic transient report and reject duplicate propositions."""

    claim_ids = tuple(item.claim_id for item in claims)
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("Workflow final report claim identifiers must be unique.")
    return WorkflowFinalReport(
        outcome_id=outcome_id,
        plan_id=plan_id,
        terminal_state_id=terminal_state_id,
        candidate=candidate,
        disposition=disposition,
        aggregate_claim_state=aggregate_claim_state,
        claims=tuple(sorted(claims, key=lambda item: item.claim_id)),
        blockers=tuple(sorted(set(blockers))),
        ambiguities=tuple(sorted(set(ambiguities))),
        limitations=tuple(sorted(set(limitations))),
    )


def _classify_agent_finding(
    finding_id: str,
    candidates: tuple[tuple[AgentResult, AgentFinding], ...],
) -> WorkflowClaimAssessment:
    ordered = tuple(sorted(candidates, key=lambda item: item[0].agent_id))
    sources = tuple(_agent_source(result, finding) for result, finding in ordered)
    statements = tuple(sorted({finding.statement for _, finding in ordered}))
    statement = statements[0] if len(statements) == 1 else " | ".join(statements)
    if any(result.status is not AgentResultStatus.COMPLETED for result, _ in ordered):
        return _unknown_agent_assessment(
            finding_id,
            statement,
            sources,
            "agent-result-not-completed",
        )
    if len({result.agent_id for result, _ in ordered}) != len(ordered):
        return _unknown_agent_assessment(
            finding_id,
            statement,
            sources,
            "duplicate-agent-identity",
        )
    signatures = {_finding_signature(finding) for _, finding in ordered}
    if len(ordered) == 1 or len(signatures) == 1:
        if all(
            finding.evidence_strength is EvidenceStrength.UNVERIFIED
            for _, finding in ordered
        ):
            return _unknown_agent_assessment(
                finding_id,
                statement,
                sources,
                "agent-evidence-unverified",
            )
        return WorkflowClaimAssessment(
            finding_id,
            statement,
            EpistemicClassification.INFERENCE,
            ClaimConclusion.SUPPORTED,
            _sorted_sources(sources),
            (),
            (),
            True,
            "agent-supported-inference",
        )
    try:
        resolution = resolve_disagreement(
            finding_id,
            tuple(result for result, _ in ordered),
        )
    except OrchestrationContractError as exc:
        if str(exc) != _EQUAL_STRENGTH_MESSAGE:
            raise
        return _unknown_agent_assessment(
            finding_id,
            statement,
            sources,
            "equal-strength-agent-disagreement",
        )
    supporting = tuple(
        source
        for source, (result, _) in zip(sources, ordered, strict=True)
        if result.agent_id == resolution.selected_agent_id
    )
    opposing = tuple(
        source
        for source, (result, _) in zip(sources, ordered, strict=True)
        if result.agent_id != resolution.selected_agent_id
    )
    return WorkflowClaimAssessment(
        finding_id,
        statement,
        EpistemicClassification.INFERENCE,
        ClaimConclusion.SUPPORTED,
        _sorted_sources(supporting),
        _sorted_sources(opposing),
        (),
        True,
        "agent-disagreement-ranked-by-existing-evidence-policy",
    )


def _unknown_agent_assessment(
    finding_id: str,
    statement: str,
    sources: tuple[WorkflowReportSource, ...],
    rationale: str,
) -> WorkflowClaimAssessment:
    return WorkflowClaimAssessment(
        finding_id,
        statement,
        EpistemicClassification.UNKNOWN,
        ClaimConclusion.UNRESOLVED,
        (),
        (),
        _sorted_sources(sources),
        True,
        rationale,
    )


def _evidence_source(record: EvidenceRecord) -> WorkflowReportSource:
    if record.evidence_type in _MACHINE_EVIDENCE_TYPES:
        kind = WorkflowReportSourceKind.PROGRAM
    elif record.evidence_type in {
        EvidenceType.MANUAL_REVIEW,
        EvidenceType.SOURCE_REVIEW,
        EvidenceType.VISUAL,
    }:
        kind = WorkflowReportSourceKind.REVIEW
    else:
        kind = WorkflowReportSourceKind.UNKNOWN
    return WorkflowReportSource(
        source_id=record.evidence_id,
        source_kind=kind,
        status=record.status.value,
        references=tuple(item.path for item in record.artifacts),
    )


def _agent_source(
    result: AgentResult,
    finding: AgentFinding,
) -> WorkflowReportSource:
    return WorkflowReportSource(
        source_id=f"{result.agent_id}:{finding.finding_id}",
        source_kind=WorkflowReportSourceKind.AGENT,
        status=f"{result.status.value}:{finding.evidence_strength.value}",
        assertion=finding.statement,
        references=tuple(sorted({*finding.specification_refs, *finding.evidence_refs})),
    )


def _finding_signature(finding: AgentFinding) -> tuple[object, ...]:
    return (
        finding.severity,
        finding.statement,
        tuple(sorted(finding.specification_refs)),
        tuple(sorted(finding.evidence_refs)),
        finding.evidence_strength,
        finding.counterexample,
    )


def _sorted_sources(
    sources: tuple[WorkflowReportSource, ...],
) -> tuple[WorkflowReportSource, ...]:
    return tuple(
        sorted(
            sources,
            key=lambda item: (
                item.source_kind.value,
                item.source_id,
                item.artifact_id or "",
                item.status,
            ),
        )
    )


class WorkflowFinalReportError(WorkflowContractError):
    """Terminal native authority cannot support a read-only final report."""


class WorkflowFinalReportService:
    """Reauthenticate terminal authority before rendering a transient report."""

    def __init__(self, planner: IntegratedPlanner) -> None:
        self._planner = planner

    def report(
        self,
        outcome_artifact: LoadedWorkflowArtifact,
        state_artifact: LoadedWorkflowArtifact,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
    ) -> WorkflowFinalReport:
        """Build a report from exact terminal receipts without publishing anything."""

        # These imports stay late because workflow_runtime imports WorkflowExplainer.
        from sdaqf.adapters.scheduler import SQLiteSchedulerStore
        from sdaqf.application.baselines import load_baseline
        from sdaqf.application.evidence import load_evidence_ledger
        from sdaqf.application.quality_gates import load_independent_review
        from sdaqf.application.scheduler_contracts import (
            bind_review_task_result_evidence,
            load_task_agent_result,
            validate_reviewed_agent_identities,
        )
        from sdaqf.application.skills import resolve_skill_capabilities
        from sdaqf.application.solver_contracts import load_solver_artifact
        from sdaqf.application.workflow_outcome import WorkflowOutcomeService
        from sdaqf.application.workflow_runtime import (
            WorkflowRuntimeService,
            _require_runtime_private_path,
        )

        try:
            plan, state, outcome = _report_values(
                outcome_artifact,
                state_artifact,
                plan_artifact,
            )
            runtime_status = WorkflowRuntimeService(planner=self._planner).status(
                state_artifact,
                plan_artifact,
                root,
                scheduler_state,
            )
            if (
                runtime_status.get("valid") is not True
                or runtime_status.get("side_effect_free") is not True
                or runtime_status.get("authoritative_state_id") != state_artifact.artifact_id
                or runtime_status.get("authoritative_outcome_id")
                != outcome_artifact.artifact_id
                or runtime_status.get("epoch_phase")
                != WorkflowEpochPhase.TERMINAL_CONFIRMED.value
            ):
                raise WorkflowFinalReportError(
                    "Workflow runtime does not confirm the supplied terminal authority."
                )

            store = SQLiteSchedulerStore(scheduler_state, root)
            store.validate()
            store.require_workflow_authority()
            snapshot = store.workflow_receipt_snapshot(plan_artifact.artifact_id)
            if snapshot.candidate != plan.candidate or len(snapshot.heads) != 1:
                raise WorkflowFinalReportError(
                    "M6 receipt snapshot does not identify one exact Plan epoch."
                )
            head = snapshot.heads[0]
            if (
                head.phase is not WorkflowEpochPhase.TERMINAL_CONFIRMED
                or head.plan_id != plan_artifact.artifact_id
                or head.candidate != plan.candidate
                or head.graph_id != plan.task_graph.artifact_id
                or head.workflow_event_id != state.latest_event.artifact_id
                or head.workflow_state_id != state_artifact.artifact_id
                or head.outcome_id != outcome_artifact.artifact_id
                or head.scheduler_state_id != state.scheduler_state_id
                or head.scheduler_state_id != outcome.scheduler_state_id
            ):
                raise WorkflowFinalReportError(
                    "M6 terminal head does not bind the supplied Workflow artifacts."
                )
            if any(
                receipt.status is not WorkflowReceiptStatus.CONFIRMED
                for receipt in head.receipts
            ):
                raise WorkflowFinalReportError(
                    "M6 terminal authority contains an unconfirmed artifact receipt."
                )

            authoritative = (
                (
                    WorkflowArtifactType.INTEGRATED_PLAN,
                    plan_artifact,
                    None,
                ),
                (
                    WorkflowArtifactType.WORKFLOW_EVENT,
                    None,
                    head.workflow_event_path,
                ),
                (
                    WorkflowArtifactType.WORKFLOW_STATE,
                    state_artifact,
                    head.workflow_state_path,
                ),
                (
                    WorkflowArtifactType.WORKFLOW_OUTCOME,
                    outcome_artifact,
                    head.outcome_path,
                ),
            )
            expected_ids = {
                WorkflowArtifactType.INTEGRATED_PLAN: plan_artifact.artifact_id,
                WorkflowArtifactType.WORKFLOW_EVENT: state.latest_event.artifact_id,
                WorkflowArtifactType.WORKFLOW_STATE: state_artifact.artifact_id,
                WorkflowArtifactType.WORKFLOW_OUTCOME: outcome_artifact.artifact_id,
            }
            for artifact_type, supplied, head_path in authoritative:
                artifact_id = expected_ids[artifact_type]
                matches = tuple(
                    receipt
                    for receipt in head.receipts
                    if receipt.artifact_type == artifact_type.value
                    and receipt.artifact_id == artifact_id
                )
                if len(matches) != 1:
                    raise WorkflowFinalReportError(
                        "M6 terminal authority lacks one exact confirmed artifact receipt."
                    )
                receipt = matches[0]
                if head_path is not None and receipt.path != head_path:
                    raise WorkflowFinalReportError(
                        "M6 terminal head and artifact receipt paths disagree."
                    )
                receipt_path = _require_runtime_private_path(
                    root,
                    root / receipt.path,
                    existing=True,
                )
                reloaded = load_workflow_artifact(
                    receipt_path,
                    expected_type=artifact_type,
                )
                if reloaded.artifact_id != artifact_id or (
                    supplied is not None and reloaded.to_dict() != supplied.to_dict()
                ):
                    raise WorkflowFinalReportError(
                        "A supplied Workflow artifact differs from its M6 receipt."
                    )

            reproduced = WorkflowOutcomeService(planner=self._planner).derive(
                state_artifact,
                plan_artifact,
                root,
                scheduler_state,
            )
            if reproduced.to_dict() != outcome_artifact.to_dict():
                raise WorkflowFinalReportError(
                    "Workflow Outcome does not reproduce exactly from terminal State."
                )

            binding_by_id: dict[str, NativeArtifactBinding] = {}
            binding_paths: dict[str, Path] = {}
            for binding in state.observation_artifacts:
                if binding.artifact_id in binding_by_id:
                    raise WorkflowFinalReportError(
                        "Workflow observation artifact identifiers must be unique."
                    )
                binding_by_id[binding.artifact_id] = binding
                binding_paths[binding.artifact_id] = verify_workflow_reference(root, binding)

            tagged_claims: list[tuple[str, WorkflowClaimAssessment]] = []
            limitations: set[str] = set()
            classified_binding_types = {
                "agent-result",
                "evidence-ledger",
                "skill",
                SolverArtifactType.RESULT.value,
                SolverArtifactType.VERIFICATION.value,
            }
            limitations.update(
                f"No proposition classifier for observation type {binding.artifact_type}."
                for binding in state.observation_artifacts
                if binding.artifact_type not in classified_binding_types
            )

            for binding in state.observation_artifacts:
                if binding.artifact_type != "evidence-ledger":
                    continue
                ledger = load_evidence_ledger(binding_paths[binding.artifact_id])
                if (
                    ledger.baseline_id != plan.requirement_baseline_id
                    or ledger.source_spec_sha256 != plan.candidate.source_spec_sha256
                    or ledger.git_head != plan.candidate.git_head
                    or ledger.repository_digest != plan.candidate.repository_digest
                ):
                    raise WorkflowFinalReportError(
                        "Evidence Ledger does not match the terminal Candidate."
                    )
                tagged_claims.extend(
                    (binding.artifact_id, classify_evidence_claim(claim, ledger.evidence))
                    for claim in ledger.claims
                )

            graph_artifact = store.graph_artifact()
            if (
                graph_artifact.artifact_type is not SchedulerArtifactType.TASK_GRAPH
                or graph_artifact.artifact_id != plan.task_graph.artifact_id
            ):
                raise WorkflowFinalReportError(
                    "M6 Task Graph does not match the terminal Plan."
                )
            graph = graph_artifact.value
            if not isinstance(graph, TaskGraph):
                raise WorkflowFinalReportError("M6 Task Graph value is unavailable.")
            task_by_id = {task.task_id: task for task in graph.tasks}
            expected_agent_bindings = {
                identifier: binding
                for identifier, binding in binding_by_id.items()
                if binding.artifact_type == "agent-result"
            }
            expected_skill_bindings = {
                identifier: binding
                for identifier, binding in binding_by_id.items()
                if binding.artifact_type == "skill"
            }
            expected_review_bindings = {
                identifier: binding
                for identifier, binding in binding_by_id.items()
                if binding.artifact_type == "independent-review"
            }
            seen_agent_bindings: set[str] = set()
            seen_skill_bindings: set[str] = set()
            seen_review_bindings: set[str] = set()
            accepted_results: list[AgentResult] = []
            accepted_results_by_task: dict[str, AgentResult] = {}
            accepted_result_references_by_task: dict[str, ArtifactReference] = {}
            completed_result_messages = store.completed_task_result_messages()
            for message_artifact in completed_result_messages:
                message = message_artifact.value
                if not isinstance(message, MailboxMessage):
                    raise WorkflowFinalReportError(
                        "M6 completed result is not a Task Result message."
                    )
                result, result_reference = load_task_agent_result(root, graph, message)
                identifier = f"M2-AGENT-RESULT-{result_reference.sha256}"
                agent_binding = expected_agent_bindings.get(identifier)
                if agent_binding is None:
                    continue
                if (
                    agent_binding.reference != result_reference
                    or identifier in seen_agent_bindings
                ):
                    raise WorkflowFinalReportError(
                        "Accepted Agent Result binding is duplicated or inconsistent."
                    )
                seen_agent_bindings.add(identifier)
                accepted_results.append(result)
                if message.task_id is None or message.task_id not in task_by_id:
                    raise WorkflowFinalReportError(
                        "Accepted Agent Result has no exact Task binding."
                    )
                task = task_by_id[message.task_id]
                accepted_results_by_task[task.task_id] = result
                accepted_result_references_by_task[task.task_id] = result_reference
                for skill in resolve_skill_capabilities(root, task.required_capabilities):
                    skill_identifier = f"M2-SKILL-{skill.digest}"
                    skill_binding = expected_skill_bindings.get(skill_identifier)
                    if skill_binding is None or skill_binding.reference != skill.reference:
                        raise WorkflowFinalReportError(
                            "Accepted Agent Result Skill provenance is absent from State."
                        )
                    seen_skill_bindings.add(skill_identifier)
                    tagged_claims.append(
                        (
                            f"{task.task_id}:{skill.name}",
                            classify_skill_claim(
                                f"SKILL-{task.task_id}-{skill.digest[:16]}",
                                (
                                    f"Accepted Agent Result {result.agent_id} binds exact "
                                    f"Skill provenance {skill.name}."
                                ),
                                source_id=skill_identifier,
                                status=EvidenceStatus.PASS,
                                artifact_id=skill_identifier,
                                references=(
                                    skill.reference.path,
                                    message_artifact.artifact_id,
                                    result.agent_id,
                                ),
                            ),
                        )
                    )
            for message_artifact in completed_result_messages:
                message = message_artifact.value
                assert isinstance(message, MailboxMessage)
                if message.task_id is None or message.task_id not in task_by_id:
                    raise WorkflowFinalReportError(
                        "Accepted Agent Result has no exact Task binding."
                    )
                task = task_by_id[message.task_id]
                if task.kind is not TaskKind.REVIEW:
                    continue
                try:
                    review_reference = bind_review_task_result_evidence(
                        graph,
                        message,
                        accepted_result_references_by_task,
                    )
                    review = load_independent_review(
                        verify_workflow_reference(
                            root,
                            NativeArtifactBinding(
                                "independent-review",
                                "independent-review",
                                review_reference,
                                True,
                            ),
                        )
                    )
                except (OSError, ValueError) as exc:
                    raise WorkflowFinalReportError(
                        "Independent Review lacks exact target Agent Result lineage."
                    ) from exc
                review_binding = expected_review_bindings.get(review.review_id)
                review_result = accepted_results_by_task.get(task.task_id)
                if (
                    review_binding is None
                    or review_binding.reference != review_reference
                    or review.review_id in seen_review_bindings
                    or review_result is None
                    or review.candidate != plan.candidate
                ):
                    raise WorkflowFinalReportError(
                        "Independent Review binding or reviewed Agent Results are stale."
                    )
                try:
                    validate_reviewed_agent_identities(
                        task,
                        review_result,
                        review,
                        accepted_results_by_task,
                    )
                except ValueError as exc:
                    raise WorkflowFinalReportError(
                        "Independent Review binding or reviewed Agent Results are stale."
                    ) from exc
                seen_review_bindings.add(review.review_id)
            if set(expected_agent_bindings) != seen_agent_bindings:
                raise WorkflowFinalReportError(
                    "State Agent Result bindings are not accepted M6 Task Results."
                )
            if set(expected_skill_bindings) != seen_skill_bindings:
                raise WorkflowFinalReportError(
                    "State Skill bindings are not exact accepted-result provenance."
                )
            if set(expected_review_bindings) != seen_review_bindings:
                raise WorkflowFinalReportError(
                    "State Independent Review bindings lack exact accepted-result lineage."
                )
            tagged_claims.extend(
                ("accepted-agents", assessment)
                for assessment in classify_agent_findings(tuple(accepted_results))
            )

            solver_results: dict[str, tuple[NativeArtifactBinding, SolverResult]] = {}
            solver_verifications: list[tuple[NativeArtifactBinding, SolverVerification]] = []
            for binding in state.observation_artifacts:
                if binding.artifact_type == SolverArtifactType.RESULT.value:
                    loaded = load_solver_artifact(
                        binding_paths[binding.artifact_id],
                        expected_type=SolverArtifactType.RESULT,
                    )
                    if loaded.artifact_id != binding.artifact_id or not isinstance(
                        loaded.value, SolverResult
                    ):
                        raise WorkflowFinalReportError(
                            "Solver Result binding does not match its exact artifact."
                        )
                    solver_results[loaded.artifact_id] = (binding, loaded.value)
                elif binding.artifact_type == SolverArtifactType.VERIFICATION.value:
                    loaded = load_solver_artifact(
                        binding_paths[binding.artifact_id],
                        expected_type=SolverArtifactType.VERIFICATION,
                    )
                    if loaded.artifact_id != binding.artifact_id or not isinstance(
                        loaded.value, SolverVerification
                    ):
                        raise WorkflowFinalReportError(
                            "Solver Verification binding does not match its exact artifact."
                        )
                    solver_verifications.append((binding, loaded.value))
            if set(state.solver_verification_ids) != {
                binding.artifact_id for binding, _ in solver_verifications
            }:
                raise WorkflowFinalReportError(
                    "Workflow solver verification identifiers and bindings disagree."
                )
            for binding, verification in solver_verifications:
                result_pair = solver_results.get(verification.result_id)
                solver_task = task_by_id.get(verification.task_id)
                if (
                    result_pair is None
                    or result_pair[0].reference != verification.result
                    or solver_task is None
                    or verification.graph_id != graph_artifact.artifact_id
                ):
                    raise WorkflowFinalReportError(
                        "Solver Verification lacks its exact Result or Task lineage."
                    )
                solver_result = result_pair[1]
                if (
                    verification.request != solver_result.request
                    or verification.request_id != solver_result.request_id
                    or verification.contract_id != solver_result.contract_id
                    or verification.candidate != solver_result.candidate
                    or verification.graph_id != solver_result.graph_id
                    or verification.task_id != solver_result.task_id
                    or verification.context_snapshot_id
                    != solver_result.context_snapshot_id
                    or verification.lease != solver_result.lease
                ):
                    raise WorkflowFinalReportError(
                        "Solver Verification and Result lineage do not match exactly."
                    )
                tagged_claims.append(
                    (
                        binding.artifact_id,
                        classify_solver_verification_claim(
                            f"SOLVER-{binding.artifact_id}",
                            (
                                f"Solver verification {binding.artifact_id} permits "
                                f"adoption of result {verification.result_id}."
                            ),
                            verification,
                            verification_id=binding.artifact_id,
                            expected_candidate=plan.candidate,
                            expected_context_snapshot_id=solver_task.context_snapshot_id,
                        ),
                    )
                )

            baseline_binding = NativeArtifactBinding(
                "requirement-baseline",
                plan.requirement_baseline_id,
                plan.requirement_baseline,
                True,
            )
            baseline = load_baseline(verify_workflow_reference(root, baseline_binding))
            if (
                baseline.baseline_id != plan.requirement_baseline_id
                or baseline.source.sha256 != plan.candidate.source_spec_sha256
            ):
                raise WorkflowFinalReportError(
                    "Requirement Baseline does not match the terminal Plan."
                )
            for requirement in baseline.requirements:
                references = (
                    f"{requirement.source.document}:{requirement.source.line_start}",
                    requirement.requirement_id,
                )
                if requirement.requirement_type is RequirementType.ASSUMPTION:
                    tagged_claims.append(
                        (
                            requirement.requirement_id,
                            classify_assumption(
                                f"ASSUMPTION-{requirement.requirement_id}",
                                requirement.statement,
                                source_id=f"{baseline.baseline_id}:{requirement.requirement_id}",
                                references=references,
                            ),
                        )
                    )
                tagged_claims.extend(
                    (
                        f"{requirement.requirement_id}:{index}",
                        classify_assumption(
                            f"ASSUMPTION-{requirement.requirement_id}-{index}",
                            statement,
                            source_id=f"{baseline.baseline_id}:{requirement.requirement_id}",
                            references=references,
                        ),
                    )
                    for index, statement in enumerate(requirement.assumptions, start=1)
                )

            claims = _unique_report_claims(tuple(tagged_claims))
            blockers = tuple(
                f"{blocker.code}: {', '.join(blocker.references)}"
                if blocker.references
                else blocker.code
                for blocker in outcome.blockers
            )
            return build_workflow_final_report(
                outcome_id=outcome_artifact.artifact_id,
                plan_id=plan_artifact.artifact_id,
                terminal_state_id=state_artifact.artifact_id,
                candidate=plan.candidate,
                disposition=outcome.disposition.value,
                aggregate_claim_state=outcome.claim_state.value,
                claims=claims,
                blockers=blockers,
                ambiguities=outcome.ambiguities,
                limitations=tuple(sorted(limitations)),
            )
        except WorkflowFinalReportError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkflowFinalReportError(
                "Workflow final report inputs failed exact read-only validation."
            ) from exc


def _report_values(
    outcome_artifact: LoadedWorkflowArtifact,
    state_artifact: LoadedWorkflowArtifact,
    plan_artifact: LoadedWorkflowArtifact,
) -> tuple[IntegratedPlan, WorkflowState, WorkflowOutcome]:
    if outcome_artifact.artifact_type is not WorkflowArtifactType.WORKFLOW_OUTCOME:
        raise WorkflowFinalReportError("Workflow report requires Workflow Outcome.")
    if state_artifact.artifact_type is not WorkflowArtifactType.WORKFLOW_STATE:
        raise WorkflowFinalReportError("Workflow report requires Workflow State.")
    if plan_artifact.artifact_type is not WorkflowArtifactType.INTEGRATED_PLAN:
        raise WorkflowFinalReportError("Workflow report requires Integrated Plan.")
    plan = plan_artifact.value
    state = state_artifact.value
    outcome = outcome_artifact.value
    if not isinstance(plan, IntegratedPlan):
        raise WorkflowFinalReportError("Workflow report Plan value is invalid.")
    if not isinstance(state, WorkflowState):
        raise WorkflowFinalReportError("Workflow report State value is invalid.")
    if not isinstance(outcome, WorkflowOutcome):
        raise WorkflowFinalReportError("Workflow report Outcome value is invalid.")
    if (
        state.plan_id != plan_artifact.artifact_id
        or outcome.plan_id != plan_artifact.artifact_id
        or outcome.terminal_state_id != state_artifact.artifact_id
        or state.candidate != plan.candidate
        or outcome.candidate != plan.candidate
        or state.observation_artifacts != outcome.observation_artifacts
        or state.solver_verification_ids != outcome.solver_verification_ids
        or state.evidence_ids != outcome.evidence_ids
        or state.review_ids != outcome.review_ids
    ):
        raise WorkflowFinalReportError(
            "Workflow Outcome, State, and Plan lineage does not match exactly."
        )
    return plan, state, outcome


def _unique_report_claims(
    tagged: tuple[tuple[str, WorkflowClaimAssessment], ...],
) -> tuple[WorkflowClaimAssessment, ...]:
    counts: dict[str, int] = {}
    for _, assessment in tagged:
        counts[assessment.claim_id] = counts.get(assessment.claim_id, 0) + 1
    resolved: list[WorkflowClaimAssessment] = []
    used: set[str] = set()
    for namespace, assessment in tagged:
        identifier = assessment.claim_id
        if counts[identifier] > 1:
            identifier = f"{identifier}@{namespace}"
        if identifier in used:
            raise WorkflowFinalReportError(
                "Workflow report propositions remain ambiguous after source qualification."
            )
        used.add(identifier)
        resolved.append(replace(assessment, claim_id=identifier))
    return tuple(sorted(resolved, key=lambda item: item.claim_id))


class WorkflowExplanationError(WorkflowContractError):
    """A Plan cannot be reproduced exactly from its native references."""


class WorkflowExplainer:
    """Recompute every Plan decision instead of trusting saved prose."""

    def __init__(self, planner: IntegratedPlanner) -> None:
        self._planner = planner

    def explain(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        *,
        predecessor_scheduler_state: Path | None = None,
    ) -> dict[str, object]:
        """Return exact JSON-ready selection, exclusion, and blocker reasons."""

        explanation, _observation = self.explain_with_observation(
            plan_artifact,
            root,
            scheduler_state,
            predecessor_scheduler_state=predecessor_scheduler_state,
        )
        return explanation

    def explain_with_observation(
        self,
        plan_artifact: LoadedWorkflowArtifact,
        root: Path,
        scheduler_state: Path,
        *,
        predecessor_scheduler_state: Path | None = None,
    ) -> tuple[dict[str, object], WorkflowPublicationObservation]:
        """Return the explanation and the single observation consumed to derive it."""

        if plan_artifact.artifact_type is not WorkflowArtifactType.INTEGRATED_PLAN:
            raise WorkflowExplanationError("Workflow explanation requires Integrated Plan.")
        plan = plan_artifact.value
        assert isinstance(plan, IntegratedPlan)
        if (plan.predecessor_plan_id is not None) != (
            predecessor_scheduler_state is not None
        ):
            raise WorkflowExplanationError(
                "Predecessor scheduler state is required exactly for a successor Plan."
            )
        intent_path = verify_workflow_reference(root, plan.intent)
        intent_artifact = load_workflow_artifact(
            intent_path,
            expected_type=WorkflowArtifactType.DEVELOPMENT_INTENT,
        )
        if intent_artifact.artifact_id != plan.intent.artifact_id:
            raise WorkflowExplanationError("Plan Intent identity drifted.")
        intent = intent_artifact.value
        assert isinstance(intent, DevelopmentIntent)
        publication_scheduler_state = (
            scheduler_state
            if predecessor_scheduler_state is None
            else predecessor_scheduler_state
        )
        observation = self._planner._verify_candidate(
            root,
            intent,
            publication_scheduler_state,
            require_scheduler_candidate=predecessor_scheduler_state is None,
        )
        reproduced = self._planner.plan(
            intent_artifact,
            plan.intent.reference,
            root,
            scheduler_state,
            publication_observation=observation,
            predecessor_scheduler_state=predecessor_scheduler_state,
        )
        if reproduced.artifact_id != plan_artifact.artifact_id:
            raise WorkflowExplanationError("Integrated Plan does not reproduce exactly.")
        selected = tuple(
            item.to_dict() for item in plan.decisions if item.kind is WorkflowDecisionKind.SELECTED
        )
        excluded = tuple(
            item.to_dict() for item in plan.decisions if item.kind is WorkflowDecisionKind.EXCLUDED
        )
        uncertainties = tuple(
            item.to_dict()
            for item in plan.decisions
            if item.kind is WorkflowDecisionKind.UNCERTAINTY
        )
        approvals = tuple(
            {
                "effect_id": effect.effect_id,
                "task_id": effect.task_id,
                "approval_types": list(effect.approval_types),
                "fresh_native_revalidation_required": True,
                "intent_grants_authority": False,
            }
            for effect in plan.protected_effects
        )
        evidence = tuple(
            {
                "task_id": task.task_id,
                "predicates": list(task.evidence_predicates),
                "future_observation_only": True,
            }
            for task in plan.tasks
        )
        blocking = tuple(item.reason_code for item in plan.decisions if item.blocking)
        return {
            "plan_id": plan_artifact.artifact_id,
            "intent_id": intent_artifact.artifact_id,
            "deterministic": True,
            "side_effect_free": True,
            "selection": list(selected),
            "exclusion": list(excluded),
            "uncertainty": list(uncertainties),
            "budget": plan.budget.to_dict(),
            "approval": list(approvals),
            "evidence": list(evidence),
            "gates": list(plan.required_gate_ids),
            "completion": {
                "profile": plan.completion_profile.value,
                "blocking_reason_codes": list(blocking),
                "handoff_required": plan.completion_profile.value != "plan-only",
                "outcome_may_not_upgrade_native_status": True,
            },
        }, observation
