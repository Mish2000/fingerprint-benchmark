"""Choosing which subjects take part.

The protocol calls for 50 subjects that are complete in every participating
release: all ten anatomical fingers present as plain impressions *and* as
rolled impressions, with simultaneous-capture slap images excluded.

The choice among eligible subjects is arbitrary but reproducible: candidates
are ranked by SHA-256(seed || subject_id). The full candidate pool, winners and
source image-manifest hashes are fingerprinted, so neither an eligibility
change nor changed source bytes can silently reuse a cohort id.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Mapping

from fpbench.core.enums import CohortRole, Impression
from fpbench.core.errors import InsufficientCohortError, ProtocolError
from fpbench.core.identifiers import CohortId, SubjectId, compose_id
from fpbench.core.models import Cohort, CohortSelection, SubjectRecord
from fpbench.core.serialization import stable_hash

__all__ = ["CohortCriteria", "eligible_subjects", "select_cohort"]


@dataclass(frozen=True, slots=True)
class CohortCriteria:
    """What makes a subject eligible, and how many are taken.

    ``require_common_across_releases`` is what makes the same 50 subjects
    comparable across SD300A/B/C: a subject that is complete in A but missing a
    finger in C is rejected everywhere, not silently used where it happens to
    work.

    The constructor refuses a criteria object that cannot describe a cohort,
    rather than leaving it to :func:`select_cohort` to notice. ``size=0`` and
    ``size=-1`` both used to survive the "is the pool big enough" check — every
    pool is at least as large as a negative number — and then ``[:size]``
    returned a short cohort or an empty one. A run over nobody would have
    reported success, and every rate derived from it would have had a
    denominator that came from nowhere (docs/adr/0140).
    """

    size: int
    seed: int
    releases: tuple[str, ...]
    role: CohortRole = CohortRole.TEST
    require_all_ten_plain: bool = True
    require_all_ten_roll: bool = True
    require_common_across_releases: bool = True

    def __post_init__(self) -> None:
        if type(self.size) is not int or self.size < 1:
            raise ProtocolError(
                f"cohort size must be a positive integer, got {self.size!r}"
            )
        if type(self.seed) is not int:
            raise ProtocolError(
                f"cohort seed must be an exact integer, got {self.seed!r}"
            )
        releases = tuple(self.releases)
        if not releases:
            raise ProtocolError("a cohort must name at least one release")
        if len(set(releases)) != len(releases):
            raise ProtocolError(f"a cohort names a release twice: {releases}")
        if not isinstance(self.role, CohortRole):
            raise ProtocolError("cohort role must be a CohortRole")
        for name in (
            "require_all_ten_plain",
            "require_all_ten_roll",
            "require_common_across_releases",
        ):
            if type(getattr(self, name)) is not bool:
                raise ProtocolError(f"{name} must be a bool")
        object.__setattr__(self, "releases", releases)

    def as_criteria_map(self) -> Mapping[str, str]:
        """Flat, hashable description recorded in the cohort's provenance."""
        return {
            "releases": ",".join(self.releases),
            "require_all_ten_plain": str(self.require_all_ten_plain).lower(),
            "require_all_ten_roll": str(self.require_all_ten_roll).lower(),
            "require_common_across_releases": str(
                self.require_common_across_releases
            ).lower(),
        }


def _is_complete(record: SubjectRecord, criteria: CohortCriteria) -> bool:
    if criteria.require_all_ten_plain and not record.has_all_ten(Impression.PLAIN):
        return False
    if criteria.require_all_ten_roll and not record.has_all_ten(Impression.ROLL):
        return False
    return True


def eligible_subjects(
    subjects: Iterable[SubjectRecord], criteria: CohortCriteria
) -> tuple[SubjectId, ...]:
    """Subjects satisfying the criteria in every required release, sorted.

    Only records for the requested releases are considered; a subject manifest
    covering extra releases is not an error.
    """
    required = set(criteria.releases)
    by_subject: dict[SubjectId, dict[str, SubjectRecord]] = {}
    for record in subjects:
        if record.release in required:
            by_subject.setdefault(record.subject_id, {})[record.release] = record

    needed = required if criteria.require_common_across_releases else set()
    candidates = [
        subject_id
        for subject_id, per_release in by_subject.items()
        if needed <= per_release.keys()
        and all(_is_complete(record, criteria) for record in per_release.values())
    ]
    return tuple(sorted(candidates))


def select_cohort(
    *,
    protocol_id: str,
    dataset_id: str,
    subjects: Iterable[SubjectRecord],
    criteria: CohortCriteria,
    image_manifest_hashes: Mapping[str, str],
) -> Cohort:
    """Draw a reproducible cohort of ``criteria.size`` eligible subjects.

    Raises:
        InsufficientCohortError: when the eligible pool is smaller than the
            requested size. Quietly returning a short cohort would change the
            denominator of every reported rate.
    """
    missing_hashes = set(criteria.releases) - set(image_manifest_hashes)
    if missing_hashes:
        raise ProtocolError(
            f"missing image manifest hash(es) for releases {sorted(missing_hashes)}"
        )
    source_hashes = {
        release: image_manifest_hashes[release].lower()
        for release in criteria.releases
    }
    invalid_hashes = [
        release
        for release, digest in source_hashes.items()
        if len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest.lower())
    ]
    if invalid_hashes:
        raise ProtocolError(
            f"invalid image manifest hash(es) for releases {invalid_hashes}"
        )

    candidates = eligible_subjects(subjects, criteria)
    if len(candidates) < criteria.size:
        raise InsufficientCohortError(
            f"{protocol_id}: {len(candidates)} eligible subjects for releases "
            f"{list(criteria.releases)}, but {criteria.size} were requested"
        )

    def rank(subject_id: SubjectId) -> tuple[bytes, str]:
        payload = f"{criteria.seed}\0{subject_id}".encode("utf-8")
        return hashlib.sha256(payload).digest(), str(subject_id)

    chosen = tuple(sorted(sorted(candidates, key=rank)[: criteria.size]))

    selection = CohortSelection(
        seed=criteria.seed,
        size=criteria.size,
        candidate_ids=candidates,
        criteria=criteria.as_criteria_map(),
        image_manifest_hashes=source_hashes,
    )
    # The id changes whenever anything that could change the membership changes,
    # so two cohorts drawn under different rules can never collide on disk.
    fingerprint = stable_hash(
        {
            "dataset_id": dataset_id,
            "protocol_id": protocol_id,
            "role": criteria.role,
            "criteria": criteria.as_criteria_map(),
            "seed": criteria.seed,
            "size": criteria.size,
            "candidate_ids": candidates,
            "selected_subject_ids": chosen,
            "image_manifest_hashes": source_hashes,
        },
        length=12,
    )
    return Cohort(
        cohort_id=CohortId(compose_id(protocol_id, criteria.role.value, fingerprint)),
        protocol_id=protocol_id,
        dataset_id=dataset_id,
        role=criteria.role,
        releases=criteria.releases,
        subject_ids=chosen,
        selection=selection,
    )
