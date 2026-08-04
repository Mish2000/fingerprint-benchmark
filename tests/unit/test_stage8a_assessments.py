from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.modern_matcher_models import QualificationStatus
from fpbench.core.serialization import to_plain
from fpbench.modern_matchers.acquisition import load_acquisition_manifests
from fpbench.modern_matchers.assessments import build_frozen_qualification_reports
from fpbench.modern_matchers.loading import qualification_report_from_plain
from fpbench.modern_matchers.registry import load_candidate_registry
from fpbench.modern_matchers.verify import ensure_publishable
from fpbench.core.errors import Stage8AFinalizationError

pytestmark = pytest.mark.stage8a_contract

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    REPOSITORY_ROOT
    / "configs"
    / "modern-matchers"
    / "stage8a_candidates_v1.yaml"
)
MANIFEST_DIRECTORY = (
    REPOSITORY_ROOT / "integrations" / "modern-matchers" / "manifests"
)
EVIDENCE_DIRECTORY = (
    REPOSITORY_ROOT / "evidence" / "stage8a-modern-matcher-selection"
)


def _reports():
    registry = load_candidate_registry(REGISTRY_PATH)
    manifests = load_acquisition_manifests(
        MANIFEST_DIRECTORY, registry=registry
    )
    expected = build_frozen_qualification_reports(
        registry=registry, manifests=manifests
    )
    stored = tuple(
        qualification_report_from_plain(
            json.loads(
                (
                    EVIDENCE_DIRECTORY
                    / f"qualification-{candidate.candidate_id}.json"
                ).read_text(encoding="utf-8")
            )
        )
        for candidate in registry.candidates
    )
    return expected, stored


def test_committed_qualifications_are_exactly_the_frozen_inspections() -> None:
    expected, stored = _reports()
    assert [to_plain(item) for item in stored] == [
        to_plain(item) for item in expected
    ]


def test_paper_only_candidates_are_incomplete_and_flx_is_license_blocked() -> None:
    _expected, reports = _reports()
    by_id = {item.candidate_id: item for item in reports}
    assert by_id["afr_net_official_artifact"].qualification_status is (
        QualificationStatus.ARTIFACT_INCOMPLETE
    )
    assert by_id["mgvit_official_artifact"].qualification_status is (
        QualificationStatus.ARTIFACT_INCOMPLETE
    )
    assert by_id["flx_fixed_length_extractor"].qualification_status is (
        QualificationStatus.LICENSE_BLOCKED
    )


def test_failed_static_inspection_prevented_every_runtime_probe() -> None:
    _expected, reports = _reports()
    for report in reports:
        assert not report.static_inspection_passed
        assert not report.execution_attempted
        assert not report.smoke_qualification_passed
        assert not report.contract_qualification_passed
        assert not report.determinism_report.tested
        assert not report.operational_report.measured
        assert not report.raw_score_ready
        assert not report.decision_path_ready


def test_flx_static_identity_keeps_both_branches_and_direct_score_semantics() -> None:
    _expected, reports = _reports()
    report = next(
        item for item in reports if item.candidate_id == "flx_fixed_length_extractor"
    )
    assert report.representation_profile is not None
    assert report.representation_profile.representation_shape == (512,)
    assert {branch.branch_id: branch.shape for branch in report.representation_profile.branches} == {
        "texture": (256,),
        "minutia": (256,),
    }
    assert all(
        branch.included_in_final_score
        for branch in report.representation_profile.branches
    )
    assert report.score_profile is not None
    assert "dot product" in report.score_profile.similarity_function
    assert report.score_profile.score_direction == "higher_is_more_similar"
    assert not report.score_profile.hidden_threshold


@pytest.mark.parametrize(
    "local_path",
    (
        "/root/private",
        "/var/lib/model",
        "/etc/secret",
        "/opt/runtime",
        "/שלום/פרטי",
        "//server/share/model",
        "/",
    ),
)
def test_publication_rejects_every_general_posix_absolute_path(
    local_path: str,
) -> None:
    with pytest.raises(Stage8AFinalizationError, match="absolute path"):
        ensure_publishable({"note": f"local file: {local_path}"})


def test_publication_does_not_misclassify_https_sources_as_local_paths() -> None:
    ensure_publishable(
        {
            "source": "https://example.test/release/model.pyt",
            "scheme": "profile://portable-identifier",
        }
    )
