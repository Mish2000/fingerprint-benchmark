"""The SD300 inputs every stage-4B-and-later experiment starts from.

Extracted from the native SourceAFIS experiment when a second experiment needed
exactly the same thing: the same 50-subject cohort, the same 6,000 pairs, the
same 3,000 participating images, checked the same way. Two copies of this would
be two chances to disagree about what "the experiment" is, and the whole
argument of stage 6A is that native and canonical runs differ in *one* thing.

This module is allowed to know facts the rest of the harness is not — that
SD300A is 500 ppi, that the protocol yields 6,000 pairs, that a research run
needs VERIFIED checksums. Those are facts about *this experiment*, and the entire
reason an ``experiments`` package exists is that they have somewhere to live
other than the planner (docs/adr/0007).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.enums import ChecksumStatus, ProtocolStage
from fpbench.core.errors import ResearchPreflightError
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.imaging_models import PreparationSourceBundle
from fpbench.core.models import Cohort, ComparisonPair, ImageRecord
from fpbench.core.serialization import stable_hash
from fpbench.datasets import create_provider, load_dataset_spec, summarise_subjects
from fpbench.datasets.sd300 import ppi_policy
from fpbench.protocols.sd300_protocol import SD300Protocol
from fpbench.storage.manifest_store import ManifestStore

__all__ = [
    "SD300Inputs",
    "load_sd300_inputs",
    "participating_image_ids",
    "preparation_source_bundle",
    "require_expected_shape",
    "EXPECTED_SUBJECTS",
    "EXPECTED_FINGERS",
    "EXPECTED_RELEASES",
    "EXPECTED_PER_RELEASE",
    "EXPECTED_PER_STAGE",
    "EXPECTED_JOBS",
    "EXPECTED_IMAGES_PER_RELEASE",
    "EXPECTED_PARTICIPATING_IMAGES",
]

#: The shape the supervisor's protocol implies: 50 subjects, ten anatomical
#: fingers, four stages, three releases. Asserted here rather than in the
#: planner, because the planner must stay true for any protocol and these
#: numbers are true only for this one.
EXPECTED_SUBJECTS = 50
EXPECTED_FINGERS = 10
EXPECTED_RELEASES = ("SD300A", "SD300B", "SD300C")
EXPECTED_PER_RELEASE = EXPECTED_SUBJECTS * EXPECTED_FINGERS * len(ProtocolStage)  # 2,000
EXPECTED_PER_STAGE = EXPECTED_SUBJECTS * EXPECTED_FINGERS * len(EXPECTED_RELEASES)  # 1,500
EXPECTED_JOBS = EXPECTED_PER_RELEASE * len(EXPECTED_RELEASES)  # 6,000

#: 500 plain plus 500 rolled per release. Every one of them takes part in at
#: least one comparison, so the participating set is the whole of it.
EXPECTED_IMAGES_PER_RELEASE = EXPECTED_SUBJECTS * EXPECTED_FINGERS * 2  # 1,000
EXPECTED_PARTICIPATING_IMAGES = EXPECTED_IMAGES_PER_RELEASE * len(EXPECTED_RELEASES)


@dataclass(frozen=True, slots=True)
class SD300Inputs:
    """Everything an experiment reads before it decides anything."""

    protocol: SD300Protocol
    cohort: Cohort
    images: Mapping[ImageId, ImageRecord]
    pairs: Mapping[PairId, ComparisonPair]
    pair_metadata: Mapping[str, str]
    image_manifest_hashes: Mapping[str, str]
    dataset_root: Path

    @property
    def pair_manifest_hash(self) -> str:
        return str(self.pair_metadata["pair_manifest_hash"])


def load_sd300_inputs(
    *,
    workspace: Path,
    dataset_root: Path | None,
    dataset_config: Path,
    protocol_config: Path,
    require_verified_checksums: bool = True,
    allow_creation: bool = False,
) -> SD300Inputs:
    """Build the manifests once, then read them for ever after.

    The first invocation hashes 113 GB to prove the delivery matches NIST's own
    digests, and writes an immutable manifest recording that it did. Every
    invocation after that reads the manifest: the evidence is the manifest, and
    re-hashing to produce the same answer would be a ritual rather than a check
    (docs/adr/0005).
    """
    protocol = SD300Protocol.from_config_file(protocol_config)
    spec = load_dataset_spec(dataset_config, root_override=dataset_root)
    provider = create_provider(spec)
    manifests = ManifestStore(Path(workspace))

    images: list[ImageRecord] = []
    subjects: list[Any] = []
    manifest_hashes: dict[str, str] = {}

    for release in protocol.releases:
        if not manifests.images_path(protocol.dataset_id, release).is_file():
            if not allow_creation:
                raise ResearchPreflightError(
                    f"the prepared image manifest for {release} is missing"
                )
            report = provider.validate(release)
            manifests.write_validation_report(
                report, dataset_id=protocol.dataset_id, release=release
            )
            if not report.is_clean:
                raise ResearchPreflightError(
                    f"{release}: dataset validation found blocking errors; a "
                    "research run cannot be built on it"
                )
            release_images = list(
                provider.scan(release, verify_checksums=require_verified_checksums)
            )
            manifests.write_images(
                release_images, dataset_id=protocol.dataset_id, release=release
            )
            manifests.write_subjects(
                summarise_subjects(release_images),
                dataset_id=protocol.dataset_id,
                release=release,
            )

        release_images = manifests.read_images(protocol.dataset_id, release)
        metadata = manifests.image_manifest_metadata(protocol.dataset_id, release)
        if metadata.get("validation_override_reason"):
            raise ResearchPreflightError(
                f"{release}: the image manifest was written under a validation "
                "override; a research run may not rest on overridden validation"
            )
        images += release_images
        subjects += manifests.read_subjects(protocol.dataset_id, release)
        manifest_hashes[release] = manifests.image_manifest_hash(
            protocol.dataset_id, release
        )

    cohort = protocol.build_cohort(subjects, manifest_hashes)
    pairs = protocol.build_pairs(cohort, images)

    if not manifests.cohort_path(protocol.protocol_id, cohort.cohort_id).is_file():
        if not allow_creation:
            raise ResearchPreflightError(
                f"the prepared cohort manifest {cohort.cohort_id} is missing"
            )
        manifests.write_cohort(cohort)
    if not manifests.pairs_path(protocol.protocol_id, cohort.cohort_id).is_file():
        if not allow_creation:
            raise ResearchPreflightError(
                f"the prepared pair manifest {cohort.cohort_id} is missing"
            )
        manifests.write_pairs(pairs, cohort=cohort)

    stored_cohort = manifests.read_cohort(protocol.protocol_id, cohort.cohort_id)
    if stored_cohort.subject_ids != cohort.subject_ids:
        raise ResearchPreflightError(
            f"the stored cohort {cohort.cohort_id} holds different subjects than "
            "the protocol now selects; a research run cannot straddle two cohorts"
        )
    stored_pairs = manifests.read_pairs(protocol.protocol_id, cohort.cohort_id)
    if {str(pair.pair_id) for pair in stored_pairs} != {
        str(pair.pair_id) for pair in pairs
    }:
        raise ResearchPreflightError(
            "the stored pair manifest does not hold the comparisons the protocol "
            "now generates"
        )

    pair_metadata = manifests.pair_manifest_metadata(
        protocol.protocol_id, cohort.cohort_id
    )
    return SD300Inputs(
        protocol=protocol,
        cohort=cohort,
        images={image.image_id: image for image in images},
        pairs={pair.pair_id: pair for pair in stored_pairs},
        pair_metadata=pair_metadata,
        image_manifest_hashes=manifest_hashes,
        dataset_root=spec.root,
    )


def participating_image_ids(
    pairs: Mapping[PairId, ComparisonPair],
) -> tuple[ImageId, ...]:
    """The unique images the pair manifest actually names, in ascending order.

    Derived from the pairs and never from a directory listing. Re-deriving the
    set from filenames would let a file that arrived after the manifest was
    frozen enter the experiment, and the ordering would then depend on how a
    filesystem happened to enumerate a directory (spec sections 5 and 45).
    """
    participating: set[ImageId] = set()
    for pair in pairs.values():
        participating.add(pair.left_image_id)
        participating.add(pair.right_image_id)
    return tuple(sorted(participating))


def preparation_source_bundle(inputs: SD300Inputs) -> PreparationSourceBundle:
    """Derive the external identities a prepared set is required to match.

    This is built from the authoritative dataset/protocol/cohort/pair inputs,
    never from a prepared-set manifest.  It therefore remains an independent
    anchor even if every prepared-set artefact is rehashed self-consistently.
    """
    cohort = inputs.cohort
    combined_manifest_hash = stable_hash(
        {
            "schema": "combined_image_manifest_hash_v1",
            "hashes": dict(sorted(inputs.image_manifest_hashes.items())),
        },
        length=64,
    )
    cohort_fingerprint = stable_hash(
        {
            "schema": "cohort_fingerprint_v1",
            "cohort_id": str(cohort.cohort_id),
            "protocol_id": cohort.protocol_id,
            "dataset_id": cohort.dataset_id,
            "role": cohort.role.value,
            "releases": list(cohort.releases),
            "subject_ids": [str(item) for item in cohort.subject_ids],
            "selection": {
                "seed": cohort.selection.seed,
                "size": cohort.selection.size,
                "candidate_ids": [
                    str(item) for item in cohort.selection.candidate_ids
                ],
                "criteria": dict(cohort.selection.criteria),
                "image_manifest_hashes": dict(
                    cohort.selection.image_manifest_hashes
                ),
            },
        },
        length=64,
    )
    return PreparationSourceBundle(
        dataset_id=inputs.protocol.dataset_id,
        image_manifest_hash=combined_manifest_hash,
        protocol_id=inputs.protocol.protocol_id,
        cohort_id=str(cohort.cohort_id),
        cohort_fingerprint=cohort_fingerprint,
        pair_manifest_hash=inputs.pair_manifest_hash,
        ordered_image_ids=participating_image_ids(inputs.pairs),
    )


def require_expected_shape(
    *,
    cohort: Cohort,
    pairs: Mapping[PairId, ComparisonPair],
    images: Mapping[ImageId, ImageRecord],
    expected_jobs: int = EXPECTED_JOBS,
    expected_subjects: int = EXPECTED_SUBJECTS,
    expected_participating_images: int | None = None,
) -> None:
    """Assert the dataset preflight before anything runs.

    Args:
        expected_participating_images: When given, the number of distinct images
            the pairs must name. The native run never had to state this; the
            canonical one does, because a set materialised for a different count
            is a different set.
    """
    if len(cohort.subject_ids) != expected_subjects:
        raise ResearchPreflightError(
            f"the cohort holds {len(cohort.subject_ids)} subjects, expected "
            f"{expected_subjects}"
        )
    if len(pairs) != expected_jobs:
        raise ResearchPreflightError(
            f"the protocol yields {len(pairs)} comparisons, expected {expected_jobs}"
        )

    participating = participating_image_ids(pairs)
    if (
        expected_participating_images is not None
        and len(participating) != expected_participating_images
    ):
        raise ResearchPreflightError(
            f"the pair manifest names {len(participating)} distinct images, expected "
            f"{expected_participating_images}"
        )

    unverified: list[str] = []
    blocked: list[str] = []
    absent: list[str] = []
    for image_id in participating:
        record = images.get(image_id)
        if record is None:
            absent.append(str(image_id))
            continue
        if not record.is_usable or record.blocking_issues:
            blocked.append(str(image_id))
        if record.checksum_status is not ChecksumStatus.VERIFIED:
            unverified.append(str(image_id))

    if absent:
        raise ResearchPreflightError(
            f"{len(absent)} participating image(s) are not in the image manifest"
        )
    if blocked:
        raise ResearchPreflightError(
            f"{len(blocked)} participating image(s) carry blocking validation "
            "issues and may not enter a research run"
        )
    if unverified:
        raise ResearchPreflightError(
            f"{len(unverified)} participating image(s) have no VERIFIED checksum "
            "evidence; rebuild the image manifests with verify_checksums=True"
        )

    for pair in pairs.values():
        expected = ppi_policy.effective_ppi(pair.release)
        for side, image_id in (
            ("left", pair.left_image_id),
            ("right", pair.right_image_id),
        ):
            actual = images[image_id].effective_ppi
            if actual != expected:
                raise ResearchPreflightError(
                    f"pair {pair.pair_id}'s {side} image is recorded at {actual} "
                    f"ppi; {pair.release} is used at {expected} (docs/adr/0004)"
                )
