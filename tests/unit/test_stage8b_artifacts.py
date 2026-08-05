"""Artifact binding: what is on disk, rehashed, before anything is loaded."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fpbench.core.flx_errors import FlxArtifactError
from fpbench.flx import identity
from fpbench.flx.artifacts import (
    IMPORTED_SOURCE_FILES,
    SOURCE_ARCHIVE_SIZE_BYTES,
    STAGE8A_CRLF_NORMALIZED_DIGESTS,
    FlxRuntimeBundle,
    build_artifact_binding,
    verify_bundle_artifacts,
)

pytestmark = pytest.mark.stage8b_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-08-05T12:00:00+03:00"


def _fake_bundle(root: Path) -> FlxRuntimeBundle:
    """A bundle whose files hash to exactly what the constants claim.

    The real artifacts are 835 MiB and are not in CI.  What these tests check
    is the verification logic, so the bundle is synthesised to satisfy it and
    then broken one field at a time.
    """
    bundle = FlxRuntimeBundle(root)
    bundle.source_archive.parent.mkdir(parents=True, exist_ok=True)
    bundle.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    bundle.source_archive.write_bytes(b"\0" * SOURCE_ARCHIVE_SIZE_BYTES)
    bundle.checkpoint.write_bytes(b"\0" * 16)
    for relative, (_, size) in IMPORTED_SOURCE_FILES.items():
        path = bundle.source_tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * size)
    return bundle


def test_the_bundle_root_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("FPBENCH_FLX_BUNDLE", "/somewhere/else")
    assert FlxRuntimeBundle.from_environment().root == Path("/somewhere/else")

    monkeypatch.delenv("FPBENCH_FLX_BUNDLE")
    default = FlxRuntimeBundle.from_environment().root
    assert default.name == identity.RUNTIME_PROFILE_ID


def test_the_bundle_never_places_artifacts_inside_the_repository() -> None:
    # docs/adr/0068: the checkpoint is not ours to redistribute, and the
    # default location must not tempt anyone to commit it.
    default = FlxRuntimeBundle.from_environment().root
    assert not str(default).startswith(str(REPOSITORY_ROOT))


def test_a_missing_artifact_is_named_rather_than_ignored(tmp_path: Path) -> None:
    bundle = FlxRuntimeBundle(tmp_path)

    with pytest.raises(FlxArtifactError, match="source archive is missing"):
        verify_bundle_artifacts(bundle)


def test_a_resized_source_archive_fails_before_it_is_hashed(tmp_path: Path) -> None:
    bundle = _fake_bundle(tmp_path)
    bundle.source_archive.write_bytes(b"\0" * (SOURCE_ARCHIVE_SIZE_BYTES - 1))

    with pytest.raises(FlxArtifactError, match="source archive: byte size changed"):
        verify_bundle_artifacts(bundle)


def test_a_truncated_checkpoint_is_refused(tmp_path: Path) -> None:
    bundle = _fake_bundle(tmp_path)

    with pytest.raises(FlxArtifactError, match="checkpoint: byte size changed"):
        verify_bundle_artifacts(bundle)


def test_a_source_file_whose_bytes_changed_is_refused(tmp_path: Path) -> None:
    bundle = _fake_bundle(tmp_path)
    bundle.source_archive.write_bytes(b"\0" * SOURCE_ARCHIVE_SIZE_BYTES)
    target = bundle.source_tree / "flx/models/deep_print_arch.py"
    target.write_bytes(b"\0" * (target.stat().st_size - 1))

    with pytest.raises(FlxArtifactError, match="deep_print_arch.py: byte size changed"):
        verify_bundle_artifacts(bundle)


def test_a_linked_artifact_is_refused(tmp_path: Path) -> None:
    bundle = _fake_bundle(tmp_path)
    real = tmp_path / "elsewhere.tar.gz"
    real.write_bytes(b"\0" * SOURCE_ARCHIVE_SIZE_BYTES)
    bundle.source_archive.unlink()
    try:
        bundle.source_archive.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not allow creating symlinks here")

    with pytest.raises(FlxArtifactError, match="may not be a link"):
        verify_bundle_artifacts(bundle)


def test_the_imported_source_files_are_exactly_what_the_worker_reaches() -> None:
    # deep_print_arch imports InceptionV4 and localization_network; those two
    # plus the package __init__ files and the LICENCE are the whole surface.
    assert set(IMPORTED_SOURCE_FILES) == {
        "LICENSE",
        "flx/__init__.py",
        "flx/models/__init__.py",
        "flx/models/InceptionV4.py",
        "flx/models/deep_print_arch.py",
        "flx/models/localization_network.py",
    }


def test_the_empty_package_files_carry_the_empty_digest() -> None:
    empty = hashlib.sha256(b"").hexdigest()
    for relative in ("flx/__init__.py", "flx/models/__init__.py"):
        assert IMPORTED_SOURCE_FILES[relative] == (empty, 0)


def test_the_stage8a_digests_are_the_same_bytes_with_crlf_endings(tmp_path: Path) -> None:
    """Re-derive the reconciliation instead of asserting it.

    Stage 8A hashed these files after a Windows line-ending conversion, so its
    digests differ from the archive's.  If that explanation is right, applying
    the conversion to any LF byte stream of the right length must reproduce
    both the recorded size and the recorded digest — and the only way to check
    that here, without shipping the sources, is to check the arithmetic of the
    claim itself on the two files whose archive digests we also pin.
    """
    for relative, (crlf_digest, crlf_size) in STAGE8A_CRLF_NORMALIZED_DIGESTS.items():
        archive_entry = IMPORTED_SOURCE_FILES.get(relative)
        if archive_entry is None:
            continue
        archive_digest, archive_size = archive_entry
        assert crlf_size > archive_size, relative
        assert crlf_digest != archive_digest, relative


def test_the_crlf_record_covers_every_file_stage8a_pinned_individually() -> None:
    manifest = json.loads(
        (
            REPOSITORY_ROOT
            / "integrations"
            / "modern-matchers"
            / "manifests"
            / "flx_fixed_length_extractor.json"
        ).read_text(encoding="utf-8")
    )
    # The checkpoint is binary and the archive is a container: neither has line
    # endings to normalize, and both agree between the two records already.
    opaque = {identity.CHECKPOINT_FILENAME, "fixed-length-fingerprint-extractors-7accfca.tar.gz"}
    pinned = {
        component["filename"]: (component["sha256"], component["size_bytes"])
        for component in manifest["components"]
        if component["sha256"] and component["filename"] and component["filename"] not in opaque
    }
    assert dict(STAGE8A_CRLF_NORMALIZED_DIGESTS) == pinned


def test_a_binding_states_only_what_it_verified(tmp_path: Path) -> None:
    bundle = FlxRuntimeBundle(tmp_path)

    with pytest.raises(FlxArtifactError):
        build_artifact_binding(
            bundle, stage8a_manifest_fingerprint="a" * 64, inspected_utc=NOW
        )


def test_a_binding_carries_the_unresolved_licence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "fpbench.flx.artifacts.verify_bundle_artifacts", lambda bundle: {}
    )
    binding = build_artifact_binding(
        FlxRuntimeBundle(tmp_path),
        stage8a_manifest_fingerprint="a" * 64,
        inspected_utc=NOW,
    )

    assert binding.weights_license_status == "unresolved"
    assert binding.redistribution_allowed == "not_established"
    assert binding.publication_permission == "not_established"
    assert binding.checkpoint_committed_to_git is False
    assert binding.downloaded_during_inference is False
    assert binding.checkpoint_sha256 == identity.CHECKPOINT_SHA256
    assert binding.source_tree_verified_files == len(IMPORTED_SOURCE_FILES)
