"""The committed Stage 19A evidence gate.

Reads only what is in the repository: six documents, their own recorded digests,
and the predecessor markers they bind. No dataset, no NBIS build, no OpenAFIS
binary.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from fpbench.experiments import stage19a_identity as frozen
from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT
from fpbench.experiments.stage19a_finalization import stage19a_source_fingerprint

pytestmark = pytest.mark.stage19a

DIRECTORY = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY


def _read(name: str) -> dict:
    return json.loads((DIRECTORY / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def marker() -> dict:
    return _read(frozen.STAGE_19A_FINALIZATION_NAME)


def test_the_evidence_is_exactly_the_declared_documents(marker):
    present = sorted(path.name for path in DIRECTORY.iterdir() if path.is_file())
    assert present == sorted([*frozen.EVIDENCE_DOCUMENTS, frozen.STAGE_19A_FINALIZATION_NAME])


def test_every_evidence_byte_matches_the_digest_the_marker_published(marker):
    for name, digest in marker["evidence_content_hashes"].items():
        assert hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() == digest, name


def test_the_marker_fingerprint_covers_the_marker(marker):
    payload = {k: v for k, v in marker.items() if k != "stage_19a_finalization_fingerprint"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(encoded.encode("utf-8")).hexdigest() == marker["stage_19a_finalization_fingerprint"]


def test_the_source_fingerprint_still_describes_this_tree(marker):
    assert marker["stage19a_source_fingerprint"] == stage19a_source_fingerprint(REPOSITORY_ROOT)


def test_the_raw_run_completed(marker):
    assert marker["canonical_run_executed"] is True
    assert (
        marker["unique_pair_ids"]
        == marker["unique_ordinals"]
        == marker["diagnostic_comparisons"]
        == marker["stored_outcomes"]
        == marker["expected_outcomes"]
        == 6000
    )
    assert marker["missing"] == 0
    assert len(marker["outcome_store_sha256"]) == 64

    binding = _read("canonical-run-binding.json")
    for field in (
        "expected_outcomes",
        "stored_outcomes",
        "unique_pair_ids",
        "unique_ordinals",
        "diagnostic_comparisons",
        "missing",
        "outcome_store_sha256",
    ):
        assert binding[field] == marker[field]


def test_the_score_contract_is_raw(marker):
    assert marker["threshold"] is None
    assert marker["score_transform"] == "NONE"
    assert marker["score_direction"] == "HIGHER_MORE_SIMILAR"
    assert marker["failures_recorded_as_zero"] is False


def test_nothing_was_chosen_from_the_secugen_reference(marker):
    assert marker["secugen_reference_used_for_parameter_selection"] is False


def test_the_shared_extractor_is_stated_in_the_marker_itself(marker):
    # Not only in prose: the one fact a reader of the comparison table must have.
    assert marker["shares_extractor_with"] == "nbis_mindtct_bozorth3"
    assert marker["is_an_independent_fifth_system"] is False


def test_establishment_is_never_asserted_without_the_human_determination(marker):
    sufficiency = marker["cross_impression_sufficiency"]
    assert sufficiency in frozen.SUFFICIENCY_STATES
    assert marker["cross_impression_sufficiency_is_a_human_determination"] is True

    if sufficiency == "UNDETERMINED":
        # null, not false. Nobody judged it, which is a different claim.
        assert marker["algorithm_5_established"] is None
        assert marker["algorithm_5_conditions"]["substantial_cross_impression_score_bearing"] is None
        assert marker["opens_common_calibration"] is False
        assert marker["publication_eligible"] is False
    else:
        assert isinstance(marker["algorithm_5_established"], bool)


def test_the_three_machine_conditions_are_published(marker):
    conditions = marker["algorithm_5_conditions"]
    assert conditions["translation_settled_from_sources_not_tuning"] is True
    assert set(conditions) == {
        "translation_settled_from_sources_not_tuning",
        "no_systemic_implementation_defect",
        "failures_are_upstream_limits_not_the_bridge",
        "substantial_cross_impression_score_bearing",
    }


def test_no_calibration_or_decision_was_produced(marker):
    assert marker["calibration_performed"] is False
    assert marker["decision_profile_produced"] is False
    assert marker["metrics_produced"] is False
    assert marker["algorithm_ranking_published"] is False


def test_the_run_is_bound_to_the_same_inputs_as_the_other_algorithms(marker):
    assert marker["preparation_set_id"] == "prepset_be560e047991"
    assert marker["pair_manifest_hash"] == (
        "ee4d942e23cdc112e17ed69e0abc603d5f26e17cc5839edc9aa412edc57dfe3b"
    )
    assert marker["nbis_build_id"] == "658f9f54a8f2"


def test_the_evidence_carries_no_absolute_path(marker):
    assert marker["absolute_paths_in_evidence"] is False
    for name in frozen.EVIDENCE_DOCUMENTS:
        text = (DIRECTORY / name).read_text(encoding="utf-8")
        for fragment in ("C:\\", "/home/", "/mnt/c/", "\\Users\\"):
            assert fragment not in text, f"{name} carries {fragment}"


def test_the_bound_predecessors_still_publish_these_fingerprints(marker):
    published = {
        "18A": ("evidence/stage18a-secugen-openafis-reference/stage-18a-finalization.json",
                "stage_18a_finalization_fingerprint"),
        "17A": ("evidence/stage17a-fingerprintmatcher/stage-17a-finalization.json",
                "stage_17a_finalization_fingerprint"),
        "8E": ("evidence/stage8e-research-only-policy/stage-8e-finalization.json",
               "stage_8e_finalization_fingerprint"),
    }
    for bound in marker["bound_markers"]:
        relative, field = published[bound["stage"]]
        document = json.loads((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))
        assert bound["finalization_fingerprint"] == document[field], bound["stage"]
        assert bound["outcome"] == document["outcome"], bound["stage"]


def test_the_translation_contract_names_an_authority_for_every_rule():
    contract = _read("translation-contract.json")
    assert contract["secugen_reference_used_for_parameter_selection"] is False
    assert contract["angle"]["inversion"] == "none"
    assert contract["angle"]["rotation"] == "none"
    assert "xytreps.c" in contract["angle"]["mindtct_authority"]
    assert "TripletScalar.cpp" in contract["angle"]["openafis_authority"]
    assert contract["bounds"]["top_n_rule_refused"] is True
    assert contract["bounds"]["over_maximum_policy"] == "record_template_failure_never_truncate"
    assert contract["quality"]["used_to_filter"] is False


def _keys(node: object) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key.lower())
            found |= _keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _keys(item)
    return found


def test_the_matcher_comparison_carries_no_verdict_field():
    comparison = _read("matcher-comparison.json")
    # The document is allowed — required, in fact — to say the words "better" and
    # "not" in explaining what it withholds. What it must not have is a *field*
    # holding a verdict or a rate.
    present = _keys(comparison)
    for forbidden in ("winner", "better", "worse", "verdict", "tar", "far", "eer", "threshold", "accuracy"):
        assert forbidden not in present, forbidden

    inner = comparison["comparison"]
    assert inner["differs_only_in"] == "the matcher"
    assert inner["spearman_is_over_a_self_selected_subset"] is True
    # Both counts are published, so a reader cannot see the correlation without
    # also seeing how much of the manifest it was computed over.
    assert inner["algorithm_2_score_bearing"] == 6000
    assert inner["algorithm_5_score_bearing"] == inner["both_score_bearing"]


def test_the_adr_exists():
    adr = REPOSITORY_ROOT / "docs" / "adr" / "0135-the-translation-is-settled-from-source-not-from-scores.md"
    assert adr.is_file()
