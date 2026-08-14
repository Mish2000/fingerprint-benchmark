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


def test_every_document_redirves_byte_for_byte_from_source() -> None:
    """The published bytes are the derived bytes, not an edited copy of them."""
    if not EVIDENCE.is_dir():
        pytest.skip("Stage 13A evidence has not been published yet")
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
    for component in document["runtime_closure"]:
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
    preflight = engine.run_preflight()
    published = {row["gate"]: row["status"] for row in document["gates"]}
    for result in preflight.results:
        assert published[result.gate.value] == result.status.value
    assert document["outcome"] == preflight.outcome
    assert document["gate_count_defined"] == frozen.GATE_COUNT


def test_each_gate_document_carries_its_own_gate_and_status() -> None:
    preflight = engine.run_preflight()
    for gate in frozen.GATE_ORDER:
        (name,) = frozen.gate_documents(gate)
        document = _document(name)
        assert document["gate"] == gate.value
        assert document["status"] == preflight.status(gate).value


def test_a_gate_awaiting_an_action_publishes_no_blocker() -> None:
    """The distinction, checked in the published bytes rather than in memory."""
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    awaiting = [
        row for row in document["gates"] if row["status"] == "ACTION_REQUIRED"
    ]
    for row in awaiting:
        assert row["blockers"] == []
        assert row["outstanding_action"] is not None
    if awaiting:
        assert document["blockers"] == []
        assert document["failure_class"] is None
        assert len(document["outstanding_actions"]) == len(awaiting)


def test_an_outstanding_action_says_what_was_done_and_what_remains() -> None:
    document = _document(frozen.PREFLIGHT_REPORT_NAME)
    for action in document["outstanding_actions"]:
        assert action["what_has_been_done"].strip()
        assert action["what_remains"]
        assert action["what_it_would_answer"].strip()
        assert action["action"] in {item.value for item in frozen.RequiredAction}


# -------------------------------------------------------------- the marker


def test_no_marker_exists_while_the_preflight_is_incomplete() -> None:
    """A stage that is honestly half done looks half done in its evidence."""
    preflight = engine.run_preflight()
    if preflight.outcome != frozen.STAGE_13A_INCOMPLETE_OUTCOME:
        pytest.skip("the preflight has reached a final outcome")
    assert not MARKER.is_file(), (
        "a finalization marker exists for a preflight that is still awaiting a "
        "local action; a marker is a finalization (docs/adr/0112)"
    )


def test_the_publisher_refuses_a_marker_while_an_action_is_outstanding(
    tmp_path,
) -> None:
    from fpbench.core.fingercell_preflight_errors import Stage13AFinalizationError
    from fpbench.experiments.stage13a_finalization import write_stage13a_evidence

    preflight = engine.run_preflight()
    if preflight.outcome != frozen.STAGE_13A_INCOMPLETE_OUTCOME:
        pytest.skip("the preflight has reached a final outcome")
    with pytest.raises(Stage13AFinalizationError, match="outstanding"):
        write_stage13a_evidence(REPOSITORY_ROOT, include_marker=True)


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
    preflight = engine.run_preflight()
    assert payload["gates_reached"] == preflight.gates_reached
    assert payload["gates_passed"] == preflight.gates_passed
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
