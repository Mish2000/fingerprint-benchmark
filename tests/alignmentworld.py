"""Two runs' worth of inputs, small enough to mutate one field at a time.

The alignment check is about *differences*, and a test of it is only worth
having if it can introduce exactly one. Building the pairs and the prepared
entries by hand — rather than materialising a real prepared-image set — is what
makes "the same world except this pixel hash" a two-line change.

Everything the builder produces is a real model: real :class:`ComparisonPair`
rows and real :class:`PreparedImageEntry` records, which means every invariant
those models enforce is enforced here too. An entry whose output geometry does
not follow from its source geometry cannot be constructed at all, so the
negative cases below are the ones that are genuinely possible: a *different*
valid entry, not an impossible one.

Nothing here is a fingerprint and nothing here is a score. The digests are
arithmetic on labels.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from fpbench.core.enums import GroundTruth, ProtocolStage
from fpbench.core.identifiers import ImageId, PairId, compose_id
from fpbench.core.imaging_models import (
    TRANSFORM_ACTION_DOWNSAMPLE_PREFIX,
    TRANSFORM_ACTION_IDENTITY,
    PreparedImageEntry,
    prepared_image_entry_hash,
    scale_dimension,
)
from fpbench.core.models import ComparisonPair
from fpbench.experiments.canonical_run_alignment import (
    AlignmentExpectations,
    AlignmentSide,
    ReferenceRunIdentity,
)

__all__ = [
    "AlignmentWorld",
    "build_alignment_world",
    "make_entry",
    "digest",
    "REFERENCE",
]

#: The identifiers a test's reference chain is defined against. Deliberately not
#: the real ones: a unit test that quoted ``run_4c59fa02a6ab`` would be asserting
#: something about a workspace it does not have.
REFERENCE = ReferenceRunIdentity(
    run_id="run_aaaaaaaaaaaa",
    plan_id="plan_bbbbbbbbbbbb",
    result_set_id="resultset_cccccccccccc",
    preparation_set_id="prepset_dddddddddddd",
    preparation_set_fingerprint="d" * 64,
)

_SOURCE_PPI = {"SD300A": 500, "SD300B": 1000, "SD300C": 2000}
_TARGET_PPI = 500
_BASE = (48, 40)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def make_entry(
    *,
    image_id: str,
    ordinal: int,
    source_ppi: int,
    output_ppi: int = _TARGET_PPI,
    base_size: tuple[int, int] = _BASE,
    seed: str = "",
    transform_profile_fingerprint: str = "e" * 64,
    transform_runtime_fingerprint: str = "f" * 64,
) -> PreparedImageEntry:
    """One valid prepared entry, with digests derived from its own identity.

    The entry hash is computed by the production function over a stand-in with
    the same fields, because the real model refuses to be constructed with a
    hash that does not cover it — which is the property under test elsewhere and
    would otherwise make this builder impossible.
    """
    scale = source_ppi // output_ppi
    source_width = base_size[0] * scale
    source_height = base_size[1] * scale
    fields = {
        "ordinal": ordinal,
        "image_id": ImageId(image_id),
        "source_record_fingerprint": digest(f"record:{image_id}:{seed}"),
        "source_expected_sha256": digest(f"source:{image_id}:{seed}"),
        "source_size_bytes": 1024 * scale,
        "source_effective_ppi": source_ppi,
        "source_declared_ppi": str(source_ppi),
        "source_width": source_width,
        "source_height": source_height,
        "source_pixel_sha256": digest(f"source-pixels:{image_id}:{seed}"),
        "transform_profile_id": "canonical_gray8_500ppi_lanczos3_v1",
        "transform_profile_fingerprint": transform_profile_fingerprint,
        "transform_runtime_fingerprint": transform_runtime_fingerprint,
        "transform_action": (
            TRANSFORM_ACTION_IDENTITY
            if source_ppi == output_ppi
            else f"{TRANSFORM_ACTION_DOWNSAMPLE_PREFIX}_lanczos3"
        ),
        "scale_numerator": output_ppi,
        "scale_denominator": source_ppi,
        "output_width": scale_dimension(
            source_width, target_ppi=output_ppi, source_ppi=source_ppi
        ),
        "output_height": scale_dimension(
            source_height, target_ppi=output_ppi, source_ppi=source_ppi
        ),
        "output_effective_ppi": output_ppi,
        "output_pixel_sha256": (
            digest(f"source-pixels:{image_id}:{seed}")
            if source_ppi == output_ppi
            else digest(f"output-pixels:{image_id}:{output_ppi}:{seed}")
        ),
        "output_encoded_sha256": digest(f"encoded:{image_id}:{output_ppi}:{seed}"),
        "output_size_bytes": 512,
        "output_media_type": "image/png",
        "relative_path": f"prepared-images/images/{image_id}.png",
    }
    stand_in = _EntryStandIn(**fields)
    return PreparedImageEntry(**fields, entry_hash=prepared_image_entry_hash(stand_in))


@dataclass(frozen=True, slots=True)
class AlignmentWorld:
    """One aligned experiment, and the two sides that describe it."""

    pairs: Mapping[str, ComparisonPair]
    pair_sequence: tuple[str, ...]
    entries: Mapping[str, PreparedImageEntry]
    image_releases: Mapping[str, str]
    expectations: AlignmentExpectations
    reference: ReferenceRunIdentity

    def side(self, label: str, **overrides: object) -> AlignmentSide:
        """A side over this world, with any field replaced.

        ``label`` is what the issue messages say, so the two sides are told
        apart in a failure without the test having to decode ids.
        """
        defaults: dict[str, object] = {
            "label": label,
            "run_id": (
                self.reference.run_id if label == "reference" else "run_111111111111"
            ),
            "plan_id": (
                self.reference.plan_id if label == "reference" else "plan_222222222222"
            ),
            "result_set_id": (
                self.reference.result_set_id if label == "reference" else None
            ),
            "protocol_id": "sd300_50_subjects",
            "cohort_id": "sd300_50_subjects_test_abcdef123456",
            "pair_manifest_hash": digest("pair-manifest"),
            "preparation_set_id": self.reference.preparation_set_id,
            "preparation_set_fingerprint": (
                self.reference.preparation_set_fingerprint
            ),
            "pair_sequence": self.pair_sequence,
            "pairs": dict(self.pairs),
            "prepared_entries": dict(self.entries),
            "image_releases": dict(self.image_releases),
            "research_ready": True if label == "reference" else None,
            "research_status": "research_ready" if label == "reference" else None,
        }
        defaults.update(overrides)
        return AlignmentSide(**defaults)  # type: ignore[arg-type]


def build_alignment_world(
    *,
    releases: Sequence[str] = ("SD300A", "SD300B", "SD300C"),
    per_cell: int = 2,
) -> AlignmentWorld:
    """``per_cell`` comparisons in each of the four stages, in every release.

    The same shape as the real experiment at 1/250 of the size: two SELF stages,
    a mated stage and a non-mated sanity stage, with every image taking part in
    at least one comparison so that the participating set is the whole set.
    """
    pairs: dict[str, ComparisonPair] = {}
    entries: dict[str, PreparedImageEntry] = {}
    image_releases: dict[str, str] = {}
    ordinal = 0

    for release in releases:
        source_ppi = _SOURCE_PPI[release]
        plain: list[str] = []
        roll: list[str] = []
        for index in range(per_cell):
            subject = f"s{index + 1:04d}"
            for impression, bucket in (("plain", plain), ("roll", roll)):
                image_id = compose_id(release, subject, impression, "f01")
                bucket.append(image_id)
                entries[image_id] = make_entry(
                    image_id=image_id, ordinal=ordinal, source_ppi=source_ppi
                )
                image_releases[image_id] = release
                ordinal += 1

        for index in range(per_cell):
            for stage, left, right, truth in (
                (
                    ProtocolStage.PLAIN_SELF,
                    plain[index],
                    plain[index],
                    GroundTruth.MATED,
                ),
                (ProtocolStage.ROLL_SELF, roll[index], roll[index], GroundTruth.MATED),
                (
                    ProtocolStage.PLAIN_ROLL_MATED,
                    plain[index],
                    roll[index],
                    GroundTruth.MATED,
                ),
                (
                    ProtocolStage.PLAIN_ROLL_NON_MATED,
                    plain[index],
                    roll[(index + 1) % per_cell],
                    GroundTruth.NON_MATED,
                ),
            ):
                pair_id = compose_id(release, stage.value, f"p{index:03d}")
                pairs[pair_id] = ComparisonPair(
                    pair_id=PairId(pair_id),
                    dataset_id="sd300",
                    release=release,
                    left_image_id=ImageId(left),
                    right_image_id=ImageId(right),
                    ground_truth=truth,
                    protocol_stage=stage,
                )

    from fpbench.execution.planner import canonical_pair_order

    sequence = tuple(
        str(pair.pair_id) for pair in sorted(pairs.values(), key=canonical_pair_order)
    )
    return AlignmentWorld(
        pairs=pairs,
        pair_sequence=sequence,
        entries=entries,
        image_releases=image_releases,
        expectations=AlignmentExpectations(
            pair_count=per_cell * len(ProtocolStage) * len(releases),
            prepared_entry_count=2 * per_cell * len(releases),
            pairs_per_release_stage=per_cell,
            prepared_entries_per_release=2 * per_cell,
            releases=tuple(releases),
        ),
        reference=REFERENCE,
    )


def replaced_pair(pair: ComparisonPair, **changes: object) -> ComparisonPair:
    """One pair, with one field different. Kept here so tests read as one line."""
    return replace(pair, **changes)  # type: ignore[arg-type]


class _EntryStandIn:
    """Attribute-only stand-in, so the real entry hash can be computed first."""

    __slots__ = (
        "ordinal",
        "image_id",
        "source_record_fingerprint",
        "source_expected_sha256",
        "source_size_bytes",
        "source_effective_ppi",
        "source_declared_ppi",
        "source_width",
        "source_height",
        "source_pixel_sha256",
        "transform_profile_id",
        "transform_profile_fingerprint",
        "transform_runtime_fingerprint",
        "transform_action",
        "scale_numerator",
        "scale_denominator",
        "output_width",
        "output_height",
        "output_effective_ppi",
        "output_pixel_sha256",
        "output_encoded_sha256",
        "output_size_bytes",
        "output_media_type",
        "relative_path",
    )

    def __init__(self, **fields: object) -> None:
        for name in self.__slots__:
            setattr(self, name, fields[name])
