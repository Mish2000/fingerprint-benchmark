"""The committed Stage 13A evidence, verified with nothing the stage needed.

No dataset, no vendor archive, no licence, no workspace and no prior result set.
What is under test is the publication: that the tree holds exactly the expected
files, that every document re-derives from source, that the claims it makes are
the ones the engine produces, that no credential or machine path reached any
published byte, and — while the preflight is incomplete — that no finalization
marker exists.

That last one is the point of this suite. A stage that is honestly half done must
look half done in its published evidence, and the way this project makes that
checkable is by refusing to write a marker until every gate has a final answer.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath

import pytest

from fpbench.experiments import stage13a_fingercell_identity as frozen
from fpbench.experiments import stage13a_fingercell_observations as observed
from fpbench.experiments import stage13a_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT
from fpbench.experiments.stage13a_finalization import (
    STAGE_13A_BASELINE_COMMIT,
    Stage13AFinalization,
    file_sha256,
    published_evidence_names,
    require_no_forbidden_published_data,
    require_no_sensitive_published_data,
    stage13a_source_fingerprint,
    stage_13a_finalization_fingerprint,
)

pytestmark = pytest.mark.stage13a

EVIDENCE = REPOSITORY_ROOT / frozen.EVIDENCE_DIRECTORY
MARKER = EVIDENCE / frozen.STAGE_13A_FINALIZATION_NAME


def _document(relative: str) -> dict:
    path = EVIDENCE / PurePosixPath(relative)
    if not path.is_file():
        pytest.skip(f"{relative} has not been published yet")
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------- the documents


def test_the_evidence_directory_holds_only_files_this_stage_publishes() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 13A evidence has not been published yet")
    found = set(published_evidence_names(REPOSITORY_ROOT))
    assert found <= set(frozen.REQUIRED_EVIDENCE_FILES), sorted(
        found - set(frozen.REQUIRED_EVIDENCE_FILES)
    )


def test_every_derivable_document_is_present() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 13A evidence has not been published yet")
    found = set(published_evidence_names(REPOSITORY_ROOT))
    missing = sorted(set(frozen.DERIVABLE_EVIDENCE_FILES) - found)
    assert not missing, missing


def test_every_document_rederives_or_is_bound_by_the_final_marker() -> None:
    """Verify live drafts from source and final evidence from its byte binding.

    A finalized run may depend on an unredistributable archive and licence that
    are intentionally absent in CI.  In that state the committed marker, rather
    than an unrelated offline rerun, is the authority over the published bytes.
    """
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 13A evidence has not been published yet")

    if MARKER.is_file():
        marker = _document(frozen.STAGE_13A_FINALIZATION_NAME)
        for name in frozen.DERIVABLE_EVIDENCE_FILES:
            assert file_sha256(EVIDENCE / PurePosixPath(name)) == marker[
                "evidence_content_hashes"
            ][name]
        return

    from fpbench.core.serialization import to_plain

    preflight = engine.run_preflight()
    for name in frozen.DERIVABLE_EVIDENCE_FILES:
        published = _document(name)
        derived = json.loads(json.dumps(to_plain(engine.evidence_document(preflight, name))))
        assert published == derived, name


def test_no_published_document_carries_a_credential_or_a_machine_path() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 13A evidence has not been published yet")
    require_no_sensitive_published_data(REPOSITORY_ROOT)


def test_no_published_document_carries_an_image_template_or_score() -> None:
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 13A evidence has not been published yet")
    require_no_forbidden_published_data(REPOSITORY_ROOT)


def test_every_published_runtime_path_is_relative() -> None:
    document = _document(frozen.PACKAGE_RUNTIME_IDENTITY_NAME)
    components = list(document["declared_link_closure"]) + list(
        document["observed_runtime_closure"]
    )
    for component in components:
        path = component["relative_path"]
        assert not path.startswith("/")
        assert ":" not in path


# ------------------------------------------------------------- the predecessor


def test_the_published_predecessor_is_the_closed_stage_12a_marker() -> None:
    document = _document(frozen.PREDECESSOR_BINDING_NAME)
    predecessor = document["predecessor"]
    assert predecessor["stage"] == "12A"
    assert predecessor["outcome"] == "IDKIT_PREFLIGHT_FAIL"
    assert predecessor["failure_class"] == "VENDOR_ACCESS_REFUSED"
    assert predecessor["finalization_fingerprint"] == (
        frozen.STAGE_12A_FINALIZATION_FINGERPRINT
    )
    assert (
        engine.require_stage12a_is_the_closed_predecessor(REPOSITORY_ROOT)
        == predecessor["finalization_fingerprint"]
    )


def test_the_published_evidence_names_no_prior_algorithm_score() -> None:
    document = _document(frozen.PREDECESSOR_BINDING_NAME)
    assert document["sd300_used"] is False
    assert document["prior_algorithm_scores_read"] is False
    for forbidden in frozen.FORBIDDEN_READS:
        assert forbidden in document["forbidden_reads"]


# ---------------------------------------------------------------- the gates


def test_the_report_agrees_with_the_engine_about_every_gate() -> None:
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    if MARKER.is_file():
        marker = _document(frozen.STAGE_13A_FINALIZATION_NAME)
        assert document["outcome"] == marker["outcome"]
        assert document["gates_reached"] == marker["gates_reached"]
        assert document["gates_passed"] == marker["gates_passed"]
        assert document["gates_awaiting_action"] == marker["gates_awaiting_action"]
        assert document["failure_class"] == marker["failure_class"]
        assert document["blockers"] == marker["blockers"]
        assert document["gate_count_defined"] == frozen.GATE_COUNT
        return

    preflight = engine.run_preflight()
    published = {row["gate"]: row["status"] for row in document["gates"]}
    for result in preflight.results:
        assert published[result.gate.value] == result.status.value
    assert document["outcome"] == preflight.outcome
    assert document["gate_count_defined"] == frozen.GATE_COUNT


def test_each_gate_document_carries_its_own_gate_and_status() -> None:
    report = _document(frozen.PREFLIGHT_REPORT_NAME)
    published = {row["gate"]: row["status"] for row in report["gates"]}
    for gate in frozen.GATE_ORDER:
        (name,) = frozen.gate_documents(gate)
        document = _document(name)
        assert document["gate"] == gate.value
        assert document["status"] == published[gate.value]


def test_a_gate_awaiting_an_action_publishes_no_blocker() -> None:
    """The distinction, checked in the published bytes rather than in memory."""
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    awaiting = [
        row for row in document["gates"] if row["status"] == "ACTION_REQUIRED"
    ]
    # The invariant is per gate. A gate awaiting an action never carries a
    # blocker; a *different* gate may still have failed, and that failure is what
    # decides the outcome.
    for row in awaiting:
        assert row["blockers"] == []
        assert row["outstanding_action"] is not None
    if awaiting:
        assert len(document["outstanding_actions"]) == len(awaiting)
    if document["outcome"] == frozen.STAGE_13A_INCOMPLETE_OUTCOME:
        assert document["blockers"] == []
        assert document["failure_class"] is None


def test_an_outstanding_action_says_what_was_done_and_what_remains() -> None:
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    for action in document["outstanding_actions"]:
        assert action["what_has_been_done"].strip()
        assert action["what_remains"]
        assert action["what_it_would_answer"].strip()
        assert action["action"] in {item.value for item in frozen.RequiredAction}


# -------------------------------------------------------------- the marker


def test_marker_presence_agrees_with_the_published_outcome() -> None:
    """A published incomplete run has no marker; a final run has exactly one."""
    report = _document(frozen.PREFLIGHT_REPORT_NAME)
    if report["outcome"] == frozen.STAGE_13A_INCOMPLETE_OUTCOME:
        assert not MARKER.is_file(), (
            "a finalization marker exists for published evidence that is still "
            "awaiting a local action (docs/adr/0112)"
        )
    else:
        assert report["outcome"] in frozen.STAGE_13A_FINAL_OUTCOMES
        assert MARKER.is_file(), "a final Stage 13A outcome has no marker"


def test_the_publisher_refuses_a_marker_while_an_action_is_outstanding(
    tmp_path, monkeypatch,
) -> None:
    from fpbench.core.fingercell_preflight_errors import Stage13AFinalizationError
    from fpbench.experiments import stage13a_finalization as finalization

    preflight = engine.run_preflight()
    if preflight.outcome != frozen.STAGE_13A_INCOMPLETE_OUTCOME:
        pytest.skip("the preflight has reached a final outcome")

    write_json = finalization.write_evidence_json

    def write_to_scratch(path, value):
        return write_json(tmp_path / path.name, value)

    monkeypatch.setattr(finalization, "write_evidence_json", write_to_scratch)
    with pytest.raises(Stage13AFinalizationError, match="outstanding"):
        finalization.write_stage13a_evidence(REPOSITORY_ROOT, include_marker=True)
    assert not (tmp_path / frozen.STAGE_13A_FINALIZATION_NAME).exists()


def test_the_marker_verifies_against_the_published_bytes() -> None:
    if not MARKER.is_file():
        pytest.skip("Stage 13A has not been finalized")
    payload = json.loads(MARKER.read_text(encoding="utf-8"))
    marker = Stage13AFinalization(
        **{
            key: value
            for key, value in payload.items()
            if key not in {"blockers", "evidence_content_hashes"}
        },
        blockers=tuple(payload["blockers"]),
        evidence_content_hashes=payload["evidence_content_hashes"],
    )
    assert marker.stage_13a_finalization_fingerprint == payload[
        "stage_13a_finalization_fingerprint"
    ]
    for name, digest in payload["evidence_content_hashes"].items():
        assert file_sha256(EVIDENCE / PurePosixPath(name)) == digest, name


def test_the_marker_pins_the_source_that_decided_the_preflight() -> None:
    if not MARKER.is_file():
        pytest.skip("Stage 13A has not been finalized")
    payload = json.loads(MARKER.read_text(encoding="utf-8"))
    assert payload["stage13a_source_fingerprint"] == stage13a_source_fingerprint(
        REPOSITORY_ROOT
    )


def test_the_marker_gate_counts_agree_with_the_engine() -> None:
    if not MARKER.is_file():
        pytest.skip("Stage 13A has not been finalized")
    payload = json.loads(MARKER.read_text(encoding="utf-8"))
    report = _document(frozen.PREFLIGHT_REPORT_NAME)
    assert payload["gates_reached"] == report["gates_reached"]
    assert payload["gates_passed"] == report["gates_passed"]
    assert payload["gates_awaiting_action"] == report["gates_awaiting_action"]
    # Only a PASS requires every gate to have been asked and answered. A FAIL may
    # strand an action it caused: a route that cannot be executed cannot be
    # observed either (docs/adr/0124).
    if payload["outcome"] == frozen.STAGE_13A_PASS_OUTCOME:
        assert payload["gates_awaiting_action"] == 0


# ------------------------------------------------------------ the boundaries


def test_the_stage_began_at_the_commit_that_closed_its_predecessor() -> None:
    assert len(STAGE_13A_BASELINE_COMMIT) == 40


def test_the_observations_fingerprint_is_the_published_one() -> None:
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    assert document["observations_fingerprint"] == observed.observations_fingerprint()


def test_the_acquisition_manifest_never_publishes_a_tokenized_locator() -> None:
    document = _document(frozen.ACQUISITION_MANIFEST_NAME)
    locator = document["official_locator"]
    assert "?" not in locator
    assert document["official_locator_is_untokenized"] is True
    assert document["tokenized_locators_are_not_published"] is True


def test_the_settings_closure_never_reports_a_vacuous_zero() -> None:
    """A count of zero over an inventory nobody recorded would read as closed."""
    document = _document(frozen.SETTINGS_CLOSURE_NAME)
    if document["settings_recorded"] == 0:
        assert document["status"] != "PASS"
    assert document["settings_list_is_not_exhaustive"] is True


def test_the_qualification_document_publishes_no_score() -> None:
    document = _document(frozen.QUALIFICATION_RUN_NAME)
    assert document["no_score_value_is_published"] is True
    body = json.dumps(document)
    assert '"raw_score"' not in body
    assert document["mandatory_failure_probe_count"] == 4
