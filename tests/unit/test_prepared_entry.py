"""What a prepared entry refuses to be, and what its hash covers.

An entry is the only place where a source image and a canonical artefact are
named together, so it is the only place that can catch a mismatch between them.
Most of these tests build an entry that is internally contradictory and check
that it cannot exist — the constructor does the work, so no caller has to
remember to.

The hash tests are the other half. ``entry_hash`` must move when the *image*
changes and must not move when only its *position in a list* or its *place on a
disk* changes, because that is what makes the same canonical artefact reusable
across two sets and two workspaces (spec section 33).
"""

from __future__ import annotations

import dataclasses

import pytest

from fpbench.core.imaging_models import (
    TRANSFORM_ACTION_IDENTITY,
    PreparedImageEntry,
    prepared_image_entry_hash,
)
from canonicalworld import build_canonical_world

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_canonical_world(tmp_path_factory.mktemp("entries"))


@pytest.fixture()
def identity_entry(world):
    return next(entry for entry in world.entries if entry.is_identity)


@pytest.fixture()
def halved_entry(world):
    return next(
        entry for entry in world.entries if entry.source_effective_ppi == 1000
    )


@pytest.fixture()
def quartered_entry(world):
    return next(
        entry for entry in world.entries if entry.source_effective_ppi == 2000
    )


def _rebuild(entry: PreparedImageEntry, **changes) -> PreparedImageEntry:
    """Change a field and let the constructor re-check the whole entry."""
    fields = {
        field.name: getattr(entry, field.name)
        for field in dataclasses.fields(entry)
        if field.name != "entry_hash"
    }
    fields.update(changes)
    return PreparedImageEntry(
        entry_hash=prepared_image_entry_hash(_Draft(**fields)), **fields
    )


class _Draft:
    __slots__ = tuple(
        field.name
        for field in dataclasses.fields(PreparedImageEntry)
        if field.name != "entry_hash"
    )

    def __init__(self, **fields):
        for name in self.__slots__:
            setattr(self, name, fields[name])


# ------------------------------------------------------------ what it refuses


def test_a_wrong_source_digest_is_caught_by_the_entry_hash(identity_entry):
    """The hash covers the source digest, so changing it alone cannot survive."""
    with pytest.raises(ValueError, match="entry_hash does not cover"):
        dataclasses.replace(identity_entry, source_expected_sha256="a" * 64)


def test_a_wrong_source_resolution_breaks_the_scale_fraction(halved_entry):
    with pytest.raises(ValueError, match="scale_denominator"):
        _rebuild(halved_entry, source_effective_ppi=2000)


def test_a_wrong_scale_numerator_is_rejected(halved_entry):
    with pytest.raises(ValueError, match="scale_numerator"):
        _rebuild(halved_entry, scale_numerator=250)


def test_wrong_output_dimensions_are_rejected(halved_entry):
    with pytest.raises(ValueError, match="scales to"):
        _rebuild(halved_entry, output_width=halved_entry.output_width + 1)
    with pytest.raises(ValueError, match="scales to"):
        _rebuild(halved_entry, output_height=halved_entry.output_height - 1)


def test_a_wrong_output_resolution_is_rejected(halved_entry):
    """Changing the output ppi alone breaks both the fraction and the geometry."""
    with pytest.raises(ValueError):
        _rebuild(halved_entry, output_effective_ppi=400)


def test_upsampling_is_rejected(identity_entry):
    with pytest.raises(ValueError, match="upsampling"):
        _rebuild(identity_entry, source_effective_ppi=250, scale_denominator=250)


def test_the_identity_path_must_preserve_the_raster(identity_entry):
    with pytest.raises(ValueError, match="preserve the raster exactly"):
        _rebuild(identity_entry, output_pixel_sha256="b" * 64)


def test_the_identity_path_must_be_named_identity(identity_entry):
    with pytest.raises(ValueError, match=TRANSFORM_ACTION_IDENTITY):
        _rebuild(identity_entry, transform_action="downsample_1x_lanczos3")


def test_a_reducing_path_must_be_named_downsample(quartered_entry):
    with pytest.raises(ValueError, match="downsample"):
        _rebuild(quartered_entry, transform_action=TRANSFORM_ACTION_IDENTITY)


def test_a_non_png_output_is_rejected(halved_entry):
    with pytest.raises(ValueError, match="canonical artefact is a PNG"):
        _rebuild(halved_entry, output_media_type="image/tiff")


def test_an_absolute_relative_path_is_rejected(halved_entry):
    with pytest.raises(ValueError, match="workspace-relative"):
        _rebuild(halved_entry, relative_path="/var/tmp/output.png")


def test_a_path_escaping_the_workspace_is_rejected(halved_entry):
    with pytest.raises(ValueError, match="escape the workspace"):
        _rebuild(halved_entry, relative_path="../elsewhere/output.png")


@pytest.mark.parametrize(
    "field",
    [
        "source_size_bytes",
        "source_width",
        "source_height",
        "output_width",
        "output_height",
        "output_size_bytes",
    ],
)
def test_every_integer_field_must_be_an_exact_integer(halved_entry, field):
    with pytest.raises(ValueError, match="exact integer"):
        _rebuild(halved_entry, **{field: float(getattr(halved_entry, field))})


def test_a_negative_ordinal_is_rejected(halved_entry):
    with pytest.raises(ValueError, match="ordinal"):
        _rebuild(halved_entry, ordinal=-1)


# ------------------------------------------------------------ what it covers


def test_one_changed_output_pixel_changes_the_entry_hash(quartered_entry):
    changed = prepared_image_entry_hash(
        _Draft(
            **{
                **{
                    field.name: getattr(quartered_entry, field.name)
                    for field in dataclasses.fields(quartered_entry)
                    if field.name != "entry_hash"
                },
                "output_pixel_sha256": "c" * 64,
            }
        )
    )
    assert changed != quartered_entry.entry_hash


def test_a_different_runtime_changes_the_entry_hash(quartered_entry):
    changed = _rebuild(quartered_entry, transform_runtime_fingerprint="d" * 64)
    assert changed.entry_hash != quartered_entry.entry_hash


def test_a_different_transform_profile_changes_the_entry_hash(quartered_entry):
    changed = _rebuild(quartered_entry, transform_profile_fingerprint="e" * 64)
    assert changed.entry_hash != quartered_entry.entry_hash


def test_the_ordinal_does_not_affect_the_entry_hash(quartered_entry):
    """A position in a list is not a property of an image.

    Putting the ordinal in ``entry_hash`` would mean the same canonical artefact
    materialised into a second set hashed differently, and then nothing could be
    reused.
    """
    moved = _rebuild(quartered_entry, ordinal=quartered_entry.ordinal + 7)
    assert moved.entry_hash == quartered_entry.entry_hash


def test_the_relative_path_does_not_affect_the_entry_hash(quartered_entry):
    """Where a workspace sits on one machine is not a property of an image."""
    elsewhere = _rebuild(
        quartered_entry, relative_path="prepared-images/images/zz/" + "f" * 64 + ".png"
    )
    assert elsewhere.entry_hash == quartered_entry.entry_hash


def test_the_encoded_digest_is_inside_the_entry_hash(quartered_entry):
    """Both identities are load-bearing (docs/adr/0034).

    Two entries with the same raster and different files are different entries:
    a matcher opens the file, not the raster.
    """
    changed = _rebuild(quartered_entry, output_encoded_sha256="a" * 64)
    assert changed.entry_hash != quartered_entry.entry_hash


def test_the_three_sd300_paths_are_all_represented(world):
    actions = {entry.transform_action for entry in world.entries}
    assert actions == {
        "identity_pixels_reencode",
        "downsample_2x_lanczos3",
        "downsample_4x_lanczos3",
    }


def test_every_identity_entry_preserves_its_source_raster(world):
    identity = [entry for entry in world.entries if entry.is_identity]
    assert identity
    for entry in identity:
        assert entry.source_pixel_sha256 == entry.output_pixel_sha256
        assert (entry.source_width, entry.source_height) == (
            entry.output_width,
            entry.output_height,
        )
