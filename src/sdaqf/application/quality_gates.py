"""M3 implementation-evidence and independent-review Gates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.application.contracts import (
    ContractError,
    array_value,
    boolean_value,
    enum_value,
    load_json_object,
    object_value,
    only_keys,
    parse_candidate_identity,
    safe_relative_path,
    sha256,
    string_tuple,
    string_value,
    timestamp,
    verify_artifact,
)
from sdaqf.application.gates import GateEngine
from sdaqf.domain.models import GateCheck, GateResult
from sdaqf.domain.quality import (
    CandidateIdentity,
    ClaimCriticality,
    ClaimState,
    EvidenceLedger,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceType,
    FindingAcceptance,
    IndependentReview,
    ReviewArea,
    ReviewFinding,
    ReviewFindingSeverity,
    ReviewFindingStatus,
    ReviewStatus,
)
from sdaqf.domain.requirements import RequirementBaseline, RequirementPriority

_REVIEW_ID = re.compile(r"^REV-[A-Z0-9][A-Z0-9-]{0,63}$")
_AGENT_ID = re.compile(r"^AGT-[A-Z0-9][A-Z0-9-]{0,63}$")
_FINDING_ID = re.compile(r"^FND-[A-Z0-9][A-Z0-9-]{0,63}$")
_APPROVAL_ID = re.compile(r"^APR-[A-Z0-9][A-Z0-9-]{0,63}$")
_HARD_CRITICALITIES = {
    ClaimCriticality.MUST,
    ClaimCriticality.SECURITY,
    ClaimCriticality.DATA_LOSS,
    ClaimCriticality.DISCLOSURE,
}
_CONFORMANCE_TYPES = {
    EvidenceType.STATIC_ANALYSIS,
    EvidenceType.TYPE_CHECK,
    EvidenceType.BENCHMARK,
    EvidenceType.VISUAL,
    EvidenceType.MANUAL_REVIEW,
    EvidenceType.SOURCE_REVIEW,
}


class ImplementationEvidenceGateService:
    """Evaluate non-compensating Gate G2."""

    def evaluate(
        self,
        baseline: RequirementBaseline,
        ledger: EvidenceLedger,
        *,
        candidate: CandidateIdentity,
        root: Path,
    ) -> GateResult:
        """Return Gate G2 without inferring conformance from tests alone."""

        requirements = {item.requirement_id: item for item in baseline.requirements}
        acceptance = {
            criterion.criterion_id: (item.requirement_id, criterion)
            for item in baseline.requirements
            for criterion in item.acceptance_criteria
        }
        claim_ids = {item.claim_id for item in ledger.claims}
        evidence_by_claim = {
            claim_id: tuple(
                item for item in ledger.evidence if claim_id in item.claim_ids
            )
            for claim_id in claim_ids
        }
        references_valid = all(
            set(claim.requirement_ids) <= requirements.keys()
            and set(claim.acceptance_criteria) <= acceptance.keys()
            and all(
                acceptance[criterion_id][0] in claim.requirement_ids
                for criterion_id in claim.acceptance_criteria
                if criterion_id in acceptance
            )
            for claim in ledger.claims
        )
        must = tuple(
            item
            for item in baseline.requirements
            if item.priority is RequirementPriority.MUST
        )
        must_criteria = {
            criterion.criterion_id
            for item in must
            for criterion in item.acceptance_criteria
        }
        mapped_must_criteria = {
            criterion_id
            for claim in ledger.claims
            if set(claim.requirement_ids)
            & {item.requirement_id for item in must}
            for criterion_id in claim.acceptance_criteria
        }
        verified_claims = tuple(
            item for item in ledger.claims if item.state is ClaimState.VERIFIED
        )
        evidence_integrity = all(
            item.environment
            and item.commit == candidate.git_head
            and item.repository_digest == candidate.repository_digest
            and all(verify_artifact(root, artifact) for artifact in item.artifacts)
            and (item.status is not EvidenceStatus.PASS or bool(item.artifacts))
            for item in ledger.evidence
        )
        claim_consistency = all(
            _claim_evidence_consistent(
                claim.state,
                evidence_by_claim[claim.claim_id],
                ledger.diff_review_evidence_id,
            )
            for claim in ledger.claims
        )
        applicable_tests = all(
            not any(
                "test" in criterion.verification_methods
                for criterion_id in claim.acceptance_criteria
                if (
                    pair := acceptance.get(criterion_id)
                ) is not None
                for criterion in (pair[1],)
            )
            or any(
                evidence.status is EvidenceStatus.PASS
                and evidence.evidence_type is EvidenceType.TEST
                for evidence in evidence_by_claim[claim.claim_id]
            )
            for claim in verified_claims
        )
        must_claims = tuple(
            claim
            for claim in ledger.claims
            if set(claim.requirement_ids)
            & {item.requirement_id for item in must}
        )
        must_verified = (
            bool(must)
            and bool(must_claims)
            and all(claim.state is ClaimState.VERIFIED for claim in must_claims)
        )
        critical_failures = tuple(
            claim.claim_id
            for claim in ledger.claims
            if claim.criticality in _HARD_CRITICALITIES
            and (
                claim.state is not ClaimState.VERIFIED
                or any(
                    item.status is not EvidenceStatus.PASS
                    for item in evidence_by_claim[claim.claim_id]
                )
            )
        )
        diff_review = next(
            (
                item
                for item in ledger.evidence
                if item.evidence_id == ledger.diff_review_evidence_id
            ),
            None,
        )
        checks = (
            GateCheck(
                "G2-IDENTITY",
                ledger.baseline_id == baseline.baseline_id
                and ledger.source_spec_sha256 == baseline.source.sha256
                and ledger.source_spec_sha256 == candidate.source_spec_sha256
                and ledger.git_head == candidate.git_head
                and ledger.repository_digest == candidate.repository_digest,
                True,
                "Ledger baseline, specification, Git, and repository identities were checked.",
            ),
            GateCheck(
                "G2-TRACE",
                references_valid,
                True,
                "Claim requirement and acceptance references were checked.",
            ),
            GateCheck(
                "G2-MUST-MAPPING",
                bool(must_criteria) and must_criteria <= mapped_must_criteria,
                True,
                f"{len(must_criteria)} Must acceptance criteria require claim mappings.",
            ),
            GateCheck(
                "G2-EVIDENCE",
                bool(verified_claims) and evidence_integrity,
                True,
                "Evidence requires exact candidate identity and verified artifacts.",
            ),
            GateCheck(
                "G2-APPLICABLE-TESTS",
                applicable_tests,
                True,
                "Verified test-applicable claims require passing TEST evidence.",
            ),
            GateCheck(
                "G2-CONSISTENCY",
                claim_consistency
                and not any(
                    item.status is EvidenceStatus.FAIL for item in ledger.evidence
                ),
                True,
                "Claim states and all evidence states must be non-compensating.",
            ),
            GateCheck(
                "G2-MUST-VERIFIED",
                must_verified,
                True,
                "Every mapped Must claim must be verified for this M3 Gate.",
            ),
            GateCheck(
                "G2-DIFF-REVIEW",
                diff_review is not None
                and diff_review.evidence_type is EvidenceType.SOURCE_REVIEW
                and diff_review.status is EvidenceStatus.PASS,
                True,
                "A passing source diff review is named explicitly.",
            ),
            GateCheck(
                "G2-CRITICAL",
                not critical_failures,
                True,
                (
                    "No critical Must, security, data-loss, or disclosure failure exists."
                    if not critical_failures
                    else f"{len(critical_failures)} critical claims are not satisfied."
                ),
            ),
        )
        return GateEngine().evaluate("G2", checks)


def _claim_evidence_consistent(
    state: ClaimState,
    evidence: tuple[EvidenceRecord, ...],
    diff_review_evidence_id: str,
) -> bool:
    if not evidence:
        return False
    statuses = {item.status for item in evidence}
    passing_conformance = any(
        item.status is EvidenceStatus.PASS
        and item.evidence_type in _CONFORMANCE_TYPES
        and item.evidence_id != diff_review_evidence_id
        for item in evidence
    )
    explicit_unverified = any(
        item.evidence_type is EvidenceType.UNVERIFIED
        and item.status is EvidenceStatus.NOT_VERIFIED
        for item in evidence
    )
    if state is ClaimState.VERIFIED:
        return statuses == {EvidenceStatus.PASS} and passing_conformance
    if state is ClaimState.IMPLEMENTED:
        return (
            EvidenceStatus.PASS in statuses
            and EvidenceStatus.FAIL not in statuses
            and explicit_unverified
        )
    if state is ClaimState.UNVERIFIED:
        return statuses == {EvidenceStatus.NOT_VERIFIED} and explicit_unverified
    return EvidenceStatus.FAIL in statuses


def load_independent_review(path: Path) -> IndependentReview:
    """Load one bounded independent review result."""

    return parse_independent_review(load_json_object(path, "Independent review"))


def parse_independent_review(payload: object) -> IndependentReview:
    """Validate a decoded independent review result."""

    root = object_value(payload, "review")
    only_keys(
        root,
        {
            "schema_version",
            "review_id",
            "baseline_id",
            "candidate",
            "reviewed_at",
            "reviewer_id",
            "reviewed_agent_ids",
            "status",
            "read_only",
            "areas",
            "findings",
            "reviewed_paths",
            "changed_paths",
        },
        "review",
    )
    if string_value(root.get("schema_version"), "schema_version", maximum=10) != "1.0":
        raise ContractError("schema_version must be 1.0.")
    reviewer = _identifier(root.get("reviewer_id"), "reviewer_id", _AGENT_ID)
    reviewed = string_tuple(
        root.get("reviewed_agent_ids"),
        "reviewed_agent_ids",
        minimum=1,
    )
    if any(not _AGENT_ID.fullmatch(value) for value in reviewed):
        raise ContractError("reviewed_agent_ids contains an invalid identifier.")
    if reviewer in reviewed:
        raise ContractError("An independent reviewer cannot review itself.")
    areas = tuple(
        enum_value(ReviewArea, value, f"areas[{index}]")
        for index, value in enumerate(
            array_value(root.get("areas"), "areas", maximum=3)
        )
    )
    if len(areas) != len(set(areas)):
        raise ContractError("areas must contain unique values.")
    findings = tuple(
        _parse_finding(value, index)
        for index, value in enumerate(
            array_value(root.get("findings"), "findings", maximum=64)
        )
    )
    finding_ids = tuple(item.finding_id for item in findings)
    if finding_ids != tuple(sorted(set(finding_ids))):
        raise ContractError("findings must have unique identifiers in sorted order.")
    changed_paths = string_tuple(
        root.get("changed_paths"),
        "changed_paths",
        maximum=64,
    )
    reviewed_paths = tuple(
        safe_relative_path(value, f"reviewed_paths[{index}]")
        for index, value in enumerate(
            array_value(root.get("reviewed_paths"), "reviewed_paths", maximum=256)
        )
    )
    if not reviewed_paths or reviewed_paths != tuple(sorted(set(reviewed_paths))):
        raise ContractError("reviewed_paths must be non-empty, unique, and sorted.")
    return IndependentReview(
        review_id=_identifier(root.get("review_id"), "review_id", _REVIEW_ID),
        baseline_id=_baseline_id(root.get("baseline_id"), "baseline_id"),
        candidate=parse_candidate_identity(root.get("candidate"), "candidate"),
        reviewed_at=timestamp(root.get("reviewed_at"), "reviewed_at"),
        reviewer_id=reviewer,
        reviewed_agent_ids=reviewed,
        status=enum_value(ReviewStatus, root.get("status"), "status"),
        read_only=boolean_value(root.get("read_only"), "read_only"),
        areas=areas,
        findings=findings,
        reviewed_paths=reviewed_paths,
        changed_paths=changed_paths,
    )


class FindingAcceptanceLoader:
    """Validate exact Owner approval for one accepted critical finding."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def load(self, path: Path) -> FindingAcceptance:
        """Load one bounded acceptance approval."""

        return self.parse(
            load_json_object(
                path,
                "Finding acceptance approval",
                maximum_bytes=64 * 1024,
            )
        )

    def parse(self, payload: object) -> FindingAcceptance:
        """Validate a decoded exact Owner approval."""

        root = object_value(payload, "approval")
        only_keys(
            root,
            {
                "schema_version",
                "approval_id",
                "approval_type",
                "action",
                "scope",
                "risk",
                "status",
                "rationale",
                "reversible",
                "approved_by",
                "approved_at",
                "expires_at",
            },
            "approval",
        )
        constants = {
            "schema_version": "1.0",
            "approval_type": "owner",
            "action": "Accept independent review finding",
            "risk": "high",
            "status": "approved",
            "approved_by": "Owner",
        }
        for field, expected in constants.items():
            if string_value(root.get(field), field, maximum=100) != expected:
                raise ContractError(f"{field} does not match the approval contract.")
        if root.get("reversible") is not True:
            raise ContractError("reversible must be true.")
        scope = object_value(root.get("scope"), "scope")
        only_keys(
            scope,
            {
                "review_id",
                "finding_id",
                "finding_sha256",
                "candidate",
            },
            "scope",
        )
        approved_at = timestamp(root.get("approved_at"), "approved_at")
        expires_at = timestamp(root.get("expires_at"), "expires_at")
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        approved_time = datetime.fromisoformat(approved_at)
        if approved_time > now:
            raise ContractError("Approval time cannot be in the future.")
        expires_time = datetime.fromisoformat(expires_at)
        if expires_time <= approved_time:
            raise ContractError("Approval expiry must follow approval time.")
        if expires_time <= now:
            raise ContractError("Approval record has expired.")
        return FindingAcceptance(
            approval_id=_identifier(
                root.get("approval_id"),
                "approval_id",
                _APPROVAL_ID,
            ),
            review_id=_identifier(
                scope.get("review_id"),
                "scope.review_id",
                _REVIEW_ID,
            ),
            finding_id=_identifier(
                scope.get("finding_id"),
                "scope.finding_id",
                _FINDING_ID,
            ),
            finding_sha256=sha256(
                scope.get("finding_sha256"),
                "scope.finding_sha256",
            ),
            candidate=parse_candidate_identity(
                scope.get("candidate"),
                "scope.candidate",
            ),
            rationale=string_value(
                root.get("rationale"),
                "rationale",
                maximum=500,
            ),
            approved_at=approved_at,
            expires_at=expires_at,
        )


class IndependentReviewGateService:
    """Evaluate non-compensating Gate G3."""

    def evaluate(
        self,
        review: IndependentReview,
        *,
        baseline_id: str,
        candidate: CandidateIdentity,
        changed_paths: tuple[str, ...],
        candidate_paths: tuple[str, ...] = (),
        approvals: tuple[FindingAcceptance, ...] = (),
    ) -> GateResult:
        """Require logical independence and resolved material findings."""

        approval_ids = tuple(item.approval_id for item in approvals)
        approvals_unique = len(approval_ids) == len(set(approval_ids))
        scoped_approvals = {
            (
                item.review_id,
                item.finding_id,
                item.approval_id,
                item.finding_sha256,
                item.candidate,
            )
            for item in approvals
        }
        material_resolved = all(
            finding.status is ReviewFindingStatus.RESOLVED
            for finding in review.findings
            if finding.severity
            in {ReviewFindingSeverity.HIGH, ReviewFindingSeverity.MEDIUM}
        )
        critical_resolved = all(
            finding.status is ReviewFindingStatus.RESOLVED
            or (
                finding.status is ReviewFindingStatus.ACCEPTED
                and finding.approval_id is not None
                and (
                    review.review_id,
                    finding.finding_id,
                    finding.approval_id,
                    finding_digest(finding),
                    candidate,
                )
                in scoped_approvals
            )
            for finding in review.findings
            if finding.severity is ReviewFindingSeverity.CRITICAL
        )
        accepted_consistent = all(
            (
                finding.status is ReviewFindingStatus.ACCEPTED
                and finding.severity is ReviewFindingSeverity.CRITICAL
            )
            == (finding.approval_id is not None)
            for finding in review.findings
        )
        review_scope = changed_paths if changed_paths else candidate_paths
        checks = (
            GateCheck(
                "G3-CANDIDATE",
                review.baseline_id == baseline_id
                and review.candidate == candidate,
                True,
                "Review baseline and immutable candidate identity were checked.",
            ),
            GateCheck(
                "G3-COMPLETED",
                review.status is ReviewStatus.COMPLETED,
                True,
                "Independent review must be completed.",
            ),
            GateCheck(
                "G3-INDEPENDENCE",
                review.read_only
                and not review.changed_paths
                and review.reviewer_id not in review.reviewed_agent_ids,
                True,
                "Reviewer identity and read-only behavior were checked.",
            ),
            GateCheck(
                "G3-COVERAGE",
                set(review.areas) == set(ReviewArea)
                and bool(review.reviewed_paths)
                and bool(review_scope)
                and set(review_scope) <= set(review.reviewed_paths),
                True,
                "Required areas and the exact changed or full candidate scope were reviewed.",
            ),
            GateCheck(
                "G3-MATERIAL-FINDINGS",
                material_resolved,
                True,
                "Every High and Medium finding must be resolved.",
            ),
            GateCheck(
                "G3-CRITICAL-FINDINGS",
                critical_resolved,
                True,
                "Critical findings require resolution or exact Owner acceptance.",
            ),
            GateCheck(
                "G3-APPROVALS",
                approvals_unique and accepted_consistent,
                True,
                "Finding acceptance uses unique exact Owner approvals.",
            ),
        )
        return GateEngine().evaluate("G3", checks)


def finding_digest(finding: ReviewFinding) -> str:
    """Return the approval-stable digest of one exact finding."""

    payload = {
        "finding_id": finding.finding_id,
        "severity": finding.severity.value,
        "statement": finding.statement,
        "specification_refs": list(finding.specification_refs),
        "evidence_refs": list(finding.evidence_refs),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _parse_finding(value: object, index: int) -> ReviewFinding:
    where = f"findings[{index}]"
    item = object_value(value, where)
    only_keys(
        item,
        {
            "finding_id",
            "severity",
            "status",
            "statement",
            "specification_refs",
            "evidence_refs",
            "approval_id",
        },
        where,
    )
    return ReviewFinding(
        finding_id=_identifier(
            item.get("finding_id"),
            f"{where}.finding_id",
            _FINDING_ID,
        ),
        severity=enum_value(
            ReviewFindingSeverity,
            item.get("severity"),
            f"{where}.severity",
        ),
        status=enum_value(
            ReviewFindingStatus,
            item.get("status"),
            f"{where}.status",
        ),
        statement=string_value(
            item.get("statement"),
            f"{where}.statement",
            maximum=500,
        ),
        specification_refs=string_tuple(
            item.get("specification_refs"),
            f"{where}.specification_refs",
            minimum=1,
        ),
        evidence_refs=string_tuple(
            item.get("evidence_refs"),
            f"{where}.evidence_refs",
            minimum=1,
        ),
        approval_id=(
            None
            if item.get("approval_id") is None
            else _identifier(
                item.get("approval_id"),
                f"{where}.approval_id",
                _APPROVAL_ID,
            )
        ),
    )


def _identifier(value: object, where: str, pattern: re.Pattern[str]) -> str:
    text = string_value(value, where, maximum=100)
    if not pattern.fullmatch(text):
        raise ContractError(f"{where} is not a stable identifier.")
    return text


def _baseline_id(value: object, where: str) -> str:
    text = string_value(value, where, maximum=19)
    if not re.fullmatch(r"RB-[0-9A-F]{16}", text):
        raise ContractError(f"{where} is not a stable baseline identifier.")
    return text
