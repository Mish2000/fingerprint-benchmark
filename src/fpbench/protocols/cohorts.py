"""Choosing which subjects take part.

The protocol calls for 50 subjects that are complete in every participating
release: all ten anatomical fingers present as plain impressions *and* as
rolled impressions, with simultaneous-capture slap images excluded.

The choice among eligible subjects is arbitrary but reproducible: candidates
are sorted, then sampled with a fixed seed. The full candidate pool is recorded
alongside the winners, so a later change to the eligibility rules cannot pass
unnoticed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, Mapping

from fpbench.core.enums import CohortRole, Impression
from fpbench.core.errors import InsufficientCohortError
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
    """

    size: int
    seed: int
    releases: tuple[str, ...]
    role: CohortRole = CohortRole.TEST
    require_all_ten_plain: bool = True
    require_all_ten_roll: bool = True
    require_common_across_releases: bool = True

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
) -> Cohort:
    """Draw a reproducible cohort of ``criteria.size`` eligible subjects.

    Raises:
        InsufficientCohortError: when the eligible pool is smaller than the
            requested size. Quietly returning a short cohort would change the
            denominator of every reported rate.
    """
    candidates = eligible_subjects(subjects, criteria)
    if len(candidates) < criteria.size:
        raise InsufficientCohortError(
            f"{protocol_id}: {len(candidates)} eligible subjects for releases "
            f"{list(criteria.releases)}, but {criteria.size} were requested"
        )

    rng = random.Random(criteria.seed)
    chosen = tuple(sorted(rng.sample(candidates, criteria.size)))

    selection = CohortSelection(
        seed=criteria.seed,
        size=criteria.size,
        candidate_ids=candidates,
        criteria=criteria.as_criteria_map(),
    )
    # The id changes whenever anything that could change the membership changes,
    # so two cohorts drawn under different rules can never collide on disk.
    fingerprint = stable_hash(
        {**criteria.as_criteria_map(), "seed": criteria.seed, "size": criteria.size},
        length=8,
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
