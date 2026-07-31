"""What each view contains, and — for the impostor set — what it refuses to be.

The conditional view is where the protocol's requirement becomes a file, so
most of these tests are about one boolean per row: is this comparison included,
and if not, exactly why. The rows themselves never disappear; a view that
dropped its exclusions would be smaller and unauditable.

The non-mated tests are about naming. The set is 1,500 same-subject,
different-finger pairs at a fixed cyclic shift over 50 people. It is a good
sanity check and it is not a false-match rate, and the view is required to keep
saying so in a field that reaches its own fingerprint (docs/adr/0025).
"""

from __future__ import annotations

import pytest

from fpbench.core.enums import (
    DecisionValue,
    ProtocolStage,
    SelfEligibilityStatus,
)
from fpbench.core.errors import EvaluationViewIntegrityError, StorageError
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
    ExclusionReason,
    evaluation_view_id,
    require_honest_view_name,
)
from fpbench.decisions import apply_decision_profile
from fpbench.eligibility import derive_self_eligibility
from fpbench.evaluation import (
    build_mated_conditional_view,
    build_mated_unconditional_view,
    build_non_mated_sanity_view,
    verify_evaluation_view,
)
from decisionworld import DEFAULT_SCORES, build_decision_world, extraction_failure
from runworld import research_provenance

pytestmark = pytest.mark.decisions


def _chain(world):
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


def _views(world, decision_set, eligibility):
    common = {
        "run": world.run,
        "plan": world.plan,
        "pairs": world.pairs,
        "decisions": decision_set.by_job(),
        "decision_set": decision_set.manifest,
        "pair_manifest_hash": world.pair_manifest_hash,
    }
    return (
        build_mated_unconditional_view(**common),
        build_mated_conditional_view(
            **common,
            eligibility=eligibility.manifest,
            eligibility_records=eligibility.records,
        ),
        build_non_mated_sanity_view(**common, finger_shift=1),
    )


@pytest.fixture
def world(tmp_path):
    return build_decision_world(tmp_path)


# ----------------------------------------------------------- unconditional


def test_the_unconditional_view_holds_every_mated_pair(world):
    decision_set, eligibility = _chain(world)
    unconditional, _, _ = _views(world, decision_set, eligibility)

    mated = [
        pair
        for pair in world.run_world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
    ]
    assert unconditional.manifest.total_rows == len(mated)
    assert {entry.pair_id for entry in unconditional.entries} == {
        str(pair.pair_id) for pair in mated
    }


def test_every_unconditional_row_is_included(world):
    decision_set, eligibility = _chain(world)
    unconditional, _, _ = _views(world, decision_set, eligibility)
    assert all(entry.included for entry in unconditional.entries)
    assert all(entry.exclusion_reason is None for entry in unconditional.entries)


def test_the_unconditional_view_cites_no_eligibility(world):
    decision_set, eligibility = _chain(world)
    unconditional, _, _ = _views(world, decision_set, eligibility)
    assert unconditional.manifest.eligibility_set_fingerprint is None
    assert all(entry.eligibility_unit_id is None for entry in unconditional.entries)


def test_a_failed_comparison_stays_in_the_unconditional_view(tmp_path):
    """Whether a failure belongs in a denominator is a metric question."""

    def failure_for(pair):
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED:
            return extraction_failure()
        return None

    world = build_decision_world(tmp_path, failure_for=failure_for)
    decision_set, eligibility = _chain(world)
    unconditional, _, _ = _views(world, decision_set, eligibility)

    assert all(entry.included for entry in unconditional.entries)
    assert all(entry.decision is None for entry in unconditional.entries)


# ------------------------------------------------------------- conditional


def test_the_conditional_view_keeps_every_row(world):
    decision_set, eligibility = _chain(world)
    unconditional, conditional, _ = _views(world, decision_set, eligibility)
    assert conditional.manifest.total_rows == unconditional.manifest.total_rows


def test_all_eligible_means_all_included(world):
    decision_set, eligibility = _chain(world)
    _, conditional, _ = _views(world, decision_set, eligibility)
    assert all(entry.included for entry in conditional.entries)
    assert conditional.included_count == conditional.manifest.total_rows


def test_an_ineligible_unit_excludes_its_pair_with_a_reason(tmp_path):
    targets: list[str] = []

    def score_for(pair):
        if pair.protocol_stage is ProtocolStage.ROLL_SELF and not targets:
            targets.append(str(pair.pair_id))
        if (
            pair.protocol_stage is ProtocolStage.ROLL_SELF
            and str(pair.pair_id) == targets[0]
        ):
            return 1.0
        return DEFAULT_SCORES[pair.protocol_stage]

    world = build_decision_world(tmp_path, score_for=score_for)
    decision_set, eligibility = _chain(world)
    _, conditional, _ = _views(world, decision_set, eligibility)

    excluded = [entry for entry in conditional.entries if not entry.included]
    assert len(excluded) == 1
    assert excluded[0].exclusion_reason == ExclusionReason.SELF_INELIGIBLE
    assert excluded[0].eligibility_status is SelfEligibilityStatus.INELIGIBLE
    # The row is still present and still carries its decision.
    assert excluded[0].decision in (DecisionValue.MATCH, DecisionValue.NON_MATCH)


def test_an_undetermined_unit_excludes_its_pair_for_a_different_reason(tmp_path):
    seen: list[str] = []

    def failure_for(pair):
        if pair.protocol_stage is ProtocolStage.PLAIN_SELF and not seen:
            seen.append(str(pair.pair_id))
            return extraction_failure()
        return None

    world = build_decision_world(tmp_path, failure_for=failure_for)
    decision_set, eligibility = _chain(world)
    _, conditional, _ = _views(world, decision_set, eligibility)

    excluded = [entry for entry in conditional.entries if not entry.included]
    assert len(excluded) == 1
    assert excluded[0].exclusion_reason == ExclusionReason.SELF_UNDETERMINED
    assert excluded[0].eligibility_status is SelfEligibilityStatus.UNDETERMINED


def test_the_conditional_view_does_not_change_the_unconditional_one(tmp_path):
    def score_for(pair):
        if pair.protocol_stage is ProtocolStage.ROLL_SELF:
            return 1.0
        return DEFAULT_SCORES[pair.protocol_stage]

    world = build_decision_world(tmp_path, score_for=score_for)
    decision_set, eligibility = _chain(world)
    unconditional, conditional, _ = _views(world, decision_set, eligibility)

    assert all(entry.included for entry in unconditional.entries)
    assert not any(entry.included for entry in conditional.entries)
    assert unconditional.manifest.total_rows == conditional.manifest.total_rows


def test_the_conditional_view_names_its_eligibility_set(world):
    decision_set, eligibility = _chain(world)
    _, conditional, _ = _views(world, decision_set, eligibility)
    assert (
        conditional.manifest.eligibility_set_fingerprint
        == eligibility.manifest.eligibility_set_fingerprint
    )


def test_moving_one_unit_changes_the_view_fingerprint(tmp_path):
    from decisionworld import documented_profile_for

    world = build_decision_world(tmp_path)
    decision_set, eligibility = _chain(world)
    _, conditional, _ = _views(world, decision_set, eligibility)

    strict = documented_profile_for(world.run, threshold="46")
    strict_decisions = apply_decision_profile(
        **{**world.decisions_kwargs(), "profile": strict},
        derivation_software=research_provenance(),
    )
    strict_eligibility = derive_self_eligibility(
        run=world.run,
        units=world.units,
        decisions=strict_decisions.by_job(),
        decision_set=strict_decisions.manifest,
        pair_manifest_hash=world.pair_manifest_hash,
    )
    _, strict_conditional, _ = _views(world, strict_decisions, strict_eligibility)

    assert (
        conditional.manifest.view_fingerprint
        != strict_conditional.manifest.view_fingerprint
    )


# -------------------------------------------------------------- non-mated


def test_the_non_mated_view_holds_every_impostor_pair(world):
    decision_set, eligibility = _chain(world)
    _, _, non_mated = _views(world, decision_set, eligibility)

    impostors = [
        pair
        for pair in world.run_world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_NON_MATED
    ]
    assert non_mated.manifest.total_rows == len(impostors)
    assert {entry.pair_id for entry in non_mated.entries} == {
        str(pair.pair_id) for pair in impostors
    }


def test_the_non_mated_view_holds_no_mated_pair(world):
    decision_set, eligibility = _chain(world)
    unconditional, _, non_mated = _views(world, decision_set, eligibility)
    mated_ids = {entry.pair_id for entry in unconditional.entries}
    assert mated_ids.isdisjoint({entry.pair_id for entry in non_mated.entries})


def test_the_non_mated_view_applies_no_self_filter(tmp_path):
    def score_for(pair):
        if pair.protocol_stage is ProtocolStage.ROLL_SELF:
            return 1.0
        return DEFAULT_SCORES[pair.protocol_stage]

    world = build_decision_world(tmp_path, score_for=score_for)
    decision_set, eligibility = _chain(world)
    _, _, non_mated = _views(world, decision_set, eligibility)

    assert all(entry.included for entry in non_mated.entries)
    assert non_mated.manifest.eligibility_set_fingerprint is None


def test_the_non_mated_view_records_what_it_is(world):
    decision_set, eligibility = _chain(world)
    _, _, non_mated = _views(world, decision_set, eligibility)
    metadata = non_mated.manifest.policy_metadata
    assert metadata["negative_kind"] == "same_subject_different_finger"
    assert metadata["pairing_strategy"] == "cyclic_finger_shift"
    assert metadata["finger_shift"] == "1"
    assert metadata["closed_set"] == "true"
    assert metadata["purpose"] == "negative_sanity_check"


def test_the_non_mated_view_says_it_is_not_a_false_match_rate(world):
    decision_set, eligibility = _chain(world)
    _, _, non_mated = _views(world, decision_set, eligibility)
    assert non_mated.manifest.policy_metadata["primary_fmr_estimate"] == "false"


def test_no_view_may_be_named_after_a_rate():
    for name in ("plain_roll_non_mated_fmr_v1", "general_fmr_view", "eer_view"):
        with pytest.raises(EvaluationViewIntegrityError, match="would claim"):
            require_honest_view_name(name)


def test_the_three_view_kinds_are_honestly_named():
    for kind in (
        MATED_UNCONDITIONAL_VIEW,
        MATED_CONDITIONAL_VIEW,
        NON_MATED_SANITY_VIEW,
    ):
        require_honest_view_name(kind)


def test_there_is_no_conditional_non_mated_view(world):
    """Spec section 41: filtering impostors needs a rule for two fingers."""
    decision_set, eligibility = _chain(world)
    built = _views(world, decision_set, eligibility)
    kinds = {view.manifest.view_kind for view in built}
    assert kinds == {
        MATED_UNCONDITIONAL_VIEW,
        MATED_CONDITIONAL_VIEW,
        NON_MATED_SANITY_VIEW,
    }


# ------------------------------------------------------------ verification


def test_the_three_views_verify(world):
    decision_set, eligibility = _chain(world)
    unconditional, conditional, non_mated = _views(world, decision_set, eligibility)
    common = {
        "run": world.run,
        "plan": world.plan,
        "pairs": world.pairs,
        "decisions": decision_set.by_job(),
        "decision_set": decision_set.manifest,
        "pair_manifest_hash": world.pair_manifest_hash,
        "non_mated_finger_shift": 1,
    }
    verify_evaluation_view(
        manifest=unconditional.manifest,
        entries=unconditional.entries,
        eligibility=None,
        **common,
    )
    verify_evaluation_view(
        manifest=conditional.manifest,
        entries=conditional.entries,
        eligibility=eligibility.manifest,
        eligibility_records=eligibility.records,
        **common,
    )
    verify_evaluation_view(
        manifest=non_mated.manifest,
        entries=non_mated.entries,
        eligibility=None,
        **common,
    )


def test_a_flipped_inclusion_flag_is_caught(tmp_path):
    from types import SimpleNamespace

    from fpbench.core.evaluation_view_models import evaluation_entry_hash

    world = build_decision_world(tmp_path)
    decision_set, eligibility = _chain(world)
    _, conditional, _ = _views(world, decision_set, eligibility)

    entries = list(conditional.entries)
    original = entries[0]
    fields = {
        name: getattr(original, name)
        for name in type(original).__dataclass_fields__
        if name != "evaluation_entry_hash"
    }
    fields["included"] = False
    fields["exclusion_reason"] = ExclusionReason.SELF_INELIGIBLE
    probe = SimpleNamespace(**fields)
    entries[0] = type(original)(
        evaluation_entry_hash=evaluation_entry_hash(probe), **fields
    )

    with pytest.raises(EvaluationViewIntegrityError, match="eligibility implies"):
        verify_evaluation_view(
            manifest=conditional.manifest,
            entries=tuple(entries),
            run=world.run,
            plan=world.plan,
            pairs=world.pairs,
            decisions=decision_set.by_job(),
            decision_set=decision_set.manifest,
            eligibility=eligibility.manifest,
            eligibility_records=eligibility.records,
            pair_manifest_hash=world.pair_manifest_hash,
            non_mated_finger_shift=1,
        )


def test_an_unconditional_view_that_cites_eligibility_is_caught(world):
    from dataclasses import replace

    decision_set, eligibility = _chain(world)
    unconditional, _, _ = _views(world, decision_set, eligibility)
    forged = replace(
        unconditional.manifest,
        eligibility_set_fingerprint=eligibility.manifest.eligibility_set_fingerprint,
    )
    with pytest.raises(EvaluationViewIntegrityError, match="not conditional"):
        verify_evaluation_view(
            manifest=forged,
            entries=unconditional.entries,
            run=world.run,
            plan=world.plan,
            pairs=world.pairs,
            decisions=decision_set.by_job(),
            decision_set=decision_set.manifest,
            eligibility=None,
            pair_manifest_hash=world.pair_manifest_hash,
            non_mated_finger_shift=1,
        )


def _manifest_for_entries(manifest, entries):
    from dataclasses import replace

    from fpbench.core.evaluation_view_models import (
        evaluation_view_fingerprint,
        evaluation_view_id,
        ordered_entries_hash,
    )

    fingerprint = evaluation_view_fingerprint(
        view_kind=manifest.view_kind,
        policy_id=manifest.policy_id,
        policy_version=manifest.policy_version,
        run_fingerprint=manifest.run_fingerprint,
        result_set_fingerprint=manifest.result_set_fingerprint,
        decision_set_fingerprint=manifest.decision_set_fingerprint,
        eligibility_set_fingerprint=manifest.eligibility_set_fingerprint,
        pair_manifest_hash=manifest.pair_manifest_hash,
        policy_metadata=manifest.policy_metadata,
        entries=entries,
    )
    return replace(
        manifest,
        view_id=evaluation_view_id(manifest.view_kind, fingerprint),
        view_fingerprint=fingerprint,
        total_rows=len(entries),
        ordered_entries_hash=ordered_entries_hash(entries),
    )


def test_a_self_consistently_rehashed_truncated_view_is_caught(world):
    decision_set, eligibility = _chain(world)
    unconditional, _, _ = _views(world, decision_set, eligibility)
    entries = unconditional.entries[:-1]
    forged = _manifest_for_entries(unconditional.manifest, entries)

    with pytest.raises(EvaluationViewIntegrityError, match="exactly the jobs"):
        verify_evaluation_view(
            manifest=forged,
            entries=entries,
            run=world.run,
            plan=world.plan,
            pairs=world.pairs,
            decisions=decision_set.by_job(),
            decision_set=decision_set.manifest,
            eligibility=None,
            pair_manifest_hash=world.pair_manifest_hash,
            non_mated_finger_shift=1,
        )


def test_view_policy_id_and_metadata_are_exact(world):
    from dataclasses import replace

    decision_set, eligibility = _chain(world)
    unconditional, _, _ = _views(world, decision_set, eligibility)
    common = {
        "entries": unconditional.entries,
        "run": world.run,
        "plan": world.plan,
        "pairs": world.pairs,
        "decisions": decision_set.by_job(),
        "decision_set": decision_set.manifest,
        "eligibility": None,
        "pair_manifest_hash": world.pair_manifest_hash,
        "non_mated_finger_shift": 1,
    }
    with pytest.raises(EvaluationViewIntegrityError, match="policy id"):
        verify_evaluation_view(
            manifest=replace(unconditional.manifest, policy_id="forged_policy"),
            **common,
        )
    with pytest.raises(EvaluationViewIntegrityError, match="policy metadata"):
        verify_evaluation_view(
            manifest=replace(
                unconditional.manifest,
                policy_metadata={**unconditional.manifest.policy_metadata, "extra": "1"},
            ),
            **common,
        )


def test_non_mated_finger_shift_is_verified_against_protocol_config(world):
    decision_set, eligibility = _chain(world)
    _, _, non_mated = _views(world, decision_set, eligibility)
    with pytest.raises(EvaluationViewIntegrityError, match="policy metadata"):
        verify_evaluation_view(
            manifest=non_mated.manifest,
            entries=non_mated.entries,
            run=world.run,
            plan=world.plan,
            pairs=world.pairs,
            decisions=decision_set.by_job(),
            decision_set=decision_set.manifest,
            eligibility=None,
            pair_manifest_hash=world.pair_manifest_hash,
            non_mated_finger_shift=2,
        )


def test_view_run_fingerprint_is_load_bearing(world):
    from dataclasses import replace

    decision_set, eligibility = _chain(world)
    unconditional, _, _ = _views(world, decision_set, eligibility)
    with pytest.raises(EvaluationViewIntegrityError, match="run fingerprint"):
        verify_evaluation_view(
            manifest=replace(unconditional.manifest, run_fingerprint="f" * 64),
            entries=unconditional.entries,
            run=world.run,
            plan=world.plan,
            pairs=world.pairs,
            decisions=decision_set.by_job(),
            decision_set=decision_set.manifest,
            eligibility=None,
            pair_manifest_hash=world.pair_manifest_hash,
            non_mated_finger_shift=1,
        )


def test_store_rejects_a_manifest_in_another_view_kinds_directory(world):
    from fpbench.core.serialization import write_json
    from fpbench.storage.evaluation_view_store import EvaluationViewStore

    decision_set, eligibility = _chain(world)
    unconditional, _, non_mated = _views(world, decision_set, eligibility)
    store = EvaluationViewStore(world.workspace)
    path = store.manifest_path(
        world.run.run_id,
        decision_set.manifest.decision_set_id,
        unconditional.manifest.view_kind,
    )
    write_json(path, non_mated.manifest)
    with pytest.raises(StorageError, match="does not match its"):
        store.read_manifest(
            world.run.run_id,
            decision_set.manifest.decision_set_id,
            unconditional.manifest.view_kind,
        )
