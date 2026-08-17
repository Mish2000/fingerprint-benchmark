"""The frozen Stage 19A protocol: MINDTCT -> OpenAFIS, settled from source.

Stage 19A had exactly one thing to invent — how a MINDTCT minutia becomes an
OpenAFIS minutia — and these tests defend that it stayed a format change. No
filtering, no scaling, no reordering, no quality cutoff, no angle heuristic, and
no rule that lets a template above OpenAFIS's ceiling through by dropping the
minutiae it likes least.

Needs no NBIS build, no OpenAFIS binary and no dataset.
"""

from __future__ import annotations

import inspect
import math

import pytest

from fpbench.adapters.nbis.xyt import NbisMinutia
from fpbench.adapters.openafis import adapter as stage19
from fpbench.adapters.openafis.failure_mapping import (
    STAGE19_STATUSES,
    infrastructure_failure,
    invalid_xyt_failure,
    mindtct_failure,
    openafis_match_failure,
    template_refused_failure,
)
from fpbench.adapters.openafis.translation import (
    ANGLE_CONVERSION,
    MINUTIA_TYPE_POLICY,
    MINUTIA_TYPE_RIDGE_BIFURCATION,
    MINUTIA_TYPE_RIDGE_ENDING,
    OPENAFIS_MAXIMUM_MINUTIAE,
    OPENAFIS_MINIMUM_MINUTIAE,
    PLACEHOLDER_MINUTIA_TYPE,
    TranslationRefused,
    translate_xyt_to_openafis_csv,
)
from fpbench.core.enums import FailureCode, ScoreDirection

pytestmark = pytest.mark.stage19a_contract


def minutiae(count: int, *, theta: int = 45, quality: int = 50) -> list[NbisMinutia]:
    return [NbisMinutia(x=10 + i, y=20 + 2 * i, theta=theta, quality=quality) for i in range(count)]


def body(text: str) -> list[str]:
    return text.strip().split("\n")[1:]


# ------------------------------------------------------------------ the header


def test_the_csv_header_is_the_real_raster_size():
    # OpenAFIS scales every coordinate by 256/width and 256/height. A header that
    # was anything but the true size would silently rescale the template.
    result = translate_xyt_to_openafis_csv(minutiae(5), width=381, height=891)
    assert result.text.split("\n")[0] == "381,891"


def test_a_degenerate_raster_is_refused_rather_than_defaulted():
    with pytest.raises(TranslationRefused) as raised:
        translate_xyt_to_openafis_csv(minutiae(5), width=0, height=891)
    assert raised.value.reason == "invalid_raster_dimensions"


# ------------------------------------------------------- coordinates and angles


def test_x_and_y_are_carried_over_exactly_and_never_scaled():
    source = minutiae(6)
    result = translate_xyt_to_openafis_csv(source, width=381, height=891)
    for original, line in zip(source, body(result.text)):
        _type, x, y, _angle = line.split(",")
        assert int(x) == original.x
        assert int(y) == original.y


def test_the_angle_conversion_is_degrees_to_radians_and_nothing_else():
    # NBIS xytreps.c: XYT without -m1 is origin bottom-left, degrees 0..360,
    # 0 east, increasing counter-clockwise. OpenAFIS TripletScalar.cpp relates a
    # minutia's angle to atan2(dy, dx) over the stored coordinates, which is the
    # same handedness. So there is no flip to apply.
    for theta in (0, 1, 45, 90, 179, 180, 270, 359):
        source = [NbisMinutia(x=1, y=2, theta=theta, quality=0), NbisMinutia(x=3, y=4, theta=theta, quality=0)]
        line = body(translate_xyt_to_openafis_csv(source, width=100, height=200).text)[0]
        angle = float(line.split(",")[3])
        assert angle == pytest.approx(theta * math.pi / 180.0, abs=1e-9)


def test_no_inversion_and_no_rotation_is_declared_and_true():
    assert ANGLE_CONVERSION == "radians = degrees * pi / 180; no inversion, no rotation"
    # 90 degrees must not come out as 270 (an inversion) or 0 (a rotation).
    source = [NbisMinutia(x=1, y=2, theta=90, quality=0), NbisMinutia(x=3, y=4, theta=90, quality=0)]
    angle = float(body(translate_xyt_to_openafis_csv(source, width=100, height=200).text)[0].split(",")[3])
    assert angle == pytest.approx(math.pi / 2, abs=1e-9)


# ----------------------------------------------------------- what is not done


def test_every_minutia_is_carried_over_in_mindtct_order():
    source = [
        NbisMinutia(x=99, y=1, theta=10, quality=5),
        NbisMinutia(x=1, y=99, theta=20, quality=95),
        NbisMinutia(x=50, y=50, theta=30, quality=50),
    ]
    lines = body(translate_xyt_to_openafis_csv(source, width=100, height=100).text)
    assert len(lines) == 3
    # Not sorted by quality, not sorted spatially, not deduplicated.
    assert [int(line.split(",")[1]) for line in lines] == [99, 1, 50]


def test_low_quality_minutiae_are_not_dropped():
    source = [NbisMinutia(x=i, y=i, theta=0, quality=0) for i in range(1, 6)]
    result = translate_xyt_to_openafis_csv(source, width=100, height=100)
    assert result.minutiae_count == 5
    assert len(body(result.text)) == 5


def test_quality_reaches_no_column_at_all():
    source = minutiae(4, quality=77)
    for line in body(translate_xyt_to_openafis_csv(source, width=100, height=100).text):
        assert len(line.split(",")) == 4  # type,x,y,angle — there is no fifth field
        assert "77" not in line.split(",")[0]


def test_duplicate_coordinates_survive():
    same = [NbisMinutia(x=5, y=5, theta=0, quality=1) for _ in range(4)]
    assert translate_xyt_to_openafis_csv(same, width=100, height=100).minutiae_count == 4


# ------------------------------------------------------------ the 2..128 bounds


def test_the_bounds_are_openafis_own():
    assert (OPENAFIS_MINIMUM_MINUTIAE, OPENAFIS_MAXIMUM_MINUTIAE) == (2, 128)


def test_too_few_minutiae_is_a_refusal():
    with pytest.raises(TranslationRefused) as raised:
        translate_xyt_to_openafis_csv(minutiae(1), width=100, height=100)
    assert raised.value.reason == "minutiae_below_upstream_minimum"


def test_too_many_minutiae_is_a_refusal_and_never_a_truncation():
    with pytest.raises(TranslationRefused) as raised:
        translate_xyt_to_openafis_csv(minutiae(129), width=100, height=100)
    assert raised.value.reason == "minutiae_above_upstream_maximum"


def test_exactly_at_the_bounds_is_accepted():
    assert translate_xyt_to_openafis_csv(minutiae(2), width=100, height=100).minutiae_count == 2
    assert translate_xyt_to_openafis_csv(minutiae(128), width=100, height=100).minutiae_count == 128


def test_an_accepted_template_always_carries_every_minutia_it_was_given():
    # The behavioural statement of "no top-N rule": for every count the
    # translator accepts, the output length equals the input length. A truncating
    # implementation would pass the refusal test above and fail this one.
    for count in (2, 3, 17, 64, 127, 128):
        source = minutiae(count)
        result = translate_xyt_to_openafis_csv(source, width=400, height=400)
        assert result.minutiae_count == count
        assert len(body(result.text)) == count


def test_quality_order_cannot_change_which_minutiae_survive():
    # Same coordinates, opposite quality orderings. If anything ranked by quality,
    # these two would not produce identical geometry.
    ascending = [NbisMinutia(x=i, y=i, theta=i % 360, quality=i) for i in range(1, 101)]
    descending = [NbisMinutia(x=i, y=i, theta=i % 360, quality=101 - i) for i in range(1, 101)]
    first = body(translate_xyt_to_openafis_csv(ascending, width=200, height=200).text)
    second = body(translate_xyt_to_openafis_csv(descending, width=200, height=200).text)
    assert first == second


# --------------------------------------------------------------- minutia type


def test_type_is_a_constant_placeholder():
    assert PLACEHOLDER_MINUTIA_TYPE == MINUTIA_TYPE_RIDGE_ENDING
    assert MINUTIA_TYPE_POLICY == "constant_placeholder_non_score_bearing"
    for line in body(translate_xyt_to_openafis_csv(minutiae(5), width=100, height=100).text):
        assert line.split(",")[0] == "1"


def test_the_type_column_is_the_only_thing_the_type_changes():
    source = minutiae(6)
    ending = translate_xyt_to_openafis_csv(
        source, width=100, height=100, minutia_type=MINUTIA_TYPE_RIDGE_ENDING
    ).text
    bifurcation = translate_xyt_to_openafis_csv(
        source, width=100, height=100, minutia_type=MINUTIA_TYPE_RIDGE_BIFURCATION
    ).text
    # Everything but the first column is identical, which is what makes the
    # end-to-end invariance check meaningful rather than trivially true.
    strip = lambda text: [line.split(",", 1)[1] for line in body(text)]  # noqa: E731
    assert strip(ending) == strip(bifurcation)
    assert body(ending) != body(bifurcation)


def test_type_zero_is_never_emitted():
    # OpenAFIS's CSV reader refuses type 0 outright ("invalid minutia type").
    for line in body(translate_xyt_to_openafis_csv(minutiae(4), width=100, height=100).text):
        assert line.split(",")[0] != "0"


# ------------------------------------------------------------ failure semantics


def test_the_status_vocabulary_is_section_17s_closed_list():
    assert STAGE19_STATUSES == (
        "OK",
        "MINDTCT_FAILED_LEFT",
        "MINDTCT_FAILED_RIGHT",
        "MINDTCT_FAILED_BOTH",
        "INVALID_XYT_LEFT",
        "INVALID_XYT_RIGHT",
        "OPENAFIS_TEMPLATE_FAILED_LEFT",
        "OPENAFIS_TEMPLATE_FAILED_RIGHT",
        "OPENAFIS_TEMPLATE_FAILED_BOTH",
        "OPENAFIS_MATCH_FAILED",
        "INFRASTRUCTURE_FAILURE",
    )


@pytest.mark.parametrize(
    "info, expected",
    [
        (mindtct_failure(side="left", exit_code=1), "MINDTCT_FAILED_LEFT"),
        (mindtct_failure(side="right", exit_code=1), "MINDTCT_FAILED_RIGHT"),
        (invalid_xyt_failure(side="left", kind="invalid_extractor_output"), "INVALID_XYT_LEFT"),
        (template_refused_failure(side="right", reason="minutiae_above_upstream_maximum"),
         "OPENAFIS_TEMPLATE_FAILED_RIGHT"),
        (template_refused_failure(side="both", reason="minutiae_above_upstream_maximum"),
         "OPENAFIS_TEMPLATE_FAILED_BOTH"),
        (openafis_match_failure(detail="exit_2"), "OPENAFIS_MATCH_FAILED"),
    ],
)
def test_every_failure_carries_its_section_17_word(info, expected):
    assert info.details["stage19_status"] == expected
    assert set(info.details) <= {"tool", "side", "exit_code", "kind", "reason", "detail", "stage19_status"}


def test_no_failure_helper_can_carry_a_path_or_a_pair():
    for info in (
        mindtct_failure(side="left", exit_code=1),
        invalid_xyt_failure(side="right", kind="k"),
        template_refused_failure(side="both", reason="r"),
        openafis_match_failure(detail="d"),
    ):
        blob = " ".join([info.message, *info.details.values()])
        for fragment in ("/", "\\", "sd300", "pair_"):
            assert fragment not in blob.lower(), fragment


def test_a_refused_template_is_an_extraction_failure_not_a_matching_one():
    # It is the algorithm declining, not the machine breaking. The distinction
    # decides whether the run is clean.
    info = template_refused_failure(side="left", reason="minutiae_above_upstream_maximum")
    assert info.code is FailureCode.TEMPLATE_EXTRACTION_FAILED


def test_a_matcher_that_answered_nothing_is_blocking():
    assert openafis_match_failure(detail="exit_3").code is FailureCode.MATCHING_FAILED


# ------------------------------------------------------------------- identity


def test_the_algorithm_names_the_whole_route():
    assert stage19.ALGORITHM_ID == "nbis_mindtct_openafis"
    assert stage19.ADAPTER_ID == "nbis_mindtct_openafis_subprocess"


def test_the_descriptor_is_raw_and_higher_is_better():
    metadata = stage19.PIPELINE_METADATA
    assert metadata["openafis_threshold"] == "none"
    assert metadata["openafis_score_transform"] == "none"
    assert metadata["probe_side"] == "left"
    assert metadata["template_cache"] == "disabled"


def test_the_extractor_is_declared_shared_with_algorithm_2():
    # The one thing about Algorithm 5 that must never be quietly omitted.
    assert stage19.PIPELINE_METADATA["shares_extractor_with"] == "nbis_mindtct_bozorth3"
    assert stage19.PIPELINE_METADATA["extractor_id"] == "mindtct"


def test_mindtct_runs_with_no_flags_that_would_change_the_route():
    assert stage19.PIPELINE_METADATA["mindtct_contrast_boost"] == "disabled"
    assert stage19.PIPELINE_METADATA["mindtct_m1"] == "disabled"


def test_nothing_was_chosen_from_the_secugen_reference():
    assert stage19.PIPELINE_METADATA["secugen_reference_used_for_parameter_selection"] == "false"
    assert stage19.RESULT_METADATA["secugen_reference_used_for_parameter_selection"] == "false"


def test_the_route_carries_no_resize_of_its_own():
    # Stage 18A's 300x400 belonged to the helper it was transcribed from and must
    # not have leaked into Algorithm 5. Asserted behaviourally: whatever raster
    # size goes in comes out in the header, unchanged, and the coordinates with
    # it. A route that resized would have to rewrite both.
    source = minutiae(5)
    for width, height in ((381, 891), (836, 728), (300, 400), (1024, 1024)):
        result = translate_xyt_to_openafis_csv(source, width=width, height=height)
        assert result.text.split("\n")[0] == f"{width},{height}"
        assert [int(line.split(",")[1]) for line in body(result.text)] == [m.x for m in source]

    assert stage19.PIPELINE_METADATA["input_mode"] == "direct_gray8_png_byte_copy"
    assert stage19.PIPELINE_METADATA["coordinate_scaling"] == "none"


def test_the_translator_has_no_parameter_that_could_filter():
    # There is nowhere to pass a cutoff, a limit or a ranking, so a future caller
    # cannot introduce one without a visible signature change.
    parameters = inspect.signature(translate_xyt_to_openafis_csv).parameters
    assert set(parameters) == {"minutiae", "width", "height", "minutia_type"}


# ------------------------------------------------------- the validator's split


class _Algorithm:
    algorithm_id = "nbis_mindtct_openafis"
    adapter_id = "nbis_mindtct_openafis_subprocess"


class _Run:
    run_id = "run_x"
    algorithm = _Algorithm()


class _Plan:
    plan_id = "plan_x"

    def __init__(self, job_ids):
        self.jobs = [type("P", (), {"job": type("J", (), {"job_id": j})()})() for j in job_ids]


class _Record:
    def __init__(self, status, score=None, failure=None, metadata=None):
        from fpbench.core.enums import ExecutionStatus

        self.status = ExecutionStatus.SUCCESS if status == "ok" else ExecutionStatus.FAILURE
        self.raw_score = score
        self.failure = failure
        self.metadata = metadata or {}
        self.algorithm_id = "nbis_mindtct_openafis"


class _Store:
    def __init__(self, records):
        self._records = records

    def read(self, run_id, job_id):
        if job_id not in self._records:
            raise FileNotFoundError(job_id)
        return self._records[job_id]


def _validate(records):
    from fpbench.experiments.stage19a_validation import validate_stage19a_result_set

    return validate_stage19a_result_set(
        run=_Run(),
        plan=_Plan(list(records)),
        pairs={},
        images={},
        result_store=_Store(records),
        runtime_reference=None,
    )


def test_a_refused_template_is_algorithmic_and_keeps_the_run_clean():
    # 4,000 rolled prints over OpenAFIS's ceiling must not make the run a defect.
    records = {
        f"job_{i}": _Record(
            "failed",
            failure=template_refused_failure(side="right", reason="minutiae_above_upstream_maximum"),
            metadata={"stage19_status": "OPENAFIS_TEMPLATE_FAILED_RIGHT"},
        )
        for i in range(50)
    }
    report = _validate(records)
    assert report.algorithmic_failures == 50
    assert report.blocking_failures == 0
    assert report.is_clean is True


def test_a_matcher_that_answered_nothing_makes_the_run_unclean():
    records = {"job_0": _Record("failed", failure=openafis_match_failure(detail="exit_2"))}
    report = _validate(records)
    assert report.blocking_failures == 1
    assert report.is_clean is False


def test_a_failure_carrying_a_score_is_an_issue():
    records = {
        "job_0": _Record("failed", score=0.0, failure=mindtct_failure(side="left", exit_code=1))
    }
    report = _validate(records)
    assert not report.is_clean
    assert any("carries a score" in issue.message for issue in report.issues)


def test_a_success_without_a_score_is_an_issue():
    records = {"job_0": _Record("ok", score=None)}
    report = _validate(records)
    assert not report.is_clean


def test_a_zero_score_is_a_perfectly_good_success():
    records = {"job_0": _Record("ok", score=0.0)}
    report = _validate(records)
    assert report.successful_results == 1
    assert report.is_clean is True


def test_a_missing_result_is_never_clean():
    from fpbench.experiments.stage19a_validation import validate_stage19a_result_set

    report = validate_stage19a_result_set(
        run=_Run(), plan=_Plan(["job_0"]), pairs={}, images={},
        result_store=_Store({}), runtime_reference=None,
    )
    assert report.is_clean is False
