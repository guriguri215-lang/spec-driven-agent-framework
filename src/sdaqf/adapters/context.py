"""Standard-library local adapters for the M5 Context Framework."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sdaqf.application.contracts import ContractError
from sdaqf.application.release_qa import GitInspector
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.context import SourceLocator
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity
from sdaqf.ports.context import ContextSourceError, ObservedContextSource
from sdaqf.ports.process import ProcessRunner


class ContextAdapterError(ContextSourceError):
    """A local Context boundary failed closed."""


class LocalContextSourceReader:
    """Read one regular source under an explicit regular root."""

    def __init__(self, *, maximum_source_bytes: int = 256 * 1024) -> None:
        if maximum_source_bytes <= 0:
            raise ValueError("maximum_source_bytes must be positive")
        self._maximum_source_bytes = maximum_source_bytes

    def observe(self, root: Path, locator: SourceLocator) -> ObservedContextSource:
        """Read a stable strict UTF-8 source and verify its exact locator."""

        content = self._read_regular(root, locator.path, self._maximum_source_bytes)
        digest = hashlib.sha256(content).hexdigest().upper()
        if digest != locator.sha256:
            raise ContextAdapterError("Context source digest does not match its locator.")
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ContextAdapterError("Context source must be strict UTF-8.") from exc
        if "\x00" in text or any(0xD800 <= ord(character) <= 0xDFFF for character in text):
            raise ContextAdapterError("Context source contains unsupported text.")
        lines = text.splitlines(keepends=True)
        if not lines and text == "":
            lines = [""]
        if locator.line_end > len(lines):
            raise ContextAdapterError("Context source line range is outside the source.")
        selected = "".join(lines[locator.line_start - 1 : locator.line_end])
        return ObservedContextSource(
            content=content,
            text=text,
            selected_text=selected,
            sha256=digest,
        )

    def verify_reference(self, root: Path, reference: ArtifactReference) -> None:
        """Verify one stable provenance reference under its explicit root."""

        content = self._read_regular(root, reference.path, 1 * 1024 * 1024)
        digest = hashlib.sha256(content).hexdigest().upper()
        if digest != reference.sha256:
            raise ContextAdapterError(
                "Context provenance digest does not match its reference."
            )

    @staticmethod
    def _read_regular(root: Path, path: str, maximum_bytes: int) -> bytes:
        """Return stable bytes from one safe regular relative path."""

        try:
            if root.is_symlink() or is_reparse_point(root):
                raise ContextAdapterError("Context root must be regular and unlinked.")
            resolved_root = root.resolve(strict=True)
            if not resolved_root.is_dir():
                raise ContextAdapterError("Context root must be a directory.")
            parts = PurePosixPath(path).parts
            candidate = resolved_root.joinpath(*parts)
            current = resolved_root
            for part in parts:
                current = current / part
                if current.is_symlink() or is_reparse_point(current):
                    raise ContextAdapterError("Context source must be unlinked.")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(resolved_root):
                raise ContextAdapterError("Context source escapes its explicit root.")
            if (
                not resolved.is_file()
                or resolved.is_symlink()
                or is_reparse_point(resolved)
            ):
                raise ContextAdapterError("Context source must be a regular file.")
            before = resolved.stat()
            if before.st_size > maximum_bytes:
                raise ContextAdapterError("Context source exceeds the size limit.")
            content = resolved.read_bytes()
            after = resolved.stat()
        except ContextAdapterError:
            raise
        except OSError as exc:
            raise ContextAdapterError("Context source could not be observed.") from exc
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(content) != after.st_size
        ):
            raise ContextAdapterError("Context source changed during observation.")
        return content


class LocalContextCandidateVerifier:
    """Verify CandidateIdentity through the existing bounded Git inspector."""

    def __init__(self, runner: ProcessRunner) -> None:
        self._inspector = GitInspector(runner)

    def verify(self, repository_root: Path, expected: CandidateIdentity) -> None:
        """Fail unless Git HEAD and publication digest exactly match."""

        try:
            observed = self._inspector.inspect(repository_root)
        except ContractError as exc:
            raise ContextAdapterError(
                "Repository candidate could not be inspected."
            ) from exc
        if (
            not observed.root_matches
            or observed.head != expected.git_head
            or observed.repository_digest != expected.repository_digest
        ):
            raise ContextAdapterError(
                "Repository candidate does not match Context CandidateIdentity."
            )


class SystemUTCClock:
    """System UTC clock for explicit Query authoring defaults."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC value."""

        return datetime.now(UTC)


class CanonicalUTF8ByteEstimator:
    """Cost canonical serialized content by its exact UTF-8 bytes."""

    def cost(self, content: object) -> int:
        """Return the canonical JSON UTF-8 byte length."""

        from sdaqf.application.context_contracts import canonical_json_bytes

        return len(canonical_json_bytes(content))


class ExclusiveJSONPublisher:
    """Publish immutable JSON through a same-directory temporary hard link."""

    def publish(self, target: Path, content: bytes) -> None:
        """Exclusively publish a fresh regular JSON file."""

        if target.suffix.casefold() != ".json":
            raise ContextAdapterError("Context output must be a JSON file.")
        parent = target.parent
        try:
            if (
                not parent.is_dir()
                or parent.is_symlink()
                or is_reparse_point(parent)
                or target.exists()
                or target.is_symlink()
                or is_reparse_point(target)
            ):
                raise ContextAdapterError(
                    "Context output must be a fresh file under a regular directory."
                )
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        except ContextAdapterError:
            raise
        except FileExistsError as exc:
            raise ContextAdapterError("Context output already exists.") from exc
        except OSError as exc:
            raise ContextAdapterError(
                "Context output publication was unsuccessful or indeterminate."
            ) from exc
