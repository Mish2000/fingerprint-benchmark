from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.errors import CandidateArtifactError, StorageError
from fpbench.modern_matchers.artifacts import ModernMatcherArtifactStore
from fpbench.storage.modern_matcher_store import Stage8AEvidenceStore
from stage8aworld import (
    build_evidence_world,
    make_candidate,
    make_manifest,
    make_registry,
    make_report,
    rebuild,
    write_artifact_files,
)

pytestmark = pytest.mark.stage8a_contract


def test_the_evidence_store_uses_the_exact_public_tree(tmp_path: Path) -> None:
    store = Stage8AEvidenceStore(tmp_path)
    assert store.evidence_dir == (
        tmp_path / "evidence/stage8a-modern-matcher-selection"
    )
    assert store.registry_path.name == "candidate-registry.json"
    assert store.selection_path.name == "selection-decision.json"
    assert store.finalization_path.name == "stage-8a-finalization.json"
    assert store.readme_path.name == "README.md"
    assert store.qualification_path("candidate_alpha").name == (
        "qualification-candidate_alpha.json"
    )


def test_registry_must_precede_qualification_and_selection(tmp_path: Path) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    report = make_report(candidate, registry)
    store = Stage8AEvidenceStore(tmp_path)

    with pytest.raises(StorageError, match="registry must be written"):
        store.ensure_qualification(candidate.candidate_id, report)
    with pytest.raises(StorageError, match="registry must exist"):
        store.ensure_selection(object(), (candidate.candidate_id,))  # type: ignore[arg-type]


def test_identical_store_retry_is_byte_identical_and_conflicts_do_not_overwrite(
    tmp_path: Path,
) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    report = make_report(candidate, registry)
    store = Stage8AEvidenceStore(tmp_path)
    store.ensure_registry(registry)
    path = store.ensure_qualification(candidate.candidate_id, report)
    before = path.read_bytes()

    assert store.ensure_qualification(candidate.candidate_id, report) == path
    assert path.read_bytes() == before

    changed = rebuild(report, paper_year=report.paper_year - 1)
    with pytest.raises(StorageError, match="refusing to overwrite"):
        store.ensure_qualification(candidate.candidate_id, changed)
    assert path.read_bytes() == before


def test_finalization_is_refused_before_every_prerequisite_exists(tmp_path: Path) -> None:
    finished = build_evidence_world(tmp_path / "finished", ready=True)
    empty = Stage8AEvidenceStore(tmp_path / "empty")
    candidate_ids = tuple(
        candidate.candidate_id for candidate in finished.registry.candidates
    )

    with pytest.raises(StorageError, match="finalization is last"):
        empty.ensure_finalization(finished.finalization, candidate_ids)


def test_artifact_store_rehashes_every_required_file(tmp_path: Path) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(candidate, registry)
    payloads = {
        "source_bundle": b"source-bundle",
        "model_checkpoint": b"model-checkpoint",
        "threshold_documentation": b"threshold-document",
    }
    write_artifact_files(tmp_path, manifest, payloads)

    verified = ModernMatcherArtifactStore(tmp_path).verify_manifest(manifest)
    assert set(verified) == set(payloads)

    checkpoint = verified["model_checkpoint"]
    checkpoint.write_bytes(b"model-checkpoinu")
    with pytest.raises(CandidateArtifactError, match="SHA-256 changed"):
        ModernMatcherArtifactStore(tmp_path).verify_manifest(manifest)


def test_artifact_paths_cannot_escape_the_supplied_root(tmp_path: Path) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(candidate, registry)
    escaped = rebuild(manifest, storage_reference="../outside")

    with pytest.raises(CandidateArtifactError, match="relative logical path"):
        ModernMatcherArtifactStore(tmp_path).verify_manifest(escaped)


@pytest.mark.parametrize(
    "unsafe_path",
    (
        r"C:\outside\file",
        r"\\server\share\file",
        r"..\outside\file",
        "C:/outside/file",
        "candidate/source.bin:alternate-stream",
        "candidate//nested",
        "candidate/./nested",
        "candidate/CON",
        "candidate/trailing.",
    ),
)
def test_windows_and_noncanonical_storage_paths_are_rejected_on_every_platform(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(candidate, registry)
    escaped = rebuild(manifest, storage_reference=unsafe_path)

    with pytest.raises(CandidateArtifactError, match="canonical relative logical path"):
        ModernMatcherArtifactStore(tmp_path).verify_manifest(escaped)


@pytest.mark.parametrize(
    "unsafe_path",
    (
        r"C:\outside\file",
        r"\\server\share\file",
        r"..\outside\file",
        "C:/outside/file",
        "source_bundle.bin:alternate-stream",
        "nested//source_bundle.bin",
        "nested/./source_bundle.bin",
        "CON/source_bundle.bin",
        "nested/source_bundle.bin.",
    ),
)
def test_windows_and_noncanonical_component_paths_are_rejected_on_every_platform(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(candidate, registry)
    write_artifact_files(
        tmp_path,
        manifest,
        {
            "source_bundle": b"source-bundle",
            "model_checkpoint": b"model-checkpoint",
            "threshold_documentation": b"threshold-document",
        },
    )
    source, checkpoint, documentation = manifest.components
    unsafe_source = rebuild(source, filename=unsafe_path)
    escaped = rebuild(
        manifest, components=(unsafe_source, checkpoint, documentation)
    )

    with pytest.raises(CandidateArtifactError, match="canonical relative logical path"):
        ModernMatcherArtifactStore(tmp_path).verify_manifest(escaped)


def test_canonical_nested_posix_paths_are_accepted(tmp_path: Path) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(
        candidate,
        registry,
        storage_reference="candidates/candidate_alpha/v1",
    )
    source, checkpoint, documentation = manifest.components
    source = rebuild(source, filename="archives/source_bundle.bin")
    checkpoint = rebuild(checkpoint, filename="weights/model_checkpoint.bin")
    manifest = rebuild(
        manifest, components=(source, checkpoint, documentation)
    )
    assert manifest.storage_reference is not None
    base = tmp_path / manifest.storage_reference
    (base / "archives").mkdir(parents=True)
    (base / "weights").mkdir()
    (base / source.filename).write_bytes(b"source-bundle")  # type: ignore[arg-type]
    (base / checkpoint.filename).write_bytes(b"model-checkpoint")  # type: ignore[arg-type]
    (base / documentation.filename).write_bytes(b"threshold-document")  # type: ignore[arg-type]

    verified = ModernMatcherArtifactStore(tmp_path).verify_manifest(manifest)

    assert verified["source_bundle"] == base / "archives/source_bundle.bin"
    assert verified["model_checkpoint"] == base / "weights/model_checkpoint.bin"


def test_resolved_artifact_paths_must_remain_beneath_the_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    store = ModernMatcherArtifactStore(root)

    with pytest.raises(CandidateArtifactError, match="escapes the supplied root"):
        store._resolved_beneath_root(outside, "fixture")


def test_artifact_read_errors_are_wrapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(candidate, registry)
    write_artifact_files(
        tmp_path,
        manifest,
        {
            "source_bundle": b"source-bundle",
            "model_checkpoint": b"model-checkpoint",
            "threshold_documentation": b"threshold-document",
        },
    )
    original_open = Path.open

    def unreadable_source(path: Path, *args: object, **kwargs: object):
        if path.name == "source_bundle.bin":
            raise PermissionError("fixture denies access")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unreadable_source)

    with pytest.raises(CandidateArtifactError, match="could not be read") as captured:
        ModernMatcherArtifactStore(tmp_path).verify_manifest(manifest)

    assert isinstance(captured.value.__cause__, PermissionError)


def test_even_an_in_tree_symlink_is_not_a_regular_artifact(tmp_path: Path) -> None:
    candidate = make_candidate()
    registry = make_registry((candidate,))
    manifest = make_manifest(candidate, registry)
    source, checkpoint, documentation = manifest.components
    linked_source = rebuild(source, filename="linked-source.bin")
    manifest = rebuild(
        manifest, components=(linked_source, checkpoint, documentation)
    )
    assert manifest.storage_reference is not None
    base = tmp_path / manifest.storage_reference
    base.mkdir(parents=True)
    target = base / "source-target.bin"
    target.write_bytes(b"source-bundle")
    try:
        (base / "linked-source.bin").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this platform policy does not permit symlinks")
    (base / checkpoint.filename).write_bytes(b"model-checkpoint")  # type: ignore[arg-type]

    with pytest.raises(CandidateArtifactError, match="non-link"):
        ModernMatcherArtifactStore(tmp_path).verify_manifest(manifest)


def test_candidate_ids_cannot_traverse_out_of_the_evidence_tree(
    tmp_path: Path,
) -> None:
    store = Stage8AEvidenceStore(tmp_path)
    with pytest.raises(ValueError):
        store.qualification_path("../outside")
