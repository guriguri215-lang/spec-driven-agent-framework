"""Gate G1 evaluation for validated requirement baselines."""

from __future__ import annotations

import re

from sdaqf.application.comparison import BaselineDiff
from sdaqf.application.gates import GateEngine
from sdaqf.domain.models import GateCheck, GateResult
from sdaqf.domain.requirements import (
    DiagnosticSeverity,
    RequirementBaseline,
    RequirementPriority,
    RequirementType,
    generated_requirement_id,
)

_STABLE_ID = re.compile(r"^[A-Z][A-Z0-9-]*$")
_SHA256 = re.compile(r"^[0-9A-F]{64}$")


class RequirementsGateService:
    """Evaluate the non-compensating M1 requirements baseline Gate."""

    def evaluate(
        self,
        baseline: RequirementBaseline,
        *,
        comparison: BaselineDiff | None = None,
    ) -> GateResult:
        """Return Gate G1 with every hard blocker kept explicit."""

        requirements = baseline.requirements
        must = tuple(
            item for item in requirements if item.priority is RequirementPriority.MUST
        )
        ids = tuple(item.requirement_id for item in requirements)
        open_decisions = tuple(
            item
            for item in requirements
            if item.requirement_type is RequirementType.OPEN_DECISION
        )
        blocking_diagnostics = tuple(
            item
            for item in baseline.diagnostics
            if item.severity is DiagnosticSeverity.BLOCKER and item.status == "open"
        )
        baseline_unresolved = baseline.approval_required
        comparison_unresolved = (
            comparison.unresolved_approvals if comparison is not None else ()
        )
        checks = (
            GateCheck(
                "G1-SOURCE",
                bool(_SHA256.fullmatch(baseline.source.sha256))
                and baseline.source.size_bytes >= 0,
                True,
                "Source digest and bounded metadata are present.",
            ),
            GateCheck(
                "G1-STABLE-IDS",
                bool(ids)
                and len(ids) == len(set(ids))
                and all(_STABLE_ID.fullmatch(identifier) for identifier in ids)
                and all(
                    item.identifier_source != "generated"
                    or item.requirement_id
                    == generated_requirement_id(
                        item.statement, item.requirement_type
                    )
                    for item in requirements
                ),
                True,
                f"{len(ids)} normalized requirement identifiers were checked.",
            ),
            GateCheck(
                "G1-MUST-PRESENT",
                bool(must),
                True,
                f"{len(must)} Must requirements were found.",
            ),
            GateCheck(
                "G1-ACCEPTANCE",
                all(
                    item.acceptance_criteria
                    and all(
                        criterion.verification_methods
                        and criterion.criterion_id.startswith(
                            f"AC-{item.requirement_id}-"
                        )
                        for criterion in item.acceptance_criteria
                    )
                    for item in requirements
                ),
                True,
                (
                    f"All {len(requirements)} requirements were checked for "
                    "linked acceptance criteria."
                ),
            ),
            GateCheck(
                "G1-VERIFICATION",
                all(item.verification_methods for item in requirements),
                True,
                "Every normalized requirement declares a verification method.",
            ),
            GateCheck(
                "G1-SOURCE-TRACE",
                all(
                    item.source.document
                    and item.source.section
                    and item.source.line_start >= 1
                    and item.source.line_end >= item.source.line_start
                    and item.source.excerpt
                    and item.source.derivation_basis
                    for item in requirements
                ),
                True,
                "Every requirement preserves source location and derivation.",
            ),
            GateCheck(
                "G1-DOWNSTREAM-TRACE",
                all(
                    isinstance(item.trace_links.design, tuple)
                    and isinstance(item.trace_links.code, tuple)
                    and isinstance(item.trace_links.tests, tuple)
                    and isinstance(item.trace_links.evidence, tuple)
                    and isinstance(item.trace_links.releases, tuple)
                    for item in requirements
                ),
                False,
                "Design, code, test, evidence, and release links are explicit.",
            ),
            GateCheck(
                "G1-OPEN-DECISIONS",
                all(item.open_questions for item in open_decisions),
                True,
                f"{len(open_decisions)} open decisions preserve unresolved questions.",
            ),
            GateCheck(
                "G1-DIAGNOSTICS",
                not blocking_diagnostics,
                True,
                (
                    "No unresolved blocking diagnostic exists."
                    if not blocking_diagnostics
                    else f"{len(blocking_diagnostics)} unresolved blocking diagnostics exist."
                ),
            ),
            GateCheck(
                "G1-APPROVALS",
                not baseline_unresolved and not comparison_unresolved,
                True,
                (
                    "No unresolved removal or weakening approval exists."
                    if not baseline_unresolved and not comparison_unresolved
                    else "A removal or weakening still requires Owner approval."
                ),
            ),
            GateCheck(
                "G1-NO-UNVERIFIED-CLAIM",
                all(item.status in {"draft", "baselined"} for item in requirements),
                True,
                "The requirements baseline makes no implementation or verification claim.",
            ),
        )
        return GateEngine().evaluate("G1", checks)
