"""The committed Stage 18A evidence gate.

Reads only what is in the repository: five documents, their own recorded digests,
and the predecessor markers they bind. No dataset, no vendor SDK, no OpenAFIS
build and no private run — so this is the check that keeps running long after the
machine that produced the numbers is gone.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fpbench.experiments import stage18a_identity as frozen
from fpbench.experiments.stage18a_finalization import stage18a_source_fingerprint
from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT

pytestmark = pytest.mark.stage18a

DIRECTORY = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY


def _read(name: str) -> dict:
    return json.loads((DIRECTORY / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def marker() -> dict:
    return _read(frozen.STAGE_18A_FINALIZATION_NAME)


def test_the_evidence_is_exactly_the_declared_documents(marker):
    present = sorted(path.name for path in DIRECTORY.iterdir() if path.is_file())
    expected = sorted([*frozen.EVIDENCE_DOCUMENTS, frozen.STAGE_18A_FINALIZATION_NAME])
    assert present == expected


def test_every_evidence_byte_matches_the_digest_the_marker_published(marker):
    for name, digest in marker["evidence_content_hashes"].items():
        actual = hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest()
        assert actual == digest, name


def test_the_marker_fingerprint_covers_the_marker(marker):
    payload = {k: v for k, v in marker.items() if k != "stage_18a_finalization_fingerprint"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(encoded.encode("utf-8")).hexdigest() == marker["stage_18a_finalization_fingerprint"]


def test_the_source_fingerprint_still_describes_this_tree(marker):
    assert marker["stage18a_source_fingerprint"] == stage18a_source_fingerprint(REPOSITORY_ROOT)


def test_the_outcome_is_the_completion_and_nothing_more(marker):
    assert marker["outcome"] == frozen.OUTCOME_COMPLETE
    assert marker["expected_pair_outcomes"] == 6000
    assert marker["stored_pair_outcomes"] == 6000
    assert marker["missing"] == 0


def test_the_marker_never_claims_algorithm_5_or_publication(marker):
    assert marker["algorithm_5_established"] is False
    assert marker["opens_common_calibration"] is False
    assert marker["publication_eligible"] is False
    assert marker["purpose"] == "PRIVATE_REFERENCE_ONLY"
    assert marker["calibration_performed"] is False
    assert marker["decision_profile_produced"] is False
    assert marker["metrics_produced"] is False
    assert marker["threshold_applied"] is False
    assert marker["production_adapter_built"] is False


def test_the_marker_is_honest_that_the_input_pixels_differ(marker):
    # The one property that would be easy to leave implied, and that a reader
    # comparing this column to the other four has to be told.
    assert marker["canonical_input_pixels_identical_to_other_algorithms"] is False
    assert "aspect ratio" in marker["why_input_pixels_differ"]


def test_the_score_contract_is_raw(marker):
    assert marker["fpbench_score_transformation"] == "NONE"
    assert marker["failures_recorded_as_zero"] is False
    assert marker["zero_is_a_valid_raw_score"] is True
    assert marker["pair_orientation_fixed"] is True


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


def test_no_score_and_no_vendor_byte_reached_the_repository(marker):
    assert marker["scores_in_evidence"] is False
    assert marker["vendor_binaries_in_git"] is False

    binding = _read("private-run-binding.json")
    assert binding["scores_are_not_published_here"] is True

    # On keys, not on substrings: the document names "score histogram 0..100" in
    # its list of permitted diagnostics, and saying the words is not publishing
    # the numbers. What must not exist is a field carrying one.
    present = _keys(binding)
    for forbidden in ("openafis_score", "histogram", "median_score", "scores", "distribution"):
        assert forbidden not in present, forbidden


def test_the_evidence_carries_no_absolute_path(marker):
    assert marker["absolute_paths_in_evidence"] is False
    for name in frozen.EVIDENCE_DOCUMENTS:
        text = (DIRECTORY / name).read_text(encoding="utf-8")
        for fragment in ("C:\\", "/home/", "/mnt/c/", "\\Users\\"):
            assert fragment not in text, f"{name} carries {fragment}"


def test_the_bound_predecessors_still_publish_these_fingerprints(marker):
    published = {
        "17A": REPOSITORY_ROOT / "evidence/stage17a-fingerprintmatcher/stage-17a-finalization.json",
        "15A": REPOSITORY_ROOT / "evidence/stage15a-fingerprints-matching/stage-15a-finalization.json",
        "8E": REPOSITORY_ROOT / "evidence/stage8e-research-only-policy/stage-8e-finalization.json",
    }
    fields = {
        "17A": "stage_17a_finalization_fingerprint",
        "15A": "stage_15a_finalization_fingerprint",
        "8E": "stage_8e_finalization_fingerprint",
    }
    for bound in marker["bound_markers"]:
        stage = bound["stage"]
        document = json.loads(published[stage].read_text(encoding="utf-8"))
        assert bound["finalization_fingerprint"] == document[fields[stage]], stage
        assert bound["outcome"] == document["outcome"], stage


def test_the_openafis_identity_pins_the_commit_and_its_contract_files():
    identity = _read("openafis-identity.json")
    assert identity["commit"] == frozen.OPENAFIS_COMMIT
    assert identity["license"] == "BSD-2-Clause"
    assert identity["score_contract"]["transform"] == "NONE"
    assert identity["score_contract"]["threshold"] == "NONE"
    assert identity["score_contract"]["zero_is_a_valid_score"] is True
    assert set(identity["contract_files"]) == set(frozen.OPENAFIS_CONTRACT_FILES)


def test_the_route_contract_records_every_deviation_with_a_reason():
    route = _read("route-contract.json")
    assert route["resize"]["aspect_ratio_preserved"] is False
    assert route["impression_type"]["applies_to_rolled_prints_too"] is True
    assert route["determinism"]["result"] == "identical"
    assert route["fallback_used"] == "A"
    assert route["recorded_deviations"], "a route contract with no deviations is a claim, not a record"
    for deviation in route["recorded_deviations"]:
        assert deviation["deviation"]
        assert deviation["why"], deviation["deviation"]


def test_the_forbidden_stage19_uses_are_published(marker):
    assert marker["forbidden_stage19_uses"] == list(frozen.FORBIDDEN_STAGE19_USES)


def test_the_adr_exists():
    adr = REPOSITORY_ROOT / "docs" / "adr" / "0134-a-reference-route-is-copied-not-improved.md"
    assert adr.is_file()
