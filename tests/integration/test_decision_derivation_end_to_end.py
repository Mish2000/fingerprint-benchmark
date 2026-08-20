"""The whole 5A chain over scores chosen so that every answer is known in advance.

    PLAIN SELF   50      ROLL SELF   45      mated   42      non-mated   10

Against a threshold of 40 that makes every SELF comparison a match, every unit
eligible, every mated comparison a match and every impostor comparison a
non-match — so every assertion below is an exact expected value rather than a
property. A second world moves one score at a time to check that the chain
reacts the way the protocol says it should.

Then the tampering half: after finalisation, change one thing — a decision, a
verdict, an inclusion flag, a receipt field, the marker — and the status must
fall to ``INVALID``. A chain that survived any of those would be a chain nobody
should cite (docs/adr/0022).
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from fpbench.core.enums import (
    DecisionDerivationStatus,
    DecisionValue,
    ProtocolStage,
    ResearchRunStatus,
    SelfEligibilityStatus,
)
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
)
from fpbench.core.json_io import write_json
from fpbench.storage.decision_set_store import DecisionSetStore
from decisionworld import (
    DEFAULT_SCORES,
    build_decision_world,
    derivation_definition_for,
    derive_full_chain,
    extraction_failure,
    inspect_chain,
)

pytestmark = pytest.mark.decisions


@pytest.fixture(scope="module")
def finalised(tmp_path_factory):
    """One derivation, finalised, shared by the read-only assertions below."""
    root = tmp_path_factory.mktemp("derivation_e2e")
    world = build_decision_world(root, subjects=3, fingers=2)
    chain = derive_full_chain(world, finalize=True)
    return chain


# --------------------------------------------------------------- the chain


def test_every_comparison_got_exactly_one_decision(finalised):
    world = finalised.world
    manifest = finalised.decision_set.manifest
    assert manifest.total_decisions == world.plan.total_jobs
    assert manifest.decided_count == world.plan.total_jobs
    assert manifest.undecidable_count == 0


def test_the_decisions_are_the_ones_the_scores_imply(finalised):
    by_pair = {r.pair_id: r for r in finalised.decision_set.records}
    for pair in finalised.world.run_world.pairs:
        record = by_pair[str(pair.pair_id)]
        score = DEFAULT_SCORES[pair.protocol_stage]
        expected = DecisionValue.MATCH if score >= 40 else DecisionValue.NON_MATCH
        assert record.decision is expected


def test_every_unit_is_eligible_under_this_script(finalised):
    records = finalised.eligibility.records
    assert len(records) == len(finalised.world.units)
    assert all(record.status is SelfEligibilityStatus.ELIGIBLE for record in records)


def test_the_three_views_cover_the_right_comparisons(finalised):
    world = finalised.world
    mated = sum(
        1
        for pair in world.run_world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_MATED
    )
    impostors = sum(
        1
        for pair in world.run_world.pairs
        if pair.protocol_stage is ProtocolStage.PLAIN_ROLL_NON_MATED
    )
    assert finalised.views[MATED_UNCONDITIONAL_VIEW].manifest.total_rows == mated
    assert finalised.views[MATED_CONDITIONAL_VIEW].manifest.total_rows == mated
    assert finalised.views[NON_MATED_SANITY_VIEW].manifest.total_rows == impostors


def test_all_mated_pairs_are_included_in_the_conditional_view(finalised):
    conditional = finalised.views[MATED_CONDITIONAL_VIEW]
    assert conditional.included_count == conditional.manifest.total_rows


def test_the_chain_reaches_decision_ready(finalised):
    state = inspect_chain(finalised.world, finalised.decision_set_id)
    assert state.status is DecisionDerivationStatus.DECISION_READY, list(state.issues)
    assert state.decision_set_valid
    assert state.eligibility_valid
    assert state.views_valid == 3
    assert state.receipt_valid
    assert state.finalization_valid


def test_deriving_again_changes_nothing(finalised):
    """Same scores, same profile, same code: same ids, no rewrite."""
    again = derive_full_chain(finalised.world, finalize=True)
    assert again.decision_set_id == finalised.decision_set_id
    assert (
        again.eligibility.manifest.eligibility_set_id
        == finalised.eligibility.manifest.eligibility_set_id
    )
    assert again.receipt.decision_set_id == finalised.receipt.decision_set_id


# ------------------------------------------------------------- the receipt


def test_the_receipt_names_every_link(finalised):
    receipt = finalised.receipt
    assert receipt.run_id == finalised.world.run.run_id
    assert (
        receipt.decision_set_fingerprint
        == finalised.decision_set.manifest.decision_set_fingerprint
    )
    assert (
        receipt.eligibility_set_fingerprint
        == finalised.eligibility.manifest.eligibility_set_fingerprint
    )
    assert set(receipt.view_total_rows) == {
        MATED_UNCONDITIONAL_VIEW,
        MATED_CONDITIONAL_VIEW,
        NON_MATED_SANITY_VIEW,
    }


def test_the_receipt_carries_no_outcome_and_no_score(finalised):
    store = DecisionSetStore(finalised.world.workspace)
    path = store.receipt_path(finalised.world.run.run_id, finalised.decision_set_id)
    text = path.read_text(encoding="utf-8").lower()
    for forbidden in (
        "raw_score",
        "match_count",
        "eligible_count",
        "included_count",
        "threshold",
        "fmr",
        "fnmr",
        "eer",
        "accuracy",
        "subject_id",
    ):
        assert forbidden not in text, forbidden


def test_the_receipt_carries_no_path(finalised):
    store = DecisionSetStore(finalised.world.workspace)
    path = store.receipt_path(finalised.world.run.run_id, finalised.decision_set_id)
    text = path.read_text(encoding="utf-8")
    assert str(finalised.world.workspace) not in text


def test_the_receipt_says_it_carries_no_metric(finalised):
    assert "no biometric performance metric or conclusion" in finalised.receipt.statement


# ------------------------------------------------------ the interesting cases


def test_a_finger_that_fails_roll_self_is_excluded_but_not_deleted(tmp_path):
    targets: list[str] = []

    def score_for(pair):
        if pair.protocol_stage is ProtocolStage.ROLL_SELF and not targets:
            targets.append(str(pair.pair_id))
        if (
            pair.protocol_stage is ProtocolStage.ROLL_SELF
            and str(pair.pair_id) == targets[0]
        ):
            return 3.0
        return DEFAULT_SCORES[pair.protocol_stage]

    world = build_decision_world(tmp_path, score_for=score_for)
    chain = derive_full_chain(world, finalize=True)

    conditional = chain.views[MATED_CONDITIONAL_VIEW]
    unconditional = chain.views[MATED_UNCONDITIONAL_VIEW]

    assert conditional.manifest.total_rows == unconditional.manifest.total_rows
    assert conditional.included_count == conditional.manifest.total_rows - 1
    assert unconditional.included_count == unconditional.manifest.total_rows

    state = inspect_chain(world, chain.decision_set_id)
    assert state.status is DecisionDerivationStatus.DECISION_READY


def test_a_failed_self_comparison_produces_an_undecidable_and_an_undetermined(
    tmp_path,
):
    seen: list[str] = []

    def failure_for(pair):
        if pair.protocol_stage is ProtocolStage.ROLL_SELF and not seen:
            seen.append(str(pair.pair_id))
            return extraction_failure()
        return None

    world = build_decision_world(tmp_path, failure_for=failure_for)
    chain = derive_full_chain(world, finalize=True)

    assert chain.decision_set.manifest.undecidable_count == 1
    undetermined = [
        r
        for r in chain.eligibility.records
        if r.status is SelfEligibilityStatus.UNDETERMINED
    ]
    assert len(undetermined) == 1
    assert inspect_chain(world, chain.decision_set_id).status is (
        DecisionDerivationStatus.DECISION_READY
    )


# -------------------------------------------------------------- tampering


@pytest.fixture
def tamperable(tmp_path):
    world = build_decision_world(tmp_path, subjects=2, fingers=2)
    chain = derive_full_chain(world, finalize=True)
    assert inspect_chain(world, chain.decision_set_id).status is (
        DecisionDerivationStatus.DECISION_READY
    )
    return chain


def _store(chain) -> DecisionSetStore:
    return DecisionSetStore(chain.world.workspace)


def _inspect_with_definition(chain, definition):
    from fpbench.derivations import inspect_decision_derivation

    world = chain.world
    return inspect_decision_derivation(
        run=world.run,
        plan=world.plan,
        pairs=world.pairs,
        units=world.units,
        result_set=world.result_set,
        result_set_entries=world.result_set_entries,
        result_store=world.result_store,
        research_status=ResearchRunStatus.RESEARCH_READY,
        decision_profile=world.profile,
        definition=definition,
        decision_set_id=chain.decision_set_id,
        pair_manifest_hash=world.pair_manifest_hash,
        non_mated_finger_shift=1,
        workspace=world.workspace,
    )


def test_editing_a_decision_invalidates_the_chain(tamperable):
    import pyarrow.parquet as pq

    from fpbench.storage.derivation_schemas import (
        decisions_to_table,
        table_to_decisions,
    )

    store = _store(tamperable)
    path = store.records_path(
        tamperable.world.run.run_id, tamperable.decision_set_id
    )
    records = table_to_decisions(pq.read_table(path))

    # Rewrite one row's decision without touching its hash: the record's own
    # invariant is bypassed by going through the table.
    rows = decisions_to_table(records).to_pylist()
    rows[0]["decision"] = (
        "non_match" if rows[0]["decision"] == "match" else "match"
    )
    import pyarrow as pa

    from fpbench.storage.derivation_schemas import DECISION_RECORD_SCHEMA

    table = pa.table(
        {f.name: [row[f.name] for row in rows] for f in DECISION_RECORD_SCHEMA},
        schema=DECISION_RECORD_SCHEMA,
    )
    pq.write_table(table, path, compression="zstd")

    state = inspect_chain(tamperable.world, tamperable.decision_set_id)
    assert state.status is DecisionDerivationStatus.INVALID


def test_editing_the_profile_threshold_invalidates_the_chain(tamperable):
    store = _store(tamperable)
    path = store.profile_path(
        tamperable.world.run.run_id, tamperable.decision_set_id
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["threshold"] = "41"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    state = inspect_chain(tamperable.world, tamperable.decision_set_id)
    assert state.status is DecisionDerivationStatus.INVALID


def test_editing_an_eligibility_verdict_invalidates_the_chain(tamperable):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from fpbench.storage.derivation_schemas import ELIGIBILITY_RECORD_SCHEMA
    from fpbench.storage.eligibility_set_store import EligibilitySetStore

    store = EligibilitySetStore(tamperable.world.workspace)
    path = store.entries_path(
        tamperable.world.run.run_id, tamperable.decision_set_id
    )
    rows = pq.read_table(path).to_pylist()
    rows[0]["status"] = "ineligible"
    rows[0]["reasons"] = ["plain_self_non_match"]
    table = pa.table(
        {f.name: [row[f.name] for row in rows] for f in ELIGIBILITY_RECORD_SCHEMA},
        schema=ELIGIBILITY_RECORD_SCHEMA,
    )
    pq.write_table(table, path, compression="zstd")

    state = inspect_chain(tamperable.world, tamperable.decision_set_id)
    assert state.status is DecisionDerivationStatus.INVALID


def test_editing_an_inclusion_flag_invalidates_the_chain(tamperable):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from fpbench.storage.derivation_schemas import EVALUATION_VIEW_ENTRY_SCHEMA
    from fpbench.storage.evaluation_view_store import EvaluationViewStore

    store = EvaluationViewStore(tamperable.world.workspace)
    path = store.entries_path(
        tamperable.world.run.run_id,
        tamperable.decision_set_id,
        MATED_CONDITIONAL_VIEW,
    )
    rows = pq.read_table(path).to_pylist()
    rows[0]["included"] = False
    rows[0]["exclusion_reason"] = "self_ineligible"
    table = pa.table(
        {f.name: [row[f.name] for row in rows] for f in EVALUATION_VIEW_ENTRY_SCHEMA},
        schema=EVALUATION_VIEW_ENTRY_SCHEMA,
    )
    pq.write_table(table, path, compression="zstd")

    state = inspect_chain(tamperable.world, tamperable.decision_set_id)
    assert state.status is DecisionDerivationStatus.INVALID


def test_editing_the_receipt_invalidates_the_chain(tamperable):
    store = _store(tamperable)
    path = store.receipt_path(
        tamperable.world.run.run_id, tamperable.decision_set_id
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["total_eligibility_units"] = payload["total_eligibility_units"] + 1
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    state = inspect_chain(tamperable.world, tamperable.decision_set_id)
    assert state.status is DecisionDerivationStatus.INVALID


def test_editing_the_finalization_marker_invalidates_the_chain(tamperable):
    store = _store(tamperable)
    path = store.finalization_path(
        tamperable.world.run.run_id, tamperable.decision_set_id
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["decision_set_fingerprint"] = "a" * 64
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    state = inspect_chain(tamperable.world, tamperable.decision_set_id)
    assert state.status is DecisionDerivationStatus.INVALID


def test_a_self_consistent_definition_for_another_commit_is_rejected(tamperable):
    from dataclasses import replace

    from runworld import research_provenance

    software = replace(research_provenance(), source_revision="b" * 40)
    definition = derivation_definition_for(tamperable.world, software=software)
    state = _inspect_with_definition(tamperable, definition)
    assert state.status is DecisionDerivationStatus.INVALID
    assert any("source commit" in issue for issue in state.issues)


@pytest.mark.parametrize(
    "field,value,issue",
    [
        ("run_id", "run_forged", "run id"),
        ("run_fingerprint", "b" * 64, "run fingerprint"),
        ("result_set_id", "resultset_forged", "result-set id"),
        ("result_set_fingerprint", "c" * 64, "result-set fingerprint"),
        ("decision_profile_id", "profile_forged", "decision-profile id"),
        (
            "decision_profile_fingerprint",
            "d" * 64,
            "decision-profile fingerprint",
        ),
    ],
)
def test_every_definition_source_claim_is_load_bearing(
    tamperable, field, value, issue
):
    from fpbench.core.derivation_models import (
        DerivationDefinition,
        derivation_definition_fingerprint,
    )
    from fpbench.core.serialization import to_plain

    payload = dict(to_plain(derivation_definition_for(tamperable.world)))
    payload[field] = value
    fingerprint = derivation_definition_fingerprint(payload)
    payload["definition_fingerprint"] = fingerprint
    payload["definition_id"] = f"derivation_{fingerprint[:12]}"
    definition = DerivationDefinition(**payload)

    state = _inspect_with_definition(tamperable, definition)
    assert state.status is DecisionDerivationStatus.INVALID
    assert any(issue in item for item in state.issues)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "999"),
        ("derivation_source_commit", "b" * 40),
        ("derivation_source_tree_clean", False),
    ],
)
def test_receipt_schema_and_source_claims_are_revalidated(
    tamperable, field, value
):
    store = _store(tamperable)
    path = store.receipt_path(
        tamperable.world.run.run_id, tamperable.decision_set_id
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    state = inspect_chain(tamperable.world, tamperable.decision_set_id)
    assert state.status is DecisionDerivationStatus.INVALID
    assert not state.receipt_valid


def test_a_rehashed_marker_for_another_commit_is_rejected(tamperable):
    from fpbench.core.derivation_models import derivation_finalization_fingerprint

    store = _store(tamperable)
    path = store.finalization_path(
        tamperable.world.run.run_id, tamperable.decision_set_id
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["derivation_source_commit"] = "b" * 40
    fingerprint = derivation_finalization_fingerprint(payload)
    payload["finalization_fingerprint"] = fingerprint
    payload["finalization_id"] = f"derivationfinal_{fingerprint[:12]}"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    state = inspect_chain(tamperable.world, tamperable.decision_set_id)
    assert state.status is DecisionDerivationStatus.INVALID
    assert state.receipt_valid
    assert not state.finalization_valid


def test_changing_a_raw_score_invalidates_the_chain(tamperable):
    """The scores are the foundation; nothing above them survives their moving."""
    job_id = tamperable.world.plan.job_ids()[0]
    tamperable.world.result_store.raw_result_path(
        tamperable.world.run.run_id, job_id
    ).unlink()

    state = inspect_chain(tamperable.world, tamperable.decision_set_id)
    assert state.status is DecisionDerivationStatus.INVALID


# ------------------------------------------------------- failure injection


def test_without_a_marker_the_chain_is_not_authoritative(tmp_path):
    """Everything present, nothing finalised: VIEWS_READY, not DECISION_READY."""
    world = build_decision_world(tmp_path)
    chain = derive_full_chain(world, finalize=False)
    state = inspect_chain(world, chain.decision_set_id)
    assert state.status is DecisionDerivationStatus.VIEWS_READY
    assert not state.finalization_present


@pytest.mark.parametrize(
    "stop_after", ["decisions", "eligibility", "views"]
)
def test_an_interrupted_derivation_is_retryable(tmp_path, stop_after):
    """Whatever was written stays; the next attempt reuses it and continues."""
    from fpbench.storage.eligibility_set_store import EligibilitySetStore
    from fpbench.storage.evaluation_view_store import EvaluationViewStore

    world = build_decision_world(tmp_path)
    chain = derive_full_chain(world, store=False)
    set_id = chain.decision_set_id

    DecisionSetStore(world.workspace).ensure_decision_set(
        profile=chain.decision_set.profile,
        manifest=chain.decision_set.manifest,
        records=chain.decision_set.records,
    )
    if stop_after in ("eligibility", "views"):
        EligibilitySetStore(world.workspace).ensure_eligibility_set(
            decision_set_id=set_id,
            manifest=chain.eligibility.manifest,
            records=chain.eligibility.records,
        )
    if stop_after == "views":
        for view in chain.views.values():
            EvaluationViewStore(world.workspace).ensure_view(
                run_id=world.run.run_id,
                decision_set_id=set_id,
                manifest=view.manifest,
                entries=view.entries,
            )

    partial = inspect_chain(world, set_id)
    assert partial.status is not DecisionDerivationStatus.DECISION_READY
    assert not partial.finalization_present

    # Retry from scratch: the identities are unchanged, so the existing files
    # are reused rather than conflicting.
    retried = derive_full_chain(world, finalize=True)
    assert retried.decision_set_id == set_id
    assert inspect_chain(world, set_id).status is (
        DecisionDerivationStatus.DECISION_READY
    )


def test_a_receipt_without_its_views_is_not_decision_ready(tmp_path):
    from fpbench.storage.evaluation_view_store import EvaluationViewStore

    world = build_decision_world(tmp_path)
    chain = derive_full_chain(world, finalize=True)

    view_path = EvaluationViewStore(world.workspace).manifest_path(
        world.run.run_id, chain.decision_set_id, NON_MATED_SANITY_VIEW
    )
    view_path.unlink()

    state = inspect_chain(world, chain.decision_set_id)
    assert state.status is DecisionDerivationStatus.INVALID
    assert state.views_valid == 2
