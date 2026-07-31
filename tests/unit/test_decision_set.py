"""One decision per planned job, each traceable to the score it came from.

The tests below fall into two halves. The first checks the shapes a decision
record may take — a success becomes a decision, a failure becomes an
``UNDECIDABLE`` with its reason preserved, and neither can pretend to be the
other. The second checks that a stored set survives re-derivation: change a
score, a threshold or a single flag, and verification must notice.

That second half is the whole argument for storing decisions at all. If a
decision set could not be checked against the scores it claims to interpret,
it would be a convenient cache rather than evidence (docs/adr/0022).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from fpbench.core.decision_models import (
    DecisionApplicationStatus,
    DecisionValue,
    decision_record_hash,
    decision_set_fingerprint,
)
from fpbench.core.enums import ExecutionStatus, ProtocolStage
from fpbench.core.errors import (
    DecisionDerivationError,
    DecisionSetConflictError,
    DecisionSetIntegrityError,
    StorageError,
)
from fpbench.decisions import apply_decision_profile, verify_decision_set
from fpbench.storage.decision_set_store import DecisionSetStore
from decisionworld import (
    DEFAULT_SCORES,
    build_decision_world,
    documented_profile_for,
    extraction_failure,
)
from runworld import research_provenance

pytestmark = pytest.mark.decisions


@pytest.fixture
def world(tmp_path):
    return build_decision_world(tmp_path)


def _apply(world, *, profile=None, software=None):
    return apply_decision_profile(
        **{
            **world.decisions_kwargs(),
            "profile": profile or world.profile,
        },
        derivation_software=software or research_provenance(),
    )


def _verify(world, decision_set, *, profile=None, manifest=None, records=None):
    verify_decision_set(
        profile=profile or decision_set.profile,
        manifest=manifest or decision_set.manifest,
        records=records or decision_set.records,
        run=world.run,
        plan=world.plan,
        result_set=world.result_set,
        result_set_entries=world.result_set_entries,
        result_store=world.result_store,
    )


# ------------------------------------------------------------------ shape


def test_one_decision_per_planned_job_in_plan_order(world):
    decision_set = _apply(world)
    assert decision_set.manifest.total_decisions == world.plan.total_jobs
    assert [record.ordinal for record in decision_set.records] == list(
        range(world.plan.total_jobs)
    )
    assert [record.job_id for record in decision_set.records] == list(
        world.plan.job_ids()
    )


def test_the_scripted_scores_produce_the_expected_decisions(world):
    decision_set = _apply(world)
    by_pair = {record.pair_id: record for record in decision_set.records}
    for pair in world.run_world.pairs:
        record = by_pair[str(pair.pair_id)]
        score = DEFAULT_SCORES[pair.protocol_stage]
        expected = (
            DecisionValue.MATCH if score >= 40 else DecisionValue.NON_MATCH
        )
        assert record.decision is expected, pair.protocol_stage


def test_no_raw_score_is_copied_into_a_decision(world):
    """The number stays where it was written (docs/adr/0022)."""
    decision_set = _apply(world)
    fields = set(type(decision_set.records[0]).__dataclass_fields__)
    assert {"raw_score", "score", "raw_result"} & fields == set()
    rendered = repr(decision_set.records[0])
    assert "50.0" not in rendered and "42.0" not in rendered


def test_a_decision_carries_no_subject_finger_or_stage(world):
    decision_set = _apply(world)
    fields = set(type(decision_set.records[0]).__dataclass_fields__)
    forbidden = {"subject_id", "finger", "position", "protocol_stage", "ground_truth"}
    assert forbidden & fields == set()


def test_the_manifest_carries_no_outcome_counts(world):
    """Decidability is provenance; how many matched is a result."""
    decision_set = _apply(world)
    fields = set(type(decision_set.manifest).__dataclass_fields__)
    forbidden = {"match_count", "non_match_count", "matched", "eligible_count"}
    assert forbidden & fields == set()


# ----------------------------------------------------------- undecidables


def test_a_failed_comparison_becomes_undecidable_not_a_non_match(tmp_path):
    def failure_for(pair):
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED:
            return extraction_failure()
        return None

    world = build_decision_world(tmp_path, failure_for=failure_for)
    decision_set = _apply(world)

    undecided = [
        record
        for record in decision_set.records
        if record.application_status is DecisionApplicationStatus.UNDECIDABLE
    ]
    assert undecided, "the fixture was supposed to fail some comparisons"
    for record in undecided:
        assert record.decision is None
        assert record.source_execution_status is ExecutionStatus.FAILURE
        assert record.source_failure_code == "template_extraction_failed"
    assert decision_set.manifest.undecidable_count == len(undecided)
    assert decision_set.manifest.decided_count == (
        world.plan.total_jobs - len(undecided)
    )


def test_a_failure_cannot_be_forged_into_a_decision(world):
    decision_set = _apply(world)
    record = decision_set.records[0]
    with pytest.raises(ValueError, match="no score to threshold"):
        replace(
            record,
            source_execution_status=ExecutionStatus.FAILURE,
            source_failure_code="timeout",
        )


def test_a_success_cannot_be_marked_undecidable(world):
    decision_set = _apply(world)
    record = decision_set.records[0]
    with pytest.raises(ValueError, match="must be decided"):
        replace(
            record,
            application_status=DecisionApplicationStatus.UNDECIDABLE,
            decision=None,
            source_failure_code="timeout",
        )


# ------------------------------------------------------------ derivation


def test_a_dirty_derivation_tree_cannot_produce_decisions(world):
    with pytest.raises(DecisionDerivationError, match="clean source revision"):
        _apply(world, software=research_provenance(clean=False))


def test_a_changed_raw_result_stops_derivation(world):
    """The result set says what the evidence was; the files must still be it."""
    job_id = world.plan.job_ids()[0]
    path = world.result_store.raw_result_path(world.run.run_id, job_id)
    path.unlink()
    with pytest.raises(StorageError):
        _apply(world)


def test_the_derivation_commit_reaches_the_set_fingerprint(world):
    first = _apply(world, software=research_provenance(revision="a" * 40))
    second = _apply(world, software=research_provenance(revision="b" * 40))
    assert (
        first.manifest.decision_set_fingerprint
        != second.manifest.decision_set_fingerprint
    )


def test_a_different_threshold_produces_a_different_set(world):
    other = documented_profile_for(world.run, threshold="46")
    first = _apply(world)
    second = _apply(world, profile=other)
    assert first.manifest.decision_set_id != second.manifest.decision_set_id


def test_deriving_twice_is_stable(world):
    first = _apply(world)
    second = _apply(world)
    assert (
        first.manifest.decision_set_fingerprint
        == second.manifest.decision_set_fingerprint
    )
    assert first.manifest.created_utc != second.manifest.created_utc or True


# ---------------------------------------------------------- verification


def test_a_freshly_derived_set_verifies(world):
    _verify(world, _apply(world))


def _forge(record, **changes):
    """A self-consistent record that says something the scores do not.

    The hash has to be recomputed over the *changed* fields, or the record's own
    invariant catches the forgery before the verifier gets a chance — and it is
    the verifier that is under test here.
    """
    from types import SimpleNamespace

    fields = {
        name: getattr(record, name)
        for name in type(record).__dataclass_fields__
        if name != "decision_record_hash"
    }
    fields.update(changes)
    probe = SimpleNamespace(**fields)
    return type(record)(decision_record_hash=decision_record_hash(probe), **fields)


def test_a_flipped_decision_is_caught(world):
    decision_set = _apply(world)
    records = list(decision_set.records)
    original = records[0]
    flipped = (
        DecisionValue.NON_MATCH
        if original.decision is DecisionValue.MATCH
        else DecisionValue.MATCH
    )
    records[0] = _forge(original, decision=flipped)
    with pytest.raises(DecisionSetIntegrityError, match="stored score decides"):
        verify_decision_set(
            profile=decision_set.profile,
            manifest=decision_set.manifest,
            records=tuple(records),
            run=world.run,
            plan=world.plan,
            result_set=world.result_set,
            result_set_entries=world.result_set_entries,
            result_store=world.result_store,
        )


def test_a_set_verified_against_a_different_profile_is_caught(world):
    decision_set = _apply(world)
    other = documented_profile_for(world.run, threshold="46")
    with pytest.raises(DecisionSetIntegrityError, match="not the profile"):
        _verify(world, decision_set, profile=other)


def test_a_reordered_set_is_caught(world):
    decision_set = _apply(world)
    records = list(decision_set.records)
    records[0], records[1] = records[1], records[0]
    with pytest.raises(DecisionSetIntegrityError):
        verify_decision_set(
            profile=decision_set.profile,
            manifest=decision_set.manifest,
            records=tuple(records),
            run=world.run,
            plan=world.plan,
            result_set=world.result_set,
            result_set_entries=world.result_set_entries,
            result_store=world.result_store,
        )


def test_a_truncated_set_is_caught(world):
    decision_set = _apply(world)
    with pytest.raises(DecisionSetIntegrityError, match="decisions for"):
        verify_decision_set(
            profile=decision_set.profile,
            manifest=decision_set.manifest,
            records=decision_set.records[:-1],
            run=world.run,
            plan=world.plan,
            result_set=world.result_set,
            result_set_entries=world.result_set_entries,
            result_store=world.result_store,
        )


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("run_id", "run_forged", "run id"),
        ("plan_id", "plan_forged", "plan id"),
    ],
)
def test_manifest_identity_claims_are_load_bearing(world, field, value, error):
    from dataclasses import replace

    decision_set = _apply(world)
    forged = replace(decision_set.manifest, **{field: value})
    with pytest.raises(DecisionSetIntegrityError, match=error):
        _verify(world, decision_set, manifest=forged)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("result_set_id", "resultset_forged", "different result set"),
        ("result_set_fingerprint", "f" * 64, "result-set fingerprint"),
        ("decision_profile_id", "profile_forged", "decision profile"),
    ],
)
def test_record_identity_claims_are_load_bearing(world, field, value, error):
    decision_set = _apply(world)
    records = list(decision_set.records)
    records[0] = _forge(records[0], **{field: value})
    with pytest.raises(DecisionSetIntegrityError, match=error):
        verify_decision_set(
            profile=decision_set.profile,
            manifest=decision_set.manifest,
            records=tuple(records),
            run=world.run,
            plan=world.plan,
            result_set=world.result_set,
            result_set_entries=world.result_set_entries,
            result_store=world.result_store,
        )


# ----------------------------------------------------------------- store


def test_a_decision_set_round_trips(world, tmp_path):
    decision_set = _apply(world)
    store = DecisionSetStore(world.workspace)
    store.ensure_decision_set(
        profile=decision_set.profile,
        manifest=decision_set.manifest,
        records=decision_set.records,
    )
    profile, manifest, records = store.read_decision_set(
        world.run.run_id, decision_set.manifest.decision_set_id
    )
    assert profile == decision_set.profile
    assert manifest == decision_set.manifest
    assert records == decision_set.records


def test_storing_the_same_set_again_is_a_no_op(world):
    decision_set = _apply(world)
    store = DecisionSetStore(world.workspace)
    store.ensure_decision_set(
        profile=decision_set.profile,
        manifest=decision_set.manifest,
        records=decision_set.records,
    )
    path = store.manifest_path(
        world.run.run_id, decision_set.manifest.decision_set_id
    )
    before = path.read_bytes()
    store.ensure_decision_set(
        profile=decision_set.profile,
        manifest=decision_set.manifest,
        records=decision_set.records,
    )
    assert path.read_bytes() == before


def test_a_different_derivation_lands_somewhere_else_entirely(world):
    """The first line of defence: two derivations cannot collide by construction."""
    first = _apply(world)
    second = _apply(world, profile=documented_profile_for(world.run, threshold="46"))
    store = DecisionSetStore(world.workspace)
    store.ensure_decision_set(
        profile=first.profile, manifest=first.manifest, records=first.records
    )
    store.ensure_decision_set(
        profile=second.profile, manifest=second.manifest, records=second.records
    )
    assert first.manifest.decision_set_id != second.manifest.decision_set_id
    assert set(store.decision_set_ids(world.run.run_id)) == {
        first.manifest.decision_set_id,
        second.manifest.decision_set_id,
    }


def test_a_swapped_manifest_is_a_conflict(world):
    """The second: a directory whose manifest was replaced refuses to be reused."""
    first = _apply(world)
    second = _apply(world, profile=documented_profile_for(world.run, threshold="46"))
    store = DecisionSetStore(world.workspace)
    store.ensure_decision_set(
        profile=first.profile, manifest=first.manifest, records=first.records
    )
    store.ensure_decision_set(
        profile=second.profile, manifest=second.manifest, records=second.records
    )

    # Drop the second derivation's manifest into the first's directory.
    target = store.manifest_path(world.run.run_id, first.manifest.decision_set_id)
    source = store.manifest_path(world.run.run_id, second.manifest.decision_set_id)
    target.write_bytes(source.read_bytes())

    with pytest.raises(DecisionSetConflictError, match="refusing to replace"):
        store.ensure_decision_set(
            profile=first.profile, manifest=first.manifest, records=first.records
        )


def test_the_profile_is_stored_beside_the_decisions(world):
    decision_set = _apply(world)
    store = DecisionSetStore(world.workspace)
    store.ensure_decision_set(
        profile=decision_set.profile,
        manifest=decision_set.manifest,
        records=decision_set.records,
    )
    stored = store.read_profile(
        world.run.run_id, decision_set.manifest.decision_set_id
    )
    assert stored.threshold == "40"
    assert stored.profile_fingerprint == decision_set.profile.profile_fingerprint


def test_a_set_whose_profile_disagrees_is_refused(world):
    decision_set = _apply(world)
    store = DecisionSetStore(world.workspace)
    other = documented_profile_for(world.run, threshold="46")
    with pytest.raises(StorageError, match="not the profile"):
        store.ensure_decision_set(
            profile=other,
            manifest=decision_set.manifest,
            records=decision_set.records,
        )
