from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from sdaqf.application.contracts import ContractError
from sdaqf.application.evidence import (
    EvidenceLedgerStore,
    load_evidence_ledger,
    load_evidence_record,
    parse_evidence_ledger,
    parse_evidence_record,
)
from tests.m3_helpers import (
    evidence_addition_payload,
    ledger_payload,
    write_json,
)


def test_ledger_and_standalone_evidence_round_trip(tmp_path: Path) -> None:
    ledger_path = write_json(tmp_path / "ledger.json", ledger_payload())
    record_path = write_json(
        tmp_path / "record.json",
        evidence_addition_payload(),
    )

    loaded = load_evidence_ledger(ledger_path)
    record = load_evidence_record(record_path)

    assert loaded.to_dict() == ledger_payload()
    assert record.evidence_id == "EV-STATIC-0001"
    assert record.to_dict()["environment"] == {"os": "test"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"schema_version": "2.0"}),
        lambda value: value["claims"][0].update({"claim_id": "bad"}),
        lambda value: value["claims"][0].update({"requirement_ids": ["bad"]}),
        lambda value: value["evidence"][0].update(
            {"claim_ids": ["CLM-UNKNOWN"]}
        ),
        lambda value: value["evidence"][0].update(
            {"type": "UNVERIFIED", "status": "PASS"}
        ),
        lambda value: value["evidence"][0].update(
            {"artifacts": ["../secret.txt"]}
        ),
        lambda value: value.update(
            {"diff_review_evidence_id": "EV-INSTALL-0001"}
        ),
        lambda value: value.update(
            {"evidence": list(reversed(value["evidence"]))}
        ),
        lambda value: value.update({"claims": []}),
        lambda value: value.update({"evidence": []}),
        lambda value: value["claims"].append(copy.deepcopy(value["claims"][0])),
        lambda value: value["evidence"][0].update(
            {"environment": {f"k{i}": "v" for i in range(33)}}
        ),
        lambda value: value["evidence"][0].update(
            {"environment": {"BAD": "value"}}
        ),
        lambda value: value["evidence"][0].update(
            {"artifacts": [value["evidence"][0]["artifacts"][0]] * 2}
        ),
        lambda value: value["evidence"][0].update({"artifacts": []}),
    ],
)
def test_ledger_rejects_invalid_or_unsafe_contracts(
    mutate: Any,
) -> None:
    payload = copy.deepcopy(ledger_payload())
    mutate(payload)

    with pytest.raises(ContractError):
        parse_evidence_ledger(payload)


def test_ledger_rejects_duplicate_json_keys_and_oversized_file(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":"1.0","schema_version":"1.0"}',
        encoding="utf-8",
    )
    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * (256 * 1024 + 1), encoding="utf-8")

    with pytest.raises(ContractError, match="duplicate"):
        load_evidence_ledger(duplicate)
    with pytest.raises(ContractError, match="size limit"):
        load_evidence_ledger(oversized)


def test_evidence_record_rejects_secret_environment_and_bad_timestamp() -> None:
    secret = evidence_addition_payload()
    secret["environment"] = {"token": "ghp_" + ("a" * 24)}
    with pytest.raises(ContractError, match="secret-shaped"):
        parse_evidence_record(secret)

    personal = evidence_addition_payload()
    personal["command"] = ["python", "C:\\Users\\person\\script.py"]
    with pytest.raises(ContractError, match="absolute path"):
        parse_evidence_record(personal)

    timestamp = evidence_addition_payload()
    timestamp["recorded_at"] = "2026-07-29T00:00:00"
    with pytest.raises(ContractError, match="timezone"):
        parse_evidence_record(timestamp)

    version = evidence_addition_payload()
    version["schema_version"] = "2.0"
    with pytest.raises(ContractError, match="schema_version"):
        parse_evidence_record(version)


def test_store_adds_in_sorted_order_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    ledger_path = write_json(tmp_path / "ledger.json", ledger_payload())
    record = parse_evidence_record(evidence_addition_payload())
    store = EvidenceLedgerStore(tmp_path)

    updated = store.add(ledger_path, record)

    assert [item.evidence_id for item in updated.evidence] == [
        "EV-DIFF-0001",
        "EV-INSTALL-0001",
        "EV-REVIEW-0001",
        "EV-STATIC-0001",
    ]
    assert load_evidence_ledger(ledger_path) == updated
    with pytest.raises(ContractError, match="already exists"):
        store.add(ledger_path, record)


def test_store_rejects_escape_and_unknown_claim(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = write_json(tmp_path / "ledger.json", ledger_payload())
    store = EvidenceLedgerStore(root)

    with pytest.raises(ContractError, match="allowed root"):
        store.add(outside, parse_evidence_record(evidence_addition_payload()))

    ledger_path = write_json(root / "ledger.json", ledger_payload())
    record_payload = evidence_addition_payload()
    record_payload["claim_ids"] = ["CLM-UNKNOWN"]
    with pytest.raises(ContractError, match="unknown claim"):
        store.add(ledger_path, parse_evidence_record(record_payload))

    mismatch = evidence_addition_payload()
    mismatch["repository_digest"] = "E" * 64
    with pytest.raises(ContractError, match="candidate"):
        store.add(ledger_path, parse_evidence_record(mismatch))


def test_store_rejects_reparse_root_and_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = write_json(tmp_path / "ledger.json", ledger_payload())
    monkeypatch.setattr(
        "sdaqf.application.evidence.is_reparse_point",
        lambda path: path == tmp_path,
    )
    with pytest.raises(ContractError, match="root"):
        EvidenceLedgerStore(tmp_path)

    monkeypatch.setattr(
        "sdaqf.application.evidence.is_reparse_point",
        lambda path: path == ledger_path,
    )
    with pytest.raises(ContractError, match="regular file"):
        EvidenceLedgerStore(tmp_path).add(
            ledger_path,
            parse_evidence_record(evidence_addition_payload()),
        )


def test_store_failure_is_atomic_and_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = write_json(tmp_path / "ledger.json", ledger_payload())
    before = ledger_path.read_bytes()

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr("sdaqf.application.evidence.os.replace", fail_replace)

    with pytest.raises(ContractError, match="atomically"):
        EvidenceLedgerStore(tmp_path).add(
            ledger_path,
            parse_evidence_record(evidence_addition_payload()),
        )

    assert ledger_path.read_bytes() == before
    assert list(tmp_path.glob(".ledger.json.*.tmp")) == []
    assert not (tmp_path / ".ledger.json.lock").exists()


def test_store_fails_closed_when_another_writer_holds_lock(
    tmp_path: Path,
) -> None:
    ledger_path = write_json(tmp_path / "ledger.json", ledger_payload())
    lock = tmp_path / ".ledger.json.lock"
    lock.write_text("other writer\n", encoding="utf-8")

    with pytest.raises(ContractError, match="locked"):
        EvidenceLedgerStore(tmp_path).add(
            ledger_path,
            parse_evidence_record(evidence_addition_payload()),
        )

    assert lock.read_text(encoding="utf-8") == "other writer\n"


def test_contract_rejects_non_json_and_non_object(tmp_path: Path) -> None:
    text = tmp_path / "ledger.txt"
    text.write_text("{}", encoding="utf-8")
    array = tmp_path / "ledger.json"
    array.write_text(json.dumps([]), encoding="utf-8")

    with pytest.raises(ContractError, match="JSON"):
        load_evidence_ledger(text)
    with pytest.raises(ContractError, match="object"):
        load_evidence_ledger(array)
