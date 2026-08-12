"""The frozen Stage 11B protocol, checked without a licence.

Everything a public CI runner is allowed to know about VeriFinger: the identity,
the wire format, the failure classification, the runtime closure, the config
binding, the guards that keep vendor bytes and machine paths out of the
repository, and the result-set validator. No SDK is downloaded, no trial is
activated, no DLL is loaded and no biometric score exists anywhere in this file
(spec section 37).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.adapters.registry import create_adapter, registered_adapters
from fpbench.adapters.verifinger_java.bridge_models import (
    build_compare_request,
    parse_compare_response,
    parse_version_response,
)
from fpbench.adapters.verifinger_java.config import (
    RUNTIME_ASSET_ROLES,
    VeriFingerJavaConfig,
)
from fpbench.adapters.verifinger_java.failure_mapping import (
    ALGORITHMIC_FAILURE_CODES,
    BLOCKING_FAILURE_CODES,
    BRIDGE_FAILURE_MAP,
    map_bridge_failure,
    process_crash,
)
from fpbench.core.enums import EnvironmentStatus, ExecutionStatus, FailureCode
from fpbench.core.errors import ConfigurationError, RuntimeDriftError
from fpbench.core.execution_models import descriptor_fingerprint
from fpbench.core.verifinger_errors import (
    Stage11BBindingError,
    VeriFingerBridgeContractViolation,
    VeriFingerRuntimeClosureError,
)
from fpbench.experiments import stage11b_identity as frozen
from fpbench.experiments.stage11a_binding import require_stage11a_binding
from fpbench.adapters.verifinger_java import identity, runtime as runtime_closure
from fpbench.experiments import verifinger_policy as policy
from verifingerworld import (
    comparison_context,
    fake_adapter,
    fake_installation,
    failure_document,
    gray8_png,
    job_directories,
    prepared_image,
    success_document,
    version_document,
)

pytestmark = pytest.mark.stage11b_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------- identity


def test_the_production_identity_is_the_one_stage_11b_froze() -> None:
    assert identity.ALGORITHM_ID == "verifinger_1to1"
    assert identity.ADAPTER_ID == "verifinger_java_subprocess"
    assert identity.DISPLAY_NAME == "VeriFinger 2025.2 1:1 Verification"
    assert identity.IMPLEMENTATION_VERSION == "2025.2"
    assert identity.VENDOR == "Neurotechnology"
    assert identity.ALGORITHM_SLOT == "algorithm_4"


def test_the_pipeline_names_a_route_rather_than_a_matcher() -> None:
    metadata = identity.PIPELINE_METADATA
    assert metadata["family_id"] == "verifinger"
    assert metadata["pipeline_kind"] == "end_to_end_image_matcher"
    assert metadata["extractor_id"] == "verifinger_finger_extractor"
    assert metadata["matcher_id"] == "verifinger_finger_matcher"
    assert metadata["integration_mode"] == "subprocess_per_comparison"
    assert metadata["input_mode"] == "canonical_gray8_500ppi"
    # The contract's spelling, and the route's own, said in both places.
    assert metadata["probe_side"] == "left"
    assert metadata["probe_role"] == "left_as_reference"
    for key in ("template_cache", "template_persistence", "score_cache"):
        assert metadata[key] == "disabled"


def test_the_identity_carries_no_threshold_anywhere() -> None:
    """48 may appear as provenance and may never appear as an operating point."""
    profile = identity.algorithm_profile()
    assert profile["runtime"]["official_sample_matching_threshold"] == 48
    assert profile["runtime"]["decision_threshold_produced_by_fpbench"] is False
    assert profile["score"]["calibrated"] is False
    assert profile["score"]["normalized"] is False
    assert profile["score"]["clamped"] is False
    assert profile["score"]["far_computed_by_fpbench"] is False
    flattened = json.dumps(profile)
    for forbidden in ("decision_profile", "fmr_target", "operating_point"):
        assert forbidden not in flattened


def test_the_algorithm_profile_fingerprint_is_stable() -> None:
    assert identity.algorithm_profile_fingerprint() == (
        identity.algorithm_profile_fingerprint()
    )


def test_the_expected_defaults_are_the_ten_stage_11a_read() -> None:
    assert dict(identity.EXPECTED_RUNTIME_DEFAULTS) == {
        "Fingers.TemplateSize": "LARGE",
        "Fingers.ExtractionScenario": "0",
        "Fingers.FastExtraction": "false",
        "Fingers.QualityThreshold": "40",
        "Fingers.MinimalMinutiaCount": "10",
        "Fingers.DetectTips": "false",
        "Fingers.DetectLiveness": "false",
        "Fingers.LivenessConfidenceThreshold": "0",
        "Fingers.MaximalRotation": "180.0",
        "Matching.Scenario": "0",
    }


def test_the_java_bridge_expects_the_same_defaults_this_source_does() -> None:
    """The two tables are in two languages and may not drift apart.

    The bridge refuses a runtime whose defaults differ, and the adapter refuses
    one too. Both need the same ten values, and a copy in Java that nobody
    compares is a copy that will be wrong one day (spec section 8).
    """
    source = (
        REPOSITORY_ROOT
        / "integrations"
        / "verifinger-java"
        / "src"
        / "main"
        / "java"
        / "org"
        / "fpbench"
        / "verifingerbridge"
        / "VeriFingerBridge.java"
    ).read_text(encoding="utf-8")
    table = source.split("EXPECTED_DEFAULTS = {", 1)[1].split("};", 1)[0]
    parsed: dict[str, str] = {}
    for line in table.splitlines():
        stripped = line.strip().strip(",")
        if not stripped.startswith("{"):
            continue
        name, value = stripped.strip("{}").split(",", 1)
        parsed[name.strip().strip('"')] = value.strip().strip('"')
    assert parsed == dict(identity.EXPECTED_RUNTIME_DEFAULTS)

    assert f'MATCHING_SPEED = "{identity.MATCHING_SPEED}"' in source
    assert (
        f"OFFICIAL_SAMPLE_MATCHING_THRESHOLD = "
        f"{identity.OFFICIAL_SAMPLE_MATCHING_THRESHOLD}" in source
    )
    assert f"REQUIRED_PPI = {identity.REQUIRED_EFFECTIVE_PPI}" in source


def test_the_bridge_never_returns_a_decision() -> None:
    source = (
        REPOSITORY_ROOT
        / "integrations"
        / "verifinger-java"
        / "src"
        / "main"
        / "java"
        / "org"
        / "fpbench"
        / "verifingerbridge"
        / "VeriFingerBridge.java"
    ).read_text(encoding="utf-8")
    assert '"decision"' not in source
    assert '"match"' not in source
    assert 'response.put("matched"' not in source


# ------------------------------------------------------------------- registry


def test_the_adapter_is_an_ordinary_registry_entry() -> None:
    assert identity.ADAPTER_ID in registered_adapters()


def test_registering_it_needs_no_sdk_no_licence_and_no_jvm() -> None:
    adapter = create_adapter(identity.ADAPTER_ID, {})
    assert adapter.descriptor.algorithm_id == identity.ALGORITHM_ID
    assert descriptor_fingerprint(adapter.descriptor) == descriptor_fingerprint(
        adapter.descriptor
    )


def test_nothing_generic_branches_on_this_algorithm() -> None:
    """The registry is the whole selection mechanism (spec section 20)."""
    generic = [
        REPOSITORY_ROOT / "src" / "fpbench" / "execution",
        REPOSITORY_ROOT / "src" / "fpbench" / "experiments" / "algorithm_research.py",
        REPOSITORY_ROOT / "src" / "fpbench" / "experiments" / "research_integration.py",
    ]
    offenders: list[str] = []
    for location in generic:
        files = [location] if location.is_file() else sorted(location.glob("*.py"))
        for path in files:
            text = path.read_text(encoding="utf-8")
            if "verifinger" in text.lower():
                offenders.append(path.name)
    assert offenders == []


# --------------------------------------------------------------- the protocol


def test_a_request_carries_two_paths_and_two_resolutions_and_nothing_else() -> None:
    request = json.loads(
        build_compare_request(
            request_id="5b0000000000c001",
            left_path=Path("/tmp/left.png").resolve(),
            left_effective_ppi=500,
            right_path=Path("/tmp/right.png").resolve(),
            right_effective_ppi=500,
        )
    )
    assert set(request) == {
        "schema_version",
        "request_id",
        "left_image_path",
        "left_effective_ppi",
        "right_image_path",
        "right_effective_ppi",
    }
    for forbidden in identity.FORBIDDEN_INPUTS:
        assert forbidden not in request


@pytest.mark.parametrize("ppi", [499, 1000, 2000, 0])
def test_a_request_at_any_other_resolution_is_refused(ppi: int) -> None:
    with pytest.raises(VeriFingerBridgeContractViolation):
        build_compare_request(
            request_id="5b0000000000c002",
            left_path=Path("/tmp/left.png").resolve(),
            left_effective_ppi=ppi,
            right_path=Path("/tmp/right.png").resolve(),
            right_effective_ppi=500,
        )


def test_a_relative_path_is_refused() -> None:
    with pytest.raises(VeriFingerBridgeContractViolation):
        build_compare_request(
            request_id="5b0000000000c003",
            left_path=Path("left.png"),
            left_effective_ppi=500,
            right_path=Path("/tmp/right.png").resolve(),
            right_effective_ppi=500,
        )


def test_a_well_formed_success_parses() -> None:
    result = parse_compare_response(
        json.dumps(success_document("5b0000000000c004", score=1712)),
        expected_request_id="5b0000000000c004",
    )
    assert result.succeeded
    assert result.score == 1712
    assert result.extraction_count == 2
    assert result.engine_status == "OK"


def test_a_score_read_under_match_not_found_is_a_success() -> None:
    """The whole reason the vendor's 48 is not fpbench's threshold."""
    result = parse_compare_response(
        json.dumps(
            success_document("5b0000000000c005", score=2, engine_status="MATCH_NOT_FOUND")
        ),
        expected_request_id="5b0000000000c005",
    )
    assert result.succeeded and result.score == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"score": 2.5},
        {"score": "2"},
        {"score": True},
        {"extraction_count": 1},
        {"engine_status": "BAD_OBJECT"},
        {"score_direction": "LOWER_IS_BETTER"},
        {"native_score_type": "double"},
        {"bridge_protocol": "fpbench.verifinger.bridge.v2"},
        {"schema_version": "2"},
    ],
)
def test_an_almost_valid_success_is_refused(overrides) -> None:
    with pytest.raises(VeriFingerBridgeContractViolation):
        parse_compare_response(
            json.dumps(success_document("5b0000000000c006", **overrides)),
            expected_request_id="5b0000000000c006",
        )


@pytest.mark.parametrize("field", ["match", "matched", "decision", "threshold", "far"])
def test_a_response_carrying_a_decision_is_refused(field: str) -> None:
    with pytest.raises(VeriFingerBridgeContractViolation):
        parse_compare_response(
            json.dumps(success_document("5b0000000000c007", **{field: True})),
            expected_request_id="5b0000000000c007",
        )


def test_a_response_for_another_job_is_refused() -> None:
    with pytest.raises(VeriFingerBridgeContractViolation):
        parse_compare_response(
            json.dumps(success_document("5b0000000000c008")),
            expected_request_id="5b0000000000c009",
        )


def test_a_failure_may_not_carry_a_score() -> None:
    with pytest.raises(VeriFingerBridgeContractViolation):
        parse_compare_response(
            json.dumps(failure_document("5b000000000000a", score=0)),
            expected_request_id="5b000000000000a",
        )


def test_a_version_response_reports_the_engines_own_modules() -> None:
    version = parse_version_response(json.dumps(version_document()))
    assert version.licences_obtained is True
    assert set(version.loaded_modules) == {
        name.removesuffix(".dll") for name in runtime_closure.NATIVE_LIBRARY_NAMES
    }
    assert dict(version.delivered_runtime_defaults) == dict(
        identity.EXPECTED_RUNTIME_DEFAULTS
    )


# ------------------------------------------------------- failure classification


def test_every_bridge_code_maps_to_exactly_one_classification() -> None:
    for code, (failure_code, _stage) in BRIDGE_FAILURE_MAP.items():
        classified = (failure_code in ALGORITHMIC_FAILURE_CODES) + (
            failure_code in BLOCKING_FAILURE_CODES
        )
        assert classified == 1, f"{code} is classified {classified} times"


def test_the_algorithms_own_opinion_is_the_only_recordable_failure() -> None:
    assert ALGORITHMIC_FAILURE_CODES == frozenset(
        {FailureCode.TEMPLATE_EXTRACTION_FAILED}
    )


@pytest.mark.parametrize(
    "code",
    [
        "licence_not_obtained",
        "runtime_unavailable",
        "runtime_defaults_mismatch",
        "engine_error",
        "unclassified_engine_status",
        "bridge_failure",
        "unsupported_resolution",
        "input_unreadable",
        "image_decode_failed",
        "engine_timeout",
    ],
)
def test_infrastructure_failures_are_blocking(code: str) -> None:
    failure = map_bridge_failure(code=code, message="x")
    assert failure.code in BLOCKING_FAILURE_CODES
    assert failure.code not in ALGORITHMIC_FAILURE_CODES


def test_a_crashed_jvm_is_blocking() -> None:
    """One JVM is one comparison, so a crash is the machine, not the finger."""
    failure = process_crash(exit_code=134, stderr="SIGABRT")
    assert failure.code is FailureCode.PROCESS_CRASHED
    assert failure.code in BLOCKING_FAILURE_CODES


def test_an_unknown_bridge_code_is_a_contract_violation_not_a_guess() -> None:
    failure = map_bridge_failure(code="something_new", message="x")
    assert failure.code is FailureCode.INTERNAL_ERROR
    assert failure.details["kind"] == "bridge_contract_violation"


def test_no_failure_is_retryable() -> None:
    for code in BRIDGE_FAILURE_MAP:
        assert map_bridge_failure(code=code, message="x").retryable is False


# ------------------------------------------------------------ runtime closure


def test_the_closure_holds_seven_libraries_two_models_and_eight_jars() -> None:
    assert len(runtime_closure.NATIVE_LIBRARY_NAMES) == 7
    assert len(runtime_closure.MODEL_DATA_FILES) == 2
    assert len(runtime_closure.CLASSPATH_JARS) == 8
    assert len(runtime_closure.CLOSURE_PATHS) == 17


def test_the_two_dlls_stage_11a_left_unpinned_are_in_the_closure() -> None:
    """The last unpinned bytes on the route (spec section 16)."""
    assert "NMediaProc.dll" in runtime_closure.NATIVE_LIBRARY_NAMES
    assert "NDevices.dll" in runtime_closure.NATIVE_LIBRARY_NAMES


def test_the_committed_manifest_is_this_sources_closure() -> None:
    manifest = runtime_closure.read_runtime_manifest(
        REPOSITORY_ROOT / "configs" / "verifinger" / "verifinger_runtime_manifest_v1.json"
    )
    assert tuple(item.relative_path for item in manifest.components) == (
        runtime_closure.CLOSURE_PATHS
    )
    assert manifest.platform == "windows/x86_64"


def test_the_committed_manifest_agrees_with_stage_11a_where_they_overlap() -> None:
    """Eight of the seventeen were already pinned by Stage 11A.

    A digest this stage derived that disagreed with the one that stage published
    would mean one of the two is describing a different artifact — and this check
    needs no SDK, because both sides are committed JSON.
    """
    from fpbench.experiments.stage11a_verifinger_observations import (
        FINGER_DATA_FILES,
        JAVA_BINDING_JARS,
        WINDOWS_X64_NATIVE_LIBRARIES,
    )

    manifest = runtime_closure.read_runtime_manifest(
        REPOSITORY_ROOT / "configs" / "verifinger" / "verifinger_runtime_manifest_v1.json"
    )
    by_path = manifest.by_path
    overlap = 0
    for item in (*WINDOWS_X64_NATIVE_LIBRARIES, *FINGER_DATA_FILES, *JAVA_BINDING_JARS):
        relative = item.relative_path.split("/", 1)[1]
        component = by_path.get(relative)
        assert component is not None, f"{relative} is not in the Stage 11B closure"
        assert component.sha256 == item.sha256
        assert component.size_bytes == item.size_bytes
        overlap += 1
    assert overlap == 10


def test_a_manifest_missing_a_component_is_refused(tmp_path: Path) -> None:
    installation, manifest = fake_installation(tmp_path)
    document = manifest.as_document()
    document["components"] = document["components"][:-1]
    path = tmp_path / "short.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(VeriFingerRuntimeClosureError):
        runtime_closure.read_runtime_manifest(path)


def test_a_changed_component_is_caught_by_the_full_pass(tmp_path: Path) -> None:
    installation, manifest = fake_installation(tmp_path)
    runtime_closure.verify_installation(installation, manifest)
    target = installation / Path(runtime_closure.CLOSURE_PATHS[0])
    target.write_bytes(b"replaced\n")
    with pytest.raises(VeriFingerRuntimeClosureError):
        runtime_closure.verify_installation(installation, manifest)


def test_a_replaced_component_is_caught_by_the_cheap_guard(tmp_path: Path) -> None:
    installation, manifest = fake_installation(tmp_path)
    snapshot = runtime_closure.snapshot_runtime_identity(installation, manifest)
    runtime_closure.require_runtime_unchanged(installation, snapshot)
    target = installation / Path(runtime_closure.CLOSURE_PATHS[-1])
    target.write_bytes(b"a different length entirely\n")
    with pytest.raises(RuntimeDriftError):
        runtime_closure.require_runtime_unchanged(installation, snapshot)


def test_a_missing_component_is_drift_not_a_comparison_failure(tmp_path: Path) -> None:
    installation, manifest = fake_installation(tmp_path)
    snapshot = runtime_closure.snapshot_runtime_identity(installation, manifest)
    (installation / Path(runtime_closure.CLOSURE_PATHS[3])).unlink()
    with pytest.raises(RuntimeDriftError):
        runtime_closure.require_runtime_unchanged(installation, snapshot)


def test_the_classpath_is_ordered_and_absolute(tmp_path: Path) -> None:
    installation, _ = fake_installation(tmp_path)
    entries = runtime_closure.classpath_entries(installation)
    assert [item.name for item in entries] == [
        Path(relative).name for relative in runtime_closure.CLASSPATH_JARS
    ]
    assert all(item.is_absolute() for item in entries)


# ------------------------------------------------------------- the adapter


def test_a_ready_environment_names_the_runtime_and_no_path(tmp_path: Path) -> None:
    adapter = fake_adapter(tmp_path)
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.READY
    assert report.implementation_version == identity.IMPLEMENTATION_VERSION
    assert report.dependencies["verifinger.runtime_components"] == "17"
    rendered = json.dumps(dict(report.dependencies)) + json.dumps(dict(report.runtime))
    assert str(tmp_path) not in rendered
    assert "C:\\Users" not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        {"licences_obtained": False},
        {"runtime_started": False},
        {"bridge_protocol": "fpbench.verifinger.bridge.v9"},
        {"required_ppi": 1000},
        {
            "delivered_runtime_defaults": {
                **dict(identity.EXPECTED_RUNTIME_DEFAULTS),
                "Fingers.QualityThreshold": "60",
            }
        },
        {
            "loaded_modules": [
                {"name": "NCore", "version": "2025.2.0.0", "file_name": "NCore.dll"}
            ]
        },
    ],
)
def test_a_runtime_that_is_not_the_qualified_one_is_unavailable(
    tmp_path: Path, payload
) -> None:
    adapter = fake_adapter(tmp_path, version_payload=version_document(**payload))
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert report.message


def test_a_drifted_default_is_reported_never_corrected(tmp_path: Path) -> None:
    drifted = dict(identity.EXPECTED_RUNTIME_DEFAULTS)
    drifted["Fingers.MinimalMinutiaCount"] = "6"
    adapter = fake_adapter(
        tmp_path, version_payload=version_document(delivered_runtime_defaults=drifted)
    )
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE
    assert "delivered runtime defaults" in report.message


def test_a_missing_installation_is_unavailable_not_an_exception(tmp_path: Path) -> None:
    adapter = fake_adapter(tmp_path)
    adapter.config  # the configuration is valid; the tree is not
    (tmp_path / "installation").rename(tmp_path / "moved")
    report = adapter.validate_environment()
    assert report.status is EnvironmentStatus.UNAVAILABLE


def test_a_success_stores_an_integer_and_the_route_it_came_from(tmp_path: Path) -> None:
    adapter = fake_adapter(
        tmp_path,
        responder=lambda request_id, left, right: success_document(request_id, score=451),
    )
    assert adapter.validate_environment().status is EnvironmentStatus.READY
    working, artifacts = job_directories(tmp_path / "job")
    left = prepared_image(tmp_path / "inputs" / "l.png", gray8_png(1), image_id="img_l")
    right = prepared_image(tmp_path / "inputs" / "r.png", gray8_png(2), image_id="img_r")
    result = adapter.compare(left, right, comparison_context(working, artifacts))
    assert result.status is ExecutionStatus.SUCCESS
    assert result.raw_score == 451.0
    assert float(result.raw_score).is_integer()
    metadata = dict(result.metadata)
    assert metadata["verifinger.algorithm_id"] == identity.ALGORITHM_ID
    assert metadata["verifinger.extraction_count"] == "2"
    assert metadata["verifinger.probe_side"] == "left"
    assert metadata["verifinger.matching_speed"] == "LOW"
    assert metadata["verifinger.score_transformation_by_fpbench"] == "none"


def test_a_result_carries_no_answer_and_no_path(tmp_path: Path) -> None:
    adapter = fake_adapter(tmp_path)
    adapter.validate_environment()
    working, artifacts = job_directories(tmp_path / "job")
    left = prepared_image(tmp_path / "inputs" / "l.png", gray8_png(1), image_id="img_l")
    right = prepared_image(tmp_path / "inputs" / "r.png", gray8_png(2), image_id="img_r")
    result = adapter.compare(left, right, comparison_context(working, artifacts))
    rendered = json.dumps(dict(result.metadata))
    for forbidden in ("threshold", "decision", "is_match", "ground_truth", "pair_id"):
        assert f'"{forbidden}"' not in rendered
        assert f'"verifinger.{forbidden}"' not in rendered
    assert str(tmp_path) not in rendered


def test_a_biometric_failure_is_recorded_and_carries_no_score(tmp_path: Path) -> None:
    adapter = fake_adapter(
        tmp_path,
        responder=lambda request_id, left, right: failure_document(request_id),
    )
    adapter.validate_environment()
    working, artifacts = job_directories(tmp_path / "job")
    left = prepared_image(tmp_path / "inputs" / "l.png", gray8_png(1), image_id="img_l")
    right = prepared_image(tmp_path / "inputs" / "r.png", gray8_png(2), image_id="img_r")
    result = adapter.compare(left, right, comparison_context(working, artifacts))
    assert result.status is ExecutionStatus.FAILURE
    assert result.raw_score is None
    assert result.failure.code is FailureCode.TEMPLATE_EXTRACTION_FAILED
    assert result.failure.details["engine_status"] == "BAD_OBJECT"


def test_a_failure_is_never_a_score_of_zero(tmp_path: Path) -> None:
    adapter = fake_adapter(
        tmp_path,
        responder=lambda request_id, left, right: failure_document(
            request_id, code="licence_not_obtained"
        ),
    )
    adapter.validate_environment()
    working, artifacts = job_directories(tmp_path / "job")
    left = prepared_image(tmp_path / "inputs" / "l.png", gray8_png(1), image_id="img_l")
    right = prepared_image(tmp_path / "inputs" / "r.png", gray8_png(2), image_id="img_r")
    result = adapter.compare(left, right, comparison_context(working, artifacts))
    assert result.raw_score is None


def test_an_image_at_the_wrong_resolution_is_refused_not_resampled(
    tmp_path: Path,
) -> None:
    adapter = fake_adapter(tmp_path)
    adapter.validate_environment()
    working, artifacts = job_directories(tmp_path / "job")
    left = prepared_image(
        tmp_path / "inputs" / "l.png", gray8_png(1), image_id="img_l", effective_ppi=1000
    )
    right = prepared_image(tmp_path / "inputs" / "r.png", gray8_png(2), image_id="img_r")
    result = adapter.compare(left, right, comparison_context(working, artifacts))
    assert result.status is ExecutionStatus.FAILURE
    assert result.failure.code is FailureCode.INTERNAL_ERROR


def test_left_and_right_reach_the_bridge_in_that_order(tmp_path: Path) -> None:
    adapter = fake_adapter(tmp_path)
    adapter.validate_environment()
    working, artifacts = job_directories(tmp_path / "job")
    left = prepared_image(tmp_path / "inputs" / "aaa.png", gray8_png(1), image_id="img_l")
    right = prepared_image(tmp_path / "inputs" / "zzz.png", gray8_png(2), image_id="img_r")
    adapter.compare(right, left, comparison_context(working, artifacts))
    request = adapter._client.calls[-1]
    # Reversed on the way in, reversed on the wire. No sorting, no normalising.
    assert request["left_image_path"].endswith("zzz.png")
    assert request["right_image_path"].endswith("aaa.png")


def test_a_comparison_after_the_runtime_moved_raises_rather_than_records(
    tmp_path: Path,
) -> None:
    adapter = fake_adapter(tmp_path)
    adapter.validate_environment()
    working, artifacts = job_directories(tmp_path / "job")
    left = prepared_image(tmp_path / "inputs" / "l.png", gray8_png(1), image_id="img_l")
    right = prepared_image(tmp_path / "inputs" / "r.png", gray8_png(2), image_id="img_r")
    target = Path(adapter.config.installation) / Path(runtime_closure.CLOSURE_PATHS[2])
    target.write_bytes(b"a completely different component\n")
    with pytest.raises(RuntimeDriftError):
        adapter.compare(left, right, comparison_context(working, artifacts))


# ----------------------------------------------------------------- the config


def test_a_research_adapter_must_be_pinned_completely(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        VeriFingerJavaConfig(
            bridge_jar=tmp_path / "b.jar",
            research_mode=True,
            runtime_bundle_id="bundle_x",
        )


def test_the_sdk_version_is_not_a_configuration_option() -> None:
    with pytest.raises(ConfigurationError):
        VeriFingerJavaConfig(expected_implementation_version="2025.1")


def test_unknown_configuration_keys_are_refused() -> None:
    with pytest.raises(ConfigurationError):
        VeriFingerJavaConfig.from_mapping({"threshold": 48})


def test_the_three_pinned_roles_are_all_ours() -> None:
    assert RUNTIME_ASSET_ROLES == (
        "verifinger_bridge_jar",
        "verifinger_runtime_manifest",
        "verifinger_runtime_policy",
    )


# ----------------------------------------------------------------- the policy


def test_the_committed_policy_describes_what_this_source_does() -> None:
    loaded = policy.read_runtime_policy(REPOSITORY_ROOT / policy.DEFAULT_POLICY_PATH)
    policy.require_policy_matches_source(loaded)


def test_a_policy_that_disagrees_is_refused(tmp_path: Path) -> None:
    import yaml

    document = yaml.safe_load(
        (REPOSITORY_ROOT / policy.DEFAULT_POLICY_PATH).read_text(encoding="utf-8")
    )
    document["score"]["calibrated"] = True
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    from fpbench.core.verifinger_errors import VeriFingerError

    with pytest.raises(VeriFingerError):
        policy.require_policy_matches_source(policy.read_runtime_policy(path))


# ------------------------------------------------------- the Stage 11A binding


def test_stage_11b_is_bound_to_the_published_stage_11a_qualification() -> None:
    published = require_stage11a_binding(
        declared_fingerprint=identity.STAGE_11A_FINALIZATION_FINGERPRINT,
        declared_outcome=identity.STAGE_11A_OUTCOME,
        repository_root=REPOSITORY_ROOT,
    )
    assert published.outcome == "VERIFINGER_PREFLIGHT_PASS"
    assert published.opens_stage_11b is True
    assert published.gates_passed == 17


def test_a_different_fingerprint_stops_the_stage() -> None:
    with pytest.raises(Stage11BBindingError):
        require_stage11a_binding(
            declared_fingerprint="0" * 64,
            declared_outcome=identity.STAGE_11A_OUTCOME,
            repository_root=REPOSITORY_ROOT,
        )


def test_a_different_outcome_stops_the_stage() -> None:
    with pytest.raises(Stage11BBindingError):
        require_stage11a_binding(
            declared_fingerprint=identity.STAGE_11A_FINALIZATION_FINGERPRINT,
            declared_outcome="VERIFINGER_PREFLIGHT_FAIL",
            repository_root=REPOSITORY_ROOT,
        )


# ------------------------------------------------------------- the experiment


def test_the_experiment_config_loads_and_is_frozen() -> None:
    from fpbench.experiments.verifinger_canonical500_full import (
        load_verifinger_canonical500_config,
    )

    config = load_verifinger_canonical500_config(repository_root=REPOSITORY_ROOT)
    assert config.experiment_id == frozen.EXPERIMENT_ID
    assert config.expected_jobs == 6000
    assert config.job_deadline_seconds == frozen.JOB_DEADLINE_SECONDS
    assert config.max_workers == 1
    assert config.reference.run_id == frozen.REFERENCE_RUN_ID
    assert config.reference_pair_manifest_hash == frozen.REFERENCE_PAIR_MANIFEST_HASH
    assert config.preparation_set_id == frozen.PREPARATION_SET_ID
    assert config.runtime_manifest_fingerprint
    assert config.planned_logical_extractions == 12000
    assert config.planned_verify_invocations == 6000


@pytest.mark.parametrize(
    "mutation",
    [
        {"expected": {"jobs": 5999}},
        {"execution": {"retries": 1}},
        {"execution": {"max_workers": 2}},
        {"execution": {"job_deadline_seconds": 120}},
        {"reporting": {"score_statistics": True}},
        {"operations": {"logical_extractions_per_comparison": 1}},
        {"stage11a": {"outcome": "VERIFINGER_PREFLIGHT_FAIL"}},
    ],
)
def test_an_edited_experiment_is_refused(tmp_path: Path, mutation) -> None:
    import yaml

    from fpbench.experiments.verifinger_canonical500_full import (
        DEFAULT_EXPERIMENT_CONFIG,
        load_verifinger_canonical500_config,
    )

    document = yaml.safe_load(
        Path(DEFAULT_EXPERIMENT_CONFIG).read_text(encoding="utf-8")
    )
    for section, changes in mutation.items():
        document[section].update(changes)
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_verifinger_canonical500_config(path, repository_root=REPOSITORY_ROOT)


def test_a_threshold_anywhere_in_the_experiment_is_refused(tmp_path: Path) -> None:
    import yaml

    from fpbench.experiments.verifinger_canonical500_full import (
        DEFAULT_EXPERIMENT_CONFIG,
        load_verifinger_canonical500_config,
    )

    document = yaml.safe_load(
        Path(DEFAULT_EXPERIMENT_CONFIG).read_text(encoding="utf-8")
    )
    document["algorithm"]["threshold"] = 48
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_verifinger_canonical500_config(path, repository_root=REPOSITORY_ROOT)


def test_the_experiment_reuses_the_canonical_reference_exactly() -> None:
    from fpbench.experiments.verifinger_validation import SD300_CANONICAL500_INPUT_SET

    assert SD300_CANONICAL500_INPUT_SET.preparation_set_id == "prepset_be560e047991"
    assert SD300_CANONICAL500_INPUT_SET.entry_count == 3000
    assert SD300_CANONICAL500_INPUT_SET.target_ppi == 500


def test_the_algorithm_config_restates_what_this_source_freezes() -> None:
    import yaml

    document = yaml.safe_load(
        (
            REPOSITORY_ROOT / "configs" / "algorithms" / "verifinger_2025_2_1to1_v1.yaml"
        ).read_text(encoding="utf-8")
    )
    assert document["algorithm"]["id"] == identity.ALGORITHM_ID
    assert document["algorithm"]["adapter_id"] == identity.ADAPTER_ID
    assert document["stage11a"]["finalization_fingerprint"] == (
        identity.STAGE_11A_FINALIZATION_FINGERPRINT
    )
    assert tuple(document["adapter"]["forbidden_inputs"]) == identity.FORBIDDEN_INPUTS
    assert document["runtime"]["expected_delivered_defaults"] == dict(
        identity.EXPECTED_RUNTIME_DEFAULTS
    )
    # 48 appears once, as the official sample's own setting, and immediately
    # beside the statement that fpbench produces no threshold of its own.
    assert document["runtime"]["official_sample_matching_threshold"] == 48
    assert document["runtime"]["decision_threshold_produced_by_fpbench"] is False
    assert document["score"]["calibration"] == "none"
    assert document["score"]["failure_scored_as_zero"] is False
    assert "decision_profile" not in json.dumps(document)


# ------------------------------------------------------------------- the guards


def test_no_vendor_byte_is_tracked_in_this_repository() -> None:
    """The one failure this project cannot take back (docs/adr/0083)."""
    from fpbench.experiments.stage11a_artifacts import require_no_verifinger_bytes_in_git

    require_no_verifinger_bytes_in_git(repository_root=REPOSITORY_ROOT)


def test_no_committed_stage_11b_file_carries_a_machine_path() -> None:
    """Evidence and configuration name relative paths, never a home directory."""
    suspects = [
        REPOSITORY_ROOT / "configs" / "verifinger",
        REPOSITORY_ROOT / "configs" / "algorithms" / "verifinger_2025_2_1to1_v1.yaml",
        REPOSITORY_ROOT / "configs" / "experiments" / "verifinger_canonical500_full_v1.yaml",
    ]
    offenders: list[str] = []
    for location in suspects:
        files = [location] if location.is_file() else sorted(location.rglob("*"))
        for path in files:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if "C:\\Users" in text or "/home/" in text or "C:/Users" in text:
                offenders.append(path.name)
    assert offenders == []


def test_no_credential_appears_in_any_committed_stage_11b_file() -> None:
    banned = ("licence_key", "license_key", "serial_number", "activation_id", "pgd2.idm")
    for location in (
        REPOSITORY_ROOT / "configs" / "verifinger",
        REPOSITORY_ROOT / "integrations" / "verifinger-java",
    ):
        for path in sorted(location.rglob("*")):
            if not path.is_file() or path.suffix in (".jar", ".class"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for needle in banned:
                assert needle not in text, f"{path.name} mentions {needle}"
