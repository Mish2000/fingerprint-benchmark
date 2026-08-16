"""The frozen Stage 17A contract: one question, asked before anything is built.

No package, no OpenCV, no network and no dataset. The score-contract gate is
exercised against synthetic module sources written inline, so the *rule* is under
test rather than the one verdict it happened to produce: a function that returns
its ratio passes, a function that prints it does not, and a function that returns
a value only after applying a threshold is not the same thing as one that returns
a raw scalar.
"""

from __future__ import annotations

import json
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from fpbench.core.errors import FpbenchError
from fpbench.core.stage17a_errors import (
    Stage17AArtifactIdentityError,
    Stage17AError,
    Stage17AFinalizationError,
    Stage17AIdentityError,
    Stage17ARouteClosureError,
    Stage17AScoreContractError,
)
from fpbench.experiments import stage17a_acquire as acquire
from fpbench.experiments import stage17a_finalization as finalization
from fpbench.experiments import stage17a_identity as frozen
from fpbench.experiments import stage17a_score_contract as gate

pytestmark = pytest.mark.stage17a_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------- the vocabulary


def test_every_error_descends_from_the_project_root() -> None:
    for error in (
        Stage17AError,
        Stage17AIdentityError,
        Stage17AArtifactIdentityError,
        Stage17AScoreContractError,
        Stage17ARouteClosureError,
        Stage17AFinalizationError,
    ):
        assert issubclass(error, Stage17AError)
        assert issubclass(error, FpbenchError)


def test_the_error_module_is_a_sibling_and_not_an_edit_of_an_earlier_one() -> None:
    source = (REPOSITORY_ROOT / "src/fpbench/core/stage17a_errors.py").read_text(
        encoding="utf-8"
    )
    for earlier in ("class Stage15A", "class Stage16A"):
        assert earlier not in source


# --------------------------------------------------------------- the identity


def test_the_candidate_is_pinned_by_version_and_two_digests() -> None:
    assert frozen.CANDIDATE_ID == "fingerprintmatcher_1_0_6"
    assert frozen.PACKAGE_REQUIREMENT == "fingerprintMatcher==1.0.6"
    assert frozen.LICENSE == "MIT"
    assert frozen.RUNTIME_ARTIFACT_SHA256 == (
        "4491a191b6f874acdfe287fb47bff788d6b01c88e71d4c247e3fd7baceb2e5b2"
    )
    assert frozen.SOURCE_ARTIFACT_SHA256 == (
        "50692faf63ca8bccb83ea8a2adfac7284e389b05bc19347c86a513a85f868411"
    )
    assert len(frozen.MODULE_SHA256) == 64


def test_the_distribution_is_the_authority_and_the_repository_is_not() -> None:
    assert frozen.AUTHORITY_IS_THE_DISTRIBUTION is True
    assert frozen.WHY_NOT_THE_REPOSITORY.strip()
    assert acquire.acquire.__doc__
    for url in (locator for _, locator in acquire.PYPI_FILES.values()):
        assert url.startswith("https://files.pythonhosted.org/")
    assert not any("github" in url for _, url in acquire.PYPI_FILES.values())


def test_seven_gates_two_outcomes_and_three_states() -> None:
    assert frozen.GATE_ORDER == ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
    assert set(frozen.GATES) == set(frozen.GATE_ORDER)
    assert frozen.GATE_STATES == ("PASS", "FAIL", "NOT_REACHED")
    assert set(frozen.OUTCOMES) == {
        frozen.OUTCOME_COMPLETE,
        frozen.OUTCOME_SCORE_CONTRACT_FAIL,
    }


def test_the_stop_conditions_name_the_threshold_only_case() -> None:
    assert "BOOLEAN_OR_THRESHOLD_ONLY_OUTPUT" in frozen.IMMEDIATE_STOP_CONDITIONS
    assert "SCORE_DIRECTION_NOT_PROVABLE" in frozen.IMMEDIATE_STOP_CONDITIONS
    assert len(frozen.SCORE_CONTRACT_QUESTIONS) == 2


def test_evidence_is_exactly_five_documents() -> None:
    assert len(frozen.EVIDENCE_DOCUMENTS) == 5
    assert frozen.EVIDENCE_DOCUMENTS[0] == "README.md"
    assert frozen.EVIDENCE_DOCUMENTS[-1] == frozen.STAGE_17A_FINALIZATION_NAME
    assert frozen.EVIDENCE_DIRECTORY.as_posix() == (
        "evidence/stage17a-fingerprintmatcher"
    )


# ------------------------------------------- the gate, against synthetic modules


def _stage_module(root: Path, source: str) -> Path:
    """Write a synthetic sdist and wheel carrying ``source`` as the module."""
    artifacts = root / gate.STORE_DIRECTORY / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = source.encode("utf-8")

    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(f"pkg-1.0.6/{frozen.MODULE_NAME}")
        info.size = len(payload)
        archive.addfile(info, BytesIO(payload))
    (artifacts / frozen.SOURCE_ARTIFACT_NAME).write_bytes(buffer.getvalue())

    wheel = artifacts / frozen.RUNTIME_ARTIFACT_NAME
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(frozen.MODULE_NAME, payload)
    return artifacts


def _read(root: Path, source: str) -> gate.ScoreContract:
    _stage_module(root, source)
    return gate.read_score_contract(repository_root=None)


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FPBENCH_THIRD_PARTY_ROOT", str(tmp_path))
    return tmp_path


_PRINTING = '''
class fingerprintMatcher:
    def match_fingerprints(self, img1_path, img2_path):
        """Doc.

        Returns:
        None
        """
        match_ratio = len(match_points) / keypoints_count
        if match_ratio > 0.95:
            print("matched")
        else:
            print("not matched")
'''

_RETURNING = '''
class fingerprintMatcher:
    def match_fingerprints(self, img1_path, img2_path):
        """Doc.

        Returns:
        float
        """
        match_ratio = len(match_points) / keypoints_count
        return match_ratio
'''

_RETURNING_A_DECISION = '''
class fingerprintMatcher:
    def match_fingerprints(self, img1_path, img2_path):
        match_ratio = len(match_points) / keypoints_count
        if match_ratio > 0.95:
            return True
        return False
'''


def test_a_function_that_only_prints_fails_the_gate(store: Path) -> None:
    contract = _read(store, _PRINTING)
    assert contract.returns_native_scalar is False
    assert contract.direction_is_provable is False
    assert contract.gate_state == "FAIL"
    assert contract.blocker == "BOOLEAN_OR_THRESHOLD_ONLY_OUTPUT"
    assert contract.docstring_returns == "None"
    assert contract.internal_thresholds == ("match_ratio > 0.95",)
    assert contract.ratio_is_returned is False


def test_a_function_that_returns_its_ratio_passes(store: Path) -> None:
    contract = _read(store, _RETURNING)
    assert contract.returns_native_scalar is True
    assert contract.direction_is_provable is True
    assert contract.gate_state == "PASS"
    assert contract.blocker is None
    assert contract.ratio_is_returned is True
    assert contract.internal_thresholds == ()


def test_a_function_returning_a_thresholded_decision_is_not_a_raw_score(
    store: Path,
) -> None:
    """It returns a value, so the naive check would pass — the threshold is what matters."""
    contract = _read(store, _RETURNING_A_DECISION)
    assert contract.returns_with_a_value > 0
    assert contract.internal_thresholds == ("match_ratio > 0.95",)
    assert contract.ratio_is_returned is False


def test_a_module_without_the_entry_point_is_refused(store: Path) -> None:
    with pytest.raises(Stage17AScoreContractError):
        _read(store, "class fingerprintMatcher:\n    pass\n")


def test_an_absent_artifact_is_not_reached_rather_than_failed(store: Path) -> None:
    contract = gate.read_score_contract(repository_root=None)
    assert contract.found is False
    assert contract.gate_state == "NOT_REACHED"


def test_the_two_unhandled_hazards_are_reported_as_observations(store: Path) -> None:
    source = _PRINTING.replace(
        "        match_ratio",
        "        for p, q in matches:\n            pass\n        match_ratio",
    )
    contract = _read(store, source)
    hazards = {h["where"] for h in contract.unhandled_hazards}
    assert "for p, q in matches" in hazards
    assert "len(match_points) / keypoints_count" in hazards
    for hazard in contract.unhandled_hazards:
        assert hazard["hazard"] == "UNHANDLED_IMPLEMENTATION_EXCEPTION"


# ---------------------------------------------------------------- the marker


def _documents(*, score_state: str) -> dict:
    return {
        "artifact_document": {"gate_state": "PASS"},
        "score_document": {
            "gate_state": score_state,
            "blocker": None if score_state == "PASS" else
            "BOOLEAN_OR_THRESHOLD_ONLY_OUTPUT",
            "returns_native_scalar_before_decision": score_state == "PASS",
            "score_direction_provable_from_source": score_state == "PASS",
            "score_direction": None,
            "findings": {"internal_decision_thresholds": []},
        },
        "route_document": {"gate_state": "NOT_REACHED"},
    }


def test_a_failed_score_contract_cannot_establish_algorithm_5() -> None:
    marker = finalization.build_stage17a_finalization(
        repository_root=REPOSITORY_ROOT, **_documents(score_state="FAIL")
    )
    assert marker["outcome"] == frozen.OUTCOME_SCORE_CONTRACT_FAIL
    assert marker["algorithm_5_established"] is False
    assert marker["opens_common_calibration"] is False
    assert marker["reopens_algorithm_5_search"] is True
    assert marker["gate_reached_last"] == frozen.GATES["G2"]
    assert marker["score_direction"] is None


def test_a_failed_contract_may_not_publish_a_score_direction() -> None:
    documents = _documents(score_state="FAIL")
    documents["score_document"]["score_direction"] = "HIGHER_MORE_SIMILAR"
    with pytest.raises(Stage17AFinalizationError):
        finalization.build_stage17a_finalization(
            repository_root=REPOSITORY_ROOT, **documents
        )


def test_a_complete_outcome_is_refused_over_an_unreached_gate() -> None:
    with pytest.raises(Stage17AFinalizationError):
        finalization.build_stage17a_finalization(
            repository_root=REPOSITORY_ROOT, **_documents(score_state="PASS")
        )


def test_nothing_was_installed_executed_or_reconstructed() -> None:
    marker = finalization.build_stage17a_finalization(
        repository_root=REPOSITORY_ROOT, **_documents(score_state="FAIL")
    )
    for denial in (
        "package_installed",
        "package_executed",
        "score_reconstructed_by_fpbench",
        "stdout_parsed_for_a_score",
        "upstream_function_reimplemented",
        "threshold_produced",
        "calibration_performed",
        "metrics_produced",
        "prior_algorithm_scores_consulted",
        "third_party_bytes_added_to_git",
    ):
        assert marker[denial] is False, denial
    assert marker["sd300_images_opened"] == 0
    assert marker["stored_outcomes"] == 0


def test_the_marker_fingerprint_covers_everything_but_itself() -> None:
    marker = finalization.build_stage17a_finalization(
        repository_root=REPOSITORY_ROOT, **_documents(score_state="FAIL")
    )
    recomputed = finalization.stage17a_finalization_fingerprint(marker)
    assert recomputed == marker["stage_17a_finalization_fingerprint"]
    assert len(recomputed) == 64


def test_the_source_fingerprint_covers_every_file_that_decides_the_outcome() -> None:
    for relative in finalization._SOURCE_FILES:
        assert (REPOSITORY_ROOT / relative).is_file(), relative
    assert len(finalization.stage17a_source_fingerprint(REPOSITORY_ROOT)) == 64


def test_the_predecessor_markers_are_bound_by_fingerprint() -> None:
    bound = {record["stage"]: record for record in frozen.BOUND_MARKERS}
    assert set(bound) == {"16A", "15A", "8E"}
    for record in bound.values():
        assert len(record["finalization_fingerprint"]) == 64


def test_a_document_carrying_a_real_threshold_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / frozen.EVIDENCE_DIRECTORY
    directory.mkdir(parents=True)
    (directory / "x.json").write_text(json.dumps({"threshold": 0.95}), encoding="utf-8")
    with pytest.raises(Stage17AFinalizationError):
        finalization._require_no_forbidden_published_data(directory)
