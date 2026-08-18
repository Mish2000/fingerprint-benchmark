"""The committed Stage 20A MCC SDK evidence gate.

This suite needs no vendor byte, .NET runtime, network access, or dataset. It
re-derives the published hashes and checks that the PASS says only what the
official package and the non-SD300 smoke established.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fpbench.experiments import stage20a_mcc_contract as route
from fpbench.experiments import stage20a_mcc_sdk as stage

pytestmark = pytest.mark.stage20a

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPOSITORY_ROOT / stage.EVIDENCE_DIRECTORY


def _read(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def marker() -> dict:
    return _read(stage.FINALIZATION_NAME)


def test_the_evidence_shape_is_exact() -> None:
    assert sorted(path.name for path in EVIDENCE.iterdir() if path.is_file()) == sorted(
        stage.EVIDENCE_DOCUMENTS
    )


def test_the_published_stage_verifies_end_to_end() -> None:
    result = stage.verify_evidence(repository_root=REPOSITORY_ROOT)
    assert result == {
        "outcome": "MINDTCT_MCC_SDK_V2_ROUTE_PASS",
        "candidate": "nbis_mindtct_mcc_sdk_v2",
        "opens_stage20b": True,
        "missing_documents": [],
        "unexpected_documents": [],
    }


def test_every_evidence_byte_matches_the_marker(marker: dict) -> None:
    assert set(marker["evidence_content_hashes"]) == set(stage.EVIDENCE_DOCUMENTS) - {
        stage.FINALIZATION_NAME
    }
    for name, digest in marker["evidence_content_hashes"].items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == digest


def test_the_marker_fingerprint_covers_the_marker(marker: dict) -> None:
    payload = {
        key: value
        for key, value in marker.items()
        if key != "stage_20a_finalization_fingerprint"
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == marker[
        "stage_20a_finalization_fingerprint"
    ]


def test_the_source_fingerprint_describes_this_stage(marker: dict) -> None:
    assert marker["stage20a_source_fingerprint"] == stage.stage20a_source_fingerprint(
        REPOSITORY_ROOT
    )


def test_the_official_artifact_is_exactly_pinned() -> None:
    artifact = _read("artifact-identity.json")
    assert artifact["artifact_source"] == "OFFICIAL_AUTHOR_LAB"
    assert artifact["research_use"] == "ALLOWED_BY_PUBLISHED_TERMS"
    assert artifact["redistribution"] == "NOT_ASSUMED_ALLOWED"
    assert artifact["self_service_download"] is True
    assert artifact["additional_acquisition_gate"] is False
    assert artifact["archive_filename"] == "MCCSdk v2.0.zip"
    assert artifact["archive_size"] == 10_404_479
    assert artifact["archive_sha256"] == stage.ARCHIVE_SHA256
    assert artifact["archive"] == {
        "filename": "MCCSdk v2.0.zip",
        "size": 10_404_479,
        "sha256": stage.ARCHIVE_SHA256,
        "entry_count": 266,
        "file_count": 238,
        "uncompressed_file_bytes": 21_379_632,
    }
    assert {entry["sha256"] for entry in artifact["dlls"]} == {stage.DLL_SHA256}
    assert {entry["size"] for entry in artifact["dlls"]} == {171_008}
    assert artifact["included_gui"]["present"] is True
    assert artifact["included_gui"]["source_included"] is False
    assert artifact["included_matlab_examples"] is True
    assert {item["filename"] for item in artifact["documentation"]} == {
        "MccSdk Documentation v2.0.pdf",
        "MccSdk License v2.0.pdf",
        "Sdk/MccSdk.XML",
        "Executables/MccSdk.XML",
    }
    assert artifact["third_party_bytes_added_to_git"] is False


def test_the_delivered_terms_allow_this_research_but_are_not_redistributed() -> None:
    license_record = _read("license-use-record.json")
    assert license_record["research_use"] == "ALLOWED_BY_PUBLISHED_TERMS"
    assert license_record["redistribution"] == "NOT_ASSUMED_ALLOWED"
    assert license_record["redistributed_by_fpbench"] is False
    assert license_record["published_terms"]["research_purposes_only"] is True
    assert license_record["published_terms"]["paper_citation_required"] is True
    for key in (
        "vendor_archive_committed",
        "vendor_dll_committed",
        "vendor_documentation_bytes_committed",
        "vendor_sample_bytes_committed",
    ):
        assert license_record[key] is False


def test_the_dll_has_no_raster_extraction_api() -> None:
    inventory = _read("api-inventory.json")
    assert inventory["raster_image_api"]["present"] is False
    assert inventory["raster_image_api"]["minutiae_extractor"] is False
    assert inventory["minutia_struct"]["consumed_fields"] == [
        "X",
        "Y",
        "Direction",
    ]
    mcc = next(
        item
        for item in inventory["exported_types"]
        if item["full_name"] == "BioLab.Biometrics.Mcc.Sdk.MccSdk"
    )
    template_methods = [
        signature
        for signature in mcc["methods"]
        if "CreateMccTemplate" in signature
    ]
    assert template_methods
    assert all(
        token not in " ".join(template_methods)
        for token in ("System.Drawing.Image", "System.Drawing.Bitmap", "System.Byte[]")
    )


def test_the_exact_minutiae_route_is_closed_without_a_project_choice() -> None:
    contract = _read("input-route-contract.json")
    assert contract["candidate"] == route.CANDIDATE_ID
    assert contract["image_extractor_in_mcc_sdk"] is False
    assert contract["exact_mcc_input"]["api"] == route.TEMPLATE_API
    assert contract["translation"] == {
        "x": "x_mcc = x_xyt",
        "y": "y_mcc = image_height - y_xyt",
        "direction": "direction_mcc = theta_xyt_degrees * pi / 180",
        "quality": "ignored because MccSdk.Minutia has no quality field",
        "order": "MINDTCT order preserved",
        "minutiae_count": "all MINDTCT minutiae passed; no caller limit",
    }
    assert contract["field_contract"] == route.FIELD_CONTRACT
    assert contract["project_choice_fields"] == []
    assert contract["route_requires_score_affecting_fpbench_choice"] is False
    assert contract["route_closed"] is True
    assert contract["configuration"]["variant"] == "baseline MCC"
    assert contract["configuration"]["selection"] == "SDK_OPTIMAL_DEFAULTS"
    assert contract["configuration"]["parameter_setters_called"] is False
    assert contract["stage20b_self_contract"] == {
        "mindtct_extractions": 2,
        "mindtct_extractions_independent": True,
        "mcc_template_constructions": 2,
        "ordinary_match_invocation": True,
        "same_path_shortcut": False,
    }


def test_no_minutiae_filter_was_added() -> None:
    contract = _read("input-route-contract.json")
    mindtct = contract["mindtct"]
    assert mindtct["quality_cutoff"] is None
    assert mindtct["top_n"] is None
    assert mindtct["crop"] is None
    assert mindtct["resize"] is None
    assert mindtct["rotation"] is None
    source = (REPOSITORY_ROOT / stage.PROBE_SOURCE).read_text(encoding="utf-8")
    assert "MccSdk.SetMcc" not in source


def test_the_score_is_raw_native_and_higher_is_more_similar() -> None:
    score = _read("score-contract.json")
    assert score["exact_api"] == route.MATCH_API
    assert score["native_type"] == "System.Double"
    assert score["native_scalar_score"] is True
    assert score["range"] == {"minimum": 0.0, "maximum": 1.0, "inclusive": True}
    assert score["direction"] == "HIGHER_MORE_SIMILAR"
    assert score["calibration"] == "NONE"
    assert score["fpbench_threshold"] is None
    assert score["native_decision_rule"] is None
    assert score["score_transform"] == "NONE"
    assert score["pair_order"]["symmetric"] is True
    assert score["pair_order"]["aggregation_of_both_orders"] is None
    assert score["zero_score"]["valid_similarity"] is True
    assert score["zero_score"]["failure_sentinel"] is False


def test_the_runtime_qualification_is_windows_x64_and_needs_no_native_dll() -> None:
    runtime = _read("runtime-identity.json")
    assert runtime["documented_requirement"] == ".NET Framework 4.0"
    assert runtime["assembly"]["image_runtime_version"] == "v4.0.30319"
    assert runtime["target"]["managed_il_only"] is True
    assert runtime["target"]["required_32_bit"] is False
    assert runtime["target"]["any_cpu"] is True
    assert runtime["native_dll_dependencies_in_package"] == []
    assert runtime["windows_x64_qualified"] is True
    assert runtime["linux_qualification_required"] is False
    assert runtime["runtime_loads"] is True


def test_the_smoke_used_only_official_samples_and_ordinary_invocations() -> None:
    smoke = _read("runtime-smoke.json")
    assert smoke["status"] == "PASS"
    assert smoke["production_adapter"] is False
    assert smoke["sample_authority"] == "SDK_PROVIDED_SAMPLE_MINUTIAE"
    assert smoke["sample_files"] == ["1_1.txt", "1_2.txt", "2_1.txt"]
    assert smoke["sample_template_api"].endswith(
        "CreateMccTemplateFromTextTemplate(System.String)"
    )
    assert smoke["production_route_template_api"] == route.TEMPLATE_API
    assert smoke["parameter_setters_called"] is False
    assert smoke["all_scores_finite"] is True
    assert smoke["all_scores_in_documented_range"] is True
    assert smoke["pair_order_exactly_symmetric_on_smoke"] is True
    assert smoke["self_templates_constructed_independently"] is True
    assert smoke["sd300_images_used"] == 0
    assert smoke["score_values_used_to_change_route_or_configuration"] is False


def test_the_marker_is_the_requested_pass_and_opens_only_stage20b(marker: dict) -> None:
    assert marker["outcome"] == "MINDTCT_MCC_SDK_V2_ROUTE_PASS"
    assert marker["blocker"] is None
    assert marker["candidate"] == "nbis_mindtct_mcc_sdk_v2"
    assert marker["extractor"] == "NBIS_MINDTCT_5_0_0"
    assert marker["matcher"] == "OFFICIAL_MCC_SDK_V2"
    assert marker["shares_extractor_with"] == "nbis_mindtct_bozorth3"
    assert marker["native_scalar_score"] is True
    assert marker["route_closed"] is True
    assert marker["opens_stage20b"] is True
    assert marker["production_adapter_built"] is False
    assert marker["canonical_comparisons_executed"] == 0


def test_the_four_final_answers_are_unambiguous(marker: dict) -> None:
    answers = marker["final_answers"]
    assert answers["mcc_sdk_includes_image_extractor"] == "NO"
    assert "Minutia[]" in answers["exact_minutiae_input"]
    assert answers["raw_native_scalar_similarity"] == "YES"
    assert answers["canonical_image_to_mcc_score_without_sd300_choice"] == "YES"


def test_no_forbidden_selection_or_comparison_was_performed(marker: dict) -> None:
    assert marker["calibration_performed"] is False
    assert marker["threshold_selected_by_fpbench"] is False
    assert marker["sd300_images_opened"] == 0
    assert marker["sd300_parameter_selection"] is False
    assert marker["sd300_route_selection"] is False
    assert marker["sd300_performance_selection"] is False
    assert marker["prior_algorithm_scores_consulted"] is False
    assert marker["algorithm_comparison_performed"] is False
    assert marker["algorithm_ranking_performed"] is False


def test_no_vendor_bytes_or_local_absolute_paths_entered_evidence() -> None:
    forbidden = {".dll", ".exe", ".pdf", ".zip", ".mcc", ".ist"}
    for path in EVIDENCE.iterdir():
        assert path.suffix.lower() not in forbidden
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            assert "c:\\users\\" not in text
            assert "/home/" not in text
