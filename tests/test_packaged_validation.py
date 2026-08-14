from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from zipfile import ZipFile

import pytest


@pytest.fixture
def outside_repository_temp() -> Iterator[Path]:
    configured = os.environ.get("SDAQF_SYSTEM_TEMP_ROOT")
    parent = Path(tempfile.gettempdir() if configured is None else configured)
    with tempfile.TemporaryDirectory(prefix="pkg-", dir=parent) as temporary:
        yield Path(temporary)


def _run(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )
    assert completed.returncode == 0, (
        f"command failed with exit {completed.returncode}: {command!r}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    return completed


def _copy_build_inputs(repository: Path, destination: Path) -> None:
    destination.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE"):
        shutil.copyfile(repository / name, destination / name)
    (destination / "src").mkdir()
    shutil.copytree(
        repository / "src" / "sdaqf",
        destination / "src" / "sdaqf",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    shutil.copytree(repository / "schemas", destination / "schemas")


def test_installed_wheel_validates_sample_project_from_isolated_python(
    outside_repository_temp: Path,
) -> None:
    repository = Path(__file__).resolve().parents[1]
    temporary = outside_repository_temp
    source = temporary / "s"
    wheels = temporary / "w"
    runtime = temporary / "r"
    outside_checkout = temporary / "o"
    sample_project = (repository / "examples" / "sample-project").resolve()
    _copy_build_inputs(repository, source)
    wheels.mkdir()
    outside_checkout.mkdir()
    assert not outside_checkout.resolve().is_relative_to(repository.resolve())

    _run(
        [
            sys.executable,
            "-I",
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "wheel",
            "--no-input",
            "--no-index",
            "--no-cache-dir",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(wheels),
            str(source),
        ],
        cwd=outside_checkout,
        timeout=120,
    )
    built_wheels = tuple(wheels.glob("sdaqf-*.whl"))
    assert len(built_wheels) == 1
    wheel = built_wheels[0]
    with ZipFile(wheel) as archive:
        assert any(
            name.endswith(
                "/share/sdaqf/schemas/project-manifest.schema.json"
            )
            for name in archive.namelist()
        )

    _run(
        [sys.executable, "-I", "-m", "venv", "--without-pip", str(runtime)],
        cwd=outside_checkout,
        timeout=60,
    )
    runtime_python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    purelib_result = _run(
        [
            str(runtime_python),
            "-I",
            "-c",
            "import sysconfig; print(sysconfig.get_path('purelib'))",
        ],
        cwd=outside_checkout,
        timeout=30,
    )
    install_target = Path(purelib_result.stdout.strip())
    assert not (install_target / "sdaqf").exists()
    _run(
        [
            sys.executable,
            "-I",
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "install",
            "--no-input",
            "--no-index",
            "--no-cache-dir",
            "--no-compile",
            "--no-deps",
            "--target",
            str(install_target),
            str(wheel),
        ],
        cwd=outside_checkout,
        timeout=60,
    )

    validation = _run(
        [
            str(runtime_python),
            "-I",
            "-m",
            "sdaqf",
            "validate",
            str(sample_project),
            "--json",
        ],
        cwd=outside_checkout,
        timeout=30,
    )
    payload = json.loads(validation.stdout)
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert len(payload["files_checked"]) == 8
