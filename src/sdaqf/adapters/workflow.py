"""Standard-library-only local adapters for M8 workflow integration."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath

from sdaqf.adapters.scheduler import SQLiteSchedulerStore
from sdaqf.application.contracts import ContractError, safe_relative_path
from sdaqf.application.release_qa import GitInspector, repository_digest
from sdaqf.application.workspace import is_reparse_point
from sdaqf.domain.quality import ArtifactReference, CandidateIdentity
from sdaqf.domain.scheduler import (
    WorkflowArtifactReceipt,
    WorkflowEpochHead,
    WorkflowEpochPhase,
    WorkflowReceiptSnapshot,
    WorkflowReceiptStatus,
)
from sdaqf.domain.workflow import (
    NativeArtifactBinding,
    WorkflowArtifactType,
    WorkflowPublicationObservation,
)
from sdaqf.ports.process import ProcessRunner


class WorkflowAdapterError(OSError):
    """A bounded local workflow adapter operation failed or was ambiguous."""


class SystemWorkflowClock:
    """Production UTC clock for explicit workflow transition evidence."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC value."""

        return datetime.now(UTC)


class RuntimePrivateCandidateVerifier:
    """Pin Git and exclude only canonical bytes authenticated by M6 v2 receipts."""

    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner
        self._inspector = GitInspector(runner)

    def observe(
        self,
        repository_root: Path,
        expected: CandidateIdentity,
        *,
        scheduler_state: Path,
        plan_id: str | None = None,
    ) -> WorkflowPublicationObservation:
        """Return one pinned Git enumeration plus one validated receipt snapshot."""

        try:
            root = repository_root.resolve(strict=True)
            store = SQLiteSchedulerStore(scheduler_state, root)
            store.validate()
            store.require_workflow_authority()
            snapshot = store.workflow_receipt_snapshot(plan_id)
            observed = self._inspector.inspect(root)
            tracked = self._tracked_paths(root)
            publication = _normalized_paths(root, tuple(observed.publication_paths))
            tracked_set = set(tracked)
            untracked = tuple(item for item in publication if item not in tracked_set)
            scheduler_relative = _relative_path(root, store.path)
            excluded: set[str] = set()
            for relative in untracked:
                if relative == scheduler_relative:
                    excluded.add(relative)
                    continue
                match = _matching_receipt(snapshot, relative)
                if match is None:
                    continue
                receipt, _head = match
                candidate = root.joinpath(*PurePosixPath(relative).parts)
                if _canonical_artifact_id(candidate, receipt.artifact_type) == receipt.artifact_id:
                    excluded.add(relative)
            filtered_publication = tuple(item for item in publication if item not in excluded)
            filtered_changed = tuple(
                item
                for item in _normalized_paths(root, tuple(observed.changed_paths))
                if item not in excluded
            )
            filtered_git = replace(
                observed,
                clean=not filtered_changed,
                changed_paths=filtered_changed,
                publication_paths=filtered_publication,
                repository_digest=repository_digest(root, filtered_publication),
            )
        except WorkflowAdapterError:
            raise
        except (ContractError, OSError) as exc:
            raise WorkflowAdapterError("Workflow Candidate could not be inspected.") from exc
        if (
            not filtered_git.root_matches
            or filtered_git.head != expected.git_head
            or filtered_git.repository_digest != expected.repository_digest
        ):
            raise WorkflowAdapterError(
                "Repository Candidate does not match the receipt-bound publication set."
            )
        return WorkflowPublicationObservation(
            git=filtered_git,
            scheduler_state_path=scheduler_relative,
            receipts=snapshot,
            tracked_paths=tracked,
            untracked_non_ignored_paths=untracked,
            receipt_excluded_paths=tuple(sorted(excluded)),
            receipt_plan_id=plan_id,
        )

    def verify(
        self,
        repository_root: Path,
        expected: CandidateIdentity,
        *,
        scheduler_state: Path,
        plan_id: str | None = None,
    ) -> None:
        """Compatibility wrapper for callers that need only Candidate validation."""

        self.observe(
            repository_root,
            expected,
            scheduler_state=scheduler_state,
            plan_id=plan_id,
        )

    def revalidate(
        self,
        repository_root: Path,
        observation: WorkflowPublicationObservation,
        *,
        scheduler_state: Path,
    ) -> None:
        """Reject drift without reclassifying any path independently."""

        root = repository_root.resolve(strict=True)
        store = SQLiteSchedulerStore(scheduler_state, root)
        store.validate()
        store.require_workflow_authority()
        if (
            store.workflow_receipt_snapshot(observation.receipt_plan_id)
            != observation.receipts
        ):
            raise WorkflowAdapterError("M6 receipt snapshot changed after observation.")
        raw = self._inspector.inspect(root)
        tracked = self._tracked_paths(root)
        if tracked != observation.tracked_paths:
            raise WorkflowAdapterError("Git tracked paths changed after observation.")
        publication = _normalized_paths(root, tuple(raw.publication_paths))
        untracked = tuple(item for item in publication if item not in set(tracked))
        if untracked != observation.untracked_non_ignored_paths:
            raise WorkflowAdapterError("Git untracked paths changed after observation.")
        excluded = set(observation.receipt_excluded_paths)
        filtered_publication = tuple(item for item in publication if item not in excluded)
        filtered_changed = tuple(
            item
            for item in _normalized_paths(root, tuple(raw.changed_paths))
            if item not in excluded
        )
        if (
            raw.root_matches != observation.git.root_matches
            or raw.branch != observation.git.branch
            or raw.head != observation.git.head
            or filtered_publication != observation.git.publication_paths
            or filtered_changed != observation.git.changed_paths
            or repository_digest(root, filtered_publication)
            != observation.git.repository_digest
        ):
            raise WorkflowAdapterError("Git publication observation changed before use.")
        for relative in observation.receipt_excluded_paths:
            if relative == observation.scheduler_state_path:
                if _relative_path(root, store.path) != relative:
                    raise WorkflowAdapterError("Explicit M6 authority path changed.")
                continue
            match = _matching_receipt(observation.receipts, relative)
            if match is None:
                raise WorkflowAdapterError("Pinned M6 receipt disappeared.")
            receipt, _head = match
            if (
                _canonical_artifact_id(
                    root.joinpath(*PurePosixPath(relative).parts), receipt.artifact_type
                )
                != receipt.artifact_id
            ):
                raise WorkflowAdapterError("Receipt-bound artifact changed after observation.")

    def preflight_outputs(
        self,
        repository_root: Path,
        artifacts: tuple[tuple[str, str, str, str], ...],
        *,
        scheduler_state: Path,
        plan_id: str,
    ) -> None:
        """Reject tracked, ignored, linked, aliased, or foreign output before reserve."""

        root = repository_root.resolve(strict=True)
        normalized = _normalized_paths(root, tuple(item[0] for item in artifacts))
        if len(normalized) != len(artifacts):
            raise WorkflowAdapterError("Workflow output paths are not exact and unique.")
        tracked = self._tracked_paths(root)
        tracked_portable = {
            tuple(part.casefold() for part in PurePosixPath(item).parts): item
            for item in tracked
        }
        store = SQLiteSchedulerStore(scheduler_state, root)
        store.validate()
        store.require_workflow_authority()
        head = store.workflow_head(plan_id)
        receipts = () if head is None else head.receipts
        by_path = {item.path: item for item in receipts}
        for relative, artifact_type, artifact_id, producer in artifacts:
            portable = tuple(part.casefold() for part in PurePosixPath(relative).parts)
            if portable in tracked_portable:
                raise WorkflowAdapterError("Workflow output collides with a tracked path.")
            if self._is_ignored(root, relative):
                raise WorkflowAdapterError("Workflow output is ignored by Git.")
            candidate = root.joinpath(*PurePosixPath(relative).parts)
            _reject_linked_candidate(root, candidate)
            if candidate.exists() or candidate.is_symlink() or is_reparse_point(candidate):
                receipt = by_path.get(relative)
                if (
                    head is None
                    or receipt is None
                    or not _receipt_retry_phase_is_admissible(head, receipt)
                    or receipt.artifact_type != artifact_type
                    or receipt.artifact_id != artifact_id
                    or receipt.producer != producer
                    or receipt.status
                    not in {
                        WorkflowReceiptStatus.RESERVED,
                        WorkflowReceiptStatus.CONFIRMED,
                    }
                    or candidate.stat().st_nlink != 1
                    or _canonical_artifact_id(candidate, artifact_type) != artifact_id
                ):
                    raise WorkflowAdapterError(
                        "Workflow output collides with a foreign artifact."
                    )

    def classify_output_paths(
        self,
        repository_root: Path,
        paths: tuple[str, ...],
        *,
        scheduler_state: Path,
        plan_id: str | None,
    ) -> None:
        """Classify every target before persisted time or artifact derivation."""

        root = repository_root.resolve(strict=True)
        normalized = _normalized_paths(root, paths)
        if len(normalized) != len(paths):
            raise WorkflowAdapterError("Workflow output paths are not exact and unique.")
        tracked = self._tracked_paths(root)
        tracked_portable = {
            tuple(part.casefold() for part in PurePosixPath(item).parts)
            for item in tracked
        }
        store = SQLiteSchedulerStore(scheduler_state, root)
        store.validate()
        store.require_workflow_authority()
        head = None if plan_id is None else store.workflow_head(plan_id)
        receipts = {} if head is None else {item.path: item for item in head.receipts}
        for relative in paths:
            portable = tuple(part.casefold() for part in PurePosixPath(relative).parts)
            if portable in tracked_portable:
                raise WorkflowAdapterError("Workflow output collides with a tracked path.")
            if self._is_ignored(root, relative):
                raise WorkflowAdapterError("Workflow output is ignored by Git.")
            candidate = root.joinpath(*PurePosixPath(relative).parts)
            _reject_linked_candidate(root, candidate)
            if candidate.exists() or candidate.is_symlink() or is_reparse_point(candidate):
                receipt = receipts.get(relative)
                if (
                    head is None
                    or receipt is None
                    or not _receipt_retry_phase_is_admissible(head, receipt)
                    or receipt.status
                    not in {
                        WorkflowReceiptStatus.RESERVED,
                        WorkflowReceiptStatus.CONFIRMED,
                    }
                    or candidate.stat().st_nlink != 1
                    or _canonical_artifact_id(candidate, receipt.artifact_type)
                    != receipt.artifact_id
                ):
                    raise WorkflowAdapterError(
                        "Workflow output collides with a foreign artifact."
                    )

    def confirm_outputs(
        self,
        repository_root: Path,
        observation: WorkflowPublicationObservation,
        expected: CandidateIdentity,
        artifacts: tuple[tuple[str, str, str, str], ...],
        *,
        scheduler_state: Path,
        plan_id: str,
    ) -> None:
        """Freshly verify Git classification, exact receipts, and pinned Candidate."""

        root = repository_root.resolve(strict=True)
        self.preflight_outputs(
            root,
            artifacts,
            scheduler_state=scheduler_state,
            plan_id=plan_id,
        )
        final = self.observe(
            root,
            expected,
            scheduler_state=scheduler_state,
            plan_id=plan_id,
        )
        targets = {item[0] for item in artifacts}
        if (
            final.git != observation.git
            or final.tracked_paths != observation.tracked_paths
            or not targets.issubset(final.untracked_non_ignored_paths)
            or not targets.issubset(final.receipt_excluded_paths)
        ):
            raise WorkflowAdapterError(
                "Workflow terminal outputs changed the pinned Git authority."
            )
        heads = {item.plan_id: item for item in final.receipts.heads}
        head = heads.get(plan_id)
        if head is None:
            raise WorkflowAdapterError("Workflow terminal receipt head disappeared.")
        by_path = {item.path: item for item in head.receipts}
        for relative, artifact_type, artifact_id, producer in artifacts:
            receipt = by_path.get(relative)
            if (
                receipt is None
                or receipt.artifact_type != artifact_type
                or receipt.artifact_id != artifact_id
                or receipt.producer != producer
                or receipt.status is not WorkflowReceiptStatus.CONFIRMED
            ):
                raise WorkflowAdapterError("Workflow terminal receipt is not exact and confirmed.")

    def _is_ignored(self, root: Path, relative: str) -> bool:
        executable = shutil.which("git")
        if executable is None:
            raise WorkflowAdapterError("Git is unavailable.")
        result = self._runner.run(
            [
                str(Path(executable).resolve(strict=True)),
                "-C",
                str(root),
                "check-ignore",
                "--no-index",
                "--quiet",
                "--",
                relative,
            ]
        )
        if result.stdout_truncated or result.stderr_truncated or result.returncode not in {0, 1}:
            raise WorkflowAdapterError("Git ignore classification failed closed.")
        return result.returncode == 0

    def _tracked_paths(self, root: Path) -> tuple[str, ...]:
        executable = shutil.which("git")
        if executable is None:
            raise WorkflowAdapterError("Git is unavailable.")
        result = self._runner.run(
            [
                str(Path(executable).resolve(strict=True)),
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "-z",
            ]
        )
        if result.returncode or result.stdout_truncated or result.stderr_truncated:
            raise WorkflowAdapterError("Git tracked-path enumeration failed closed.")
        return _normalized_paths(root, tuple(item for item in result.stdout.split("\0") if item))


class ExclusiveWorkflowArtifactStore:
    """Publish fresh immutable JSON below one explicit regular root."""

    def __init__(self, root: Path) -> None:
        try:
            if root.is_symlink() or is_reparse_point(root):
                raise WorkflowAdapterError("Workflow root must be regular and unlinked.")
            resolved = root.resolve(strict=True)
        except WorkflowAdapterError:
            raise
        except OSError as exc:
            raise WorkflowAdapterError("Workflow root is unavailable.") from exc
        if not resolved.is_dir():
            raise WorkflowAdapterError("Workflow root must be a directory.")
        self._root = resolved

    def load(self, reference: ArtifactReference, maximum_bytes: int) -> bytes:
        """Load one exact regular file below the configured root."""

        if maximum_bytes < 1:
            raise WorkflowAdapterError("Workflow load bound must be positive.")
        candidate = self._resolve_reference(reference)
        try:
            before = candidate.stat()
            if before.st_size > maximum_bytes:
                raise WorkflowAdapterError("Workflow input exceeds its byte bound.")
            content = candidate.read_bytes()
            after = candidate.stat()
        except WorkflowAdapterError:
            raise
        except OSError as exc:
            raise WorkflowAdapterError("Workflow input could not be loaded.") from exc
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(content) != after.st_size
            or sha256(content).hexdigest().upper() != reference.sha256
        ):
            raise WorkflowAdapterError("Workflow input changed or its digest drifted.")
        return content

    def read_event_chain(
        self,
        bindings: tuple[NativeArtifactBinding, ...],
        maximum_events: int,
    ) -> tuple[bytes, ...]:
        """Load one explicit complete Event chain without directory discovery."""

        if not bindings or len(bindings) > maximum_events:
            raise WorkflowAdapterError("Workflow Event chain is empty or exceeds its bound.")
        if any(
            not item.required or item.artifact_type != WorkflowArtifactType.WORKFLOW_EVENT.value
            for item in bindings
        ):
            raise WorkflowAdapterError("Workflow Event chain binding is not exact and required.")
        return tuple(self.load(item.reference, 1_048_576) for item in bindings)

    def _resolve_reference(self, reference: ArtifactReference) -> Path:
        candidate = self._root / reference.path
        try:
            lexical = Path(os.path.abspath(candidate))
            if ".." in Path(reference.path).parts or not lexical.is_relative_to(self._root):
                raise WorkflowAdapterError("Workflow input escapes its explicit root.")
            if not lexical.is_file() or lexical.is_symlink() or is_reparse_point(lexical):
                raise WorkflowAdapterError("Workflow input must be regular and unlinked.")
            current = self._root
            for part in lexical.relative_to(self._root).parts:
                current = current / part
                if current.is_symlink() or is_reparse_point(current):
                    raise WorkflowAdapterError("Workflow input contains a linked component.")
        except WorkflowAdapterError:
            raise
        except OSError as exc:
            raise WorkflowAdapterError("Workflow input is unavailable.") from exc
        return lexical

    def publish(self, output: Path, content: bytes) -> None:
        """Hard-link a flushed temporary file without replacing output."""

        candidate = output if output.is_absolute() else self._root / output
        if candidate.suffix.casefold() != ".json":
            raise WorkflowAdapterError("Workflow output must be a JSON file.")
        try:
            lexical = Path(os.path.abspath(candidate))
            if ".." in candidate.parts or not lexical.is_relative_to(self._root):
                raise WorkflowAdapterError("Workflow output escapes its explicit root.")
            parent = lexical.parent.resolve(strict=True)
            if (
                not parent.is_relative_to(self._root)
                or not parent.is_dir()
                or parent.is_symlink()
                or is_reparse_point(parent)
            ):
                raise WorkflowAdapterError("Workflow output parent must be regular.")
            current = self._root
            for part in lexical.relative_to(self._root).parts[:-1]:
                current = current / part
                if current.is_symlink() or is_reparse_point(current):
                    raise WorkflowAdapterError("Workflow output contains a linked component.")
            if lexical.exists() or lexical.is_symlink() or is_reparse_point(lexical):
                raise WorkflowAdapterError("Workflow output already exists.")
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{lexical.name}.", suffix=".tmp", dir=parent
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, lexical)
            finally:
                temporary.unlink(missing_ok=True)
        except WorkflowAdapterError:
            raise
        except FileExistsError as exc:
            raise WorkflowAdapterError("Workflow output already exists.") from exc
        except OSError as exc:
            raise WorkflowAdapterError(
                "Workflow output publication was unsuccessful or indeterminate."
            ) from exc

    def publish_idempotent(
        self,
        output: Path,
        content: bytes,
        *,
        artifact_type: str,
        artifact_id: str,
    ) -> None:
        """Publish once or accept the same canonical artifact on exact retry."""

        candidate = output if output.is_absolute() else self._root / output
        if candidate.exists():
            if (
                candidate.is_symlink()
                or is_reparse_point(candidate)
                or candidate.stat().st_nlink != 1
            ):
                raise WorkflowAdapterError("Workflow output collision is linked.")
            if _canonical_artifact_id(candidate, artifact_type) != artifact_id:
                raise WorkflowAdapterError("Workflow output collides with a foreign artifact.")
            return
        self.publish(output, content)


def publication_candidate_paths(root: Path, paths: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize publication paths without inferring runtime privacy from content."""

    return _normalized_paths(root.resolve(strict=True), paths)


def _normalized_paths(root: Path, paths: tuple[str, ...]) -> tuple[str, ...]:
    by_portable_path: dict[str, str] = {}
    included: list[str] = []
    for raw in paths:
        normalized = safe_relative_path(raw.replace("\\", "/"), "workflow publication path")
        parts = PurePosixPath(normalized).parts
        portable = "/".join(part.casefold() for part in parts)
        previous = by_portable_path.get(portable)
        if previous is not None and previous != normalized:
            raise WorkflowAdapterError("Workflow publication path has a case collision.")
        by_portable_path[portable] = normalized
        candidate = root.joinpath(*parts)
        _reject_case_alias(root, candidate)
        _reject_linked_candidate(root, candidate)
        included.append(normalized)
    return tuple(
        sorted(
            set(included),
            key=lambda item: (
                tuple(part.casefold() for part in PurePosixPath(item).parts),
                PurePosixPath(item).parts,
            ),
        )
    )


def _reject_linked_candidate(root: Path, candidate: Path) -> None:
    current = root
    try:
        for part in candidate.relative_to(root).parts:
            current = current / part
            if current.is_symlink() or is_reparse_point(current):
                raise WorkflowAdapterError(
                    "Workflow publication path contains a link or reparse point."
                )
    except ValueError as exc:
        raise WorkflowAdapterError("Workflow publication path escapes its root.") from exc


def _reject_case_alias(root: Path, candidate: Path) -> None:
    """Reject any existing portable path component with different casing."""

    current = root
    try:
        for part in candidate.relative_to(root).parts:
            if not current.is_dir():
                return
            matches = tuple(
                entry.name
                for entry in current.iterdir()
                if entry.name.casefold() == part.casefold()
            )
            if len(matches) > 1 or (matches and matches[0] != part):
                raise WorkflowAdapterError(
                    "Workflow publication path has an existing case alias."
                )
            current = current / part
    except WorkflowAdapterError:
        raise
    except (OSError, ValueError) as exc:
        raise WorkflowAdapterError(
            "Workflow publication path case classification failed."
        ) from exc


def _relative_path(root: Path, path: Path) -> str:
    try:
        lexical = Path(os.path.abspath(path))
        if not lexical.is_relative_to(root):
            raise WorkflowAdapterError("Explicit scheduler path escapes repository root.")
        return safe_relative_path(lexical.relative_to(root).as_posix(), "scheduler state path")
    except OSError as exc:
        raise WorkflowAdapterError("Explicit scheduler path is unavailable.") from exc


def _matching_receipt(
    snapshot: WorkflowReceiptSnapshot,
    path: str,
) -> tuple[WorkflowArtifactReceipt, WorkflowEpochHead] | None:
    matches = [
        (receipt, head)
        for head in snapshot.heads
        for receipt in head.receipts
        if receipt.path == path
        and receipt.status in {WorkflowReceiptStatus.RESERVED, WorkflowReceiptStatus.CONFIRMED}
    ]
    if len(matches) > 1:
        raise WorkflowAdapterError("M6 receipts ambiguously bind one publication path.")
    return None if not matches else matches[0]


def _receipt_retry_phase_is_admissible(
    head: WorkflowEpochHead,
    receipt: WorkflowArtifactReceipt,
) -> bool:
    """Admit only exact Plan or terminal-publication retry authorities."""

    return head.phase in {
        WorkflowEpochPhase.TERMINAL_RESERVED,
        WorkflowEpochPhase.TERMINAL_CONFIRMED,
    } or (
        receipt.artifact_type == WorkflowArtifactType.INTEGRATED_PLAN.value
        and receipt.status is WorkflowReceiptStatus.CONFIRMED
    )


def _canonical_artifact_id(candidate: Path, artifact_type: str) -> str:
    try:
        if (
            not candidate.is_file()
            or candidate.is_symlink()
            or is_reparse_point(candidate)
            or candidate.stat().st_nlink != 1
        ):
            raise WorkflowAdapterError("Receipt-bound artifact must be regular and unlinked.")
        if candidate.stat().st_size > 16 * 1024 * 1024:
            raise WorkflowAdapterError("Receipt-bound artifact exceeds its byte bound.")
        content = candidate.read_bytes()
        from sdaqf.application.scheduler_contracts import parse_scheduler_artifact_bytes
        from sdaqf.application.workflow_contracts import parse_workflow_artifact_bytes

        if artifact_type in {item.value for item in WorkflowArtifactType}:
            workflow_artifact = parse_workflow_artifact_bytes(content)
            actual_type = workflow_artifact.artifact_type.value
            artifact_id = workflow_artifact.artifact_id
        else:
            scheduler_artifact = parse_scheduler_artifact_bytes(content)
            actual_type = scheduler_artifact.artifact_type.value
            artifact_id = scheduler_artifact.artifact_id
        if actual_type != artifact_type:
            raise WorkflowAdapterError("Receipt-bound artifact type drifted.")
        return artifact_id
    except WorkflowAdapterError:
        raise
    except (ContractError, OSError, ValueError) as exc:
        raise WorkflowAdapterError("Receipt-bound canonical artifact is invalid.") from exc
