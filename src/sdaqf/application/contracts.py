"""Shared strict helpers for bounded M3 data contracts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath

from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity

_SHA256 = re.compile(r"^[0-9A-F]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SECRET = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_ABSOLUTE = re.compile(r"(?:^[A-Za-z]:[\\/]|^/)")
_ABSOLUTE_ANY = re.compile(
    r"(?:[A-Za-z]:[\\/]|/(?:etc|home|opt|private|root|tmp|usr|var|Users)(?:/|$))",
    re.IGNORECASE,
)
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
_RESERVED_WINDOWS_NAMES = {
    "AUX",
    "CLOCK$",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_BIDI_OR_CONTROL = re.compile(
    r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]"
)
_PERSONAL_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]\x55sers[\\/]|/\x55sers/|/\x68ome/[^/\s]+/)",
    re.IGNORECASE,
)


class ContractError(ValueError):
    """A bounded M3 contract is invalid."""


def load_json_object(
    path: Path,
    label: str,
    *,
    maximum_bytes: int = 256 * 1024,
) -> dict[str, object]:
    """Load one bounded regular UTF-8 JSON object and reject duplicate keys."""

    if path.suffix.casefold() != ".json":
        raise ContractError(f"{label} must be a JSON file.")
    if path.is_symlink() or is_reparse_point(path) or not path.is_file():
        raise ContractError(f"{label} must be a regular, unlinked file.")
    try:
        if path.stat().st_size > maximum_bytes:
            raise ContractError(f"{label} exceeds the size limit.")
        content = path.read_bytes()
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError(f"{label} could not be read.") from exc
    return parse_json_object_bytes(
        content,
        label,
        maximum_bytes=maximum_bytes,
    )


def parse_json_object_bytes(
    content: bytes,
    label: str,
    *,
    maximum_bytes: int = 256 * 1024,
) -> dict[str, object]:
    """Parse one immutable bounded UTF-8 JSON snapshot with strict keys."""

    if len(content) > maximum_bytes:
        raise ContractError(f"{label} exceeds the size limit.")

    def strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"{label} contains a duplicate JSON key.")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ContractError(f"{label} contains non-finite JSON number {value}.")

    try:
        decoded: object = json.loads(
            content.decode("utf-8", errors="strict"),
            object_pairs_hook=strict_object,
            parse_constant=reject_constant,
        )
    except ContractError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ContractError(f"{label} could not be read.") from exc
    _validate_json_structure(decoded, label)
    return object_value(decoded, label)


def _validate_json_structure(value: object, label: str) -> None:
    """Bound decoded JSON depth and node count without recursive traversal."""

    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > 64 or nodes > 10_000:
            raise ContractError(f"{label} exceeds the JSON structure limit.")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def object_value(value: object, where: str) -> dict[str, object]:
    """Require a string-keyed JSON object."""

    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContractError(f"{where} must be an object.")
    return value


def array_value(value: object, where: str, *, maximum: int = 256) -> list[object]:
    """Require one bounded JSON array."""

    if not isinstance(value, list):
        raise ContractError(f"{where} must be an array.")
    if len(value) > maximum:
        raise ContractError(f"{where} exceeds the item limit.")
    return value


def only_keys(
    value: dict[str, object],
    expected: set[str],
    where: str,
) -> None:
    """Require exact object fields."""

    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing:
        raise ContractError(f"{where} is missing {sorted(missing)[0]}.")
    if extra:
        raise ContractError(f"{where} contains unsupported field {sorted(extra)[0]}.")


def string_value(
    value: object,
    where: str,
    *,
    maximum: int = 4_000,
    multiline: bool = False,
) -> str:
    """Require bounded, non-empty, single-line, secret-free text."""

    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{where} must be a non-empty string.")
    if len(value) > maximum:
        raise ContractError(f"{where} exceeds the text limit.")
    if "\x00" in value or "\r" in value or (not multiline and "\n" in value):
        raise ContractError(f"{where} must be one line.")
    if any(pattern.search(value) for pattern in _SECRET):
        raise ContractError(f"{where} contains secret-shaped content.")
    return value


def optional_string(
    value: object,
    where: str,
    *,
    maximum: int = 4_000,
) -> str | None:
    """Require null or bounded text."""

    return None if value is None else string_value(value, where, maximum=maximum)


def path_free_text(
    value: object,
    where: str,
    *,
    maximum: int = 4_000,
) -> str:
    """Require bounded text without a personal absolute path."""

    text = string_value(value, where, maximum=maximum)
    if _PERSONAL_PATH.search(text) or _ABSOLUTE_ANY.search(text):
        raise ContractError(f"{where} contains an absolute path.")
    if _BIDI_OR_CONTROL.search(text):
        raise ContractError(f"{where} contains unsupported control text.")
    return text


def string_tuple(
    value: object,
    where: str,
    *,
    minimum: int = 0,
    maximum: int = 64,
) -> tuple[str, ...]:
    """Require a bounded unique string array."""

    items = array_value(value, where, maximum=maximum)
    result = tuple(
        string_value(item, f"{where}[{index}]", maximum=500)
        for index, item in enumerate(items)
    )
    if len(result) < minimum:
        raise ContractError(f"{where} has too few items.")
    if len(result) != len(set(result)):
        raise ContractError(f"{where} must contain unique items.")
    return result


def path_free_tuple(
    value: object,
    where: str,
    *,
    minimum: int = 0,
    maximum: int = 64,
) -> tuple[str, ...]:
    """Require a bounded unique string array without personal paths."""

    items = array_value(value, where, maximum=maximum)
    result = tuple(
        path_free_text(item, f"{where}[{index}]", maximum=500)
        for index, item in enumerate(items)
    )
    if len(result) < minimum:
        raise ContractError(f"{where} has too few items.")
    if len(result) != len(set(result)):
        raise ContractError(f"{where} must contain unique items.")
    return result


def boolean_value(value: object, where: str) -> bool:
    """Require a JSON boolean."""

    if not isinstance(value, bool):
        raise ContractError(f"{where} must be a boolean.")
    return value


def integer_value(
    value: object,
    where: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Require an integer inside a closed range."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{where} must be an integer.")
    if value < minimum or value > maximum:
        raise ContractError(f"{where} is outside the supported range.")
    return value


def enum_value[E: StrEnum](enum_type: type[E], value: object, where: str) -> E:
    """Require one supported string enum value."""

    text = string_value(value, where, maximum=100)
    try:
        return enum_type(text)
    except ValueError as exc:
        raise ContractError(f"{where} is unsupported.") from exc


def timestamp(value: object, where: str) -> str:
    """Require a timezone-aware ISO 8601 timestamp."""

    text = string_value(value, where, maximum=100)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractError(f"{where} must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{where} must include a timezone.")
    return text


def sha256(value: object, where: str) -> str:
    """Require an uppercase SHA-256 digest."""

    text = string_value(value, where, maximum=64)
    if not _SHA256.fullmatch(text):
        raise ContractError(f"{where} must be an uppercase SHA-256 digest.")
    return text


def command_argv(value: object, where: str) -> tuple[str, ...]:
    """Require a bounded shell-free command argument array."""

    values = array_value(value, where, maximum=64)
    result = tuple(
        path_free_text(item, f"{where}[{index}]", maximum=240)
        for index, item in enumerate(values)
    )
    if not result:
        raise ContractError(f"{where} must not be empty.")
    if any(not item.strip() for item in result):
        raise ContractError(f"{where} contains an empty argument.")
    return result


def commit(value: object, where: str) -> str | None:
    """Require null or a lowercase full commit identifier."""

    if value is None:
        return None
    text = string_value(value, where, maximum=40)
    if not _COMMIT.fullmatch(text):
        raise ContractError(f"{where} must be a lowercase full commit identifier.")
    return text


def safe_relative_path(value: object, where: str) -> str:
    """Require a normalized repository-relative POSIX path."""

    text = string_value(value, where, maximum=240)
    if (
        "\\" in text
        or _ABSOLUTE.search(text)
        or not _SAFE_PATH.fullmatch(text)
        or _BIDI_OR_CONTROL.search(text)
    ):
        raise ContractError(f"{where} must be a relative POSIX path.")
    path = PurePosixPath(text)
    if text in {".", ".."} or any(part in {"", ".", ".."} for part in path.parts):
        raise ContractError(f"{where} must be a normalized relative path.")
    if path.as_posix() != text:
        raise ContractError(f"{where} must be a normalized relative path.")
    for part in path.parts:
        folded = part.upper().split(".", 1)[0]
        if (
            part.startswith("~")
            or part.endswith((".", " "))
            or ":" in part
            or folded in _RESERVED_WINDOWS_NAMES
        ):
            raise ContractError(f"{where} is not portable on Windows.")
    return text


def parse_candidate_identity(value: object, where: str) -> CandidateIdentity:
    """Parse an exact source, Git, and repository candidate identity."""

    item = object_value(value, where)
    only_keys(
        item,
        {"source_spec_sha256", "git_head", "repository_digest"},
        where,
    )
    parsed_commit = commit(item.get("git_head"), f"{where}.git_head")
    if parsed_commit is None:
        raise ContractError(f"{where}.git_head must not be null.")
    return CandidateIdentity(
        source_spec_sha256=sha256(
            item.get("source_spec_sha256"),
            f"{where}.source_spec_sha256",
        ),
        git_head=parsed_commit,
        repository_digest=sha256(
            item.get("repository_digest"),
            f"{where}.repository_digest",
        ),
    )


def parse_artifact_reference(value: object, where: str) -> ArtifactReference:
    """Parse one repository-relative artifact reference."""

    item = object_value(value, where)
    only_keys(item, {"path", "sha256"}, where)
    return ArtifactReference(
        path=safe_relative_path(item.get("path"), f"{where}.path"),
        sha256=sha256(item.get("sha256"), f"{where}.sha256"),
    )


def verify_artifact(
    root: Path,
    reference: ArtifactReference,
    *,
    maximum_bytes: int = 1_000_000,
) -> bool:
    """Verify one bounded regular artifact against its content digest."""

    try:
        if root.is_symlink() or is_reparse_point(root):
            return False
        resolved_root = root.resolve(strict=True)
        relative_parts = PurePosixPath(reference.path).parts
        candidate = resolved_root.joinpath(*relative_parts)
        current = resolved_root
        for part in relative_parts:
            current = current / part
            if current.is_symlink() or is_reparse_point(current):
                return False
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(resolved_root):
            return False
        if not resolved.is_file() or is_reparse_point(resolved):
            return False
        if resolved.stat().st_size > maximum_bytes:
            return False
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest().upper()
    except OSError:
        return False
    return digest == reference.sha256
