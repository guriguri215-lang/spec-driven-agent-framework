from collections.abc import Sequence

from sdaqf.application.doctor import DoctorService
from sdaqf.domain.models import ToolStatus
from sdaqf.ports.process import ProcessResult


class RecordingRunner:
    def __init__(
        self,
        result: ProcessResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or ProcessResult(0, "tool 1.0\n", "")
        self.error = error
        self.commands: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> ProcessResult:
        self.commands.append(tuple(args))
        if self.error is not None:
            raise self.error
        return self.result


def located(_: str) -> str:
    return "resolved"


def test_doctor_does_not_launch_nested_codex() -> None:
    runner = RecordingRunner()
    capabilities = DoctorService(
        runner,
        locator=located,
        python_executable="python",
    ).inspect(current_session_active=True)

    by_name = {item.name: item for item in capabilities}
    assert by_name["codex-current-session"].detail == "CURRENT_SESSION_ACTIVE"
    assert by_name["codex-external-cli"].status is ToolStatus.NOT_CHECKED
    assert all(command[0] != "codex" for command in runner.commands)
    assert by_name["git"].status is ToolStatus.AVAILABLE


def test_doctor_distinguishes_permission_error_from_missing_tool() -> None:
    denied = DoctorService(
        RecordingRunner(error=PermissionError()),
        locator=located,
        python_executable="python",
    ).inspect()
    missing = DoctorService(
        RecordingRunner(error=FileNotFoundError()),
        locator=located,
        python_executable="python",
    ).inspect()

    assert denied[1].status is ToolStatus.PERMISSION_DENIED
    assert missing[1].status is ToolStatus.UNAVAILABLE


def test_doctor_classifies_access_denied_output() -> None:
    runner = RecordingRunner(ProcessResult(1, "", "Access is denied"))
    capabilities = DoctorService(
        runner,
        locator=located,
        python_executable="python",
    ).inspect()

    assert capabilities[1].status is ToolStatus.PERMISSION_DENIED


def test_doctor_classifies_other_probe_failure_as_unavailable() -> None:
    runner = RecordingRunner(ProcessResult(7, "", "unexpected failure"))
    capabilities = DoctorService(
        runner,
        locator=located,
        python_executable="python",
    ).inspect()

    assert capabilities[1].status is ToolStatus.UNAVAILABLE
    assert "exit code 7" in capabilities[1].detail


def test_doctor_handles_locator_miss_and_timeout() -> None:
    missing = DoctorService(
        RecordingRunner(),
        locator=lambda _: None,
        python_executable="python",
    ).inspect()
    timeout = DoctorService(
        RecordingRunner(error=TimeoutError()),
        locator=located,
        python_executable="python",
    ).inspect()

    assert missing[2].status is ToolStatus.UNAVAILABLE
    assert timeout[1].status is ToolStatus.UNAVAILABLE


def test_doctor_classifies_other_os_error_as_unavailable() -> None:
    capabilities = DoctorService(
        RecordingRunner(error=OSError("bad executable format")),
        locator=located,
        python_executable="python",
    ).inspect()

    assert capabilities[1].status is ToolStatus.UNAVAILABLE
    assert "operating system" in capabilities[1].detail
