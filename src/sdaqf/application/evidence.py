"""Strict Claim-Evidence Ledger loading and atomic evidence addition."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from sdaqf.application.contracts import (
    ContractError,
    array_value,
    command_argv,
    commit,
    enum_value,
    load_json_object,
    object_value,
    only_keys,
    parse_artifact_reference,
    path_free_text,
    sha256,
    string_tuple,
    string_value,
    timestamp,
)
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.quality import (
    Claim,
    ClaimCriticality,
    ClaimState,
    Confidence,
    EvidenceLedger,
    EvidenceRecord,
    EvidenceStatus,
    EvidenceType,
)

_BASELINE_ID = re.compile(r"^RB-[0-9A-F]{16}$")
_CLAIM_ID = re.compile(r"^CLM-[A-Z0-9][A-Z0-9-]{0,63}$")
_EVIDENCE_ID = re.compile(r"^EV-[A-Z0-9][A-Z0-9-]{0,63}$")
_REQUIREMENT_ID = re.compile(r"^[A-Z][A-Z0-9-]{1,99}$")
_ACCEPTANCE_ID = re.compile(r"^AC-[A-Z0-9][A-Z0-9-]{1,119}$")
_ENVIRONMENT_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def load_evidence_ledger(path: Path) -> EvidenceLedger:
    """Load and validate one versioned Claim-Evidence Ledger."""

    return parse_evidence_ledger(load_json_object(path, "Evidence ledger"))


def parse_evidence_ledger(payload: object) -> EvidenceLedger:
    """Validate a decoded Claim-Evidence Ledger."""

    root = object_value(payload, "ledger")
    only_keys(
        root,
        {
            "schema_version",
            "baseline_id",
            "source_spec_sha256",
            "git_head",
            "repository_digest",
            "claims",
            "evidence",
            "diff_review_evidence_id",
        },
        "ledger",
    )
    if string_value(root.get("schema_version"), "schema_version", maximum=10) != "1.0":
        raise ContractError("schema_version must be 1.0.")
    baseline_id = _identifier(
        root.get("baseline_id"),
        "baseline_id",
        _BASELINE_ID,
    )
    claims = tuple(
        _parse_claim(value, index)
        for index, value in enumerate(
            array_value(root.get("claims"), "claims", maximum=1_024)
        )
    )
    if not claims:
        raise ContractError("claims must not be empty.")
    claim_ids = tuple(item.claim_id for item in claims)
    _ordered_unique(claim_ids, "claims")
    evidence = tuple(
        _parse_evidence(value, index, standalone=False)
        for index, value in enumerate(
            array_value(root.get("evidence"), "evidence", maximum=2_048)
        )
    )
    if not evidence:
        raise ContractError("evidence must not be empty.")
    evidence_ids = tuple(item.evidence_id for item in evidence)
    _ordered_unique(evidence_ids, "evidence")
    claim_id_set = set(claim_ids)
    for item in evidence:
        if not set(item.claim_ids) <= claim_id_set:
            raise ContractError(f"{item.evidence_id} references an unknown claim.")
    diff_review = _identifier(
        root.get("diff_review_evidence_id"),
        "diff_review_evidence_id",
        _EVIDENCE_ID,
    )
    review_item = next(
        (item for item in evidence if item.evidence_id == diff_review),
        None,
    )
    if (
        review_item is None
        or review_item.evidence_type is not EvidenceType.SOURCE_REVIEW
        or review_item.status is not EvidenceStatus.PASS
    ):
        raise ContractError(
            "diff_review_evidence_id must name passing SOURCE_REVIEW evidence."
        )
    return EvidenceLedger(
        baseline_id=baseline_id,
        source_spec_sha256=sha256(
            root.get("source_spec_sha256"),
            "source_spec_sha256",
        ),
        git_head=_required_commit(root.get("git_head"), "git_head"),
        repository_digest=sha256(
            root.get("repository_digest"),
            "repository_digest",
        ),
        claims=claims,
        evidence=evidence,
        diff_review_evidence_id=diff_review,
    )


def load_evidence_record(path: Path) -> EvidenceRecord:
    """Load one standalone evidence record for atomic addition."""

    return _parse_evidence(
        load_json_object(path, "Evidence record", maximum_bytes=64 * 1024),
        0,
        standalone=True,
    )


def parse_evidence_record(payload: object) -> EvidenceRecord:
    """Validate one decoded standalone evidence record."""

    return _parse_evidence(payload, 0, standalone=True)


class EvidenceLedgerStore:
    """Atomically add validated evidence within one allowed repository root."""

    def __init__(self, allowed_root: Path) -> None:
        if allowed_root.is_symlink() or is_reparse_point(allowed_root):
            raise ContractError("Evidence store root must be a regular directory.")
        self._allowed_root = allowed_root.resolve(strict=True)
        if (
            not self._allowed_root.is_dir()
            or is_reparse_point(self._allowed_root)
        ):
            raise ContractError("Evidence store root must be a regular directory.")

    def add(self, path: Path, record: EvidenceRecord) -> EvidenceLedger:
        """Validate, add, and atomically publish one unique evidence record."""

        if path.is_symlink() or is_reparse_point(path):
            raise ContractError("Evidence ledger must be an existing regular file.")
        target = path.resolve(strict=False)
        if not target.is_relative_to(self._allowed_root):
            raise ContractError("Evidence ledger must stay within the allowed root.")
        if target.is_symlink() or is_reparse_point(target) or not target.is_file():
            raise ContractError("Evidence ledger must be an existing regular file.")
        lock = target.with_name(f".{target.name}.lock")
        descriptor: int | None = None
        owns_lock = False
        temporary: Path | None = None
        try:
            descriptor = os.open(
                lock,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            owns_lock = True
            os.write(descriptor, b"sdaqf-evidence-ledger-lock\n")
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            ledger = load_evidence_ledger(target)
            if record.evidence_id in {item.evidence_id for item in ledger.evidence}:
                raise ContractError("Evidence identifier already exists.")
            if not set(record.claim_ids) <= {item.claim_id for item in ledger.claims}:
                raise ContractError("Evidence record references an unknown claim.")
            if (
                record.commit != ledger.git_head
                or record.repository_digest != ledger.repository_digest
            ):
                raise ContractError("Evidence record does not match the ledger candidate.")
            updated = EvidenceLedger(
                baseline_id=ledger.baseline_id,
                source_spec_sha256=ledger.source_spec_sha256,
                git_head=ledger.git_head,
                repository_digest=ledger.repository_digest,
                claims=ledger.claims,
                evidence=tuple(
                    sorted((*ledger.evidence, record), key=lambda item: item.evidence_id)
                ),
                diff_review_evidence_id=ledger.diff_review_evidence_id,
            )
            parse_evidence_ledger(updated.to_dict())
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                errors="strict",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(updated.to_dict(), stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        except FileExistsError as exc:
            raise ContractError("Evidence ledger is locked by another writer.") from exc
        except ContractError:
            raise
        except OSError as exc:
            raise ContractError("Evidence ledger update failed atomically.") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if owns_lock:
                lock.unlink(missing_ok=True)
        return updated


def _parse_claim(value: object, index: int) -> Claim:
    where = f"claims[{index}]"
    item = object_value(value, where)
    only_keys(
        item,
        {
            "claim_id",
            "statement",
            "requirement_ids",
            "acceptance_criteria",
            "state",
            "criticality",
            "confidence",
        },
        where,
    )
    requirement_ids = string_tuple(
        item.get("requirement_ids"),
        f"{where}.requirement_ids",
        minimum=1,
    )
    acceptance = string_tuple(
        item.get("acceptance_criteria"),
        f"{where}.acceptance_criteria",
        minimum=1,
    )
    if any(not _REQUIREMENT_ID.fullmatch(value) for value in requirement_ids):
        raise ContractError(f"{where}.requirement_ids contains an invalid identifier.")
    if any(not _ACCEPTANCE_ID.fullmatch(value) for value in acceptance):
        raise ContractError(
            f"{where}.acceptance_criteria contains an invalid identifier."
        )
    return Claim(
        claim_id=_identifier(item.get("claim_id"), f"{where}.claim_id", _CLAIM_ID),
        statement=string_value(
            item.get("statement"),
            f"{where}.statement",
            maximum=500,
        ),
        requirement_ids=requirement_ids,
        acceptance_criteria=acceptance,
        state=enum_value(ClaimState, item.get("state"), f"{where}.state"),
        criticality=enum_value(
            ClaimCriticality,
            item.get("criticality"),
            f"{where}.criticality",
        ),
        confidence=enum_value(
            Confidence,
            item.get("confidence"),
            f"{where}.confidence",
        ),
    )


def _parse_evidence(
    value: object,
    index: int,
    *,
    standalone: bool,
) -> EvidenceRecord:
    where = "evidence_record" if standalone else f"evidence[{index}]"
    item = object_value(value, where)
    fields = {
        "evidence_id",
        "claim_ids",
        "type",
        "status",
        "command",
        "environment",
        "commit",
        "repository_digest",
        "artifacts",
        "recorded_at",
    }
    if standalone:
        fields.add("schema_version")
    only_keys(item, fields, where)
    if standalone and (
        string_value(
            item.get("schema_version"),
            "schema_version",
            maximum=10,
        )
        != "1.0"
    ):
        raise ContractError("schema_version must be 1.0.")
    evidence_type = enum_value(EvidenceType, item.get("type"), f"{where}.type")
    status = enum_value(EvidenceStatus, item.get("status"), f"{where}.status")
    if (evidence_type is EvidenceType.UNVERIFIED) != (
        status is EvidenceStatus.NOT_VERIFIED
    ):
        raise ContractError("UNVERIFIED type and NOT_VERIFIED status must match.")
    environment = object_value(item.get("environment"), f"{where}.environment")
    if not environment:
        raise ContractError(f"{where}.environment must not be empty.")
    if len(environment) > 32:
        raise ContractError(f"{where}.environment exceeds the item limit.")
    environment_items: list[tuple[str, str]] = []
    for key in sorted(environment):
        if not _ENVIRONMENT_KEY.fullmatch(key):
            raise ContractError(f"{where}.environment contains an invalid key.")
        environment_items.append(
            (
                key,
                path_free_text(
                    environment[key],
                    f"{where}.environment.{key}",
                    maximum=200,
                ),
            )
        )
    artifacts = tuple(
        parse_artifact_reference(value, f"{where}.artifacts[{artifact_index}]")
        for artifact_index, value in enumerate(
            array_value(item.get("artifacts"), f"{where}.artifacts", maximum=64)
        )
    )
    artifact_paths = tuple(item.path for item in artifacts)
    if len(artifact_paths) != len(set(artifact_paths)):
        raise ContractError(f"{where}.artifacts must contain unique paths.")
    if status is EvidenceStatus.PASS and not artifacts:
        raise ContractError(f"{where}.artifacts must not be empty for PASS evidence.")
    claim_ids = string_tuple(
        item.get("claim_ids"),
        f"{where}.claim_ids",
        minimum=1,
    )
    if any(not _CLAIM_ID.fullmatch(value) for value in claim_ids):
        raise ContractError(f"{where}.claim_ids contains an invalid identifier.")
    return EvidenceRecord(
        evidence_id=_identifier(
            item.get("evidence_id"),
            f"{where}.evidence_id",
            _EVIDENCE_ID,
        ),
        claim_ids=claim_ids,
        evidence_type=evidence_type,
        status=status,
        command=command_argv(item.get("command"), f"{where}.command"),
        environment=tuple(environment_items),
        commit=_required_commit(item.get("commit"), f"{where}.commit"),
        repository_digest=sha256(
            item.get("repository_digest"),
            f"{where}.repository_digest",
        ),
        artifacts=artifacts,
        recorded_at=timestamp(item.get("recorded_at"), f"{where}.recorded_at"),
    )


def _identifier(value: object, where: str, pattern: re.Pattern[str]) -> str:
    text = string_value(value, where, maximum=128)
    if not pattern.fullmatch(text):
        raise ContractError(f"{where} is not a stable identifier.")
    return text


def _ordered_unique(values: tuple[str, ...], where: str) -> None:
    if len(values) != len(set(values)):
        raise ContractError(f"{where} identifiers must be unique.")
    if values != tuple(sorted(values)):
        raise ContractError(f"{where} must be sorted by identifier.")


def _required_commit(value: object, where: str) -> str:
    parsed = commit(value, where)
    if parsed is None:
        raise ContractError(f"{where} must not be null.")
    return parsed
