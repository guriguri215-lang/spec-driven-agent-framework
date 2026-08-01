"""M5 safe explicit Context indexing tests."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from sdaqf.adapters.context import (
    ContextAdapterError,
    ExclusiveJSONPublisher,
    LocalContextCandidateVerifier,
    LocalContextSourceReader,
)
from sdaqf.adapters.process import SubprocessRunner
from sdaqf.application.context_contracts import artifact_from_value
from sdaqf.application.context_index import ContextIndexer, ContextIndexError
from sdaqf.application.release_qa import GitInspector
from sdaqf.domain.context import (
    AuthorityClass,
    ContextArtifactType,
    ContextGraph,
    ContextManifest,
    RootScope,
    Sensitivity,
)
from sdaqf.domain.quality import CandidateIdentity
from tests.m5_context_helpers import (
    PinnedContextCandidateVerifier,
    manifest_and_graph,
    write_sources,
)


def test_index_reproduces_the_golden_graph(tmp_path: Path) -> None:
    manifest, expected_graph = manifest_and_graph()
    write_sources(tmp_path)
    actual = ContextIndexer(
        LocalContextSourceReader(),
        PinnedContextCandidateVerifier(),
    ).build(
        manifest,
        repository_root=tmp_path,
    )
    assert actual == expected_graph


def test_local_candidate_verifier_uses_temporary_git_and_external_output(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    write_sources(repository)
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Git is required by the M5 candidate contract.")
    runner = SubprocessRunner(timeout_seconds=10, output_limit=1_048_576)
    commands = (
        ("init", "-b", "main"),
        ("add", "."),
        (
            "-c",
            "user.name=M5 Test",
            "-c",
            "user.email=m5-test.invalid",
            "commit",
            "-m",
            "fixture",
        ),
    )
    for arguments in commands:
        result = runner.run((str(Path(git).resolve()), "-C", str(repository), *arguments))
        assert result.returncode == 0, result.stderr

    observed = GitInspector(runner).inspect(repository)
    manifest_artifact, _ = manifest_and_graph()
    assert isinstance(manifest_artifact.value, ContextManifest)
    current_candidate = CandidateIdentity(
        source_spec_sha256=(
            manifest_artifact.value.candidate.source_spec_sha256
        ),
        git_head=observed.head,
        repository_digest=observed.repository_digest,
    )
    current_manifest = artifact_from_value(
        ContextArtifactType.MANIFEST,
        replace(manifest_artifact.value, candidate=current_candidate),
    )
    output_root = tmp_path / "outputs"
    output_root.mkdir()
    graph = ContextIndexer(
        LocalContextSourceReader(),
        LocalContextCandidateVerifier(runner),
        ExclusiveJSONPublisher(),
    ).publish(
        current_manifest,
        repository_root=repository,
        owner_root=None,
        output=output_root / "context-graph.json",
    )

    assert isinstance(graph.value, ContextGraph)
    assert graph.value.candidate == current_candidate
    assert GitInspector(runner).inspect(repository) == observed


def test_index_exclusively_publishes_and_rejects_collision(tmp_path: Path) -> None:
    manifest, expected_graph = manifest_and_graph()
    write_sources(tmp_path)
    output = tmp_path / "graph.json"
    indexer = ContextIndexer(
        LocalContextSourceReader(),
        PinnedContextCandidateVerifier(),
        ExclusiveJSONPublisher(),
    )
    actual = indexer.publish(
        manifest,
        repository_root=tmp_path,
        owner_root=None,
        output=output,
    )
    assert actual == expected_graph
    before = output.read_bytes()
    with pytest.raises(ContextAdapterError, match=r"fresh|exists"):
        indexer.publish(
            manifest,
            repository_root=tmp_path,
            owner_root=None,
            output=output,
        )
    assert output.read_bytes() == before


def test_index_rejects_changed_digest_without_output(tmp_path: Path) -> None:
    manifest, _ = manifest_and_graph()
    write_sources(tmp_path)
    target = tmp_path / "examples/m5-context/sources/specification.md"
    target.write_text("changed\n", encoding="utf-8")
    output = tmp_path / "graph.json"
    with pytest.raises(ContextIndexError, match="Required Context source"):
        ContextIndexer(
            LocalContextSourceReader(),
            PinnedContextCandidateVerifier(),
            ExclusiveJSONPublisher(),
        ).publish(
            manifest,
            repository_root=tmp_path,
            owner_root=None,
            output=output,
        )
    assert not output.exists()


def test_index_rejects_unused_owner_root(tmp_path: Path) -> None:
    manifest, _ = manifest_and_graph()
    write_sources(tmp_path)
    with pytest.raises(ContextIndexError, match="Unused owner root"):
        ContextIndexer(
            LocalContextSourceReader(),
            PinnedContextCandidateVerifier(),
        ).build(
            manifest,
            repository_root=tmp_path,
            owner_root=tmp_path,
        )


def test_index_requires_owner_root_for_owner_source(tmp_path: Path) -> None:
    manifest_artifact, _ = manifest_and_graph()
    assert isinstance(manifest_artifact.value, ContextManifest)
    source = next(
        item
        for item in manifest_artifact.value.sources
        if item.authority is not AuthorityClass.CANONICAL_SPECIFICATION
    )
    owner_locator = replace(source.locator, root_scope=RootScope.OWNER)
    changed = replace(
        source,
        locator=owner_locator,
        authority=AuthorityClass.OWNER_APPROVED,
        provenance=replace(
            source.provenance,
            producer="Owner",
            recorded_by="Owner",
        ),
    )
    changed_manifest = replace(
        manifest_artifact.value,
        sources=tuple(
            item for item in manifest_artifact.value.sources if item is not source
        ),
        relationships=(),
    )
    from sdaqf.application.context_contracts import (
        artifact_from_value,
        source_identity,
    )

    changed = replace(changed, source_id=source_identity(changed.content_dict()))
    changed_manifest = replace(
        changed_manifest,
        sources=tuple(
            sorted((*changed_manifest.sources, changed), key=lambda item: item.source_id)
        ),
    )
    artifact = artifact_from_value(ContextArtifactType.MANIFEST, changed_manifest)
    with pytest.raises(ContextIndexError, match="explicit owner root"):
        ContextIndexer(
            LocalContextSourceReader(),
            PinnedContextCandidateVerifier(),
        ).build(
            artifact,
            repository_root=tmp_path,
        )


def test_index_output_is_typed_graph(tmp_path: Path) -> None:
    manifest, _ = manifest_and_graph()
    write_sources(tmp_path)
    artifact = ContextIndexer(
        LocalContextSourceReader(),
        PinnedContextCandidateVerifier(),
    ).build(
        manifest,
        repository_root=tmp_path,
    )
    assert artifact.artifact_type is ContextArtifactType.GRAPH
    assert isinstance(artifact.value, ContextGraph)
    assert all(node.text for node in artifact.value.nodes)


def test_index_records_optional_missing_source_exclusion(tmp_path: Path) -> None:
    manifest, _ = manifest_and_graph()
    write_sources(tmp_path)
    assert isinstance(manifest.value, ContextManifest)
    optional = next(source for source in manifest.value.sources if not source.required)
    tmp_path.joinpath(*Path(optional.locator.path).parts).unlink()
    graph = ContextIndexer(
        LocalContextSourceReader(),
        PinnedContextCandidateVerifier(),
    ).build(
        manifest,
        repository_root=tmp_path,
    )
    assert isinstance(graph.value, ContextGraph)
    exclusion = next(
        item
        for item in graph.value.excluded_sources
        if item.source_id == optional.source_id
    )
    assert exclusion.reason == "missing-or-unreadable"


def test_index_rejects_candidate_identity_mismatch_before_adoption(
    tmp_path: Path,
) -> None:
    manifest, _ = manifest_and_graph()
    write_sources(tmp_path)
    assert isinstance(manifest.value, ContextManifest)
    wrong = CandidateIdentity(
        source_spec_sha256=manifest.value.candidate.source_spec_sha256,
        git_head=manifest.value.candidate.git_head,
        repository_digest="D" * 64,
    )
    with pytest.raises(RuntimeError, match="candidate"):
        ContextIndexer(
            LocalContextSourceReader(),
            PinnedContextCandidateVerifier(wrong),
        ).build(
            manifest,
            repository_root=tmp_path,
        )


def test_index_requires_the_canonical_specification_to_be_required(
    tmp_path: Path,
) -> None:
    manifest, _ = manifest_and_graph()
    write_sources(tmp_path)
    assert isinstance(manifest.value, ContextManifest)
    canonical = next(
        source
        for source in manifest.value.sources
        if source.authority is AuthorityClass.CANONICAL_SPECIFICATION
    )
    changed_manifest = artifact_from_value(
        ContextArtifactType.MANIFEST,
        replace(
            manifest.value,
            sources=tuple(
                replace(source, required=False)
                if source.source_id == canonical.source_id
                else source
                for source in manifest.value.sources
            ),
        ),
    )
    with pytest.raises(ContextIndexError, match="canonical specification"):
        ContextIndexer(
            LocalContextSourceReader(),
            PinnedContextCandidateVerifier(),
        ).build(
            changed_manifest,
            repository_root=tmp_path,
        )


def test_index_excludes_optional_authority_laundering(tmp_path: Path) -> None:
    manifest_artifact, _ = manifest_and_graph()
    write_sources(tmp_path)
    assert isinstance(manifest_artifact.value, ContextManifest)
    optional = next(
        source
        for source in manifest_artifact.value.sources
        if not source.required
    )
    changed = replace(
        optional,
        authority=AuthorityClass.OWNER_APPROVED,
        sensitivity=Sensitivity.PUBLIC,
    )
    from sdaqf.application.context_contracts import artifact_from_value, source_identity

    changed = replace(changed, source_id=source_identity(changed.content_dict()))
    manifest = replace(
        manifest_artifact.value,
        sources=tuple(
            sorted(
                (
                    changed,
                    *(
                        source
                        for source in manifest_artifact.value.sources
                        if source is not optional
                    ),
                ),
                key=lambda item: item.source_id,
            )
        ),
        relationships=(),
    )
    graph = ContextIndexer(
        LocalContextSourceReader(),
        PinnedContextCandidateVerifier(),
    ).build(
        artifact_from_value(ContextArtifactType.MANIFEST, manifest),
        repository_root=tmp_path,
    )
    assert isinstance(graph.value, ContextGraph)
    assert any(
        item.source_id == changed.source_id and item.reason == "authority-invalid"
        for item in graph.value.excluded_sources
    )


def test_index_rejects_missing_required_provenance_reference(
    tmp_path: Path,
) -> None:
    manifest_artifact, _ = manifest_and_graph()
    write_sources(tmp_path)
    assert isinstance(manifest_artifact.value, ContextManifest)
    required = next(source for source in manifest_artifact.value.sources if source.required)
    reference = required.provenance.references[0]
    changed = replace(
        required,
        provenance=replace(
            required.provenance,
            references=(replace(reference, sha256="0" * 64),),
        ),
    )
    from sdaqf.application.context_contracts import artifact_from_value, source_identity

    changed = replace(changed, source_id=source_identity(changed.content_dict()))
    manifest = replace(
        manifest_artifact.value,
        sources=tuple(
            sorted(
                (
                    changed,
                    *(
                        source
                        for source in manifest_artifact.value.sources
                        if source is not required
                    ),
                ),
                key=lambda item: item.source_id,
            )
        ),
        relationships=(),
    )
    with pytest.raises(ContextIndexError, match="Required Context source"):
        ContextIndexer(
            LocalContextSourceReader(),
            PinnedContextCandidateVerifier(),
        ).build(
            artifact_from_value(ContextArtifactType.MANIFEST, manifest),
            repository_root=tmp_path,
        )
