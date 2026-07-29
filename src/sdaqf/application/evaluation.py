"""Strict offline M4 sample normalization and comparative evaluation."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

from sdaqf.application.contracts import (
    ContractError,
    array_value,
    boolean_value,
    enum_value,
    integer_value,
    load_json_object,
    object_value,
    only_keys,
    path_free_text,
    path_free_tuple,
    safe_relative_path,
    sha256,
    string_tuple,
    string_value,
    timestamp,
)
from sdaqf.application.requirements import SpecificationIngestor
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.evaluation import (
    CauseAnalysis,
    CauseLayer,
    ChangeEvaluation,
    CostObservation,
    CostStatus,
    CriticalCategory,
    CriticalDefect,
    EvaluationComparison,
    EvaluationEvidence,
    EvaluationInputIdentity,
    EvaluationProject,
    EvaluationResult,
    EvaluationRun,
    EvaluationSuite,
    EvidenceStatus,
    EvidenceType,
    ExpectedRequirement,
    HandoffObservation,
    HandoffStatus,
    NormalizationExpectation,
    ReworkEvent,
    RunMetrics,
    Workflow,
)
from sdaqf.domain.requirements import RequirementPriority

_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_RUN_ID = re.compile(r"^RUN-[A-Z0-9][A-Z0-9-]{0,63}$")
_EVENT_ID = re.compile(r"^[A-Z][A-Z0-9-]{1,63}$")
_REQUIREMENT_ID = re.compile(r"^[A-Z][A-Z0-9-]{1,63}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$")
_PLATFORM = {"windows", "linux", "macos"}
_ARTIFACT_TYPES = {"skill", "template", "prompt"}


def load_normalization_expectation(path: Path) -> NormalizationExpectation:
    """Load one strict expected normalized projection."""

    root = load_json_object(path, "normalization expectation")
    only_keys(
        root,
        {
            "schema_version",
            "project_id",
            "source_sha256",
            "baseline_id",
            "requirements",
            "diagnostic_kinds",
        },
        "normalization expectation",
    )
    _require_version(root.get("schema_version"), "normalization expectation")
    project_id = _project_id(root.get("project_id"), "project_id")
    baseline_id = string_value(root.get("baseline_id"), "baseline_id", maximum=19)
    if not re.fullmatch(r"RB-[0-9A-F]{16}", baseline_id):
        raise ContractError("baseline_id is invalid.")
    requirements = tuple(
        _parse_expected_requirement(item, f"requirements[{index}]")
        for index, item in enumerate(
            array_value(root.get("requirements"), "requirements", maximum=128)
        )
    )
    if not requirements:
        raise ContractError("requirements must not be empty.")
    identifiers = [item.requirement_id for item in requirements]
    if identifiers != sorted(identifiers) or len(identifiers) != len(set(identifiers)):
        raise ContractError("requirements must be sorted and unique.")
    diagnostic_kinds = string_tuple(
        root.get("diagnostic_kinds"),
        "diagnostic_kinds",
        maximum=128,
    )
    if diagnostic_kinds != tuple(sorted(diagnostic_kinds)):
        raise ContractError("diagnostic_kinds must be sorted.")
    return NormalizationExpectation(
        project_id=project_id,
        source_sha256=sha256(root.get("source_sha256"), "source_sha256"),
        baseline_id=baseline_id,
        requirements=requirements,
        diagnostic_kinds=diagnostic_kinds,
    )


def load_evaluation_run(path: Path) -> EvaluationRun:
    """Load one bounded comparative-evaluation run record."""

    root = load_json_object(path, "evaluation run")
    only_keys(
        root,
        {
            "schema_version",
            "run_id",
            "workflow",
            "input_identity",
            "intervention",
            "intervention_sha256",
            "requirements_implemented",
            "scope_additions",
            "critical_defects",
            "rework_events",
            "approvals",
            "handoffs",
            "trace",
            "decisions",
            "evidence",
            "cause_analyses",
            "cost",
            "limitations",
        },
        "evaluation run",
    )
    _require_version(root.get("schema_version"), "evaluation run")
    run_id = string_value(root.get("run_id"), "run_id", maximum=68)
    if not _RUN_ID.fullmatch(run_id):
        raise ContractError("run_id is invalid.")
    run = EvaluationRun(
        run_id=run_id,
        workflow=enum_value(Workflow, root.get("workflow"), "workflow"),
        input_identity=_parse_input_identity(root.get("input_identity")),
        intervention=path_free_text(
            root.get("intervention"),
            "intervention",
            maximum=500,
        ),
        intervention_sha256=sha256(
            root.get("intervention_sha256"),
            "intervention_sha256",
        ),
        requirements_implemented=_requirement_ids(
            root.get("requirements_implemented"),
            "requirements_implemented",
        ),
        scope_additions=_event_ids(
            root.get("scope_additions"),
            "scope_additions",
        ),
        critical_defects=tuple(
            _parse_critical_defect(item, f"critical_defects[{index}]")
            for index, item in enumerate(
                array_value(
                    root.get("critical_defects"),
                    "critical_defects",
                    maximum=128,
                )
            )
        ),
        rework_events=tuple(
            _parse_rework_event(item, f"rework_events[{index}]")
            for index, item in enumerate(
                array_value(root.get("rework_events"), "rework_events", maximum=128)
            )
        ),
        approvals=_event_ids(root.get("approvals"), "approvals"),
        handoffs=tuple(
            _parse_handoff(item, f"handoffs[{index}]")
            for index, item in enumerate(
                array_value(root.get("handoffs"), "handoffs", maximum=64)
            )
        ),
        trace=path_free_tuple(root.get("trace"), "trace", minimum=1, maximum=128),
        decisions=path_free_tuple(
            root.get("decisions"),
            "decisions",
            minimum=1,
            maximum=128,
        ),
        evidence=tuple(
            _parse_evidence(item, f"evidence[{index}]")
            for index, item in enumerate(
                array_value(root.get("evidence"), "evidence", maximum=128)
            )
        ),
        cause_analyses=tuple(
            _parse_cause_analysis(item, f"cause_analyses[{index}]")
            for index, item in enumerate(
                array_value(
                    root.get("cause_analyses"),
                    "cause_analyses",
                    maximum=64,
                )
            )
        ),
        cost=_parse_cost(root.get("cost")),
        limitations=path_free_tuple(
            root.get("limitations"),
            "limitations",
            minimum=1,
            maximum=64,
        ),
    )
    _require_unique(run.scope_additions, "scope_additions")
    _require_unique(run.approvals, "approvals")
    _require_unique(tuple(item.defect_id for item in run.critical_defects), "defects")
    _require_unique(tuple(item.event_id for item in run.rework_events), "rework events")
    _require_unique(tuple(item.handoff_id for item in run.handoffs), "handoffs")
    evidence_ids = tuple(item.evidence_id for item in run.evidence)
    if not evidence_ids:
        raise ContractError("evidence must not be empty.")
    _require_unique(evidence_ids, "evidence")
    evidence_paths = tuple(item.path for item in run.evidence)
    _require_unique(evidence_paths, "evidence paths")
    signatures = Counter(item.failure_signature for item in run.rework_events)
    analysis_signatures = tuple(
        item.failure_signature for item in run.cause_analyses
    )
    _require_unique(analysis_signatures, "cause analyses")
    analyses = set(analysis_signatures)
    repeated = {signature for signature, count in signatures.items() if count > 1}
    if repeated != analyses:
        raise ContractError(
            "Repeated failures require cause analysis with exact signature coverage."
        )
    if any(
        not set(analysis.verification_evidence) <= set(evidence_ids)
        for analysis in run.cause_analyses
    ):
        raise ContractError("Cause analysis references unknown evidence.")
    evidence_by_id = {item.evidence_id: item for item in run.evidence}
    if any(
        analysis.status == "verified"
        and any(
            evidence_by_id[evidence_id].status is not EvidenceStatus.PASS
            for evidence_id in analysis.verification_evidence
        )
        for analysis in run.cause_analyses
    ):
        raise ContractError("Verified cause analysis requires passing evidence.")
    return run


def load_evaluation_suite(path: Path) -> EvaluationSuite:
    """Load one bounded evaluation-suite manifest."""

    root = load_json_object(path, "evaluation suite")
    only_keys(
        root,
        {"schema_version", "suite_id", "projects", "changes", "limitations"},
        "evaluation suite",
    )
    _require_version(root.get("schema_version"), "evaluation suite")
    suite_id = string_value(root.get("suite_id"), "suite_id", maximum=68)
    if not re.fullmatch(r"EVS-[A-Z0-9][A-Z0-9-]{0,63}", suite_id):
        raise ContractError("suite_id is invalid.")
    projects = tuple(
        _parse_project(item, f"projects[{index}]")
        for index, item in enumerate(
            array_value(root.get("projects"), "projects", maximum=32)
        )
    )
    if len(projects) < 3:
        raise ContractError("An M4 evaluation suite requires at least three projects.")
    project_ids = tuple(item.project_id for item in projects)
    _require_unique(project_ids, "project identifiers")
    if project_ids != tuple(sorted(project_ids)):
        raise ContractError("projects must be sorted by project_id.")
    changes = tuple(
        _parse_change(item, f"changes[{index}]")
        for index, item in enumerate(
            array_value(root.get("changes"), "changes", maximum=64)
        )
    )
    if not changes:
        raise ContractError("changes must include before/after evaluation.")
    _require_unique(tuple(item.change_id for item in changes), "change identifiers")
    return EvaluationSuite(
        suite_id=suite_id,
        projects=projects,
        changes=changes,
        limitations=path_free_tuple(
            root.get("limitations"),
            "limitations",
            minimum=1,
            maximum=64,
        ),
    )


class EvaluationService:
    """Validate sample normalization, parity, metrics, and recorded results."""

    def evaluate(self, suite_path: Path) -> EvaluationResult:
        """Evaluate all paired project records without an aggregate score."""

        suite = load_evaluation_suite(suite_path)
        base = suite_path.resolve(strict=True).parent
        comparisons: list[EvaluationComparison] = []
        runs: dict[str, EvaluationRun] = {}
        for project in suite.projects:
            specification = _suite_member(base, project.specification)
            task = _suite_member(base, project.task)
            structured_instructions = _suite_member(
                base,
                project.structured_instructions,
            )
            unstructured_instructions = _suite_member(
                base,
                project.unstructured_instructions,
            )
            expectation = load_normalization_expectation(
                _suite_member(base, project.expectation)
            )
            structured = load_evaluation_run(
                _suite_member(base, project.structured_run)
            )
            unstructured = load_evaluation_run(
                _suite_member(base, project.unstructured_run)
            )
            self._validate_evidence(base, structured)
            self._validate_evidence(base, unstructured)
            self._validate_project(
                project,
                specification,
                task,
                structured_instructions,
                unstructured_instructions,
                expectation,
                structured,
                unstructured,
            )
            for run in (structured, unstructured):
                if run.run_id in runs:
                    raise ContractError("Evaluation run identifiers must be unique.")
                runs[run.run_id] = run
            comparisons.append(
                EvaluationComparison(
                    project_id=project.project_id,
                    structured_run_id=structured.run_id,
                    unstructured_run_id=unstructured.run_id,
                    structured=_metrics(expectation, structured),
                    unstructured=_metrics(expectation, unstructured),
                )
            )
        self._validate_changes(suite, runs)
        blockers = tuple(
            sorted(
                f"{comparison.project_id}:{workflow}:{blocker}"
                for comparison in comparisons
                for workflow, metrics in (
                    ("structured", comparison.structured),
                    ("unstructured", comparison.unstructured),
                )
                for blocker in metrics.hard_blockers
            )
        )
        limitations = tuple(
            sorted(
                {
                    *suite.limitations,
                    *(
                        limitation
                        for run in runs.values()
                        for limitation in run.limitations
                    ),
                }
            )
        )
        return EvaluationResult(
            suite_id=suite.suite_id,
            comparisons=tuple(comparisons),
            limitations=limitations,
            hard_blockers=blockers,
        )

    def validate_recorded_result(
        self,
        path: Path,
        result: EvaluationResult,
    ) -> None:
        """Require a tracked result to equal the deterministic calculation."""

        recorded = load_json_object(path, "evaluation result")
        if recorded != result.to_dict():
            raise ContractError(
                "Recorded evaluation result does not match the deterministic result."
            )

    @staticmethod
    def _validate_project(
        project: EvaluationProject,
        specification: Path,
        task: Path,
        structured_instructions: Path,
        unstructured_instructions: Path,
        expectation: NormalizationExpectation,
        structured: EvaluationRun,
        unstructured: EvaluationRun,
    ) -> None:
        if (
            project.project_id != expectation.project_id
            or project.project_id != structured.input_identity.project_id
            or project.project_id != unstructured.input_identity.project_id
        ):
            raise ContractError("Evaluation project identity is inconsistent.")
        baseline = SpecificationIngestor().ingest(specification)
        actual = NormalizationExpectation(
            project_id=project.project_id,
            source_sha256=baseline.source.sha256,
            baseline_id=baseline.baseline_id,
            requirements=tuple(
                ExpectedRequirement(
                    requirement_id=item.requirement_id,
                    requirement_type=item.requirement_type.value,
                    priority=item.priority.value,
                    statement=item.statement,
                    acceptance_ids=tuple(
                        criterion.criterion_id
                        for criterion in item.acceptance_criteria
                    ),
                    verification_methods=item.verification_methods,
                )
                for item in baseline.requirements
            ),
            diagnostic_kinds=tuple(
                sorted(item.kind.value for item in baseline.diagnostics)
            ),
        )
        if actual != expectation:
            raise ContractError(
                "Sample normalization does not match its expected projection."
            )
        if structured.workflow is not Workflow.STRUCTURED:
            raise ContractError("Structured run uses the wrong workflow.")
        if unstructured.workflow is not Workflow.UNSTRUCTURED:
            raise ContractError("Unstructured run uses the wrong workflow.")
        if structured.input_identity != unstructured.input_identity:
            raise ContractError("Evaluation input parity is not satisfied.")
        if (
            structured.input_identity.specification_sha256
            != expectation.source_sha256
        ):
            raise ContractError("Run specification identity is inconsistent.")
        task_digest = _file_sha256(task, "Evaluation task")
        if structured.input_identity.task_sha256 != task_digest:
            raise ContractError("Run task identity is inconsistent.")
        if structured.intervention_sha256 != _file_sha256(
            structured_instructions,
            "Structured intervention",
        ):
            raise ContractError("Structured intervention identity is inconsistent.")
        if unstructured.intervention_sha256 != _file_sha256(
            unstructured_instructions,
            "Unstructured intervention",
        ):
            raise ContractError("Unstructured intervention identity is inconsistent.")
        if structured.intervention_sha256 == unstructured.intervention_sha256:
            raise ContractError("Evaluation interventions must differ by content.")
        expected_ids = {item.requirement_id for item in expectation.requirements}
        for run in (structured, unstructured):
            if not set(run.requirements_implemented) <= expected_ids:
                raise ContractError(
                    "requirements_implemented contains an unknown requirement."
                )
            if any(
                not set(defect.requirement_ids) <= expected_ids
                for defect in run.critical_defects
            ):
                raise ContractError("Critical defect references an unknown requirement.")
        if structured.intervention == unstructured.intervention:
            raise ContractError("Evaluation intervention must be disclosed.")

    @staticmethod
    def _validate_evidence(base: Path, run: EvaluationRun) -> None:
        for evidence in run.evidence:
            artifact = _suite_member(base, evidence.path)
            if evidence.sha256 != _file_sha256(
                artifact,
                f"Evaluation evidence {evidence.evidence_id}",
            ):
                raise ContractError("Evaluation evidence identity is inconsistent.")

    @staticmethod
    def _validate_changes(
        suite: EvaluationSuite,
        runs: dict[str, EvaluationRun],
    ) -> None:
        for change in suite.changes:
            before = runs.get(change.before_run_id)
            after = runs.get(change.after_run_id)
            if before is None or after is None:
                raise ContractError("Change evaluation references an unknown run.")
            if before.input_identity != after.input_identity:
                raise ContractError("Change evaluation input identity is inconsistent.")
            if before.run_id == after.run_id:
                raise ContractError("Change evaluation requires distinct before and after runs.")
            if before.intervention_sha256 == after.intervention_sha256:
                raise ContractError("Change evaluation requires a changed intervention.")


def _metrics(
    expectation: NormalizationExpectation,
    run: EvaluationRun,
) -> RunMetrics:
    expected = {item.requirement_id: item for item in expectation.requirements}
    implemented = set(run.requirements_implemented)
    missed = set(expected) - implemented
    blockers = {
        f"MISSED-MUST:{identifier}"
        for identifier in missed
        if expected[identifier].priority == RequirementPriority.MUST.value
    }
    blockers.update(
        f"CRITICAL:{defect.category.value}:{defect.defect_id}"
        for defect in run.critical_defects
        if not defect.resolved
    )
    blockers.update(
        f"CAUSE-ANALYSIS-OPEN:{analysis.failure_signature}"
        for analysis in run.cause_analyses
        if analysis.status == "open"
    )
    return RunMetrics(
        missed_requirements=len(missed),
        scope_additions=len(run.scope_additions),
        critical_defects=len(run.critical_defects),
        rework=len(run.rework_events),
        approval_count=len(run.approvals),
        failed_handoffs=sum(
            item.status is HandoffStatus.FAILED for item in run.handoffs
        ),
        trace_steps=len(run.trace),
        decisions=len(run.decisions),
        evidence_items=len(run.evidence),
        cost=run.cost,
        hard_blockers=tuple(sorted(blockers)),
    )


def _parse_expected_requirement(value: object, where: str) -> ExpectedRequirement:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "requirement_id",
            "type",
            "priority",
            "statement",
            "acceptance_ids",
            "verification_methods",
        },
        where,
    )
    requirement_id = _requirement_id(item.get("requirement_id"), f"{where}.id")
    acceptance_ids = _requirement_ids(
        item.get("acceptance_ids"),
        f"{where}.acceptance_ids",
        minimum=1,
    )
    if any(not value.startswith(f"AC-{requirement_id}-") for value in acceptance_ids):
        raise ContractError(f"{where}.acceptance_ids is inconsistent.")
    priority = string_value(item.get("priority"), f"{where}.priority", maximum=20)
    if priority not in {value.value for value in RequirementPriority}:
        raise ContractError(f"{where}.priority is unsupported.")
    requirement_type = string_value(item.get("type"), f"{where}.type", maximum=30)
    if requirement_type not in {
        "functional",
        "nonfunctional",
        "constraint",
        "non-goal",
        "assumption",
        "open-decision",
    }:
        raise ContractError(f"{where}.type is unsupported.")
    return ExpectedRequirement(
        requirement_id=requirement_id,
        requirement_type=requirement_type,
        priority=priority,
        statement=path_free_text(
            item.get("statement"),
            f"{where}.statement",
            maximum=2_000,
        ),
        acceptance_ids=acceptance_ids,
        verification_methods=string_tuple(
            item.get("verification_methods"),
            f"{where}.verification_methods",
            minimum=1,
            maximum=16,
        ),
    )


def _parse_input_identity(value: object) -> EvaluationInputIdentity:
    item = object_value(value, "input_identity")
    only_keys(
        item,
        {
            "project_id",
            "specification_sha256",
            "task_sha256",
            "starting_repository_digest",
            "model_id",
            "client_surface",
            "platform",
            "python_version",
            "budget_units",
            "trial_id",
        },
        "input_identity",
    )
    platform = string_value(item.get("platform"), "input_identity.platform", maximum=20)
    if platform not in _PLATFORM:
        raise ContractError("input_identity.platform is unsupported.")
    python_version = string_value(
        item.get("python_version"),
        "input_identity.python_version",
        maximum=20,
    )
    if not _VERSION.fullmatch(python_version):
        raise ContractError("input_identity.python_version is invalid.")
    trial_id = string_value(
        item.get("trial_id"),
        "input_identity.trial_id",
        maximum=68,
    )
    if not re.fullmatch(r"TRIAL-[A-Z0-9][A-Z0-9-]{0,63}", trial_id):
        raise ContractError("input_identity.trial_id is invalid.")
    return EvaluationInputIdentity(
        project_id=_project_id(
            item.get("project_id"),
            "input_identity.project_id",
        ),
        specification_sha256=sha256(
            item.get("specification_sha256"),
            "input_identity.specification_sha256",
        ),
        task_sha256=sha256(
            item.get("task_sha256"),
            "input_identity.task_sha256",
        ),
        starting_repository_digest=sha256(
            item.get("starting_repository_digest"),
            "input_identity.starting_repository_digest",
        ),
        model_id=path_free_text(
            item.get("model_id"),
            "input_identity.model_id",
            maximum=100,
        ),
        client_surface=path_free_text(
            item.get("client_surface"),
            "input_identity.client_surface",
            maximum=100,
        ),
        platform=platform,
        python_version=python_version,
        budget_units=integer_value(
            item.get("budget_units"),
            "input_identity.budget_units",
            minimum=1,
            maximum=1_000_000,
        ),
        trial_id=trial_id,
    )


def _parse_critical_defect(value: object, where: str) -> CriticalDefect:
    item = object_value(value, where)
    only_keys(
        item,
        {"defect_id", "category", "requirement_ids", "description", "resolved"},
        where,
    )
    return CriticalDefect(
        defect_id=_event_id(item.get("defect_id"), f"{where}.defect_id"),
        category=enum_value(
            CriticalCategory,
            item.get("category"),
            f"{where}.category",
        ),
        requirement_ids=_requirement_ids(
            item.get("requirement_ids"),
            f"{where}.requirement_ids",
            minimum=1,
        ),
        description=path_free_text(
            item.get("description"),
            f"{where}.description",
            maximum=1_000,
        ),
        resolved=boolean_value(item.get("resolved"), f"{where}.resolved"),
    )


def _parse_rework_event(value: object, where: str) -> ReworkEvent:
    item = object_value(value, where)
    only_keys(item, {"event_id", "failure_signature", "description"}, where)
    return ReworkEvent(
        event_id=_event_id(item.get("event_id"), f"{where}.event_id"),
        failure_signature=_event_id(
            item.get("failure_signature"),
            f"{where}.failure_signature",
        ),
        description=path_free_text(
            item.get("description"),
            f"{where}.description",
            maximum=1_000,
        ),
    )


def _parse_handoff(value: object, where: str) -> HandoffObservation:
    item = object_value(value, where)
    only_keys(item, {"handoff_id", "status"}, where)
    return HandoffObservation(
        handoff_id=_event_id(item.get("handoff_id"), f"{where}.handoff_id"),
        status=enum_value(HandoffStatus, item.get("status"), f"{where}.status"),
    )


def _parse_evidence(value: object, where: str) -> EvaluationEvidence:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "evidence_id",
            "evidence_type",
            "status",
            "path",
            "sha256",
            "observed_at",
            "command",
        },
        where,
    )
    return EvaluationEvidence(
        evidence_id=_event_id(
            item.get("evidence_id"),
            f"{where}.evidence_id",
        ),
        evidence_type=enum_value(
            EvidenceType,
            item.get("evidence_type"),
            f"{where}.evidence_type",
        ),
        status=enum_value(
            EvidenceStatus,
            item.get("status"),
            f"{where}.status",
        ),
        path=safe_relative_path(item.get("path"), f"{where}.path"),
        sha256=sha256(item.get("sha256"), f"{where}.sha256"),
        observed_at=timestamp(item.get("observed_at"), f"{where}.observed_at"),
        command=path_free_text(
            item.get("command"),
            f"{where}.command",
            maximum=500,
        ),
    )


def _parse_cause_analysis(value: object, where: str) -> CauseAnalysis:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "failure_signature",
            "layers",
            "owner",
            "action",
            "status",
            "verification_evidence",
        },
        where,
    )
    layers = tuple(
        enum_value(CauseLayer, value, f"{where}.layers[{index}]")
        for index, value in enumerate(
            array_value(item.get("layers"), f"{where}.layers", maximum=5)
        )
    )
    if not layers or len(layers) != len(set(layers)):
        raise ContractError(f"{where}.layers must be non-empty and unique.")
    status = string_value(item.get("status"), f"{where}.status", maximum=20)
    if status not in {"open", "verified"}:
        raise ContractError(f"{where}.status is unsupported.")
    evidence = _event_ids(
        item.get("verification_evidence"),
        f"{where}.verification_evidence",
        minimum=1 if status == "verified" else 0,
    )
    if status == "open" and evidence:
        raise ContractError(f"{where}.verification_evidence contradicts open status.")
    return CauseAnalysis(
        failure_signature=_event_id(
            item.get("failure_signature"),
            f"{where}.failure_signature",
        ),
        layers=layers,
        owner=path_free_text(item.get("owner"), f"{where}.owner", maximum=100),
        action=path_free_text(item.get("action"), f"{where}.action", maximum=1_000),
        status=status,
        verification_evidence=evidence,
    )


def _parse_cost(value: object) -> CostObservation:
    item = object_value(value, "cost")
    only_keys(
        item,
        {
            "status",
            "elapsed_seconds",
            "tool_calls",
            "input_tokens",
            "output_tokens",
            "reason",
        },
        "cost",
    )
    status = enum_value(CostStatus, item.get("status"), "cost.status")
    names = ("elapsed_seconds", "tool_calls", "input_tokens", "output_tokens")
    raw_values = tuple(item.get(name) for name in names)
    values: tuple[int | None, ...]
    if status is CostStatus.AVAILABLE:
        values = tuple(
            integer_value(value, f"cost.{name}", minimum=0, maximum=1_000_000_000)
            for name, value in zip(names, raw_values, strict=True)
        )
        if item.get("reason") is not None:
            raise ContractError("cost.reason must be null when cost is available.")
        reason = None
    else:
        if any(value is not None for value in raw_values):
            raise ContractError("Unverified cost values must be null.")
        values = (None, None, None, None)
        reason = path_free_text(item.get("reason"), "cost.reason", maximum=500)
    return CostObservation(
        status=status,
        elapsed_seconds=values[0],
        tool_calls=values[1],
        input_tokens=values[2],
        output_tokens=values[3],
        reason=reason,
    )


def _parse_project(value: object, where: str) -> EvaluationProject:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "project_id",
            "specification",
            "task",
            "structured_instructions",
            "unstructured_instructions",
            "expectation",
            "structured_run",
            "unstructured_run",
        },
        where,
    )
    return EvaluationProject(
        project_id=_project_id(item.get("project_id"), f"{where}.project_id"),
        specification=safe_relative_path(
            item.get("specification"),
            f"{where}.specification",
        ),
        task=safe_relative_path(item.get("task"), f"{where}.task"),
        structured_instructions=safe_relative_path(
            item.get("structured_instructions"),
            f"{where}.structured_instructions",
        ),
        unstructured_instructions=safe_relative_path(
            item.get("unstructured_instructions"),
            f"{where}.unstructured_instructions",
        ),
        expectation=safe_relative_path(
            item.get("expectation"),
            f"{where}.expectation",
        ),
        structured_run=safe_relative_path(
            item.get("structured_run"),
            f"{where}.structured_run",
        ),
        unstructured_run=safe_relative_path(
            item.get("unstructured_run"),
            f"{where}.unstructured_run",
        ),
    )


def _parse_change(value: object, where: str) -> ChangeEvaluation:
    item = object_value(value, where)
    only_keys(
        item,
        {
            "change_id",
            "artifact_type",
            "artifact_id",
            "before_run_id",
            "after_run_id",
        },
        where,
    )
    artifact_type = string_value(
        item.get("artifact_type"),
        f"{where}.artifact_type",
        maximum=20,
    )
    if artifact_type not in _ARTIFACT_TYPES:
        raise ContractError(f"{where}.artifact_type is unsupported.")
    before = string_value(
        item.get("before_run_id"),
        f"{where}.before_run_id",
        maximum=68,
    )
    after = string_value(
        item.get("after_run_id"),
        f"{where}.after_run_id",
        maximum=68,
    )
    if not _RUN_ID.fullmatch(before) or not _RUN_ID.fullmatch(after):
        raise ContractError(f"{where} references an invalid run identifier.")
    return ChangeEvaluation(
        change_id=_event_id(item.get("change_id"), f"{where}.change_id"),
        artifact_type=artifact_type,
        artifact_id=path_free_text(
            item.get("artifact_id"),
            f"{where}.artifact_id",
            maximum=200,
        ),
        before_run_id=before,
        after_run_id=after,
    )


def _suite_member(base: Path, relative: str) -> Path:
    try:
        resolved_base = base.resolve(strict=True)
        candidate = resolved_base.joinpath(*Path(relative).parts)
        current = resolved_base
        for part in Path(relative).parts:
            current = current / part
            if current.is_symlink() or is_reparse_point(current):
                raise ContractError("Evaluation suite member contains a link.")
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ContractError("Evaluation suite member could not be resolved.") from exc
    if not resolved.is_relative_to(resolved_base) or not resolved.is_file():
        raise ContractError("Evaluation suite member is outside the suite.")
    return resolved


def _file_sha256(path: Path, label: str) -> str:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"{label} could not be read.") from exc
    if len(content) > 1_000_000:
        raise ContractError(f"{label} exceeds the size limit.")
    return hashlib.sha256(content).hexdigest().upper()


def _project_id(value: object, where: str) -> str:
    parsed = string_value(value, where, maximum=64)
    if not _PROJECT_ID.fullmatch(parsed):
        raise ContractError(f"{where} is invalid.")
    return parsed


def _requirement_id(value: object, where: str) -> str:
    parsed = string_value(value, where, maximum=64)
    if not _REQUIREMENT_ID.fullmatch(parsed):
        raise ContractError(f"{where} is invalid.")
    return parsed


def _requirement_ids(
    value: object,
    where: str,
    *,
    minimum: int = 0,
) -> tuple[str, ...]:
    parsed = tuple(
        _requirement_id(item, f"{where}[{index}]")
        for index, item in enumerate(array_value(value, where, maximum=256))
    )
    if len(parsed) < minimum:
        raise ContractError(f"{where} has too few items.")
    _require_unique(parsed, where)
    if parsed != tuple(sorted(parsed)):
        raise ContractError(f"{where} must be sorted.")
    return parsed


def _event_id(value: object, where: str) -> str:
    parsed = string_value(value, where, maximum=64)
    if not _EVENT_ID.fullmatch(parsed):
        raise ContractError(f"{where} is invalid.")
    return parsed


def _event_ids(
    value: object,
    where: str,
    *,
    minimum: int = 0,
) -> tuple[str, ...]:
    parsed = tuple(
        _event_id(item, f"{where}[{index}]")
        for index, item in enumerate(array_value(value, where, maximum=256))
    )
    if len(parsed) < minimum:
        raise ContractError(f"{where} has too few items.")
    _require_unique(parsed, where)
    if parsed != tuple(sorted(parsed)):
        raise ContractError(f"{where} must be sorted.")
    return parsed


def _require_unique(values: tuple[str, ...], where: str) -> None:
    if len(values) != len(set(value.casefold() for value in values)):
        raise ContractError(f"{where} must be unique.")


def _require_version(value: object, where: str) -> None:
    if string_value(value, f"{where}.schema_version", maximum=10) != "1.0":
        raise ContractError(f"{where}.schema_version must be 1.0.")
