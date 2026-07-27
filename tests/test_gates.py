import pytest

from sdaqf.application.gates import GateEngine
from sdaqf.domain.models import GateCheck


def test_gate_engine_builds_result_without_scoring() -> None:
    result = GateEngine().evaluate(
        "G2",
        [
            GateCheck("tests", True, True, "passed"),
            GateCheck("manual-review", False, False, "pending"),
        ],
    )

    assert not result.passed
    assert result.hard_blockers == ()


@pytest.mark.parametrize(
    ("gate_id", "checks", "message"),
    [
        ("", [GateCheck("check", True, False, "ok")], "gate_id"),
        ("G0", [], "at least one"),
        ("G0", [GateCheck("", True, False, "ok")], "identifiers"),
        (
            "G0",
            [
                GateCheck("same", True, False, "ok"),
                GateCheck("same", False, False, "bad"),
            ],
            "unique",
        ),
    ],
)
def test_gate_engine_rejects_invalid_check_sets(
    gate_id: str,
    checks: list[GateCheck],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        GateEngine().evaluate(gate_id, checks)
