from sdaqf.domain.models import GateCheck, GateResult, ToolCapability, ToolStatus


def test_tool_capability_serializes_enum() -> None:
    capability = ToolCapability(
        name="git",
        status=ToolStatus.AVAILABLE,
        detail="Probe succeeded.",
        version="git version 2.54.0",
    )

    assert capability.to_dict() == {
        "name": "git",
        "status": "AVAILABLE",
        "detail": "Probe succeeded.",
        "version": "git version 2.54.0",
    }


def test_gate_result_passes_only_when_all_checks_pass() -> None:
    result = GateResult(
        gate_id="G0",
        checks=(
            GateCheck("boundary", True, True, "safe"),
            GateCheck("lint", True, False, "clean"),
        ),
    )

    assert result.passed
    assert result.hard_blockers == ()
    assert result.to_dict()["passed"] is True


def test_gate_result_reports_failed_hard_blocker() -> None:
    result = GateResult(
        gate_id="G0",
        checks=(GateCheck("secret", False, True, "detected"),),
    )

    assert not result.passed
    assert result.hard_blockers == ("secret",)


def test_empty_gate_result_does_not_pass() -> None:
    assert not GateResult("G0", ()).passed
