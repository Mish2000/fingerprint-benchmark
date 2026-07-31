"""The rule: both SELF comparisons must match, and "unknown" is not "failed".

The truth table is nine cells, and eight of them are obvious. The interesting
one is ``NON_MATCH + UNDECIDABLE``, which is ``INELIGIBLE`` rather than
``UNDETERMINED`` — because one side is already known to have failed, and no
outcome on the other side could rescue "both matched". Its mirror,
``MATCH + UNDECIDABLE``, is ``UNDETERMINED``: that unit might have qualified,
and nobody measured whether it did.

Getting that asymmetry backwards in either direction would quietly change which
comparisons a conditional report covers (docs/adr/0023).
"""

from __future__ import annotations

import pytest

from fpbench.core.eligibility_models import eligibility_status_of
from fpbench.core.enums import (
    DecisionValue,
    ProtocolStage,
    SelfEligibilityReason,
    SelfEligibilityStatus,
)
from fpbench.core.errors import EligibilityIntegrityError
from fpbench.decisions import apply_decision_profile
from fpbench.eligibility import (
    SelfIndependenceRequirement,
    derive_self_eligibility,
    verify_eligibility_set,
)
from decisionworld import build_decision_world, extraction_failure
from runworld import research_provenance

pytestmark = pytest.mark.decisions

MATCH = DecisionValue.MATCH
NON_MATCH = DecisionValue.NON_MATCH
UNDECIDABLE = None


def test_self_independence_metadata_is_deeply_immutable():
    requirement = SelfIndependenceRequirement(required_metadata={"count": "2"})
    with pytest.raises(TypeError):
        requirement.required_metadata["count"] = "1"  # type: ignore[index]


# ------------------------------------------------------------ the truth table


@pytest.mark.parametrize(
    "plain, roll, status, reasons",
    [
        (
            MATCH,
            MATCH,
            SelfEligibilityStatus.ELIGIBLE,
            {SelfEligibilityReason.BOTH_SELF_MATCH},
        ),
        (
            NON_MATCH,
            MATCH,
            SelfEligibilityStatus.INELIGIBLE,
            {SelfEligibilityReason.PLAIN_SELF_NON_MATCH},
        ),
        (
            MATCH,
            NON_MATCH,
            SelfEligibilityStatus.INELIGIBLE,
            {SelfEligibilityReason.ROLL_SELF_NON_MATCH},
        ),
        (
            NON_MATCH,
            NON_MATCH,
            SelfEligibilityStatus.INELIGIBLE,
            {
                SelfEligibilityReason.PLAIN_SELF_NON_MATCH,
                SelfEligibilityReason.ROLL_SELF_NON_MATCH,
            },
        ),
        (
            MATCH,
            UNDECIDABLE,
            SelfEligibilityStatus.UNDETERMINED,
            {SelfEligibilityReason.ROLL_SELF_UNDECIDABLE},
        ),
        (
            UNDECIDABLE,
            MATCH,
            SelfEligibilityStatus.UNDETERMINED,
            {SelfEligibilityReason.PLAIN_SELF_UNDECIDABLE},
        ),
        (
            UNDECIDABLE,
            UNDECIDABLE,
            SelfEligibilityStatus.UNDETERMINED,
            {
                SelfEligibilityReason.PLAIN_SELF_UNDECIDABLE,
                SelfEligibilityReason.ROLL_SELF_UNDECIDABLE,
            },
        ),
        (
            NON_MATCH,
            UNDECIDABLE,
            SelfEligibilityStatus.INELIGIBLE,
            {
                SelfEligibilityReason.PLAIN_SELF_NON_MATCH,
                SelfEligibilityReason.ROLL_SELF_UNDECIDABLE,
            },
        ),
        (
            UNDECIDABLE,
            NON_MATCH,
            SelfEligibilityStatus.INELIGIBLE,
            {
                SelfEligibilityReason.PLAIN_SELF_UNDECIDABLE,
                SelfEligibilityReason.ROLL_SELF_NON_MATCH,
            },
        ),
    ],
)
def test_the_rule(plain, roll, status, reasons):
    actual_status, actual_reasons = eligibility_status_of(plain=plain, roll=roll)
    assert actual_status is status
    assert set(actual_reasons) == reasons


def test_only_a_double_match_is_eligible():
    for plain in (MATCH, NON_MATCH, UNDECIDABLE):
        for roll in (MATCH, NON_MATCH, UNDECIDABLE):
            status, _ = eligibility_status_of(plain=plain, roll=roll)
            eligible = status is SelfEligibilityStatus.ELIGIBLE
            assert eligible == (plain is MATCH and roll is MATCH)


def test_an_undecidable_is_never_treated_as_a_non_match():
    """If it were, MATCH + UNDECIDABLE would be INELIGIBLE. It is not."""
    status, _ = eligibility_status_of(plain=MATCH, roll=UNDECIDABLE)
    assert status is SelfEligibilityStatus.UNDETERMINED


# ------------------------------------------------------------- derivation


def _derive(world):
    decision_set = apply_decision_profile(
        **world.decisions_kwargs(), derivation_software=research_provenance()
    )
    eligibility = derive_self_eligibility(
        run=world.run,
        units=world.units,
        decisions=decision_set.by_job(),
        decision_set=decision_set.manifest,
        pair_manifest_hash=world.pair_manifest_hash,
    )
    return decision_set, eligibility


def test_the_default_script_makes_every_unit_eligible(tmp_path):
    world = build_decision_world(tmp_path)
    _, eligibility = _derive(world)
    assert len(eligibility.records) == len(world.units)
    assert all(record.is_eligible for record in eligibility.records)


def test_a_failing_roll_self_makes_its_unit_ineligible(tmp_path):
    """One finger below threshold in one impression, and only that one."""
    targets: list[str] = []

    def score_for(pair):
        if pair.protocol_stage is ProtocolStage.ROLL_SELF and not targets:
            targets.append(str(pair.pair_id))
        if (
            pair.protocol_stage is ProtocolStage.ROLL_SELF
            and str(pair.pair_id) == targets[0]
        ):
            return 12.0
        from decisionworld import DEFAULT_SCORES

        return DEFAULT_SCORES[pair.protocol_stage]

    world = build_decision_world(tmp_path, score_for=score_for)
    _, eligibility = _derive(world)

    ineligible = [r for r in eligibility.records if not r.is_eligible]
    assert len(ineligible) == 1
    assert ineligible[0].status is SelfEligibilityStatus.INELIGIBLE
    assert SelfEligibilityReason.ROLL_SELF_NON_MATCH in ineligible[0].reasons
    assert ineligible[0].roll_self_decision is NON_MATCH
    assert ineligible[0].plain_self_decision is MATCH


def test_a_failed_plain_self_makes_its_unit_undetermined(tmp_path):
    seen: list[str] = []

    def failure_for(pair):
        if pair.protocol_stage is ProtocolStage.PLAIN_SELF and not seen:
            seen.append(str(pair.pair_id))
            return extraction_failure()
        return None

    world = build_decision_world(tmp_path, failure_for=failure_for)
    _, eligibility = _derive(world)

    undetermined = [
        r
        for r in eligibility.records
        if r.status is SelfEligibilityStatus.UNDETERMINED
    ]
    assert len(undetermined) == 1
    assert undetermined[0].plain_self_decision is None
    assert (
        SelfEligibilityReason.PLAIN_SELF_UNDECIDABLE in undetermined[0].reasons
    )


def test_every_unit_gets_a_record_including_the_failing_ones(tmp_path):
    """An eligibility set that only described the fingers that worked would be
    a biased description of the protocol."""

    def failure_for(pair):
        if pair.protocol_stage is ProtocolStage.ROLL_SELF:
            return extraction_failure()
        return None

    world = build_decision_world(tmp_path, failure_for=failure_for)
    _, eligibility = _derive(world)
    assert len(eligibility.records) == len(world.units)
    assert all(
        record.status is SelfEligibilityStatus.UNDETERMINED
        for record in eligibility.records
    )


def test_eligibility_is_derived_only_from_the_two_self_decisions(tmp_path):
    """Moving the mated score across the threshold changes no verdict."""
    from decisionworld import DEFAULT_SCORES

    def low_mated(pair):
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED:
            return 1.0
        return DEFAULT_SCORES[pair.protocol_stage]

    high = build_decision_world(tmp_path / "high")
    low = build_decision_world(tmp_path / "low", score_for=low_mated)

    _, high_eligibility = _derive(high)
    _, low_eligibility = _derive(low)

    assert [r.status for r in high_eligibility.records] == [
        r.status for r in low_eligibility.records
    ]


def test_the_eligibility_set_names_the_decision_set_it_came_from(tmp_path):
    world = build_decision_world(tmp_path)
    decision_set, eligibility = _derive(world)
    assert (
        eligibility.manifest.decision_set_fingerprint
        == decision_set.manifest.decision_set_fingerprint
    )
    assert (
        eligibility.manifest.decision_profile_fingerprint
        == world.profile.profile_fingerprint
    )


def test_a_different_threshold_produces_a_different_eligibility_set(tmp_path):
    from decisionworld import documented_profile_for

    world = build_decision_world(tmp_path)
    first_decisions, first = _derive(world)

    strict = documented_profile_for(world.run, threshold="46")
    strict_decisions = apply_decision_profile(
        **{**world.decisions_kwargs(), "profile": strict},
        derivation_software=research_provenance(),
    )
    second = derive_self_eligibility(
        run=world.run,
        units=world.units,
        decisions=strict_decisions.by_job(),
        decision_set=strict_decisions.manifest,
        pair_manifest_hash=world.pair_manifest_hash,
    )

    # ROLL SELF scores 45, so a threshold of 46 disqualifies every unit.
    assert all(record.is_eligible for record in first.records)
    assert not any(record.is_eligible for record in second.records)
    assert (
        first.manifest.eligibility_set_id != second.manifest.eligibility_set_id
    )


def test_the_manifest_carries_no_outcome_counts(tmp_path):
    world = build_decision_world(tmp_path)
    _, eligibility = _derive(world)
    fields = set(type(eligibility.manifest).__dataclass_fields__)
    forbidden = {"eligible_count", "ineligible_count", "undetermined_count"}
    assert forbidden & fields == set()


# ------------------------------------------------------------ verification


def test_a_freshly_derived_set_verifies(tmp_path):
    world = build_decision_world(tmp_path)
    decision_set, eligibility = _derive(world)
    verify_eligibility_set(
        manifest=eligibility.manifest,
        records=eligibility.records,
        units=world.units,
        decisions=decision_set.by_job(),
        decision_set=decision_set.manifest,
        pair_manifest_hash=world.pair_manifest_hash,
    )


def test_a_verdict_that_does_not_follow_is_caught(tmp_path):
    from types import SimpleNamespace

    from fpbench.core.eligibility_models import eligibility_record_hash

    world = build_decision_world(tmp_path)
    decision_set, eligibility = _derive(world)

    records = list(eligibility.records)
    original = records[0]
    fields = {
        name: getattr(original, name)
        for name in type(original).__dataclass_fields__
        if name != "eligibility_record_hash"
    }
    fields["status"] = SelfEligibilityStatus.INELIGIBLE
    fields["reasons"] = (SelfEligibilityReason.PLAIN_SELF_NON_MATCH,)
    probe = SimpleNamespace(**fields)
    # The model refuses to build a verdict that contradicts its own decisions,
    # which is the first line of defence; construct it the hard way to reach the
    # verifier.
    with pytest.raises(ValueError, match="does not follow"):
        type(original)(
            eligibility_record_hash=eligibility_record_hash(probe), **fields
        )


def test_a_set_over_the_wrong_units_is_caught(tmp_path):
    world = build_decision_world(tmp_path)
    decision_set, eligibility = _derive(world)
    with pytest.raises(EligibilityIntegrityError, match="verdicts for"):
        verify_eligibility_set(
            manifest=eligibility.manifest,
            records=eligibility.records,
            units=world.units[:-1],
            decisions=decision_set.by_job(),
            decision_set=decision_set.manifest,
            pair_manifest_hash=world.pair_manifest_hash,
        )


def test_a_set_citing_another_pair_manifest_is_caught(tmp_path):
    world = build_decision_world(tmp_path)
    decision_set, eligibility = _derive(world)
    with pytest.raises(EligibilityIntegrityError, match="pair-manifest hash"):
        verify_eligibility_set(
            manifest=eligibility.manifest,
            records=eligibility.records,
            units=world.units,
            decisions=decision_set.by_job(),
            decision_set=decision_set.manifest,
            pair_manifest_hash="a" * 64,
        )


def test_a_set_citing_another_run_is_caught(tmp_path):
    from dataclasses import replace

    world = build_decision_world(tmp_path)
    decision_set, eligibility = _derive(world)
    forged = replace(eligibility.manifest, run_id="run_forged")
    with pytest.raises(EligibilityIntegrityError, match="run id"):
        verify_eligibility_set(
            manifest=forged,
            records=eligibility.records,
            units=world.units,
            decisions=decision_set.by_job(),
            decision_set=decision_set.manifest,
            pair_manifest_hash=world.pair_manifest_hash,
        )
