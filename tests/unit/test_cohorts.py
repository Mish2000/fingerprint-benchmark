from __future__ import annotations

import pytest

from fpbench.core.enums import CohortRole, FingerprintPosition
from fpbench.core.errors import InsufficientCohortError, ProtocolError
from fpbench.core.models import SubjectRecord
from fpbench.protocols.cohorts import CohortCriteria, eligible_subjects, select_cohort

ALL_TEN = tuple(FingerprintPosition)
MANIFEST_HASHES = {"SD300A": "a" * 64, "SD300B": "b" * 64}


def subject(subject_id: str, release: str, *, plain=ALL_TEN, roll=ALL_TEN):
    return SubjectRecord(
        subject_id=subject_id,
        dataset_id="sd300",
        release=release,
        image_count=len(plain) + len(roll),
        plain_positions=plain,
        roll_positions=roll,
        multi_finger_count=2,
    )


def population(count: int, releases=("SD300A", "SD300B")):
    return [
        subject(f"{1000 + n:08d}", release)
        for n in range(count)
        for release in releases
    ]


def criteria(**overrides) -> CohortCriteria:
    base = dict(size=3, seed=7, releases=("SD300A", "SD300B"))
    base.update(overrides)
    return CohortCriteria(**base)


def test_complete_subjects_are_eligible():
    assert len(eligible_subjects(population(6), criteria())) == 6


def test_a_missing_finger_disqualifies_the_subject_everywhere():
    subjects = population(4)
    subjects = [s for s in subjects if not (s.subject_id == "00001002" and s.release == "SD300B")]
    subjects.append(subject("00001002", "SD300B", roll=ALL_TEN[:9]))
    assert "00001002" not in eligible_subjects(subjects, criteria())


def test_a_subject_absent_from_one_release_is_not_eligible():
    subjects = [s for s in population(4) if s.release == "SD300A"]
    assert eligible_subjects(subjects, criteria()) == ()


def test_the_cross_release_requirement_can_be_relaxed():
    subjects = [s for s in population(4) if s.release == "SD300A"]
    relaxed = criteria(require_common_across_releases=False)
    assert len(eligible_subjects(subjects, relaxed)) == 4


def test_selection_is_reproducible_for_a_given_seed():
    subjects = population(20)
    first = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects, criteria=criteria(),
        image_manifest_hashes=MANIFEST_HASHES,
    )
    second = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects, criteria=criteria(),
        image_manifest_hashes=MANIFEST_HASHES,
    )
    assert first == second
    assert first.subject_ids == tuple(sorted(first.subject_ids))


def test_a_different_seed_gives_a_different_cohort_id():
    subjects = population(20)
    a = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects,
        criteria=criteria(seed=1), image_manifest_hashes=MANIFEST_HASHES,
    )
    b = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects,
        criteria=criteria(seed=2), image_manifest_hashes=MANIFEST_HASHES,
    )
    assert a.cohort_id != b.cohort_id


def test_the_full_candidate_pool_is_recorded():
    subjects = population(20)
    cohort = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects, criteria=criteria(),
        image_manifest_hashes=MANIFEST_HASHES,
    )
    assert cohort.selection.candidate_count == 20
    assert set(cohort.subject_ids) <= set(cohort.selection.candidate_ids)


def test_too_few_candidates_is_an_error_not_a_short_cohort():
    with pytest.raises(InsufficientCohortError):
        select_cohort(
            protocol_id="p",
            dataset_id="sd300",
            subjects=population(2),
            criteria=criteria(size=50),
            image_manifest_hashes=MANIFEST_HASHES,
        )


def test_the_role_is_carried_into_the_cohort():
    cohort = select_cohort(
        protocol_id="p",
        dataset_id="sd300",
        subjects=population(5),
        criteria=criteria(role=CohortRole.DEVELOPMENT),
        image_manifest_hashes=MANIFEST_HASHES,
    )
    assert cohort.role is CohortRole.DEVELOPMENT


def test_source_manifest_change_always_changes_the_cohort_id():
    subjects = population(20)
    first = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects,
        criteria=criteria(), image_manifest_hashes=MANIFEST_HASHES,
    )
    changed = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=subjects,
        criteria=criteria(),
        image_manifest_hashes={**MANIFEST_HASHES, "SD300B": "c" * 64},
    )
    assert changed.subject_ids == first.subject_ids
    assert changed.cohort_id != first.cohort_id


def test_candidate_pool_change_changes_the_cohort_id():
    first = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=population(20),
        criteria=criteria(), image_manifest_hashes=MANIFEST_HASHES,
    )
    changed = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=population(21),
        criteria=criteria(), image_manifest_hashes=MANIFEST_HASHES,
    )
    assert changed.cohort_id != first.cohort_id


def test_every_selected_release_requires_an_image_manifest_hash():
    with pytest.raises(ProtocolError, match="SD300B"):
        select_cohort(
            protocol_id="p", dataset_id="sd300", subjects=population(5),
            criteria=criteria(), image_manifest_hashes={"SD300A": "a" * 64},
        )


def test_image_manifest_hashes_must_be_full_sha256_values():
    with pytest.raises(ProtocolError, match="SD300B"):
        select_cohort(
            protocol_id="p", dataset_id="sd300", subjects=population(5),
            criteria=criteria(),
            image_manifest_hashes={"SD300A": "a" * 64, "SD300B": "short"},
        )


def test_selection_provenance_mappings_are_defensively_frozen():
    source = dict(MANIFEST_HASHES)
    cohort = select_cohort(
        protocol_id="p", dataset_id="sd300", subjects=population(5),
        criteria=criteria(), image_manifest_hashes=source,
    )
    source["SD300A"] = "f" * 64
    assert cohort.selection.image_manifest_hashes["SD300A"] == "a" * 64
    with pytest.raises(TypeError):
        cohort.selection.criteria["new"] = "value"
