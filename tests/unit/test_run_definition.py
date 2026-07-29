"""Run and job identity.

Two properties are being defended here, and they pull in opposite directions:

* anything that could change a score must change the id, or incomparable
  results end up in the same directory;
* nothing incidental may change the id, or a legitimate resume turns into a
  fresh run and the work is done twice.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from fpbench.core.enums import EnvironmentStatus, ScoreDirection
from fpbench.core.execution_models import EnvironmentReport, ExecutionProfile
from fpbench.core.identifiers import CohortId
from fpbench.execution.jobs import build_comparison_job
from fpbench.execution.run_definition import (
    DEFAULT_EXECUTION_PROFILE,
    create_run_definition,
)
from fakes import comparison_pair, fake_descriptor

PAIR_MANIFEST_HASH = "a" * 64
COHORT = CohortId("sd300_50_subjects_test_ab12cd34")


def environment(**overrides) -> EnvironmentReport:
    defaults = dict(
        status=EnvironmentStatus.READY,
        implementation_version="test-1",
        runtime={"python": "3.12.0"},
        dependencies={},
    )
    return EnvironmentReport(**{**defaults, **overrides})


def run(**overrides):
    defaults = dict(
        protocol_id="sd300_50_subjects",
        cohort_id=COHORT,
        pair_manifest_hash=PAIR_MANIFEST_HASH,
        algorithm=fake_descriptor("dummy_sha256"),
        environment=environment(),
        execution_profile=DEFAULT_EXECUTION_PROFILE,
    )
    return create_run_definition(**{**defaults, **overrides})


PAIR = comparison_pair(
    pair_id="sd300a_00001000_f01_mated",
    left_image_id="sd300a_00001000_plain_f01",
    right_image_id="sd300a_00001000_roll_f01",
)


# ------------------------------------------------------------------- run shape


def test_run_id_is_derived_from_the_fingerprint():
    definition = run()
    assert definition.run_id == f"run_{definition.run_fingerprint[:12]}"
    assert len(definition.run_fingerprint) == 64


def test_the_same_inputs_always_give_the_same_run_id():
    assert run().run_id == run().run_id


def test_fingerprints_are_stored_alongside_what_they_summarise():
    definition = run()
    assert len(definition.algorithm_fingerprint) == 64
    assert len(definition.environment_fingerprint) == 64
    assert len(definition.execution_profile_hash) == 64


def test_replicate_index_cannot_be_negative():
    with pytest.raises(ValueError, match="replicate_index"):
        run(replicate_index=-1)


# ------------------------------------------------- what must change the run id


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"pair_manifest_hash": "b" * 64}, id="pair_manifest"),
        pytest.param({"cohort_id": CohortId("other_cohort_1")}, id="cohort"),
        pytest.param({"protocol_id": "sd300_pilot"}, id="protocol"),
        pytest.param({"replicate_index": 1}, id="replicate_index"),
    ],
)
def test_load_bearing_inputs_change_the_run_id(change):
    assert run(**change).run_id != run().run_id


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"implementation_version": "test-2"}, id="algorithm_version"),
        pytest.param({"adapter_version": "2"}, id="adapter_version"),
        pytest.param(
            {"score_direction": ScoreDirection.LOWER_IS_BETTER}, id="score_direction"
        ),
    ],
)
def test_algorithm_changes_change_the_run_id(change):
    changed = replace(fake_descriptor("dummy_sha256"), **change)
    assert run(algorithm=changed).run_id != run().run_id


def test_environment_changes_change_the_run_id():
    changed = environment(dependencies={"nbis": "5.0.0"})
    assert run(environment=changed).run_id != run().run_id


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"deterministic_seed": 1}, id="seed"),
        pytest.param({"profile_id": "downsample_500_v1"}, id="profile_id"),
        pytest.param({"timeout_seconds": 30.0}, id="timeout"),
        pytest.param({"parameters": {"method": "lanczos"}}, id="parameters"),
    ],
)
def test_execution_profile_changes_change_the_run_id(change):
    changed = ExecutionProfile(
        **{
            "profile_id": DEFAULT_EXECUTION_PROFILE.profile_id,
            "preparer_id": DEFAULT_EXECUTION_PROFILE.preparer_id,
            "timeout_seconds": DEFAULT_EXECUTION_PROFILE.timeout_seconds,
            "deterministic_seed": DEFAULT_EXECUTION_PROFILE.deterministic_seed,
            **change,
        }
    )
    assert run(execution_profile=changed).run_id != run().run_id


# --------------------------------------------- what must NOT change the run id


def test_the_creation_timestamp_is_not_part_of_the_identity():
    early = run(created_utc="2020-01-01T00:00:00+00:00")
    late = run(created_utc="2030-12-31T23:59:59+00:00")
    assert early.run_id == late.run_id
    assert early.run_fingerprint == late.run_fingerprint


def test_mapping_insertion_order_is_not_part_of_the_identity():
    forward = environment(runtime={"python": "3.12.0", "platform": "Linux"})
    backward = environment(runtime={"platform": "Linux", "python": "3.12.0"})
    assert run(environment=forward).run_id == run(environment=backward).run_id


def test_the_display_name_is_not_part_of_the_identity():
    renamed = replace(fake_descriptor("dummy_sha256"), display_name="Renamed")
    assert run(algorithm=renamed).run_id == run().run_id


# ------------------------------------------------------------------------ jobs


def test_job_id_is_derived_from_the_job_fingerprint():
    job = build_comparison_job(run(), PAIR)
    assert job.job_id == f"job_{job.job_fingerprint[:16]}"
    assert len(job.job_fingerprint) == 64


def test_the_same_pair_in_the_same_run_gives_the_same_job_id():
    definition = run()
    assert (
        build_comparison_job(definition, PAIR).job_id
        == build_comparison_job(definition, PAIR).job_id
    )


def test_a_different_run_gives_a_different_job_id():
    assert (
        build_comparison_job(run(), PAIR).job_id
        != build_comparison_job(run(replicate_index=1), PAIR).job_id
    )


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"pair_id": "sd300a_00001000_f02_mated"}, id="pair_id"),
        pytest.param({"left_image_id": "sd300a_00001000_plain_f02"}, id="left"),
        pytest.param({"right_image_id": "sd300a_00001000_roll_f02"}, id="right"),
    ],
)
def test_changing_the_pair_changes_the_job_id(change):
    definition = run()
    other = replace(PAIR, **change)
    assert (
        build_comparison_job(definition, other).job_id
        != build_comparison_job(definition, PAIR).job_id
    )


def test_a_retry_is_a_different_job():
    definition = run()
    assert (
        build_comparison_job(definition, PAIR, attempt=2).job_id
        != build_comparison_job(definition, PAIR, attempt=1).job_id
    )


def test_job_id_reveals_nothing_about_the_pair():
    """docs/adr/0010: an adapter sees the job id and learns nothing from it."""
    job = build_comparison_job(run(), PAIR)
    for leak in ("mated", "plain", "roll", "00001000", "f01", "sd300a"):
        assert leak not in job.job_id


def test_attempt_is_one_based():
    with pytest.raises(ValueError, match="1-based"):
        build_comparison_job(run(), PAIR, attempt=0)
