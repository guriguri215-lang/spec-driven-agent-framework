from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path

import pytest

from sdaqf.application.contracts import (
    ContractError,
    array_value,
    command_argv,
    commit,
    enum_value,
    integer_value,
    load_json_object,
    parse_candidate_identity,
    path_free_text,
    safe_relative_path,
    sha256,
    string_tuple,
    string_value,
    timestamp,
    verify_artifact,
)
from sdaqf.domain.quality import ArtifactReference


class ExampleEnum(StrEnum):
    VALUE = "value"


def test_bounded_file_and_array_helpers_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="regular"):
        load_json_object(tmp_path / "missing.json", "Input")

    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(b"\xff")
    with pytest.raises(ContractError, match="could not be read"):
        load_json_object(invalid, "Input")

    with pytest.raises(ContractError, match="array"):
        array_value({}, "items")
    with pytest.raises(ContractError, match="item limit"):
        array_value([1, 2], "items", maximum=1)


@pytest.mark.parametrize(
    "content",
    [
        '{"value":NaN}',
        '{"value":' + ("9" * 5_000) + "}",
        '{"value":' + ("[" * 2_000) + "0" + ("]" * 2_000) + "}",
    ],
)
def test_json_loader_contains_nonfinite_and_parser_resource_failures(
    tmp_path: Path,
    content: str,
) -> None:
    path = tmp_path / "hostile.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ContractError):
        load_json_object(path, "Hostile input", maximum_bytes=16 * 1024)


def test_string_and_tuple_helpers_enforce_bounds_and_uniqueness() -> None:
    with pytest.raises(ContractError, match="non-empty"):
        string_value("", "value")
    with pytest.raises(ContractError, match="text limit"):
        string_value("long", "value", maximum=3)
    with pytest.raises(ContractError, match="too few"):
        string_tuple([], "items", minimum=1)
    with pytest.raises(ContractError, match="unique"):
        string_tuple(["same", "same"], "items")


def test_integer_enum_timestamp_and_digest_helpers_reject_invalid_values() -> None:
    with pytest.raises(ContractError, match="integer"):
        integer_value(True, "number", minimum=1, maximum=2)
    with pytest.raises(ContractError, match="range"):
        integer_value(3, "number", minimum=1, maximum=2)
    with pytest.raises(ContractError, match="unsupported"):
        enum_value(ExampleEnum, "other", "enum")
    with pytest.raises(ContractError, match="ISO 8601"):
        timestamp("not-a-time", "time")
    with pytest.raises(ContractError, match="SHA-256"):
        sha256("bad", "digest")
    assert commit(None, "commit") is None
    with pytest.raises(ContractError, match="commit identifier"):
        commit("ABC", "commit")


@pytest.mark.parametrize(
    "path",
    [
        "/absolute.txt",
        "C:\\absolute.txt",
        "../parent.txt",
        "folder/../file.txt",
        "./file.txt",
        "file.txt:stream",
        "CON",
        "folder/NUL.txt",
        "trailing.",
        "~backup.txt",
        "unicodé.txt",
    ],
)
def test_safe_relative_path_rejects_absolute_and_non_normal_paths(path: str) -> None:
    with pytest.raises(ContractError, match=r"relative|normalized|portable"):
        safe_relative_path(path, "path")


def test_helpers_accept_supported_values() -> None:
    assert enum_value(ExampleEnum, "value", "enum") is ExampleEnum.VALUE
    assert timestamp("2026-07-29T00:00:00+00:00", "time").endswith("+00:00")
    assert sha256("A" * 64, "digest") == "A" * 64
    assert safe_relative_path("docs/report.md", "path") == "docs/report.md"


def test_command_candidate_and_artifact_helpers_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="must not be empty"):
        command_argv([], "command")
    with pytest.raises(ContractError, match="non-empty"):
        command_argv([""], "command")
    with pytest.raises(ContractError, match="control"):
        path_free_text("unsafe\u202epath", "text")
    with pytest.raises(ContractError, match="must not be null"):
        parse_candidate_identity(
            {
                "source_spec_sha256": "A" * 64,
                "git_head": None,
                "repository_digest": "B" * 64,
            },
            "candidate",
        )

    missing = ArtifactReference("missing.txt", "A" * 64)
    assert not verify_artifact(tmp_path, missing)
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("content\n", encoding="utf-8")
    wrong = ArtifactReference("artifact.txt", "A" * 64)
    assert not verify_artifact(tmp_path, wrong)
    assert not verify_artifact(tmp_path, wrong, maximum_bytes=1)


def test_artifact_verification_rejects_reparse_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "alias"
    folder.mkdir()
    artifact = folder / "artifact.txt"
    artifact.write_bytes(b"content\n")
    reference = ArtifactReference(
        "alias/artifact.txt",
        hashlib.sha256(b"content\n").hexdigest().upper(),
    )
    monkeypatch.setattr(
        "sdaqf.application.contracts.is_reparse_point",
        lambda path: path == folder,
    )

    assert not verify_artifact(tmp_path, reference)
