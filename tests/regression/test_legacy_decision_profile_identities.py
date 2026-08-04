"""The two published SourceAFIS profiles, pinned by their exact digests.

Stage 7D adds a second decision-profile grammar. The one thing it may not do is
change the first, because four decision sets, four eligibility sets, four metric
sets and every receipt and finalization marker above them cite fingerprints
computed under it. A schema bump that "just adds a field" would move all of
those at once, and nothing downstream would notice — the artefacts would simply
stop verifying, or worse, verify against a newly computed identity.

So the check is the crudest one available: load the committed YAML, and compare
the resulting fingerprint with the literal 64 characters that
``workspace/results/*/decisions/*/profile.json`` has held since stage 5A and
stage 6B (docs/adr/0055, spec sections 15 and 19).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.core.decision_models import ThresholdComparator, ThresholdOrigin
from fpbench.core.enums import ScoreDirection
from fpbench.core.errors import DecisionProfileError
from fpbench.decisions import load_decision_profile

pytestmark = [pytest.mark.decisions, pytest.mark.stage7d_contract]

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = REPOSITORY_ROOT / "configs" / "decisions"

#: The SourceAFIS Java 3.18.1 descriptor fingerprint, unchanged since stage 4A
#: and re-verified at every stage since.
SOURCEAFIS_ALGORITHM_FINGERPRINT = (
    "5a1784faae1e82c12c374e050fcd6cfd41aa25b7a9ade3905d099df2e06a9531"
)

#: profile file -> the fingerprint the published artefacts cite.
PUBLISHED_PROFILES: dict[str, str] = {
    "sourceafis_java_3_18_1_documented_40_v1.yaml": (
        "02be9e07d28522b657f4fed3ee930b4c117573403926ad919b745274d6b6de4c"
    ),
    "sourceafis_java_3_18_1_documented_40_canonical500_v1.yaml": (
        "a9550e9dfd0ce54f6538d395a32c5e354db3bd4a9cbafff4cf0268e88fc78b75"
    ),
}


@pytest.mark.parametrize("filename, fingerprint", sorted(PUBLISHED_PROFILES.items()))
def test_a_published_profile_still_fingerprints_to_its_published_identity(
    filename, fingerprint
):
    profile = load_decision_profile(
        CONFIGS / filename,
        algorithm_fingerprint=SOURCEAFIS_ALGORITHM_FINGERPRINT,
    )
    assert profile.profile_fingerprint == fingerprint


@pytest.mark.parametrize("filename", sorted(PUBLISHED_PROFILES))
def test_a_published_profile_is_read_as_schema_one(filename):
    """Absence of ``schema_version`` means 1, and 1 is what these files are."""
    profile = load_decision_profile(
        CONFIGS / filename,
        algorithm_fingerprint=SOURCEAFIS_ALGORITHM_FINGERPRINT,
    )
    assert profile.schema_version == "1"
    assert profile.comparator is ThresholdComparator.GREATER_THAN_OR_EQUAL
    assert profile.threshold == "40"
    assert profile.score_direction is ScoreDirection.HIGHER_IS_BETTER
    assert profile.origin is ThresholdOrigin.DOCUMENTED_NATIVE
    assert profile.calibration_performed is False


@pytest.mark.parametrize("filename", sorted(PUBLISHED_PROFILES))
def test_the_committed_files_declare_no_schema_version(filename):
    """The files themselves are not to be touched, so nor is their text.

    Adding ``schema_version: "1"`` would be a no-op semantically and would still
    be an edit to a file that four published derivations were produced from.
    """
    text = (CONFIGS / filename).read_text(encoding="utf-8")
    assert "schema_version" not in text
    assert "claims:" not in text
    assert "source_statement_kind" not in text


def test_a_schema_one_file_that_grew_a_claims_block_is_refused(tmp_path):
    """A claims block outside the fingerprint would be an unbacked assertion."""
    source = (CONFIGS / "sourceafis_java_3_18_1_documented_40_v1.yaml").read_text(
        encoding="utf-8"
    )
    path = tmp_path / "tampered.yaml"
    path.write_text(source + "\nclaims:\n  calibrated_fmr: false\n", encoding="utf-8")
    with pytest.raises(DecisionProfileError, match="schema 2"):
        load_decision_profile(
            path, algorithm_fingerprint=SOURCEAFIS_ALGORITHM_FINGERPRINT
        )


def test_a_profile_bound_to_a_different_build_is_a_different_profile():
    """The algorithm fingerprint is inside the profile fingerprint, still."""
    profile = load_decision_profile(
        CONFIGS / "sourceafis_java_3_18_1_documented_40_v1.yaml",
        algorithm_fingerprint="b" * 64,
    )
    assert profile.profile_fingerprint != PUBLISHED_PROFILES[
        "sourceafis_java_3_18_1_documented_40_v1.yaml"
    ]
