from __future__ import annotations

import copy
import hashlib
import json
import struct
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sdaqf.application.contracts import ContractError
from sdaqf.application.ui_validation import (
    UiValidationService,
    _valid_png,
    load_manifest_ui,
    parse_ui_validation,
)
from tests.m3_helpers import (
    SOURCE_SHA,
    UI_SCREENSHOT_PATH,
    UI_TRACE_PATH,
    candidate,
    ui_payload,
    valid_png_bytes,
    write_evidence_artifacts,
    write_json,
)


def test_png_validation_rejects_invalid_stream_and_decompression_bomb() -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    signature = b"\x89PNG\r\n\x1a\n"
    invalid_stream = (
        signature
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", b"not-zlib")
        + chunk(b"IEND", b"")
    )
    bomb = (
        signature
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8_192, 8_192, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0"))
        + chunk(b"IEND", b"")
    )
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    compressed = zlib.compress(b"\x00\x14\x57\xd9")
    unknown_critical = (
        signature
        + header
        + chunk(b"ABCD", b"")
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
    invalid_reserved_bit = (
        signature
        + header
        + chunk(b"abca", b"")
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
    split = len(compressed) // 2
    nonconsecutive_idat = (
        signature
        + header
        + chunk(b"IDAT", compressed[:split])
        + chunk(b"tEXt", b"key\x00value")
        + chunk(b"IDAT", compressed[split:])
        + chunk(b"IEND", b"")
    )

    assert _valid_png(valid_png_bytes())
    assert not _valid_png(invalid_stream)
    assert not _valid_png(bomb)
    assert not _valid_png(unknown_critical)
    assert not _valid_png(invalid_reserved_bit)
    assert not _valid_png(nonconsecutive_idat)


def test_non_ui_project_passes_without_fabricated_browser_evidence(
    tmp_path: Path,
) -> None:
    manifest = _manifest(False)
    manifest_path = write_json(tmp_path / "manifest.json", manifest)
    manifest_identity = load_manifest_ui(manifest_path)
    validation = parse_ui_validation(ui_payload())

    result = UiValidationService().evaluate(
        manifest=manifest_identity,
        candidate=candidate(),
        validation=validation,
        root=tmp_path,
    )

    assert result.passed
    assert result.gate_id == "UI"
    assert len(result.checks) == 2


def test_ui_project_passes_complete_recorded_browser_loop(tmp_path: Path) -> None:
    manifest_path = write_json(tmp_path / "manifest.json", _manifest(True))
    write_evidence_artifacts(tmp_path)
    manifest_identity = load_manifest_ui(manifest_path)
    validation = parse_ui_validation(ui_payload(present=True))

    result = UiValidationService().evaluate(
        manifest=manifest_identity,
        candidate=candidate(),
        validation=validation,
        root=tmp_path,
    )

    assert result.passed
    assert validation.observations[0].browser == "Chromium"
    assert validation.to_dict() == ui_payload(present=True)


def test_ui_gate_fails_manifest_mismatch_and_failed_latest_attempt(
    tmp_path: Path,
) -> None:
    write_evidence_artifacts(tmp_path)
    payload = ui_payload(present=True)
    observations = payload["observations"]
    assert isinstance(observations, list)
    observation = observations[0]
    assert isinstance(observation, dict)
    observation["status"] = "FAIL"
    observation["failures"] = ["Offline recovery failed."]
    observation["offline"] = False
    payload["project_id"] = "other-project"
    validation = parse_ui_validation(payload)

    result = UiValidationService().evaluate(
        manifest=load_manifest_ui(
            write_json(tmp_path / "manifest.json", _manifest(True))
        ),
        candidate=candidate(),
        validation=validation,
        root=tmp_path,
    )

    assert {
        "UI-CLASSIFICATION",
        "UI-PRIMARY-FLOWS",
        "UI-RECOVERY-OFFLINE",
    } <= set(result.hard_blockers)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"design_brief": None}),
        lambda value: value["observations"][0].update({"attempt": 2}),
        lambda value: value["observations"][0].update({"browser": "simulated"}),
        lambda value: value["observations"][0].update(
            {"screenshots": ["../screen.png"]}
        ),
        lambda value: value["observations"][0].update(
            {"status": "NOT_VERIFIED"}
        ),
        lambda value: value["observations"][0].update({"observer_id": "bad"}),
        lambda value: value["observations"][0].update({"provenance": "claimed"}),
        lambda value: value["observations"][0].update(
            {"screenshots": value["observations"][0]["screenshots"] * 2}
        ),
        lambda value: value["observations"][0].update(
            {"visual_regression": "UNKNOWN"}
        ),
        lambda value: value["observations"][0].update(
            {
                "visual_regression": "NOT_APPLICABLE",
                "visual_regression_reason": None,
            }
        ),
    ],
)
def test_ui_contract_rejects_missing_or_unsafe_browser_evidence(
    mutation: Callable[[dict[str, Any]], object],
) -> None:
    payload = copy.deepcopy(ui_payload(present=True))
    mutation(payload)

    with pytest.raises(ContractError):
        parse_ui_validation(payload)


def test_non_ui_contract_rejects_fabricated_brief_or_observation() -> None:
    payload = ui_payload()
    payload["design_brief"] = {
        "users": ["Owner"],
        "primary_flows": ["Flow"],
        "states": ["offline"],
        "target_devices": ["desktop"],
        "design_research": ["Approved specification."],
        "third_party_asset_policy": "none-used",
        "third_party_asset_provenance": [],
    }

    with pytest.raises(ContractError, match="must not fabricate"):
        parse_ui_validation(payload)


def test_ui_gate_fails_incomplete_design_and_accessibility(
    tmp_path: Path,
) -> None:
    write_evidence_artifacts(tmp_path)
    payload = ui_payload(present=True)
    brief = payload["design_brief"]
    observations = payload["observations"]
    assert isinstance(observations, list)
    observation = observations[0]
    assert isinstance(brief, dict)
    assert isinstance(observation, dict)
    brief["states"] = ["offline"]
    observation["keyboard"] = False
    observation["focus_order"] = False
    validation = parse_ui_validation(payload)

    result = UiValidationService().evaluate(
        manifest=load_manifest_ui(
            write_json(tmp_path / "manifest.json", _manifest(True))
        ),
        candidate=candidate(),
        validation=validation,
        root=tmp_path,
    )

    assert "UI-DESIGN-BRIEF" in result.hard_blockers
    assert "UI-BOUNDED-LOOP" in result.hard_blockers
    assert "UI-ACCESSIBILITY" in result.hard_blockers


def test_manifest_rejects_extra_field_and_invalid_ui_type(tmp_path: Path) -> None:
    extra = _manifest(False)
    extra["unexpected"] = True
    with pytest.raises(ContractError, match="unsupported"):
        load_manifest_ui(write_json(tmp_path / "extra.json", extra))

    invalid = _manifest(False)
    ui = invalid["ui"]
    assert isinstance(ui, dict)
    ui["present"] = "false"
    with pytest.raises(ContractError, match="boolean"):
        load_manifest_ui(write_json(tmp_path / "invalid.json", invalid))

    incomplete = _manifest(False)
    incomplete["source_spec"] = {}
    with pytest.raises(ContractError, match="missing"):
        load_manifest_ui(write_json(tmp_path / "incomplete.json", incomplete))

    mutations: tuple[Callable[[dict[str, Any]], object], ...] = (
        lambda value: value.update({"schema_version": "2.0"}),
        lambda value: value.update({"project_id": "Bad ID"}),
        lambda value: value["source_spec"].update({"filename": "docs/spec.md"}),
        lambda value: value["platforms"].update({"required": ["plan9"]}),
        lambda value: value["platforms"].update(
            {"required": ["windows"], "optional": ["windows"]}
        ),
        lambda value: value.update({"network_policy": "open"}),
    )
    for index, mutation in enumerate(mutations):
        payload = _manifest(False)
        mutation(payload)
        with pytest.raises(ContractError):
            load_manifest_ui(
                write_json(tmp_path / f"manifest-{index}.json", payload)
            )


def test_ui_gate_rejects_missing_or_changed_screenshot(tmp_path: Path) -> None:
    write_evidence_artifacts(tmp_path)
    validation = parse_ui_validation(ui_payload(present=True))
    (tmp_path / UI_SCREENSHOT_PATH).write_bytes(b"\x89PNG\r\n\x1a\nbroken")

    result = UiValidationService().evaluate(
        manifest=load_manifest_ui(
            write_json(tmp_path / "manifest.json", _manifest(True))
        ),
        candidate=candidate(),
        validation=validation,
        root=tmp_path,
    )

    assert "UI-BOUNDED-LOOP" in result.hard_blockers


def test_ui_gate_rejects_changed_or_duplicate_key_execution_trace(
    tmp_path: Path,
) -> None:
    write_evidence_artifacts(tmp_path)
    validation = parse_ui_validation(ui_payload(present=True))
    trace_path = tmp_path / UI_TRACE_PATH
    original = trace_path.read_text(encoding="utf-8")
    trace_path.write_text(original.replace('"returncode": 0', '"returncode": 1'), encoding="utf-8")

    changed = UiValidationService().evaluate(
        manifest=load_manifest_ui(
            write_json(tmp_path / "manifest.json", _manifest(True))
        ),
        candidate=candidate(),
        validation=validation,
        root=tmp_path,
    )
    assert "UI-BOUNDED-LOOP" in changed.hard_blockers

    duplicate = original.replace('"returncode": 0', '"returncode": 1, "returncode": 0')
    trace_path.write_text(duplicate, encoding="utf-8")
    payload = ui_payload(present=True)
    observations = payload["observations"]
    assert isinstance(observations, list)
    observation = observations[0]
    assert isinstance(observation, dict)
    trace = observation["trace"]
    assert isinstance(trace, dict)
    trace["sha256"] = hashlib.sha256(duplicate.encode()).hexdigest().upper()
    duplicated = UiValidationService().evaluate(
        manifest=load_manifest_ui(
            write_json(tmp_path / "manifest-duplicate.json", _manifest(True))
        ),
        candidate=candidate(),
        validation=parse_ui_validation(payload),
        root=tmp_path,
    )
    assert "UI-BOUNDED-LOOP" in duplicated.hard_blockers


def test_ui_gate_rejects_browser_executable_and_command_mismatch(
    tmp_path: Path,
) -> None:
    write_evidence_artifacts(tmp_path)
    trace_path = tmp_path / UI_TRACE_PATH
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["execution"]["executable"] = "python"
    changed = json.dumps(trace, indent=2).encode()
    trace_path.write_bytes(changed)
    payload = ui_payload(present=True)
    observations = payload["observations"]
    assert isinstance(observations, list)
    observation = observations[0]
    assert isinstance(observation, dict)
    reference = observation["trace"]
    assert isinstance(reference, dict)
    reference["sha256"] = hashlib.sha256(changed).hexdigest().upper()

    result = UiValidationService().evaluate(
        manifest=load_manifest_ui(
            write_json(tmp_path / "manifest.json", _manifest(True))
        ),
        candidate=candidate(),
        validation=parse_ui_validation(payload),
        root=tmp_path,
    )

    assert "UI-BOUNDED-LOOP" in result.hard_blockers


def _manifest(present: bool) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "project_id": "example-project",
        "title": "Example",
        "release_level": "prototype",
        "source_spec": {
            "filename": "specification.md",
            "sha256": SOURCE_SHA,
            "imported_at": "2026-07-29T00:00:00+00:00",
        },
        "platforms": {"required": ["windows"], "optional": []},
        "ui": {"present": present},
        "network_policy": "default-deny",
        "api_required": False,
    }
