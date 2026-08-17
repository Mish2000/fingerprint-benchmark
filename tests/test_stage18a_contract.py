"""The frozen Stage 18A protocol, tested without a vendor SDK and without OpenAFIS.

Stage 18A is execution-first, so most of what these tests defend is *the absence*
of a gate: no minimum coverage, no minimum score count, no threshold. What they
do defend hard is the handful of properties that decide whether the numbers are
honest — that a failure is never stored as a zero, that a zero is never stored as
a failure, that the probe side never swaps, and that the inputs are the same ones
the other four algorithms consumed.

Nothing here needs the SecuGen SDK, a built OpenAFIS or the dataset. The matcher
is replaced by a script that speaks the bridge's wire format, so the mapping from
bridge vocabulary to the requirement's closed status list is exercised end to end
on every platform.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fpbench.experiments import stage18a_identity as frozen
from fpbench.experiments import stage18a_reference_run as runner
from fpbench.experiments.stage18a_diagnostics import build_diagnostic_report
from fpbench.experiments.stage18a_inputs import ComparisonPair, PreparedImage, Stage18AInputs

pytestmark = pytest.mark.stage18a_contract


# --------------------------------------------------------------------------- world


def _pair(ordinal: int, name: str, left: str, right: str, stage: str = "plain_self", truth: str = "mated") -> ComparisonPair:
    return ComparisonPair(
        ordinal=ordinal,
        pair_id=name,
        release="SD300A",
        protocol_stage=stage,
        ground_truth=truth,
        left_image_id=left,
        right_image_id=right,
    )


def _image(ordinal: int, image_id: str) -> PreparedImage:
    return PreparedImage(
        ordinal=ordinal,
        image_id=image_id,
        path=Path(f"/nonexistent/{image_id}.png"),
        output_width=381,
        output_height=891,
        output_pixel_sha256="0" * 64,
        output_encoded_sha256="1" * 64,
    )


@pytest.fixture
def inputs() -> Stage18AInputs:
    images = tuple(_image(n, f"img_{n}") for n in range(4))
    pairs = (
        _pair(0, "both_ok", "img_0", "img_1"),
        _pair(1, "left_missing", "img_2", "img_1"),
        _pair(2, "right_missing", "img_0", "img_2"),
        _pair(3, "both_missing", "img_2", "img_3", stage="plain_roll_non_mated", truth="non_mated"),
    )
    return Stage18AInputs(
        preparation_set_id=frozen.REFERENCE_PREPARATION_SET_ID,
        preparation_set_fingerprint=frozen.REFERENCE_PREPARATION_SET_FINGERPRINT,
        pair_manifest_hash=frozen.REFERENCE_PAIR_MANIFEST_HASH,
        cohort_id=frozen.REFERENCE_COHORT_ID,
        protocol_id=frozen.REFERENCE_PROTOCOL_ID,
        dataset_id=frozen.REFERENCE_DATASET_ID,
        transform_profile_id="canonical_gray8_500ppi_lanczos3_v1",
        transform_profile_fingerprint="2" * 64,
        images=images,
        pairs=pairs,
    )


# A stand-in matcher that speaks the bridge's wire format. `score` is echoed from
# the left template's contents, so a test can ask for a specific number — including
# zero, which is the case that matters most.
FAKE_MATCHER = """
import sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    pair_id, left, right = line.split('\\t')
    with open(left) as handle:
        directive = handle.read().strip()
    if directive.startswith('BRIDGE:'):
        print('\\t'.join([pair_id, directive.split(':', 1)[1], '-1', '10', '10', '0']))
    else:
        print('\\t'.join([pair_id, 'OK', directive, '10', '10', '25']))
"""


@pytest.fixture
def config(tmp_path: Path) -> runner.Stage18AConfig:
    matcher = tmp_path / "fake_matcher.py"
    matcher.write_text(FAKE_MATCHER, encoding="utf-8")
    cfg = runner.Stage18AConfig(
        private_root=tmp_path / "private",
        extract_python=Path(sys.executable),
        extract_script=tmp_path / "unused_extract.py",
        secugen_sdk_dir=None,
        matcher_command=(sys.executable, str(matcher)),
        matcher_is_wsl=False,
        wsl_distro="",
    )
    cfg.ensure_layout()
    return cfg


def _write_templates(config: runner.Stage18AConfig, contents: dict[str, str | None]) -> None:
    """`None` means SecuGen failed on that image and produced no template."""
    index = config.templates_dir / "index.jsonl"
    with index.open("w", encoding="utf-8") as handle:
        for image_id, body in contents.items():
            if body is None:
                handle.write(
                    json.dumps(
                        {
                            "image_id": image_id,
                            "status": "EXTRACTION_FAILED",
                            "template_bytes": 0,
                            "extract_ms": 4.0,
                            "detail": "SGFPM_CreateTemplate=2",
                            "path": None,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                continue
            path = config.templates_dir / f"{image_id}.iso"
            path.write_text(body, encoding="utf-8")
            handle.write(
                json.dumps(
                    {
                        "image_id": image_id,
                        "status": "OK",
                        "template_bytes": len(body),
                        "extract_ms": 12.0,
                        "detail": "",
                        "path": str(path),
                    },
                    sort_keys=True,
                )
                + "\n"
            )


# ------------------------------------------------------------------ frozen identity


def test_the_stage_never_claims_algorithm_5():
    assert frozen.ALGORITHM_5_ESTABLISHED is False
    assert frozen.OPENS_COMMON_CALIBRATION is False
    assert frozen.PUBLICATION_ELIGIBLE is False
    assert frozen.PURPOSE == "PRIVATE_REFERENCE_ONLY"


def test_openafis_is_pinned_to_one_commit():
    assert frozen.OPENAFIS_REPOSITORY == "neilharan/openafis"
    assert frozen.OPENAFIS_COMMIT == "3ae1c757c6dafea977a33ef51380e37f1715e626"
    assert frozen.OPENAFIS_LICENSE == "BSD-2-Clause"
    assert len(frozen.OPENAFIS_COMMIT) == 40


def test_the_score_contract_has_no_transform_and_no_threshold():
    assert frozen.SCORE_NATIVE_TYPE == "uint8_t"
    assert frozen.SCORE_DIRECTION == "HIGHER_MORE_SIMILAR"
    assert frozen.SCORE_TRANSFORM == "NONE"
    assert frozen.SCORE_THRESHOLD == "NONE"
    assert frozen.ZERO_IS_A_VALID_SCORE is True


def test_left_is_the_probe_and_right_is_the_candidate():
    assert frozen.PAIR_ORIENTATION == {"left": "probe", "right": "candidate"}


def test_the_distorting_resize_is_frozen_rather_than_corrected():
    # Both of these are wrong on their face. The stage keeps them because it is a
    # reference for the author's route, not for a better one.
    assert (frozen.SENSOR_WIDTH, frozen.SENSOR_HEIGHT) == (300, 400)
    assert frozen.RESAMPLING_FILTER == "LANCZOS"
    assert frozen.ASPECT_RATIO_PRESERVED is False
    assert frozen.SECUGEN_FINGER_INFO["ImpressionType"] == "SG_IMPTYPE_LP"


def test_the_status_list_is_closed_and_matches_the_requirement():
    assert frozen.PAIR_OUTCOME_STATUSES == (
        "OK",
        "SECU_GEN_EXTRACTION_FAILED_LEFT",
        "SECU_GEN_EXTRACTION_FAILED_RIGHT",
        "SECU_GEN_EXTRACTION_FAILED_BOTH",
        "OPENAFIS_TEMPLATE_LOAD_FAILED",
        "OPENAFIS_MATCH_PROCESS_FAILED",
        "INFRASTRUCTURE_FAILURE",
    )


def test_the_inputs_are_the_ones_the_other_four_algorithms_ran_over():
    assert frozen.REFERENCE_PREPARATION_SET_ID == "prepset_be560e047991"
    assert frozen.REFERENCE_PAIR_MANIFEST_HASH == (
        "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
    )
    assert frozen.EXPECTED_PAIR_OUTCOMES == 6000
    assert frozen.EXPECTED_IMAGES == 3000


# ------------------------------------------------------------- the completion rule


def test_completion_is_arithmetic_and_nothing_else():
    complete = runner.MatchingSummary(6000, 6000, 0, {"OK": 1000, "SECU_GEN_EXTRACTION_FAILED_BOTH": 5000}, 1.0)
    # Five thousand failures and a thousand scores still completes the stage.
    assert complete.complete is True


def test_a_missing_row_is_the_only_way_to_fail_completion():
    assert runner.MatchingSummary(6000, 5999, 1, {}, 1.0).complete is False


def test_completion_requires_the_full_six_thousand():
    # A run over a subset is not a short Stage 18A; it is not Stage 18A.
    assert runner.MatchingSummary(60, 60, 0, {}, 1.0).complete is False


# --------------------------------------------------------- the failure/score split


def test_extraction_failure_maps_to_the_side_that_failed(inputs, config):
    _write_templates(config, {"img_0": "40", "img_1": "40", "img_2": None, "img_3": None})
    runner.run_matching_phase(inputs, config)
    by_id = {outcome.pair_id: outcome for outcome in runner.read_pair_outcomes(config)}

    assert by_id["left_missing"].status == "SECU_GEN_EXTRACTION_FAILED_LEFT"
    assert by_id["right_missing"].status == "SECU_GEN_EXTRACTION_FAILED_RIGHT"
    assert by_id["both_missing"].status == "SECU_GEN_EXTRACTION_FAILED_BOTH"
    assert by_id["both_ok"].status == "OK"


def test_a_failure_never_carries_a_score(inputs, config):
    _write_templates(config, {"img_0": "40", "img_1": "40", "img_2": None, "img_3": None})
    runner.run_matching_phase(inputs, config)

    for outcome in runner.read_pair_outcomes(config):
        if outcome.status != "OK":
            # Not zero. None. A zero here would be indistinguishable from a real
            # OpenAFIS zero, and the two mean opposite things.
            assert outcome.openafis_score is None, outcome.pair_id


def test_zero_is_a_score_and_not_a_failure(inputs, config):
    _write_templates(config, {"img_0": "0", "img_1": "0", "img_2": None, "img_3": None})
    runner.run_matching_phase(inputs, config)
    by_id = {outcome.pair_id: outcome for outcome in runner.read_pair_outcomes(config)}

    assert by_id["both_ok"].status == "OK"
    assert by_id["both_ok"].openafis_score == 0


def test_a_template_openafis_refuses_is_a_load_failure(inputs, config):
    _write_templates(config, {"img_0": "BRIDGE:LOAD_FAILED_LEFT", "img_1": "40", "img_2": None, "img_3": None})
    runner.run_matching_phase(inputs, config)
    by_id = {outcome.pair_id: outcome for outcome in runner.read_pair_outcomes(config)}

    assert by_id["both_ok"].status == "OPENAFIS_TEMPLATE_LOAD_FAILED"
    assert by_id["both_ok"].openafis_score is None


def test_a_matcher_exception_is_its_own_status(inputs, config):
    _write_templates(config, {"img_0": "BRIDGE:MATCH_EXCEPTION", "img_1": "40", "img_2": None, "img_3": None})
    runner.run_matching_phase(inputs, config)
    by_id = {outcome.pair_id: outcome for outcome in runner.read_pair_outcomes(config)}

    assert by_id["both_ok"].status == "OPENAFIS_MATCH_PROCESS_FAILED"


def test_an_unknown_bridge_word_is_never_silently_an_ok(inputs, config):
    _write_templates(config, {"img_0": "BRIDGE:SOMETHING_NEW", "img_1": "40", "img_2": None, "img_3": None})
    runner.run_matching_phase(inputs, config)
    by_id = {outcome.pair_id: outcome for outcome in runner.read_pair_outcomes(config)}

    assert by_id["both_ok"].status == "OPENAFIS_MATCH_PROCESS_FAILED"
    assert by_id["both_ok"].openafis_score is None


def test_every_pair_gets_a_row_even_when_the_matcher_dies(inputs, config, tmp_path):
    dead = tmp_path / "dead_matcher.py"
    dead.write_text("import sys; sys.exit(3)", encoding="utf-8")
    broken = runner.Stage18AConfig(
        private_root=config.private_root,
        extract_python=config.extract_python,
        extract_script=config.extract_script,
        secugen_sdk_dir=None,
        matcher_command=(sys.executable, str(dead)),
        matcher_is_wsl=False,
        wsl_distro="",
    )
    _write_templates(broken, {"img_0": "40", "img_1": "40", "img_2": None, "img_3": None})
    runner.run_matching_phase(inputs, broken)

    outcomes = runner.read_pair_outcomes(broken)
    assert len(outcomes) == len(inputs.pairs)
    by_id = {outcome.pair_id: outcome for outcome in outcomes}
    assert by_id["both_ok"].status == "INFRASTRUCTURE_FAILURE"
    assert by_id["both_ok"].openafis_score is None
    # The pairs that never needed the matcher still carry their real reason.
    assert by_id["both_missing"].status == "SECU_GEN_EXTRACTION_FAILED_BOTH"


def test_resume_does_not_duplicate_rows(inputs, config):
    _write_templates(config, {"img_0": "40", "img_1": "40", "img_2": None, "img_3": None})
    runner.run_matching_phase(inputs, config)
    again = runner.run_matching_phase(inputs, config)

    assert again.stored == len(inputs.pairs)
    ids = [outcome.pair_id for outcome in runner.read_pair_outcomes(config)]
    assert len(ids) == len(set(ids))


# ------------------------------------------------------------------- path handling


def test_windows_paths_are_translated_for_the_wsl_matcher(config):
    wsl = runner.Stage18AConfig(
        private_root=config.private_root,
        extract_python=config.extract_python,
        extract_script=config.extract_script,
        secugen_sdk_dir=None,
        matcher_command=("wsl.exe",),
        matcher_is_wsl=True,
        wsl_distro="NBIS-BUILD-V1",
    )
    translated = runner._to_matcher_path(Path(r"C:\templates\a.iso"), wsl)
    if sys.platform == "win32":
        assert translated == "/mnt/c/templates/a.iso"
    assert "\\" not in translated


def test_the_sdk_is_only_demanded_when_extraction_runs(config):
    # status, match and receipt all work with no vendor SDK on the machine.
    with pytest.raises(Exception):
        config.require_sdk()


# --------------------------------------------------------------------- diagnostics


def _keys(node: object) -> set[str]:
    """Every key anywhere in the document, however deeply nested."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key.lower())
            found |= _keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _keys(item)
    return found


def test_the_report_cannot_express_a_rate_or_a_threshold(inputs, config):
    _write_templates(config, {"img_0": "40", "img_1": "40", "img_2": None, "img_3": None})
    runner.run_matching_phase(inputs, config)
    report = build_diagnostic_report(runner.read_pair_outcomes(config), runner.read_template_index(config))
    document = report.describe()

    # The names appear once, in the list of what was deliberately excluded, and
    # never as a key carrying a value. Asserting on keys rather than on substrings
    # is the difference between "the report has no FAR" and "the report never says
    # the word", and only the first is the requirement.
    present = _keys(document)
    for forbidden in ("tar", "far", "fmr", "eer", "threshold", "best_threshold"):
        assert forbidden not in present, forbidden

    assert document["forbidden_statistics"] == list(frozen.DIAGNOSTICS_FORBIDDEN)
    assert frozen.DIAGNOSTICS_FORBIDDEN == ("TAR", "FAR", "FMR", "EER", "best threshold")


def test_the_report_counts_only_score_bearing_comparisons(inputs, config):
    _write_templates(config, {"img_0": "0", "img_1": "0", "img_2": None, "img_3": None})
    runner.run_matching_phase(inputs, config)
    report = build_diagnostic_report(runner.read_pair_outcomes(config), runner.read_template_index(config))

    assert report.overall.count == 4
    assert report.overall.scored == 1
    assert report.overall.zeros == 1
    assert report.extraction_coverage["templates_produced"] == 2
    assert report.extraction_coverage["extraction_failures"] == 2


def test_build_report_takes_no_threshold_parameter():
    import inspect

    parameters = inspect.signature(build_diagnostic_report).parameters
    assert "threshold" not in parameters
    assert "cutoff" not in parameters


# ------------------------------------------------------- what 18A may not decide


def test_stage_19_may_not_be_tuned_from_these_scores():
    assert frozen.FORBIDDEN_STAGE19_USES == (
        "which MINDTCT quality cutoff",
        "how many minutiae to keep",
        "which angle conversion correlates better",
        "which coordinate scaling produces more similar scores",
    )


def test_the_stage_declares_no_minimum_coverage_criterion():
    assert "minimum coverage criterion" in frozen.NOT_REQUIREMENTS
    assert not hasattr(frozen, "MINIMUM_EXTRACTION_COVERAGE")
    assert not hasattr(frozen, "MINIMUM_SCORE_COUNT")
    assert not hasattr(frozen, "MINIMUM_DISCRIMINATION")


def test_the_csv_fallback_forbids_every_content_change():
    assert frozen.FORBIDDEN_CSV_STEPS == (
        "filter",
        "sort for quality",
        "drop minutiae",
        "invent type",
        "change angles heuristically",
        "scale coordinates for better scores",
    )
