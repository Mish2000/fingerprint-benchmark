"""The committed Stage 19B evidence gate."""

from __future__ import annotations

import hashlib
import json

import pytest

from fpbench.experiments.stage18a_inputs import REPOSITORY_ROOT
from fpbench.experiments.stage19b_finalization import (
    EVIDENCE_DIRECTORY,
    EVIDENCE_DOCUMENTS,
    STAGE_19B_FINALIZATION_NAME,
    SUPERVISOR_DISCLOSURE,
    stage19b_source_fingerprint,
)

pytestmark = pytest.mark.stage19b

DIRECTORY = REPOSITORY_ROOT / EVIDENCE_DIRECTORY


def _read(name: str) -> dict:
    return json.loads((DIRECTORY / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def marker() -> dict:
    return _read(STAGE_19B_FINALIZATION_NAME)


def test_the_evidence_is_exactly_the_declared_documents(marker):
    present = sorted(path.name for path in DIRECTORY.iterdir() if path.is_file())
    assert present == sorted([*EVIDENCE_DOCUMENTS, STAGE_19B_FINALIZATION_NAME])


def test_every_evidence_byte_matches_the_digest_the_marker_published(marker):
    for name, digest in marker["evidence_content_hashes"].items():
        assert hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest() == digest, name


def test_the_marker_fingerprint_covers_the_marker(marker):
    payload = {k: v for k, v in marker.items() if k != "stage_19b_finalization_fingerprint"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(encoded.encode("utf-8")).hexdigest() == marker["stage_19b_finalization_fingerprint"]


def test_the_source_fingerprint_still_describes_this_tree(marker):
    assert marker["stage19b_source_fingerprint"] == stage19b_source_fingerprint(REPOSITORY_ROOT)


def test_gate_a_passed_exactly(marker):
    inertness = marker["baseline_inertness"]
    assert inertness["comparisons"] == 1583
    assert inertness["exact_score_matches"] == 1583
    assert inertness["mismatches"] == 0
    assert inertness["status_regressions"] == 0
    # The limit of the claim must travel with it.
    assert "upstream" in inertness["what_it_does_not_prove"]


def test_the_translator_inertness_is_published_too(marker):
    # Half the change was in fpbench's own translator; a marker that recorded only
    # the C++ half would be claiming more than was proved.
    inertness = marker["translator_inertness"]
    assert inertness["counts_compared"] == 127
    assert inertness["byte_identical"] == 127
    assert inertness["mismatches"] == 0


def test_the_capacity_problem_is_gone(marker):
    assert marker["capacity_failures_remaining"] == 0
    assert (
        marker["unique_pair_ids"]
        == marker["unique_ordinals"]
        == marker["diagnostic_comparisons"]
        == marker["stored_outcomes"]
        == marker["expected_outcomes"]
        == 6000
    )
    assert marker["missing"] == 0
    assert marker["score_bearing"] == 6000
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


def test_all_the_structural_conditions_hold(marker):
    """Section 17's six, and the two added since — all computed for this run."""
    conditions = marker["algorithm_5_conditions"]
    assert set(conditions) == {
        "gate_a_baseline_scores_identical",
        "canonical_run_complete",
        "no_capacity_failure_remains",
        "no_systemic_implementation_defect",
        "translation_contract_unchanged",
        "no_secugen_based_tuning",
        "no_unclassified_failure",
        "at_least_one_score",
    }
    assert all(conditions.values())
    assert marker["algorithm_5_established"] is True


def test_establishment_follows_from_the_conditions_and_nothing_else(marker):
    # No accuracy floor was applied, and none may be implied later.
    assert "minimum_score" not in marker
    assert "minimum_median" not in marker
    assert marker["threshold"] is None
    assert marker["metrics_produced"] is False
    assert marker["algorithm_ranking_published"] is False


def test_the_modification_is_never_hidden(marker):
    assert marker["upstream_modified"] is True
    assert marker["base_openafis_commit"] == "3ae1c757c6dafea977a33ef51380e37f1715e626"
    assert marker["modification"] == (
        "disable_template_upper_minutiae_rejection_for_stage19b_csv_route"
    )
    assert marker["algorithm_id"].endswith("_capacity_extended")


def test_the_supervisor_disclosure_is_a_field_not_only_prose(marker):
    # It has to survive being copied into a table by someone who did not read the
    # README, so the marker carries it verbatim.
    assert marker["supervisor_disclosure"] == SUPERVISOR_DISCLOSURE
    assert "capacity-extended variant" in marker["supervisor_disclosure"]
    assert "1,583 previously accepted comparisons" in marker["supervisor_disclosure"]


def test_the_shared_extractor_is_still_declared(marker):
    assert marker["shares_extractor_with"] == "nbis_mindtct_bozorth3"
    assert marker["is_independent_fifth_system"] is False


def test_nothing_was_chosen_from_the_secugen_reference(marker):
    assert marker["secugen_reference_used_for_parameter_selection"] is False


def test_the_patch_is_minimal_and_auditable():
    patch = _read("patch-provenance.json")
    assert patch["files_changed"] == 1
    assert patch["lines_added"] == 2
    assert patch["lines_removed"] == 0
    assert patch["constant_maximum_minutiae_changed"] is False
    assert patch["minimum_minutiae_unchanged"] is True
    assert patch["matching_algorithm_unchanged"] is True
    assert patch["files_differing_from_pristine_tree"] == ["lib/Template.cpp"]
    # The pristine file must still be the one Stage 18A pinned.
    assert patch["pristine_template_cpp_sha256"] == (
        "c815a69b995aaa444a6b00be4e5827ab708874fbac18ca6003d337f6aea6acfa"
    )
    for key in ("patched_template_cpp_sha256", "compiled_bridge_sha256", "compiler", "build_command"):
        assert patch[key]


def test_no_score_affecting_field_differs_from_the_base_route():
    identity = _read("variant-identity.json")
    assert all(identity["score_affecting_fields_identical_to_base_route"].values())
    assert identity["compare_inherited_unchanged"] is True
    assert sorted(identity["overridden_methods"]) == ["__init__", "_translate", "from_config", "validate_environment"]


def test_the_evidence_carries_no_absolute_path(marker):
    assert marker["absolute_paths_in_evidence"] is False
    for name in EVIDENCE_DOCUMENTS:
        text = (DIRECTORY / name).read_text(encoding="utf-8")
        for fragment in ("C:\\", "/home/", "/mnt/c/", "\\Users\\"):
            assert fragment not in text, f"{name} carries {fragment}"


def test_the_bound_predecessors_still_publish_these_fingerprints(marker):
    published = {
        "19A": ("evidence/stage19a-mindtct-openafis/stage-19a-finalization.json",
                "stage_19a_finalization_fingerprint"),
        "18A": ("evidence/stage18a-secugen-openafis-reference/stage-18a-finalization.json",
                "stage_18a_finalization_fingerprint"),
        "8E": ("evidence/stage8e-research-only-policy/stage-8e-finalization.json",
               "stage_8e_finalization_fingerprint"),
    }
    for bound in marker["bound_markers"]:
        relative, field = published[bound["stage"]]
        document = json.loads((REPOSITORY_ROOT / relative).read_text(encoding="utf-8"))
        assert bound["finalization_fingerprint"] == document[field], bound["stage"]


def test_the_adr_exists():
    adr = REPOSITORY_ROOT / "docs" / "adr" / "0136-a-modified-matcher-gets-its-own-identity.md"
    assert adr.is_file()


def test_the_published_conditions_are_the_ones_the_rule_derives(marker):
    """Section 17's six conditions, re-derived from the documents beside them.

    ``no_capacity_failure_remains`` is the one Stage 19B exists to answer, and
    it used to be read out of a diagnostics document — a report the run wrote
    about itself, which a store of six thousand capacity failures could
    contradict while still publishing ``{}``. Both are now counted off the
    verified store and land in the binding; this checks the marker agrees with
    the binding it was assembled from.
    """
    from fpbench.experiments.stage19b_finalization import BLOCKING_STATUSES

    binding = _read("canonical-run-binding.json")
    counts = binding["outcome_counts"]
    blocking = sum(int(v) for k, v in counts.items() if k in BLOCKING_STATUSES)
    conditions = marker["algorithm_5_conditions"]

    assert conditions["no_systemic_implementation_defect"] is (blocking == 0)
    assert conditions["no_capacity_failure_remains"] is (
        binding["capacity_failures_remaining"] == 0
    )
    assert conditions["canonical_run_complete"] is (
        binding["unique_pair_ids"] == 6000
        and binding["unique_ordinals"] == 6000
        and binding["diagnostic_comparisons"] == 6000
        and binding["stored_outcomes"] == 6000
        and binding["expected_outcomes"] == 6000
        and binding["missing"] == 0
    )


def test_establishment_is_never_wider_than_the_run_it_rests_on(marker):
    """A run with no scores cannot establish an algorithm.

    The reviewer's store scored nothing: 6,000 rows, every one of them
    ``OPENAFIS_TEMPLATE_FAILED_LEFT``, ``score_bearing: 0`` — and
    ``algorithm_5_established: true``, because the capacity count came from a
    diagnostics document that reported ``{}``. Establishment and a scoring run
    are now tied together in the published evidence.
    """
    binding = _read("canonical-run-binding.json")
    if not marker["algorithm_5_established"]:
        return
    assert binding["score_bearing"] > 0
    assert binding["score_bearing"] == binding["outcome_counts"].get("OK", 0)
    assert binding["capacity_failures_remaining"] == 0
    assert sum(binding["failure_reasons"].values()) == (
        binding["stored_outcomes"] - binding["score_bearing"]
    )


def test_the_published_run_satisfies_the_conditions_added_since(marker):
    """Two conditions were added after this run was published.

    ``no_unclassified_failure`` and ``at_least_one_score`` are not in the
    marker's own ``algorithm_5_conditions`` — the publisher that wrote it did
    not compute them. The evidence beside it does say whether they hold, and
    they do: 6,000 comparisons, every one scored, no failure of any kind. A
    reader should not have to take that on the marker's silence.
    """
    binding = _read("canonical-run-binding.json")
    assert binding["score_bearing"] > 0, "ADR 0128: no score, no matcher"
    assert binding["failure_reasons"] == {}
    assert binding["outcome_counts"] == {"OK": binding["stored_outcomes"]}
    if marker["algorithm_5_established"]:
        assert binding["score_bearing"] == binding["stored_outcomes"]


def test_every_published_status_is_one_the_route_declares(marker):
    """The vocabulary the validator now closes, checked against what was run."""
    from fpbench.experiments.stage19b_finalization import ALLOWED_STATUSES

    counts = _read("canonical-run-binding.json")["outcome_counts"]
    unknown = sorted(set(counts) - ALLOWED_STATUSES)
    assert not unknown, (
        f"the published run recorded {unknown}, which this route cannot produce"
    )
