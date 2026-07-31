"""The preparer that must not resample anything.

Its whole job is to look up an artefact somebody else produced, prove it is the
right one, prove it has not moved, and point at it. Two things are being tested:
that it does that correctly, and that it does *not* do the thing whose absence is
the fairness argument — no decode, no resize, no encode, at comparison time.

The drift tests are the sharpest ones. A prepared artefact that changes during a
run is not a bad comparison; it is a run whose results cannot be attributed, and
``PreparedImageDriftError`` is a ``RuntimeDriftError`` precisely so the runner's
existing "re-raise, never record" rule applies to it unchanged.
"""

from __future__ import annotations

import dataclasses
import stat

import pytest

from fpbench.core.enums import ChecksumStatus
from fpbench.core.errors import (
    ImagePreparationError,
    PreflightError,
    PreparedImageDriftError,
    RuntimeDriftError,
)
from fpbench.core.execution_models import ExecutionProfile
from fpbench.imaging.canonical500 import (
    PREPARER_ID,
    PREPARER_VERSION,
    RESOLUTION_MODE,
    RUNNER_METADATA_SCHEMA,
    Canonical500ImagePreparer,
)
from canonicalworld import build_canonical_world, publish_receipt_and_marker

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


@pytest.fixture()
def world(tmp_path):
    built = build_canonical_world(tmp_path)
    publish_receipt_and_marker(built)
    return built


def _profile(world, **overrides) -> ExecutionProfile:
    parameters = {
        "resolution_mode": RESOLUTION_MODE,
        "target_ppi": "500",
        "transform_profile_id": world.profile.profile_id,
        "transform_profile_fingerprint": world.profile.profile_fingerprint,
        "preparation_set_id": world.preparation_set_id,
        "preparation_set_fingerprint": world.preparation_set_fingerprint,
        "output_media_type": "image/png",
        "output_pixel_format": "gray8",
        "output_ppi_metadata_policy": "fixed_500",
    }
    parameters.update(overrides)
    return ExecutionProfile(
        profile_id="canonical_500_lanczos3_60s_v1",
        preparer_id=PREPARER_ID,
        timeout_seconds=60,
        deterministic_seed=0,
        parameters=parameters,
    )


def _preparer(world, **overrides) -> Canonical500ImagePreparer:
    preparer = Canonical500ImagePreparer(
        store=world.store,
        preparation_set_id=overrides.get(
            "preparation_set_id", world.preparation_set_id
        ),
        preparation_set_fingerprint=overrides.get(
            "preparation_set_fingerprint", world.preparation_set_fingerprint
        ),
    )
    return preparer


def _writable(path):
    path.chmod(path.stat().st_mode | stat.S_IWUSR)
    return path


# ------------------------------------------------------------------ lookup


def test_a_lookup_returns_the_exact_prepared_entry(world):
    preparer = _preparer(world)
    preparer.preflight()
    image_id = world.entries[0].image_id
    entry = world.entry_for(image_id)

    prepared = preparer.prepare(
        world.images[image_id], world.dataset_root, _profile(world)
    )

    assert prepared.image_id == image_id
    assert prepared.local_path == (world.workspace / entry.relative_path).resolve()
    assert prepared.preparation_entry_hash == entry.entry_hash
    assert prepared.prepared_sha256 == entry.output_encoded_sha256
    assert prepared.pixel_sha256 == entry.output_pixel_sha256
    assert prepared.pixel_width == entry.output_width
    assert prepared.pixel_height == entry.output_height
    assert prepared.preparation_set_id == world.preparation_set_id
    assert prepared.preparation_set_fingerprint == world.preparation_set_fingerprint


def test_preflight_source_bundle_must_match_every_external_identity(world):
    preparer = _preparer(world)
    preparer.preflight()
    preparer.require_source_bundle(world.source_bundle)

    forged = dataclasses.replace(world.source_bundle, pair_manifest_hash="f" * 64)
    with pytest.raises(PreflightError, match="source manifests"):
        preparer.require_source_bundle(forged)


def test_preflight_source_bundle_requires_the_exact_participating_image_order(world):
    preparer = _preparer(world)
    preparer.preflight()
    forged = dataclasses.replace(
        world.source_bundle,
        ordered_image_ids=world.source_bundle.ordered_image_ids[:-1],
    )
    with pytest.raises(PreflightError, match="source manifests"):
        preparer.require_source_bundle(forged)


def test_the_effective_resolution_is_always_the_target(world):
    preparer = _preparer(world)
    preparer.preflight()
    for entry in world.entries:
        prepared = preparer.prepare(
            world.images[entry.image_id], world.dataset_root, _profile(world)
        )
        assert prepared.effective_ppi == 500
        assert prepared.source_effective_ppi == entry.source_effective_ppi
        assert prepared.media_type == "image/png"


def test_the_source_digest_keeps_its_own_meaning(world):
    """``expected_sha256`` stays the publisher's digest of the *source*.

    Overloading it with the prepared file's digest would make a canonical run
    indistinguishable from a native one in every stored result (spec section 60).
    """
    preparer = _preparer(world)
    preparer.preflight()
    # A resampled entry, where the two files cannot coincide. (For an SD300A
    # identity entry the pixels are the same by design, and this synthetic
    # world's sources happen to use the canonical encoder, so the two digests
    # would legitimately match.)
    entry = next(e for e in world.entries if e.source_effective_ppi == 2000)
    prepared = preparer.prepare(
        world.images[entry.image_id], world.dataset_root, _profile(world)
    )
    assert prepared.expected_sha256 == entry.source_expected_sha256
    assert prepared.source_expected_sha256 == entry.source_expected_sha256
    assert prepared.prepared_sha256 == entry.output_encoded_sha256
    assert prepared.prepared_sha256 != prepared.expected_sha256


def test_preparation_decodes_nothing(world, monkeypatch):
    """The fairness claim, asserted rather than described.

    If ``prepare`` opened an image it would be resampling inside a run, under one
    algorithm's timing budget, with nothing recording that it had happened.
    """
    from PIL import Image

    def forbidden(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("the canonical preparer decoded an image")

    preparer = _preparer(world)
    preparer.preflight()
    monkeypatch.setattr(Image, "open", forbidden)
    monkeypatch.setattr(Image, "frombytes", forbidden)

    entry = world.entries[0]
    preparer.prepare(world.images[entry.image_id], world.dataset_root, _profile(world))


# --------------------------------------------------------------- preflight


def test_an_unverified_preparer_refuses_to_serve(world):
    preparer = _preparer(world)
    entry = world.entries[0]
    with pytest.raises(PreflightError, match="has not been verified"):
        preparer.prepare(
            world.images[entry.image_id], world.dataset_root, _profile(world)
        )


def test_the_wrong_preparation_set_is_refused_at_preflight(world):
    preparer = _preparer(world, preparation_set_fingerprint="a" * 64)
    with pytest.raises(PreflightError, match="pinned to"):
        preparer.preflight()


def test_a_set_with_no_marker_is_refused_at_preflight(tmp_path):
    """A set that was never finalised is not an input set.

    Every image might be present and correct; without the marker nothing has
    stated that the chain was re-verified as a whole (spec section 56).
    """
    unfinished = build_canonical_world(tmp_path)
    preparer = Canonical500ImagePreparer(
        store=unfinished.store,
        preparation_set_id=unfinished.preparation_set_id,
        preparation_set_fingerprint=unfinished.preparation_set_fingerprint,
    )
    with pytest.raises(PreflightError, match="did not verify"):
        preparer.preflight()


def test_a_missing_image_is_a_run_level_failure_not_six_thousand_pair_failures(world):
    preparer = _preparer(world)
    preparer.preflight()
    absent = {"sd300a_s9999_plain_f01"}
    with pytest.raises(PreflightError, match="holds no artefact"):
        preparer.require_expected_images(set(world.images) | absent)


def test_a_superset_is_accepted(world):
    """Reuse is the point: a set materialised for more than this run is fine."""
    preparer = _preparer(world)
    preparer.preflight()
    preparer.require_expected_images({world.entries[0].image_id})


def test_a_missing_entry_is_refused_at_prepare_time_too(world):
    preparer = _preparer(world)
    preparer.preflight()
    entry = world.entries[0]
    stranger = dataclasses.replace(
        world.images[entry.image_id], image_id="sd300a_s9999_plain_f01"
    )
    with pytest.raises(ImagePreparationError, match="holds no canonical artefact"):
        preparer.prepare(stranger, world.dataset_root, _profile(world))


# ------------------------------------------------------ profile agreement


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("preparation_set_id", "prepset_000000000000"),
        ("preparation_set_fingerprint", "b" * 64),
        ("transform_profile_fingerprint", "c" * 64),
        ("transform_profile_id", "some_other_profile_v1"),
    ],
)
def test_an_execution_profile_naming_a_different_set_is_refused(world, key, value):
    preparer = _preparer(world)
    preparer.preflight()
    entry = world.entries[0]
    with pytest.raises(ImagePreparationError):
        preparer.prepare(
            world.images[entry.image_id],
            world.dataset_root,
            _profile(world, **{key: value}),
        )


def test_a_non_canonical_execution_profile_is_refused(world):
    preparer = _preparer(world)
    preparer.preflight()
    entry = world.entries[0]
    with pytest.raises(ImagePreparationError, match="canonical_500"):
        preparer.prepare(
            world.images[entry.image_id],
            world.dataset_root,
            _profile(world, resolution_mode="native"),
        )


# --------------------------------------------------------- source agreement


def test_a_changed_source_record_is_refused(world):
    """An image manifest rebuilt under a different resolution policy.

    The bytes are unchanged and the digest still matches; only ``effective_ppi``
    moved, which is exactly what decided the scale (docs/adr/0032).
    """
    preparer = _preparer(world)
    preparer.preflight()
    entry = next(e for e in world.entries if e.source_effective_ppi == 2000)
    rewritten = dataclasses.replace(world.images[entry.image_id], effective_ppi=1000)
    with pytest.raises(ImagePreparationError, match="scaled from"):
        preparer.prepare(rewritten, world.dataset_root, _profile(world))


def test_an_unverified_source_checksum_is_refused(world):
    preparer = _preparer(world)
    preparer.preflight()
    entry = world.entries[0]
    unverified = dataclasses.replace(
        world.images[entry.image_id], checksum_status=ChecksumStatus.NOT_VERIFIED
    )
    with pytest.raises(ImagePreparationError, match="VERIFIED"):
        preparer.prepare(unverified, world.dataset_root, _profile(world))


def test_a_blocked_source_is_refused(world):
    preparer = _preparer(world)
    preparer.preflight()
    entry = world.entries[0]
    blocked = dataclasses.replace(
        world.images[entry.image_id], blocking_issues=("E_SOMETHING",)
    )
    with pytest.raises(ImagePreparationError, match="blocked by validation"):
        preparer.prepare(blocked, world.dataset_root, _profile(world))


# ------------------------------------------------------------------- drift


def test_a_changed_artefact_raises_drift_rather_than_failing_a_pair(world):
    preparer = _preparer(world)
    preparer.preflight()
    entry = world.entries[0]
    path = world.artifact_path(entry)
    data = bytearray(path.read_bytes())
    data[-5] ^= 0xFF
    _writable(path).write_bytes(bytes(data))

    with pytest.raises(PreparedImageDriftError, match="changed during the run"):
        preparer.prepare(
            world.images[entry.image_id], world.dataset_root, _profile(world)
        )


def test_prepared_image_drift_is_a_runtime_drift_error(world):
    """So the runner's existing fatal-and-unrecorded rule applies unchanged."""
    assert issubclass(PreparedImageDriftError, RuntimeDriftError)


def test_a_deleted_artefact_raises_drift(world):
    preparer = _preparer(world)
    preparer.preflight()
    entry = world.entries[0]
    _writable(world.artifact_path(entry)).unlink()

    with pytest.raises(PreparedImageDriftError):
        preparer.prepare(
            world.images[entry.image_id], world.dataset_root, _profile(world)
        )


# ------------------------------------------------------------------- SELF


def test_a_self_comparison_calls_the_preparer_twice_and_may_reuse_one_artefact(world):
    """One immutable PNG, two independent lookups.

    Materialising a second identical file for a SELF comparison would prove
    nothing: independence is a property of *template extraction*, not of
    resampling, and the bridge still extracts twice (docs/adr/0035).
    """
    preparer = _preparer(world)
    preparer.preflight()
    entry = world.entries[0]
    record = world.images[entry.image_id]

    left = preparer.prepare(record, world.dataset_root, _profile(world))
    right = preparer.prepare(record, world.dataset_root, _profile(world))

    assert left.local_path == right.local_path
    assert left.preparation_entry_hash == right.preparation_entry_hash
    assert left is not right


# ---------------------------------------------------------------- metadata


def test_the_preparer_declares_its_own_provenance_keys(world):
    preparer = _preparer(world)
    preparer.preflight()
    assert preparer.preparer_id == PREPARER_ID
    assert preparer.preparer_version == PREPARER_VERSION
    assert preparer.runner_metadata_schema == RUNNER_METADATA_SCHEMA

    run_level = preparer.run_metadata()
    assert run_level["preparation_set_id"] == world.preparation_set_id
    assert run_level["transform_profile_id"] == world.profile.profile_id
    assert run_level["transform_runtime_fingerprint"] == world.runtime.runtime_fingerprint

    entry = world.entries[0]
    prepared = preparer.prepare(
        world.images[entry.image_id], world.dataset_root, _profile(world)
    )
    side = preparer.side_metadata(prepared)
    assert side["preparation_entry_hash"] == entry.entry_hash
    assert side["output_ppi"] == "500"
    assert side["source_ppi"] == str(entry.source_effective_ppi)
    assert not any("path" in key for key in side)
