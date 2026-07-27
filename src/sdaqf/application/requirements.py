"""Bounded Markdown ingestion and deterministic requirement normalization."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.requirements import (
    AcceptanceCriterion,
    Diagnostic,
    DiagnosticKind,
    DiagnosticSeverity,
    RequirementBaseline,
    RequirementPriority,
    RequirementRecord,
    RequirementType,
    SourceMetadata,
    SourceTrace,
    TraceLinks,
    generated_requirement_id,
)

_EXPLICIT_ITEM = re.compile(
    r"^\s*(?:[-*]\s+)?`(?P<identifier>[A-Z][A-Z0-9-]+)`:\s*(?P<statement>.*)$"
)
_NUMBERED_ITEM = re.compile(r"^\s*\d+[.)]\s+(?P<statement>.+)$")
_BULLET_ITEM = re.compile(r"^\s*[-*]\s+(?P<statement>.+)$")
_HEADING = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
_SAFE_ID = re.compile(r"^[A-Z][A-Z0-9-]*$")
_SPACE = re.compile(r"\s+")
_MARKUP = re.compile(r"[`*_~\[\]<>]")
_NEGATION = re.compile(r"\b(?:not|never|no)\b", re.IGNORECASE)
_CONTRADICTION_NOISE = re.compile(
    r"\b(?:must|shall|should|may|do|does|the|a|an)\b", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    identifier: str | None
    statement: str
    section: str
    line_start: int
    line_end: int
    excerpt: str


class SpecificationError(ValueError):
    """A safe, user-correctable specification intake failure."""


class SpecificationIngestor:
    """Ingest one bounded UTF-8 Markdown specification without executing it."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_bytes = max_bytes

    def ingest(self, path: Path) -> RequirementBaseline:
        """Read, validate, and normalize a Markdown source."""

        if path.suffix.lower() not in {".md", ".markdown"}:
            raise SpecificationError("Specification must be a Markdown file.")
        if path.is_symlink() or is_reparse_point(path) or not path.is_file():
            raise SpecificationError("Specification must be a regular, unlinked file.")
        try:
            stat_before = path.stat()
        except OSError as exc:
            raise SpecificationError("Specification metadata could not be read.") from exc
        if stat_before.st_size > self._max_bytes:
            raise SpecificationError("Specification exceeds the configured size limit.")
        try:
            payload = path.read_bytes()
            stat_after = path.stat()
        except OSError as exc:
            raise SpecificationError("Specification could not be read.") from exc
        if path.is_symlink() or is_reparse_point(path):
            raise SpecificationError("Specification must be a regular, unlinked file.")
        if (
            stat_before.st_size != stat_after.st_size
            or stat_before.st_mtime_ns != stat_after.st_mtime_ns
        ):
            raise SpecificationError("Specification changed during ingestion.")
        if len(payload) > self._max_bytes:
            raise SpecificationError("Specification exceeds the configured size limit.")
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SpecificationError("Specification must be valid UTF-8.") from exc
        if "\x00" in text:
            raise SpecificationError("Specification must not contain NUL bytes.")

        imported = self._clock()
        if imported.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        digest = hashlib.sha256(payload).hexdigest().upper()
        source = SourceMetadata(
            filename=path.name,
            path=_safe_display_path(path),
            sha256=digest,
            size_bytes=len(payload),
            modified_at=datetime.fromtimestamp(stat_after.st_mtime, UTC).isoformat(),
            imported_at=imported.astimezone(UTC).isoformat(),
        )
        candidates = _extract_candidates(text)
        requirements, source_criteria, diagnostics = _normalize_candidates(
            candidates, document=path.name
        )
        if not requirements:
            raise SpecificationError(
                "Specification contains no recognized requirement records."
            )
        return RequirementBaseline(
            baseline_id=f"RB-{digest[:16]}",
            source=source,
            requirements=requirements,
            source_acceptance_criteria=source_criteria,
            diagnostics=diagnostics,
        )


def _safe_display_path(path: Path) -> str:
    if path.is_absolute() or ".." in path.parts:
        return path.name
    normalized = path.as_posix()
    return normalized if normalized not in {"", "."} else path.name


def _extract_candidates(text: str) -> tuple[_Candidate, ...]:
    lines = text.splitlines()
    headings: list[tuple[int, str]] = []
    candidates: list[_Candidate] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group("level"))
            headings = [item for item in headings if item[0] < level]
            headings.append((level, _clean_text(heading.group("title"))))
            index += 1
            continue

        explicit = _EXPLICIT_ITEM.match(line)
        numbered = _NUMBERED_ITEM.match(line)
        bullet = _BULLET_ITEM.match(line)
        section = " > ".join(title for _, title in headings) or "Document"
        selected: re.Match[str] | None = explicit
        if selected is None and _section_accepts_unlabelled(section):
            selected = numbered or bullet
        plain_statement = (
            line.strip()
            if selected is None
            and _section_accepts_plain_paragraph(section)
            and line.strip()
            else None
        )
        if selected is None and plain_statement is None:
            index += 1
            continue

        start = index
        statement_parts = [
            selected.group("statement") if selected is not None else plain_statement or ""
        ]
        plain_mode = selected is None
        index += 1
        while index < len(lines):
            continuation = lines[index]
            if (
                not continuation.strip()
                or _HEADING.match(continuation)
                or _EXPLICIT_ITEM.match(continuation)
                or _NUMBERED_ITEM.match(continuation)
                or _BULLET_ITEM.match(continuation)
            ):
                break
            if plain_mode or continuation[:1].isspace():
                statement_parts.append(continuation.strip())
                index += 1
                continue
            break
        statement = _clean_text(" ".join(statement_parts))
        if statement:
            candidates.append(
                _Candidate(
                    identifier=explicit.group("identifier") if explicit else None,
                    statement=statement,
                    section=section,
                    line_start=start + 1,
                    line_end=index,
                    excerpt="\n".join(lines[start:index]),
                )
            )
        if index == start:
            index += 1
    return tuple(candidates)


def _section_accepts_unlabelled(section: str) -> bool:
    lowered = section.casefold()
    return any(
        label in lowered
        for label in (
            "functional requirement",
            "non-functional requirement",
            "nonfunctional requirement",
            "constraint",
            "non-goal",
            "non goal",
            "assumption",
            "open decision",
        )
    )


def _section_accepts_plain_paragraph(section: str) -> bool:
    return "open decision" in section.casefold()


def _normalize_candidates(
    candidates: tuple[_Candidate, ...],
    *,
    document: str,
) -> tuple[
    tuple[RequirementRecord, ...],
    tuple[AcceptanceCriterion, ...],
    tuple[Diagnostic, ...],
]:
    candidates = tuple(
        expanded
        for candidate in candidates
        for expanded in _expand_open_decision_candidate(candidate)
    )
    requirement_candidates = tuple(
        candidate
        for candidate in candidates
        if candidate.identifier is None or not candidate.identifier.startswith("AC-")
    )
    source_criteria = tuple(
        AcceptanceCriterion(
            criterion_id=_require_identifier(candidate),
            statement=candidate.statement,
            verification_methods=("source-review",),
        )
        for candidate in candidates
        if candidate.identifier is not None and candidate.identifier.startswith("AC-")
    )

    records: list[RequirementRecord] = []
    diagnostics: list[Diagnostic] = []
    seen_ids: dict[str, RequirementRecord] = {}
    seen_statements: dict[str, RequirementRecord] = {}

    for candidate in requirement_candidates:
        requirement_type = _requirement_type(candidate)
        identifier = candidate.identifier or _generated_identifier(candidate, requirement_type)
        priority = _priority(candidate.statement)
        methods = _verification_methods(requirement_type)
        linked_criteria = tuple(
            criterion
            for criterion in source_criteria
            if criterion.criterion_id.startswith(f"AC-{identifier}-")
        )
        if not linked_criteria:
            linked_criteria = (
                AcceptanceCriterion(
                    criterion_id=f"AC-{identifier}-01",
                    statement=(
                        "Evidence confirms the normalized requirement: "
                        f"{candidate.statement}"
                    ),
                    verification_methods=methods,
                ),
            )
        assumptions: tuple[str, ...] = ()
        open_questions: tuple[str, ...] = ()
        if requirement_type is RequirementType.ASSUMPTION:
            assumptions = (candidate.statement,)
        if requirement_type is RequirementType.OPEN_DECISION:
            open_questions = (candidate.statement,)
        record = RequirementRecord(
            requirement_id=identifier,
            title=_title(candidate.statement),
            requirement_type=requirement_type,
            priority=priority,
            source=SourceTrace(
                document=document,
                section=candidate.section,
                line_start=candidate.line_start,
                line_end=candidate.line_end,
                excerpt=candidate.excerpt,
                derivation_basis=(
                    "Preserved from the explicit source identifier."
                    if candidate.identifier
                    else "Generated from the normalized statement digest."
                ),
            ),
            statement=candidate.statement,
            acceptance_criteria=linked_criteria,
            verification_methods=methods,
            assumptions=assumptions,
            open_questions=open_questions,
            trace_links=TraceLinks(),
            identifier_source="explicit" if candidate.identifier else "generated",
        )

        prior_id = seen_ids.get(identifier)
        if prior_id is not None:
            diagnostics.append(
                _diagnostic(
                    DiagnosticKind.DUPLICATE_IDENTIFIER,
                    DiagnosticSeverity.BLOCKER,
                    (identifier,),
                    "The source repeats a stable identifier.",
                    candidate,
                )
            )
            if _negative(prior_id.statement) != _negative(record.statement):
                diagnostics.append(
                    _diagnostic(
                        DiagnosticKind.CONTRADICTION,
                        DiagnosticSeverity.BLOCKER,
                        (identifier,),
                        "The repeated identifier has conflicting normative polarity.",
                        candidate,
                    )
                )
            continue

        statement_key = _statement_key(record.statement)
        prior_statement = seen_statements.get(statement_key)
        if prior_statement is not None:
            diagnostics.append(
                _diagnostic(
                    DiagnosticKind.DUPLICATE_STATEMENT,
                    DiagnosticSeverity.WARNING,
                    (prior_statement.requirement_id, identifier),
                    "Equivalent normalized requirement statements were found.",
                    candidate,
                )
            )
            if candidate.identifier is None:
                continue

        seen_ids[identifier] = record
        seen_statements[statement_key] = record
        records.append(record)
        diagnostics.extend(_language_diagnostics(record, candidate))

    diagnostics.extend(_contradiction_diagnostics(tuple(records)))
    return (
        tuple(sorted(records, key=lambda item: item.requirement_id)),
        tuple(sorted(source_criteria, key=lambda item: item.criterion_id)),
        tuple(sorted(diagnostics, key=lambda item: item.diagnostic_id)),
    )


def _expand_open_decision_candidate(candidate: _Candidate) -> tuple[_Candidate, ...]:
    if (
        candidate.identifier is not None
        or "open decision" not in candidate.section.casefold()
    ):
        return (candidate,)
    match = re.match(r"(?i)^the owner must decide\s+(.+?)[.]?$", candidate.statement)
    if match is None or "," not in match.group(1):
        return (candidate,)
    fragments = tuple(
        fragment.strip()
        for fragment in re.split(r",\s+(?:and\s+)?", match.group(1))
        if fragment.strip()
    )
    if len(fragments) < 2:
        return (candidate,)
    return tuple(
        _Candidate(
            identifier=None,
            statement=f"Decide {fragment}.",
            section=candidate.section,
            line_start=candidate.line_start,
            line_end=candidate.line_end,
            excerpt=candidate.excerpt,
        )
        for fragment in fragments
    )


def _require_identifier(candidate: _Candidate) -> str:
    if candidate.identifier is None or not _SAFE_ID.fullmatch(candidate.identifier):
        raise AssertionError("candidate does not have an explicit safe identifier")
    return candidate.identifier


def _generated_identifier(
    candidate: _Candidate, requirement_type: RequirementType
) -> str:
    return generated_requirement_id(candidate.statement, requirement_type)


def _requirement_type(candidate: _Candidate) -> RequirementType:
    identifier = candidate.identifier or ""
    if identifier.startswith("NFR-"):
        return RequirementType.NONFUNCTIONAL
    if identifier.startswith("NG-"):
        return RequirementType.NON_GOAL
    if identifier.startswith(("C-", "WKS-")):
        return RequirementType.CONSTRAINT
    if identifier.startswith("ASM-"):
        return RequirementType.ASSUMPTION
    if identifier.startswith("OD-"):
        return RequirementType.OPEN_DECISION
    section = candidate.section.casefold()
    if "non-functional" in section or "nonfunctional" in section:
        return RequirementType.NONFUNCTIONAL
    if "non-goal" in section or "non goal" in section:
        return RequirementType.NON_GOAL
    if "constraint" in section:
        return RequirementType.CONSTRAINT
    if "assumption" in section:
        return RequirementType.ASSUMPTION
    if "open decision" in section:
        return RequirementType.OPEN_DECISION
    return RequirementType.FUNCTIONAL


def _priority(statement: str) -> RequirementPriority:
    if re.search(r"\b(?:may|could)\b", statement, re.IGNORECASE):
        return RequirementPriority.COULD
    if re.search(r"\bshould\b", statement, re.IGNORECASE):
        return RequirementPriority.SHOULD
    return RequirementPriority.MUST


def _verification_methods(requirement_type: RequirementType) -> tuple[str, ...]:
    if requirement_type is RequirementType.FUNCTIONAL:
        return ("test",)
    if requirement_type is RequirementType.NONFUNCTIONAL:
        return ("test", "benchmark")
    if requirement_type is RequirementType.CONSTRAINT:
        return ("static-analysis", "source-review")
    return ("source-review",)


def _title(statement: str) -> str:
    cleaned = _MARKUP.sub("", statement).strip().rstrip(".")
    words = cleaned.split()
    if len(words) > 12:
        cleaned = " ".join(words[:12]) + "..."
    return cleaned[:100] or "Untitled requirement"


def _clean_text(value: str) -> str:
    return _SPACE.sub(" ", value).strip()


def _statement_key(statement: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", statement.casefold()).strip()


def _negative(statement: str) -> bool:
    return _NEGATION.search(statement) is not None


def _contradiction_key(statement: str) -> str:
    normalized = _NEGATION.sub(" ", statement.casefold())
    normalized = _CONTRADICTION_NOISE.sub(" ", normalized)
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _language_diagnostics(
    record: RequirementRecord, candidate: _Candidate
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    lowered = record.statement.casefold()
    ambiguity_terms = (
        "when practical",
        "where applicable",
        "if needed",
        "as appropriate",
        "normally",
        "few seconds",
    )
    unverifiable_terms = (
        "as soon as possible",
        "user-friendly",
        "high quality",
        "adequate",
        "sufficiently fast",
    )
    if any(term in lowered for term in ambiguity_terms):
        diagnostics.append(
            _diagnostic(
                DiagnosticKind.AMBIGUITY,
                DiagnosticSeverity.WARNING,
                (record.requirement_id,),
                "The statement contains a context-dependent term that requires interpretation.",
                candidate,
            )
        )
    if any(term in lowered for term in unverifiable_terms):
        severity = (
            DiagnosticSeverity.BLOCKER
            if record.priority is RequirementPriority.MUST
            else DiagnosticSeverity.WARNING
        )
        diagnostics.append(
            _diagnostic(
                DiagnosticKind.UNVERIFIABLE,
                severity,
                (record.requirement_id,),
                "The statement contains an unmeasured quality term.",
                candidate,
            )
        )
    if re.search(r"\b(?:if|unless|when)\b", lowered) and not record.assumptions:
        diagnostics.append(
            _diagnostic(
                DiagnosticKind.MISSING_ASSUMPTION,
                DiagnosticSeverity.INFO,
                (record.requirement_id,),
                "A source condition is present but its operating assumption is not explicit.",
                candidate,
            )
        )
    return diagnostics


def _contradiction_diagnostics(
    records: tuple[RequirementRecord, ...],
) -> list[Diagnostic]:
    by_key: dict[str, RequirementRecord] = {}
    diagnostics: list[Diagnostic] = []
    for record in records:
        key = _contradiction_key(record.statement)
        if not key:
            continue
        prior = by_key.get(key)
        if prior is None:
            by_key[key] = record
            continue
        if _negative(prior.statement) == _negative(record.statement):
            continue
        line_start = min(prior.source.line_start, record.source.line_start)
        line_end = max(prior.source.line_end, record.source.line_end)
        synthetic = _Candidate(
            identifier=None,
            statement="",
            section=record.source.section,
            line_start=line_start,
            line_end=line_end,
            excerpt="",
        )
        diagnostics.append(
            _diagnostic(
                DiagnosticKind.CONTRADICTION,
                DiagnosticSeverity.BLOCKER,
                (prior.requirement_id, record.requirement_id),
                "Two requirements have equivalent wording with conflicting polarity.",
                synthetic,
            )
        )
    return diagnostics


def _diagnostic(
    kind: DiagnosticKind,
    severity: DiagnosticSeverity,
    requirement_ids: tuple[str, ...],
    message: str,
    candidate: _Candidate,
) -> Diagnostic:
    stable = "|".join(
        (
            kind.value,
            ",".join(sorted(requirement_ids)),
            str(candidate.line_start),
            str(candidate.line_end),
            message,
        )
    )
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12].upper()
    return Diagnostic(
        diagnostic_id=f"DIAG-{digest}",
        kind=kind,
        severity=severity,
        requirement_ids=tuple(sorted(requirement_ids)),
        message=message,
        line_start=candidate.line_start,
        line_end=candidate.line_end,
    )
