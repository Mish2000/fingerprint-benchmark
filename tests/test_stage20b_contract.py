"""Stage 20B runs Stage 20A's route, and adds no decision of its own.

Everything here is pure Python. No MCC SDK, no NBIS build, no .NET, no dataset —
the point of these tests is that the *rules* hold, and a test that needed a
licence-restricted assembly to state a rule could never run where it matters.
"""

from __future__ import annotations

import inspect
import json
import math
import sys
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from fpbench.adapters.mcc import adapter as mcc_adapter
from fpbench.adapters.mcc import identity, interop, translation
from fpbench.adapters.mcc.config import MccSdkConfig
from fpbench.adapters.mcc.failure_mapping import STAGE20B_STATUSES, STATUS_KEY
from fpbench.adapters.nbis.adapter import PIPELINE_METADATA as NBIS_PIPELINE_METADATA
from fpbench.adapters.nbis.xyt import NbisMinutia
from fpbench.core.enums import ExecutionStatus, FailureCode, FailureStage, ScoreDirection
from fpbench.core.errors import ConfigurationError
from fpbench.experiments import stage20a_mcc_contract as stage20a
from fpbench.experiments import stage20b_identity as frozen
from fpbench.experiments import stage20b_gates as gates

pytestmark = pytest.mark.stage20b_contract


def _minutia(x: int, y: int, theta: int, quality: int = 50) -> NbisMinutia:
    return NbisMinutia(x=x, y=y, theta=theta, quality=quality)


# ------------------------------------------------------------------- identity


def test_the_algorithm_names_its_extractor_because_the_sdk_has_none() -> None:
    assert identity.ALGORITHM_ID == "nbis_mindtct_mcc_sdk_v2"
    assert identity.DISPLAY_NAME == "NBIS MINDTCT + MCC SDK v2.0"
    assert identity.ALGORITHM_ID != "mcc"
    assert identity.SHARES_EXTRACTOR_WITH == "nbis_mindtct_bozorth3"


def test_the_route_claims_nothing_of_bolognas_was_modified() -> None:
    assert identity.UPSTREAM_MODIFIED is False
    assert mcc_adapter.PIPELINE_METADATA["mcc_upstream_modified"] == "false"


def test_the_descriptor_is_the_frozen_identity() -> None:
    descriptor = _adapter().descriptor
    assert descriptor.algorithm_id == frozen.ALGORITHM_ID
    assert descriptor.adapter_id == frozen.ADAPTER_ID
    assert descriptor.display_name == frozen.DISPLAY_NAME
    assert descriptor.score_direction is ScoreDirection.HIGHER_IS_BETTER
    assert descriptor.deterministic is True


def test_this_route_shares_only_the_extractor_with_algorithm_two() -> None:
    """The claim that makes the pair interesting, checked rather than asserted."""
    mcc = mcc_adapter.PIPELINE_METADATA
    nbis = NBIS_PIPELINE_METADATA
    assert mcc["extractor_id"] == nbis["extractor_id"]
    assert mcc["extractor_version"] == nbis["extractor_version"]
    assert mcc["matcher_id"] != nbis["matcher_id"]
    assert mcc["family_id"] != nbis["family_id"]


# ---------------------------------------------------------------- translation


def test_the_adapter_translation_is_the_frozen_stage20a_translation() -> None:
    """Stage 20A's contract is pinned by a published marker and lives above the
    adapter layer, so the rule is restated rather than imported. These two must
    never be allowed to drift apart."""
    source = [
        _minutia(x=index % 380, y=1 + index % 890, theta=index % 360, quality=index % 101)
        for index in range(300)
    ]
    ours = translation.translate_xyt_to_mcc_input(source, width=381, height=891)
    theirs = stage20a.translate_xyt_to_mcc_input(source, width=381, height=891)

    assert (ours.image_width, ours.image_height) == (theirs.image_width, theirs.image_height)
    assert ours.image_resolution == theirs.image_resolution == 500
    assert [(m.x, m.y, m.direction) for m in ours.minutiae] == [
        (m.x, m.y, m.direction) for m in theirs.minutiae
    ]


def test_x_is_carried_and_y_is_the_upstream_subtraction() -> None:
    result = translation.translate_xyt_to_mcc_input(
        [_minutia(19, 1, 0), _minutia(35, 90, 0)], width=100, height=100
    )
    assert [(item.x, item.y) for item in result.minutiae] == [(19, 99), (35, 10)]


def test_direction_changes_units_and_nothing_else() -> None:
    source = [_minutia(1, 1, theta) for theta in (0, 1, 45, 90, 180, 270, 359)]
    result = translation.translate_xyt_to_mcc_input(source, width=10, height=10)
    for original, translated in zip(source, result.minutiae):
        assert translated.direction == original.theta * math.pi / 180.0


def test_every_minutia_is_retained_in_mindtct_order_with_no_cap() -> None:
    source = [
        _minutia(x=index % 200, y=1 + index % 198, theta=index % 360)
        for index in range(400)
    ]
    result = translation.translate_xyt_to_mcc_input(source, width=200, height=200)
    assert len(result.minutiae) == 400
    assert [item.x for item in result.minutiae] == [item.x for item in source]


def test_quality_and_type_have_nowhere_to_go_and_change_nothing() -> None:
    low = translation.translate_xyt_to_mcc_input(
        [_minutia(10, 20, 30, quality=0)], width=100, height=100
    )
    high = translation.translate_xyt_to_mcc_input(
        [_minutia(10, 20, 30, quality=100)], width=100, height=100
    )
    assert low == high
    assert set(translation.MccInputMinutia.__slots__) == {"x", "y", "direction"}


def test_the_payload_is_the_sdks_own_documented_text_format_twice() -> None:
    left = translation.translate_xyt_to_mcc_input(
        [_minutia(3, 4, 90)], width=50, height=60
    )
    right = translation.translate_xyt_to_mcc_input(
        [_minutia(5, 6, 180), _minutia(7, 8, 0)], width=70, height=80
    )
    lines = translation.render_bridge_payload(left, right).splitlines()
    assert lines[0] == identity.BRIDGE_PROTOCOL
    assert lines[1] == "LEFT 50 60 500 1"
    assert lines[2].split(" ")[:2] == ["3", "56"]
    assert lines[3] == "RIGHT 70 80 500 2"
    assert len(lines) == 1 + (1 + 1) + (1 + 2)


def test_the_payload_round_trips_every_direction_exactly() -> None:
    """A fixed number of decimals here would hand the matcher a different angle."""
    source = [_minutia(1, 1, theta) for theta in range(360)]
    side = translation.translate_xyt_to_mcc_input(source, width=10, height=10)
    rows = translation.render_bridge_payload(side, side).splitlines()[2 : 2 + 360]
    assert [float(row.split(" ")[2]) for row in rows] == [
        item.direction for item in side.minutiae
    ]


@pytest.mark.parametrize(
    "minutiae, width, height, reason",
    [
        ([_minutia(10, 10, 10)], 0, 100, "invalid_raster_dimensions"),
        ([_minutia(100, 10, 10)], 100, 100, "minutia_outside_mindtct_raster"),
        ([_minutia(10, 100, 10)], 100, 100, "minutia_outside_mindtct_raster"),
    ],
)
def test_an_unrepresentable_minutia_is_refused_and_never_clamped(
    minutiae, width, height, reason
) -> None:
    with pytest.raises(translation.MccTranslationRefused) as refusal:
        translation.translate_xyt_to_mcc_input(minutiae, width=width, height=height)
    assert refusal.value.reason == reason


def test_the_route_names_every_operation_it_refuses_to_perform() -> None:
    for operation in (
        "crop", "resize", "sorting", "deduplication", "quality cutoff",
        "enhancement", "rotation optimization",
    ):
        assert operation in identity.FORBIDDEN_ROUTE_OPERATIONS
    assert set(identity.FORBIDDEN_ROUTE_OPERATIONS) == set(
        stage20a.FORBIDDEN_ROUTE_OPERATIONS
    )


# ----------------------------------------------------------- the score contract


def test_the_score_contract_is_stage20as_and_carries_no_threshold() -> None:
    assert (identity.SCORE_MINIMUM, identity.SCORE_MAXIMUM) == (0.0, 1.0)
    metadata = mcc_adapter.PIPELINE_METADATA
    assert metadata["mcc_threshold"] == "none"
    assert metadata["mcc_score_transform"] == "none"
    assert metadata["mcc_score_native_type"] == "System.Double"


def test_no_threshold_calibration_or_decision_appears_anywhere_in_the_route() -> None:
    """The route computes a similarity. Everything downstream of that is somebody
    else's stage, and none of it may leak into this one."""
    for module in (mcc_adapter, translation, identity, interop):
        source = inspect.getsource(module).lower()
        for forbidden in ("calibrat", "def threshold", "tar(", "far(", "eer("):
            assert forbidden not in source, (module.__name__, forbidden)
    for key in mcc_adapter.RESULT_METADATA:
        assert key not in {"threshold", "decision", "is_match", "matched", "tar", "far", "eer"}
    assert mcc_adapter.RESULT_METADATA["mcc_threshold"] == "none"
    assert mcc_adapter.RESULT_METADATA["mcc_score_transform"] == "none"


def test_the_adapter_never_calls_a_parameter_setter() -> None:
    source = inspect.getsource(mcc_adapter)
    assert "SetEnrollParameters" not in source
    assert "SetMatchParameters" not in source
    assert mcc_adapter.PIPELINE_METADATA["mcc_parameter_setters_called"] == "false"
    assert mcc_adapter.PIPELINE_METADATA["mcc_parameters"] == "sdk_optimal_defaults"


def test_zero_is_a_similarity_and_is_never_turned_into_a_failure() -> None:
    adapter = _adapter()
    report = {
        "status": "OK", "score": "0", "template_left_us": "1.0",
        "template_right_us": "1.0", "match_us": "1.0",
        "left_minutiae": "40", "right_minutiae": "40", "detail": "",
    }
    assert _match_from_report(adapter, report) == 0.0


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1.5", "-0.5"])
def test_a_score_outside_the_contract_is_recorded_verbatim_and_never_clamped(
    value: str,
) -> None:
    adapter = _adapter()
    report = {
        "status": "MCC_INVALID_SCORE", "score": value, "template_left_us": "1.0",
        "template_right_us": "1.0", "match_us": "1.0",
        "left_minutiae": "40", "right_minutiae": "40", "detail": "",
    }
    with pytest.raises(mcc_adapter._StageFailure) as failure:
        _match_from_report(adapter, report)
    details = failure.value.info.details
    assert details[STATUS_KEY] == "MCC_INVALID_SCORE"
    assert details["observed_score"] == value
    assert details["clamped"] == "false"
    assert failure.value.info.code is FailureCode.NO_SCORE


def test_the_adapter_rejects_an_out_of_range_score_even_if_the_bridge_calls_it_ok() -> None:
    """Both sides refuse, and neither repairs. Belt and braces, on purpose."""
    adapter = _adapter()
    report = {
        "status": "OK", "score": "1.0000000000000002", "template_left_us": "1.0",
        "template_right_us": "1.0", "match_us": "1.0",
        "left_minutiae": "40", "right_minutiae": "40", "detail": "",
    }
    with pytest.raises(mcc_adapter._StageFailure) as failure:
        _match_from_report(adapter, report)
    assert failure.value.info.details[STATUS_KEY] == "MCC_INVALID_SCORE"


# --------------------------------------------------------------- failure map


def test_the_failure_vocabulary_is_section_twenty_exactly() -> None:
    assert set(STAGE20B_STATUSES) == {
        "OK",
        "MINDTCT_FAILED_LEFT", "MINDTCT_FAILED_RIGHT", "MINDTCT_FAILED_BOTH",
        "INVALID_XYT_LEFT", "INVALID_XYT_RIGHT", "INVALID_XYT_BOTH",
        "MCC_TEMPLATE_REFUSAL_LEFT", "MCC_TEMPLATE_REFUSAL_RIGHT",
        "MCC_TEMPLATE_REFUSAL_BOTH",
        "MCC_MATCH_REFUSAL",
        "MCC_INVALID_SCORE",
        "MCC_RUNTIME_FAILURE",
        "BRIDGE_FAILURE",
        "INFRASTRUCTURE_FAILURE",
    }


@pytest.mark.parametrize(
    "status, expected",
    [
        ("MCC_TEMPLATE_REFUSAL_LEFT", FailureCode.TEMPLATE_EXTRACTION_FAILED),
        ("MCC_TEMPLATE_REFUSAL_RIGHT", FailureCode.TEMPLATE_EXTRACTION_FAILED),
        ("MCC_TEMPLATE_REFUSAL_BOTH", FailureCode.TEMPLATE_EXTRACTION_FAILED),
        ("MCC_MATCH_REFUSAL", FailureCode.MATCHING_FAILED),
        ("MCC_RUNTIME_FAILURE", FailureCode.DEPENDENCY_MISSING),
        ("BRIDGE_FAILURE", FailureCode.INTERNAL_ERROR),
    ],
)
def test_each_bridge_status_maps_to_its_own_failure(status, expected) -> None:
    adapter = _adapter()
    report = {
        "status": status, "score": "", "template_left_us": "1.0",
        "template_right_us": "1.0", "match_us": "", "left_minutiae": "40",
        "right_minutiae": "40", "detail": "System.ArgumentException",
    }
    with pytest.raises(mcc_adapter._StageFailure) as failure:
        _match_from_report(adapter, report)
    assert failure.value.info.code is expected
    assert failure.value.info.details[STATUS_KEY] == status


def test_a_status_the_bridge_should_never_print_is_a_bridge_failure() -> None:
    adapter = _adapter()
    report = {
        "status": "MATCH", "score": "0.9", "template_left_us": "1.0",
        "template_right_us": "1.0", "match_us": "1.0", "left_minutiae": "40",
        "right_minutiae": "40", "detail": "",
    }
    with pytest.raises(mcc_adapter._StageFailure) as failure:
        _match_from_report(adapter, report)
    assert failure.value.info.details[STATUS_KEY] == "BRIDGE_FAILURE"


def test_an_exception_is_never_stored_as_a_score() -> None:
    """Neither direction: no failure becomes a zero, and no zero becomes a failure.

    Checked structurally, because it is the one rule that would be invisible in a
    result file if it were broken. Every path out of ``compare`` that carries a
    failure goes through ``RawMatchResult.failed``, and the single
    ``RawMatchResult.success`` call is reached only when no failure was recorded.
    """
    source = inspect.getsource(mcc_adapter.MccSdkAdapter.compare)
    assert source.count("RawMatchResult.success(") == 1
    assert source.count("RawMatchResult.failed(") == 1
    assert "if failure is not None:" in source
    assert "raw_score=0" not in source.replace("raw_score=0.0 is a success", "")
    assert "raw_score=float(score)" in source.replace(" ", "")

    # And no failure constructor anywhere in the route offers a score to put in.
    failure_module = inspect.getsource(mcc_adapter.invalid_score_failure)
    assert "clamp" in failure_module and '"clamped": "false"' in failure_module


# ------------------------------------------------------------------ self, cache


def test_self_gets_two_extractions_and_two_templates_and_no_shortcut() -> None:
    source = inspect.getsource(mcc_adapter.MccSdkAdapter.compare)
    assert "left is right" not in source
    assert "same_path" not in source
    assert source.count("self._extract(") == 2
    assert source.count("self._translate(") == 2
    assert mcc_adapter.PIPELINE_METADATA["template_cache"] == "disabled"
    assert mcc_adapter.PIPELINE_METADATA["template_persistence"] == "disabled"


def test_the_bridge_builds_a_template_per_side_unconditionally() -> None:
    bridge = (
        Path(__file__).resolve().parents[1]
        / "integrations"
        / "mcc-sdk-v2-bridge"
        / "Program.cs"
    ).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in bridge.splitlines() if not line.strip().startswith("//")
    )
    # Two constructions and one match, both counted outside the documentation
    # comments and outside the API-signature constants.
    assert code.count("MccSdk.CreateMccTemplate(\n") == 2
    assert code.count("MccSdk.MatchMccTemplates(leftTemplate, rightTemplate)") == 1
    assert "cache" not in code.lower().replace("template_cache", "")


def test_pair_orientation_is_fixed_and_never_averaged() -> None:
    source = inspect.getsource(mcc_adapter.MccSdkAdapter)
    assert "mean(" not in source
    assert "max(a" not in source
    assert mcc_adapter.PIPELINE_METADATA["probe_side"] == "left"


# ----------------------------------------------------------------- environment


def test_no_asset_is_discovered_and_every_path_must_be_absolute() -> None:
    for module in (mcc_adapter, interop):
        source = inspect.getsource(module)
        assert "shutil.which" not in source
        assert "glob(" not in source
        assert "rglob(" not in source
    settings = {
        name: str(path)
        for name, path in (
            ("mindtct_executable", _config().mindtct_executable),
            ("bozorth3_executable", _config().bozorth3_executable),
            ("build_manifest", _config().build_manifest),
            ("mcc_bridge", _config().mcc_bridge),
            ("mcc_bridge_manifest", _config().mcc_bridge_manifest),
            ("mcc_sdk_dll", _config().mcc_sdk_dll),
        )
    }
    MccSdkConfig.from_mapping(settings)
    with pytest.raises(ConfigurationError):
        MccSdkConfig.from_mapping({**settings, "mindtct_executable": "mindtct"})


def test_the_four_runtime_assets_are_the_ones_that_decide_a_score() -> None:
    config = _config()
    assert tuple(config.runtime_assets()) == (
        "nbis_mindtct_executable",
        "nbis_build_manifest",
        "mcc_match_bridge",
        "mcc_bridge_manifest",
        "mcc_sdk_dll",
    )


def test_the_pinned_sdk_assembly_is_the_one_stage20a_hashed() -> None:
    assert identity.MCC_SDK_DLL_SHA256 == (
        "7267ea9f2ea4c32bdeef30a49e648a516381941b531c59960517a87e5cd2eb01"
    )
    assert "494f31afeacaf3f4" in identity.MCC_SDK_ASSEMBLY_FULL_NAME


# ------------------------------------------------- binding to Stage 20A's evidence


def _stage20a(name: str) -> dict:
    directory = (
        Path(__file__).resolve().parents[1]
        / "evidence"
        / "stage20a-mcc-sdk-preflight"
    )
    return json.loads((directory / name).read_text(encoding="utf-8"))


def test_every_pinned_constant_came_from_the_published_stage20a_evidence() -> None:
    """The adapter restates Stage 20A rather than importing it, because it cannot
    import upwards. This is what stops the restatement from drifting."""
    artifact = _stage20a("artifact-identity.json")
    runtime = _stage20a("runtime-identity.json")
    route = _stage20a("input-route-contract.json")
    contract = _stage20a("score-contract.json")
    marker = _stage20a("stage-20a-finalization.json")

    sdk_dll = next(row for row in artifact["dlls"] if row["filename"] == "Sdk/MccSdk.dll")
    assert identity.MCC_SDK_DLL_SHA256 == sdk_dll["sha256"]
    assert identity.MCC_SDK_ASSEMBLY_FULL_NAME == runtime["assembly"]["full_name"]
    assert identity.MCC_SDK_VERSION == runtime["assembly"]["version"]

    assert identity.TEMPLATE_API == route["exact_mcc_input"]["api"]
    assert identity.MATCH_API == contract["exact_api"]
    assert identity.MCC_INPUT_RESOLUTION == route["exact_mcc_input"]["image_resolution"]
    assert identity.ALGORITHM_ID == marker["candidate"]
    assert identity.SHARES_EXTRACTOR_WITH == marker["shares_extractor_with"]
    assert identity.UPSTREAM_MODIFIED is (marker["upstream_modified"] is True)
    assert [identity.SCORE_MINIMUM, identity.SCORE_MAXIMUM] == marker["score_range"]


def test_the_sdk_defaults_are_the_ones_stage20a_read_off_the_assembly() -> None:
    configuration = _stage20a("input-route-contract.json")["configuration"]
    assert dict(identity.SDK_OPTIMAL_ENROLL_PARAMETERS) == configuration["enroll"]
    assert dict(identity.SDK_OPTIMAL_MATCH_PARAMETERS) == configuration["match"]
    assert configuration["parameter_setters_called"] is False
    assert configuration["selection"] == "SDK_OPTIMAL_DEFAULTS"


def test_gate_as_expected_scores_are_stage20as_recorded_smoke() -> None:
    smoke = _stage20a("runtime-smoke.json")["scores"]
    assert dict(identity.STAGE_20A_SMOKE_SCORES) == smoke


def test_a_changed_sdk_default_is_a_refusal_to_start() -> None:
    adapter = _adapter()
    good = _bridge_identity()
    assert adapter._bridge_disagreement(good) is None

    for key in ("default_enroll.R", "default_match.MinNP", "assembly_version"):
        broken = dict(good)
        broken[key] = "999"
        assert adapter._bridge_disagreement(broken) is not None


def test_dotnets_seventeen_digit_doubles_still_compare_equal() -> None:
    """The bridge prints 0.52359877559829882; the frozen table holds
    0.5235987755982988. The same IEEE-754 double, so this must not be a
    string comparison."""
    adapter = _adapter()
    report = dict(_bridge_identity())
    report["default_enroll.SigmaD"] = "0.52359877559829882"
    report["default_match.MuRho2"] = "0.78539816339744828"
    assert adapter._bridge_disagreement(report) is None


def test_runtime_drift_stops_a_research_comparison() -> None:
    from fpbench.core.errors import RuntimeDriftError

    adapter = mcc_adapter.MccSdkAdapter(_config(research_mode=True))
    with pytest.raises(RuntimeDriftError):
        adapter.check_runtime_integrity()


# --------------------------------------------------------------------- interop


def test_a_linux_workspace_path_becomes_the_windows_path_the_bridge_can_open(
    monkeypatch,
) -> None:
    monkeypatch.setattr(interop.sys, "platform", "linux")
    assert interop.windows_path(PurePosixPath("/mnt/c/Users/x/mcc-payload.txt")) == (
        r"C:\Users\x\mcc-payload.txt"
    )


def test_a_path_windows_cannot_see_is_refused_rather_than_guessed(monkeypatch) -> None:
    monkeypatch.setattr(interop.sys, "platform", "linux")
    for unreachable in ("/home/x/work/p.txt", "/mnt/share/p.txt", "/p.txt"):
        with pytest.raises(interop.InteropPathUnreachable):
            interop.windows_path(PurePosixPath(unreachable))


def test_on_windows_the_path_is_left_exactly_as_it_is(monkeypatch) -> None:
    monkeypatch.setattr(interop.sys, "platform", "win32")
    assert interop.windows_path(Path(r"C:\x\y.txt")) == r"C:\x\y.txt"


# ----------------------------------------------------------------------- gates


def test_gate_a_compares_exactly_and_declares_no_tolerance() -> None:
    """No epsilon, no rounding, no ``isclose``: two IEEE-754 doubles or nothing."""
    source = inspect.getsource(gates.run_gate_a)
    for approximation in ("abs(", "isclose", "round(", "pytest.approx", "1e-"):
        assert approximation not in source
    assert 'actual == expected' in source
    record = gates.run_gate_a.__doc__ or ""
    assert "bit-identical" in record


def test_gate_a_expects_stage20as_five_scores() -> None:
    assert identity.STAGE_20A_SMOKE_SCORES == {
        "self": 0.6463866269440767,
        "related_forward": 0.18989714373119645,
        "related_reverse": 0.18989714373119645,
        "unrelated_forward": 0.10158917843359545,
        "unrelated_reverse": 0.10158917843359545,
    }


def test_gate_a_does_not_translate_vendor_samples_a_second_time() -> None:
    """The official samples are already in MCC's coordinate system. Passing them
    through the XYT translator would apply the origin change twice."""
    sample = gates.SampleTemplate(
        width=100, height=200, resolution=500, minutiae=((10, 20, 1.25),)
    )
    payload = gates.render_sample_payload(sample, sample).splitlines()
    assert payload[1] == "LEFT 100 200 500 1"
    assert payload[2] == "10 20 1.25"


def test_gate_b_reads_no_score_at_all() -> None:
    source = inspect.getsource(gates.run_gate_b) + inspect.getsource(
        gates._extract_through_route
    )
    assert "compare(" not in source
    assert "raw_score" not in source
    assert "MatchMccTemplates" not in source


def test_the_gate_b_subset_is_frozen_and_re_derivable() -> None:
    """Twelve images, two per impression type per release, chosen by position in
    the published order and never by anything a run produced."""
    assert len(frozen.GATE_B_SUBSET) == 12
    assert len(set(frozen.GATE_B_SUBSET)) == 12
    for release in ("sd300a", "sd300b", "sd300c"):
        of_release = [i for i in frozen.GATE_B_SUBSET if i.startswith(release)]
        assert len(of_release) == 4
        assert sum(1 for i in of_release if "_plain_" in i) == 2
        assert sum(1 for i in of_release if "_roll_" in i) == 2
        # at most one image per subject, per the frozen rule
        subjects = [i.split("_")[1] for i in of_release if "_plain_" in i]
        assert len(set(subjects)) == 2


def test_the_gate_b_rule_still_produces_the_frozen_subset() -> None:
    """Re-derived from the preparation set itself where that set is available.

    Skipped rather than faked on a machine without the workspace: the point of
    the test is that the *published order* produces these twelve identifiers, and
    a stub order would prove nothing about it.
    """
    try:
        from fpbench.experiments.stage18a_inputs import load_stage18a_inputs

        inputs = load_stage18a_inputs()
    except Exception as unavailable:  # noqa: BLE001 - any absence is a skip
        pytest.skip(f"the prepared image set is not on this machine: {unavailable}")

    chosen: dict[tuple[str, str], list[str]] = {}
    seen: dict[tuple[str, str], set[str]] = {}
    for image in sorted(inputs.images, key=lambda entry: entry.ordinal):
        release, subject, impression = image.image_id.split("_")[:3]
        if impression not in {"plain", "roll"}:
            continue
        key = (release, impression)
        chosen.setdefault(key, [])
        seen.setdefault(key, set())
        if len(chosen[key]) < 2 and subject not in seen[key]:
            chosen[key].append(image.image_id)
            seen[key].add(subject)

    derived = [
        image_id
        for release in ("sd300a", "sd300b", "sd300c")
        for impression in ("plain", "roll")
        for image_id in chosen[(release, impression)]
    ]
    assert derived == list(frozen.GATE_B_SUBSET)


# ------------------------------------------------------------------- decisions


def test_the_preference_reason_is_frozen_before_the_run_and_is_not_accuracy() -> None:
    assert frozen.PREFERENCE_REASON == "OFFICIAL_UNMODIFIED_MATCHER_ROUTE"
    source = inspect.getsource(frozen)
    assert "accuracy" not in source.lower().replace(
        "selection_based_on_sd300_accuracy", ""
    )


def test_the_human_failure_review_starts_unanswered() -> None:
    """Section 33: with structured failures present, the fifth slot waits for a
    person rather than for an invented 90%/95% rule."""
    assert frozen.FAILURE_REVIEW is None or frozen.FAILURE_REVIEW in frozen.FAILURE_REVIEW_STATES


def test_the_run_is_bound_to_the_same_manifest_as_every_other_algorithm() -> None:
    assert frozen.EXPECTED_OUTCOMES == 6000
    assert frozen.REFERENCE_PREPARATION_SET_ID == "prepset_be560e047991"
    assert frozen.REFERENCE_PAIR_MANIFEST_HASH == (
        "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
    )
    assert frozen.NBIS_BUILD_ID == "658f9f54a8f2"


# ------------------------------------------------------------------- utilities


def _config(*, research_mode: bool = False) -> MccSdkConfig:
    root = Path("C:/x") if sys.platform == "win32" else Path("/x")
    return MccSdkConfig(
        mindtct_executable=root / "bin" / "mindtct",
        bozorth3_executable=root / "bin" / "bozorth3",
        build_manifest=root / "nbis-build-manifest.json",
        mcc_bridge=root / "bridge" / "FpbenchMccBridge.exe",
        mcc_bridge_manifest=root / "bridge" / "bridge-manifest.json",
        mcc_sdk_dll=root / "bridge" / "MccSdk.dll",
        research_mode=research_mode,
    )


def _adapter() -> mcc_adapter.MccSdkAdapter:
    return mcc_adapter.MccSdkAdapter(_config())


def _bridge_identity() -> dict[str, str]:
    report = {
        "bridge_protocol": identity.BRIDGE_PROTOCOL,
        "assembly_full_name": identity.MCC_SDK_ASSEMBLY_FULL_NAME,
        "assembly_version": identity.MCC_SDK_VERSION,
        "template_api": identity.TEMPLATE_API,
        "match_api": identity.MATCH_API,
        "variant": identity.MCC_VARIANT,
        "parameter_setters_called": "false",
        "score_native_type": "System.Double",
        "score_transform": "NONE",
        "threshold": "NONE",
        "template_cache": "disabled",
    }
    for prefix, parameters in identity.SDK_OPTIMAL_PARAMETERS.items():
        for name, value in parameters.items():
            if value is None:
                report[f"{prefix}.{name}"] = "null"
            elif value is True or value is False:
                report[f"{prefix}.{name}"] = "true" if value else "false"
            else:
                report[f"{prefix}.{name}"] = str(value)
    return report


def _match_from_report(adapter: mcc_adapter.MccSdkAdapter, report: dict[str, str]) -> float:
    """Drive ``_match``'s answer-handling with a bridge line and nothing else.

    The bridge is a Windows .NET process against a licence-restricted assembly,
    so it cannot run here. What *can* run here is every rule about what the
    adapter does with the line it gets back, which is what these tests are about.
    """
    line = "\t".join(report[field] for field in mcc_adapter.BRIDGE_OUTPUT_FIELDS)
    result = SimpleNamespace(
        stdout=line + "\r\n", stderr="", exit_code=0,
        launch_failed=False, timed_out=False, duration_ms=1.0,
    )
    timings: dict[str, float] = {}
    workspace = SimpleNamespace(working_directory=Path("."))

    def _fake_run(**_kwargs):
        return result

    original_run = adapter._run
    original_write = mcc_adapter.render_bridge_payload
    original_windows_path = mcc_adapter.windows_path
    try:
        adapter._run = _fake_run  # type: ignore[method-assign]
        mcc_adapter.render_bridge_payload = lambda left, right: ""
        mcc_adapter.windows_path = lambda path: str(path)
        workspace.work_path = lambda name: _Sink()  # type: ignore[attr-defined]
        return adapter._match(
            left=None, right=None, workspace=workspace,
            budget=mcc_adapter._Budget(60.0), timings=timings,
        )
    finally:
        adapter._run = original_run  # type: ignore[method-assign]
        mcc_adapter.render_bridge_payload = original_write
        mcc_adapter.windows_path = original_windows_path


class _Sink(Path):
    """A payload path that accepts a write and goes nowhere."""

    _flavour = getattr(Path(), "_flavour", None)

    def __new__(cls):
        return super().__new__(cls, "mcc-payload.txt")

    def write_text(self, *args, **kwargs) -> int:  # noqa: D102
        return 0
