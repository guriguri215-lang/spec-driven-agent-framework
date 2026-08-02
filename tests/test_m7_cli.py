"""Public additive M7 solver CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdaqf.adapters.context import ContextAdapterError, ExclusiveJSONPublisher
from sdaqf.cli import main
from sdaqf.domain.scheduler import MailboxMessage
from tests.m6_scheduler_helpers import ROOT
from tests.m7_solver_helpers import HOST_ID, build_fixture, start_solver_lease


def test_registry_and_request_validation_commands_emit_stable_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture(tmp_path)
    assert (
        main(
            [
                "solver",
                "registry",
                "validate",
                str(fixture.registry_path),
                "--root",
                str(ROOT),
                "--json",
            ]
        )
        == 0
    )
    registry_output = json.loads(capsys.readouterr().out)
    assert registry_output == {
        "adapters": 1,
        "artifact_id": fixture.registry.artifact_id,
        "valid": True,
    }

    assert (
        main(
            [
                "solver",
                "request",
                "validate",
                str(fixture.request_path),
                "--registry",
                str(fixture.registry_path),
                "--task-graph",
                str(fixture.graph_path),
                "--root",
                str(ROOT),
                "--json",
            ]
        )
        == 0
    )
    request_output = json.loads(capsys.readouterr().out)
    assert request_output["artifact_id"] == fixture.request.artifact_id
    assert request_output["adapter_id"] == "stdlib-finite-domain-v1"
    assert request_output["valid"] is True


def test_run_and_verify_commands_publish_fresh_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture(tmp_path)
    _, dispatch = start_solver_lease(fixture)
    dispatch_value = dispatch.value
    assert isinstance(dispatch_value, MailboxMessage)
    assert dispatch_value.lease_id is not None
    shared = [
        "--registry",
        str(fixture.registry_path),
        "--task-graph",
        str(fixture.graph_path),
        "--state",
        str(fixture.state_path),
        "--root",
        str(ROOT),
        "--host-id",
        HOST_ID,
        "--lease-id",
        dispatch_value.lease_id,
    ]
    assert (
        main(
            [
                "solver",
                "run",
                str(fixture.request_path),
                *shared,
                "--output",
                str(fixture.result_path),
                "--json",
            ]
        )
        == 0
    )
    run_output = json.loads(capsys.readouterr().out)
    assert run_output["status"] == "optimal"
    assert run_output["output"] == fixture.result_path.name

    assert (
        main(
            [
                "solver",
                "verify",
                str(fixture.result_path),
                "--request",
                str(fixture.request_path),
                *shared,
                "--output",
                str(fixture.verification_path),
                "--json",
            ]
        )
        == 0
    )
    verification_output = json.loads(capsys.readouterr().out)
    assert verification_output["outcome"] == "verified"
    assert verification_output["adoption_allowed"] is True


def test_invalid_cli_request_fails_closed_without_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = build_fixture(tmp_path)
    output = tmp_path / "never-created.json"
    assert (
        main(
            [
                "solver",
                "request",
                "validate",
                str(fixture.request_path),
                "--registry",
                str(fixture.registry_path),
                "--task-graph",
                str(ROOT / "examples/m6-scheduler/task-graph.json"),
                "--root",
                str(ROOT),
                "--json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error"] == "m7-solver-invalid"
    assert not output.exists()


def test_publication_failure_stays_inside_bounded_cli_error_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_fixture(tmp_path)
    _, dispatch = start_solver_lease(fixture)
    dispatch_value = dispatch.value
    assert isinstance(dispatch_value, MailboxMessage)
    assert dispatch_value.lease_id is not None

    def fail_publish(self: object, target: Path, content: bytes) -> None:
        raise ContextAdapterError("sensitive absolute path must not escape")

    monkeypatch.setattr(ExclusiveJSONPublisher, "publish", fail_publish)
    assert (
        main(
            [
                "solver",
                "run",
                str(fixture.request_path),
                "--registry",
                str(fixture.registry_path),
                "--task-graph",
                str(fixture.graph_path),
                "--state",
                str(fixture.state_path),
                "--root",
                str(ROOT),
                "--host-id",
                HOST_ID,
                "--lease-id",
                dispatch_value.lease_id,
                "--output",
                str(fixture.result_path),
                "--json",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out) == {
        "error": "m7-solver-invalid",
        "operation": "run",
    }
    assert not fixture.result_path.exists()
